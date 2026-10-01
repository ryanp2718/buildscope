# ADR-0016: Tests are replay over the raw store, published numbers are pinned, and the package boundary ratchets

Status: Proposed

Date: 2026-09-21

## Context

> **[2026-09-22]** Two updates. The dependency clause of this ADR's Decision is superseded by
> [ADR-0017](0017-the-inference-layer-uses-the-vendor-sdk.md). And the package-boundary problem
> described below is **resolved**: `scripts/measure_fetch.py` is now `permits/capture.py`, its
> allowlist entry has been deleted, and `scripts/` has been split into six maintained tools and a
> `spikes/` lab notebook. The sequencing argument in *Consequences* — that the move should wait for
> its tests — was **not** honoured; the move went first because the directory split needed it, and the
> capture tests are now the top item in
> [`docs/design/refactoring.md`](../design/refactoring.md). Everything else here stands, and the
> paragraphs below are left as they were written.

Until today this project had no tests. That was defensible while it was three spikes; it stopped being
defensible once `permits/` grew a shared normalization layer that three adapters depend on, because the
failure mode changed shape. The defects that have actually cost this project time are not crashes:

- **`norm_date` nulled 100% of St. Johns' dates** while the adapter reported records and looked healthy.
  A fixed-width slice handed `strptime` the string `"3/2/2026 1"`.
- **Austin's sub-permits produced a 726% unit error**, because every Electrical, Mechanical and Plumbing
  record carries a populated `housing_units` value.
- **Mecklenburg County abandoned `worktype` mid-dataset** — populated 123,262 times historically, blank in
  all 500 Q1 2026 records — with no signal of any kind.
- **All 28 office ids in `portals.csv` were wrong**, and 7 of them resolved to a real, different office.
  An existence check passes on every one.
- **A figure was re-quoted after it changed.** The catalog sweep reported 112 offices / 5.0% of units;
  hand resolution later tripled it to 180 / 16.63%. The original number was not wrong when written — it
  was wrong when *re-quoted*.

Every one of these is silent. None would be caught by testing that functions return without raising, and
several would be caught by nothing short of comparing an output to a recorded expectation.

There is a second problem, structurally separate and more dangerous long-term. `scripts/measure_fetch.py`
is the capture layer — robots handling, politeness, verdicts, the manifest, D1's write-page-and-row-in-one-operation
rule — and it is **imported by 23 sibling scripts** through `sys.path` insertion, under a filename that
claims it belongs to Measurements A and B. 24 of 51 scripts carry a `sys.path` hack. Production code is
living in the spike directory and the only thing marking the boundary is that nobody has written down
where it is.

## Decision

### Tests

**Stdlib `unittest`, offline, free, run by `python scripts/run_tests.py`.**

- **No third-party dependencies, including in the tests.** **[SUPERSEDED 2026-09-22 by [ADR-0017](0017-the-inference-layer-uses-the-vendor-sdk.md)]** - this clause was applied to the inference layer, which it had never been weighed for, and cost retries, error observability and a cache-key bug there. The entire import graph is stdlib, which is why
  every script written for this project still runs. Adding pytest would make the test suite the only part
  of the system that needs an install and the first thing to break on a new machine. `subTest` covers the
  parametrization pytest is usually reached for.
- **Tests replay the raw store rather than using fixtures.**
  [ADR-0006](0006-the-observation-log-is-the-source-of-truth.md) makes every downstream stage a pure
  function of immutable bytes, so `data/step1/pages/` is a free regression corpus. Replay has already
  caught four defects at zero request cost.
- **Every published figure is recomputed from the artifact that produced it.**
  `tests/test_artifacts.py` derives the gate metric from `classification.csv` and asserts the exact
  numbers the evidence reports and `docs/design/history.md` quote. **These assertions are supposed to fail when a
  measurement changes** — the failure is the reminder to write a new dated report and update the prose,
  which is the only mechanism that has ever been proposed for the re-quoting failure above.
- **A test corresponds to a defect or to an invariant a published number depends on.** Coverage is not the
  target. Where a test exists because something broke, the file says which thing.
- **A skip is treated as a disabled test.** The first version of the adapter replay globbed
  `sj_stjohns_2*.html` against files named `sj_stjohns_01012026_*.html`, matched nothing, and reported
  `OK (skipped=5)`. `TestGoldenCorpus` now asserts that the expected page families exist, and the runner
  prints every skip.

### The package boundary

