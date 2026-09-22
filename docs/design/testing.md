# Testing

**How it runs**

```
python scripts/run_tests.py           # everything: 195 tests, ~2s, no network
python scripts/run_tests.py emit      # one file
python scripts/run_tests.py -q        # quiet
```

Stdlib `unittest`. No install, no dependencies, no network, no model calls — the whole suite is free to
run, which is the only property that makes a suite actually get run. The decision and its alternatives are
[ADR-0016](../adr/0016-tests-are-replay-over-the-raw-store.md).

`check_docs.py` and `check_identity.py` are invoked as tests, so `run_tests.py` is the single command.

## What is being defended against

Not crashes. Every defect that has cost this project real time was silent — the code ran, produced
output, and the output was wrong:

| Defect | How it presented |
|---|---|
| `norm_date` fixed-width slice | 100% of one county's dates null; adapter looked healthy |
| Austin sub-permits | 726% unit overcount against BPS |
| Mecklenburg drops `worktype` | 123,262 historical values, then blank, no signal |
| `portals.csv` office ids | all 28 wrong; 7 resolved to a real *different* office |
| The 112 → 180 re-quote | a correct figure became wrong by being repeated later |
| Empty-DOM fingerprints | 5 unrelated APIs appeared to share one template |

A test suite aimed at exceptions catches none of these. So the suite is shaped around three things that do:
**replay**, **recomputation of published numbers**, and **structural invariants**.

## The files

| File | Covers | Descended from |
|---|---|---|
| `test_normalize.py` | `norm_date`, `norm_int`, `norm_text` | the St. Johns 100%-null regression |
| `test_emit.py` | the emit contract: identity, units, milestones, the drift alarm | Austin 726%, Nashville's absent unit field, Mecklenburg |
| `test_fingerprint.py` | skeleton stability, version guard, absence guard, Spike C's negative result | the empty-DOM collision |
| `test_adapters.py` | replay over stored pages; column-order assertions; truncation detection | the Clark vocabulary bug, the truncated page |
| `test_artifacts.py` | published figures, classification shape, D1's capture invariant, record store | the 112 → 180 re-quote |
| `test_structure.py` | the `permits/`/`scripts/` boundary ratchet, declared-dependency rule, adapters stay thin | 23 scripts importing the capture layer |

## Three ideas worth knowing before editing these

**Replay, not fixtures.** [ADR-0006](../adr/0006-the-observation-log-is-the-source-of-truth.md) makes
every downstream stage a pure function of immutable bytes, so `data/step1/pages/` is a free regression
corpus. A hand-written fixture is a page someone *believed* the portal returned — and every failure above
is a case where the real page differed from that belief. A hand-written St. Johns fixture would have
carried a zero-padded date and the bug would have survived.

**Published-number tests are supposed to fail.** `test_artifacts.py` recomputes the gate metric from
`classification.csv` and asserts the exact figures the evidence reports and `DESIGN.md` quote. When a
measurement changes, these break. That is the mechanism, not a defect: the break is the reminder to write
a new dated evidence report and update the prose *together*. Editing the artifact without the docs now
fails the build, and so does the reverse.

**A skip is a disabled test.** The first version of the adapter replay globbed `sj_stjohns_2*.html` at
files named `sj_stjohns_01012026_*.html`. It matched nothing and reported `OK (skipped=5)`.
`TestGoldenCorpus` now asserts the expected page families exist with minimum counts, and the runner prints
every skip with its reason. If a capture is renamed, update `GOLDEN` — do not let the suite go quiet.

## What this suite is not

**It is not a golden set.** It asserts that behaviour has not *changed*. It says nothing about whether the
behaviour is *correct*. [ADR-0014](../adr/0014-the-golden-set-precedes-the-pipeline.md) still requires
500–1,000 records labelled blind from the rendered page, 15–25 hours, none of it done. The regression set
is free and the golden set is expensive, and letting the cheap one stand in for the expensive one is
exactly how a project stops measuring accuracy.

**It does not test the network path.** Nothing here exercises `fetch`, robots handling, politeness or the
retry behaviour, because doing so means either making requests or mocking `urllib` — and a mock of
`urllib` tests the mock. This is the largest untested surface in the project and it is the one that writes
the manifest. Closing it is the first item in
[`refactoring.md`](refactoring.md): the capture layer gets tests as part of moving into `permits/`.

**It does not test the reconciliation arithmetic end to end.** `test_artifacts.py` checks the properties
of emitted records and the gate metric, not the BPS fold that produces the 1.0% / 4.4% / 4.1% figures.

## Adding a test

Two questions, and if both answers are no, do not write it:

1. Did this break, or nearly break, and produce a wrong answer rather than an error?
2. Does a published number depend on it?

Say which in the test's docstring. A file full of assertions with no provenance becomes a file nobody
dares delete from and nobody trusts.
