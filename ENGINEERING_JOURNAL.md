# ClauseGuard Engineering Journal

Real decisions made while building ClauseGuard — what happened, what the numbers were, what changed as a result. Roadmap tracks progress; this tracks reasoning, briefly.

---

## Entry 1 — Evaluation before development

- Built a labeled test set before writing any prompts, so later decisions could be measured against real numbers instead of intuition.
- Result: `evaluation/datasets/test_set.json` — 63 hand-labeled clauses across 8 documents. 53 of those clauses come from the 5 real documents and are what every reported number is scored on; the other 10 come from 3 synthetic documents I kept only for checking the pipeline runs end to end.

---

## Entry 2 — Synthetic data looked fine and wasn't

- First attempt: 500 auto-generated leases. All followed the same clean key-value template — no real legal density, nothing genuinely ambiguous.
- A system tested against this set would score well without being tested on anything hard.
- Decision: scrapped the batch. Rebuilt on real documents — a PA lease template, an FTC/Consumer.gov sample, a personal signed lease (redacted), and ToS pulled from tosdr.org.
- Takeaway: realistic-looking synthetic data is risky specifically because it can pass evaluation without proving anything real.

---

## Entry 3 — Verifying a data source before relying on it

- Assumed CUAD (a legal contract dataset) included residential leases. Wrote a filter script — zero matches.
- Follow-up inspection confirmed CUAD is commercial/M&A contracts (license, distributor, supply agreements) with no lease category at all.
- Decision: dropped CUAD for the lease category. Used HUD's public-domain model lease and free state templates instead.
- Takeaway: verify a dataset's actual contents before building extraction tooling around it.

---

## Entry 4 — Not every real document belongs in the eval set

- Reviewed two more real leases for inclusion: a commercial university retail lease, and a blank "Simple Rental Agreement" template.
- Excluded both — one is the wrong domain (commercial, not consumer residential), the other has no real clause content to evaluate.
- Takeaway: "real" and "relevant" are separate bars — a document needs both to be useful.

---

## Entry 5 — Prompt iteration on the clause classifier

- Baseline (v1): 86.8% (46/53) on `llama-3.1-8b-instant`. All 7 errors were the same direction — standard boilerplate (no interest, no liability) wrongly flagged as concerning.
- v2 — added few-shot examples of boilerplate labeled neutral, plus a rule distinguishing it from genuine risk: **88.7% (47/53)**. One fix generalized from a different example, not a direct match.
- v3 — broadened that rule further: dropped back to 86.8%, but two genuinely concerning clauses (no appliance-repair obligation, a one-sided liability shift) got misclassified as neutral — a worse error than before.
- Decision: kept v2. Reverted rather than chasing a v4 — Phase 3's model comparison will show whether the remaining bias is a prompt limit or a model limit.
- Takeaway: broadening a rule to fix false positives can quietly introduce false negatives. Check the direction and severity of errors after every change, not just the aggregate score.

---

## Entry 6 — Model comparison (Phase 3)

- Compared `gpt-oss-20b`, `gpt-oss-120b`, and `qwen/qwen3.6-27b` on the same 53-clause test set.
- Found a real bug along the way: `gpt-oss` models wrap answers in `<think>` reasoning blocks, and errored clauses were being silently excluded from the accuracy calculation instead of counted — quietly inflating scores. Fixed by stripping the think block before parsing.
- Results: `gpt-oss-20b` 79.2% (42/53), `gpt-oss-120b` 88.5% (46/52), `qwen3.6-27b` 89.4% but only 47/53 scored — it hit its 200k/day token cap mid-run and couldn't finish.
- Decision: going with `gpt-oss-120b`. Tied with qwen on accuracy but tested on the full set, faster, and doesn't have a quota ceiling that breaks under realistic use.
- Takeaway: a model that scores well on paper isn't automatically usable — qwen's free-tier daily limit makes it impractical for a live demo regardless of accuracy. Full write-up in `docs/experiments/02_model_benchmark.md`.

---

