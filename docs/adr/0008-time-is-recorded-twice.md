# ADR-0008: Time is recorded twice — valid time and transaction time, and neither overwrites the other

Status: Accepted

Date: 2026-09-20

*Back-fill. The decision is D7 in `DESIGN.md` and predates this directory. It is the least-implemented of
the back-filled decisions and this ADR says so plainly rather than describing an intention as a mechanism.*

## Context

Two different questions get asked of the same permit and they have different answers:

- *When did this permit issue?* — the portal's answer, the date printed on the record.
- *When did we learn that?* — our answer, the moment a fetch returned a page saying so.

Collapsing them loses two things irrecoverably. The first is **point-in-time correctness**: a dataset that
cannot say what it believed last Tuesday cannot be audited, and cannot be used to reconstruct any analysis
run on it. The second is **the gap itself**, which is a finding rather than an artifact. How long a
jurisdiction takes to make an issued permit visible online — nationally, p50 and p95 — is not published
anywhere, falls directly out of the difference between these two clocks, and is one of the more publishable
things in the dataset.

The forcing constraint is the same asymmetry that decides [ADR-0006](0006-the-observation-log-is-the-source-of-truth.md):
transaction time can only be recorded **at the moment of observation**. It cannot be backfilled, inferred,
or recovered from the portal later, because the portal does not remember. Valid time can always be re-read;
transaction time is gone the instant it is not written down.

## Decision

**Both clocks are stored on every record, and neither overwrites the other.**

- **Valid time** is the portal-reported date. Under D6 this is *per milestone*, not per permit: `applied`,
  `issued`, `finaled` and `terminated` each carry their own `reported_date`. There is no single "the date"
  of a permit and the schema does not offer one.
- **Transaction time** is `observed_at`, stamped when the fetch that produced the record returned.
- **The gap between them is the reporting-lag metric** — a pipeline health check and a headline finding at
  once.
- **Comparisons state which clock they are denominated in.** The BPS reconciliation folds by *valid time*
  (`date_issued`), because that is what the Census Building Permits Survey counts.

## Consequences

- **Today this buys nothing and costs a column, and that is the expected state.** Every permit has been
  observed exactly once, so there is no second observation to disagree with the first, no transition
  interval to record, and no lag to measure. No lifecycle view exists; the fold is last-row-wins. The
  decision is justified **entirely** by the option it preserves, and an option that would be unbuyable
  later is worth paying a column for now.
- **It gives the reconciliation error a vocabulary it otherwise lacks.** The St. Johns figure is 1.0% /
  4.4% / 4.1% against BPS. Because the comparison is explicitly valid-time-denominated, **month-boundary
  lag is inside that number and is not separable from extraction error** — a permit issued on 31 January
  and reported by the county in February lands in different months on the two sides. Naming the clock is
  what makes that statement precise rather than a hedge
  ([step 1 evidence](../evidence/2026-09-20-step1-stjohns-reconciliation.md)).
- **The lag metric needs repeat observation, which needs cadence, which is step 6.** D4's tiered cadence is
  the mechanism; until it runs, every `observed_at` in the store is within hours of every other and the
  distribution is degenerate. Quoting a lag figure from the current data would be quoting the crawl
  schedule.
- **Transitions must be intervals when they arrive.** `transition(from, to, observed_between: [t1, t2])`.
  A weekly cadence against a five-day permit lifecycle will lose middle states, and a schema storing an
  instant would assert a precision the observation cannot support.
- **The cost of being wrong here is asymmetric and that is the whole argument.** Storing both clocks and
  never using the second wastes a column. Storing one and needing the second means the history does not
  exist and no amount of later work recovers it.
- **Two clocks make some queries harder.** "What is the current state" is a fold rather than a select, and
  every consumer must know which clock a figure is denominated in or they will compare across them. That
  is a real ergonomic cost, paid on every query, for a correctness property most queries do not need.

## Alternatives considered

- **Store valid time only.** Simplest, sufficient for aggregate monthly reconciliation — which is the
  entire near-term deliverable — and it forfeits point-in-time correctness and the lag finding permanently.
  Rejected on the asymmetry, not on near-term value, because on near-term value it would win.
- **Store transaction time only and treat the portal's dates as derivable.** They are not derivable; a
  weekly crawl places an issue date within a seven-day interval at best, and BPS counts by issue month.
  This would make the reconciliation impossible.
- **Derive transaction time from file modification times on the raw store.** Free, and it decays: files get
  copied, backed up, and moved, and mtime silently becomes the date of the copy. An identity or a timestamp
  reconstructed from a filesystem is not evidence
  ([ADR-0006](0006-the-observation-log-is-the-source-of-truth.md)).
- **Full SQL:2011 bitemporal tables with system-versioning.** The textbook implementation. Rejected as
  overbuilt for a step-1 pipeline emitting JSONL, and unnecessary: the two columns are the decision, and
  the storage engine is not.

## Revisit when

The first repeat observation of the same permit lands — which is when the lifecycle view and the transition
interval stop being hypothetical and need to be built rather than described. Also revisit if step 6 is cut
from scope, because at that point the lag metric is not deferred but abandoned, and this ADR's second
justification would need to be withdrawn rather than left standing.

## References

- `DESIGN.md` §D7, §D1, §D4 (cadence), §D6 (milestones as rows), §9 (step 6 unlocks the lag finding)
- [ADR-0006](0006-the-observation-log-is-the-source-of-truth.md) — the log that carries both clocks
- [`docs/evidence/2026-09-20-step1-stjohns-reconciliation.md`](../evidence/2026-09-20-step1-stjohns-reconciliation.md)
  — what a valid-time-denominated comparison does and does not contain
- `permits/emit.py` — `observed_at`, `milestone(name, reported_date)`
