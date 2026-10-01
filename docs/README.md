# Documentation map

Three kinds of document, three different lifecycles. The split exists so that a reader can tell, without
reading the body, whether a document is allowed to be out of date.

| Directory | Answers | Lifecycle | If it is wrong |
|---|---|---|---|
| [`adr/`](adr/) | **Why** a rule exists | Immutable once accepted | Write a new ADR superseding it; never edit |
| [`design/`](design/) | **How** the system works today | Living; edited in place | Fix it in place |
| [`evidence/`](evidence/) | **What we measured**, and when | Append-only, dated | Re-run and add a new dated report |

One file in `design/` is the exception to its lifecycle: [`design/history.md`](design/history.md) is
the original planning narrative (thesis, open questions, sequencing, risk register), frozen on
2026-10-01 and kept as a record of the order things were decided in. Start from the repository
[README](../README.md) instead.

## The three-way split, and why it is not the usual two

The conventional split is ADRs for decisions and design docs for mechanism. That is sound and this
project keeps it. What that split does not provide, and this project cannot do without, is a home for
**measured numbers**.

Nearly every load-bearing claim here is empirical - `16.63% of national authorized units`,
`0.90% of offices`, `443 publisher names adjudicated`, `$9.36 to reach the decision gate`. Each is the
output of a specific script run against specific data on a specific day. Numbers like these rot silently:
they get quoted in a summary, the underlying data is refreshed, and nothing in the document says the
figure is now stale. Putting them in a design doc makes the design doc undateable. Putting them in an ADR
makes the ADR mutable. They need their own category with its own rule.

**The rule for `evidence/`: every number is reproducible or it does not go in.** A report states the date
it was produced, the script that produced it, the input artifact and its row count, and the output
artifact. A claim with no named producer is not evidence, it is a recollection.

## Conventions

- **Filenames are kebab-case.** No `SHOUTING_SNAKE.md`; the extra emphasis conveys nothing once every
  file has it.
- **Evidence reports are date-prefixed**, `YYYY-MM-DD-slug.md`, so the directory sorts chronologically
  and a stale report is visibly stale in `ls`.
- **ADRs are zero-padded four digits**, never renumbered, never reused.
- **Nothing lives at the repository root but the README, the license and project configuration.** Working notes, audits, and drafts go
  in the scratchpad or in `evidence/`; they do not accumulate at the top level.
- **Cross-references are relative links**, so they survive the directory being moved or browsed on disk.

## Checking

```
python scripts/run_tests.py       # everything below, plus the code. ~2s, offline, free.
```

Three checks run, and they are separated because they fail for different reasons:

- **`scripts/check_docs.py`** - the ADR index matches the files on disk, statuses are drawn from the
  permitted set, superseding references resolve, every relative link inside `docs/` exists, and every
  evidence report names a producer and a non-empty "What this does not establish". Hand-maintained
  indexes drift; this makes the drift fail loudly instead of quietly.
- **`scripts/check_identity.py`** - every `(state_fips, bps_id)` in every data artifact resolves in the
  frame **and agrees with the office name recorded beside it**. The second half is the one that matters:
  when `portals.csv` was audited, 21 of its 28 wrong ids failed an existence check loudly and **7 passed
  it**, because they named a real office somewhere else in the same state. Known-wrong keys in dated
  captures are registered in `data/corrections.csv` and reported rather than rewritten.
- **`tests/test_artifacts.py`** - **every headline figure is recomputed from the artifact that produced
  it.** This is the structural answer to the failure this directory exists to prevent: a figure that was
  correct when written becoming wrong when re-quoted. Editing `classification.csv` without updating the
  evidence report now breaks the build, and so does the reverse. These assertions are *meant* to fail
  when a measurement changes - the failure is the prompt to write a new dated report.

See [`design/testing.md`](design/testing.md) for what is covered and what is deliberately not.
