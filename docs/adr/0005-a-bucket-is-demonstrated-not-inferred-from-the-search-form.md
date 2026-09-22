# ADR-0005: A bucket is demonstrated, not inferred from the search form; and the gate metric may fire but may not clear

Status: Accepted

Date: 2026-09-20

## Context

Spike A classified 28 offices into enumerability buckets by fetching each portal's search form, probing
empty-criteria behaviour, and reading what the form rendered. That is a ten-minute-per-office method, and
it is the only reason a 28-office distribution exists at all.

St. Johns County FL was classified **bucket 4** — *search-only, needs a known address, parcel or permit
number* — on that basis. Step 1 then pulled it: a date range alone returns the complete set, the result
cap is announced in the page body, and weekly partitioning stays under it without a single bisection.
That is the **bucket 3** definition, exactly. 3,627 records in 28 requests
([2026-09-20 step 1](../evidence/2026-09-20-step1-stjohns-reconciliation.md)).

The misfiling matters out of all proportion to one row, for two reasons.

**First, that row carries 28% of the sample's units.** St. Johns is 3,637 of bucket 4's 4,386 units. The
revised gate in `DESIGN.md` states that unit-weighted reachability of 73.1% *"depends entirely on bucket 4
being acquirable"*, and that if adaptive query partitioning fails, reachability collapses to buckets 1–3
plus 5 = **39.2%, below the 50% line, and the gate fires.** With St. Johns in bucket 3 that fallback floor
is **67.3%** and the gate does not fire. One row moved a decision.

**Second, the error runs one way.** Reading a form can only under-classify. A form that renders address
fields and no date field looks like bucket 4 whether or not the backend will accept a bare date range; a
portal that *does* enumerate can look like one that does not, but not the reverse. So the published 28.5%
enumerable was a lower bound and nothing in the method said so.

A third fact belongs here because it is the same failure: the adapter was built with
`bps_id = "633000"`, copied from Spike A's hardcoded probe key. `12|633000` is Okeechobee County, which
reports zero units in zero of 24 months. The classification CSV had the correct `12|803000` the whole
time. A probe artifact was treated as a source of record, and probe artifacts are not that.

## Decision

**1. A bucket assignment read off a rendered form is `provisional`. A bucket is `confirmed` only by a
demonstrated pull** that returns a complete set under a stated cap and is verified complete by the
adapter's own completeness check. A confirmed assignment supersedes a provisional one, and the
reachability aggregates are re-derived from the classification file when it does.

**2. `data/spike_a/classification.csv` is the single source of bucket and identity.** Probe JSONs are
working notes. Nothing downstream — an adapter, a run script, a report — may take a bucket, a `bps_id` or
a label from a probe artifact.

**3. The unit-weighted reachability metric may fire the gate but may not clear it.** It is a valid halting
signal and an invalid passing signal, and the asymmetry is deliberate: at n = 28 with one row carrying 28%
of the units, the figure is precise enough to catch a domain that is obviously unreachable and nowhere
near precise enough to certify one that is reachable. Clearing the gate requires the named-office test,
which has an external consumer.

**4. Any movement in the metric is reported with its leverage** — which rows moved, and what share of the
denominator they carry. A reachability number quoted without that is a number whose fragility has been
hidden.

## Consequences

- **The distribution is now a mix of provisional and confirmed rows, and every report must say which.**
  This is a real cost: the headline is less tidy than "28.5% enumerable" and has to be read with a
  qualifier attached. That is the point.
- **Confirmation is not free.** St. Johns cost 28 requests and an adapter. Confirming all 28 offices is
  several hundred requests and several adapters, which is not affordable before the gate. So most rows
  stay provisional indefinitely, and the honest summary of the distribution is *"one row confirmed, one
  row confirmed-and-moved, twenty-six provisional"*.
- **The published 28.5% is now known to have been a lower bound.** So, by the same argument, is today's
  56.7% — the one-way bias does not disappear because it was corrected once. Two bucket-4 rows and four
  bucket-7 rows have never been tested against the behaviour their classification asserts.
- **It makes the cheap method legitimate rather than discarding it.** Form-reading stays the default
  because 28 rows at ten minutes each is what made any distribution possible; what changes is that its
  output is labelled for what it is.
- **The gate becomes harder to pass and no easier to fire**, which is the correct direction for a rule
  whose failure mode is flattering the project. Nothing in this ADR moves a threshold.

## Alternatives considered

- **Keep the Spike A classification and note the discrepancy in a footnote.** Cheapest, and it means
  continuing to quote 39.2% as the fallback floor after demonstrating it is 67.3%. Rejected: quoting a
  number known to be wrong is the specific failure the evidence directory exists to prevent.
- **Re-probe all 28 rows with a demonstrated pull before quoting any distribution.** Methodologically
  clean and unaffordable — several hundred requests and up to five adapters, against a gate that is weeks
  away. Rejected on cost, with a partial version kept: **the two remaining bucket-4 rows are worth probing
  first**, because they are the only rows that can move the fallback floor again.
- **Treat the reclassification as proof the unit-weighted gate is unusable and drop it.** Tempting, and it
  over-corrects. The metric still catches the case it was written for — a domain where the data is
  genuinely unreachable — and dropping it leaves no halting rule at all until the named-office list
  exists. The asymmetry in decision 3 keeps its useful half and discards the half it cannot support.
- **Weight the gate by confirmed rows only.** Would make the figure honest by construction. Rejected: with
  one confirmed row the denominator is one, and a metric that cannot be computed is worse than one that
  must be read with a caveat.

## Revisit when

Either of the two remaining bucket-4 rows is tested and does *not* move — which would be the first
evidence that form-reading is accurate rather than merely cheap — or a second provisional row is
demonstrated wrong, which would make the provisional distribution untrustworthy enough to stop quoting.
Also revisit if n grows materially past 28, since most of the fragility in decision 3 is a sample-size
problem and not a permanent property of the metric.

## References

- [`docs/evidence/2026-09-20-step1-stjohns-reconciliation.md`](../evidence/2026-09-20-step1-stjohns-reconciliation.md)
  — the pull, the reclassification arithmetic, and the identity error
- [`docs/evidence/2026-09-20-spike-a-portal-enumerability.md`](../evidence/2026-09-20-spike-a-portal-enumerability.md)
  — the original classification and its method
- `DESIGN.md` §8, "The revised gate"
- [ADR-0004](0004-bucket-taxonomy-gains-a-no-record-and-an-access-gated-cell.md) — the taxonomy this
  re-files a row within
- [ADR-0007](0007-office-identity-is-the-bps-office-id.md) — why a probe artifact may not supply identity
