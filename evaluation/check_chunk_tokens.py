# check_chunk_tokens.py
# Verifies the claim behind D29: does any chunk exceed the embedding model's
# 256 word-piece limit, where it would be silently truncated?
#
# This is the only place the real tokenizer is used outside production, and it
# exists because the chunker's character fallback (MAX_CHUNK_CHARS) is an
# estimate. This script says whether that estimate is safe on real documents.
#
#   python evaluation/check_chunk_tokens.py

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src" / "rag"))

from chunking import MAX_CHUNK_CHARS, MAX_CHUNK_TOKENS, chunk_document  # noqa: E402

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
SAMPLES = Path("data/sample_docs")


def make_counter():
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(EMBEDDING_MODEL)
    return lambda s: len(tok.encode(s, add_special_tokens=True))


def report(name, text, counter):
    print(f"\n=== {name}")
    for label, kwargs in (("char fallback", {}), ("real tokenizer", {"token_counter": counter})):
        chunks, strategy = chunk_document(text, **kwargs)
        counts = [counter(c) for c in chunks]
        over = [c for c, n in zip(chunks, counts) if n > MAX_CHUNK_TOKENS]
        print(f"  {label:15s} strategy={strategy:20s} chunks={len(chunks):3d} "
              f"max_tokens={max(counts):4d} over_limit={len(over)}")
        for c in over:
            print(f"      TRUNCATED: {len(c)} chars, {counter(c)} tokens: {c[:60]!r}")
    # the ratio that justifies MAX_CHUNK_CHARS
    chunks, _ = chunk_document(text, token_counter=counter)
    ratios = [len(c) / counter(c) for c in chunks if counter(c) > 20]
    if ratios:
        worst = min(ratios)
        print(f"  chars per token: worst observed {worst:.2f} "
              f"=> {MAX_CHUNK_TOKENS} tokens is about {MAX_CHUNK_TOKENS * worst:.0f} chars")
        verdict = "SAFE" if MAX_CHUNK_CHARS <= MAX_CHUNK_TOKENS * worst else "TOO HIGH"
        print(f"  MAX_CHUNK_CHARS = {MAX_CHUNK_CHARS} -> {verdict}")


if __name__ == "__main__":
    counter = make_counter()
    for path in sorted(SAMPLES.glob("*.txt")):
        report(path.name, path.read_text(encoding="utf-8"), counter)
