# ADR-0001: Source-to-office links are an evidence-bearing bitemporal relation

Status: Proposed

Date: 2026-09-20

## Context

The catalog sweep of 2026-09-19 harvested 443 publisher names from Socrata and ArcGIS Hub and attempted
to match each to an office in the 20,069-row BPS frame. Three facts came out of it that together
determine the shape of this relation.

**The relationship is many-to-many from the very top of the distribution.** The NYC open-data portal is a
single endpoint covering five separate BPS borough offices, two of which are the 8th and 9th
highest-volume permit offices in the country. In the other direction, an office can be served by a city
portal and a county aggregation at once. A `source_id` column on the office, or a `bps_id` column on the
source, is wrong for the largest publisher in the dataset.

**The link carries metadata that belongs to neither side.** How confident are we, by what method, over
what period, covering how much. `City of Charlotte` publishes the data while Mecklenburg County is the
BPS office - a statement about the pairing, not about either party.

**Wrong links are the dominant failure mode, and they are silent.** Four distinct classes of false match
were found and fixed during the sweep: foreign publishers matched to same-named US places
(`Government of Yukon` to Yukon, Oklahoma); a state agency matched to an unrelated office; state names
parsed as place names (`Delaware County, Ohio` to Delaware); and `county` glued inside a domain token
escaping a `\bcounty\b` test, so `data.marincounty.gov` matched Marina, a different city 150 miles away.
Every one of these produced a plausible-looking row. Each was recoverable only because the matcher's
reasoning had been written down; nothing in the row itself was visibly wrong.

19 names were left deliberately unresolved - the same name in several states with no geography available
to disambiguate. They are a known hole, and the headline coverage figure is a lower bound because of them.

## Decision

Source-to-office links are their own table: many-to-many, append-only, bitemporal, and carrying mandatory
structured evidence. Schema and constraints in
[`docs/design/entity-resolution.md`](../design/entity-resolution.md). Five properties are load-bearing:

- **`evidence` is `NOT NULL` and structured.** Centroid, county FIPS, catalog record id, adjudicator
  note. The thing that made every false match above recoverable was inspectable reasoning, so the schema
  requires it rather than hoping for it. `data/frame/bucket1_audit.csv` is this column's flat-file
  ancestor.
- **`confidence` is a property of the link, not the source.** One portal links confidently to one office
  and speculatively to another. Rolling up to the source is a view, and the rollup is `MIN`: a source
  resolving to five offices with one guess among them is not an A-confidence source, and taking `MAX`
  would launder the guess into the other four.
- **Unresolved links are rows, not absences.** `link_method = 'unresolved'` with a candidate list in
  `evidence`. This converts the 19 ambiguous names from silent under-coverage into a worklist, and makes
  the lower-bound claim auditable instead of merely asserted. A `CHECK` makes `confidence IS NULL`
  equivalent to `link_method = 'unresolved'`, in both directions, so neither an unresolved row carrying a
  tier nor a resolved row missing one can be written.
- **Valid time and transaction time are separate axes, and retraction is not time travel.** `valid_to`
  means the link stopped being true - a portal migration. `superseded_by` means it was never true - the
  Marina bug. A retraction never sets `valid_to`, because closing the interval would assert the link
  *was* true until some date, which is precisely the false claim being retracted. Queries filter
  `superseded_by IS NULL` unconditionally, then filter valid time for the as-of date.
- **At most one live link per `(source, office)`**, enforced by a partial unique index. This is the
  constraint that stops a resolver re-run from quietly producing two live rows and double-counting units.

## Consequences

- A coverage figure can be defended down to the individual row, including the rows that are wrong. The
  `16.63%` claim is quotable because the 443 adjudications behind it are inspectable.
- The unresolved set cannot be dropped by accident. `coverage_stat` returns `sources_unresolved` in the
  same row as `units_linked`, so a consumer has to actively discard the caveat rather than merely forget
  it.
- Correcting a link is an append, so a claim made in October still reproduces in December. That is the
  entire point, and it costs storage growth proportional to correction volume - acceptable at this scale,
  where corrections number in the hundreds.
- The partial unique index depends on `source` being one row per **endpoint**. Coarsening that grain to
  one row per domain would silently break the index, because a domain can legitimately host a residential
  and a commercial dataset for the same office. This is now a standing constraint on the `source` table.
- Writes are more expensive than an upsert: assert, never update. Resolver code must be written to append
  and supersede, which is a real ergonomic cost paid on every correction.
- Storing `superseded_at` denormalized from the successor's `asserted_at` is redundant. It is guarded by
  a `CHECK`, and it buys a scan instead of a self-join on every belief-state query.

## Alternatives considered

- **`source_id` as a column on the office, or `bps_id` on the source.** Cannot represent NYC, which is
  the single largest open-data permit publisher in the dataset. Rejected on the first row of real data,
  not on principle.
- **A join table without evidence, with the reasoning kept in a separate audit log.** This is what the
  sweep actually did - `bucket1_candidates.csv` beside `bucket1_audit.csv` - and it worked only because
  one person held both files in their head at once. The two drift the moment resolution is incremental,
  and the audit trail is exactly what is needed at the row that looks fine.
- **`confidence` on the source.** Simpler, and wrong in a way that hides the error: a source's worst link
  is the one that needs review, and a source-level tier makes the good links vouch for the bad one.
- **Drop unresolved names rather than storing them.** Cheaper, and it makes the coverage figure look
  identical while quietly turning a lower bound into an apparent point estimate. Rejected because the
  distinction between those two things is most of what makes the figure worth quoting.
- **Single-temporal, with corrections applied in place.** Half the storage and much simpler writes. It
  makes a past claim unreproducible, which conflicts with D1 and D7 and would have erased the evidence
  trail for all four false-match classes above.

## Revisit when

A correction volume large enough that append-and-supersede becomes a performance problem rather than a
storage one, or the first case where a link genuinely needs a fourth temporal axis (for example, a
distinction between when a portal published data and when the permit was issued - currently held at the
observation layer, not here).

## References

- [`docs/design/entity-resolution.md`](../design/entity-resolution.md) - schema, constraints, views
- `docs/design/history.md` §D1 (observation log), §D3 (BPS ID as identity), §D5, §D7 (bitemporality)
- `data/frame/bucket1_candidates.csv` - 183 matched offices with confidence tiers
- `data/frame/bucket1_audit.csv` - 347 rejections, each with its reason
- [ADR-0002](0002-no-mirror-relation.md), [ADR-0003](0003-jurisdiction-identity-is-bps-scoped.md)
