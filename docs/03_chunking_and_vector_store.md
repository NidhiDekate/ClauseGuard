# Experiment: Chunking Strategy and Vector Store Comparison (Phase 4)

> **Status, Aug 25 2026: superseded by `docs/08_chunking_comparison.md`.** The comparison
> below is against naive fixed-size character slicing, which cuts mid-word and mid-sentence.
> That is a strawman, not a baseline, so the margin reported here is inflated. Against
> recursive character splitting, what most production RAG systems actually use, clause
> chunking wins by a single test case out of twelve. The conclusion survives; the magnitude
> does not.

**Question:** does clause-boundary-aware chunking actually retrieve better than generic fixed-size chunking? And does the choice of vector store (local vs. hosted) change anything besides speed?

## Setup

PA lease sample document, split two ways (fixed-size 500 chars with overlap, and clause-boundary — splitting before each numbered section). Both chunk sets embedded with the same local model (`sentence-transformers/all-MiniLM-L6-v2`) and stored in two vector stores: Chroma (local) and Pinecone (hosted). Three real questions with a known correct clause, run against all four combinations.

## Results

| Question | Correct clause | Fixed-size | By-clause |
|---|---|---|---|
| "does this lease have an early termination fee?" | XIX | Found, but cut off mid-sentence at both ends | Found, clean and complete |
| "what is the late fee for rent?" | X | Found, but truncated mid-word at the end | Found, clean and complete |
| "how many guests am I allowed to have over?" | XXXIII | **Returned a chunk dominated by an unrelated clause (XXXIV, Compliance with Law)** — the real answer was only partially present | Found, clean and complete |

Chroma and Pinecone returned identical results in every case — expected, since both use the same embeddings and the same chunks. The only real difference between them was speed: Pinecone's hosted queries were noticeably slower than Chroma's local ones, since every call is a real network round-trip instead of local computation.

## Decision

**Clause-boundary chunking wins, clearly.** It was correct and clean on every question. Fixed-size got lucky on two of three (technically correct clause, but messy — cut off text, wrong sentence boundaries) and outright failed on the third, returning a chunk where the real answer was crowded out by an unrelated clause. Going forward, `chunk_by_clause` is the chunking strategy used in the actual pipeline.

**Chroma for development, Pinecone validated as a deployment option.** Since retrieval quality was identical between the two, the only real trade-off is dev speed vs. production readiness. Staying on Chroma for continued local iteration (Phase 4 onward) — free, no network dependency, fast to rebuild for testing. Pinecone is confirmed working and ready to revisit at Phase 8 (deployment) if a persistent, publicly-hosted vector store is needed for the live demo instead of rebuilding an in-memory store on every server start.

## Takeaway

The failure mode on question 3 is the most useful result here — fixed-size chunking doesn't fail loudly, it fails quietly, by returning something that's *partially* relevant and looks plausible at a glance. That's a worse failure mode for a system like ClauseGuard than an obvious miss would be, since a partially-relevant, clause-mixing chunk could lead the agent to describe the wrong clause with real confidence.
