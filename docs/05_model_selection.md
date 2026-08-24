# Experiment: Model Selection (Phase 10)

**Question:** which model should classify clauses, and is the classifier's remaining error
a limit of the model or a limit of the prompt?

Phase 3 compared three Groq models on accuracy and picked `gpt-oss-120b`. Two things made
that worth redoing. Groq is now down to two production language models, so there is no
shortlist left to choose from. And accuracy is the wrong thing to select on here: the eval
set is 64% `concerning`, so accuracy rewards a model for leaning toward the majority class,
which is the exact bias this project has been trying to fix.

Behind that sat a question three prompt versions had failed to answer. Six clauses were
consistently classified `neutral` when the gold set says `concerning`, four of them
liability or warranty disclaimers. Prompt v3 and v4 both tried to fix them by writing a
better rule, and both made things worse. Without a strong model in the comparison there was
no way to tell whether that was a `gpt-oss` limitation or the task being genuinely hard.

## Setup

Seven models, 53 hand-labelled clauses, prompt v2 unchanged, only the model varies.
`evaluation/eval_models.py`.

The shortlist is a price and vendor spread with a frontier model as a ceiling. It is **not**
a leaderboard shortlist, and it is worth saying so plainly. A proper step-two filter would
rank candidates on instruction following before spending anything on them. That was skipped.
The list here is two incumbents so the numbers stay comparable, three cheap models across
three vendors, one mid-tier, and Claude Opus 5 as the ceiling.

The ceiling model is the point of the exercise. Everything else answers "which model should
I deploy". Opus answers "is this task winnable at all".

### What is measured, and why it is not just accuracy

**Accuracy with a 95% interval.** At n=53 one clause is 1.9 points and the interval is
roughly 18 points wide. Reporting `86.8%` to one decimal implies a precision this sample size
does not support.

**Coverage.** How many clauses the model answered at all. Phase 3 computed accuracy as
`correct / (total - errors)`, which grades a model only on the questions it got around to and
quietly rewards failing. Accuracy here is over all 53, with coverage reported separately.

**Recall on `concerning`.** The safety metric. A missed one-sided clause reaches the user
unflagged. A false alarm makes them read a clause that turns out to be fine. Those are not
equally expensive, and accuracy treats them as if they are.

**Macro-F1.** All three classes weighted equally, so the 64% majority cannot carry the score.

**Cost, from measured token counts** rather than an estimate. The first estimate was wrong by
3.5x, because the prompt carries nine few-shot examples on every call.

## Results

Run 1, strict `json.loads` parsing:

| model | accuracy | coverage | recall | macro-F1 | missed | alarms | latency | cost/53 |
|---|---|---|---|---|---|---|---|---|
| anthropic/claude-opus-5 | 47/53 89% | 100% | 91% | 0.87 | 3 | 3 | 5.43s | $0.622 |
| openai/gpt-oss-120b | 45/53 85% | 100% | 79% | 0.85 | 7 | 1 | 5.78s | free tier |
| openai/gpt-5.6-luna | 43/53 81% | 91% | 85% | 0.83 | 5 | 3 | 2.56s | $0.015 |
| qwen/qwen3.7-flash | 41/53 77% | 100% | 76% | 0.75 | 8 | 1 | 6.69s | $0.010 |
| google/gemini-3.6-flash | 40/53 75% | 89% | 76% | 0.77 | 8 | 1 | 4.27s | $0.118 |
| openai/gpt-oss-20b | 37/53 70% | 100% | 59% | 0.73 | 14 | 1 | 7.04s | free tier |
| deepseek/deepseek-v4-flash-0731 | 11/53 21% | **25%** | 15% | 0.38 | 29 | 1 | 7.14s | $0.003 |

Majority-class baseline, always answering `concerning`: 64.2%. Two models are below it.

## What actually happened

### The comparison was partly measuring the parser

`deepseek-v4-flash` scored 21% with 25% coverage. Reading its failures, they were not wrong
answers. They were correct answers wrapped in reasoning:

> We need to classify this clause... So label: concerning. Reason: You could lose your home
> just for being arrested... `{"label": "concerning", "reason": "..."}`

