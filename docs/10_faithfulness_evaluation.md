# Faithfulness: does the explanation follow from the clause?

> **Correction, later on Aug 25.** This document originally read as though the clause-text
> restoration below happened BEFORE the faithfulness run. It did not. The scripts were written,
> the write-up was drafted as if they had been executed, and `git status` caught it hours later.
>
> **So the 86.8% was measured on the abridged set.** At least one of the six unfaithful verdicts,
> `pa XXXV`, is an artifact of text our own dataset had removed rather than a model hallucination.
> The restoration has now been applied and the eval has NOT been rerun against it. Treat every
> number here as provisional until it is.
>
> Writing a result up as though a command had run is the exact failure this document is about,
> committed inside the document about it.

Written Aug 25, 2026. E3.

## Why this exists

The README's promise is that every conclusion traces to the text it came from. Nothing checked it.

Accuracy tells you whether the **label** is right. It says nothing about whether the **sentence** is
invented. A right label with a fabricated justification scores as a win on every metric this
project had, and it is the worst thing the product can do: a confident sentence, in plain English,
telling someone something about their lease that the lease does not say.

## Setup

53 clauses, prompt v6 zero-shot, classified by `gemini-3.6-flash`. Each explanation is then judged
against its clause.

**The judge is `claude-opus-5`.** Not because it is the strongest, but because **it is not the
model being judged.** A model grading its own output prefers it. Different vendor, different
family. `evaluation/eval_faithfulness.py` refuses to run if the judge and the system under test are
the same model, so this cannot be undone by accident later.

The judge is asked one question only: is every factual statement in the explanation supported by
the clause. It is explicitly not judging whether the label is right, and it is told that a claim
about the wider world such as "this is common in leases" is out of scope, because prompt v6
requires the model to make exactly that claim.

Zero extra classifier calls: the reasons are read from an existing report. About fifty cents.

## Result

```
46 of 53 explanations fully grounded   86.8%

label correct + reason grounded : 38
label correct + reason invented :  6   <- accuracy scored all six as wins
label wrong   + reason grounded :  8
label wrong   + reason invented :  1
```

The cross-tab is the point. **Six explanations carry the right label and a claim the clause does
not support.** Every metric in this repository counts those as successes.

## The pattern: inventing the absence of a protection

Three of the seven are the same failure.

```
clause: "Your content can be licensed to third parties"
model:  "...allows the company to share or sell rights to your content to outside parties
         WITHOUT PAYING YOU"

clause: "Your identity is used in ads that are shown to other users"
model:  "...lets the company use your name and image in advertisements to other users
         WITHOUT COMPENSATING YOU"

clause: "this Service will assume your consent to changes of terms merely from your usage"
model:  "...the service can change your contract WITHOUT DIRECTLY NOTIFYING or asking you"
```

In each case the clause is **silent** on the point, and the model states there is no protection.

This is not vagueness or overstatement. It is a specific factual claim about the person's rights,
asserted in the confident one-sentence format the product is built around. A user reading "without
paying you" reasonably concludes the contract rules out compensation. It does not. It says nothing.

Silence in a contract is not the same as a term against you, and the classifier does not know the
difference.

## The other four

**Inventing a consequence the clause does not create.**

`pa XXXIII` limits guests to 48 hours and states no penalty. The model added "could put your
housing at risk if breached."

`ftc 12` says a tenant "may be held financially responsible" without saying for what. The model
added "personally responsible for costly repairs."

`pa XXXV` is the DEFAULT clause, which covers failure to comply with lease provisions. The model
wrote "allows your landlord to evict you based on a mere arrest." The arrest language sits
elsewhere in the lease; this clause does not make that link.

**And one that is wrong in both label and reasoning.** `ban_evasion_prohibited` says banned users
are not allowed to re-register. The model wrote that it "permanently bars you from ever creating a
new account." Neither "permanently" nor "ever" is in the clause.

## What this eval found that was not about the model

The first run flagged `pa XXXV` as unfaithful. My first reading was that the model had invented an
eviction consequence. It had not: the lease says exactly that, and **our own dataset had cut it
out.** Seven of the 53 gold clauses were stored abridged with an ellipsis, so the classifier had
never seen the full text.

Checking the sources found worse. The clause stored as `lease_real_002 / 2.13` was two unrelated
clauses spliced together under a third clause's number: the first half from 2.1 Notice to Quit, the
second from 2.21 Reporting of Past Rent Owed, filed under 2.13, which is Lead Based Paint. And 2.1
was already in the set separately, so that waiver was counted twice.

All seven are now restored from source, and the fabricated clause replaced with the real 2.21.

**The judge was right, the model was right, and the ground truth was wrong.** That combination is
the one nothing else in this project could have detected.

## A side effect worth recording

After restoring the clause text, gemini scored 44, 44, 44 across three runs, where four earlier
runs on the abridged set gave 42, 43, 44, 44.

Plausible mechanism: truncated clauses are ambiguous, ambiguity produces borderline decisions, and
borderline decisions flip between runs. Three runs is not proof.

**And the stability is partly an illusion.** Two clauses still flip between runs in opposite
directions, so nine are wrong every time and the total is 44 every time. An aggregate that is
stable because its errors cancel is not a stable system, and only per-clause reporting shows the
difference.

## What to do about it

Not fixed here, because the fix is a prompt change and prompt changes need a held-out set to
validate, which is spent.

The obvious candidate is a rule in the prompt: **do not state that something is absent unless the
clause says it is absent.** Silence is not a term. That is one sentence, it targets three of the
six failures directly, and it should be the first experiment when a second held-out set exists.

## What this does not establish

n=53, one classification run, one judging run. No variance estimate on the judge itself, which is
the obvious gap: a second judge, or the same judge twice, would say how stable 86.8% is.

The judge is a single model with no measured precision or recall of its own. It was spot-checked
by hand on seven verdicts and was correct on all seven, including two where it was right and the
dataset was wrong. That is reassuring and it is not a measurement.

86.8% is measured on gemini's explanations only. The fallback model was not judged.
