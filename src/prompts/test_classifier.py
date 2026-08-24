# test_classifier.py
# scores the classifier against evaluation/datasets/test_set.json
# run this after any prompt change to see if it actually helped
#
# usage: python src/prompts/test_classifier.py

import json
import time
from pathlib import Path

from classify_clause import classify_clause, MODEL_NAME, PROMPT_VERSION

TEST_SET_PATH = Path("evaluation/datasets/test_set.json")

# per-clause results, one file per (prompt, model) combination. printing the
# mismatches and losing them was the same defect as compare_models.py had:
# without the per-clause record you cannot diff two runs to see which specific
# clauses moved, only that the total changed.
RESULTS_DIR = Path("evaluation/reports")


def load_real_clauses():
    data = json.loads(TEST_SET_PATH.read_text(encoding="utf-8"))
    clauses = []
    for doc in data["documents"]:
        if doc.get("source") == "synthetic_example":
            continue  # the fake smoke-test docs don't count toward the real score
        for clause in doc["clauses"]:
            clauses.append({
                "clause": clause["text"],
                "expected_label": clause["label"],
                "doc_id": doc["doc_id"],
                "clause_ref": clause["clause_ref"],
            })
    return clauses


def run_regression_test():
    clauses = load_real_clauses()
    total = len(clauses)
    correct = 0
    mismatches = []
    per_clause = []

    print(f"testing {total} real clauses...\n")

    for i, item in enumerate(clauses, start=1):
        print(f"[{i}/{total}] {item['doc_id']} / {item['clause_ref']} ... ", end="", flush=True)
        time.sleep(1.5) 
        try:
            result = classify_clause(item["clause"])
        except ValueError as e:
            print(f"error: {e}")
            per_clause.append({
                "doc_id": item["doc_id"], "clause_ref": item["clause_ref"],
                "expected": item["expected_label"], "predicted": None,
                "correct": False, "error": str(e),
            })
            continue

        predicted = result.get("label")
        per_clause.append({
            "doc_id": item["doc_id"], "clause_ref": item["clause_ref"],
            "expected": item["expected_label"], "predicted": predicted,
            "correct": predicted == item["expected_label"],
        })

        if predicted == item["expected_label"]:
            correct += 1
            print(f"correct ({predicted})")
        else:
            print(f"wrong (expected {item['expected_label']}, got {predicted})")
            mismatches.append({
                "doc_id": item["doc_id"],
                "clause_ref": item["clause_ref"],
                "expected": item["expected_label"],
                "predicted": predicted,
                "clause": item["clause"][:80] + "...",
            })

    acc = correct / total if total else 0
    print(f"\naccuracy: {correct}/{total} ({acc:.1%})\n")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    slug = f"{PROMPT_VERSION}_{MODEL_NAME.split('/')[-1]}"
    results_path = RESULTS_DIR / f"classifier_{slug}.json"
    results_path.write_text(json.dumps({
        "prompt_version": PROMPT_VERSION,
        "model": MODEL_NAME,
        "correct": correct,
        "total": total,
        "accuracy": correct / total if total else 0.0,
        "per_clause": per_clause,
    }, indent=2), encoding="utf-8")
    print(f"saved to {results_path}\n")

    if mismatches:
        print(f"{len(mismatches)} mismatches:\n")
        for m in mismatches:
            print(f"  [{m['doc_id']} / {m['clause_ref']}] expected={m['expected']} predicted={m['predicted']}")
            print(f"    {m['clause']}")


if __name__ == "__main__":
    run_regression_test()