The JSON is present and correct. `json.loads` rejected the whole response. Gemini had a milder
version of the same problem: it fences output in ` ```json ` and lost six clauses to it.

That model is, by tokens processed, the most used model on OpenRouter. It came last here, and
not because it cannot judge clauses.

`src/parsing.py` now strips known wrappers and, failing that, scans for balanced `{...}` spans
and takes the last one carrying the expected key. Rerunning the three affected models:

| model | before | after | coverage |
|---|---|---|---|
| deepseek-v4-flash | 11/53 | **37/53** | 25% -> 94% |
| gemini-3.6-flash | 40/53 | **49/53** | 89% -> 100% |
| gpt-5.6-luna | 43/53 | 43/53 | 91% -> 94% |

**deepseek gained 26 clauses from a parser change.** Nothing about the model changed.

Luna barely moved, and its remaining failures are not parseable by anything. Two empty
responses and this:

> `{"analysis \U0005ffff♀♀♀♀♀♀ 天天中彩票开奖json 亚历山大发...`

Corrupted output with unrelated Chinese text in it. That is the fastest model in the field
producing garbage on about one call in eighteen, which the accuracy column hides.

### Final standings

| model | accuracy | coverage | recall | macro-F1 | missed | alarms | latency | cost/53 |
|---|---|---|---|---|---|---|---|---|
| **google/gemini-3.6-flash** | **49/53 92%** | 100% | 91% | **0.92** | **3** | **1** | 4.46s | $0.131 |
| anthropic/claude-opus-5 | 47/53 89% | 100% | 91% | 0.87 | 3 | 3 | 5.43s | $0.622 |
| openai/gpt-oss-120b | 45/53 85% | 100% | 79% | 0.85 | 7 | 1 | 5.78s | free tier |
| openai/gpt-5.6-luna | 43/53 81% | 94% | 82% | 0.82 | 6 | 3 | 2.71s | $0.015 |
| qwen/qwen3.7-flash | 41/53 77% | 100% | 76% | 0.75 | 8 | 1 | 6.69s | $0.010 |
| deepseek/deepseek-v4-flash-0731 | 37/53 70% | 94% | 62% | 0.74 | 13 | 1 | 7.86s | $0.012 |
| openai/gpt-oss-20b | 37/53 70% | 100% | 59% | 0.73 | 14 | 1 | 7.04s | free tier |

### The frontier model does not fix the six clauses

This is the answer to the question that started it.

Claude Opus 5 still classifies `pa XLIV` and `spotify liability_cap` as neutral. So do
`gpt-oss-120b`, `gpt-oss-20b`, and `qwen`. So does every prompt version tried.

- **pa XLIV**: landlord not liable "unless caused **solely** by the Landlord's negligence"
- **spotify liability_cap**: liability limited to fees paid, or $30
- **ftc 10**: maximum one vehicle on the premises

Four model families across four vendors, plus three prompt versions, all agree with each
other and disagree with the gold set.

When the strongest available model and every cheap one reach the same answer, the useful
reading is not that all of them are wrong. **The label may be the outlier.** An exculpatory
clause and a liability cap at fees paid are both extremely common in real leases and real
Terms of Service. They were labelled `concerning` because they *are* one-sided. The models
label them `neutral` because they are *typical*, and prompt v2 explicitly instructs that
typical wins.

Both readings are defensible. There is one annotator on this eval set and no
inter-annotator agreement measurement, so there is nothing to appeal to.

`pa XLIV` also flips between runs on the same model. Gemini got it wrong in run 1 and right
in run 2, luna the reverse. It is a genuine boundary case, not a competence failure.

## Decision

**`google/gemini-3.6-flash`.**

Best on every metric that matters. It matches Claude Opus on recall and misses, beats it on
macro-F1 and false alarms, and costs one fifth as much.

Against the incumbent, `gpt-oss-120b`: **3 missed concerning clauses against 7.** That is the
comparison worth making. Accuracy moved 7 points, which is inside the noise band; the misses
halving is not.

Against Claude Opus: one clause apart with almost entirely overlapping intervals. **These two
are indistinguishable on this set.** Gemini is not "better than Opus". It is not worse, and it
is 4.7x cheaper, which is enough.

`gpt-oss-120b` stays documented as the free fallback, with the gap stated rather than hidden:
7 missed against 3.

Total spend for the whole comparison, both runs, seven models: under $1.

## What this does not establish

The shortlist was built on price and vendor spread, not on a capability filter. A proper
step-two would rank candidates on instruction following first. Given how the deepseek result
turned out, that filter would have mattered.

n=53, so the accuracy interval is about 18 points wide and anything inside two clauses is
noise. Gemini's jump from 40 to 49 includes six recovered parse failures and about three
clauses of run-to-run variation.

One run per model. No repeats, so no variance estimate. `gpt-oss-120b` scored 45 here and 46
on a separate run an hour earlier, same prompt, same clauses.

Latency is not comparable across providers. Groq models were slowed by free-tier rate limits;
OpenRouter models were not.

Cost is measured from real token counts, but a rerun would not reproduce it exactly, since
output length varies.

## Takeaway

Two things, and the first is the one worth remembering.

**An evaluation measures the whole path, not just the thing being evaluated.** A model that
answers correctly and formats differently scores the same as a model that answers wrong. For
one model that difference was 26 clauses out of 53. Before comparing models, check that the
harness is capable of hearing them.

**Three prompt versions and a frontier model reaching the same answer is evidence about the
labels, not just the models.** Chasing six errors through v3 and v4 was the wrong instinct.
Two of the six were a disagreement with the gold set, not a failure to meet it. The next step
is a second annotator on the disputed clauses, not a fifth prompt.
