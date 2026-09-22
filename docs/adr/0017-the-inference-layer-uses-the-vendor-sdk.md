# ADR-0017: The inference layer uses the vendor SDK; dependencies are declared and locked

Status: Accepted

Date: 2026-09-22

Supersedes the dependency clause of [ADR-0016](0016-tests-are-replay-over-the-raw-store.md). The rest of
that ADR — replay over the raw store, pinned published numbers, the package-boundary ratchet — stands.

## Context

ADR-0016 decided "no third-party dependencies, including in the tests." Read closely, its argument is
about **pytest**: adding it would make the test suite the only part of the system needing an install.
The project-wide stdlib property was treated as already existing and simply not spent.

It was then applied to a case it had never been weighed for. When `permits/infer.py` was written the
next day, `tests/test_structure.py::test_no_third_party_imports` already existed, the vendor SDK was
therefore unusable, and the Messages API got spoken over `urllib`. **No ADR, design note or comment ever
records anyone weighing the SDK against a hand-rolled client.** The decision was inherited, not made.

What it cost, all of it found by inspection on 2026-09-22 rather than by anything failing loudly:

- **No retries of any kind.** One `urlopen` and an `HTTPError` handler that re-raised. No backoff, no
  429 handling, no 529 handling. The 55-draw variance experiment ran unattended for hours against a
  client that a single rate-limit response would have ended.
- **Failed calls never reached the ledger.** The raise happened three lines before `ledger.write`, so
  the error rate was structurally unobservable and every rate computed from that ledger silently had
  "calls that succeeded" as its denominator.
- **A per-model capability table maintained by hand.** `ADAPTIVE_THINKING` exists because
  `thinking: {type: "adaptive"}` 400s on Haiku 4.5 and `budget_tokens` 400s on Opus 5. Discovered by a
  rejected request.
- **A streaming parser whose transport flag leaked into the cache key**, orphaning $0.60 of paid
  responses silently — a bug class the vendor client does not have because it does not construct the
  request body twice.

The second force is unrelated to any of that: this repository is about to be published, and a reviewer
cloning it should be able to run it. Stdlib-only makes that true by having nothing to install, which is
the one thing the rule genuinely bought. A lockfile makes it true more strongly, because it also pins
what "stdlib" does not — the interpreter version, and the transitive graph.

## Decision

**The inference layer uses the official `anthropic` SDK. Dependencies are declared in `pyproject.toml`,
locked with `uv`, and asserted by test.**

- `uv` is the toolchain: `uv sync --group dev` is the one command to reproduce the environment, and
  `uv.lock` is committed.
- `tests/test_structure.py::test_imports_are_declared_dependencies` replaces the stdlib-only assertion.
  It walks the same import graph and fails on any import `pyproject.toml` does not declare. The property
  worth keeping was never "stdlib"; it was **"a fresh checkout plus one command runs everything"**, and
  an undeclared import breaks that where a declared one does not.
- `pytest` is the dev runner. `scripts/run_tests.py` still works and is still the single command to
  remember; ADR-0016's `subTest` workaround is no longer load-bearing.
- **Telemetry uses OpenTelemetry GenAI semantic conventions, and is off by default.** Spans carry
  `gen_ai.*` attributes plus the project dimensions (`permits.call_class`, `permits.draw`) that join a
  span to a ledger row. `permits/telemetry.py` selects an exporter from `PERMITS_TRACE`; with the
  variable unset the OTel API returns a no-op tracer and nothing is emitted.

## Consequences

- **Retries, backoff and streaming are the vendor's.** `MAX_RETRIES = 5` and a 900-second timeout are
  stated explicitly rather than inherited from the SDK default of 2.
- **Failed calls are ledger rows** carrying `ok: False`, `error_type` and `status_code`, billed at zero.
  Rows written before this ADR have no `ok` field and are read as successes, which they are. A `Refused`
  is still not a row: nothing was sent.
- **Every one of the 67 cached responses still resolves.** `build()` and `_key_for()` were left byte-for-byte
  unchanged and the swap was verified by rebuilding all 55 variance-draw keys against the cache before
  anything else was run. This was the binding constraint on how the change could be made, and it is why
  `body` is still constructed as a dict and splatted into the SDK call rather than passed as keyword
  arguments directly.
- **The hand-written SSE parser and its four tests are deleted.** Testing a vendor's parser is not this
  suite's job. What replaced them tests what the project still owns: that failures reach the ledger,
  that refusals do not, that truncation still surfaces, and that retries are configured.
- **`data/infer/ledger.jsonl` keeps its field names.** OTel conventions govern the spans; the ledger is
  the cost record of account and renaming its fields would have meant migrating 67 historical rows for
  no gain.
- **The repo now has an install step**, which is the cost. `uv sync --group dev` is it.
- **A hosted tracing backend is now one environment variable away**, which is a hazard worth naming:
  [ADR-0015](0015-the-raw-store-is-permanently-private.md) makes the raw store permanently private, and
  page content appears in prompts. Default-off, plus a vendor-neutral wire format, is what keeps that a
  deliberate act rather than a side effect of switching tracing on.

## Alternatives considered

- **Keep the hand-rolled client and add retries to it.** Roughly twenty lines, and it was seriously
  considered — it fixes the single worst defect without an install step. Rejected because it fixes only
  the defect that had already been noticed. The per-model capability table, the streaming parser and the
  double-construction of the request body all remain, and all of them are code this project has no
  reason to own.
- **Keep stdlib-only and accept the gaps**, on the grounds that the experiment already ran. Rejected:
  the experiment ran *successfully*, which is not the same thing, and the next one is a repair loop with
  many more calls.
- **Adopt LangChain / LangGraph for the agent layer.** Rejected for now on fit, not on principle: there
  is no agent here. Synthesis is three single-shot call sites — one request, one response, run the
  generated code — with no loop, no tool use and no multi-turn state. LangGraph would model a one-node
  graph. Revisit at the repair loop, which is genuinely agentic.
- **LangSmith or another hosted tracing backend as the default.** Rejected on ADR-0015: prompts carry raw
  page content, and a default that ships it off the machine is the wrong default for a project whose
  raw store is private. It remains one env var away for anyone who wants it, via OTLP.
- **Rename the ledger fields to `gen_ai.*`.** Rejected as a migration with no benefit; conventions belong
  on the telemetry, not on the cost record.

## Revisit when

The repair loop is built, at which point "there is no agent here" stops being true and the agent-framework
question is live again. Revisit the default-off telemetry decision if anyone other than the author starts
running experiments, since an unobserved default is worse than a configured one once there is more than
one operator.

## References

- [ADR-0016](0016-tests-are-replay-over-the-raw-store.md) — the dependency clause this supersedes
- [ADR-0015](0015-the-raw-store-is-permanently-private.md) — why telemetry is default-off
- `permits/infer.py`, `permits/telemetry.py`, `pyproject.toml`, `uv.lock`
- `tests/test_infer.py::TestFailedCallsReachTheLedger`, `tests/test_structure.py::test_imports_are_declared_dependencies`
