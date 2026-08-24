# parsing.py
# pulling the JSON out of a model response, tolerantly.
#
# this exists because the model comparison turned out to be measuring this
# parser as much as the models. deepseek-v4-flash scored 25% coverage on the
# eval set while producing correct answers: it narrates its reasoning first and
# puts the JSON at the end, and a bare json.loads rejects the whole thing.
# gemini fences its output in ```json and lost six clauses the same way.
#
# every model decorates its output differently and all of them are defensible:
#   gpt-oss     wraps a <think>...</think> block around the answer
#   gemini      fences it in ```json ... ```
#   deepseek    narrates the reasoning, then emits the JSON at the end
#
# strategy: strip the known wrappers, and if that still is not valid JSON, scan
# for balanced {...} spans and take the last one that parses and carries the key
# we asked for. last rather than first because reasoning text sometimes contains
# brace-looking fragments before the real answer.
#
# this is a fallback, not a fix. the real fix is provider-side structured output,
# where the model cannot produce anything but the schema. this makes the
# comparison fair in the meantime.

import json
import re

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _balanced_spans(text):
    """Every balanced {...} span in the text, as (start, end) pairs.

    Brace counting rather than a regex, because JSON nests. String-aware, so a
    brace inside a quoted reason does not throw the depth off.
    """
    depth = 0
    start = None
    in_string = False
    escaped = False

    for i, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = i
            depth += 1
        elif char == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    yield start, i + 1
                    start = None


def extract_json(content, required_key=None):
    """Parse a model response into a dict, or raise ValueError.

    required_key narrows which candidate object counts as the answer, so that a
    stray {...} in the reasoning is not mistaken for the result.
    """
    if content is None:
        raise ValueError("model returned nothing")

    cleaned = _THINK_BLOCK.sub("", content).strip()
    cleaned = _CODE_FENCE.sub("", cleaned).strip()

    if not cleaned:
        raise ValueError("model returned an empty response")

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict) and (required_key is None or required_key in parsed):
            return parsed
    except json.JSONDecodeError:
        pass

    found = None
    for start, end in _balanced_spans(cleaned):
        try:
            candidate = json.loads(cleaned[start:end])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and (required_key is None or required_key in candidate):
            found = candidate

    if found is not None:
        return found

    raise ValueError(f"no parseable json object in response: {cleaned!r}")
