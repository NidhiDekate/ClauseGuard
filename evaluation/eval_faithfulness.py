# eval_faithfulness.py
# E3. Does the sentence the classifier writes about a clause actually follow
# from that clause?
#
# This tests the README's core promise, that every conclusion traces to the text
# it came from, and nothing checked it before. Accuracy tells you whether the
# LABEL is right. It says nothing about whether the EXPLANATION is invented.
#
# A faithful reason may still be a wrong label, and an unfaithful reason may
# accompany a correct label. Those are separate failures and this measures the
# second one.
#
# JUDGE CHOICE, which is the design decision here:
#
# The judge must not be the model under test. A model asked to grade its own
# output has a documented preference for it, and the deployed classifier is
# gemini-3.6-flash. So the judge is claude-opus-5: different vendor, different
# family, no shared weights with the system being judged.
#
# It is also the most capable model available here, which matters because a
# weak judge produces a faithfulness number nobody should believe. This runs
# rarely, so the cost is acceptable: about 50 cents for 53 clauses.
#
# Set CLAUSEGUARD_JUDGE to override. If you point it at the model under test,
# the script refuses.
#
#   python evaluation/eval_faithfulness.py \
#       --report evaluation/reports/model_selection_v6_zeroshot.json
#
# Zero new classifier calls: it reads the reasons from an existing report.

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))
sys.path.append(str(Path(__file__).resolve().parents[1] / "src" / "prompts"))

from dotenv import load_dotenv  # noqa: E402
from parsing import extract_json  # noqa: E402

# every other eval script gets .env loaded as a side effect of importing
# classify_clause. this one does not import it, so it has to load it itself.
load_dotenv()

JUDGE_MODEL = os.environ.get("CLAUSEGUARD_JUDGE", "anthropic/claude-opus-5")
TEST_SET_PATH = Path("evaluation/datasets/test_set.json")
HELD_OUT_CLAUSES = Path("evaluation/datasets/held_out_clauses.json")

JUDGE_PROMPT = """You are checking whether an explanation is grounded in a contract clause.

You will be given a CLAUSE and an EXPLANATION that a system wrote about it.

Your only job is to decide whether every factual statement in the EXPLANATION is
supported by the CLAUSE. You are NOT judging whether the explanation reaches the
right conclusion, and you are NOT judging whether the clause is good or bad.

Supported means the clause states it, or it follows directly from what the clause
states. A general characterisation such as "this is common in leases" is a claim
about the wider world, not about the clause, and counts as OUT OF SCOPE rather
than unsupported.

Unsupported means the explanation introduces a specific fact the clause does not
contain: a number that is not there, a party that is not mentioned, a consequence
the clause does not create, or a condition the clause does not impose.

Return only JSON:

{"faithful": true or false,
 "unsupported": ["each specific unsupported statement, quoted from the explanation"],
 "note": "one short sentence"}

CLAUSE:
{clause}

EXPLANATION:
{explanation}"""


def build_judge():
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=JUDGE_MODEL,
        temperature=0,
        max_retries=0,
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
        max_tokens=1024,
    )


