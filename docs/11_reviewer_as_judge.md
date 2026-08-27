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

## Which model should judge

The Reviewer was later run on `gemini-3.6-flash`, the model the classifier uses, to see whether
the better classifier is also the better judge.

```
                    recall    absent    precision   total correct
gpt-oss-120b        11/12      3/4         92%         14/16
gemini-3.6-flash    10/12      4/4        100%         14/16
```

**Tied on total correct, differing only in which error they make.** gemini is more conservative:
no false positives, two false negatives. gpt-oss catches one more real clause and wrongly flags a
category the document does not address.

**Decision: `gpt-oss-120b`**, on the same principle that makes recall the classifier's safety
metric. A Reviewer false negative reaches the user as "not addressed in this document", which is a
false statement about their contract: the PA lease does have a late fee clause, $25 plus $5 a day
uncapped. A false positive shows them a real clause under the wrong heading, which they can read
and dismiss. **The miss is also a lie; the false alarm is only noise.**

At n=16 this is one case each way and inside noise. It is a decision about which error costs more,
not a measured difference, and the code says so.

The two nodes now run different models and fall back to each other: classifier on gemini falling
back to gpt-oss, Reviewer on gpt-oss falling back to gemini. Neither can end up as its own
fallback, which had already taken the app down once.

## The one where the golden set is probably wrong

**PA, "automatic renewal and rent increases".** The Reviewer said none of the candidates address
it. The golden set says clause II.

Clause II describes what happens at the end of the term when no renewal is made. The golden set's
own note admits the weakness: *"Weaker than the FTC clause, which says AUTOMATICALLY, but it is
still the renewal provision."*

**This mapping was flagged as one of the two most arguable in the set before any of this ran**, and
never reviewed. The label has not been changed on the strength of this result.

**Withdrawn, later the same day.** Running the Reviewer on `gemini-3.6-flash` gave the opposite
answer: gemini accepts clause II and agrees with the golden set. So the better explanation is that
`gpt-oss-120b` has a bias toward "none of these" on borderline renewal language, not that the label
is wrong.

That is worth recording as its own mistake. Twice this week, every model disagreeing with a gold
label meant the label was wrong, and I generalised from that to "a model disagreeing means look at
the label." **Two vendors agreeing is evidence. One model repeating itself is one observation
repeated.** The mapping stays as disputed-but-probably-fine, and it still wants a second annotator
rather than another model.

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

The Reviewer runs `gpt-oss-120b` and the classifier runs `gemini-3.6-flash`. That was an unexamined
default when this was written and is now a decision, made on which error costs more rather than on a
measured difference. See the section above.

**And in production it did not hold.** On the first live deployment Groq rate limited, the circuit
breaker sent every Reviewer call to gemini, and the app ran one model on both nodes. The judge and
the system under test were the same model, which is the arrangement this document argues against,
and nothing on screen said so. A run that falls back now says so in the report. Entry 31 of the
journal has the full account.

Two documents, both leases. No Terms of Service, where "not addressed" is a much more common
answer and false positives would be more costly.
