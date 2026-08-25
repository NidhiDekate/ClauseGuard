# eval_models.py
# model selection for the clause classifier, done as a proper comparison rather
# than "which of the two models my free tier offers scored higher".
#
# the original Phase 3 benchmark compared three Groq models on accuracy alone.
# two problems with that. Groq is now down to two production language models,
# so there is no shortlist to select from. and accuracy is the wrong thing to
# select on here: the eval set is 64% concerning, so accuracy rewards leaning
# toward the majority class, which is exactly the bias being investigated.
#
# what this reports instead:
#   accuracy with a confidence interval, because 53 items is small enough that
#     a single decimal place is false precision
#   coverage, so a model that fails to answer is visible rather than flattered
#     by a smaller denominator
#   recall on "concerning", which is the safety metric for this product: a
#     missed one-sided clause costs more than a false alarm
#   macro-F1, which weights the three classes equally instead of letting the
#     majority class carry the score
#   measured cost from real token counts
#
# usage:
#   OPENROUTER_API_KEY=... python evaluation/eval_models.py
#   python evaluation/eval_models.py --only openai/gpt-oss-120b
#   python evaluation/eval_models.py --limit 5      # smoke test before spending

import argparse
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src" / "prompts"))

import classify_clause as cc  # noqa: E402

TEST_SET_PATH = Path("evaluation/datasets/test_set.json")
# report path carries the prompt version. the retrieval eval had this exact bug:
# two strategies writing to one filename, each run silently destroying the last.
# the v2 run is committed evidence of a decision, so a v5 run must not land on top
# of it.
REPORT_PATH = Path(f"evaluation/reports/model_selection_{cc.PROMPT_VERSION}.json")

LABELS = ("concerning", "neutral", "favorable")

# the shortlist. prices are USD per million tokens, from each provider's own
# pricing page, recorded here so the cost column is reproducible and so it is
# obvious when they go stale.
#
# spread is deliberate: both incumbents so the numbers stay comparable to the
# existing Phase 3 report, two cheap models, two mid-tier, and one frontier
# model as a ceiling. the ceiling is the point. three prompt versions failed to
# fix the same six clauses, and without a strong model in the comparison there
# is no way to tell whether that is a gpt-oss limitation or the task being hard.
CANDIDATES = [
    # id,                                provider,     $/M in,  $/M out
    ("openai/gpt-oss-120b",              "groq",        0.15,   0.60),
    ("openai/gpt-oss-20b",               "groq",        0.075,  0.30),
    ("qwen/qwen3.7-flash",               "openrouter",  0.03,   0.13),
    ("deepseek/deepseek-v4-flash-0731",  "openrouter",  0.14,   0.28),
    ("openai/gpt-5.6-luna",              "openrouter",  0.20,   1.20),
    ("google/gemini-3.6-flash",          "openrouter",  0.75,   3.75),
    ("anthropic/claude-opus-5",          "openrouter",  5.00,  25.00),
]


def load_real_clauses():
    data = json.loads(TEST_SET_PATH.read_text(encoding="utf-8"))
    clauses = []
    for doc in data["documents"]:
        if doc.get("source") == "synthetic_example":
            continue  # smoke-test documents, deliberately easy, never scored
        for clause in doc["clauses"]:
            clauses.append({
                "clause": clause["text"],
                "expected_label": clause["label"],
                "doc_id": doc["doc_id"],
                "clause_ref": clause["clause_ref"],
            })
    return clauses


def wilson(k, n, z=1.96):
    """Confidence interval on a proportion. Wilson rather than normal because
    at n=53 with p near 0.87 the normal approximation is unreliable."""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return centre - half, centre + half


def per_class(rows, label):
    """Precision, recall and F1 for one label."""
    tp = sum(1 for r in rows if r["expected"] == label and r["predicted"] == label)
    fp = sum(1 for r in rows if r["expected"] != label and r["predicted"] == label)
    fn = sum(1 for r in rows if r["expected"] == label and r["predicted"] != label)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1, "tp": tp, "fp": fp, "fn": fn}


