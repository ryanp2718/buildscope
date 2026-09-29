# Cost per success with its uncertainty: one price-list inversion survives, and it is not the headline one

Date:      2026-09-27
Produced:  `python spikes/cost_per_success_intervals.py` (no model calls; cost $0.00; seeded)
Inputs:    `data/infer/model_stats.csv` (protocol v1 baseline cells, 2026-09-21 to 2026-09-26),
           list prices in `permits/models.py`
Outputs:   stdout only; no artifact written
Status:    Current. Qualifies [2026-09-22 cost per success](2026-09-22-cost-per-success.md) and the
           cost-per-success comparisons in [2026-09-25 open-weight model axis](2026-09-25-open-weight-model-axis.md).

## Question

For each pair of models measured on the same target, how sure can we be which one is cheaper per
working extractor? And do the rankings the 2026-09-22 and 2026-09-25 reports quote survive that
uncertainty?

## Method

**Cells.** Every protocol v1 baseline cell with at least 3 scored draws and at least one perfect draw:
6 on Clark, 5 on St. Johns. Cells with no success have no defined cost per success and are left out;
the St. Johns reasoning-tier cells (n of 1 or 2) are left out, as in the 2026-09-25 report.

**Why a ratio of point estimates is not enough.** Cost per success is mean cost per draw divided by the
pass rate. Cost per draw is measured on every draw and is fairly tight. The pass rate is the uncertain
part, and dividing by it gives an interval with a long tail on the expensive side: Haiku's 1 of 20 on
Clark has a Wilson interval of [0.009, 0.236], which puts its cost per success anywhere from $0.15 to
$3.86.

**Two readings of each pair.**

- *Wilson ends.* Each model's cost per draw over the ends of its rate's Wilson 95% interval, paired
  worst against best. This is the widest the ratio can be if both rates sit at opposite ends at once.
  It is not a 95% interval for the ratio, and overlapping ranges do not mean there is no evidence
  either way. The 2026-09-22 report's check ("a true Opus rate of 50%...") moved one end of one cell
  and held the other at its point estimate.
- *Simulation.* 100,000 draws per pair. Each rate is drawn from a Beta posterior and each cell's mean
  cost per draw from a bootstrap of its own draws. The result is the ratio's median, its central 95%
  range, and the share of draws in which the model listed first is cheaper (P). Two priors, uniform
  (Beta(1, 1)) and Jeffreys (Beta(0.5, 0.5)), because at n = 3 the prior moves the answer. When it
  does, the data are not deciding it.

**Token price.** From the list prices in the registry. "Inverts" means the model cheaper per success
costs more per token on both input and output; "mixed" means the two prices order the pair
differently.

**Holds.** A ranking is said to hold when P is at least 0.975 under both priors.

**Not controlled.** Draws are treated as independent, and a draw's cost as independent of whether it
passed. Every cell ran under protocol v1, whose configuration differs by vendor (output ceiling,
reasoning setting, host; audit findings F1 to F6). This report measures how certain the v1 rankings
are, not whether they are fair.

## Result

Pairs, with the model cheaper per success at the point estimate listed first. The full table, all 25
pairs under both priors, is printed by the producer.

**The rankings earlier reports quote:**

| target | cheaper | dearer | token price | point | simulated 95% range | P (uniform / Jeffreys) | quoted in |
|---|---|---|---|---:|---|---|---|
| Clark | Opus 5 | Haiku 4.5 | inverts | 2.40x | 0.34x to 8.5x / 0.44x to 19.6x | 0.60 / 0.77 | 2026-09-22, README |
| Clark | Opus 5 | Sonnet 5 | inverts | 1.13x | 0.26x to 3.2x / 0.32x to 4.7x | **0.32 / 0.46** | 2026-09-22 |
| Clark | kimi-k2-thinking | Opus 5 | also cheaper | 1.64x | 0.58x to 7.4x / 0.40x to 6.1x | 0.90 / 0.83 | 2026-09-25 |
| Clark | deepseek-v4-flash | Opus 5 | also cheaper | 5.05x | 1.3x to 71x / 0.60x to 54x | 0.98 / 0.95 | 2026-09-25 |
| Clark | glm-5.3-flash | Opus 5 | also cheaper | 20.2x | 6.2x to 144x / 4.4x to 121x | 1.000 / 0.999 | 2026-09-25 |
| St. Johns | Haiku 4.5 | Sonnet 5 | also cheaper | 2.29x | 1.8x to 4.2x / 1.8x to 3.7x | 1.000 / 1.000 | 2026-09-22 |
| St. Johns | gpt-oss-120b | Haiku 4.5 | also cheaper | 32.7x | 23x to 48x / 23.5x to 47x | 1.000 / 1.000 | 2026-09-25 |
| St. Johns | gpt-oss-120b | Sonnet 5 | also cheaper | 74.9x | 53x to 149x / 52x to 134x | 1.000 / 1.000 | 2026-09-25 |

