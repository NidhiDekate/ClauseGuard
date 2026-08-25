
# Runs the clause classifier using the prompt in clause_classifier_v2.txt.

import json
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from groq import RateLimitError
from langchain_core.prompts import ChatPromptTemplate, FewShotChatMessagePromptTemplate
from langchain_groq import ChatGroq

sys.path.append(str(Path(__file__).resolve().parents[1]))
from parsing import extract_json  # noqa: E402

load_dotenv()

# which prompt version to run. was hardcoded, so comparing two versions meant
# editing this file, which is a bad way to run an experiment: the thing you are
# varying should not live inside the code under test.
#   CLAUSEGUARD_PROMPT_VERSION=v4 python src/prompts/test_classifier.py
# v5 is the frozen default. v2 classified on typicality, which contradicted the
# harm-based labels in both gold sets and made six clauses permanently unfixable.
# See docs/06_annotation_guidelines.md for the definition and docs/07 for the
# held-out result.
PROMPT_VERSION = os.environ.get("CLAUSEGUARD_PROMPT_VERSION", "v5")
SYSTEM_PROMPT_PATH = Path(f"src/prompts/system_prompts/clause_classifier_{PROMPT_VERSION}.txt")
FEW_SHOT_PATH = Path("src/prompts/few_shot_examples/clause_classification_examples.json")

# same reasoning as the prompt version above: the thing being varied should not
# live inside the code under test.
#   CLAUSEGUARD_MODEL=openai/gpt-oss-20b python src/prompts/test_classifier.py
MODEL_NAME = os.environ.get("CLAUSEGUARD_MODEL", "openai/gpt-oss-120b")

# the only three labels this system understands. anything else is a bad response,
# not a new category.
VALID_LABELS = {"concerning", "neutral", "favorable"}


def _load_system_prompt():
    raw = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    # the prompt has a literal json example in it, which langchain tries to read
    # as a {variable} if we don't escape the braces first. cost me an hour to find.
    return raw.replace("{", "{{").replace("}", "}}")


def _load_few_shot_examples():
    return json.loads(FEW_SHOT_PATH.read_text(encoding="utf-8"))


def _build_model(model_name):
    """Chat model for the given id, on whichever provider is selected.

    Groq is the default and what the deployed app uses. OpenRouter exists so
    model selection is not limited to whatever one provider happens to offer:
    Groq is down to two production language models, which is not a shortlist.

        CLAUSEGUARD_PROVIDER=openrouter OPENROUTER_API_KEY=... \
        CLAUSEGUARD_MODEL=anthropic/claude-opus-5 python src/prompts/test_classifier.py

    max_retries=0 on both because the default clients retry rate limit errors
    silently with a sleep, which just looks like the script froze. Handled
    explicitly in classify_clause instead so there is a message.
    """
    provider = os.environ.get("CLAUSEGUARD_PROVIDER", "groq")

    if provider == "openrouter":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model_name,
            temperature=0,
            max_retries=0,
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ["OPENROUTER_API_KEY"],
        )

    if provider != "groq":
        raise ValueError(f"unknown CLAUSEGUARD_PROVIDER={provider!r}, expected 'groq' or 'openrouter'")

    return ChatGroq(model=model_name, temperature=0, max_retries=0)


def build_classifier_chain(model_name):
    system_prompt = _load_system_prompt()
    examples = _load_few_shot_examples()

    example_prompt = ChatPromptTemplate.from_messages([
        ("human", "Clause: {clause}"),
        ("ai", '{{"label": "{label}", "reason": "{reason}"}}'),
    ])

    few_shot_prompt = FewShotChatMessagePromptTemplate(
        example_prompt=example_prompt,
        examples=examples,
    )

    final_prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        few_shot_prompt,
        ("human", "Clause: {clause}"),
    ])

    return final_prompt | _build_model(model_name)


def classify_clause(clause_text, model_name=MODEL_NAME, with_usage=False):
    chain = build_classifier_chain(model_name)

    try:
        response = chain.invoke({"clause": clause_text})
    except RateLimitError as e:
        if "tokens per day" in str(e) or "TPD" in str(e):
            # daily quota, not per-minute - a 20s retry won't help, groq's own
            # message says to wait 10-25+ minutes. just fail this one.
            raise ValueError(f"hit daily token limit, skipping: {e}") from e
        print("\n  [rate limited, waiting 20s before retrying this one]", end=" ", flush=True)
        time.sleep(20)
        response = chain.invoke({"clause": clause_text})  # only retrying once, not looping forever

    # every model decorates its output differently: gpt-oss wraps a <think>
    # block, gemini fences in ```json, deepseek narrates first. see src/parsing.py
    result = extract_json(response.content, required_key="label")

    # parseable json is not the same as correct json. an unexpected label used to
    # travel all the way to the streamlit ui, which indexes a dict with it, so a
    # stray label crashed the page with a KeyError after the user had already
    # waited a full minute. rejecting it here means report_node's existing
    # ValueError handling turns it into a finding without a label instead.
    label = result.get("label")
    if label not in VALID_LABELS:
        raise ValueError(f"model returned an unexpected label: {label!r}")
    if not result.get("reason"):
        raise ValueError(f"model returned no reason for label {label!r}")

    if with_usage:
        # real token counts from the provider, so the cost column in a model
        # comparison is measured rather than guessed from a tokenizer that
        # does not match the model being priced.
        usage = getattr(response, "usage_metadata", None) or {}
        return result, {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
        }

    return result


if __name__ == "__main__":
    # quick manual sanity check, run this file directly to try one clause
    test_clause = (
        "Tenant agrees to pay a $500 fine if smoking is detected, "
        "determined solely at Landlord's discretion."
    )
    print(json.dumps(classify_clause(test_clause), indent=2))
