# Retrieval evaluation

Written Aug 24, 2026. E1. The first thing in this project that was measured rather than eyeballed.

## Why this exists

Phase 4 concluded that clause-boundary chunking beat fixed-size chunking. That conclusion came from
three questions on one document, judged by eye, by the person who expected that result. The README
called one end-to-end run "full pipeline validation."

Nothing had measured whether retrieval actually finds the right clause.

## The golden set

16 cases: 2 documents by 8 concern categories. 12 where an answer exists, 4 where the document
genuinely does not address the category.

Each case stores:

```
must_find_ref       the clause that IS the answer
must_find_snippet   verbatim text from it
also_relevant_refs  clauses that are on topic and are NOT the answer
```

**The golden set is not keyed on chunk IDs.** Chunk IDs mean nothing once chunking changes, and
comparing chunking strategies was the whole point. Keying on the clause reference plus a text
snippet survives a chunking change, which is what let the same golden set be reused for the
chunking comparison in `docs/08` and the Reviewer eval in `docs/11`.

**`also_relevant_refs` earned its place twice.** It is what makes the chunking comparison fair and
what makes the Reviewer eval possible, and neither of those existed when it was written.

**Zero API calls.** Chunks are whole clauses and matching is deterministic text comparison, so this
runs free and repeatably.

## Result

```
                 @1      @2      @3      @5     @10
by_clause      75.0%   83.3%  100.0%  100.0%  100.0%
fixed_size     58.3%   75.0%   75.0%   91.7%  100.0%
```

**Every correct clause sits within the top 3.** The pipeline at the time read rank 1 only and
fetched k=2.

So 25% of the answers were being retrieved and never looked at.

## What it changed

`k` went from 2 to 3. It had been 2 with no experiment behind it.

And the Reviewer changed shape. It had been a yes/no gate on the top result, which can reject noise
but can do nothing about a miss. On the real failure, "guest and occupancy restrictions" returned
`III. OCCUPANT(S)` first, and III genuinely is about occupancy, so a strict gate approves it and
stops. What was needed was not a stricter gate but the ability to say "relevant, but this other one
is more relevant."

**Both changes cost nothing.** Retrieval is local, and the Reviewer was already making one call per
category; it now sees three candidates in that call instead of one.

Confirmed on the FTC lease: not-addressed went from 6 categories to 4, both misses fixed, and all
four genuinely absent categories stayed absent.

## Two failures with the same cause

Both misses were compound category names. "guest **and** occupancy restrictions" and "automatic
renewal **and** rent increases" split the query, and the wrong half dominated the embedding. That
is a query-construction problem, not a chunking problem, and it is why separating retrieval queries
from display labels is on the list.

## What this does not establish

n=12 scorable cases. One case is 8.3 points.

Two documents, both leases, one a blank template. No Terms of Service, which is the document type
where the chunker was later found to collapse entirely.

**The 16 mappings are one person's judgments and have never been reviewed by a second annotator.**
Two were flagged at the time as most arguable: FTC maintenance (clause 12) and PA automatic renewal
(clause II). The Reviewer eval later rejected clause II twice, independently, which is some
confirmation that the flag was right. Neither has been changed.