**Every pair that inverts the price list at the point estimate:**

| target | cheaper per success | dearer per success | token price ratio | point | P (uniform / Jeffreys) |
|---|---|---|---:|---:|---|
| St. Johns | gpt-oss-120b | qwen3.5-flash | 2.3x dearer | 6.69x | **1.000 / 1.000** |
| Clark | Opus 5 | Haiku 4.5 | 5x dearer | 2.40x | 0.60 / 0.77 |
| Clark | Sonnet 5 | Haiku 4.5 | 2x dearer | 2.13x | 0.71 / 0.74 |
| Clark | Opus 5 | Sonnet 5 | 2.5x dearer | 1.13x | 0.32 / 0.46 |

Of the four, one holds: **gpt-oss-120b is 6.7x cheaper per working extractor than qwen3.5-flash on
St. Johns (95% range about 4x to 12x under both priors) while costing 2.3x more per token.** Two
things multiply to give it: qwen3.5-flash spends 3.8x as much per draw ($0.0034 against $0.0009,
because it writes far more output tokens), and it passes 1.8x less often (10 of 20 against 18 of
20). Most of the gap is token volume, which a per-token price cannot show.

The three Clark inversions among the Claude models are between 32% and 77% likely. **The 2026-09-22
headline, that Opus 5 is cheaper per success than Haiku on the hard page, is somewhat more likely true
than not, and not established.** Against Sonnet 5 the simulation leans the other way. 3 of 3 is the
most flattering result 3 draws can produce, and once the posterior allows a lower true rate, Opus's
$0.29 per draw (5.3x Sonnet's) outweighs its pass rate.

**What holds on Clark.** glm-5.3-flash is the cheapest per success there, against every model it
can be compared with except deepseek-v4-flash (P at least 0.992 against Haiku, Sonnet, Opus 5 and
kimi-k2-thinking). It is also among the cheapest per token, so this agrees with the price list.

## What this establishes

- **Cost per success does rank differently from price per token, and at least one inversion is
  robust**: gpt-oss-120b over qwen3.5-flash on St. Johns, with every simulated draw in the same
  direction. The claim the project has been making is supported, by a different pair from the one it
  cited.
- **The Opus 5 inversion on Clark is not established**: P = 0.60 to 0.77 against Haiku and 0.32 to 0.46
  against Sonnet. The 2026-09-22 report's "the direction survives" is withdrawn, as is the 2.40x.
- **The easy-page multiples are robust.** gpt-oss-120b's 32.7x over Haiku and 74.9x over Sonnet, and
  Haiku's 2.29x over Sonnet, hold with 95% ranges that stay well above 1.
- **On Clark, the cheap current-generation models beat the Claude models per success**: glm-5.3-flash
  holds against all three, and deepseek-v4-flash holds against Opus 5 under the uniform prior only.

## What this does not establish

- **Anything about fairness.** Every cell ran under protocol v1, where Claude had a quarter of the
  output ceiling of the OpenRouter reasoning models and hosts were unconstrained (audit F1, F4). A
  robust v1 ranking is a certain answer to an uncontrolled question. Protocol v2 is the controlled one.
- **A frequentist interval.** The simulated ranges are posterior intervals under a model of
  independent draws. At these sample sizes they agree in direction with the Wilson-ends reading
  wherever that reading excludes 1, but they are not the same object, and the pre-registered test for
  the v2 run (non-overlapping Wilson intervals of cost per success) is a different test, and
  generally a more conservative one.
- **Opus 5 at a larger n.** The v2 run does not re-run Opus 5; it asks the same question of Opus 5.5.
- **Accuracy.** Every pass is agreement with the hand-written adapter.
- **Retries.** A cheap model retried on failure changes every figure here, as in the 2026-09-22 report.

## Reproduction

```
python scripts/model_stats.py
python spikes/cost_per_success_intervals.py
```

No API key required, no calls made. Seeded, so the simulated figures reproduce exactly.
