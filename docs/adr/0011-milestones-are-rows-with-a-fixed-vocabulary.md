# ADR-0011: Milestones are rows with a fixed vocabulary, not a state machine over booleans

Status: Accepted

Date: 2026-09-21

*Back-fill. The decision is D6 in `DESIGN.md` and predates this directory.*

## Context

Permit lifecycles do not form a state machine. Real ones loop — plan review, revisions requested,
resubmitted, plan review — and branch, and are frequently invisible because the portal simply does not
expose the intermediate states. A canonical enum with allowed transitions has to either forbid transitions
that actually occur, or permit every transition it observes, which is a fully connected graph with extra
steps.

The alternative that suggests itself, a set of boolean flags, fails differently and worse: `issued = true`
on a revoked permit is a false statement under the ordinary reading. A boolean conflates *"this ever
happened"* with *"this is currently true"*, and once those are merged no query can separate them.

There is a third failure hiding behind both, and it is the one that matters for the headline metric.
**Absence has to mean something specific.** No issuance row can mean the permit was not issued, or that
the jurisdiction was never crawled, or that the cadence was too coarse, or that the portal never exposes
issuance at all. A flag defaulting to `false` silently asserts the first.

## Decision

**Milestones are rows, with a closed vocabulary of four.**

```
permit_milestones(permit_id, milestone, reported_date, observed_from, observed_to, confidence)
```

Values: `applied`, `issued`, `finaled`, `terminated{reason}`. `permits/emit.py` enforces the vocabulary
and raises on anything else.

- **Absence of a row means *not observed*, which is not *did not happen*.** This is the property the whole
  shape exists for.
- **`approved` was demoted to activity.** Plan-review approval is routinely provisional and never
  satisfied monotonicity honestly. Issuance and finalization essentially do not loop.
- **Activity is a separate, non-monotone label** — `in_plan_review`, `awaiting_applicant`, `inspecting`,
  `on_hold` — which flips freely with no ordering guarantees.
- **`authorization_state` is derived**, and returns `unknown` wherever the jurisdiction's expiry rule is
  unknown, which will be often. Do not compute an expiry you cannot justify.
- **Vocabulary mapping is per-vocabulary, not per-record.** A jurisdiction has 10–60 distinct status
  strings; collect distinct `(platform, jurisdiction, status_string)`, dedupe globally, map once, cache
  permanently. Always retain the native string, always allow `unmapped`, and track percent of observations
  with a confidently-mapped milestone as a headline quality metric.

## Consequences

- **BPS maps cleanly and that is not a coincidence.** BPS counts units *authorized*, which is a milestone.
  The reconciliation falls out of the model rather than being reverse-engineered from a status string —
  which is why `date_issued` is a fold over milestone rows and not a column.
- **The fixed vocabulary caught a real bug by refusing.** The Clark County adapter emitted a milestone
  name outside the four and 20 of 371 records were rejected at the boundary rather than written with a
  meaningless lifecycle. A free-text milestone column would have accepted all 20.
- **A milestone with no parseable date is dropped, not nulled.** `emit.milestone()` returns without
  appending when `norm_date` yields `None`, because a row asserting an observation with no date asserts
  something we do not have. The cost is that a date-parsing bug looks like an absence — which is exactly
  how `norm_date` nulled 100% of St. Johns' dates while the adapter appeared to work. The tests in
  `tests/test_normalize.py` exist because of that trade.
- **Monotonicity is a free data-quality alarm.** A milestone regression means an extraction error, a false
  merge, or something genuinely odd. It is falsifiable and checkable on every write. **It is not yet
  implemented** — every permit has been observed once, so no regression is possible to detect.
- **The loop information is not lost, it is projected away.** Five plan-review cycles are all in the
  observation log and exposed by the transition view; loop count is a query. This must be stated
  explicitly in the dataset docs, which converts an apparent limitation into documented intent.
- **The lifecycle view is a committed deliverable and it is what justifies
  [ADR-0010](0010-permit-identity-has-two-levels.md)'s surrogate.** These two decisions hold each other
  up, and cutting either should reopen the other.
- **Some jurisdictions never distinguish issue date from application date**, and those cannot participate
  in BPS reconciliation. That needs an explicit exclusion flag, not a silent guess. Not yet built.

## Alternatives considered

- **A canonical state enum with allowed transitions.** The textbook model, and it is how the domain
  describes itself. Rejected: permitting every observed transition yields a complete graph, and forbidding
  any means dropping real records. The model would be enforcing a fiction about municipal process.
- **Boolean flags per stage.** Cheapest to query — `WHERE issued` — and it is what most permit datasets
  publish. Rejected because it cannot express *not observed*, and because `issued = true` on a revoked
  permit is simply false.
- **Free-text status, normalized at read time.** Maximally faithful to the source and defers every hard
  decision. Rejected because "defer" here means every consumer re-implements the mapping, inconsistently;
  and because the native string is retained anyway, so this alternative offers nothing the decision does
  not already provide.
- **An open milestone vocabulary that grows as sources are added.** Tempting, and it would have accepted
  the Clark County records instead of rejecting them. Rejected precisely for that reason: the four values
  are the intersection that nearly every jurisdiction exposes somehow, and a vocabulary that grows to fit
  each source is a per-source vocabulary wearing a shared name.

## Revisit when

The first source that exposes a milestone genuinely outside the four and genuinely comparable across
jurisdictions — `expired` is the likeliest candidate, and the question to ask is whether it is observed or
computed. Also revisit when repeat observation begins, because that is when monotonicity checking stops
being describable and has to be built.

## References

- `DESIGN.md` §D6, §D5, §D7, §5 (quality metrics)
- [ADR-0010](0010-permit-identity-has-two-levels.md) — the surrogate this deliverable justifies
- [ADR-0008](0008-time-is-recorded-twice.md) — `reported_date` is per milestone, not per permit
- `permits/emit.py` — `MILESTONES`, `milestone()`, `reported()`
- `tests/test_emit.py` — the vocabulary and the absence-is-not-falsity assertions
