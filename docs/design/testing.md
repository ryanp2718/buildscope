# Testing

**How it runs**

```
python scripts/run_tests.py           # everything: 423 tests, ~18s, no network
python scripts/run_tests.py emit      # one file
python scripts/run_tests.py -q        # quiet
```

Stdlib `unittest`. No install, no dependencies, no network, no model calls — the whole suite is free to
run, which is the only property that makes a suite actually get run. The decision and its alternatives are
[ADR-0016](../adr/0016-tests-are-replay-over-the-raw-store.md).

`check_docs.py` and `check_identity.py` are invoked as tests, so `run_tests.py` is the single command.

CI also runs `ruff check .` and `mypy`. mypy is strict and covers only the files listed under
`[tool.mypy]` in `pyproject.toml`; a file joins that list once it passes, starting from the inference
layer.

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
| `test_capture.py` | robots, politeness, the budget ceiling, schema migration, the verdict rules, and D1's page-and-row invariant | the unrecorded page it found on its first run |
| `test_providers.py` | provider routing, the OpenAI/Anthropic usage translation, which figure gets billed, the golden cache keys, protocol v1 frozen and protocol v2's request and ledger fields | the `stream` cache-key bug, and four ways a second wire format can produce a wrong number |
| `test_models.py` | the model registry: every id ever called resolves, reasoning controls fit their provider, tiers, every model that reasons is asked to at its lab's default level, and the protocol v2 efforts, caps, sampling, host filters and excluded endpoints against the catalogue and endpoint snapshots | seven hand-kept model tables that disagreed, so two reasoning models ran as non-reasoning |
| `test_transport.py` | streaming on both providers, the read timeout and wall-clock limit, the fatal/transient error split with one retry per draw, time to first token, and infra errors reported beside the pass rate | a 900 s per-read timeout that let one call run 65,161 s, and a timeout, a revoked key and a budget refusal all stopping the cell as one outcome |
| `test_fileio.py` | atomic writes of the cache and the roll-ups, `variance.json` merged under a lock, one run per cell, whole ledger lines under concurrent appends; the races are run between real processes | a truncated cache entry that failed on every later hit, a corrupt `variance.json` read as empty, and two processes that both bought draw 1 of one cell |
| `test_cells.py` | the variance records: `--cells` parsing, a per-cell config that cannot leak, and a byte-for-byte round trip of every stored draw | `run_cells` mutating the shared argument namespace, and `.get()` turning a misspelled field into a silent zero |

## Four ideas worth knowing before editing these

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

**A fake is not the only alternative to a mock.** Until 2026-09-22 this document said the capture layer
could not be tested without either making requests or mocking `urllib`, "and a mock of `urllib` tests the
mock". The objection was right and the conclusion was wrong. `tests/test_capture.py` starts a
`ThreadingHTTPServer` on 127.0.0.1: it costs a millisecond, makes no network call, and exercises the real
opener, the real cookie jar, the real `HTTPError` branch and a real `robots.txt` round trip. Nothing in it
is stubbed, so nothing in it can pass because the stub agreed with the code.

That distinction was not academic. The first run failed on the one property the module's own docstring
claims — that a page may not exist on disk without a manifest row — because `fetch()` wrote the page and
*then* the row, and `_migrate()` raises between the two. A refused schema migration left an unrecorded
page behind: the Spike C failure this module was written to prevent, reintroduced inside it. It had been
live for as long as the migration path had existed, and no amount of reading the file had caught it.

## What this suite is not

**It is not a golden set.** It asserts that behaviour has not *changed*. It says nothing about whether the
behaviour is *correct*. [ADR-0014](../adr/0014-the-golden-set-precedes-the-pipeline.md) still requires
500–1,000 records labelled blind from the rendered page, 15–25 hours, none of it done. The regression set
is free and the golden set is expensive, and letting the cheap one stand in for the expensive one is
exactly how a project stops measuring accuracy.

**It does not test the reconciliation arithmetic end to end.** `test_artifacts.py` checks the properties
of emitted records and the gate metric, not the BPS fold that produces the 1.0% / 4.4% / 4.1% figures.

**It does not test either vendor's transport.** `test_providers.py` and
`test_transport.py` run against fake streams, which is the opposite of the choice
`test_capture.py` makes and is deliberate. There the risk *was* the transport -
what real `urllib` does on a real error path - so a real server was worth
starting. Here the transport is the vendor's, tested by the vendor, and what
this project owns is the translation between two wire formats and the decision
about which number to bill. A fake response exercises exactly that and nothing
else. What is consequently untested is whether OpenRouter's live response
actually carries the fields `_usage_from_chat` reads; the first real call is
what establishes that, and it is cheap to make against a free model. The same
goes for the stream: that the last chunk carries usage and cost, and that
reasoning arrives as a `reasoning` delta, which is what time to first token
counts on a model that thinks.

**It does not test the postback path.** `test_capture.py` covers `fetch` over GET. The ASP.NET POST
sequence — `__VIEWSTATE` round-tripping, the `Referer`/`Origin` headers Accela demands, the cookie that
carries a session across a paged result grid — is exercised only by `test_adapters.py` replaying pages
that path already produced, which is not the same as exercising the path. A loopback server that answers
a postback the way Accela does is the obvious next step and has not been written.

## Adding a test

Two questions, and if both answers are no, do not write it:

1. Did this break, or nearly break, and produce a wrong answer rather than an error?
2. Does a published number depend on it?

Say which in the test's docstring. A file full of assertions with no provenance becomes a file nobody
dares delete from and nobody trusts.
