# Refactoring schedule

A living document. Each item is scheduled against a **trigger**, not a date — a date with no artifact
attached gets renegotiated the week it arrives, which is the reasoning behind
[ADR-0009](../adr/0009-adapters-first-generic-extraction-second.md) and its written trigger, and it
applies here too.

## Where the mess is

Measured 2026-09-22, not estimated:

| | |
|---|---|
| Modules in `permits/` | 14 · 3,670 lines |
| Maintained tools in `scripts/` | 6 · 2,344 lines |
| Lab notebook in `spikes/` | 47 · 7,013 lines |
| Spikes carrying a `sys.path.insert` hack | 39 |
| Spikes importing a **sibling spike** as a library | 3 modules, 6 import sites |
| Tools importing anything but `permits/` | **0**, enforced |
| Third-party dependencies | 4 runtime, 2 dev, locked |

Two structural problems dominated this document until 2026-09-22 and both are now closed, so what follows
is shorter than it used to be.

The counter-pressure has not changed: the project is small, solo, and earns nothing from tidiness by
itself. The rule is **refactor when a change is already touching the code, or when the mess is actively
blocking a measurement.** Not on a schedule, and not for its own sake. The exception was the reviewer-ready
pass, which is tidiness for its own sake, done deliberately and once.

## The ratchet

`tests/test_structure.py` holds the current violation set as an explicit allowlist and fails if a **new**
one appears, a known one **grows**, or an entry goes **dead**. Entries may be deleted and never added.

That third condition is what makes it a schedule rather than a wall: finishing a move is the only way to
get an entry out, and leaving a finished move unrecorded breaks the build. Each item below, when done,
deletes one line from `ALLOWED`.

## Done

### ~~The capture layer moves to `permits/capture.py`~~ — **done 2026-09-22**

`scripts/measure_fetch.py` was the capture layer — robots, politeness, verdicts, the manifest, the schema
migration, capture-time fingerprinting — living in the spike directory under the name of the measurement
it was first written for, imported by 23 siblings through `sys.path` insertion. It was the most
load-bearing module in the project and the most misplaced.

It is now `permits/capture.py`. The 23 call sites import it from the package; nine of them turned out to
have no `sys.path` bootstrap of their own and were reaching `permits/` *transitively through the module
they were importing*, which is a fair illustration of what the old arrangement cost in ways nobody had
counted.

**The honest caveat, now paid off.** This document named the tests as a precondition and the move happened
without them, because the `scripts/` ↔ `spikes/` split needed it first — so the sequencing argument in
[ADR-0016](../adr/0016-tests-are-replay-over-the-raw-store.md) was settled in the wrong order. The tests
landed the same day; the entry below says what they found, which is the argument for the sequencing that
was not followed.

### ~~The capture layer gets its tests~~ — **done 2026-09-22**

All six properties this document named, in `tests/test_capture.py`: robots disallow produces a `rejected`
row and no file; a transport error produces a row and no file; the budget ceiling raises rather than
continuing; the per-host pause is honoured and is per-host; a page is never written without its row; the
header migration is additive and refuses to drop a column. Plus the verdict rules, each of which is a
discriminator that once fired on something every page has.

Written against a **loopback `ThreadingHTTPServer`, not a fake opener** — which is a change from what this
document scheduled. A fake opener would have been faster to write and would have tested the fake: the
whole risk in this module is what real `urllib` does on a real error path. The server costs a millisecond,
makes no network call, and exercises the real opener, the real `HTTPError` branch and a real `robots.txt`
round trip.

**It found a live defect on the first run.** `fetch()` wrote the page and *then* the row, and `_migrate()`
raises between the two, so a manifest carrying an unknown column left an unrecorded page on disk — the
Spike C failure, reintroduced inside the module written to prevent it, live for as long as the migration
path had existed. The page is now staged under a temporary name and promoted only after its row is
committed.

**Residual:** the ASP.NET postback path — viewstate round-tripping, the `Referer`/`Origin` headers Accela
demands, the session cookie across a paged grid — is still exercised only by replay. Noted in
[`testing.md`](testing.md), not scheduled.

### ~~`scripts/` splits into tools and notebook~~ — **done 2026-09-22**

Fifty-three files in one directory, six of them maintained and forty-seven of them a lab notebook, with no
way for a reader to tell which was which. `scripts/` now holds only what the README tells you to run;
[`spikes/`](../../spikes/README.md) holds the rest, with a README mapping each family to the evidence
report it produced. Two new tests fix the direction of dependency: a tool may not import a sibling tool,
and a tool may not import a spike.

### ~~A package manifest~~ — **done 2026-09-22**

