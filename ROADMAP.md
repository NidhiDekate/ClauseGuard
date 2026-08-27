# ClauseGuard Roadmap

Status tracker. For the reasoning and the bugs behind each decision, see `ENGINEERING_JOURNAL.md`
and the write-ups in `docs/`.

**Current status:** Phases 1 to 10 are built. Several were marked done on weaker evidence than the
success criteria required, and the August 2026 audit corrected that. Phase 11, LLMOps, is not
started.

| Phase | Objective | Status |
|---|---|---|
| 1. Evaluation dataset | Labelled benchmark | **Done, and rebuilt.** 53 real clauses plus 28 held-out clauses from a document used nowhere else. Labels re-derived from a written rubric after the definition finding. 7 gold clauses were later found stored abridged and one was a splice of two unrelated clauses; all restored from source. 3 synthetic documents are kept for pipeline smoke tests and never scored |
| 2. Prompt engineering | Versioned prompts, compared systematically | **Done, and redone.** v1 to v3 compared on leaked data, so those numbers were void. v4 rejected. v5 rewrote the classification rubric after the harm-vs-typicality finding. v6, in use, adds an output length cap. See `docs/01`, `docs/09` |
| 3. Model benchmarking | Compare models on quality, latency, cost | **Done, and redone.** The original 3-model Groq comparison used a denominator that hid failures. Replaced by a 7-model comparison across 4 vendors with confidence intervals, coverage, per-class recall and measured cost. See `docs/05` |
| 4. Retrieval and chunking | Build and optimise RAG | **Done, and remeasured.** Recall@k now measured against a golden set rather than judged by eye. Chunking compared against recursive and semantic baselines, not just naive slicing. See `docs/04`, `docs/08` |
| 5. Custom MCP server | Clause retrieval as an MCP tool | **Partly done.** `src/agents/clause_search_server.py` exists and was verified once with an in-process client. It has never been run as a real process end to end, and the graph does not call it in the deployed path |
| 6. Multi-agent workflow | Planner → Retriever → Reviewer → Calculator → Report | **Done.** `src/agents/graph.py`. The Reviewer runs before the Calculator because of a real bug; see the journal. The Reviewer selects the best of k retrieved candidates rather than approving the first. Per-category calls run concurrently, 77s to 19s |
| 7. Trust and verification | Every claim traces to a source clause | **Was claimed done, was not, now is.** `guardrails.py` validates structure, not faithfulness. E3 now measures whether the reason written for a clause follows from that clause: 47 of 53 grounded, judged cross-vendor. See `docs/10` |
| 8. Deployment | FastAPI, Streamlit, Docker | **Done.** Live at clauseguard-ai.streamlit.app. Classifier on `gemini-3.6-flash`, Reviewer on `gpt-oss-120b`, each falling back to the other's model |
| 9. Observability | Tracing and structured logging | **Done, with the limit stated.** LangSmith tracing, enabled by environment variables with no application code, plus SQLite request logging. Tracing only: no evaluator or alert runs on top of it. It did earn its place once, by identifying a silent production fallback that could not be diagnosed from the UI |
| 10. Application evaluation | Evaluate the pipeline, not just the model | **Mostly done.** E1 retrieval, E2 reviewer-as-judge, E3 faithfulness and E8 few-shot ablation all exist. E4 answer relevancy, E5 the RAG triad and E9 the single-call baseline do not |
| 11. LLMOps | Regression pipeline and CI | **Not started** |

## The evaluations

| ID | What it measures | Status |
|---|---|---|
| E1 | Retrieval: does it find the right clause | Done. recall@3 100% over 12 cases. `docs/04` |
| E2 | The Reviewer as a judge: its own precision and recall | Done. 11/12 recall, 3/4 absent rejected, 92% precision, n=16. `docs/11` |
| E3 | Faithfulness: does the explanation follow from the clause | Done. 47/53 grounded, 88.7%, cross-vendor judge. `docs/10` |
| E4 | Answer relevancy | Not built |
| E5 | The RAG triad | Not built |
| E8 | Few-shot versus zero-shot | Done. Tie on accuracy, examples deleted. `docs/09` |
| E9 | Is the pipeline worth it against one well-prompted call | Not built. There is no single-call baseline to compare against |

