# Architecture decision records

An ADR captures one significant decision: the context that forced it, the choice made, and the
alternatives rejected. It is a historical record, not living documentation. Once accepted an ADR is
immutable; a later decision that changes course gets its own ADR and marks the old one superseded.

For how the system works *today*, read [`docs/design/`](../design/). For the measurements a decision
rests on, read [`docs/evidence/`](../evidence/). An ADR explains *why* a rule in those documents exists.

ADRs 0001-0016 were written during the project's first week and are **Proposed**: drafted, not yet
reviewed. ADR-0017 is accepted.

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-source-office-link-is-an-evidence-bearing-relation.md) | Source-to-office links are an evidence-bearing bitemporal relation | Proposed |
| [0002](0002-no-mirror-relation.md) | No mirror relation; cross-portal duplication is an ordering plus observation-layer dedup | Proposed |
| [0003](0003-jurisdiction-identity-is-bps-scoped.md) | Jurisdiction identity is BPS-scoped, with forward compatibility bought by a view | Proposed |
| [0004](0004-bucket-taxonomy-gains-a-no-record-and-an-access-gated-cell.md) | The bucket taxonomy gains a no-record cell and an access-gated cell | Proposed |
| [0005](0005-a-bucket-is-demonstrated-not-inferred-from-the-search-form.md) | A bucket is demonstrated, not inferred from the search form; the gate metric may fire but may not clear | Proposed |
| [0006](0006-the-observation-log-is-the-source-of-truth.md) | The observation log is the source of truth; every table is a fold over it (D1) | Proposed |
| [0007](0007-office-identity-is-the-bps-office-id.md) | Office identity is `(state_fips, bps_id)`, assigned from the frame (D3) | Proposed |
| [0008](0008-time-is-recorded-twice.md) | Time is recorded twice - valid time and transaction time (D7) | Proposed |
| [0009](0009-adapters-first-generic-extraction-second.md) | Adapters first, generic extraction second; the template-identity premise is withdrawn (D8) | Proposed |
| [0010](0010-permit-identity-has-two-levels.md) | Permit identity has two levels - a deterministic observation key and a resolved permit id (D5) | Proposed |
| [0011](0011-milestones-are-rows-with-a-fixed-vocabulary.md) | Milestones are rows with a fixed vocabulary, not a state machine over booleans (D6) | Proposed |
| [0012](0012-ingest-everything-calibrate-one-slice.md) | Ingest everything, normalize everything, calibrate one slice (D2) | Proposed |
| [0013](0013-crawl-cadence-is-temporal-resolution.md) | Crawl cadence is temporal resolution, so it is chosen, not configured (D4) | Proposed |
| [0014](0014-the-golden-set-precedes-the-pipeline.md) | The golden set precedes the pipeline, and is labelled blind from the rendered page (D9) | Proposed |
| [0015](0015-the-raw-store-is-permanently-private.md) | The raw store is permanently private; only derived tables are releasable (D10) | Proposed |
| [0016](0016-tests-are-replay-over-the-raw-store.md) | Tests are replay over the raw store, published numbers are pinned, and the package boundary ratchets | Proposed |
| [0017](0017-the-inference-layer-uses-the-vendor-sdk.md) | The inference layer uses the vendor SDK; dependencies are declared and locked | Accepted |

## Back-fill status

Decisions D1-D10 in the design history ([`docs/design/history.md`](../design/history.md)) predate this
directory. The back-fill is complete as of 2026-09-21: every one of D1-D10 now has an ADR.

| Decision | ADR | Back-filled |
|---|---|---|
| D1 observation log is the source of truth | [0006](0006-the-observation-log-is-the-source-of-truth.md) | 2026-09-20 |
| D2 ingest everything, calibrate one slice | [0012](0012-ingest-everything-calibrate-one-slice.md) | 2026-09-21 |
| D3 office identity | [0007](0007-office-identity-is-the-bps-office-id.md) | 2026-09-20 |
| D4 tiered crawl cadence | [0013](0013-crawl-cadence-is-temporal-resolution.md) | 2026-09-21 |
| D5 two-level permit identity | [0010](0010-permit-identity-has-two-levels.md) | 2026-09-21 |
| D6 milestones as rows | [0011](0011-milestones-are-rows-with-a-fixed-vocabulary.md) | 2026-09-21 |
| D7 time is recorded twice | [0008](0008-time-is-recorded-twice.md) | 2026-09-20 |
| D8 adapters first | [0009](0009-adapters-first-generic-extraction-second.md) | 2026-09-20 |
| D9 golden set precedes the pipeline | [0014](0014-the-golden-set-precedes-the-pipeline.md) | 2026-09-21 |
| D10 raw store permanently private | [0015](0015-the-raw-store-is-permanently-private.md) | 2026-09-21 |

**A back-filled ADR states that it is a back-fill and dates the original decision**, rather than
pretending to have been written at the time. Where the decision has since been contradicted by a
measurement - as D8's DOM-fingerprint premise was by Spike C - the ADR records what survived and what did
not, and does not quietly restate the decision as though its rationale were intact. Where the decision is
unimplemented - D4 and most of D7 - the ADR says so plainly rather than describing an intention as a
mechanism.

## Writing one

Copy `0000-template.md` to `NNNN-short-title.md` with the next number, fill it in, and add the row above.
Keep it to the decision and its rationale; move mechanism detail into `docs/design/` and link to it.

Status is one of `Proposed`, `Accepted`, `Superseded by ADR-NNNN`, or `Deprecated`.

**Ground the decision in evidence where evidence exists.** This project's decisions are mostly forced by
measurements rather than by taste. An ADR that rests on a number should cite the dated report in
`docs/evidence/` that produced it, not restate the number as though it were self-evident. A reader in six
months needs to be able to tell whether the decision was right *then* and whether it is still right *now*,
and those are different questions with different answers.

Run `python scripts/check_docs.py` before committing; it catches an index row that does not match a file.
