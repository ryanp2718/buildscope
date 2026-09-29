# spikes/ — the lab notebook

Forty-nine scripts. None of them are maintained, none of them are imported by
`permits/`, and nothing in `scripts/` depends on them — `tests/test_structure.py`
enforces both of those. They are here for one reason: **every number published
in [`docs/evidence/`](../docs/evidence/) came out of this directory**, and a
result whose instrument has been deleted is a claim, not a measurement.

If you are evaluating this repo, this is not the code to read. Read
[`permits/`](../permits) (the library, ~3,700 lines) and
[`scripts/`](../scripts) (six maintained tools). This directory is the
provenance chain behind the reports, kept deliberately, at the cost of looking
untidy.

## Why they look like this

They look like what they are: a question asked once, at speed, against a live
municipal portal, with the answer written down and the script abandoned. The
`_probe`, `_probe2`, `_probe3` chains are not copy-paste sloppiness surviving
review — each one is a separate attempt after the previous attempt returned an
answer that turned out to be wrong, and the earlier ones are kept because the
evidence reports cite them by name.

Three properties they do *not* have, and it is worth being explicit: they have
no tests, they have no error handling worth the name, and several will no
longer run because the portal they targeted has changed. That is acceptable for
a notebook and would not be acceptable anywhere else in this repo.

## What produced what

| Family | n | Question it was asked | Where the answer lives |
|---|---:|---|---|
| `spike_a_*` | 14 | Can permit portals be enumerated at all, across a 28-office sample? | [spike-a-portal-enumerability](../docs/evidence/2026-09-20-spike-a-portal-enumerability.md), [tier2-issuing-level-rerun](../docs/evidence/2026-09-20-tier2-issuing-level-rerun.md) |
| `spike_b_*` | 7 | Does an open-data portal's permit count reconcile with the Census BPS frame? | [spike-b-bps-reconciliation](../docs/evidence/2026-09-20-spike-b-bps-reconciliation.md) |
| `spike_c_*` | 3 | Do pages from different jurisdictions collide under a structural fingerprint? | [spike-c-template-collision](../docs/evidence/2026-09-20-spike-c-template-collision.md) |
| `measure_*` | 6 | How expensive is capture, in requests, bytes and tokens? | [measurement-ab-preregistration](../docs/evidence/2026-09-20-measurement-ab-preregistration.md), [measurement-ab-results](../docs/evidence/2026-09-20-measurement-ab-results.md) |
| `step1_*` | 15 | Can two real jurisdictions be pulled end to end and reconciled against an oracle? | [step1-stjohns-reconciliation](../docs/evidence/2026-09-20-step1-stjohns-reconciliation.md), [bucket4-resolution](../docs/evidence/2026-09-21-bucket4-resolution.md) |
| `open_weight_axis_tables` | 1 | Which records does each failing Clark extractor miss, and how do the cells compare? | [open-weight-model-axis](../docs/evidence/2026-09-25-open-weight-model-axis.md) |
| `audit_model_fairness` | 1 | Is the cross-vendor model comparison a fair test? | [model-comparison-fairness-audit](../docs/evidence/2026-09-26-model-comparison-fairness-audit.md) |
| `preregister_v2_run` | 1 | What does the step 6 plan cost, and does the roster follow its rule? | [v2-run-preregistration](../docs/evidence/2026-09-27-v2-run-preregistration.md) |
| `fetch_roster_sources` | 1 | What do the step 6 roster's endpoint listings, Hugging Face configs, cards and chat templates say, for setting its registry entries? | [v2-run-preregistration](../docs/evidence/2026-09-27-v2-run-preregistration.md), `permits/models.py` |
| `heldout_fetch`, `heldout_review` | 2 | Held-out targets for the step 6 comparison: fetch one closed window per tenancy, and hand-check the adapter's reference on it. | [v2-run-preregistration](../docs/evidence/2026-09-27-v2-run-preregistration.md) |
| `cost_per_success_intervals` | 1 | How sure can we be which model is cheaper per working extractor? | [cost-per-success-intervals](../docs/evidence/2026-09-27-cost-per-success-intervals.md) |
| `backfill_fingerprints`, `fix_portal_identity` | 2 | — | One-shot data migrations, run once against the private store. |

The inference experiments — variance, drift, conformance — are **not** here.
They are in [`scripts/conformance.py`](../scripts/conformance.py), because
unlike everything in this directory they are meant to be re-run.

## The rule this directory lives under

A spike may import another spike. It is the one place in the repo where that is
allowed, and it is allowed on a ratchet, not on principle:
`tests/test_structure.py` holds the current violation set as an explicit
allowlist and fails if a new module joins it or a known one gains importers.
Six import sites remain, across three modules, each annotated in that file with
where it is going.

The one that mattered is already gone. `measure_fetch.py` was the capture layer
— robots, politeness, verdicts, the manifest — living here under the name of the
measurement it was first written for, reached by twenty-three siblings through a
`sys.path` hack. On 2026-09-22 it became
[`permits/capture.py`](../permits/capture.py).

## Running one

From the repository root, and expect most of them to need the private data
store described in [ADR-0015](../docs/adr/0015-the-raw-store-is-permanently-private.md):

```
python spikes/spike_b_compare.py
```

Anything that fetches is rate-limited and robots-aware through
`permits.capture`; that behaviour is not optional and not per-script.
