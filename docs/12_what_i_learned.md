# What I learned rebuilding this project

Written Aug 25, 2026, after re-auditing ClauseGuard from scratch.

If you read one file in this repository, read this one. The eleven documents in `docs/` are the
experiments. This is what they add up to.

## What I set out to do

ClauseGuard worked. It read a lease, found the clauses worth attention, and explained them. The
README quoted 88.7% accuracy and I believed it.

I reopened the project to add proper LLM evaluation, which I had learned since building it. I
expected to add a few eval scripts to finished work.

Instead I found 67 defects in my own project, and the first one made every number I had published
meaningless.

## The finding the whole project turned on

I built a held-out set: 28 clauses from a Boston Housing Authority lease used nowhere else. Two
annotators labelled it independently and blind.

**We agreed on 15 of 28. Cohen's kappa 0.32.**

The disagreement was not carelessness. Ten of the thirteen ran in one direction. I was labelling on
**harm**, meaning what could cost this person money. The prompt was classifying on **typicality**,
meaning what is unusual for a document of this kind. Nobody had written down which one the project
meant.

Both rubrics agree on most clauses, which is why it stayed hidden. Aggregate accuracy could never
have shown it. It only appeared because a second annotator labelled the same clauses without seeing
mine.

That explained something that had bothered me for weeks. Six clauses the classifier always got
wrong, no matter which prompt I wrote. Four model families across four vendors all called
`pa XLIV` and `spotify liability_cap` neutral, and all four disagreed with my gold set. I had
assumed the models were wrong. **They were correctly applying a definition my labels did not use.**

I picked harm, because the person using this has not read the lease and does not know what typical
looks like. Telling them a term is unusual does not stop it costing them money.

Then I wrote `docs/06_annotation_guidelines.md`, the rubric that should have existed from day one.
Nine standing decisions. Deleting one sentence from the prompt made two of those six clauses flip
immediately.

## The thing that kept happening

Seven times in this audit, a measurement failed at something other than the thing it was measuring.
Each one would have produced a number somebody could have quoted.

**The parser.** `deepseek-v4-flash` scored 11/53. It was not the model. It narrates before emitting
JSON and my parser only accepted pure JSON. Fixing the parser moved it to 37/53 and moved
`gemini-3.6-flash` from fifth place to first. Nothing about any model changed.

**The leakage.** Eight of my nine few-shot examples were verbatim clauses from the test set. Every
score I had published was measured on data whose answers were in the prompt.

**The eval chunked differently from production.** The retrieval eval indexed 53 chunks for a
document where the live retriever indexed 52. It had been measuring a slightly different system.

**A metric that favoured one contestant.** Comparing chunking strategies, only clause chunking
keeps the section number attached, so only it could match on an exact reference. Everything else
had to clear a text-similarity bar. The comparison was rigged toward the strategy I was testing,
and I only noticed because a coverage number came out lower than a recall number, which should be
impossible.

**A failed run overwriting a good one.** A run that answered 1 clause of 53 replaced a run that
answered all 53. Reports are evidence, and nothing stopped a broken run from destroying evidence.

**A fix that broke a different model.** I set `max_tokens=512` to stop `gpt-oss-120b` truncating
its JSON. Gemini reasons before answering, spent the budget thinking, and had ten words left for
the answer. The symptom looked exactly like a parser bug.

**And the ground truth itself.** The faithfulness eval flagged an explanation as invented. My first
read was that the model had hallucinated an eviction consequence. It had not. **Our dataset had cut
that consequence out with an ellipsis.** Seven of 53 gold clauses were stored abridged. One,
`2.13`, was two unrelated clauses spliced together under a third clause's number, and half of it
duplicated a clause already in the set.

The judge was right, the model was right, and the ground truth was wrong.

**The lesson is one sentence: whatever you are measuring, something else in the path is being
measured too.** I now have seven concrete examples of it, and every one was invisible in the
headline number.

## The bug that turned a system error into a fact about your lease

Everything above is about measurement. This one was in the product.

The report builder took each category the Reviewer had looked at and, if the category came back
unverified, printed **"not addressed in this document"**. That string was the only fallback. So when
the Reviewer call failed on a rate limit, the user was told their lease has no late fee clause.

The lease I was testing with has one. $25 plus $5 a day, uncapped.

There is no way for a reader to tell those two states apart. Both render as a calm grey line saying
the document does not cover it. The second one is the whole reason somebody would run this tool.

The fix separates the two. A category the model looked at and found nothing in is `not_addressed`.
A category the model never successfully looked at is `error`, and it says so: "Analysis failed for
this category, so nothing can be said about it either way." It renders amber, not grey, with the
underlying error available, and a red banner at the top of the report. Errors no longer count toward
the "not addressed" total, which had been quietly inflating it.

**Never state an absence you did not establish.** A failure and a clean result are not the same
answer, and the moment you collapse them the tool is more dangerous than no tool, because the user
came here specifically to stop reading the document themselves.

