
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
PROMPT_VERSION = os.environ.get("CLAUSEGUARD_PROMPT_VERSION", "v6")
SYSTEM_PROMPT_PATH = Path(f"src/prompts/system_prompts/clause_classifier_{PROMPT_VERSION}.txt")
FEW_SHOT_PATH = Path("src/prompts/few_shot_examples/clause_classification_examples.json")

# same reasoning as the prompt version above: the thing being varied should not
# live inside the code under test.
#   CLAUSEGUARD_MODEL=openai/gpt-oss-20b python src/prompts/test_classifier.py
MODEL_NAME = os.environ.get("CLAUSEGUARD_MODEL", "google/gemini-3.6-flash")
MODEL_PROVIDER = os.environ.get("CLAUSEGUARD_PROVIDER", "openrouter")

# When the primary provider fails, fall back rather than failing the request.
# gemini-3.6-flash scored best on the held-out set (docs/07) but runs on paid
# credit with auto top-up deliberately off, so the balance can run out. Groq's
# free tier then keeps the demo alive on the second-best model instead of
# returning an error. Set CLAUSEGUARD_FALLBACK="" to disable.
FALLBACK_MODEL = os.environ.get("CLAUSEGUARD_FALLBACK", "openai/gpt-oss-120b")
FALLBACK_PROVIDER = "groq"

# E8: few-shot examples were assumed from the start and never tested against
# zero-shot. They are not free. Nine examples ride on every single call, which
# is where the Phase 3 cost estimate went 3.5x wrong, and they are the surface
# that leaked the eval set into the prompt in the first place (D1). If they earn
# nothing, deleting them makes that class of bug structurally impossible rather
# than guarded against by evaluation/check_leakage.py.
#   CLAUSEGUARD_FEW_SHOT=0 python evaluation/eval_models.py --only ...
# E8 result: few-shot and zero-shot tied at 42/53. Zero-shot used 55% fewer
# input tokens, cost 36% less, missed one fewer concerning clause, and removed
# the surface that leaked the eval set into the prompt in the first place (D1).
# Default is now zero-shot. See docs/09_few_shot_ablation.md.
USE_FEW_SHOT = os.environ.get("CLAUSEGUARD_FEW_SHOT", "0") not in ("0", "false", "no")

# the only three labels this system understands. anything else is a bad response,
# not a new category.
VALID_LABELS = {"concerning", "neutral", "favorable"}

# Output budget per call.
#
# This is a runaway guard, NOT a cost control: providers bill for tokens actually
# generated, so a high cap costs nothing when it is not reached.
#
# It has to be high because reasoning and thinking tokens are drawn from the same
# budget as the visible answer, and how many a model spends is not knowable in
# advance. 512 was enough for gpt-oss-120b and starved gemini-3.6-flash, which
# thinks first and had about ten words left for the JSON. Setting this too low
# looks exactly like a parser bug: valid output, cut off mid-string.
#
# The real defence against long output is the 30-word cap in prompt v6. This is
# the backstop behind it.
MAX_OUTPUT_TOKENS = 2048


def _load_system_prompt():
    raw = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    # the prompt has a literal json example in it, which langchain tries to read
    # as a {variable} if we don't escape the braces first. cost me an hour to find.
    return raw.replace("{", "{{").replace("}", "}}")


def _load_few_shot_examples():
    """Only called when CLAUSEGUARD_FEW_SHOT=1. The examples file was deleted
    after E8; set the variable only if you restore it."""
    if not FEW_SHOT_PATH.exists():
        raise FileNotFoundError(
            f"{FEW_SHOT_PATH} was removed after E8 showed the examples earned nothing. "
            "See docs/09_few_shot_ablation.md. Restore the file to run the few-shot arm.")
    return json.loads(FEW_SHOT_PATH.read_text(encoding="utf-8"))


def _build_model(model_name, provider=None):
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
    provider = provider or MODEL_PROVIDER

    if provider == "openrouter":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model_name,
            temperature=0,
            max_retries=0,
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ["OPENROUTER_API_KEY"],
            max_tokens=MAX_OUTPUT_TOKENS,
        )

    if provider != "groq":
        raise ValueError(f"unknown CLAUSEGUARD_PROVIDER={provider!r}, expected 'groq' or 'openrouter'")

    # max_tokens set explicitly. gpt-oss models emit reasoning tokens that count
    # against the output budget, so a long chain of thought can leave too little
    # room for the JSON and the response is cut off mid-string. src/parsing.py
    # cannot recover that: the object genuinely never closed. Observed on 2 of 53
    # clauses under v5, which produces longer reasons than v2 did.
    return ChatGroq(model=model_name, temperature=0, max_retries=0,
                    max_tokens=MAX_OUTPUT_TOKENS)


def build_classifier_chain(model_name, use_few_shot=None, provider=None):
    system_prompt = _load_system_prompt()
    if use_few_shot is None:
        use_few_shot = USE_FEW_SHOT

    messages = [("system", system_prompt)]

    if use_few_shot:
        example_prompt = ChatPromptTemplate.from_messages([
            ("human", "Clause: {clause}"),
            ("ai", '{{"label": "{label}", "reason": "{reason}"}}'),
        ])
        messages.append(FewShotChatMessagePromptTemplate(
            example_prompt=example_prompt,
            examples=_load_few_shot_examples(),
        ))

    messages.append(("human", "Clause: {clause}"))

    return ChatPromptTemplate.from_messages(messages) | _build_model(model_name, provider)


def classify_clause(clause_text, model_name=MODEL_NAME, with_usage=False, use_few_shot=None):
    chain = build_classifier_chain(model_name, use_few_shot=use_few_shot)

    try:
        response = chain.invoke({"clause": clause_text})
    except Exception as e:
        # Provider-level failure: out of credit, provider outage, auth. Fall back
        # to the free model rather than failing the user's request. Deliberately
        # broad, because the point is that ANY provider failure degrades instead
        # of breaking, and the exception types differ by SDK.
        if not FALLBACK_MODEL or model_name == FALLBACK_MODEL:
            raise
        print(f"\n  [{model_name} failed ({type(e).__name__}), "
              f"falling back to {FALLBACK_MODEL}]", end=" ", flush=True)
        chain = build_classifier_chain(FALLBACK_MODEL, use_few_shot=use_few_shot,
                                       provider=FALLBACK_PROVIDER)
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
