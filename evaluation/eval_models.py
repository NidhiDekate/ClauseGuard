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
# Any variable that changes what a report MEANS belongs in its filename.
# Learned three times: two chunking strategies shared a file, a failed run
# overwrote a good one, and two models shared a slot.
REPORT_PATH = Path(f"evaluation/reports/model_selection_{cc.PROMPT_VERSION}{'' if cc.USE_FEW_SHOT else '_zeroshot'}.json")

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


def load_held_out(gold_path, clauses_path=Path("evaluation/datasets/held_out_clauses.json")):
    """The held-out set is stored as two files, clause text and adjudicated labels,
    because the labels were written by two annotators independently and the text had
    to exist before either of them could label it. Joined on clause_id here."""
    gold = json.loads(Path(gold_path).read_text(encoding="utf-8"))
    text = {c["clause_id"]: c for c in json.loads(clauses_path.read_text(encoding="utf-8"))["clauses"]}
    out = []
    for row in gold["clauses"]:
        c = text[row["clause_id"]]
        out.append({
            "clause": c["text"],
            "expected_label": row["label"],
            "doc_id": gold["doc_id"],
            "clause_ref": c["clause_ref"],
        })
    return out


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
            # the reason was generated and thrown away until E3 needed it.
            # faithfulness cannot be evaluated from a report that only stores
            # the label, and the sentence is the thing a human would actually
            # want to read when a label looks wrong.
            "reason": result.get("reason"),
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
    parser.add_argument("--force-report", action="store_true",
                        help="write the report even if coverage is poor and would overwrite "
                             "a better run")
    parser.add_argument("--provider", choices=("groq", "openrouter"),
                        help="override the provider in CANDIDATES. Groq's free tier is 200k "
                             "tokens per day and one full run of 53 clauses with few-shot "
                             "examples costs about 72k, so three runs exhaust it.")
    parser.add_argument("--repeat", type=int, default=1, metavar="N",
                        help="run each model N times and report the spread. Single runs of this "
                             "eval are unstable: gpt-oss-120b scored 45, 46, 43 and 41 on "
                             "identical inputs at temperature 0. A number without a spread is "
                             "not a result.")
    parser.add_argument("--held-out", metavar="GOLD",
                        help="score against the held-out set instead of test_set.json, "
                             "e.g. evaluation/datasets/held_out_gold.json")
    args = parser.parse_args()

    clauses = load_held_out(args.held_out) if args.held_out else load_real_clauses()
    if args.held_out:
        globals()["REPORT_PATH"] = Path(
            f"evaluation/reports/held_out_{cc.PROMPT_VERSION}{'' if cc.USE_FEW_SHOT else '_zeroshot'}.json")
    if args.limit:
        clauses = clauses[:args.limit]

    counts = Counter(c["expected_label"] for c in clauses)
    majority = counts.most_common(1)[0]
    print(f"{len(clauses)} clauses: {dict(counts)}")
    print(f"majority-class baseline: always answer '{majority[0]}' -> {majority[1]/len(clauses):.1%}")
    print("any model at or below that line has learned nothing.\n")

    candidates = [c for c in CANDIDATES if not args.only or c[0] in args.only]
    if args.provider:
        candidates = [(m, args.provider, pi, po) for m, _, pi, po in candidates]

    results = []
    for model_id, provider, price_in, price_out in candidates:
        runs = []
        for attempt in range(args.repeat):
            if args.repeat > 1:
                print(f"\n--- run {attempt + 1} of {args.repeat} ---")
            try:
                runs.append(evaluate(model_id, provider, price_in, price_out,
                                     clauses, args.pause))
            except Exception as e:
                print(f"\n[{model_id} failed entirely] {type(e).__name__}: {e}")
                runs.append({"model": model_id, "provider": provider, "error": str(e)})
        scored_runs = [r for r in runs if "accuracy" in r]
        if len(scored_runs) > 1:
            # Report the median run, and carry the spread alongside it. The median
            # rather than the mean because with 3 runs one bad run should not drag
            # the headline; the spread is what tells you how much to trust it.
            scored_runs.sort(key=lambda r: r["correct"])
            headline = dict(scored_runs[len(scored_runs) // 2])
            correct = [r["correct"] for r in scored_runs]
            headline["runs"] = len(scored_runs)
            headline["correct_per_run"] = correct
            headline["correct_min"] = min(correct)
            headline["correct_max"] = max(correct)
            headline["missed_per_run"] = [r["missed_concerning"] for r in scored_runs]
            headline["all_runs"] = [{k: v for k, v in r.items() if k != "per_clause"}
                                    for r in scored_runs]
            results.append(headline)
        else:
            results.extend(runs)

    scored = [r for r in results if "accuracy" in r]

    print("\n\n=== comparison ===\n")
    if args.repeat > 1:
        print("accuracy shows the MEDIAN run, with the observed range over all runs\n"
              "in brackets. missed shows a range only when it varied.\n")
    header = (f"{'model':<34}{'accuracy':<20}{'cover':<8}{'recall':<9}"
              f"{'macroF1':<9}{'missed':<8}{'alarms':<8}{'latency':<10}{'cost'}")
    print(header)
    print(f"{'':34}{'':20}{'':8}{'(conc)':<9}{'':9}{'(conc)':<8}{'':8}{'':10}{'per run'}")
    print("-" * len(header))
    for r in scored:
        lo, hi = r["accuracy_ci"]
        # With repeats, show the observed spread across runs rather than the Wilson
        # interval. The interval answers "how uncertain is one measurement"; the
        # range answers "does this number move when I run it again", and this eval
        # moves by up to 3 clauses at temperature 0.
        if r.get("runs", 1) > 1:
            acc_cell = (f"{r['correct']}/{r['total']} "
                        f"[{r['correct_min']}-{r['correct_max']} over {r['runs']}]")
        else:
            acc_cell = f"{r['correct']}/{r['total']} {r['accuracy']:.0%} [{lo:.0%}-{hi:.0%}]"
        print(
            f"{r['model']:<34}"
            + acc_cell.ljust(20)
            + f"{r['coverage']:.0%}".ljust(8)
            + f"{r['per_class']['concerning']['recall']:.0%}".ljust(9)
            + f"{r['macro_f1']:.2f}".ljust(9)
            + (f"{min(r['missed_per_run'])}-{max(r['missed_per_run'])}"
               if r.get("runs", 1) > 1 and len(set(r['missed_per_run'])) > 1
               else f"{r['missed_concerning']}").ljust(8)
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

    # A run that dies on rate limits still reaches this point with a report full
    # of errors. Without this guard it overwrites the good run that came before,
    # which is how the first E8 result was destroyed: a run answering 1 clause of
    # 53 replaced one that answered all 53. Reports are evidence; a failed run is
    # not entitled to replace evidence.
    worst_coverage = min((r["coverage"] for r in results), default=0.0)
    if worst_coverage < 0.9 and REPORT_PATH.exists() and not args.force_report:
        print(f"\n[NOT SAVED] coverage {worst_coverage:.0%} and {REPORT_PATH.name} already "
              f"exists. A failed run will not overwrite a good one. Re-run when the rate "
              f"limit clears, or pass --force-report if you really mean it.")
        return

    REPORT_PATH.write_text(json.dumps({
        "prompt_version": cc.PROMPT_VERSION,
        "few_shot": cc.USE_FEW_SHOT,
        "clauses": len(clauses),
        "label_counts": dict(counts),
        "majority_baseline": majority[1] / len(clauses),
        "results": results,
    }, indent=2), encoding="utf-8")
    print(f"\nsaved to {REPORT_PATH}")


if __name__ == "__main__":
    main()
