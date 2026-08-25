# ClauseGuard Roadmap

Status tracker. For the reasoning and the bugs behind each decision, see `ENGINEERING_JOURNAL.md`
and the write-ups in `docs/`.

**Current status:** Phases 1 to 9 are built. Several were marked "done" on weaker evidence than the
success criteria required, and the August 2026 audit corrected that. Phase 10 is split into
application evaluation, partly done, and LLMOps, not started.

| Phase | Objective | Status |
|---|---|---|
| 1. Evaluation dataset | Labelled benchmark | **Done, and rebuilt.** 53 real clauses plus 28 held-out clauses from a document used nowhere else. Labels re-derived from a written rubric after the definition finding. 3 synthetic documents are kept for pipeline smoke tests and never scored |
| 2. Prompt engineering | Versioned prompts, compared systematically | **Done, and redone.** v1 to v3 compared on leaked data, so those numbers were void. v4 rejected. v5 rewrote the classification rubric after the harm-vs-typicality finding. v6, in use, adds an output length cap. See `docs/01`, `docs/09` |
| 3. Model benchmarking | Compare models on quality, latency, cost | **Done, and redone.** The original 3-model Groq comparison used a denominator that hid failures. Replaced by a 7-model comparison across 4 vendors with confidence intervals, coverage, per-class recall and measured cost. See `docs/05` |
| 4. Retrieval and chunking | Build and optimise RAG | **Done, and remeasured.** Recall@k now measured against a golden set rather than judged by eye. Chunking compared against recursive and semantic baselines, not just naive slicing. See `docs/04`, `docs/08` |
| 5. Custom MCP server | Clause retrieval as an MCP tool | **Partly done.** `src/agents/clause_search_server.py` exists. It has never been run as a real process end to end, and the graph does not call it in the deployed path |
| 6. Multi-agent workflow | Planner → Retriever → Reviewer → Calculator → Report | **Done.** `src/agents/graph.py`. The Reviewer runs before the Calculator because of a real bug; see the journal. The Reviewer now selects the best of k retrieved candidates rather than approving the first |
| 7. Trust and verification | Every claim traces to a source clause | **Not done, previously claimed as done.** `guardrails.py` validates structure, not faithfulness. Nothing checks whether the reason written for a clause actually follows from that clause. This is E3 and it is unbuilt |
| 8. Deployment | FastAPI, Streamlit, Docker | **Done.** Live at clauseguard-ai.streamlit.app |
| 9. Observability | Tracing and structured logging | **Done.** LangSmith tracing, enabled by environment variables with no application code, plus SQLite request logging. Tracing only: no evaluator or alert runs on top of it |
| 10. Application evaluation | Evaluate the pipeline, not just the model | **Partly done.** Retrieval eval, model selection, held-out eval, chunking comparison and the few-shot ablation exist. Reviewer-as-judge (E2), faithfulness (E3), answer relevancy (E4) and the RAG triad (E5) do not |
| 11. LLMOps | Regression pipeline and CI | **Not started** |

## Questions this project set out to answer

**Which chunking strategy retrieves legal clauses most accurately?**
Answered, and the first answer was overstated. Clause-boundary chunking finds every answer within
the top 3. Against recursive character splitting, the standard production approach, it wins on 4
of 12 cases and loses none, which at n=12 is suggestive rather than conclusive. The large margin
originally reported was against naive character slicing, a weak baseline. See `docs/08`.

**Which model gives the best quality per dollar?**
Answered. `gemini-3.6-flash` on the held-out set, `gpt-oss-120b` deployed because switching costs
about two cents per analysis on a public demo with no rate limiting. See `docs/05`, `docs/07`.

**Do few-shot examples earn their place?**
Answered, and the answer was no. Tied on accuracy with zero-shot, cost 55% more input tokens, and
were the surface that leaked the test set into the prompt. Deleted. See `docs/09`.

**Does a dedicated reviewer agent measurably reduce unsupported claims?**
**Not answered.** This was previously marked answered on the basis of a spot check. The Reviewer is
an LLM-as-a-judge with no measured precision or recall. This is E2.

**Does a reranking step improve retrieval?**
Not tested.

**Is multi-agent orchestration worth the complexity against a single well-prompted call?**
Not answered. The Calculator ordering bug is a concrete case where separating steps caught an
error, but there is no single-call baseline to compare against. This is E9.

## Known gaps, in priority order

1. **E3, faithfulness.** Nothing checks that a clause's explanation follows from the clause. This is
   the README's core promise and it is unverified.
2. **E2, reviewer-as-judge.** An LLM judge nobody has evaluated.
3. **MCP server.** Exists, never run as a real process.
4. **A second held-out set.** The first was spent by running it before the prompt was frozen. Any
   further prompt work needs a new one.
5. **E4, E5.** Answer relevancy and the RAG triad.
6. **CI and regression testing.** Phase 11.
