# ClauseGuard

> Read a lease, insurance policy, or Terms of Service and get back the clauses that could cost you, each one linked to the exact text it came from.

ClauseGuard reads legal-style documents, finds the clauses that matter across eight risk categories, labels each one, and explains it in a sentence a non-lawyer can act on.

## Live demo

https://clauseguard-ai.streamlit.app/

## What this project is for

This is an AI engineering case study. The application works, but the point of the repository is the set of questions behind it: how should a contract be chunked, does the retrieval actually find the right clause, which model should classify it, do few-shot examples earn their place, and how do you know any of the answers are real.

Every one of those was measured rather than assumed, and the write-ups include the experiments that failed and the numbers that turned out to be wrong.

In August 2026 the whole project was re-audited from scratch. That audit found 67 defects in my own work, including a data leak that invalidated every accuracy number I had published. Those numbers are corrected below. The story of the audit is in `docs/12_what_i_learned.md`.

## Results

All figures are scored on 53 hand-labelled clauses from 5 real documents. The test set also holds 10 clauses from 3 synthetic documents; those are used only to check the pipeline runs end to end and are never scored.

**Always state the baseline.** The label distribution is 36 concerning, 11 neutral, 6 favorable, so a classifier that answers "concerning" every time scores 67.9%. Any number near that line has learned nothing.

**Clause classifier, prompt v6 zero-shot, three runs per model at temperature 0:**

| | `gemini-3.6-flash` (default) | `gpt-oss-120b` (fallback) |
|---|---|---|
| Correct, per run | 44, 44, 44 | 41, 41, 44 |
| Missed concerning clauses | **0, 0, 0** | 1, 1, 1 |
| Coverage | 100% | 100% |
| Cost per 53 clauses | $0.14 | $0.014 |
| Majority-class baseline | 67.9% | 67.9% |

**On accuracy these two models are not distinguishable.** Both reach 44 of 53 and their ranges
overlap. Quoting a 3-point gap from any single pair of runs would be quoting noise.

**And a stable total is not a stable system.** Gemini scores 44 in all three runs, but two
clauses flip between runs in opposite directions, so nine are wrong every time and the errors
cancel. Only per-clause reporting shows that.

**On the safety metric they separate cleanly.** Gemini missed zero concerning clauses in all
three runs; the fallback missed exactly one in all three. No overlap, and both perfectly
consistent. Recall on `concerning` is the metric that matters here: a missed one-sided clause
reaches a person who trusted the tool to catch it, while a false alarm costs a few seconds of
reading.

**Single runs of this evaluation are unstable.** The same model on identical inputs at
temperature 0 has scored 41, 43, 44, 45 and 46 across the project's history. Every number above
is reported as a range for that reason, and `evaluation/eval_models.py --repeat N` is how they
were produced.

**Held-out evaluation.** 28 clauses from a Boston Housing Authority lease used in no other part of this project, labelled independently by two annotators and adjudicated in writing. `gemini-3.6-flash` scored 21/28, 75%, against a 50% baseline, with **zero missed concerning clauses**. Full write-up in `docs/07_held_out_evaluation.md`. Those figures were measured under prompt v5 and were not re-measured under v6, because a held-out set only works once.

**Latency is not a stable number.** LangSmith traces show per-call latency ranging from 0.6s to 21.6s on clauses of near-identical length and token count. The averages reported in the experiment write-ups hide a distribution with a 30x spread, most of it provider variance rather than model behaviour. Treat every latency comparison in this repository as weak.

**Faithfulness.** 46 of 53 explanations are fully grounded in their clause, 86.8%, judged by a
different model from a different vendor. **Six carry the right label and a claim the clause does
not support**, which every accuracy figure above scores as a win. Three of those six are the same
failure: the model states that a protection is absent when the clause is simply silent on it, for
example "without paying you" on a clause that never mentions payment. Full write-up in
`docs/10_faithfulness_evaluation.md`, `docs/11_reviewer_as_judge.md`.

**Retrieval.** Every correct clause is within the top 3 retrieved chunks. Recall@1 75%, recall@2 83%, recall@3 100%, over 12 cases where an answer exists. The pipeline fetches 3.

**Chunking.** Clause-boundary chunking finds every answer at k=3. Against recursive character splitting, which is what most production RAG uses, it is better on 4 of 12 cases and worse on none, which at n=12 is suggestive and not conclusive. It beats naive fixed-size slicing by a wide margin, but that is a weak baseline and the earlier version of this README oversold it.

