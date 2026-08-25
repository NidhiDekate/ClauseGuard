# chunking_baselines.py
# Honest baselines for the chunking comparison (D30, D40).
#
# Phase 4 compared clause-boundary chunking against naive fixed-size character
# slicing, on three questions, one document, judged by eye, by the person who
# expected clause chunking to win. Fixed-size cuts mid-word and mid-sentence. It
# is not a baseline, it is a strawman: any structure-aware method beats it, so
# beating it establishes almost nothing.
#
# These are the two comparisons that actually test the claim.
#
# recursive  what most production RAG systems use. Tries paragraph breaks first,
#            then line breaks, then sentences, then words, then characters, so it
#            respects natural boundaries without knowing anything about leases.
#            This is the baseline to beat.
#
# semantic   split where meaning changes rather than where the formatting does.
#            Embed each sentence, walk the document, and cut where the similarity
#            between neighbouring sentences drops. Usually expensive; cheap here,
#            because the documents are 7-20k characters and the embedding model
#            runs locally for free.

import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src" / "rag"))

CHUNK_CHARS = 700   # matches MAX_CHUNK_CHARS so size is not the variable under test
CHUNK_OVERLAP = 80


def chunk_recursive(text):
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_CHARS,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return [c.strip() for c in splitter.split_text(text) if c.strip()]


def _sentences(text):
    parts = re.split(r"(?<=[.;:])\s+(?=[A-Z(\"'])|\n{2,}", text)
    return [p.strip() for p in parts if p and p.strip()]


def chunk_semantic(text, percentile=80):
    """Cut where consecutive sentences stop being about the same thing.

    The threshold is a percentile of the observed distance distribution rather
    than a fixed number, because absolute cosine distances vary by document and
    a fixed cut point would silently mean something different on each one.
    """
    import numpy as np
    from tokenizer_util import EMBEDDING_MODEL
    from langchain_huggingface import HuggingFaceEmbeddings

    sentences = _sentences(text)
    if len(sentences) < 3:
        return [text.strip()] if text.strip() else []

    embedder = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    vectors = np.array(embedder.embed_documents(sentences))
    vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    distances = 1 - np.sum(vectors[:-1] * vectors[1:], axis=1)

    cut_at = np.percentile(distances, percentile)
    breaks = [i + 1 for i, d in enumerate(distances) if d > cut_at]

    chunks, start = [], 0
    for b in breaks + [len(sentences)]:
        piece = " ".join(sentences[start:b]).strip()
        if piece:
            chunks.append(piece)
        start = b

    # semantic splitting has no size ceiling of its own, so a long stretch of
    # similar sentences becomes one oversized chunk and gets truncated at
    # embedding time. Same failure as D29, so apply the same fix.
    from chunking import chunk_document
    out = []
    for c in chunks:
        out.extend(chunk_document(c, drop_non_clause=False)[0] if len(c) > CHUNK_CHARS else [c])
    return out