## Entry 7 — Chunking and vector store comparison (Phase 4)

- Compared fixed-size vs clause-boundary chunking, and Chroma vs Pinecone, on 3 real retrieval questions against the PA lease sample.
- Clause-boundary chunking won clearly. Worst case: the guest-limit question, where fixed-size returned a chunk dominated by an unrelated clause (Compliance with Law) with the real answer only partially present — a quiet failure, not an obvious one.
- Chroma and Pinecone gave identical results (same embeddings, same chunks) — only real difference was speed, Pinecone noticeably slower due to real network calls.
- Decision: `chunk_by_clause` going forward. Chroma for continued dev, Pinecone validated and parked for Phase 8 deployment.
- Takeaway: a chunking strategy that fails quietly (plausible-looking but wrong) is worse than one that fails obviously, since it could make the agent confidently describe the wrong clause. Full write-up in `docs/experiments/03_chunking_and_vector_store.md`.

---

## Entry 8 — Custom MCP server (Phase 5)

- Built `clause_search` as a real MCP tool using FastMCP, wrapping the retriever from Phase 4.
- Added a retriever cache keyed by document hash, so calling the tool multiple times on the same document (the planner will likely do this once per concern category) doesn't re-embed from scratch each time.
- Verified end to end with an in-process MCP client - correct clause (XIX, early termination) came back through the actual protocol layer, not a direct function call.
- Takeaway: `@mcp.tool`'s type-hint-to-schema generation means the tool's callable interface is defined once, by the function signature, not hand-written twice (once for the function, once for a schema).

---

## Entry 9 — Chunking bug found on a second real document (Phase 6)

- Wiring the full graph (Planner + Retriever + Calculator) against a second real document (FTC sample lease, numbered `1. 2. 3.`) instead of just the PA template (numbered `I. II. III.`) surfaced a real bug: `chunk_by_clause`'s regex only matched Roman numeral headings. On the FTC document it found zero split points and silently treated the entire document as one chunk - every single retrieval query returned the exact same result (the document's title/preamble), with no error.
- Fixed by matching either Roman or Arabic numeral section headers.
- After the fix, retrieval on the same document revealed a second, different layer of findings: some categories correctly returned nothing good because the document genuinely lacks that clause (no right-of-entry or liability clause exists in this lease); but two categories missed better content that *does* exist (maintenance/repair grabbed the utilities clause instead of the actual building-problems clause; automatic renewal grabbed the rent-amount clause instead of the clause that actually states the auto-renewal terms).
- Takeaway: testing a working pipeline against a second, differently-formatted real document caught a bug that a single test document made invisible. A chunking or retrieval strategy that works on one document's formatting quirks isn't proven until it's been tried against a document with different quirks. This is also the concrete case for the Reviewer node - three distinct failure types now documented (chunking bug, correctly-absent content, genuinely-missed content), and nothing in the pipeline yet distinguishes a trustworthy result from a weak one.

---

## Entry 10 — Reviewer catches real misses, but pipeline order let one leak through (Phase 6)

- Wired all four nodes into the full graph and ran it against the FTC document. The Reviewer correctly verified the 2 genuinely good matches and rejected all 6 weak/wrong ones - including the two subtle misses (maintenance, automatic renewal) where a plausible-but-wrong clause had been retrieved. Zero false verifications.
- But found a real ordering bug: Calculator ran *before* Reviewer, so it computed a confident-looking $75 late-fee exposure for "early termination" using the wrong clause - the same one already reused for the late fee category - even though the Reviewer, running right after, correctly flagged that category as not found. The final output showed a real-looking dollar figure attached to a provision that doesn't exist in the document.
- Fixed by reordering the graph: Retriever -> Reviewer -> Calculator, and having Calculator only run on clauses the Reviewer has already verified.
- Takeaway: a correct Reviewer doesn't help if something downstream never has to pass through it. Trust gates only work if everything that reaches the user actually flows through them - the order nodes run in is itself a safety property, not just a technical detail.

---

