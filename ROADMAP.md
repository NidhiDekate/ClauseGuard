# ClauseGuard Roadmap

Public-facing progress tracker. For the reasoning behind each decision, see `ENGINEERING_JOURNAL.md`.

**Current status:** Phases 1-9 are complete. Phase 10 (LLMOps) is the remaining work.

| Phase | Objective | Success Criteria | Status |
|---|---|---|---|
| 1. Evaluation Dataset | Build a high-quality labeled benchmark | 8+ real documents with labeled clauses | Done — `evaluation/datasets/test_set.json`, 53 hand-labeled clauses across 5 real documents (plus 3 synthetic documents held aside for pipeline validation only) |
| 2. Prompt Engineering | Versioned prompts, systematic comparison between versions | Prompt regression tests pass | Done — v1/v2/v3 compared on the labeled set, v2 in use, v3 rejected. See `docs/01_prompt_engineering.md` |
| 3. Model Benchmarking | Compare open models on quality, latency, and cost | Documented benchmark report | Done — 3 models benchmarked, `gpt-oss-120b` selected. See `docs/02_model_benchmark.md` |
| 4. Retrieval System | Build and optimize RAG, including chunking strategy | Chunking strategies compared on real retrieval tests | Done — clause-boundary-aware chunking beat fixed-size; Chroma vs Pinecone compared. See `docs/03_chunking_and_vector_store.md`. Reranking and formal Precision@K / Recall@K measurement not done — moved to future work |
| 5. Custom MCP Server | Expose clause retrieval as an MCP tool | LangGraph agent successfully calls the MCP server | Done — `src/agents/clause_search_server.py` (FastMCP) |
| 6. Multi-Agent Workflow | Planner → Retriever → Reviewer → Calculator → Report | End-to-end pipeline produces a decision report | Done — `src/agents/graph.py`. Note the order: Reviewer runs *before* Calculator. It was originally the other way round; see Engineering Journal for the bug that caused the swap |
| 7. Trust & Verification | Evidence grounding and guardrails | Every claim in the output traces to a source clause | Done — `src/agents/guardrails.py` |
| 8. Deployment | FastAPI + Streamlit + Docker | Public demo available | Done — live at clauseguard-ai.streamlit.app |
| 9. Observability | LangSmith tracing + structured logging | Traces, latency, and cost visible per request | Done — LangSmith tracing plus SQLite request logging in `src/agents/logging_db.py` |
| 10. LLMOps | Automated evaluation and CI/CD | Regression pipeline operational | Not started |

## Engineering questions this project is investigating

- Which chunking strategy retrieves legal clauses most accurately — fixed-size or clause-boundary-aware? **Answered in Phase 4: clause-boundary-aware, on every retrieval test run.**
- Does a reranking step meaningfully improve retrieval quality over raw similarity search? **Not yet tested.**
- Which open model provides the best quality per dollar for clause classification versus final decision reasoning? **Answered in Phase 3: `gpt-oss-120b`, chosen for the accuracy/latency balance rather than raw top score.**
- Does a dedicated reviewer agent measurably reduce unsupported claims? **Answered in Phase 7: yes — the reviewer-enabled-vs-disabled comparison caught both obvious and subtle irrelevant matches.**
- Is multi-agent orchestration worth its added complexity compared to a single well-prompted call? **Partly answered — the Calculator bug in Phase 6 is a concrete case where separating the steps caught an error a single call would have shipped. Not yet measured end-to-end against a single-call baseline.**
- Does the Calculator node perform meaningful financial computation, or is it redundant with what the LLM already extracts? **Answered during Phase 6: it earns its place, but only downstream of the Reviewer. Run before the Reviewer it produced a confident dollar figure from a clause the Reviewer then rejected as irrelevant. Fixed by reordering the graph rather than patching either node.**

## Future work

- RAGAS-based evaluation, replacing the current hand-scored benchmark
- Reranking after initial retrieval, with Precision@K / Recall@K measured properly
- CI/CD with automatic regression testing on every prompt or retrieval change
- Cost-aware model routing based on measured performance, not assumption
- A single-call baseline to measure what the multi-agent structure actually buys
- Expanded document coverage — the architecture is not lease-specific and should generalize to insurance policies, employment agreements, warranties, and NDAs; real evaluation data for those categories is a later addition, not part of the current scope
