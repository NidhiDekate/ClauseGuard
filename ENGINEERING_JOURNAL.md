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
- Live app: https://clauseguard-ai.streamlit.app

---

## Entry 16 — Reopening the project, and finding 67 defects in it

- Reopened ClauseGuard to add proper LLM evaluation. Expected to bolt eval scripts onto finished work.
- Audited all ten phases against the code instead of against my own summaries. Result: 67 defects.
- Takeaway: auditing your own work against your own notes finds nothing. The notes are where the mistakes came from.

---

## Entry 17 — The leakage that voided every published number (D1)

- Diffed `clause_classification_examples.json` against `test_set.json`, two files nobody had ever compared.
- **Eight of the nine few-shot examples were verbatim clauses from the 53-clause test set.** Every accuracy figure I had published was measured on data whose answers were sitting in the prompt.
- Fix: nine replacements from HUD model lease 90105a, public domain. Verified zero exact matches, highest word overlap 0.256 against 1.0 for eight of the originals.
- Added `check_leakage.py` matching on word overlap rather than exact strings, since a reworded near-duplicate leaks just as badly.
- Takeaway: the two files that must never overlap are the two nobody thinks to compare.

---

## Entry 18 — Retrieval measured for the first time (E1)

- Built a 16-case golden set: 2 documents by 8 categories, 12 answerable, 4 genuinely absent. Zero API calls, deterministic text matching.
- Keyed it on clause reference plus snippet, **not chunk IDs**, because chunk IDs mean nothing once chunking changes and comparing chunking strategies was the point.
- Result: recall@1 75%, recall@2 83.3%, recall@3 100%. The pipeline read rank 1 and fetched k=2, so a quarter of the answers were being retrieved and never looked at.
- Fix: k=3, and the Reviewer changed from a yes/no gate on the top result to choosing the best of three. Zero extra API calls, since it was already one call per category.
- Both misses had the same cause: compound category names like "guest **and** occupancy restrictions" split the query and the wrong half won.
- Takeaway: a gate can reject noise. It cannot do anything about a miss.

---

## Entry 19 — A parser bug that looked like a model being bad

- Seven-model comparison. `deepseek-v4-flash` scored 11/53 with 25% coverage.
- It was not the model. It narrates its reasoning before emitting JSON, and the parser only accepted a response that was JSON and nothing else.
- Wrote `src/parsing.py`: strips think-blocks and code fences, then walks the text for balanced `{...}` spans using brace counting rather than a regex, because JSON nests and a regex cannot count.
- Rerun on the same responses: deepseek 11 to 37, **gemini 40 to 49, moving it from fifth place to first.** Nothing about any model changed.
- Takeaway: an evaluation measures the whole path. A model that answers correctly and formats differently scores the same as a model that answers wrong.

---

## Entry 20 — Two annotators, and the definition the project was arguing with itself about

- Built a held-out set: 28 clauses from a Boston Housing Authority lease used nowhere else. Two annotators labelled independently and blind.
- **Agreement 15 of 28. Cohen's kappa 0.32.**
- Ten of the thirteen disagreements ran one direction. I label on **harm**; prompt v2 classified on **typicality**. Nobody had written down which the project meant, and both rubrics agree on most clauses, so aggregate accuracy could never have shown it.
- This explained the six clauses no prompt could fix. Four model families all called `pa XLIV` and `spotify liability_cap` neutral and all disagreed with my gold set. They were correctly applying a definition my labels did not use.
- Decision: harm wins, because the user has not read the document and does not know what typical looks like. Wrote `docs/06_annotation_guidelines.md`, nine standing decisions, and re-derived both gold sets from it.
- Takeaway: an annotation rubric is not documentation. It is the definition, and without it two artifacts can disagree for months in silence.

---

## Entry 21 — The chunker collapsed on anything without numbers (D39, D28, D29)

- `chunk_by_clause` matched only `I.` or `1.` at line start. Any Terms of Service written with headings, letters or plain paragraphs became **one chunk**, and every query on that document returned it. No error. The README claimed ToS support throughout.
- Fix: a fallback chain, numbered then decimal then lettered then headings then paragraphs, using the first that genuinely splits. "Genuinely" matters: a pattern matching once near the top gives a fragment plus a chunk holding the whole document, which is the same failure in disguise.
- Also filtered preambles and signature blocks (the FTC preamble is the false match that motivated the Reviewer, so a chunking problem was being fixed downstream by an LLM judge), and split oversized chunks against the embedding model's real 256-token limit.
- Verified byte-identical output on both E1 documents first, so E1 did not need rerunning.
- Takeaway: silent failures need a loud default. The retriever now prints which strategy fired.

---

## Entry 22 — Deleting the few-shot examples (E8)

- Few-shot had been assumed from the start and never tested. Nine examples rode on every call, which is where the Phase 3 cost estimate went 3.5x wrong.
- Result: tied at 42/53 with zero-shot. Zero-shot used 55% fewer input tokens, cost 36% less, and missed one fewer concerning clause.
- Deleted them, and `check_leakage.py` with them. The leakage in Entry 17 is now **structurally impossible** rather than guarded.
- Takeaway: an ablation you never run is a design decision you never made.

---

