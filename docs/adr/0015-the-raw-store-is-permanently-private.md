# ADR-0015: The raw store is permanently private; only derived tables are releasable

Status: Proposed

Date: 2026-09-21

*Back-fill. The decision is D10 in `docs/design/history.md`, dated 2026-09-19 there and carrying its own rationale.
This ADR records it in the permanent series and adds what has been observed since.*

## Context

Two facts that were each already settled, taken together, force a boundary the earlier draft left
implicit.

[ADR-0006](0006-the-observation-log-is-the-source-of-truth.md) makes raw bytes the source of truth and
every downstream stage a pure function of them, so extraction improves by replaying rather than
re-crawling. That is the property the whole architecture is built around, and it argues for keeping the
raw store forever.

`docs/design/history.md` §11 separately establishes that owner-builder permits carry an individual's name attached to
their home address. **Those names are in the raw HTML.** Not in a field this project chose to extract — in
the bytes, whether or not anything ever reads them.

## Decision

- **The raw store is never published.** Not as a torrent, not as a requester-pays bucket, not on request.
- **Replayability is an internal property.** Third parties get the derived dataset and the extractor
  source; they do not get the ability to re-derive it. External reproduction means re-crawling, which is
  not reproducible against a changing web. **State this plainly in the dataset documentation** rather than
  implying a reproducibility guarantee the architecture cannot honour.
- **Individual-vs-business classification happens at extraction time, not release time.** The
  classification is stored; the raw applicant-name string stays in the raw store and never lands in
  `permits` or any other derived table.

The last rule is the load-bearing one. A release-time filter over a derived table that already holds the
names is a strictly weaker posture, because it depends on the filter being correct forever rather than on
the data never being there.

## Consequences

- **This has now been confirmed live rather than reasoned about.** The St. Louis bucket-4 probe returned a
  parcel table whose columns are Parcel ID, Address and **Owner Name**, with individual names attached to
  residential addresses, from a portal that publishes no permit records at all
  ([evidence](../evidence/2026-09-21-bucket4-resolution.md)). The PII arrives in the course of
  *classifying a portal*, before any extraction decision is made — which is precisely why the boundary has
  to sit at the store rather than at the extractor.
- **The extraction schema already complies and was not designed to.** `permits/emit.py` has no applicant
  or owner field: `address`, `description`, `valuation`, and the classification enums. A name could only
  reach a derived table via the free-text `description`, which is a real leak path and is not currently
  filtered.
- **Reproducibility has to be described honestly, and that is a cost.** A dataset paper that cannot offer
  its inputs is weaker than one that can. The available substitute — publish the extractor, the manifest
  schema, and per-source record counts and hashes — lets a reader verify internal consistency but not
  re-derive. Overclaiming here would be worse than the limitation.
- **It constrains collaboration, not just publication.** A second machine or a collaborator means copying
  the raw store, and every copy is a place the names live. No policy on that exists.
- **It makes the golden set harder to outsource.** [ADR-0014](0014-the-golden-set-precedes-the-pipeline.md)
  requires labelling from the rendered page in the raw store, and the rendered page is exactly what cannot
  be handed to an external labeller unredacted.
- **Deletion is not currently possible.** There is no mechanism to remove one person's data from the raw
  store on request, because nothing indexes which pages mention whom. Whether that is required depends on
  jurisdiction and on whether the data is treated as public record, and the question has not been
  researched.

## Alternatives considered

- **Publish a redacted raw store.** The version that would preserve the reproducibility claim. Rejected:
  redacting names out of arbitrary municipal HTML reliably enough to publish nationally is a harder NLP
  problem than the extraction pipeline itself, and failure is unrecoverable once distributed. This is the
  asymmetry that decides it — a false negative in a redactor is a permanent disclosure.
- **Publish raw bytes only for offices whose portals expose no personal names.** Narrower and superficially
  safe. Rejected because it requires being right about which portals those are, forever, including after a
  vendor adds a field; and because the resulting corpus would be biased toward exactly the simplest
  portals, making it useless as a benchmark.
- **Filter at release time over a derived table that holds the names.** Operationally easier and keeps the
  names available for internal entity resolution. Rejected on the standing argument: it depends on a
  filter being correct forever rather than on the data never being there.
- **Do not retain raw bytes at all; extract and discard.** Removes the problem entirely. Rejected because
  it destroys replay, which is the single most valuable property the architecture has — it has already
  caught four defects at zero request cost — and because it would make every extractor improvement require
  a re-crawl.

## Revisit when

The dataset is prepared for actual publication, at which point the free-text `description` leak path needs
an explicit decision rather than an observation. Also revisit if a collaborator or second machine is
added, because the copy policy does not exist and would need to.

## References

- `docs/design/history.md` §D10, §D1, §11 (legal and ethical constraints)
- [ADR-0006](0006-the-observation-log-is-the-source-of-truth.md) — the replay property this constrains
- [ADR-0014](0014-the-golden-set-precedes-the-pipeline.md) — labelling from the raw store
- [`docs/evidence/2026-09-21-bucket4-resolution.md`](../evidence/2026-09-21-bucket4-resolution.md)
  — owner names observed in a portal that publishes no permit records
- `permits/emit.py` — the derived schema, which carries no name field
