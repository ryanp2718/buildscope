# ADR-0006: The observation log is the source of truth; every table is a fold over it

Status: Accepted

Date: 2026-09-20

*Back-fill. The decision is D1 in `DESIGN.md` and was taken at the start of the project, before this
directory existed; `DESIGN.md` has been authoritative for it until now. The context and alternatives below
are the original ones. The consequences section has been written with three replays' worth of hindsight
that the original decision did not have, and says so where it matters.*

## Context

Permit portals do not emit events. They render current state. We never observe *"issued on the 14th"*; we
observe *"on the 16th this page said Issued, and on the 9th it said Plan Review."* Any schema that stores
the first sentence has thrown away the distinction between what a portal said and when it said it, and
that distinction cannot be recovered afterwards from any amount of re-crawling — the earlier state is
simply gone from the portal.

There is a second, more mundane force. Extraction is the part of this project most likely to be wrong,
and it will be wrong repeatedly. If a bug means re-crawling, every bug costs requests against somebody
else's server, and the rate at which extraction can be improved is capped by politeness rather than by
engineering.

## Decision

**The primary table is append-only, one row per successful fetch-and-extract:**

```
(source_id, observation_key, observed_at, content_hash, extractor_version, extracted_state)
```

Current-state and lifecycle views are **folds** over that log — last row wins — never tables that are
updated in place.

- **Raw bytes are stored immutably and every downstream stage is a pure function of them.** Improving
  extraction means replaying, not re-crawling.
- **`extractor_version` is part of the key.** When v7 disagrees with v4 about the same `content_hash`,
  that disagreement is a queryable fact rather than a silent overwrite. This is what makes measured
  accuracy improvement provable rather than asserted.
- **Transitions are intervals, never instants.** The schema is `transition(from, to, observed_between:
  [t1, t2])`. A weekly cadence against a five-day lifecycle loses the middle states, and the schema must
  not pretend otherwise.
- **A page may not exist on disk without a manifest row written in the same operation**, and **every
  analysis reads the manifest, never the directory.** A page with no manifest row is not input. This is
  the operational half of the decision and is what makes provenance a property of the capture rather than
  a reconstruction afterwards.
- **The capture-time verdict is not re-litigated downstream.** A page marked `rejected` at capture stays
  rejected; a later stage may not promote it because it would be convenient.

## Consequences

- **Replay is free, and it has already paid for itself three times.** The first Clark County run emitted
  20 records out of 371 because `build()` called a milestone name outside D6's vocabulary. A shared
  `norm_date` bug nulled 100% of St. Johns' dates. A truncated control page was being replayed into the
  totals. Each was fixed and replayed over bytes already on disk for **zero requests**
  ([step 1 evidence](../evidence/2026-09-20-step1-stjohns-reconciliation.md)).
- **Storage is the price, and it is being paid.** 218 manifest rows and 149.1 MB for three months of three
  jurisdictions plus probes. Accela costs 72.3 KB per record against St. Johns' 0.76 KB, so the storage
  curve is set by which portals get crawled far more than by how many records are captured. At national
  scale this is the cost line that needs a number, and it does not have one yet.
- **"A rejected page stays rejected" is load-bearing and was nearly inverted once.** Spike A's no-result
  detector matched a JavaScript constant that Accela ships on *every* page, including pages returning
  records — a downstream stage "correcting" a capture verdict on that basis would have discarded good
  data twice over.
- **The rule has a boundary the original decision did not state, and a real incident found it.** A
  manifest verdict of `ok` means *the fetch succeeded*, not *the content is complete*. St. Johns returned
  a page announcing "Maximum record retrieved" — a successful fetch of a truncated result set. The verdict
  was correct and the page was still unusable. **Completeness is an adapter question, not a capture
  question**, because only the adapter can read a vendor's truncation banner; adapters now expose
  `page_is_complete(html)` and replays skip incomplete pages. This does not weaken the
  no-re-litigation rule: nothing promotes a rejected page, a second and orthogonal check was added.
- **Bitemporal queries are possible but not yet built.** The log carries `observed_at` per record today;
  the fold is last-row-wins and no lifecycle view exists. See [ADR-0008](0008-time-is-recorded-twice.md).
- **Append-only means mistakes are permanent and visible.** The wrong `bps_id` on three probe artifacts
  cannot be edited away, which is the intended behaviour and is mildly uncomfortable in exactly the way
  it should be.

## Alternatives considered

- **A flat current-state table, updated in place.** Cheaper, smaller, and adequate for the aggregate BPS
  queries that are the near-term deliverable. Rejected because it destroys point-in-time correctness
  *irrecoverably* — the portal will not tell you later what it said last week — and because the
  observation log is nearly free given that raw bytes are being retained regardless. The asymmetry decides
  it: the flat table can be folded out of the log at any time, and the log cannot be reconstructed from
  the flat table.
- **Store extracted records only; discard the raw HTML.** Would cut storage by roughly two orders of
  magnitude at Accela's byte cost. Rejected: it makes every extractor bug a re-crawl, and step 2's golden
  set must be drawn from the raw store rather than from live fetches (D9) or it is not replayable against
  future extractor versions.
- **Enumerate pages by listing the capture directory rather than reading a manifest.** Simpler, and it
  silently admits any file that happens to be there — including partial writes, hand-copied files, and
  pages from an abandoned probe. Rejected: provenance that is reconstructed from a filesystem is not
  provenance.
- **Key observations on content hash rather than on `(source_id, native_id)`.** Deduplicates identical
  pages for free. Rejected for step 1 under D5: a content-derived key cannot distinguish "the portal
  re-rendered the same state" from "two records happen to be identical", and the first of those is the
  observation this project is trying to count.

## Revisit when

Storage cost becomes a binding constraint at scale — the trigger is a measured national projection, not a
feeling — or a downstream consumer needs a fold that cannot be expressed over an append-only log, which
would be the first real evidence that the log shape is wrong rather than merely expensive.

## References

- `DESIGN.md` §D1, §D5, §D9, §10 (the raw-store risk row)
- [`docs/evidence/2026-09-20-step1-stjohns-reconciliation.md`](../evidence/2026-09-20-step1-stjohns-reconciliation.md)
  — the three replays and the completeness boundary
- `permits/emit.py`, `permits/capture.py` (manifest write), `spikes/step1_rebuild.py` (replay)
- [ADR-0008](0008-time-is-recorded-twice.md) — the bitemporal half, not yet implemented
