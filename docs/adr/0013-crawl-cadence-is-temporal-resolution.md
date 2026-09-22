# ADR-0013: Crawl cadence is temporal resolution, so it is chosen, not configured

Status: Accepted

Date: 2026-09-21

*Back-fill. The decision is D4 in `DESIGN.md` and predates this directory. It is unimplemented — nothing
has been crawled twice — and this ADR says so rather than describing a scheduler that does not exist.*

## Context

Crawl cadence looks like an operations setting and is not. It is the sampling rate of the dataset, and it
bounds what can ever be said about time.

Two things follow from that and neither is obvious from the scheduler's point of view. A weekly crawl
places an issue date within a seven-day interval *at best*, which is fine for BPS reconciliation because
BPS counts by issue month. But the reporting-lag metric — how long a jurisdiction takes to make an issued
permit visible online, which [ADR-0008](0008-time-is-recorded-twice.md) names as one of the more
publishable things in the dataset — has a resolution that is exactly the cadence. A monthly crawl cannot
measure a lag distribution whose interesting mass is under a month.

And a uniform cadence is wrong in both directions at once: it wastes fetches on a village issuing four
permits a month, and under-resolves Houston.

## Decision

**Tiered by BPS unit volume, with churn-driven promotion.**

| Tier | Cadence |
|---|---|
| Top BPS unit-volume decile | Daily |
| Remainder of tier-1 | Weekly |
| Tier-2 (imputed) | Monthly |

- **Base tier is volume-driven.** Unit volume is what the dataset is weighted by, so it is what resolution
  should be spent on.
- **Promotion is churn-driven.** Unexpected index-page churn temporarily upgrades a jurisdiction. Keying
  promotion on volume would merely re-derive the base tier and buy nothing.

## Consequences

- **Nothing here is implemented, and the consequence of that is specific.** Every permit in the store has
  been observed exactly once, so every `observed_at` is within hours of every other and the lag
  distribution is degenerate. Quoting a lag figure from the current data would be quoting the crawl
  schedule. [ADR-0008](0008-time-is-recorded-twice.md)'s second justification is deferred until this runs.
- **The tiers are already computable and the frame already carries them.** `data/frame/bps_frame.csv` has
  `bps_tier` (`collected` / `imputed_tier`) and `units_12mo` per office, so tier assignment is a sort, not
  a research problem. What does not exist is the scheduler.
- **Churn detection now has a mechanism it did not have when D4 was written.** The capture layer stores a
  structural fingerprint per page
  ([obligation 3](../evidence/2026-09-21-bucket4-resolution.md), `permits/fingerprint.py`), so "this
  index page changed structurally" is a comparison rather than a diff over bytes. Byte-level change is
  useless here — a session token or a rendered timestamp changes every fetch. This is the first concrete
  reason the fingerprint pays for itself outside Spike C.
- **Cadence interacts with the milestone model rather than being independent of it.** A weekly cadence
  against a five-day permit lifecycle loses middle states. The model survives that — a monthly crawl
  catching `applied -> issued -> finaled` in one gap records all three as latched-by-t2 rather than
  inventing an ordering ([ADR-0011](0011-milestones-are-rows-with-a-fixed-vocabulary.md)) — but the
  transitions have to be recorded as intervals, not instants, or the schema asserts a precision the
  observation cannot support.
- **The politeness budget is a constraint on this, not a separate concern.** The capture layer enforces a
  per-host pause and a request ceiling, and the top decile at daily cadence is where those two meet. No
  crawl plan has been costed against them yet.
- **Tier-2 at monthly is a resolution floor on the imputed tier, which is where validation is weakest
  anyway.** An imputed office has no BPS oracle to check against, so it gets the least resolution *and*
  the least verification. That compounding is a real weakness and is not addressed by this decision.

## Alternatives considered

- **Uniform cadence.** One number, no tier logic, no promotion machinery, and trivially auditable.
  Rejected because it is wrong in both directions simultaneously, and because the wasted fetches are not
  free — they are the same politeness budget the large jurisdictions need.
- **Promotion keyed on volume rather than churn.** The obvious signal, and already available. Rejected
  because it re-derives the base tier: a high-volume office is already in the top decile, so
  volume-triggered promotion can only fire where it has already fired.
- **Cadence driven by the source's own published update frequency.** Some open-data portals state one.
  Rejected as unreliable — a stated refresh frequency is a claim about intent, and the lag metric exists
  precisely because publication lags reality. Using it would bake the assumption into the measurement
  designed to test it.
- **Adaptive cadence per office, learned from observed change rates.** Strictly better in principle and
  the eventual right answer. Rejected for now because it needs a history of repeat observations to learn
  from, and there is none — it is unimplementable before the thing it would replace has run.

## Revisit when

The first repeat crawl completes and real churn rates exist, which turns the tier table from an estimate
into something fittable. Revisit sooner if the lag metric is promoted from a nice-to-have to a headline
finding, because that would make daily cadence a requirement rather than a tier.

## References

- `DESIGN.md` §D4, §D7, §9 (step 6), §6 (scale estimates)
- [ADR-0008](0008-time-is-recorded-twice.md) — the lag metric this cadence bounds
- [ADR-0011](0011-milestones-are-rows-with-a-fixed-vocabulary.md) — why coarse cadence does not corrupt
  the milestone model
- `permits/fingerprint.py` — the churn signal
- `data/frame/bps_frame.csv` — `bps_tier`, `units_12mo`
