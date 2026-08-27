# llm.py
# One place that builds a chat model and falls back when the provider fails.
#
# This exists because the Reviewer took the whole app down. The classifier had a
# fallback and the Reviewer did not, and they run in the same request: a Groq
# daily-limit error inside reviewer_node crashed a document analysis that the
# classifier would have survived.
#
# A fallback that only covers some of the calls in a request is not a fallback.

import os

DEFAULT_MODEL = "google/gemini-3.6-flash"
DEFAULT_PROVIDER = "openrouter"

# When the primary fails, drop to the free model rather than failing the request.
# Set CLAUSEGUARD_FALLBACK="" to disable.
FALLBACK_MODEL = os.environ.get("CLAUSEGUARD_FALLBACK", "openai/gpt-oss-120b")
FALLBACK_PROVIDER = "groq"

MAX_OUTPUT_TOKENS = 2048

# Circuit breaker. Without it, a provider that is down is rediscovered on every
# single call: eight concern categories meant eight failed calls before eight
# fallback calls. The failure is fast, but it is pure waste and it scales with
# the number of categories. Once a model has failed, stop trying it.
_DEAD = set()


def reset_circuit_breaker():
    """Forget which models have failed. Call between documents, or in tests."""
    _DEAD.clear()


def _require_key(name, provider):
    """Fail with a sentence that says what to do, not a bare KeyError.

    This matters on Streamlit Cloud specifically. Secrets set there are exposed
    as environment variables, so a missing one shows up at the first model call,
    deep inside a worker thread, as KeyError('OPENROUTER_API_KEY'). That is a
    hostile way to learn you forgot to paste a key.
    """
    key = os.environ.get(name)
    if not key:
        raise RuntimeError(
            f"{name} is not set, so the {provider} provider cannot start. "
            f"Locally: put it in .env. On Streamlit Cloud: Settings > Secrets, "
            f"as a top-level {name} = \"...\" entry."
        )
    return key


def build_model(model_name=None, provider=None, temperature=0):
    """Chat model on the given provider. Reads the environment when not told."""
    model_name = model_name or os.environ.get("CLAUSEGUARD_MODEL", DEFAULT_MODEL)
    provider = provider or os.environ.get("CLAUSEGUARD_PROVIDER", DEFAULT_PROVIDER)

    if provider == "openrouter":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_name,
            temperature=temperature,
            max_retries=0,
            base_url="https://openrouter.ai/api/v1",
            api_key=_require_key("OPENROUTER_API_KEY", "openrouter"),
            max_tokens=MAX_OUTPUT_TOKENS,
        )

    if provider != "groq":
        raise ValueError(f"unknown provider {provider!r}, expected 'groq' or 'openrouter'")

    _require_key("GROQ_API_KEY", "groq")
    from langchain_groq import ChatGroq
    # max_retries=0 because the default client retries rate limits silently with
    # a sleep, which just looks like the app has frozen.
    return ChatGroq(model=model_name, temperature=temperature, max_retries=0,
                    max_tokens=MAX_OUTPUT_TOKENS)


def invoke_with_fallback(build_chain, payload, model_name=None, provider=None,
                         fallback_model=None, fallback_provider=None, label=""):
    """Run a chain, and on ANY provider-level failure rebuild it on the fallback
    model and run it once more.

    Deliberately broad: out of credit, rate limit, provider outage and auth all
    raise different exception types across three SDKs, and the point is that any
    provider failure degrades instead of breaking. The print is what stops that
    being silent, and a fallback shows in LangSmith as two calls rather than one.
    """
    model_name = model_name or os.environ.get("CLAUSEGUARD_MODEL", DEFAULT_MODEL)
    # the caller can name its own fallback. the Reviewer runs gpt-oss-120b, which
    # is the global fallback, so without this it would have no fallback at all
    # and a Groq daily limit would take the whole analysis down again.
    fb_model = fallback_model or FALLBACK_MODEL
    fb_provider = fallback_provider or FALLBACK_PROVIDER

    if model_name in _DEAD and fb_model and model_name != fb_model:
        # already known to be down in this run. skip straight to the fallback
        # rather than paying for the failure again.
        return build_chain(build_model(fb_model, fb_provider)).invoke(payload)

    try:
        return build_chain(build_model(model_name, provider)).invoke(payload)
    except Exception as e:
        if not fb_model or model_name == fb_model:
            raise
        _DEAD.add(model_name)
        print(f"  [{label or model_name} failed ({type(e).__name__}), "
              f"falling back to {fb_model} for the rest of this run]", flush=True)
        return build_chain(build_model(fb_model, fb_provider)).invoke(payload)
