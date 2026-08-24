# graph.py
# the actual langgraph pipeline, now complete:
# planner -> retriever -> reviewer -> calculator -> report
#
# usage: python src/agents/graph.py

import asyncio
import sys
from pathlib import Path
from typing import TypedDict

from fastmcp import Client
from langgraph.graph import StateGraph, START, END

from clause_search_server import mcp
from calculator import extract_fee_terms, compute_late_fee_exposure
from reviewer import select_best_clause

sys.path.append(str(Path(__file__).resolve().parents[1] / "prompts"))
from classify_clause import classify_clause  # noqa: E402
from guardrails import validate_document, check_call_budget


class ClauseGuardState(TypedDict):
    document_text: str
    document_type: str
    concern_categories: list[str]
    retrieved_clauses: dict[str, list[str]]
    reviewed_findings: dict[str, dict]
    fee_computations: dict[str, dict]
    decision_report: list[dict]


# retrieval depth. was 2, chosen without an experiment. the retrieval eval
# (evaluation/eval_retrieval.py) measured where the correct clause actually
# lands: recall@1 75%, recall@2 83%, recall@3 100% on clause-boundary chunks.
# so 3 is where every answer in the eval set is reachable. retrieval is local
# and free, and the reviewer still makes one call per category regardless of
# how many candidates are in it, so this costs nothing.
RETRIEVAL_K = 3

LEASE_CONCERN_CATEGORIES = [
    "late fees and rent payment terms",
    "early termination and lease-breaking fees",
    "security deposit terms",
    "landlord right of entry and notice period",
    "guest and occupancy restrictions",
    "maintenance and repair responsibilities",
    "liability and indemnification",
    "automatic renewal and rent increases",
]

TOS_CONCERN_CATEGORIES = [
    "data collection and third-party sharing",
    "arbitration and dispute resolution",
    "account termination and content removal",
    "liability limits and refund policy",
    "changes to terms",
]


def planner_node(state: ClauseGuardState) -> dict:
    # validate here, not only in the callers. every entry point used to call
    # validate_document itself, which meant graph.invoke could be called
    # unguarded and every new caller had to remember. check_call_budget already
    # lives inside the graph in retriever_node, so this makes the pair
    # consistent: the graph guards itself, and a caller validating early is an
    # optimisation rather than the guarantee.
    validate_document(state["document_text"])

    if state["document_type"] == "lease":
        categories = LEASE_CONCERN_CATEGORIES
    elif state["document_type"] == "terms_of_service":
        categories = TOS_CONCERN_CATEGORIES
    else:
        raise ValueError(f"no concern checklist for document_type={state['document_type']!r} yet")

    return {"concern_categories": categories}


async def _search_all_categories(document_text, categories, k=RETRIEVAL_K):
    results = {}
    async with Client(mcp) as client:
        for category in categories:
            result = await client.call_tool(
                "clause_search",
                {"document_text": document_text, "query": category, "k": k},
            )
            results[category] = result.data
    return results


def retriever_node(state: ClauseGuardState) -> dict:
    # guardrail: check the category count before spending any real api
    # calls on it, not after
    check_call_budget(state["concern_categories"])

    retrieved = asyncio.run(
        _search_all_categories(state["document_text"], state["concern_categories"])
    )
    return {"retrieved_clauses": retrieved}


def reviewer_node(state: ClauseGuardState) -> dict:
    # this used to check only clauses[0] and answer yes or no. the retrieval eval
    # showed a quarter of the correct clauses arrive below rank 1, so they were
    # being fetched and then thrown away unread. it now sees every candidate and
    # picks the best one, or none. still one model call per category.
    reviewed = {}

    for category, clauses in state["retrieved_clauses"].items():
        if not clauses:
            reviewed[category] = {"verified": False, "clause": None, "reason": "nothing retrieved"}
            continue

        try:
            result = select_best_clause(category, clauses)
        except ValueError:
            reviewed[category] = {"verified": False, "clause": None, "reason": "clause selection failed"}
            continue

        if result["index"] is None:
            reviewed[category] = {"verified": False, "clause": None, "reason": result["reason"]}
            continue

        reviewed[category] = {
            "verified": True,
            "clause": clauses[result["index"]],
            "reason": result["reason"],
        }

    return {"reviewed_findings": reviewed}


