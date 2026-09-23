# Cost per working extractor: the price list is the wrong ranking

Date:      2026-09-22
Produced:  `python scripts/model_stats.py` (no model calls; cost $0.00)
Inputs:    `data/infer/variance.json` (55 synthesis draws, 2026-09-21),
           `data/infer/drift.json` (robustness matrix, 2026-09-21),
           `data/infer/ledger.jsonl` (67 priced calls)
Outputs:   `data/infer/model_stats.csv` (1,090 observations, long format),
           `data/infer/model_stats.json` (5 cells with Wilson intervals)
Status:    Current. Pinned by `tests/test_model_stats.py`.

## What changed

Nothing was measured again. The 55 draws and the drift matrix are the 2026-09-21 run, unaltered. What
changed is that the per-model figures are now derived by one script from one long-format table instead
of being computed inside `scripts/conformance.py`, printed once, and pasted into prose by hand.

Doing that made one quantity computable that had never been computed: **dollars per extractor that
actually works**, rather than dollars per call. Everything below falls out of that one division.

## Result

| target | model | draws | perfect | success | 95% CI | cell spend | **$ / success** | p50 | p95 |
|---|---|---:|---:|---:|---|---:|---:|---:|---:|
| Clark (Accela) | Haiku 4.5 | 20 | 1 | 5% | [0.01, 0.24] | $0.6863 | **$0.6863** | 22.3s | 40.5s |
| Clark (Accela) | Sonnet 5 | 12 | 2 | 17% | [0.05, 0.45] | $0.6432 | **$0.3216** | 22.9s | 44.6s |
| Clark (Accela) | Opus 5 | 3 | 3 | 100% | [0.44, 1.00] | $0.8575 | **$0.2858** | 110.7s | 118.9s |
| St. Johns (WATS) | Haiku 4.5 | 15 | 15 | 100% | [0.80, 1.00] | $0.4987 | **$0.0332** | 26.9s | 92.9s |
| St. Johns (WATS) | Sonnet 5 | 5 | 5 | 100% | [0.57, 1.00] | $0.3804 | **$0.0761** | 35.7s | 79.4s |

**On Accela the ranking inverts.** Opus 5 bills 5x Haiku 4.5 per token and is **2.40x cheaper per working
extractor**, because Haiku succeeds once in twenty attempts and each failure is paid for in full. Sonnet 5
lands between them at 1.13x Opus.

**On WATS it inverts back.** Both models succeed on every draw, nothing is wasted, and the price list
governs again: Haiku is 2.29x cheaper than Sonnet.

So the finding is not "the expensive model is cheaper." It is that **page difficulty decides which model
is cheaper, and the per-token price cannot tell you which regime you are in.** The quantity that ranks
correctly in both regimes is cost per success; the quantity the project had been reporting — cost per
call — ranks correctly in neither.

## Why this was invisible before

The variance experiment reported success rates. The cost model reported dollars per call. Both were
correct and neither was actionable, because the division that joins them was never performed: the rates
lived in `variance.json` and the dollars in `ledger.jsonl`, and no code read both.

This is the ordinary shape of the problem. Each artifact was complete, the join was the missing
instrument, and the missing instrument is not visible in either artifact.

## A second finding, smaller

**Latency does not track the price list either, and it splits the other way.** Opus's p50 on Accela is
110.7s against Haiku's 22.3s — roughly 5x — while its p95 is *tighter in relative terms* (118.9s, a 7%
spread over p50) than Haiku's (40.5s, an 82% spread). The cheap model is fast on average and erratic; the
expensive one is slow and predictable. For a batch pipeline that schedules against a worst case, a
predictable 119s is easier to plan around than an 82%-variable 22s.

n is 3 for the Opus cell. This is an observation, not a result.

## What this establishes

- **Cost per success is the correct unit for model selection in a synthesis pipeline**, and it is not
  derivable from a price list, a success rate, or a per-call cost alone.
- **The inversion is real in both directions**, which rules out the trivial reading. A finding that only
  ever favoured the expensive model would more likely be an artifact of the metric.
- **The roll-up reproduces every previously published figure exactly** — the five success rates, their
  intervals, the drift survival rates, and 55 draws / 29 failures / 25 silent. That agreement is the
  validation: two independent implementations of the same aggregation returning the same numbers.

## What this does not establish

- **It is agreement with a hand-written adapter, not accuracy.** Every figure here inherits the reference
  parse. [ADR-0014](../adr/0014-the-golden-set-precedes-the-pipeline.md) is untouched.
- **n is small where it matters most.** The Opus cell is three draws and its success interval is
  [0.44, 1.00], which admits a true rate near half. A true Opus rate of 50% would put its cost per success
  at roughly $0.57 and shrink the gap to 1.2x. **The direction survives that; the magnitude does not.**
- **Two platforms is not a difficulty axis.** "Page difficulty decides" is an inference from two points.
  It is the natural reading and it is not a measurement.
- **Retries are not priced in.** Nothing here models the obvious production strategy of retrying a cheap
  model on failure, which would change every number in the table. That is the next experiment, and it is
  also the one that needs the repair loop.
- **Latency is wall-clock from one machine on one day**, including network. It is not a server-side
  measurement and should not be quoted as one.

## Reproduction

```
python scripts/model_stats.py
python -m unittest tests.test_model_stats -v
```

No API key required, no calls made. `tests/test_model_stats.py` pins the five success rates, the 55/29/25
failure taxonomy, and both directions of the cost inversion.
