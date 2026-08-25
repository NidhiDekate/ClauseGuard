# eval_retrieval.py
# measures whether retrieval actually finds the right clause, which nothing in
# this repo did before. the existing evaluation scores the classifier: given a
# clause, is the label right. that tests the half of the system that was not
# failing. both confirmed live failures were retrieval - the correct clause sat
# at rank 3 while the pipeline read rank 1.
#
# no api calls. the chunks are whole clauses and the ideal answer is a clause
# from the same document, so "did the top k contain it" is a direct text
# comparison. an llm judge would add cost and non-determinism and nothing else.
# the judge is for faithfulness and answer relevancy, where there is a real
# paraphrasing gap. not here.
#
# usage: python evaluation/eval_retrieval.py
#        python evaluation/eval_retrieval.py --k 10 --strategy by_clause

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src" / "rag"))

from chunking import chunk_by_clause, chunk_fixed_size  # noqa: E402
from tokenizer_util import token_counter  # noqa: E402


def chunk_by_clause_like_production(text):
    """The eval must chunk the way production chunks, or it measures a
    different system. retriever.py splits against the embedding model's real
    256-token limit, so this does too."""
    return chunk_by_clause(text, token_counter=token_counter())
from langchain_chroma import Chroma  # noqa: E402
from langchain_huggingface import HuggingFaceEmbeddings  # noqa: E402

TEST_SET_PATH = Path("evaluation/datasets/retrieval_test_set.json")
REPORT_DIR = Path("evaluation/reports")

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# how much of the ideal snippet has to appear in a chunk to call it a match.
# 0.8 rather than 1.0 because the snippet is copied from the document by hand
# and small differences in whitespace or a trailing clause creep in.
TEXT_MATCH_THRESHOLD = 0.8

# report recall at these depths. the system currently uses k=2 and reads only
# rank 1, so the gap between @1 and @2 is answers being thrown away and the gap
# between @2 and @10 is answers never fetched.
RECALL_DEPTHS = (1, 2, 3, 5, 10)

STRATEGIES = {
    "by_clause": chunk_by_clause_like_production,
    "fixed_size": chunk_fixed_size,
}


def leading_ref(chunk):
    """The section number a clause chunk starts with, or None.

    Only works for clause-boundary chunking, where the split deliberately keeps
    the numbering attached. Exact match on the captured group, not a prefix
    test, because 'XXXI' is a prefix of both 'XXXII' and 'XXXIII'.
    """
    match = re.match(r"^([IVXLCDM]+|[0-9]+)\.", chunk.strip())
    return match.group(1) if match else None


def words(text):
    return set(re.sub(r"\W+", " ", text.lower()).split())


def contains_snippet(chunk, snippet):
    """What fraction of the snippet's words appear in this chunk.

    Containment rather than similarity: a long chunk that fully contains a short
    snippet should score 1.0, which a symmetric measure like Jaccard would not
    give. This is what makes the metric work across chunking strategies, where
    chunk boundaries and sizes differ completely.
    """
    snippet_words = words(snippet)
    if not snippet_words:
        return 0.0
    return len(snippet_words & words(chunk)) / len(snippet_words)


def find_rank(chunks, case):
    """1-based rank of the first chunk that is the required clause, else None."""
    for position, chunk in enumerate(chunks, start=1):
        if case["must_find_ref"] and leading_ref(chunk) == case["must_find_ref"]:
            return position, "ref"
        if case["must_find_snippet"] and contains_snippet(chunk, case["must_find_snippet"]) >= TEXT_MATCH_THRESHOLD:
            return position, "text"
    return None, None


