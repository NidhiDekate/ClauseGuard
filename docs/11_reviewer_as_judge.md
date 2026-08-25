# The Reviewer as a judge

Written Aug 25, 2026. E2.

## Why this exists

Every finding a user sees passes through the Reviewer. It is handed a concern category and the
clauses retrieval returned, and it decides which one actually answers the category, or that none
do.

It is an LLM-as-a-judge, it had never been named as one, and its precision and recall were unknown.
The ROADMAP claimed "does a dedicated reviewer agent measurably reduce unsupported claims?
Answered: yes" on the strength of a spot check. That claim has been withdrawn.

## Why this set, and what makes it a judge eval

The retrieval golden set already contained what a judge eval needs. Each case carries the clause
that IS the answer, the clauses that are on topic and are NOT the answer (`also_relevant_refs`),
and four categories the document genuinely does not address.

The `also_relevant_refs` are the point. The Reviewer was rebuilt from a yes/no gate into a chooser
because "guest and occupancy restrictions" retrieved `III. OCCUPANT(S)` first, and III genuinely is
about occupancy, so a strict relevance gate approves it and stops. The question was never "can it
spot irrelevance", it was **"can it tell relevant from most relevant"**.

**And the Reviewer is isolated here.** E1 measured retrieval recall@3 at 100%, so the right clause
is always among the candidates. Any miss is the Reviewer's, not retrieval's. Cases where retrieval
did fail are excluded from scoring rather than counted against the judge.

## Result

Two complete runs, identical. A third died on Groq's daily token limit and is excluded.

```
recall on answerable   11/12
absent rejected         3/4
precision of picks      92%
picked a distractor      1
```

Perfectly consistent across both runs, which is worth noting on its own: the classifier moves by
up to three clauses between identical runs, and the Reviewer did not move at all.

## The one it got wrong

**FTC, "liability and indemnification", a category that document does not address.** The Reviewer
picked clause 14, FULL DISCLOSURE, reasoning that it "explicitly states the tenant will face legal
and financial consequences for violating the agreement, directly addressing liability."

Facing consequences for breaching a lease is not an indemnity and not a liability limitation. The
distinction is subtle and it is the right one. This is a false positive on precisely the job the
node exists to do, and it is the same shape as the original failure: something on topic, mistaken
for the answer.

## The one where the golden set is probably wrong

**PA, "automatic renewal and rent increases".** The Reviewer said none of the candidates address
it. The golden set says clause II.

Clause II describes what happens at the end of the term when no renewal is made. The golden set's
own note admits the weakness: *"Weaker than the FTC clause, which says AUTOMATICALLY, but it is
still the renewal provision."*

**This mapping was flagged as one of the two most arguable in the set before any of this ran**, and
never reviewed. That prior flagging is what makes revisiting it legitimate. The label has not been
changed on the strength of this result, because changing ground truth to match a prediction is the
failure this project has spent two days undoing. It is recorded as disputed, and it needs a second
annotator, not a rerun.

If that mapping is wrong, the Reviewer is 12/12 on answerable cases. That number is not being
claimed.

## Two reporting bugs found in this eval, both of which flattered the result

**Distractor picks were counted only on answerable cases.** The summary printed "picked a
DISTRACTOR: 0" while the Reviewer had picked a distractor on the FTC absent case. Same failure,
different bucket, hidden by the metric that existed to expose it. Now counted across all cases.

**A run that died on rate limits was summarised as 0/0 and 0% precision**, sitting in the table
next to real results and reading like a catastrophic score rather than an absent one. Failed runs
are now excluded and labelled.

That is the sixth and seventh instance in this project of a measurement failing at something other
than the thing being measured.

## What this does not establish

n=16, of which 12 are answerable and 4 absent. One case is 8 percentage points on recall and 25
points on absent rejection.

Two runs, not three. The third was lost to a rate limit.

The Reviewer runs `gpt-oss-120b`, hardcoded, while the classifier runs `gemini-3.6-flash` from the
environment. That is an unexamined default rather than a decision, and if the false positive
matters, running the Reviewer on the better model is the first thing to try.

Two documents, both leases. No Terms of Service, where "not addressed" is a much more common
answer and false positives would be more costly.
