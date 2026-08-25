# eval_reviewer.py
# E2. The Reviewer is an LLM-as-a-judge. Nobody had ever measured it.
#
# It is handed a concern category and the k clauses retrieval returned, and it
# picks the one that actually answers the category, or none. Every finding the
# user sees passed through it, and its precision and recall were unknown.
#
# WHY THIS SET IS THE RIGHT ONE TO USE
#
# The retrieval golden set already contains what a judge eval needs:
#   must_find_ref      the clause that IS the answer
#   also_relevant_refs clauses that are on topic and are NOT the answer
#   4 absent cases     categories the document genuinely does not address
#
# The also_relevant_refs are the point. The Reviewer was rebuilt from a yes/no
# gate into a chooser because "guest and occupancy restrictions" retrieved
# III. OCCUPANT(S) first, and III genuinely is about occupancy, so a strict
# relevance gate approves it and stops. The question is not "can it spot
# irrelevance" but "can it tell relevant from most relevant".
#
# AND THE REVIEWER IS ISOLATED HERE. E1 measured retrieval recall@3 at 100%, so
# the right clause is always among the candidates. Any miss below is the
# Reviewer's, not retrieval's. That is what makes this a judge eval rather than
# a pipeline eval.
#
#   python evaluation/eval_reviewer.py

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "src"))
sys.path.append(str(ROOT / "src" / "rag"))
sys.path.append(str(ROOT / "src" / "agents"))
sys.path.append(str(Path(__file__).resolve().parent))

from dotenv import load_dotenv  # noqa: E402
load_dotenv()

from eval_retrieval import (  # noqa: E402
    chunk_by_clause_like_production, leading_ref, contains_snippet, TEXT_MATCH_THRESHOLD,
)
from reviewer import select_best_clause  # noqa: E402

TEST_SET = Path("evaluation/datasets/retrieval_test_set.json")
REPORT = Path("evaluation/reports/reviewer_eval.json")
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def build_store(text, name):
    from langchain_chroma import Chroma
    from langchain_huggingface import HuggingFaceEmbeddings
    chunks = chunk_by_clause_like_production(text)
    store = Chroma.from_texts(
        texts=chunks,
        embedding=HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL),
        collection_name=name,
    )
    return store


def identify(chunk, case):
    """What is this chunk, relative to the case? the answer, a distractor, or other."""
    ref = leading_ref(chunk)
    if case.get("must_find_ref") and ref == case["must_find_ref"]:
        return "answer"
    if case.get("must_find_snippet") and \
            contains_snippet(chunk, case["must_find_snippet"]) >= TEXT_MATCH_THRESHOLD:
        return "answer"
    if ref and ref in (case.get("also_relevant_refs") or []):
        return "distractor"
    return "other"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=3, help="candidates shown to the Reviewer")
    parser.add_argument("--pause", type=float, default=1.0)
    parser.add_argument("--repeat", type=int, default=1,
                        help="run N times. LLM judges are not deterministic either.")
    args = parser.parse_args()

    data = json.loads(TEST_SET.read_text(encoding="utf-8"))
    cases = data["cases"]

    stores = {}
    for case in cases:
        if case["doc_id"] not in stores:
            text = Path(case["document_path"]).read_text(encoding="utf-8")
            stores[case["doc_id"]] = build_store(text, f"e2_{case['doc_id']}")
            print(f"  indexed {case['doc_id']}")
    print()

    all_runs = []
    for attempt in range(args.repeat):
        if args.repeat > 1:
            print(f"--- run {attempt + 1} of {args.repeat} ---")
        rows = []
        print(f"{'document':<16}{'category':<44}{'want':<8}{'picked':<10}verdict")
        print("-" * 96)
        for case in cases:
            candidates = [d.page_content for d in
                          stores[case["doc_id"]].similarity_search(case["category"], k=args.k)]
            kinds = [identify(c, case) for c in candidates]
            answer_available = "answer" in kinds

            time.sleep(args.pause)
            try:
                result = select_best_clause(case["category"], candidates)
            except Exception as e:
                print(f"{case['doc_id']:<16}{case['category'][:42]:<44}{'':<8}{'':<10}"
                      f"ERROR {type(e).__name__}")
                rows.append({"doc_id": case["doc_id"], "category": case["category"],
                             "error": f"{type(e).__name__}: {e}"})
                continue

            idx = result.get("index")
            picked = kinds[idx] if isinstance(idx, int) and 0 <= idx < len(kinds) else "none"
            absent = case["expected"] == "absent"

            if absent:
                correct = idx is None
                verdict = "correct" if correct else f"FALSE POSITIVE (picked {picked})"
            elif not answer_available:
                # retrieval failed, so the Reviewer could not have won. excluded
                # from scoring rather than counted against it.
                correct = None
                verdict = "excluded, answer not retrieved"
            else:
                correct = picked == "answer"
                verdict = ("correct" if correct
                           else f"WRONG, picked {picked}" if idx is not None
                           else "WRONG, said none")

            want = "absent" if absent else case.get("must_find_ref", "?")
            print(f"{case['doc_id']:<16}{case['category'][:42]:<44}{want:<8}{picked:<10}{verdict}")
            rows.append({
                "doc_id": case["doc_id"], "category": case["category"],
                "expected": case["expected"], "must_find_ref": case.get("must_find_ref"),
                "candidate_kinds": kinds, "answer_available": answer_available,
                "picked_index": idx, "picked_kind": picked,
                "correct": correct, "reason": result.get("reason"),
            })
        all_runs.append(rows)
        print()

    summarise(all_runs, args)


