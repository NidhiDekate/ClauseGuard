# Faithfulness: does the explanation follow from the clause?

> **Rerun Aug 25, 2026.** The first version of this document was written as though the clause-text
> restoration described below had already been applied. It had not. The scripts existed, the
> write-up was drafted from what they were going to do, and `git status` caught it hours later. The
> first number, 86.8%, was measured on the abridged set.
>
> The restoration has now been applied and the whole thing rerun end to end: a fresh classification
> pass on the restored text, then a fresh judging pass on those explanations. **Every number below
> is from the rerun.** The old numbers are kept where they are useful for comparison and are
> labelled as such.
>
> Writing up a result as though a command had run is the exact failure this document is about,
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
47 of 53 explanations fully grounded   88.7%

label correct + reason grounded : 39
label correct + reason invented :  5   <- accuracy scored all five as wins
label wrong   + reason grounded :  8
label wrong   + reason invented :  1
```

The cross-tab is the point. **Five explanations carry the right label and a claim the clause does
not support.** Every other metric in this repository counts those five as successes.

For comparison, the same eval on the abridged gold set scored 46 of 53, 86.8%, with six in the
right-label-invented cell. That comparison is weaker than it looks and the next section says why.

## What the restoration actually changed, and what it did not

The restored run scored 44 of 53 on accuracy. The abridged runs scored 41, 43, 44, 45 and 46 across
five runs of the same model at temperature 0. **44 sits inside that spread, so the restoration
moved accuracy by an amount this project cannot measure.**

Faithfulness went 86.8% to 88.7%, which is one clause. Also not a result.

There is a second problem with reading anything into the change. The rerun regenerated the
explanations as well as the clause text, and the classifier writes a different sentence every time.
So two things moved at once: the input the model saw, and the wording it produced. A clause can
flip from unfaithful to faithful because the gold text was fixed, or because the model happened to
write a more careful sentence this time. **Nothing in this design separates those.**

What the restoration did fix is specific and it is not a number. `pa XXXV` was previously flagged
for inventing an eviction consequence. The lease says exactly that. Our dataset had cut it out with
an ellipsis, so the model had never seen it. That verdict was wrong, and it was wrong because of us.

## The five that carry a right label and an unsupported claim

**Inventing a consequence the clause does not create.**

`pa XXXV`, the DEFAULT clause, now flagged for a different span than before:

```
model: "...allows your landlord to evict you and DEMAND ALL REMAINING RENT IMMEDIATELY
        if you breach the agreement"
```

Eviction is in the clause. Rent acceleration is not. The model attached a second, more expensive
remedy to a clause that does not grant it.

`ftc 12` says a tenant "may be held financially responsible" and does not say for what:

```
model: "...you could be held financially liable if YOU FAIL TO REPORT MAINTENANCE ISSUES QUICKLY"
```

The clause names no trigger. The model supplied one, and it reads as a rule the tenant could
actually follow.

**Importing a term from a different clause.**

```
clause: binding arbitration
model:  "...takes away your right to resolve disputes in court or JOIN A CLASS ACTION"
```

The class action waiver is real and it is a separate clause in the same document, sitting in this
test set under its own reference. The model merged them. The conclusion a reader draws is true of
the contract and false of the clause, which is exactly the failure mode a per-clause citation
product is supposed to make impossible.

**Overstating what the clause grants.**

```
clause: your content can be licensed to third parties
model:  "...allows the platform to share or PROFIT FROM your content with outside companies
         WITHOUT YOUR CONTROL"
```

Licensing to third parties is in the clause. Profiting from it is an inference. So is the absence
of control.

**Stating an absence the clause is silent on.**

```
clause: your identity is used in ads shown to other users
model:  "...use your personal identity in advertisements WITHOUT EXTRA PERMISSION OR PAYMENT"
```

The clause says nothing about permission or payment. The model says there is none. A reader
concludes the contract rules out compensation. It does not. It is silent, and **silence in a
contract is not a term against you.**

This was the dominant pattern in the abridged run, three of six. In the rerun it is one of five.
Whether that is the restoration, the rewording, or noise at n=53 is not something one run can say.

## And one that is wrong in both label and reasoning

`ftc 1` is an automatic renewal clause. Gold label neutral, model said concerning:

```
model: "...you could owe extra rent if you fail to give 30 DAYS' WRITTEN NOTICE before moving out"
```

There is no notice period in the clause. The model produced a specific, actionable, invented
number. This is the worst shape a failure can take here, because "30 days' written notice" is the
kind of detail a person would write on a calendar.

## What to do about it

Not fixed here, because the fix is a prompt change and validating a prompt change needs a held-out
set, which is spent.

Two candidate rules, in the order the evidence supports:

1. **Do not state that something is absent unless the clause says it is absent.** Silence is not a
   term.
2. **Do not attribute a consequence, a number, or a condition that is not in this clause, even if
   it is elsewhere in the document.**

The second one is new to this run and it is the more interesting of the two, because the class
action example shows the model producing a claim that is true about the contract while being false
about the clause it cites. A citation-based product cannot tolerate that, and no accuracy metric
would ever surface it.

Both should be the first experiment when a second held-out set exists.

## What this does not establish

n=53. One classification run, one judging run.

No variance estimate on the judge. A second judge, or the same judge twice on the same
explanations, would say how stable 88.7% is. Nothing here does.

The judge is a single model with no measured precision or recall of its own. It was spot-checked by
hand on seven verdicts in the first run and was correct on all seven, including two where it was
right and our dataset was wrong. That is reassuring and it is not a measurement.

88.7% is measured on gemini's explanations only. The fallback model was never judged.

And the comparison against the abridged run confounds two changes at once. It is reported because
hiding it would be worse, not because it supports a conclusion.
