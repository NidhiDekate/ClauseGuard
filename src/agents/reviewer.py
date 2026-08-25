# reviewer.py
# decides which of the retrieved clauses, if any, actually addresses the concern
# category it was searched for.
#
# this used to be a yes/no gate on the single top result. the retrieval eval
# (evaluation/eval_retrieval.py) showed why that was the wrong shape: with
# clause-boundary chunking every correct clause sits within the top 3, but only
# 75% of them are at rank 1. so a quarter of the answers were being retrieved
# and then never looked at.
#
# a yes/no gate could not have fixed that even at a higher k. on the real
# failure, "guest and occupancy restrictions" returned III. OCCUPANT(S) first,
# and III genuinely is about occupancy, so a strict relevance check approves it
# and stops. what was needed was not a stricter gate but the ability to say
# "relevant, but this other one is more relevant". so the node now picks the
# best of the candidates, or none.
#
# cost is unchanged: still one model call per category, just with three
# candidates in it instead of one.
#
# usage: python src/agents/reviewer.py

import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate

sys.path.append(str(Path(__file__).resolve().parents[1]))
from parsing import extract_json  # noqa: E402
from llm import invoke_with_fallback  # noqa: E402

load_dotenv()

# The Reviewer runs a DIFFERENT model from the classifier, on purpose.
#
# evaluation/eval_reviewer.py, n=16:
#   gpt-oss-120b     recall 11/12, absent 3/4, precision  92%
#   gemini-3.6-flash recall 10/12, absent 4/4, precision 100%
#
# Tied on total correct, 14/16 each, differing only in which error they make.
# gemini is more conservative: no false positives, two false negatives.
#
# gpt-oss wins here for the same reason recall beats precision in the
# classifier. A Reviewer false negative reaches the user as "not addressed in
# this document", which is a false statement about their contract: the PA lease
# does have a late fee clause, $25 plus $5 a day uncapped. A false positive
# shows them a real clause under the wrong heading, which they can read and
# dismiss. The miss is also a lie; the false alarm is only noise.
#
# At n=16 this is one case each way and inside noise. Recorded as a decision
# made on which error costs more, not on a measured difference.
REVIEWER_MODEL = os.environ.get("CLAUSEGUARD_REVIEWER_MODEL", "openai/gpt-oss-120b")
REVIEWER_PROVIDER = os.environ.get("CLAUSEGUARD_REVIEWER_PROVIDER", "groq")

# The Reviewer's fallback is the OPPOSITE of the classifier's. gpt-oss-120b is
# the global fallback, so a Reviewer pinned to it would have no fallback and a
# Groq daily limit would take the whole analysis down, which is exactly what
# happened before. gemini is second best here, 10/12 against 11/12.
REVIEWER_FALLBACK = os.environ.get("CLAUSEGUARD_REVIEWER_FALLBACK", "google/gemini-3.6-flash")
REVIEWER_FALLBACK_PROVIDER = "openrouter"

SELECTION_PROMPT = """You are choosing which retrieved clause, if any, actually addresses a specific concern category.

Concern category: {category}

Candidate clauses:
{candidates}

Work in two steps.

First, decide which candidates genuinely address the concern category. Be strict. A clause that only loosely touches the topic, or is clearly about something else, does not count. A blank template field that names the topic without stating any actual term does not count either.

Second, among the candidates that genuinely address it, choose the single one that states the most substantive term. Prefer a clause that sets a real rule, limit, amount, deadline or obligation over one that merely names the subject.

If none of the candidates genuinely address the concern category, return null. Reporting that a document does not address something is a correct and useful answer, so do not reach for the closest available match.

Return ONLY valid JSON in this exact format:
{{"best": <the number of the chosen clause, or null>, "reason": "one sentence explanation"}}"""


def _format_candidates(clauses):
    return "\n\n".join(f"[{i}] {clause}" for i, clause in enumerate(clauses, start=1))