## What actually won

**Zero-shot beat few-shot.** They tied on accuracy, and zero-shot used 55% fewer input tokens and
missed one fewer concerning clause. So I deleted the examples. That also deleted the surface that
caused the leakage: it is now structurally impossible rather than guarded by a regression test.

**Clause chunking won, by much less than I claimed.** It beats naive character slicing by a wide
margin. Against recursive character splitting, which is what most production RAG uses, it wins on
4 of 12 cases and loses none. At n=12 that is suggestive, not conclusive. The original README
oversold it by choosing a weak opponent.

**Gemini and gpt-oss-120b are indistinguishable on accuracy and not on safety.** Both reach 44 of
53 and their ranges overlap. But gemini missed zero concerning clauses in every run, and gpt-oss
missed exactly one in every run. The honest claim is that they score the same and one is safer.

**The Reviewer is good.** 11/12 recall, 92% precision, and unlike the classifier it did not move at
all across 32 calls.

## The deployed config is deliberately not the dev config

Locally the classifier runs gemini first and falls back to gpt-oss. The Reviewer runs the mirror,
gpt-oss first and gemini as fallback. That split is on purpose: it is the cheapest way to keep
working when one provider's daily limit runs out, and it means neither node can take the whole app
down alone. Before this, the Reviewer had no fallback at all, so one Groq rate limit crashed the
entire run.

Pinning the Reviewer to gpt-oss and giving it gpt-oss as its fallback did nothing, which is obvious
in hindsight and was not obvious while writing it. The fallback has to be a different vendor or it
is not a fallback.

There is also a circuit breaker. Once a model fails inside a run, every later call in that run skips
it instead of paying the timeout again. It resets between runs, not across them, because a daily
limit and a transient blip look identical at the call site and only the run boundary tells them
apart.

The deployed config is not automatically whatever I last ran locally, and I have to set it
explicitly at deploy time. That is a thing I would have got wrong by assuming.

## Numbers move more than I thought

The same model, same prompt, same clauses, temperature 0, scored 41, 43, 44, 45 and 46 across this
project's history.

Almost every comparison I had made was a single run against a single run. The few-shot experiment
came down to one clause, and one clause is inside the noise. I had been reporting three significant
figures on a measurement with a three-clause error bar.

Every eval now takes `--repeat`, and the reports carry the spread.

One thing I would have missed without per-case output: gemini scores 44 in all three runs, and two
clauses still flip between runs in opposite directions. **A stable total is not a stable system.**
The errors cancel.

## What I got wrong along the way

I predicted the smaller model would over-flag and be safe. It had the worst recall in the field.

I predicted a prompt fix would repair four disclaimer errors. It fixed one and broke three.

My cost estimate was 3.5x low, because I forgot the nine few-shot examples rode on every call.

I ran the held-out set before freezing the prompt. **A held-out set works once.** That spent it,
and it is why the prompt was frozen where it is instead of improved. That is a process error and it
is recorded in `docs/07` rather than quietly absorbed.

And I labelled 28 clauses in six minutes off a summary table, called it done, and got caught by the
file timestamps. The second pass, done properly with the clause text open, is the one that found
the definition split.

## What I would do differently

Write the annotation rubric before labelling anything. Every downstream problem traces back to
there being no written definition of `concerning`.

Never compare single runs. Report a spread or report nothing.

Store full clause text. The ellipses saved a few hundred characters and cost a real finding.

Pick baselines that could actually win. Beating naive character slicing proved almost nothing.

And check the instrument before believing the reading. Twice I concluded something did not exist
because my own search or metric was broken.

## What is still not done

Faithfulness is measured at 86.8% and not fixed. Six explanations carry the right label and an
unsupported claim, and three of those are the same failure: the model states a protection is absent
where the clause is simply silent. "Without paying you" on a clause that never mentions payment.
The fix is a prompt rule, and validating a prompt change needs a held-out set, which is spent.

The MCP server exists and has never run as a real process.

Answer relevancy and the RAG triad are not built.

Every sample here is small. 53 clauses, 28 held out, 16 retrieval cases, 12 scorable. One case is
8 percentage points. Most of what is in these documents is suggestive.

## Where to read more

| | |
|---|---|
| What `concerning` means, and the nine standing decisions | `docs/06_annotation_guidelines.md` |
| The held-out evaluation and the kappa 0.32 finding | `docs/07_held_out_evaluation.md` |
| Model selection, and the parser bug it exposed | `docs/05_model_selection.md` |
| Retrieval | `docs/04_retrieval_evaluation.md` |
| Chunking against honest baselines | `docs/08_chunking_comparison.md` |
| Few-shot versus zero-shot | `docs/09_few_shot_ablation.md` |
| Faithfulness, and the fabricated gold clause | `docs/10_faithfulness_evaluation.md` |
| The Reviewer as a judge | `docs/11_reviewer_as_judge.md` |
| Superseded, kept with banners | `docs/01`, `docs/02`, `docs/03` |