def load_clause_text():
    text = {}
    data = json.loads(TEST_SET_PATH.read_text(encoding="utf-8"))
    for doc in data["documents"]:
        for clause in doc["clauses"]:
            text[(doc["doc_id"], clause["clause_ref"])] = clause["text"]
    if HELD_OUT_CLAUSES.exists():
        held = json.loads(HELD_OUT_CLAUSES.read_text(encoding="utf-8"))
        for clause in held["clauses"]:
            text[(held["doc_id"], clause["clause_ref"])] = clause["text"]
    return text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True,
                        help="a model_selection report containing per_clause reasons")
    parser.add_argument("--model", help="which model's results to judge, if the report has several")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--pause", type=float, default=1.0)
    args = parser.parse_args()

    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    runs = [r for r in report["results"] if "per_clause" in r]
    if args.model:
        runs = [r for r in runs if r["model"] == args.model]
    if not runs:
        raise SystemExit("no results with per_clause in that report")
    run = runs[0]

    if run["model"] == JUDGE_MODEL:
        raise SystemExit(
            f"judge and system under test are both {JUDGE_MODEL}. A model grading its own "
            "output is not an evaluation. Set CLAUSEGUARD_JUDGE to something else.")

    rows = [r for r in run["per_clause"] if r.get("reason")]
    if not rows:
        raise SystemExit("that report has no reasons stored. Re-run eval_models.py first.")
    if args.limit:
        rows = rows[:args.limit]

    clause_text = load_clause_text()
    judge = build_judge()

    print(f"judging {len(rows)} explanations from {run['model']}")
    print(f"judge: {JUDGE_MODEL} (different vendor and family from the system under test)\n")

    results = []
    for i, row in enumerate(rows, start=1):
        key = (row["doc_id"], row["clause_ref"])
        clause = clause_text.get(key)
        if not clause:
            print(f"[{i}/{len(rows)}] {key} ... skipped, clause text not found")
            continue
        print(f"[{i}/{len(rows)}] {row['doc_id']} / {row['clause_ref']} ... ", end="", flush=True)
        time.sleep(args.pause)
        prompt = (JUDGE_PROMPT
                  .replace("{clause}", clause)
                  .replace("{explanation}", row["reason"]))
        try:
            verdict = extract_json(judge.invoke(prompt).content, required_key="faithful")
        except Exception as e:
            print(f"error: {type(e).__name__}: {e}")
            results.append({**key_dict(key), "error": str(e)})
            continue
        faithful = bool(verdict.get("faithful"))
        print("faithful" if faithful else f"UNFAITHFUL: {verdict.get('unsupported')}")
        results.append({
            "doc_id": key[0], "clause_ref": key[1],
            "predicted_label": row.get("predicted"),
            "label_correct": row.get("predicted") == row.get("expected"),
            "reason": row["reason"],
            "faithful": faithful,
            "unsupported": verdict.get("unsupported") or [],
            "note": verdict.get("note"),
        })

    judged = [r for r in results if "faithful" in r]
    faithful = [r for r in judged if r["faithful"]]
    print(f"\n=== faithfulness ===")
    print(f"  {len(faithful)}/{len(judged)} explanations fully grounded "
          f"({len(faithful)/len(judged):.1%})" if judged else "  nothing judged")

    # the cross-tab that matters: a right label with an invented reason is the
    # failure this eval exists to find, and accuracy cannot see it.
    both = [r for r in judged if r["label_correct"] and r["faithful"]]
    right_label_bad_reason = [r for r in judged if r["label_correct"] and not r["faithful"]]
    wrong_label_good_reason = [r for r in judged if not r["label_correct"] and r["faithful"]]
    neither = [r for r in judged if not r["label_correct"] and not r["faithful"]]
    print(f"\n  label correct + reason grounded : {len(both)}")
    print(f"  label correct + reason invented : {len(right_label_bad_reason)}   <-- accuracy hides these")
    print(f"  label wrong   + reason grounded : {len(wrong_label_good_reason)}")
    print(f"  label wrong   + reason invented : {len(neither)}")

    if right_label_bad_reason:
        print("\n  right label, unsupported reason:")
        for r in right_label_bad_reason:
            print(f"    {r['doc_id']}/{r['clause_ref']}: {r['unsupported']}")

    out = Path(f"evaluation/reports/faithfulness_{run['model'].replace('/', '_')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "system_under_test": run["model"],
        "judge": JUDGE_MODEL,
        "source_report": args.report,
        "judged": len(judged),
        "faithful": len(faithful),
        "results": results,
    }, indent=2, ensure_ascii=False))
    print(f"\nsaved to {out}")


def key_dict(key):
    return {"doc_id": key[0], "clause_ref": key[1]}


if __name__ == "__main__":
    main()