def select_best_clause(category, clauses):
    """Pick the clause that best addresses the category, or None.

    Returns {"index": int or None, "reason": str}. The index is 0-based, so it
    can be used directly against the list that was passed in. The model answers
    with 1-based numbers because that matches the numbered list it is shown.
    """
    if not clauses:
        raise ValueError("no candidate clauses given")

    prompt = ChatPromptTemplate.from_messages([("human", SELECTION_PROMPT)])
    response = invoke_with_fallback(
        lambda model: prompt | model,
        {"category": category, "candidates": _format_candidates(clauses)},
        model_name=REVIEWER_MODEL,
        provider=REVIEWER_PROVIDER,
        fallback_model=REVIEWER_FALLBACK,
        fallback_provider=REVIEWER_FALLBACK_PROVIDER,
        label="reviewer",
    )
    result = extract_json(response.content, required_key="best")

    if not isinstance(result, dict):
        raise ValueError(f"clause selection returned {type(result).__name__}, expected an object: {result!r}")

    if not result.get("reason"):
        raise ValueError("clause selection returned no reason")

    choice = result.get("best")

    if choice is None:
        return {"index": None, "reason": result["reason"]}

    # a bool is an int in python, so True would sail through as index 0 and
    # silently verify the first candidate. reject it explicitly.
    if isinstance(choice, bool) or not isinstance(choice, int):
        raise ValueError(f"clause selection returned a non-integer 'best': {choice!r}")

    if not 1 <= choice <= len(clauses):
        raise ValueError(f"clause selection returned {choice}, outside 1..{len(clauses)}")

    return {"index": choice - 1, "reason": result["reason"]}


if __name__ == "__main__":
    # two real cases, both taken from the retrieval eval.

    # 1. the failure this change exists for. these are the actual top 3 results
    # for this category on the PA lease. III came back first and the old yes/no
    # gate approved it, because III really is about occupancy. XXXIII is the
    # clause that carries the restriction. correct answer here is 3.
    category = "guest and occupancy restrictions"
    candidates = [
        'III. OCCUPANT(S). The Premises is to be occupied strictly as a residential dwelling with the '
        'following individual(s) in addition to the Tenant: (check one)\n'
        '- ______________________________________________ ("Occupant(s)")\n'
        '- There are no Occupant(s).',
        'V. PURPOSE. The Tenant and Occupant(s) may only use the Premises as: (check one)\n'
        '- A residential dwelling only.\n'
        '- A residential dwelling and: _______________________________________.',
        'XXXIII. GUESTS. There shall be no other persons living on the Premises other than the Tenant '
        'and any Occupant(s). Guests of the Tenant are allowed for periods not lasting for more than '
        '48 hours unless otherwise approved by the Landlord in writing.',
    ]
    result = select_best_clause(category, candidates)
    print(f"category: {category}")
    print(f"  picked index {result['index']} (expected 2, i.e. XXXIII)")
    print(f"  reason: {result['reason']}\n")

    # 2. the honesty case. the FTC lease has no right-of-entry clause, so the
    # correct answer is None. if this returns a number, the gate has stopped
    # being strict and "not addressed" can no longer be trusted.
    category2 = "landlord right of entry and notice period"
    candidates2 = [
        'SAMPLE RENTAL AGREEMENT (Basic/Beginning)\n'
        'THIS AGREEMENT made this 15th Day of June, 2012, by and between ABC Properties, '
        'herein called "Landlord," and Silvia Mando, herein called "Tenant."',
        '3. FORM OF PAYMENT:\nTenants agree to pay their rent in the form of a personal check, '
        'a cashier\'s check, or a money order made out to the Landlord.',
        '10. VEHICLES & GARAGE USE:\nTenants agree to keep a maximum of 1 vehicle on premises or '
        'in the garage. These vehicles must be both operable and currently licensed.',
    ]
    result2 = select_best_clause(category2, candidates2)
    print(f"category: {category2}")
    print(f"  picked index {result2['index']} (expected None)")
    print(f"  reason: {result2['reason']}")