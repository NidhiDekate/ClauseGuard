# calculator.py
# does actual math on fee clauses instead of trusting the llm to do
# arithmetic in free text - it's genuinely unreliable at that. so the real
# split is: llm extracts the numbers, python does the math.
#
# usage: python src/agents/calculator.py

import json
import re

from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq

load_dotenv()

MODEL_NAME = "openai/gpt-oss-120b"

# the fields the extraction prompt asks for. every one of them ends up in
# arithmetic, so every one of them gets checked.
FEE_FIELDS = ("flat_fee", "daily_fee", "grace_period_days")

EXTRACTION_PROMPT = """You extract numeric fee terms from a lease clause about late fees.

Return ONLY valid JSON in this exact format:
{{"flat_fee": <number or null>, "daily_fee": <number or null>, "grace_period_days": <number or null>}}

If a value isn't mentioned in the clause, use null. Don't guess numbers that aren't stated.

Clause: {clause}"""


def extract_fee_terms(clause_text):
    prompt = ChatPromptTemplate.from_messages([("human", EXTRACTION_PROMPT)])
    model = ChatGroq(model=MODEL_NAME, temperature=0)
    chain = prompt | model

    response = chain.invoke({"clause": clause_text})
    # same think-block issue as classify_clause - strip it before parsing
    content = re.sub(r"<think>.*?</think>", "", response.content.strip(), flags=re.DOTALL).strip()

    try:
        result = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"extraction didn't return valid json, got: {content!r}") from e

    # these numbers go straight into arithmetic and then into a dollar figure the
    # user might actually act on. a string like "$25" is truthy, so it survives
    # the `or 0` in compute_late_fee_exposure and then either throws on the
    # multiply or concatenates into nonsense. bools are rejected explicitly
    # because in python True is an int and would silently count as 1.
    if not isinstance(result, dict):
        raise ValueError(f"extraction returned {type(result).__name__}, expected an object: {content!r}")

    for field in FEE_FIELDS:
        value = result.get(field)
        if value is None:
            continue  # null is a valid answer here - it means the clause didn't say
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"extraction returned a non-numeric {field}: {value!r}")
        if value < 0:
            raise ValueError(f"extraction returned a negative {field}: {value!r}")

    return result


def compute_late_fee_exposure(flat_fee, daily_fee, days_late):
    # the actual math - real arithmetic, not an llm guessing at a number
    flat_fee = flat_fee or 0
    daily_fee = daily_fee or 0
    return flat_fee + (daily_fee * days_late)


if __name__ == "__main__":
    # real late-fee clause from the ftc sample doc, not a blank template
    clause = (
        "In the event rent is not received prior to the 4th of the month, "
        "Tenant agrees to pay a $25 late fee, plus an additional $5 per day "
        "for every day thereafter until the rent is paid."
    )

    terms = extract_fee_terms(clause)
    print(f"extracted terms: {terms}\n")

    for days_late in [1, 5, 10, 30]:
        exposure = compute_late_fee_exposure(
            terms.get("flat_fee"), terms.get("daily_fee"), days_late
        )
        print(f"{days_late} days late -> total exposure: ${exposure}")