## Entry 11 — Full pipeline working end to end (Phase 6 complete)

- All five nodes wired together: Planner -> Retriever -> Reviewer -> Calculator -> Decision Report. First real run against the FTC sample document produced a complete, accurate decision report - every finding checked out against the manual analysis done weeks earlier during test-set labeling.
- Late fees correctly classified concerning with the same reasoning identified by hand originally, plus a real computed dollar exposure. Security deposit correctly classified neutral, matching its original test-set label exactly. The 6 categories this document genuinely doesn't address were all honestly reported as "not addressed" rather than padded with a weak guess.
- Takeaway: the individual pieces (classifier, retriever, calculator, reviewer) were each tested in isolation across Phases 2-6, but this is the first time they were tested *together*, on a real document, producing real user-facing output - and the fact that it matched independent manual analysis is the strongest evidence yet that the design decisions along the way (clause-boundary chunking, the reviewer as a hard gate, calculator running after review) were the right calls.

---

## Entry 12 — Guardrails (Phase 7 complete)

- Added document validation (rejects empty or oversized documents) and a call budget check (caps how many concern categories the pipeline will act on, protecting against runaway API cost if the planner ever becomes smarter than a fixed checklist).
- Both guardrails verified against deliberate failure cases (empty doc, 60k-character doc, 20-category list) before confirming normal-sized input passes through untouched.
- Full pipeline re-run afterward produced the identical decision report as before - confirms the guardrails don't interfere with normal operation, only edge cases.
- Takeaway: most of Phase 7's actual safety work was already done by the Reviewer in Phase 6. What was left was genuinely small - input bounds and a cost ceiling - because the harder problem (deciding what's trustworthy) was solved earlier, not bolted on at the end.

---

## Entry 13 — FastAPI + Streamlit confirmed working (Phase 8, core)

- Built the FastAPI backend and Streamlit frontend, then verified them against both sample documents through the actual UI, not just the terminal script.
- FTC sample through the UI produced an exact match to the earlier terminal run (1 concerning, 1 neutral, 6 not addressed, same categories) - confirms the backend/frontend wiring is correct, not just that it runs without crashing.
- PA template through the UI (never run through the full 5-node pipeline before, only tested piece by piece earlier) correctly flagged the appliance-warranty clause as concerning - independently matching the label given by hand while building the original test set months earlier.
- Remaining for Phase 8: Docker containerization.

---

## Entry 14 — Docker (Phase 8 fully complete)

- Containerized both services with a shared Dockerfile and docker-compose.yml - one image, two containers (api on 8000, frontend on 8501), networked so the frontend reaches the backend by container name instead of localhost.
- Real friction along the way: Docker Desktop needed to actually be launched (not just installed) and its engine needed a restart before `docker ps` would connect - a good reminder that "installed" and "running" aren't the same thing for background services.
- Confirmed working end to end through `docker compose up --build` - same decision report behavior as the non-Docker version, now portable to any machine with Docker installed.
- Phase 8 complete: FastAPI + Streamlit + Docker, all three pieces done.

---

## Entry 15 — Live deployment confirmed (Phase 10, deployment)

- HuggingFace's Docker Spaces tier changed to paid mid-project (a genuine, undocumented platform change, confirmed via HF's own community forums) - pivoted to Streamlit Community Cloud instead, which is purpose-built for single-process Python apps and remains genuinely free.
- Deployed `streamlit_app.py` (a standalone entry point calling the LangGraph pipeline directly, since Streamlit Cloud runs one process, not a multi-container setup) with real secrets configured.
- First live analysis showed the security deposit clause flip from NEUTRAL to CONCERNING between two runs of the identical document. Re-ran immediately - back to NEUTRAL. Confirms this is the same model non-determinism already documented in Phase 3, not a deployment-specific bug. Good real-world confirmation that a documented limitation actually behaves the way it was documented to behave.
- Live app: https://clauseguard.streamlit.app

---

## Template for future entries

- What happened:
- Result (numbers):
- Decision:
- Takeaway (if worth keeping):