def build_store(document_text, strategy, name):
    chunks = STRATEGIES[strategy](document_text)
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    store = Chroma.from_texts(texts=chunks, embedding=embeddings, collection_name=name)
    return store, len(chunks)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=max(RECALL_DEPTHS),
                        help="how deep to retrieve. recall is reported at every depth up to this.")
    parser.add_argument("--strategy", choices=sorted(STRATEGIES), default="by_clause")
    args = parser.parse_args()

    data = json.loads(TEST_SET_PATH.read_text(encoding="utf-8"))
    cases = data["cases"]

    # one store per document, reused across that document's categories. building
    # it per case would re-embed the same document eight times.
    documents = {}
    for case in cases:
        documents.setdefault(case["doc_id"], case["document_path"])

    stores = {}
    print(f"strategy: {args.strategy}   retrieving k={args.k}\n")
    for doc_id, path in documents.items():
        text = Path(path).read_text(encoding="utf-8")
        store, n_chunks = build_store(text, args.strategy, f"eval_{args.strategy}_{doc_id}")
        stores[doc_id] = store
        print(f"  indexed {doc_id}: {n_chunks} chunks")
    print()

    results = []
    for case in cases:
        retrieved = [
            d.page_content
            for d in stores[case["doc_id"]].similarity_search(case["category"], k=args.k)
        ]
        retrieved_refs = [leading_ref(c) for c in retrieved]

        if case["expected"] == "absent":
            # nothing to find, so no recall to compute. recorded because these are
            # exactly the inputs the Reviewer has to reject, and that is E2's job.
            results.append({
                "doc_id": case["doc_id"],
                "category": case["category"],
                "expected": "absent",
                "rank": None,
                "matched_by": None,
                "retrieved_refs": retrieved_refs,
            })
            continue

        rank, matched_by = find_rank(retrieved, case)
        results.append({
            "doc_id": case["doc_id"],
            "category": case["category"],
            "expected": "present",
            "must_find_ref": case["must_find_ref"],
            "rank": rank,
            "matched_by": matched_by,
            "retrieved_refs": retrieved_refs,
        })

    scorable = [r for r in results if r["expected"] == "present"]
    total = len(scorable)

    print(f"{'document':<16} {'category':<44} {'want':<7} rank")
    print("-" * 80)
    for r in results:
        if r["expected"] == "absent":
            print(f"{r['doc_id']:<16} {r['category']:<44} {'absent':<7} n/a  (top: {r['retrieved_refs'][0]})")
            continue
        rank = r["rank"]
        shown = str(rank) if rank else f"NOT IN TOP {args.k}"
        flag = "" if rank == 1 else "   <-- not rank 1"
        print(f"{r['doc_id']:<16} {r['category']:<44} {r['must_find_ref']:<7} {shown}{flag}")

    print()
    print(f"recall over {total} cases where an answer exists:")
    recall = {}
    for depth in RECALL_DEPTHS:
        if depth > args.k:
            continue
        hits = sum(1 for r in scorable if r["rank"] and r["rank"] <= depth)
        recall[depth] = hits / total if total else 0.0
        marker = "   <-- what the pipeline currently fetches" if depth == 2 else ""
        marker = "   <-- what the pipeline currently reads" if depth == 1 else marker
        print(f"  recall@{depth:<3} {hits}/{total}  {recall[depth]:.1%}{marker}")

    missed = [r for r in scorable if not r["rank"]]
    if missed:
        print(f"\nnot found at any depth up to {args.k}:")
        for r in missed:
            print(f"  {r['doc_id']} / {r['category']} (wanted {r['must_find_ref']})")

    # one report per strategy. a single shared path meant the second run silently
    # overwrote the first, so whichever strategy ran last was the only one on disk.
    report_path = REPORT_DIR / f"retrieval_eval_{args.strategy}.json"
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({
        "strategy": args.strategy,
        "k": args.k,
        "embedding_model": EMBEDDING_MODEL,
        "cases_scored": total,
        "recall": {str(d): v for d, v in recall.items()},
        "per_case": results,
    }, indent=2), encoding="utf-8")
    print(f"\nsaved to {report_path}")


if __name__ == "__main__":
    main()
