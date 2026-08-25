# Few-shot vs zero-shot, and the formatting instruction that moved labels

Written Aug 25, 2026. Covers E8 and the v6 output-format change that came out of it.

## Why E8 existed

Few-shot examples were in the prompt from the first day and were never tested against zero-shot.
They were not free:

- Nine examples ride on **every single call**. This is where the Phase 3 cost estimate came out
  3.5x low.
- They are the surface that leaked the eval set into the prompt (D1). Eight of the original nine
  examples were verbatim clauses from the 53-clause test set. `evaluation/check_leakage.py` guards
  against that returning. Deleting the examples removes the surface entirely.

## Setup

Prompt v5, model `openai/gpt-oss-120b`, both arms run through OpenRouter so neither is distorted
by Groq's free-tier rate limiting. Same 53 clauses, re-derived against
`docs/06_annotation_guidelines.md`. Majority-class baseline 67.9%.

`CLAUSEGUARD_FEW_SHOT=0` switches the arm. The setting is recorded both in the report body and in
the report filename, so a result cannot be read without knowing which arm produced it.

## Result

```
                 acc     cov   recall(conc)  missed  macroF1  tokens_in    cost
few-shot       42/53    96%       92%          3      0.697     71,006   $0.0181
zero-shot      42/53    98%       94%          2      0.660     31,690   $0.0116
```

**A dead tie on accuracy.** So the decision is made on everything else, which is the honest way to
make it.

Zero-shot is better on coverage, better on recall of `concerning` which is the safety metric for
this product, misses one fewer concerning clause, uses **55% fewer input tokens**, and costs 36%
less.

It is worse on macro-F1, 0.660 against 0.697. That gap is entirely the neutral class: recall 27%
against 18%. Both of those are broken, and they are broken because of v5's known overcorrection
toward `concerning`, which few-shot examples do not fix. Choosing between two failing numbers is
not a reason to keep 40,000 tokens per run.

**Decision: delete the few-shot examples.** Same accuracy, cheaper, marginally safer, and D1
becomes structurally impossible rather than guarded.

## The defect E8 exposed

Both arms produced truncated JSON:

```
few-shot   XXXI   '{"label": "concerning", "reason": "...you could pay out-of-pocket if they break."'
zero-shot  2.13   '{"label": "concerning", "reason": "...it still poses a material risk to you'
```

Cut off mid-string. `src/parsing.py` cannot recover these, because the object genuinely never
closed. `max_tokens` was never set anywhere in the project, so the provider default applied.

Output was averaging about 250 tokens per call for a two-field JSON object that needs perhaps 40.
`gpt-oss` models emit reasoning tokens that share the output budget with the visible answer, so a
long deliberation leaves too little room for the JSON.

**This was new under v5.** v5's rule requires the reason to state two things in one sentence, what
the clause does and whether it is standard, which makes every reason longer and pushes the long
ones into the ceiling. A prompt change made for label-quality reasons introduced an output-format
failure.

## v6

v6 is v5 plus one line: the reason must be under 30 words, and the model should decide before
writing rather than reasoning at length. `max_tokens=512` is now set explicitly on both providers.

**The rubric text is byte-identical between v5 and v6.** v5 was not edited in place; it is frozen
and referenced in `docs/07`.

```
                 acc     cov   recall(conc)  missed  tokens_out    cost
v5 zero-shot   42/53    98%       94%          2       11,346    $0.0116
v6 zero-shot   43/53   100%       97%          1       14,727    $0.0139
```

Coverage reached 100%. That was the point of the change and it worked.

## Two predictions that were wrong, and what they cost

**"Output tokens will drop."** They rose 30%. The visible reason is shorter and the total output is
larger. The likely explanation is that reasoning tokens dominate and the instruction either did
nothing or backfired, but that cannot be shown, because **the eval does not log reasoning tokens
separately from answer tokens.** OpenRouter reports the split and `eval_models.py` discards it.
Recorded as a measurement gap rather than papered over with a plausible story.

**"Accuracy will not move."** It moved, and how it moved matters more than the number.

```
real_002 2.13         None       -> concerning   RECOVERED  (the truncation fix, intended)
facebook ban_evasion  concerning -> neutral      RECOVERED  (unintended, now correct)
facebook 30_day_notice favorable -> neutral      BROKE      (unintended, now wrong)
```

Three predictions changed. Two improved, one regressed. Net +1.

**A pure formatting instruction changed two classifications that have nothing to do with
formatting.** The classification rules are identical between the two prompts. Telling the model to
be brief, and to decide before writing, changed how much it deliberated, and that changed what it
decided.

This is the same family as the parser finding in `docs/05`: something that looked like plumbing
turned out to be part of the decision. It also means **43 against 42 is not a clean improvement.**
It is one clause net inside a set where three moved, which is noise-shaped.

## Decision

**v6, zero-shot, is the frozen configuration**, chosen on coverage and safety rather than accuracy:
100% coverage against 98%, one missed concerning clause against two, recall 97% against 94%. Cost
rises from 1.16 to 1.39 cents per 53 clauses, which is not a real constraint at this scale.

`src/prompts/few_shot_examples/clause_classification_examples.json` and
`evaluation/check_leakage.py` are removed. The leakage they concerned cannot occur without a
few-shot surface.

## What this does not establish

n=53. One run per arm, so no variance estimate, and this project has already seen the same model
score 45 and 46 on identical inputs an hour apart.

Both arms were scored against labels derived by one annotator applying the rubric, with a second
reviewing. Weaker than the two blind passes used for the held-out set.

The reasoning-token hypothesis is unverified and will stay unverified until the eval captures the
usage split.

The 30-word cap was not tuned. 30 was chosen because it comfortably fits a two-part sentence, not
because anything was measured at 20 or 40.
