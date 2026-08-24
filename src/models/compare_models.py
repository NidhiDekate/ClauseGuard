# Compare candidate Groq models on the same evaluation set.
# usage: python src/models/compare_models.py

import json
import time
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1] / "prompts"))
from classify_clause import classify_clause  # noqa: E402

TEST_SET_PATH = Path("evaluation/datasets/test_set.json")
REPORT_PATH = Path("evaluation/reports/model_comparison.json")

# groq deprecated llama-3.1-8b-instant + llama-3.3-70b-versatile on 6/17/26.
# these are their recommended replacements as of when I wrote this - check
# console.groq.com/docs/deprecations if these ever start failing
CANDIDATE_MODELS = [
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "qwen/qwen3.6-27b",
]


def load_real_clauses():
    data = json.loads(TEST_SET_PATH.read_text(encoding="utf-8"))
    clauses = []
    for doc in data["documents"]:
        if doc.get("source") == "synthetic_example":
            continue
        for clause in doc["clauses"]:
            clauses.append({
                "clause": clause["text"],
                "expected_label": clause["label"],
                "doc_id": doc["doc_id"],
                "clause_ref": clause["clause_ref"],
            })
    return clauses


def evaluate_model(model_name, clauses):
    correct = 0
    total_latency = 0.0
    errors = 0
    total = len(clauses)
    per_clause = []

    print(f"\n=== {model_name} ===")
    for i, item in enumerate(clauses, start=1):
        print(f"[{i}/{total}] {item['doc_id']} / {item['clause_ref']} ... ", end="", flush=True)
        time.sleep(1.5)  # pacing to stay under groq's free tier rate limit instead of hitting it and waiting
        start = time.monotonic()
        try:
            result = classify_clause(item["clause"], model_name=model_name)
        except Exception as e:
            # groq's own api throws sometimes on gpt-oss models specifically
            # (output_parse_failed) - want to skip and keep going, not die here
            errors += 1
            print(f"error: {type(e).__name__}: {e}")
            per_clause.append({
                "doc_id": item["doc_id"],
                "clause_ref": item["clause_ref"],
                "expected": item["expected_label"],
                "predicted": None,
                "correct": False,
                "error": f"{type(e).__name__}: {e}",
            })
            continue
        elapsed = time.monotonic() - start
        total_latency += elapsed

        predicted = result.get("label")
        is_correct = predicted == item["expected_label"]
        if is_correct:
            correct += 1
            print(f"correct ({predicted}, {elapsed:.2f}s)")
        else:
            print(f"wrong (expected={item['expected_label']}, got={predicted}, {elapsed:.2f}s)")

        per_clause.append({
            "doc_id": item["doc_id"],
            "clause_ref": item["clause_ref"],
            "expected": item["expected_label"],
            "predicted": predicted,
            "correct": is_correct,
            "latency_seconds": elapsed,
        })

    answered = total - errors

    # accuracy is over EVERY clause, not just the ones the model managed to answer.
    # dividing by (total - errors) grades a model only on the questions it got
    # around to, which quietly rewards failing. that is how qwen came out looking
    # like the most accurate model in the phase 3 writeup when, counted over all 53,
    # it tied for last. a clause the model cannot answer is a clause the user gets
    # no answer for, so it counts against it.
    return {
        "model": model_name,
        "accuracy": correct / total if total else 0.0,
        "correct": correct,
        "total": total,
        "answered": answered,
        "coverage": answered / total if total else 0.0,
        "errors": errors,
        # latency is averaged over answered calls only, since a failed call has no
        # meaningful duration. note it also includes prompt construction and two
        # file reads, because classify_clause rebuilds its chain on every call.
        "avg_latency_seconds": total_latency / answered if answered else 0.0,
        "per_clause": per_clause,
    }


def main():
    clauses = load_real_clauses()
    results = []

    for model in CANDIDATE_MODELS:
        try:
            results.append(evaluate_model(model, clauses))
        except Exception as e:
            # one model completely dying shouldn't stop the others from running
            print(f"\n[model failed] {model}: {type(e).__name__}: {e}")
            results.append({
                "model": model,
                "accuracy": None,
                "correct": 0,
                "total": len(clauses),
                "answered": 0,
                "coverage": 0.0,
                "errors": len(clauses),
                "avg_latency_seconds": None,
                "per_clause": [],
                "note": str(e),
            })

    print("\n\n=== comparison ===")
    print(f"{'model':<30} {'accuracy':<20} {'coverage':<16} {'avg latency':<14} errors")
    for r in results:
        if r["accuracy"] is None:
            print(f"{r['model']:<30} FAILED - {r.get('note', '?')}")
            continue
        print(
            f"{r['model']:<30} "
            + f"{r['accuracy']:.1%} ({r['correct']}/{r['total']})".ljust(20)
            + f"{r['coverage']:.1%} ({r['answered']}/{r['total']})".ljust(16)
            + f"{r['avg_latency_seconds']:.2f}s".ljust(14)
            + str(r["errors"])
        )

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nsaved to {REPORT_PATH}")


if __name__ == "__main__":
    main()