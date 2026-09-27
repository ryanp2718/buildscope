# BuildScope

[![CI](https://github.com/ryanp2718/buildscope/actions/workflows/ci.yml/badge.svg)](https://github.com/ryanp2718/buildscope/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Municipal building-permit data, and a pass@1 measurement of whether a language model can write the
extractors.**

Every city and county in the United States publishes building permits, and almost none of them publish
them the same way. Some expose an open-data JSON API. Some run a hosted permit portal. Some render an
ASP.NET results grid that only yields records to a correctly-formed postback. Covering a hundred
jurisdictions the ordinary way costs a hundred hand-written extractors, and then costs them again every
time a vendor ships a restyle.

The obvious idea is to have a model write each extractor. Code generation has a metric family for this:
pass@k (Chen et al., 2021) — draw k completions, ask whether at least one passes. This project reports the
quantity underneath it, pass@1: one completion per draw, scored against a reference, the draw repeated
independently to measure a rate instead of a single outcome. A scraper fails in ways that rate doesn't cover
on its own. Does the generated code agree with a hand-written parser? Does it still work when the page
changes? Does it fail loudly, or does it return zero rows and let a pipeline record a quiet month in a city
that issued four hundred permits?

This repository runs pass@1 against real municipal permit pages: draws per prompt, each scored against a
hand-written extractor, re-run under deliberate page mutation, cost-ledgered per call. The pipeline
underneath it is what the measurement runs against.

The pre-LLM literature on this problem called an extractor a wrapper and studied exactly the drift question
above as wrapper maintenance (Kushmerick, 1997; Lerman, Minton & Knoblock, 2003). This project keeps
"extractor" as the code-level name and treats wrapper induction as the closest prior art.

## What has been measured

| | | where |
|---|---|---|
| **29,668 records** across **7 jurisdictions**, three source families | reconciled against the Census Building Permits Survey to within **3.0–4.1%** over 12 jurisdiction-months | [report](docs/evidence/2026-09-20-step1-stjohns-reconciliation.md) |
| **26 model-generated extractors**, pass@1, never hand-edited | **agreement 1.0000** on 4,188 records over 71 pages — and that benchmark turned out to be saturated | [report](docs/evidence/2026-09-21-extractor-conformance.md) |
| **8 record-preserving page mutations**, no labels required | 20 extractors that scored *identically perfect* split under drift; **5 of 20** survived a CSS class rename | [report](docs/evidence/2026-09-21-drift-robustness.md) |
| **55 draws, pass@1**, across 3 models × 2 layouts | success rates from 5% to 100%; **86% of failures were silent** — zero rows, no exception | [report](docs/evidence/2026-09-21-extractor-conformance.md) |
| **67 priced calls, $4.3411**, every one ledgered before it billed | **cost per working extractor inverts the per-token price list**: $0.286/success on the frontier model against $0.686 on the cheapest | [report](docs/evidence/2026-09-22-cost-per-success.md) |

The last row generalises furthest. A cheap model that succeeds once in twenty attempts bills for all twenty,
so per-token price ranks models correctly only when they all succeed. Page difficulty decides which regime
you're in, and the price list can't tell you which one that is.

## What this does not claim

This section is here because the numbers above are easy to overread, and the project is worth less if
they are.

- **Agreement is not accuracy.** The 1.0000 figure is agreement with a hand-written adapter, chosen as the
  reference precisely because its mistakes are uncorrelated with a model's. Both implementations can
  misread the same column heading the same way. There is no record-level ground truth anywhere in this
  project yet; the golden set is specified in
  [ADR-0014](docs/adr/0014-the-golden-set-precedes-the-pipeline.md) and unbuilt.
- **n is small where it matters most.** The frontier-model cell in the cost comparison is three draws,
  with a 95% interval of [0.44, 1.00]. The *direction* of the cost inversion survives that. The 2.4×
  magnitude does not.
- **Two platforms is not a difficulty axis.** "Page difficulty decides which model is cheaper" is the
  natural reading of two points. It is not a measurement.
- **Nothing is measured on small jurisdictions**, which are the population this project claims to serve.
  Everything here ran against large and mid-size offices with machine-readable portals.
- **Amortisation across templates is dead**, not pending. A spike ran specifically to test whether one
  extractor could cover many jurisdictions sharing a vendor template; it could not. The economics
  claimed in the original design did not survive it.

Every evidence report carries its own "What this does not establish" section, and `check_docs.py` fails
the build if one is missing.

## Repository map

```
permits/      the library — capture, strip, identity, vocabulary, adapters,
              emit, inference, model registry, telemetry, statistics.
              16 modules, 4,951 lines.
scripts/      six maintained tools.  conformance.py is the experiment harness;
              model_stats.py rolls every measurement into one tidy table;
              three check_*.py validate the docs, the identities and the notes.
spikes/       the lab notebook.  49 scripts, unmaintained, kept because the
              published numbers came out of them.  See spikes/README.md.
tests/        373 tests, replay over stored pages.  No network, no spend.
docs/         adr/ why a rule exists · design/ how it works · evidence/ what
              was measured, dated and reproducible.
DESIGN.md     the narrative: thesis, open questions, sequencing, risk register.
```

The direction of dependency is enforced rather than documented: `permits/` imports nothing above it,
a tool may not import another tool or a spike, and the remaining sibling imports inside `spikes/` sit on
an explicit allowlist in `tests/test_structure.py` that may shrink and may not grow.

## Running it

```bash
uv sync --group dev
uv run pytest
```

No API key needed and no network calls — the suite replays over stored pages. Tests that need the private
raw store skip themselves and say so.

To re-derive the published model statistics from the stored artifacts:

```bash
uv run python scripts/model_stats.py
```

Running the inference experiments for real needs an Anthropic API key in `~/.anthropic_key`, and — for the
open-weight models — an OpenRouter key in `~/.openrouter_key`. Any model id containing a slash is routed to
OpenRouter through the OpenAI-compatible endpoint; everything else goes to Anthropic. `uv run python
scripts/conformance.py --matrix` prints the current price ladder, which spans about 90× from the cheapest
open-weight model to Opus 5.

That spread is the point rather than a saving. The project's central claim is that **cost per success, not
cost per token, is what ranks models**, and until 2026-09-23 it was measured only across three Claude tiers
— a 5× band, inside which the claim holds: Haiku needs a 20% success rate to beat Opus on cost per success
and measures 5%. Whether it survives an 88× band, where a model needs roughly one success in eighty-eight,
is a different question and an open one.

Every call is ledgered before it bills and any call whose worst-case cost would break the configured ceiling
is refused rather than attempted. Responses are cached under a hash of the request, so a 55-call experiment
replays end to end for $0.00.

## The captured pages are not in this repository

`data/` is deliberately absent. It holds the raw store — captured HTML, the inference cache, the cost
ledger — and it stays on the machine that fetched it, for the reasons in
[ADR-0015](docs/adr/0015-the-raw-store-is-permanently-private.md). Everything derived from it is published
in `docs/evidence/`, with the producing script and input row counts named in each report's front matter.

Capture itself is rate-limited, robots-aware, and identifies itself honestly: `permits/capture.py` refuses
to issue a request at all if no crawler contact is configured, and writes the page and its manifest row in
a single operation so a file cannot exist on disk without a record of how it was got.

## Where to read next

- **[`DESIGN.md`](DESIGN.md)** — the full narrative, front to back. Start here if you want the reasoning.
- **[`docs/evidence/`](docs/evidence/)** — every number, dated, with the command that reproduces it.
- **[`docs/adr/`](docs/adr/)** — 17 decision records. [ADR-0017](docs/adr/0017-the-inference-layer-uses-the-vendor-sdk.md)
  is the most recent and the most self-critical: it reverses an earlier rule that had this project
  hand-rolling its own API client.

## Provenance

This landed as a single commit because it was built in one exploratory session rather than incrementally.
Reconstructing that history afterwards would have been fiction. `docs/evidence/` is dated and append-only,
so the order things were actually learned in is recoverable there.

## License

MIT. See [LICENSE](LICENSE).
