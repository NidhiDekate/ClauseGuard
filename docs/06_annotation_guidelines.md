# Annotation guidelines for clause labelling

Written Aug 25, 2026, after two annotators labelled a 28-clause held-out set independently and
agreed on 15 of 28, Cohen's kappa 0.32.

The disagreement was not carelessness. One annotator was labelling on **harm**, the prompt was
classifying on **typicality**, and nobody had written down which one the project meant. This
document is that decision, made once, in writing, so it stops being made per clause.

It applies to every labelled set in the project: `test_set.json`, `held_out_clauses.json`, and
anything added later. Both existing sets predate it and are being re-derived against it.

---

## Who the labels are for

A person who has not read the document and is not going to read it. They do not know what is
normal for this kind of contract, so telling them a term is unusual does not help them. They
want to know what could cost them.

That is the whole reason the harm rubric wins over the typicality rubric. It follows from who
the user is, not from which is more interesting to classify.

---

## The three labels

Apply the tests in this order. First one that fires wins.

### concerning

The clause creates **material exposure**: it could cost the person money, cost them their home
or their account, or take away a right they would want to keep. Or it hands the other party
**discretion** over something that matters to them.

**Typicality is never a defence.** A term that appears in every contract of this kind is still
concerning if it does these things. Do not downgrade because it is standard.

### favorable

The clause gives a protection, remedy or benefit **beyond what the law already requires**.

The bar is the legal floor, not zero. A landlord agreeing to supply heat is not being generous,
they are obeying the sanitary code. A clause that restates a statutory duty is neutral.

### neutral

Everything else. Specifically:

- Administrative and procedural mechanics. Definitions, notice addresses, signature blocks,
  which office to write to.
- Obligations that only restate the law. The floor, described.
- Conduct rules an ordinary occupant would follow anyway and would not be surprised by.
- Costs that are **both capped and small**, where an ordinary person could absorb them without
  changing their plans.

Neutral is a real category with a real definition. It is not the middle option and it is not
where uncertain clauses go.

---

## The threshold

This is the part that stops everything becoming concerning.

**Is the exposure capped, and is the cap something an ordinary person could absorb without
changing their plans?**

- Uncapped, or capped at a number that would hurt: **concerning**
- Capped and small: **neutral**

Worked: no interest paid on a security deposit is bounded and small, so neutral. A $200 minimum
cleaning fee is a floor with no ceiling above it, so concerning. A late fee of $5 per day with
no cap is concerning. A $25 fee for a lost key is neutral.

The same test applies to non-money exposure. A rule that costs a normal person nothing unless
they were already in breach is neutral. A rule that restricts ordinary use of their own home is
concerning, because they lose something they thought they were buying.

---

## Standing decisions

These are the cases that have already caused inconsistency. They are decided here so they are
not re-decided per clause.

**1. Binding you to a document you have not seen: concerning.**
Any clause incorporating outside policies by reference, or requiring compliance with rules the
other party writes and can change, is concerning. The unknown counts as risk.
Resolves: `bha_8_n` and `bha_16` are **both concerning**. They were split neutral/concerning.

**2. Limitations of liability: concerning.**
Any cap on what the other party owes you when they cause you harm, including a total disclaimer.
A broader limitation cannot be less concerning than a narrower one.
Resolves: `spotify liability_cap` and `facebook no_damages_liability` are **both concerning**.
They were split concerning/neutral.

**3. Restating a statutory duty: neutral, not favorable.**
Heat, hot water, habitability, sanitary code compliance, statutory notice periods, access to a
grievance process that exists by regulation anyway.
Resolves: `bha_7_d`, `bha_15`, `bha_17` move from favorable to neutral.

**4. Discretion language: concerning.**
"At the Landlord's sole discretion", "as determined by us", "such other charges as we deem
appropriate". The clause is only as good as the other party chooses to make it.

**5. Restrictions on ordinary use of your own home: concerning.**
Guest night limits, occupancy minimums, vehicle limits, restrictions on ordinary domestic
activity. The person is losing something they believed they were renting.
Resolves: `ftc 10`, one vehicle, stays **concerning**. `pa XXXIII`, 48-hour guests, stays
**concerning**.

**6. Mutual and optional terms: neutral.**
A dispute process both parties must agree to, where both choose the neutral, is not the same as
imposed binding arbitration. Read who it binds and whether it is opt-in.
Resolves: `real_002 2.16` is **neutral**. Imposed arbitration with a class action waiver stays
concerning.

**7. Notice changes the answer.**
"Terms may change at any time" is concerning. "Terms may change and you will be notified" is
neutral, because the person can act. Silent or automatic acceptance is concerning.

**8. Joint and several liability: concerning.**
Any one signer can be pursued for the whole obligation. Most people signing with a partner or
housemate do not know this.
Resolves: `bha_20` moves from neutral to concerning.

---

## Writing the note

The note records **why**, not **what**. A restatement of the clause is not a note; the clause
text is already in the file.

Bad: "Requires disclosure of Social Security numbers upon request."
Good: "Every household member's SSN, and the clause does not say how it is stored or for how
long. Concerning on the discretion rule."

Required only on close calls and on anything decided by a standing decision, naming which one.
Obvious clauses can have an empty note. Do not write a note on all of them out of duty; it turns
a two-hour job into five and the notes stop being read.

If a clause is genuinely 50/50, label it, and write the note as the argument for the other side.
Those are the clauses a second annotator should be given first.

---

## Procedure

1. Label from the clause text. Never from a section title, a summary table, or another
   annotator's file.
2. Never label with model output visible. If a clause has already been seen in a model report,
   it is contaminated and must be recorded as such rather than quietly reused.
3. Two annotators label independently, and the second commits without reading the first.
4. Report agreement and Cohen's kappa before reporting any model score.
5. Adjudicate disagreements against this document. If a disagreement cannot be settled by any
   rule here, that is a gap in the rubric: add the rule, then apply it to both sets.
6. Every change to this file invalidates the labels derived from the old version. Re-derive, do
   not patch.

---

## What this does not settle

The threshold is a judgment, not a number. "Capped and small" will be read slightly differently
by two people, and that residual disagreement is the honest floor of this task.

Kappa will not reach 1.0 and should not be expected to. What it should do is stop being 0.32,
and stop being 0.32 for a reason that is a definitional split rather than genuine ambiguity.