def summarise(all_runs, args):
    print("=== reviewer as a judge ===\n")
    per_run = []
    for rows in all_runs:
        # A run that died on rate limits has nothing to summarise. Reporting it
        # as 0/0 and 0% puts a row of zeros next to real results and reads like
        # a catastrophic score rather than an absent one.
        errored = [r for r in rows if "error" in r]
        if len(errored) == len(rows):
            per_run.append({"failed": True, "error_count": len(errored)})
            continue
        scored = [r for r in rows if r.get("correct") is not None]
        present = [r for r in scored if r["expected"] == "present"]
        absent = [r for r in scored if r["expected"] == "absent"]
        selections = [r for r in scored if r.get("picked_index") is not None]
        right_selections = [r for r in selections if r.get("picked_kind") == "answer"]
        # count distractor picks across ALL cases, not just answerable ones. an
        # earlier version counted only `present`, which reported 0 distractor
        # picks while the Reviewer had picked one on an absent case. Same
        # failure, different bucket, hidden by the metric.
        distractors = [r for r in scored if r.get("picked_kind") == "distractor"]
        said_none = [r for r in present if r.get("picked_index") is None]
        per_run.append({
            "present_correct": sum(1 for r in present if r["correct"]), "present_total": len(present),
            "absent_correct": sum(1 for r in absent if r["correct"]), "absent_total": len(absent),
            "precision": len(right_selections) / len(selections) if selections else 0.0,
            "distractor_picks": len(distractors),
            "false_none": len(said_none),
            "excluded": sum(1 for r in rows if r.get("correct") is None and "error" not in r),
        })

    for i, s in enumerate(per_run, start=1):
        tag = f"run {i}: " if len(per_run) > 1 else ""
        if s.get("failed"):
            print(f"  {tag}NOT RUN, all {s['error_count']} calls failed. excluded, not scored.\n")
            continue
        print(f"  {tag}recall on answerable   {s['present_correct']}/{s['present_total']}")
        print(f"  {tag}absent rejected        {s['absent_correct']}/{s['absent_total']}")
        print(f"  {tag}precision of picks     {s['precision']:.0%}")
        print(f"  {tag}picked a DISTRACTOR    {s['distractor_picks']}"
              f"   <- on topic, not the answer. the failure it was rebuilt to fix")
        print(f"  {tag}said none wrongly      {s['false_none']}")
        if s["excluded"]:
            print(f"  {tag}excluded               {s['excluded']} (answer not retrieved)")
        print()

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        "k": args.k, "runs": len(all_runs), "summary": per_run, "results": all_runs,
    }, indent=2, ensure_ascii=False))
    print(f"saved to {REPORT}")


if __name__ == "__main__":
    main()