def evaluate(model_id, provider, price_in, price_out, clauses, pause):
    import os
    os.environ["CLAUSEGUARD_PROVIDER"] = provider

    rows = []
    latencies = []
    tokens_in = tokens_out = 0
    total = len(clauses)

    print(f"\n=== {model_id}  ({provider}) ===")
    for i, item in enumerate(clauses, start=1):
        print(f"[{i}/{total}] {item['doc_id']} / {item['clause_ref']} ... ", end="", flush=True)
        time.sleep(pause)
        start = time.monotonic()
        try:
            result, usage = cc.classify_clause(item["clause"], model_name=model_id, with_usage=True)
        except Exception as e:
            print(f"error: {type(e).__name__}: {e}")
            rows.append({
                "doc_id": item["doc_id"], "clause_ref": item["clause_ref"],
                "expected": item["expected_label"], "predicted": None,
                "error": f"{type(e).__name__}: {e}",
            })
            continue
        elapsed = time.monotonic() - start
        latencies.append(elapsed)
        tokens_in += usage.get("input_tokens") or 0
        tokens_out += usage.get("output_tokens") or 0

        predicted = result.get("label")
        rows.append({
            "doc_id": item["doc_id"], "clause_ref": item["clause_ref"],
            "expected": item["expected_label"], "predicted": predicted,
            "latency_seconds": elapsed,
        })
        print(f"{'correct' if predicted == item['expected_label'] else 'wrong  '} "
              f"({predicted}, {elapsed:.2f}s)")

    answered = sum(1 for r in rows if r["predicted"] is not None)
    correct = sum(1 for r in rows if r["predicted"] == r["expected"])
    lo, hi = wilson(correct, total)

    classes = {label: per_class(rows, label) for label in LABELS}

    return {
        "model": model_id,
        "provider": provider,
        "correct": correct,
        "total": total,
        "answered": answered,
        "accuracy": correct / total if total else 0.0,
        "accuracy_ci": [lo, hi],
        "coverage": answered / total if total else 0.0,
        "per_class": classes,
        "macro_f1": sum(classes[l]["f1"] for l in LABELS) / len(LABELS),
        # the safety number. a concerning clause reported as anything else means
        # a one-sided term reaches the user unflagged.
        "missed_concerning": classes["concerning"]["fn"],
        "false_alarms": classes["concerning"]["fp"],
        "avg_latency_seconds": sum(latencies) / len(latencies) if latencies else None,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": tokens_in / 1e6 * price_in + tokens_out / 1e6 * price_out,
        "per_clause": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", action="append", help="run just this model id, repeatable")
    parser.add_argument("--limit", type=int, help="only the first N clauses, for a cheap smoke test")
    parser.add_argument("--pause", type=float, default=1.5, help="seconds between calls")
    args = parser.parse_args()

    clauses = load_real_clauses()
    if args.limit:
        clauses = clauses[:args.limit]

    counts = Counter(c["expected_label"] for c in clauses)
    majority = counts.most_common(1)[0]
    print(f"{len(clauses)} clauses: {dict(counts)}")
    print(f"majority-class baseline: always answer '{majority[0]}' -> {majority[1]/len(clauses):.1%}")
    print("any model at or below that line has learned nothing.\n")

    candidates = [c for c in CANDIDATES if not args.only or c[0] in args.only]

    results = []
    for model_id, provider, price_in, price_out in candidates:
        try:
            results.append(evaluate(model_id, provider, price_in, price_out, clauses, args.pause))
        except Exception as e:
            print(f"\n[{model_id} failed entirely] {type(e).__name__}: {e}")
            results.append({"model": model_id, "provider": provider, "error": str(e)})

    scored = [r for r in results if "accuracy" in r]

    print("\n\n=== comparison ===\n")
    header = (f"{'model':<34}{'accuracy':<20}{'cover':<8}{'recall':<9}"
              f"{'macroF1':<9}{'missed':<8}{'alarms':<8}{'latency':<10}{'cost'}")
    print(header)
    print(f"{'':34}{'':20}{'':8}{'(conc)':<9}{'':9}{'(conc)':<8}{'':8}{'':10}{'per run'}")
    print("-" * len(header))
    for r in scored:
        lo, hi = r["accuracy_ci"]
        print(
            f"{r['model']:<34}"
            + f"{r['correct']}/{r['total']} {r['accuracy']:.0%} [{lo:.0%}-{hi:.0%}]".ljust(20)
            + f"{r['coverage']:.0%}".ljust(8)
            + f"{r['per_class']['concerning']['recall']:.0%}".ljust(9)
            + f"{r['macro_f1']:.2f}".ljust(9)
            + f"{r['missed_concerning']}".ljust(8)
            + f"{r['false_alarms']}".ljust(8)
            + (f"{r['avg_latency_seconds']:.2f}s".ljust(10) if r["avg_latency_seconds"] else "n/a".ljust(10))
            + f"${r['cost_usd']:.4f}"
        )

    print("\nreading this table:")
    print("  accuracy   the headline, with a 95% interval. at n=53 the interval is wide")
    print("             enough that small differences are not real differences.")
    print("  cover      how many clauses the model actually answered.")
    print("  recall     of the clauses labelled concerning, how many it caught. this is")
    print("             the safety metric: a miss means a one-sided term reaches the user.")
    print("  macroF1    all three classes weighted equally, so the 64% concerning majority")
    print("             cannot carry the score.")
    print("  missed     concerning clauses reported as something else. expensive.")
    print("  alarms     clauses wrongly flagged as concerning. annoying, not dangerous.")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps({
        "prompt_version": cc.PROMPT_VERSION,
        "clauses": len(clauses),
        "label_counts": dict(counts),
        "majority_baseline": majority[1] / len(clauses),
        "results": results,
    }, indent=2), encoding="utf-8")
    print(f"\nsaved to {REPORT_PATH}")


if __name__ == "__main__":
    main()
