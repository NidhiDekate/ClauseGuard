# Experiment: Prompt Iteration on the Clause Classifier (Phase 2)

> **Status, Aug 25 2026: the numbers below are void.** Eight of the nine few-shot examples in
> the prompt were verbatim clauses from this same 53-clause test set (D1). Every version was
> scored on data whose answers were in its own prompt. The model used here,
> `llama-3.1-8b-instant`, has also been deprecated by Groq.
>
> The bias-fixing conclusion may still hold; the accuracy figures do not. Prompt v2 was later
> replaced entirely after the harm-vs-typicality finding in `docs/06`, and the current prompt is
> v6 zero-shot with no examples at all. See `docs/09`.

**Question:** can few-shot examples and explicit rules fix a systematic classification bias without introducing a worse one?

## Setup

53 real clauses from `evaluation/datasets/test_set.json`, scored against `llama-3.1-8b-instant` (the model available at the time — later deprecated by Groq, see Phase 3). Same test set, same scoring script, only the prompt changes between versions.

## Results

| Version | Accuracy | Change |
|---|---|---|
| v1 (baseline) | 86.8% (46/53) | — |
| v2 (added boilerplate examples + a distinguishing rule) | **88.7% (47/53)** | bias shrank, one fix generalized to a clause not directly shown as an example |
| v3 (broadened the rule further) | 86.8% (46/53) | same score as baseline, but a worse failure pattern |

## What actually happened

**v1's errors were all one direction** — real neutral clauses (standard defensive boilerplate like "no interest on deposits," "no liability for damages") were being flagged as concerning. The prompt had no example teaching it that negative-sounding language can still be standard and expected.

**v2 added that missing example type**, plus a rule distinguishing genuine risk from boilerplate that merely sounds negative. Accuracy improved, and — more importantly — one fix worked on a clause that wasn't part of the new examples (Facebook's no-damages-liability disclaimer), suggesting real generalization rather than memorizing the new examples.

**v3 pushed the same idea further**, adding a stronger rule about not reacting to negative phrasing. Accuracy dropped back to baseline — but the composition of errors changed for the worse: two clauses that were correctly flagged as concerning in v1 and v2 (a no-appliance-repair clause, and a liability clause shifting risk onto the tenant except when damage is "solely" the landlord's fault) got misclassified as neutral instead. The broadened rule couldn't distinguish "standard disclaimer" from "one-sided risk transfer worded like a standard disclaimer" — which is precisely the distinction this system exists to make.

## Decision

Kept v2. Reverted rather than attempting a v4 narrower rule — the remaining bias in v2 is small and consistent in direction (over-cautious, not under-cautious), and Phase 3's model comparison was the more useful next step to determine whether the residual bias is a prompt ceiling or a model limitation.

## Takeaway

Broadening a rule to fix false positives can silently trade them for false negatives — and a false negative on a genuinely concerning clause is a worse error than a false positive on a safe one. Checking the *direction* and *severity* of errors after a prompt change matters more than watching the aggregate accuracy number alone.