## Questions this project set out to answer

**Which chunking strategy retrieves legal clauses most accurately?**
Answered, and the first answer was overstated. Clause-boundary chunking finds every answer within
the top 3. Against recursive character splitting, the standard production approach, it wins on 4
of 12 cases and loses none, which at n=12 is suggestive rather than conclusive. The large margin
originally reported was against naive character slicing, a weak baseline. See `docs/08`.

**Which model gives the best quality per dollar?**
Answered. `gemini-3.6-flash`, and it is now what the deployed app runs. It matches Claude Opus on
recall and misses, beats it on macro-F1 and false alarms, and costs about a fifth as much. Against
the previous incumbent the comparison worth making is missed concerning clauses, 3 against 7, not
accuracy, which moved 7 points and is inside the noise band. See `docs/05`, `docs/07`.

**Do few-shot examples earn their place?**
Answered, and the answer was no. Tied on accuracy with zero-shot, cost 55% more input tokens, and
were the surface that leaked the test set into the prompt. Deleting them made the leak
structurally impossible rather than guarded by a test. See `docs/09`.

**Does a dedicated reviewer agent measurably reduce unsupported claims?**
Answered, after being withdrawn. This was previously marked answered on the basis of a spot check,
which is not a measurement, and the claim was withdrawn during the audit. E2 then measured it:
11/12 on answerable categories, 3/4 on absent ones, 92% precision. It was also perfectly consistent
across two complete runs while the classifier moves by up to three clauses between identical runs.
See `docs/11`.

**Does a reranking step improve retrieval?**
Not tested. Retrieval already reaches 100% at k=3 on this golden set, so there is little headroom
to detect an improvement in. That is a reason it has not been a priority, not a reason it does not
matter.

**Is multi-agent orchestration worth the complexity against a single well-prompted call?**
Not answered. This is E9 and it is the sharpest open question here. The Calculator ordering bug is
a concrete case where separating the steps caught an error a single call would have produced
silently, because the Reviewer's rejection had somewhere to land. But that is an anecdote, not a
measurement, and there is no single-call baseline to compare against.

**Does any of this hold on documents that are not leases?**
Not answered. Every retrieval, chunking and Reviewer number comes from two leases. The classifier
has seen Terms of Service clauses; the retrieval and chunking layers have not been evaluated on
one, and Terms of Service is the document type with no clause numbering, which is exactly where the
chunking ranking would most likely change.

## Known gaps, in priority order

1. **A second held-out set.** Item zero. The first was spent by running it before the prompt was
   frozen, so no prompt change can be validated right now. Two candidate prompt rules from `docs/10`
   are written down and deliberately not applied for this reason. Everything below is blocked
   behind this.
2. **The MCP server run as a real process**, and called from the graph. It is the difference
   between having a tool and having an agent.
3. **A Terms of Service golden set**, so the retrieval and chunking claims extend past leases.
4. **E4 and E5**, answer relevancy and the RAG triad.
5. **CI and regression testing**, Phase 11. The retrieval evaluation makes zero API calls, so it
   can run on every pull request for free. That is the obvious first step.
6. **E9**, the single-call baseline, which would either justify the architecture or shrink it.

## Smaller known gaps

- Retrieval queries are not separated from display labels. Both retrieval misses came from compound
  category names where the query split and the wrong half dominated the embedding.
- The evaluation discards the reasoning-token split that OpenRouter reports, which is why one
  hypothesis in `docs/09` is unverifiable.
- `src/prompts/classify_clause.py` still duplicates the fallback logic instead of using the shared
  `src/llm.py`.
- Nothing is measured from live traffic. Running the faithfulness judge on a sample of production
  explanations on a schedule is the smallest real step from tracing to observability.
