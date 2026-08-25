# The held-out evaluation

Written Aug 25, 2026. This is the first measurement in ClauseGuard taken on a document that
had no part in building the prompt, scored against labels two people wrote independently.

## Why it was needed

Every earlier number was a development-set number. The 53-clause set was used to write prompt
v2, to reject v4, and to select a model from seven candidates. Nothing had ever been measured
on data the prompt had not been fitted to.

## The set

Boston Housing Authority public housing lease, revision 1/15/2015. Public domain, and used in
neither the 53-clause classification set nor the 16-case retrieval set.

28 clauses, selected for coverage across the document. Not a random sample. Three long sections
were excluded because each bundles several distinct terms into one block and a single label
would be meaningless.

Two annotators labelled all 28 independently. The second committed before seeing the first.

## The result that came before the model score

**Round 1 agreement: 15 of 28, 53.6%. Cohen's kappa 0.32.**

Ten of the thirteen disagreements ran in one direction. One annotator was labelling on harm, the
prompt was classifying on typicality, and nobody had written down which one the project meant.
That single finding invalidated every score in the project and produced
`docs/06_annotation_guidelines.md`, the annotation rubric that should have existed from Phase 2.

Round 2, both annotators re-labelling against the written rubric: **18 of 28, 64.3%, kappa
0.46.**

**That improvement cannot be attributed to the rubric.** Neither round-2 pass was blind to
round 1. Two annotators who remember their previous answers agree more than two who do not.
The number is recorded, not claimed.

Remaining disagreements were adjudicated in writing, clause by clause, with the winner and the
reasoning recorded in `evaluation/datasets/held_out_gold.json`. Five went to the first
annotator, four to the second, one to a label neither had chosen.

Final gold set: 8 concerning, 14 neutral, 6 favorable. Majority-class baseline 50%.

## The model scores

Prompt v5. One run each.

| model | accuracy | coverage | recall (conc) | macro-F1 | missed | alarms | latency | cost |
|---|---|---|---|---|---|---|---|---|
| **google/gemini-3.6-flash** | **21/28 75%** [57-87%] | 100% | **100%** | 0.75 | **0** | 3 | 5.13s | $0.109 |
| openai/gpt-oss-120b | 19/28 68% [49-82%] | 100% | 88% | 0.69 | 1 | 5 | 8.40s | $0.012 |

**Zero missed concerning clauses on unseen data** is the result worth reporting. Recall on
`concerning` is the safety metric for this product: a miss means a one-sided term reaches a
person who trusted the tool to catch it.

Do not compare the 75% here against the 92% in `docs/05`. Different prompt, different clauses,
different definition. This is the first honest measurement, not a decline from a real one.

## Four clauses both models got wrong the same way

| clause | both models | gold | history |
|---|---|---|---|
| 7(D) | favorable | neutral | annotator 1 said favorable, adjudication overruled her |
| 14(A) | neutral | favorable | annotator 2 said neutral, then conceded |
| 15 | concerning | neutral | flagged during labelling as a rule 1 / rule 3 conflict |
| 16 | concerning | neutral | annotator 2 said concerning, then conceded |

On three of the four, the models line up with a position that was abandoned during adjudication.
`8(N)` shows the same pattern on one model.

This is the second time in this project that every model agreeing against a gold label has meant
something. The first time it was the definition split. This time it points at the adjudication,
and specifically at concessions made quickly under time pressure.

**These labels were not changed.** Editing a gold set after seeing which items the models missed
is fitting labels to predictions, which is the exact failure a held-out set exists to prevent.
They are recorded here as candidate problems for the next held-out set.

## What this does not establish

n=28. The confidence interval on 75% runs from 57% to 87%, so the seven-clause gap between the
two models is inside the noise.

One document, one run per model, no variance estimate.

Clause selection was by the annotator, not random, so the set reflects what a person thought was
worth labelling.

Neither round-2 labelling pass was blind, so the kappa improvement is not attributable.

**And the set is spent.** A held-out set works once. It was run before the prompt was frozen,
which means it can no longer validate a v6. Any further prompt work needs a new held-out
document and a new labelling pass. That was a process error, it is recorded here rather than
quietly absorbed, and it is the reason v5 was frozen rather than improved.

## What was frozen

Prompt **v5** is the default in `classify_clause.py`.

Model **gemini-3.6-flash** for the classifier. The deployed Streamlit app stays on
`gpt-oss-120b`, because switching means an OpenRouter key in Streamlit secrets and roughly two
cents per analysis on a public demo with no rate limiting. That is a separate decision for after
rate limiting exists.