Listed under *Not scheduled* here until [ADR-0017](../adr/0017-the-inference-layer-uses-the-vendor-sdk.md)
reversed it. `pyproject.toml` and `uv.lock` are committed, and `tests/test_structure.py` asserts that every
import in `permits/` is stdlib or declared, so `uv sync` is sufficient to run the suite.

## Scheduled

### 1. `permits/bps.py` — the frame loader

*Trigger: the third script that needs to read `bps_frame.csv`.*

`spikes/spike_b_sample.py` holds frame-loading and office lookup that `spikes/step1_oracle_add.py` imports.
`scripts/check_identity.py` has its own copy. That is two, so this is nearly due. Should carry: load, index
by `(state_fips, bps_id)`, index by name-within-state, and the tier/unit accessors — the operations
[ADR-0007](../adr/0007-office-identity-is-the-bps-office-id.md) makes the only legitimate way to assign an
office identity.

### 2. `norm_date` gets a rewrite, not another format

*Trigger: the next date format that does not parse.*

The function is now three fallback strategies deep — split on whitespace, fixed-width slice, regex — and
each layer was added because the previous one failed on a real source. It works, and
`tests/test_normalize.py` pins the behaviour, so a rewrite is safe for the first time. The rewrite should
be: try each format against the date-part token, in order, with no width slicing at all. The width slice
is the part that caused the 100%-null bug and it no longer earns its place.

### 3. The Spike A probes get deleted

*Trigger: when the Spike A corpus is no longer re-runnable, or the offices are re-probed properly.*

Fourteen `spike_a_*` scripts. `spike_a_query_probe.py` is imported by two tier-2 scripts purely for its
`req`/`hidden` helpers. None of them will run again — they target a 28-office sample since superseded by
demonstrated verdicts. Moving them to `spikes/` in the reviewer-ready pass was a holding action, not this
item: it stopped them being mistaken for maintained code, and it did not delete them. **Not** a rewrite —
they produced dated evidence reports and their value is historical.

### 4. Adapter protocol becomes explicit

*Trigger: the fourth adapter — which [ADR-0009](../adr/0009-adapters-first-generic-extraction-second.md)
makes the last one before the conformance test, so this is the last chance to do it cheaply.*

The three adapters already implement the same informal protocol — `build`, `parse_index`, `pull_window`,
`vocabulary_for`, `page_is_complete`, `headers`, `ADAPTER_VERSION` — discovered by reading them rather
than declared anywhere. `tests/test_adapters.py` asserts part of it. A synthesized extractor at step 4 has
to satisfy this protocol, so it needs to be written down before something is asked to conform to it.

Deliberately **not** an abstract base class. The three adapters differ in pagination shape
(offset/limit vs. postback vs. recursive date bisection) and forcing a common `pull` would push the
difference into configuration. A documented protocol plus the conformance tests is the right weight.

### 5. Data-artifact hygiene

*Trigger: opportunistic.*

- ~~`data/spike_a/classification.csv.bak`~~ — **done 2026-09-21.** It held the same 28 offices with
  the same buckets and **all 28 office ids wrong**: the state before the identity correction, undated
  and unmarked as superseded. `check_identity.py` had not caught it either, because it scans `.csv`
  and `.json` and that file ends in `.bak`. Deleted, and `tests/test_artifacts.py` now fails on any
  `.bak`/`.old`/`.orig` sibling in `data/` — a suffix is not a quarantine.
- Manifest `jurisdiction` labels are inconsistent — the same tenancy appears as both `SLCREF` and
  `accela:SLCREF`, which made five fingerprints look shared across jurisdictions when they were one
  jurisdiction under two names.
- Manifest jurisdiction is a free-text label, not an office identity. It should be
  `(state_fips, bps_id)`; that it is not is why the fingerprint cross-tab cannot be joined to the frame.

## Not scheduled, and why

- **Splitting `permits/emit.py` (529 lines).** It is long because the comments carry the reasoning for
  every rule, and the rules are the product. Splitting it would scatter that.
- **Splitting `scripts/conformance.py` (1,494 lines).** The largest single file in the repo, and the one a
  reviewer is most likely to flag. It runs schema validation, prompt construction, the sandbox, scoring, and
  five CLI modes over one shared notion of a draw. The pieces that were genuinely reusable —
  the Wilson interval, the failure taxonomy, the percentile — already left for `permits/stats.py` when a
  second consumer appeared, which is the trigger this document trusts. Splitting the rest today would
  produce four files that are only ever used together.
- **Type hints.** Would help, and would be a large edit across every file for a benefit the tests
  already partly provide. Revisit if the codebase doubles.
