# Experiment: Model Comparison (Phase 3)

> **Status, Aug 25 2026: superseded by `docs/05_model_selection.md`.** Three problems. The
> accuracy denominator excluded clauses the model failed to answer, which flattered whichever
> model failed most. The few-shot examples were leaking the test set into the prompt (D1). And
> all three candidates were Groq free tier, which is not a shortlist.
>
> Replaced by a seven-model comparison across four vendors with confidence intervals, coverage,
> per-class recall and measured cost. The current default is `gemini-3.6-flash` with
> `gpt-oss-120b` as an automatic fallback.

**Question:** does the classification bias found in Phase 2 come from the prompt, or from the model? And which of the free-tier candidates is actually usable in practice, not just accurate on paper?

## Setup

Same 53 real clauses, same prompt (v2), same few-shot examples. Only the model changes between runs. All three are Groq-hosted, free tier.

## Results

| Model | Accuracy | Avg latency | Notes |
|---|---|---|---|
| `openai/gpt-oss-20b` | 79.2% (42/53) | 2.15s | Full run, no errors |
| `openai/gpt-oss-120b` | 88.5% (46/52) | 1.79s | 1 clause hit a Groq-side parsing failure (`output_parse_failed`) — their bug, not a prompt or code issue |
| `qwen/qwen3.6-27b` | 89.4% (42/47) | 11.84s | **Incomplete** — only 47 of 53 clauses were actually scored |

## Two real technical findings along the way

**1. `gpt-oss` models wrap answers in `<think>...</think>` reasoning blocks.** The first comparison run showed `gpt-oss-20b` at a much lower, misleading accuracy — not because the model was actually worse, but because our JSON parser choked on the reasoning text and those clauses got silently dropped from the denominator instead of counted. Fixed by stripping `<think>` blocks before parsing (see `classify_clause.py`). This mattered more than it sounds: excluding failed-to-parse clauses from the accuracy calculation quietly inflates the score, since a model is only graded on the clauses it managed to answer cleanly.

**2. Qwen has a daily token cap, not just a per-minute one.** Its free tier limit is 200,000 tokens/day, and this model reasons very verbosely — long `<think>` blocks burn through that budget fast. It hit the cap partway through a single 53-clause test run. The error message asks for a 15-25 minute wait, not seconds, so this isn't something a short retry can fix. Practically, this makes qwen unusable for a live demo on the free tier — one real document with a normal number of clauses could exhaust the daily budget outright.

## Decision

**Going with `openai/gpt-oss-120b`.** It's essentially tied with qwen on accuracy but measured on the *full* test set, not a partial one, it's faster, and it doesn't have a quota ceiling that breaks under realistic usage. `gpt-oss-20b` stays as a fallback for cost-sensitive routing later — its lower accuracy might still be fine for a first-pass filter before a stronger model does final review, which is worth testing once the Reviewer node exists.

## Open question this doesn't answer yet

Does the original neutral-called-concerning bias from Phase 2 actually improve with a bigger model? `gpt-oss-120b`'s errors look different in kind (a mix of both directions, including some now-neutral-called-concerning) rather than the same one-directional bias `gpt-oss-20b` showed — worth a closer look once the Reviewer node is built and can be tested against the same failure patterns directly.