**`permits/` is the library; `scripts/` is spikes, probes and runners. A module in `scripts/` that another
script imports is in the wrong place.**

This is violated today by four modules, and the violation is **ratcheted rather than fixed in one go**:
`tests/test_structure.py` carries the current violation set as an explicit allowlist and fails if a *new*
one appears. Entries may be removed, never added. A big-bang move of `measure_fetch.py` would touch 23
call sites at once with no tests underneath most of them; the ratchet stops the problem growing while
`docs/design/refactoring.md` schedules the moves one at a time.

## Consequences

- **119 tests, ~2 seconds, zero network, zero cost.** Cheap enough to run on every change, which is the
  only property that makes a suite get run at all.
- **The suite is a regression set, not a golden set, and the difference is load-bearing.** It asserts that
  behaviour has not changed; it says nothing about whether the behaviour is correct.
  [ADR-0014](0014-the-golden-set-precedes-the-pipeline.md) still needs 15–25 hours of blind labelling and
  this does not substitute for it. The temptation to let the free thing stand in for the expensive one is
  exactly how a project stops measuring accuracy.
- **Writing the tests found three defects immediately** — a bad glob that disabled five tests, an
  empty-DOM fingerprint that made five unrelated open-data APIs look like one shared template, and a
  header-mutation test that was passing the unmodified page in. Two of those were defects in the tests,
  which is the ordinary case and is why an assertion that has never been seen to fail is not yet a test.
- **The published-number tests couple the docs to the data on purpose.** Editing `classification.csv`
  without updating the evidence report now breaks the build, and so does the reverse. That is friction,
  and it is the friction the evidence directory exists to create.
- **The ratchet permits the mess to persist.** It is explicitly a holding action: `measure_fetch.py` stays
  misplaced and misnamed until scheduled work moves it. What the ratchet buys is that the count cannot
  quietly go from 4 to 9.
- **Tests that shell out to `check_docs.py` and `check_identity.py` make `run_tests.py` the single command
  to remember.** The cost is that a test failure there reports a subprocess exit code and its stdout,
  which is a worse error message than a native assertion.

## Alternatives considered

- **pytest.** Better assertion output, fixtures, parametrization, and it is the default everywhere.
  Rejected on the dependency: this project's stdlib-only property is real and has already paid off, and
  the test suite is the wrong place to spend it. Revisit if the suite grows past the point where `subTest`
  is doing violence to the structure.
- **Fixtures instead of replay.** Reproducible, fast, no dependency on a data directory. Rejected because
  a fixture is a page someone *believed* the portal returned, and the failures here are all cases where
  the real page differed from that belief. A hand-written St. Johns fixture would have carried a padded
  date.
- **No published-number tests; rely on the evidence-report convention.** The status quo, and it is what
  `docs/evidence/README.md` was written to enforce. Rejected because the convention is exactly what failed
  in the 112-to-180 incident. A convention is a reminder and a test is a gate.
- **Move `measure_fetch.py` into `permits/` now.** The honest fix. Rejected as sequencing, not as
  direction: 23 call sites with nearly no tests under them is how a refactor becomes the reason the
  project stalled. It is the first scheduled item in `docs/design/refactoring.md` and moves once the
  capture layer has tests of its own.
- **Enforce the boundary with an import linter.** Better than an allowlist and would need a dependency.
  The ratchet is the stdlib version of the same idea.

## Revisit when

The allowlist in `tests/test_structure.py` reaches zero, at which point the ratchet becomes a plain
assertion and this ADR's holding-action framing should be retired. Revisit the pytest decision if the
suite exceeds roughly 300 tests. Revisit the replay-over-fixtures decision if the raw store ever has to be
excluded from a machine the tests run on, since the suite would then be mostly skips —
[ADR-0015](0015-the-raw-store-is-permanently-private.md) makes that a live possibility for any
collaborator.

## References

- `docs/design/history.md` §9 (obligations), §5 (the drift alarm)
- [ADR-0006](0006-the-observation-log-is-the-source-of-truth.md) — replay is why the corpus is a test set
- [ADR-0014](0014-the-golden-set-precedes-the-pipeline.md) — the golden set this does not replace
- [`docs/design/testing.md`](../design/testing.md) — what each file covers
- [`docs/design/refactoring.md`](../design/refactoring.md) — the scheduled moves
- [`docs/evidence/README.md`](../evidence/README.md) — the 112-to-180 re-quoting failure
- `scripts/run_tests.py`, `tests/`
