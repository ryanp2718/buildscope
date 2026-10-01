# ADR-0004: the bucket taxonomy gains a no-record cell and an access-gated cell

Status: Proposed

Date: 2026-09-20

## Context

The six-bucket taxonomy in `docs/design/history.md` was written before a single portal had been looked at. It orders
jurisdictions by how hard their permit records are to acquire, from bulk download (1) to no online portal
found (6). Bucket 6 was terminal, so anything that was not 1-5 landed there.

Two measurements over 28 stratified jurisdictions found situations with no honest home in that scale, and
both were being recorded as bucket 6:

- **4 of 28 portals (14%) exist, are not JS-gated, and are not absent - they require registration or
  login** (Avolve ProjectDox, SagesGov, CommunityCore, iWorQ). See
  [Spike A](../evidence/2026-09-20-spike-a-portal-enumerability.md).
- **1 of 28 places issues no building permit at all.** Eastbrook ME, population 416, in a state that
  mandates code adoption only at 4,000+; its town website contains zero occurrences of "permit", "code"
  or "build", and the unit BPS reports for it is imputed. See
  [the tier-2 rerun](../evidence/2026-09-20-tier2-issuing-level-rerun.md).

Collapsing these into bucket 6 made that cell mean three different things at once, and the difference is
not cosmetic. It is the difference between *the record is on paper in a filing cabinet*, *the record is in
a database we are not admitted to*, and *the record was never created*. Those have different remedies,
different costs, and - critically - different implications for what coverage can ever mean.

The deeper problem the measurements exposed is that buckets 1-6 quietly assume two things that are not
always true: that a record exists, and that access to it is unrestricted. The ladder only orders
acquisition difficulty *given* those assumptions.

## Decision

**Add two cells, numbered 0 and 7, and stop treating the scale as a single ladder.**

| # | Bucket | What it means |
|---|---|---|
| **0** | **No permit is issued; no record exists at any level** | Not a coverage gap. Nothing to acquire, at any price. |
| 1-6 | unchanged | An ordered ladder of acquisition difficulty, given that a record exists and access is open |
| **7** | **Portal exists, behind registration or login** | The record exists in structured form; the obstacle is permission, not technique |

Buckets 1-6 remain a difficulty ordering. Buckets 0 and 7 are **off-ladder terminal states** and are not
to be read as "worse than 6" and "better than 1". The numbers are positional labels chosen for continuity
with measurements already published; they do not extend the ordering.

**Every reported bucket distribution must aggregate three ways, not one:** enumerable (1-3), acquirable
with work (4-5), and blocked (6, 7) - with bucket 0 reported *separately from all of them*, because it
changes the denominator rather than the numerator.

**Bucket 0 requires a positive basis, never absence of evidence.** An acceptable basis is a statutory
threshold that exempts the jurisdiction, or an explicit statement by the jurisdiction that no permit is
required. "We could not find a portal, a form, or a phone number" is bucket 6. This rule exists because
**bucket 0 is the only cell that improves the coverage statistic by being assigned** - it removes units
from the achievable denominator - so it is the one cell with a standing incentive to over-assign, and it
gets the strictest evidence bar for exactly that reason.

## Consequences

**Makes easier.** The coverage ceiling becomes legible instead of lumped: how much of the frame is
unreachable-but-extant, how much is permission-blocked, and how much never existed are now three numbers.
Bucket 7 in particular becomes a decision the project can take deliberately - registering for a portal is
a policy question, and it could not even be posed while those rows were filed as "no portal found".

**Makes harder.** Assigning bucket 0 well needs per-state knowledge of code-adoption thresholds, which is
fifty separate rules and real work. Until that exists, bucket 0 will be systematically *under*-assigned
and some genuinely recordless places will sit in bucket 6. That is the safe direction of error and is
accepted deliberately: it understates coverage rather than flattering it.

**Forecloses.** Quoting a single "percent enumerable" as the project's headline health metric. With a
cell that shrinks the denominator, one number can no longer carry the meaning, and any figure that does
not say which aggregate it is reporting is now ill-defined.

**Costs accepted.** The numbering implies a continuum that buckets 0 and 7 do not belong to, and readers
will occasionally misread 7 as harder than 6. The prose above is the only guard against that; a cleaner
scheme was available and was rejected below for a reason that is about evidence integrity, not taste.

**Explicitly not decided here:** whether the project will register for bucket-7 portals. This ADR names
the cell and requires it be counted. Whether to accept a portal's terms of service to reach its data is a
separate decision with legal and robots-posture dimensions, and it deserves its own ADR.

## Alternatives considered

**Keep six buckets; record registration-gating and no-permit as free-text notes.** Rejected on
proportion. Together these are 17.9% of the measured sample - too much to leave in prose, and prose does
not aggregate. The concrete harm was already visible: bucket 6 read as a single coverage ceiling when it
was three unrelated problems stacked in one cell.

**Split bucket 6 into 6a / 6b / 6c.** Rejected because it frames bucket 0 as a refinement of "no portal
found", which it is not. Bucket 0 is a claim about whether a record exists; buckets 1-6 are claims about
how to get a record that does. Nesting the first inside the second would bury the one distinction that
changes the denominator.

**Renumber the whole taxonomy with non-numeric codes,** which would remove the false ordinal reading
outright. Rejected because two dated evidence reports and `data/spike_a/classification.csv` already quote
the numbers 1-7. Evidence reports are append-only precisely so a figure quoted in September can be traced
to what was known in September; renumbering would strand them, and the false-ordinal cost is smaller than
the cost of breaking that guarantee. This is the alternative that would have won on a greenfield day one.

**File registration-gated portals as bucket 5,** since both need more than a plain HTTP fetch. Rejected
because the remedies differ completely: a headless browser solves bucket 5 and does nothing for bucket 7,
which needs an account, an accepted terms-of-service, and possibly a stated purpose. Same symptom,
different cost, different legal posture.

## Revisit when

- **A bucket-7 portal is successfully enumerated after registering.** That would make 7 a cost tier rather
  than a blocked state, and it should rejoin the ladder between 4 and 5.
- **Bucket 0's frame-wide share is measured.** One instance and one state's statute are not a rate. If it
  is negligible, the cell can be folded back into 6 and the denominator rule retired; if it is large -
  Maine alone has ~370 sub-threshold municipalities - it changes what "national coverage" can honestly
  claim, and that belongs in its own ADR.
- **A third off-ladder state appears.** This taxonomy has now been extended twice by measurement, both
  times by looking at fewer than thirty jurisdictions. A third extension would be evidence that the
  single-scale framing is wrong and the classification should become two or three independent attributes -
  record exists, access permitted, acquisition difficulty - rather than one number.

## References

- [Spike A: portal enumerability](../evidence/2026-09-20-spike-a-portal-enumerability.md) - bucket 7, 4 of 28
- [Tier-2 rerun at the issuing level](../evidence/2026-09-20-tier2-issuing-level-rerun.md) - bucket 0, and why
  the county is never the alternative level
- `docs/design/history.md`, Spike A protocol - the canonical bucket table, updated to match this ADR
- `data/spike_a/classification.csv`, `data/spike_a/tier2_reclassification.csv` - the classified rows
- [ADR-0003](0003-jurisdiction-identity-is-bps-scoped.md) - why the issuing body is not the identity, even
  when it is a private contractor or nobody at all