**Few-shot examples.** Removed. They tied with zero-shot on accuracy, cost 55% more input tokens, and were the surface that leaked the test set into the prompt in the first place.

Write-ups: `docs/05_model_selection.md`, `docs/06_annotation_guidelines.md`, `docs/07_held_out_evaluation.md`, `docs/08_chunking_comparison.md`, `docs/09_few_shot_ablation.md`, `docs/10_faithfulness_evaluation.md`, `docs/11_reviewer_as_judge.md`. Earlier experiments in `docs/01` to `docs/03`, each carrying a banner where its numbers have been superseded.

## The finding this project is actually about

Two annotators labelled a held-out set independently and agreed on 15 of 28 clauses. Cohen's kappa 0.32.

The disagreement was not carelessness. One annotator was labelling on **harm**, meaning what could cost this person money. The prompt was classifying on **typicality**, meaning what is unusual for a document of this kind. Nobody had written down which one the project meant, and the conflict was invisible in aggregate accuracy for months because both rubrics agree on most clauses.

That single finding invalidated every number in the project and produced `docs/06_annotation_guidelines.md`, the annotation rubric that should have existed from the start.

## Architecture

```
Document → Chunking → Embeddings → Chroma
                                     ↓
        Planner → Retriever → Reviewer → Calculator → Report
```

The Reviewer runs before the Calculator because of a real bug: an earlier version ran the Calculator first and produced a confident dollar figure from a clause the Reviewer rejected as irrelevant moments later. Reordering the graph fixed it without changing either node.

The Reviewer is an LLM-as-a-judge. It has never been evaluated as one, which is the largest gap in this repository and is listed below.

## Core features

- Clause-level analysis with the source text attached to every finding
- Retrieval-augmented generation over an uploaded document
- LangGraph workflow: Planner, Retriever, Reviewer, Calculator, Report
- Structure-aware chunking with a fallback chain for documents that are not numbered
- Model selection across seven candidates from four vendors
- LangSmith tracing, enabled through environment variables with no application code
- Structured SQLite request logging
- FastAPI backend, Streamlit frontend, Docker

## What this does not do

Listed because a project that names its own limits is easier to trust than one that does not.

- **The Reviewer is measured but thin.** 11/12 recall and 3/4 on absent categories, n=16. One false positive on a document with no liability clause. See `docs/11_reviewer_as_judge.md`.
- **Faithfulness is measured but not fixed.** 86.8% of explanations are grounded. The six that are not have a named pattern and no remedy yet, because fixing it means a prompt change and the held-out set that would validate it is spent.
- **Coverage is bounded by eight fixed categories.** This is a checklist, not a full document sweep. A clause outside those categories is never examined.
- **The MCP server is not finished.** It exists and has never been run as a real process end to end.
- **Observability is tracing only.** LangSmith records every call, but no evaluator or alert runs on top of it, and nothing is measured from live traffic.
- **Sample sizes are small.** 53 clauses, 28 held-out, 12 retrieval cases. One case in the retrieval set is 8 percentage points. Most results here are suggestive.
- **The deployed app runs `gpt-oss-120b`**, not `gemini-3.6-flash` which scored better, because switching means an API key in Streamlit secrets and about two cents per analysis on a public demo with no rate limiting.

## Tech stack

LangGraph, LangChain, MCP (FastMCP), FastAPI, Streamlit, Docker, SQLite, Chroma, Pinecone, sentence-transformers (all-MiniLM-L6-v2), Groq, OpenRouter.

## Running it

```bash
pip install -r requirements.txt
cp .env.example .env          # add GROQ_API_KEY
streamlit run streamlit_app.py
```

Evaluations, none of which need the app running:

```bash
python -m pytest tests/ -q                      # chunker regression tests, no network needed
python evaluation/eval_retrieval.py             # retrieval, no API calls
python evaluation/eval_models.py --only openai/gpt-oss-120b
python evaluation/eval_models.py --held-out evaluation/datasets/held_out_gold.json --only ...
```

## Roadmap

`ROADMAP.md` for status. `ENGINEERING_JOURNAL.md` for the decisions and the bugs behind them.

## Disclaimer

ClauseGuard is an educational AI engineering project. It does not provide legal advice.