def calculator_node(state: ClauseGuardState) -> dict:
    fee_categories = [c for c in state["concern_categories"] if "fee" in c.lower()]

    computations = {}
    for category in fee_categories:
        finding = state["reviewed_findings"].get(category)
        if not finding or not finding["verified"]:
            continue

        try:
            terms = extract_fee_terms(finding["clause"])
        except ValueError:
            continue

        if terms.get("daily_fee") or terms.get("flat_fee"):
            exposure = compute_late_fee_exposure(
                terms.get("flat_fee"), terms.get("daily_fee"), days_late=10
            )
            computations[category] = {"terms": terms, "exposure_10_days_late": exposure}

    return {"fee_computations": computations}


def report_node(state: ClauseGuardState) -> dict:
    # the final piece - turns everything the pipeline found into what a
    # user actually sees. verified clauses get classified (reusing the
    # phase 2 classifier, not reinventing it here). unverified categories
    # get reported honestly as not addressed, not silently dropped.
    findings = []

    for category, review in state["reviewed_findings"].items():
        if not review["verified"]:
            findings.append(
                {
                    "category": category,
                    "status": "not_addressed",
                    "note": "This document does not clearly address this.",
                }
            )
            continue

        clause = review["clause"]
        try:
            classification = classify_clause(clause)
        except ValueError:
            # classifier failed - still report the finding, just without a label
            findings.append(
                {
                    "category": category,
                    "status": "found_unclassified",
                    "clause": clause,
                }
            )
            continue

        entry = {
            "category": category,
            "status": "found",
            "label": classification["label"],
            "reason": classification["reason"],
            "clause": clause,
        }

        if category in state["fee_computations"]:
            entry["fee_exposure_10_days_late"] = state["fee_computations"][category]["exposure_10_days_late"]

        findings.append(entry)

    return {"decision_report": findings}


graph_builder = StateGraph(ClauseGuardState)
graph_builder.add_node("planner", planner_node)
graph_builder.add_node("retriever", retriever_node)
graph_builder.add_node("reviewer", reviewer_node)
graph_builder.add_node("calculator", calculator_node)
graph_builder.add_node("report", report_node)
graph_builder.add_edge(START, "planner")
graph_builder.add_edge("planner", "retriever")
graph_builder.add_edge("retriever", "reviewer")
graph_builder.add_edge("reviewer", "calculator")
graph_builder.add_edge("calculator", "report")
graph_builder.add_edge("report", END)
graph = graph_builder.compile()


if __name__ == "__main__":
    with open("data/sample_docs/ftc_lease_sample.txt", encoding="utf-8") as f:
        doc = f.read()

    result = graph.invoke({"document_text": doc, "document_type": "lease"})

    concerning = [f for f in result["decision_report"] if f.get("label") == "concerning"]
    neutral = [f for f in result["decision_report"] if f.get("label") == "neutral"]
    favorable = [f for f in result["decision_report"] if f.get("label") == "favorable"]
    not_addressed = [f for f in result["decision_report"] if f["status"] == "not_addressed"]

    print(f"DECISION REPORT — {len(concerning)} concerning, {len(neutral)} neutral, {len(favorable)} favorable, {len(not_addressed)} not addressed\n")

    for f in result["decision_report"]:
        print(f"--- {f['category']} ---")
        if f["status"] == "not_addressed":
            print(f"  Not addressed in this document. ({f['note']})")
        else:
            print(f"  [{f['label'].upper()}] {f['reason']}")
            if "fee_exposure_10_days_late" in f:
                print(f"  Estimated exposure at 10 days late: ${f['fee_exposure_10_days_late']}")
            print(f"  Source: {f['clause'][:100]}...")
        print()