## Entry 23 — Faithfulness, and a clause in my gold set that does not exist (E3)

- Nothing checked whether the sentence written about a clause follows from that clause. Accuracy scores a right label with an invented reason as a win.
- Judge is `claude-opus-5`, chosen because it is **not** the model under test. The script refuses to run if judge and system are the same model.
- Result: 46 of 53 grounded, 86.8%. Six have the right label and an unsupported claim. Three are the same failure: the model states a protection is **absent** where the clause is silent. "Without paying you" on a clause that never mentions payment.
- The judge flagged one explanation as invented and **it was our dataset that was wrong.** Seven gold clauses were stored abridged with an ellipsis. One, `2.13`, was two unrelated clauses spliced under a third clause's number, and half of it duplicated a clause already in the set.
- Takeaway: the judge was right, the model was right, and the ground truth was wrong. Nothing else in this project could have caught that.

---

## Entry 24 — Measuring the Reviewer, which had never been measured (E2)

- The Reviewer is an LLM-as-a-judge that every finding passes through. The ROADMAP claimed its value was proven; it was a spot check.
- Built on E1's golden set, which already had the answer, the on-topic-but-wrong distractors, and four absent categories. Retrieval recall@3 is 100%, so the answer is always available and any miss is the Reviewer's.
- Result: recall 11/12, absent rejected 3/4, precision 92%, identical across two runs.
- One genuine error: on a document with no indemnity clause it picked FULL DISCLOSURE, because that clause mentions legal and financial consequences. Consequences for breach are not liability allocation.
- One probable golden-set error, on a mapping flagged as arguable before this ran. Recorded as disputed, not relabelled.
- Takeaway: it did not move at all across 32 calls, where the classifier moves by up to three clauses. Nobody had looked at that either.

---

## Entry 25 — Numbers move more than I thought

- The same model, same prompt, same clauses, temperature 0, has scored **41, 43, 44, 45 and 46** across this project.
- Almost every comparison I had made was one run against one run. The few-shot experiment came down to a single clause, which is well inside that spread.
- Added `--repeat N` to the eval. Reports now carry the range, not a single figure.
- One thing only per-case output shows: gemini scores 44 in all three runs, and two clauses still flip between runs in opposite directions. **A stable total is not a stable system.** The errors cancel.
- Takeaway: a number without a spread is not a result.

---

## Entry 26 — One rate limit took down the whole app

- Groq's daily limit hit mid-run. The Reviewer had no fallback, so the exception propagated and the entire analysis crashed. The classifier had a fallback and survived; the Reviewer did not, and nobody had noticed because nothing had ever measured the Reviewer until E2.
- First fix was wrong. I pinned the Reviewer to `gpt-oss-120b` and left the fallback at the module default, which was also `gpt-oss-120b`. A model cannot be its own fallback.
- Pulled the fallback logic out of `classify_clause.py` into `src/llm.py` so both nodes share one `invoke_with_fallback`, with `fallback_model` and `fallback_provider` as parameters instead of module constants.
- Config is now mirrored on purpose: classifier gemini then gpt-oss, Reviewer gpt-oss then gemini. Different vendor on each side.
- Takeaway: a fallback you never exercised is a guess. This one was worse than a guess, it was a no-op.

---

## Entry 27 — The report told the user their lease has no late fee clause

- `report_node` mapped every unverified category to "not addressed in this document". The only reason a category could be unverified was that the model found nothing **or** the call failed, and both rendered identically.
- So on a rate limit the app printed a confident negative about a document it had never read. The test lease has a late fee clause: $25 plus $5 per day, uncapped.
- Split the states. `error` now carries "Analysis failed for this category, so nothing can be said about it either way" plus the underlying exception, renders amber with a red banner, and is excluded from the not-addressed count.
- Takeaway: **never state an absence you did not establish.** For a tool whose whole purpose is that the user does not read the document, silently converting a failure into a clean bill of health is the worst possible failure mode.

---

## Entry 28 — 77 seconds to 19

- A single run took over a minute. Every per-category Reviewer call and every classifier call ran in sequence, and they are independent of each other.
- Rewrote `reviewer_node` and `report_node` around `_review_one(category, clauses)` and `_classify_one(category, review, fee_computations)`, both dispatched through a `ThreadPoolExecutor` with `MAX_CONCURRENT_CALLS = 6`.
- 77s to 19s. No change to output.
- Six workers is a guess bounded by provider rate limits, not by anything measured. Three FTC categories failed in one run and concurrency is the first suspect, so this number may come down.
- Takeaway: latency here was never the model, it was doing nine independent calls one after another.

---

## Entry 29 — Circuit breaker

- Once gemini started rejecting calls, every remaining call in the run still tried gemini first, waited for the failure, then fell back. Nine categories, nine wasted timeouts.
- Added a module-level `_DEAD` set in `src/llm.py`. First failure marks the model dead for the rest of the process and later calls go straight to the fallback. `reset_circuit_breaker()` clears it.
- It does not persist across runs on purpose. A daily quota and a one-off blip look the same at the call site, and the run boundary is the only place I can honestly retry.
- Takeaway: the retry is cheap once and expensive nine times.

---

## Template for future entries

- What happened:
- Result (numbers):
- Decision:
- Takeaway (if worth keeping):
