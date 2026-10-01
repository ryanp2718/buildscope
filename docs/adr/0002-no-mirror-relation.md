# ADR-0002: No mirror relation; cross-portal duplication is an ordering plus observation-layer dedup

Status: Proposed

Date: 2026-09-20

## Context

The same underlying permit records are published in more than one place. Four shapes of this are already
visible in the 2026-09-19 catalog sweep:

- a city publishes to its own Socrata instance while the county republishes it as an ArcGIS layer
- the 18 statewide portals found in the sweep aggregate municipal data already published locally
- a portal migration leaves the old endpoint serving for months after the new one appears
- ArcGIS Hub surfaces the same item under several organization pages

The question raised was whether to model this with a `mirrors` or `source_alias` concept, on the grounds
that duplication would clutter the bitemporal link history established in [ADR-0001](0001-source-office-link-is-an-evidence-bearing-relation.md).

**That premise does not survive checking, and the real problem is worse.** Two portals publishing Austin
produce two live link rows, which is *correct*: there genuinely are two places to fetch from, neither row
is a correction of the other, and neither churns. Portal migration does add rows over time, but those
rows are the reproducibility guarantee of D7, not clutter - discarding them is the thing that would
break.

The actual damage is one layer down. **Fetch both and fold both, and Austin's permit count doubles.**
That is a data-integrity defect, not a tidiness problem, and it would surface in Spike B as a roughly 2x
discrepancy against the BPS control total.

## Decision

No `mirrors` table and no `source_alias` concept. Duplication is handled as two separate questions,
resolved at two different layers:

- **Which source do I fetch from?** An ordering. `source_office_link.fetch_precedence`, an integer,
  lowest wins among live links for an office. No new tables.
- **Are these two records the same permit?** `observation_key`, already established in D5. Deduplication
  happens at the observation layer, where actual records can be compared.

Equivalence between sources is never asserted, only measured. If a real overlap is ever quantified -
"source B's records are a strict subset of source A's, checked over N months" - that is an empirical
finding and earns its own table with the measurement attached.

## Consequences

- The double-count defect is prevented at the fetch layer by precedence, and caught at the fold layer by
  `observation_key` if precedence is misconfigured. Two independent mechanisms, which is appropriate for
  a defect that is invisible in the output.
- Deduplication decisions are made against records rather than against source metadata, so the evidence
  for "these are the same permit" is the records themselves.
- `fetch_precedence` is one more field a human must set correctly, and a wrong value means redundant
  fetching rather than a wrong answer. That is the right direction for the failure to point.
- Nothing records *why* two sources overlap. Accepted: that question has not yet cost anything, and the
  measurement table can be added later without migration when it does.
- A source serving an office through a slow migration keeps both links live until the old endpoint dies.
  The history is longer as a result, and that length is the feature.

## Alternatives considered

- **A `mirrors` table asserting source equivalence.** Rejected on two grounds. First, "mirror" is almost
  never exact: the county's copy of city data typically has different fields, different update latency,
  and shallower history, so the assertion is usually false in detail. Second, and more seriously, it
  would be an *unevidenced* claim in a schema whose entire discipline (ADR-0001) is that claims carry
  evidence. There is no honest value for the `evidence` column of a guessed equivalence.
- **A `canonical_source_id` self-reference on `source`.** Lighter than a table, same defect: it asserts
  equivalence without measuring it, and it forces a binary canonical/duplicate choice on relationships
  that are usually partial overlaps.
- **Deduplicate at the source layer by dropping non-canonical links.** Loses the record that a second
  access path exists, which is operationally valuable when the preferred endpoint dies - exactly the
  migration case.
- **Do nothing and rely on `observation_key` alone.** Nearly chosen; it does prevent the double count.
  Rejected because it means knowingly fetching the same data twice, which wastes request budget against
  small government servers the crawl is meant to treat politely.

## Revisit when

A measured overlap is needed for a coverage claim - for example, if a statewide aggregator turns out to
be a usable substitute for dozens of municipal portals, quantifying the subset relation becomes
load-bearing rather than incidental. At that point the measurement table is justified, and this ADR is
superseded rather than amended.

## References

- [ADR-0001](0001-source-office-link-is-an-evidence-bearing-relation.md) - the link relation
- [`docs/design/entity-resolution.md`](../design/entity-resolution.md) - `fetch_precedence`
- `docs/design/history.md` §D5 (`observation_key` versus surrogate `permit_id`), §D7, Spike B protocol
