# Chunking strategy comparison

Written Aug 25, 2026. Supersedes the Phase 4 comparison in
`docs/03_chunking_and_vector_store.md`.

## What was wrong with the original

Phase 4 compared clause-boundary chunking against fixed-size character slicing, on three
questions, one document, judged by eye, by the person who expected clause chunking to win.

The deeper problem is what it was compared against. `chunk_fixed_size` cuts every 500 characters
regardless of content: mid-word, mid-sentence, mid-clause. It is not a baseline, it is a
strawman. Any method respecting any boundary beats it, so beating it says almost nothing about
whether *clause* boundaries specifically were the right idea.

## The comparison

Four strategies, both sample documents, 12 cases where an answer exists, scored by
`evaluation/eval_retrieval.py`. No API calls; embeddings run locally.

- **by_clause** — split on section numbering, the shipped strategy
- **recursive** — `RecursiveCharacterTextSplitter`, paragraph then line then sentence then word.
  What most production RAG systems use. The baseline that actually matters.
- **semantic** — embed each sentence, cut where cosine distance to the next sentence spikes above
  the 80th percentile. Knows nothing about numbering.
- **fixed_size** — the original strawman, kept for continuity

Chunk size fixed at 700 characters with 80 overlap for the two size-based strategies, matching
`MAX_CHUNK_CHARS`. If sizes differed, the experiment would measure size, not strategy.

## Two metrics, because one of them is not neutral

**recall@k** — the rank of the first single chunk that is the answer. Rewards keeping a clause
intact, which is a genuine advantage: the classifier is handed one chunk and must judge a whole
contract term from it.

But it is not fair across strategies. Only clause chunking keeps `XXXIII.` attached to the front
of a chunk, so only it can match on an exact section reference. Everything else must clear an 80%
word-containment threshold inside a single chunk, and a strategy that splits the answer across two
chunks scores zero even though the pipeline retrieved both halves.

**coverage@k** — did the top k chunks *together* contain the answer. The union. Fair to splitting
strategies and closer to what the pipeline passes downstream.

**The metric caught itself being unfair, in the direction that mattered.** Semantic chunking
scored `recall@1` 75% but `coverage@1` 66.7%, which should be impossible since the union of one
chunk is that chunk. On PA clause XXXI, semantic cut the document just after the section heading.
The chunk *starts* with the right reference, so reference matching scored it a hit at rank 1,
while the clause body was in the next chunk. Reference matching over-credits any strategy that
begins a chunk at a clause boundary and then cuts it short. For semantic, 6 of its 12 hits came
through that route.

## Results

```
                 recall@1  recall@2  recall@3  recall@5    cov@1   cov@2   cov@3   cov@5
by_clause          75.0%     83.3%    100.0%    100.0%     75.0%   83.3%  100.0%  100.0%
semantic           75.0%     91.7%     91.7%     91.7%     66.7%   83.3%   91.7%   91.7%
recursive          66.7%     83.3%     91.7%    100.0%     58.3%   83.3%   91.7%  100.0%
fixed_size         58.3%     75.0%     75.0%     91.7%     58.3%   83.3%   83.3%   91.7%
```

Per-case rank, which is more informative than the aggregate at n=12:

```
document       category                                    by_clause  recursive  semantic  fixed
lease_pa_001   late fees and rent payment terms                1          1          1        1
lease_pa_001   early termination and lease-breaking fees       1          2          1        1
lease_pa_001   security deposit terms                          1          1          1        4
lease_pa_001   landlord right of entry and notice period       1          1          1        1
lease_pa_001   guest and occupancy restrictions                3          4          2        2
lease_pa_001   maintenance and repair responsibilities         1          1          1        5
lease_pa_001   liability and indemnification                   1          1          1        2
lease_pa_001   automatic renewal and rent increases            1          2          1        1
lease_ftc_001  late fees and rent payment terms                1          1          1        1
lease_ftc_001  security deposit terms                          1          1          1        1
lease_ftc_001  maintenance and repair responsibilities         2          3          2        9
lease_ftc_001  automatic renewal and rent increases            3          1          7        1
```

## What it means

**Against a real baseline the margin is one test case.**

At k=3, the pipeline's actual operating point, clause chunking is the only strategy at 100% on
both metrics. Recursive reaches 91.7%. That gap is a single case out of twelve, and at n=12 one
case is 8.3 points. It is not a result that survives on its own.

Paired by rank, clause chunking is better on 4 cases, worse on 1, tied on 7. Mean rank where both
find it: 1.42 against 1.58. Directionally consistent, not statistically established.

**The honest claim is therefore narrower than the one in the README.** Clause chunking is never
worse than recursive splitting on these documents, is better on four of twelve cases, and is the
only strategy that finds every answer within the three chunks the pipeline fetches. It is not
dramatically better than a generic production-standard splitter. The large win reported in Phase 4
was over naive character slicing, which is the weakest possible comparison.

**Semantic chunking is the surprise.** It beats clause chunking at k=2, 91.7% against 83.3%,
finding the PA guest clause at rank 2 where clause chunking puts it at rank 3, knowing nothing
about section numbering. If k were ever reduced to halve the Reviewer calls, semantic would be the
better chunker at that depth. It is worse at k=3 and it costs an embedding pass over every
sentence at ingest.

**Fixed-size is confirmed as the worst on every metric at every depth.** The original Phase 4
direction was right. Only its magnitude was inflated by the choice of opponent.

## Decision

Keep `by_clause`. It is never worse than the alternatives, it is the only strategy at 100% at the
operating point, and the section reference it preserves is used by the report and by the golden
set. The claim in the README changes; the code does not.

## What this does not establish

Two documents, both leases, one a blank template. 12 scorable cases. One case is 8.3 points, so
nothing here separates by_clause, recursive and semantic with any confidence.

No Terms of Service in the comparison, which is the document type where clause numbering does not
exist and where the ranking would most likely change. That is the obvious next test and it needs
a labelled ToS golden set that does not exist yet.

Semantic chunking used a fixed 80th-percentile threshold, not tuned. A tuned threshold might do
better; tuning it on these 12 cases would make it a dev-set number.
