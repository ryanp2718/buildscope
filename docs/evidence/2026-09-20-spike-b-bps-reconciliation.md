# Spike B: can portal permit data be reconciled against the BPS oracle?

Date:      2026-09-20
Produced:  `spikes/spike_b_sample.py`, `spike_b_discover.py`, `spike_b_endpoints.py`,
           `spike_b_schema.py`, `spike_b_values.py`, `spike_b_extract.py`,
           `spike_b_compare.py`
Inputs:    `data/frame/bps_frame.csv`, `data/frame/bucket1_candidates.csv`,
           `data/raw/bps/` (24 months x 4 regions of BPS place files)
Outputs:   `data/spike_b/manifest.csv` (58 rows, append-only),
           `bps_months.csv`, `schema.json`, `vocabularies.json`,
           `extract.json`, `reconciliation.csv`
Status:    Current
Cost:      $0 inference. 57 HTTP requests, no model calls.

## Question

Can portal-visible permit data actually be aggregated into something comparable
to Census unit counts? This underwrites the **differentiating** claim of the
project - the one that lands at step 1 and carries the writeup - and it had
never been tested.

## The sample changed, and why that is the first finding

The protocol says to draw 5 tier-1 jurisdictions from buckets 1-3 in Spike A.
That is impossible: Spike A's 28-office sample produced two bucket-3
jurisdictions and none in buckets 1-2, and **neither survivor is in the
clean-oracle set** - Clark County NV and McMinnville OR both carry imputed
months, so neither can be scored against anything. The sample was drawn fresh
from the frame under the two binding rules that do survive: clean-oracle
offices only, and `Source` checked per month.

**The draw then exposed a defect in the bucket-1 classification itself.**
`bucket1_candidates.csv` matched **publishers**, not datasets - `datasets` is
empty for every sampled office. Checking at dataset level, scoped to the
matched publisher:

| Office | Permit dataset? |
|---|---|
| Austin TX | **yes** - Issued Construction Permits (Socrata) |
| Seattle WA | **yes** - Issued Building Permits (Socrata) |
| Mecklenburg County NC | **yes** - Building Permits (ArcGIS, City of Charlotte) |
| Columbus OH | **yes** - Building Permits (ArcGIS) |
| Nashville-Davidson TN | **yes** - Building Permits Issued (ArcGIS) |
| Madison WI | no - parking permits and road closures only |
| Osceola County FL | no - parcels, contours, address points |
| Frisco TX | no - nothing under the matched publisher |
| Miami-Dade Unincorporated FL | no - building *violations*, water permits |

**Five of nine publisher-level bucket-1 classifications do not survive
dataset-level checking.** Section 9's claim 3b - *"bucket 1 is 0.90% of offices
but 16.6% of national units"* - is a publisher-level figure and should be read
as an **upper bound** until re-derived at dataset level.

It also cost the sample its unincorporated-county slot: both unincorporated
counties tried publish no permits, and four of the ten highest-volume permit
offices in the country are unincorporated county areas.

## Field availability, per the protocol's questions

| Office | New vs alteration? | Unit counts? | Issue date distinct from application? |
|---|---|---|---|
| Austin TX | yes - `work_class` + `permit_class` | yes - `housing_units` | yes - `issue_date` / `applieddate` |
| Seattle WA | yes - dataset is pre-filtered to New | yes - `housingunits`, plus added/removed | yes - `issueddate` / `applieddate` |
| Mecklenburg NC | **NO - `worktype` is blank in every 2026 record** | yes - `numunits` | issue only |
| Columbus OH | yes - `GENERAL_TYPE` names New Structure | yes - `UNITS` | issue only |
| Nashville TN | yes - `Permit_Type_Description` | **NO - no unit field exists** | yes - `Date_Issued` / `Date_Entered` |

Two of five fail on a field the comparison requires, for two different reasons.
Nashville publishes permit counts and nothing else; units appear only inside
free text (`Permit_Subtype_Description` = "Multifamily, Apt / Twnhome > 5 Unit
Bldg"). **Mecklenburg's failure is worse because it is silent**: the historical
record has `worktype` populated 123,262 times, and then every one of the 500
records issued in Q1 2026 has it blank. The field the classification depends on
was abandoned mid-dataset. That is section 5's *"per-field null rate per
template - the drift alarm"* firing in a live production dataset, and it is the
strongest argument yet that the alarm is not optional.

## The largest trap: sub-permits carry unit counts

Austin's first run scored **726% error** - 3,991 units against a BPS figure of
483. The cause is not extraction and not classification. Austin issues an
Electrical, Mechanical and Plumbing sub-permit alongside each Building Permit,
and **every one of them carries a populated `housing_units` value**:

| permittype | permits | units |
|---|---|---|
| EP Electrical | 197 | 1,368 |
| **BP Building** | **185** | **488** |
| MP Mechanical | 175 | 839 |
| PP Plumbing | 175 | 1,296 |

Filtering to `permittype='BP'` alone takes January from **726% error to 1.0%**.

This is invisible unless you look at the permit-type breakdown. Nothing in the
field names warns you; `housing_units` is populated, plausible and wrong. A
pipeline that summed it would have produced a confident, badly inflated
headline number. **Every jurisdiction must be checked for sub-permit
duplication before its counts are trusted**, and that check belongs in the
golden set (D9), not in a reviewer's judgement.

Austin also publishes a `jurisdiction` field distinguishing AUSTIN FULL
PURPOSE, AUSTIN LTD and AUSTIN 2 MILE ETJ. The BPS place is the incorporated
city; the dataset covers more. Not corrected for here, and a known residual.

## Result

`|ours - BPS| / BPS`, per jurisdiction-month, all months `Source`-checked. All
9 scored months are true reports; none were dropped as imputed.

| Jurisdiction | 2026-01 | 2026-02 | 2026-03 |
|---|---|---|---|
| Austin TX | **1.0%** | 32.2% | 44.1% |
| Seattle WA | 7.9% | **2.2%** | 5.7% |
| Columbus OH | 230.1% | **2.1%** | **0.1%** |
| Mecklenburg NC | no classification possible | " | " |
| Nashville TN | no unit field | " | " |

**n = 9 months, 3 jurisdictions, median |error| 5.7%.**

### The error is not uniform, and that is the actual finding

The protocol asked for the structure-type split on the grounds that a large
error concentrated in the 5+ column is a different diagnosis from a uniform
one. It is entirely concentrated there:

| Jurisdiction | month | low-density (1 + 2 + 3-4) | 5+ units |
|---|---|---|---|
| Austin | 2026-01 | 174 / 169 — **3.0%** | 314 / 314 — **0.0%** |
| Austin | 2026-02 | 165 / 144 — 14.6% | 208 / 406 — **48.8%** |
| Austin | 2026-03 | 214 / 202 — **5.9%** | 34 / 242 — **86.0%** |
| Columbus | 2026-01 | 50 / 51 — **2.0%** | 224 / 32 — **600.0%** |
| Columbus | 2026-02 | 47 / 48 — **2.1%** | 0 / 0 — n/a |
| Columbus | 2026-03 | 41 / 42 — **2.4%** | 633 / 633 — **0.0%** |

**Low-density: median 2.7%, worst case 14.6%, n=6.**
**Multifamily: 0.0%, 0.0%, 48.8%, 86.0%, 600.0% — unusable as it stands.**

Columbus's 1-3 family count lands **within a single unit of BPS in all three
months.** Austin's January matches BPS *exactly* on both single-family (157 =
157) and 5+ (314 = 314). These are not approximations that happen to be close;
for low-density construction the portal and the Census figure are measuring
the same thing and agreeing.

Multifamily fails because a single 200-unit building moves a month's entire
figure, and the portal's issue date and the month Census attributes the units
to need not agree. The errors are bidirectional - Columbus over-counts January
by 600%, Austin under-counts March by 86% - which is the signature of timing
and attribution, not of a systematic extraction bug.

## What this establishes

**1. The differentiating claim is real, with a stated scope.** Portal data
reconciles against the BPS oracle at **~2-6% for low-density residential
construction**, measured against months that are true reports rather than
Census imputations. That is a defensible, quotable claim and it is the first
direct evidence the project's headline works at all.

**2. The claim must be scoped to structure type or it is false.** A blended
"median 5.7%" hides that multifamily ranges over two orders of magnitude.
Report low-density and 5+ separately, always - the same discipline the
three-way bucket reporting rule already imposes elsewhere.

**3. Multifamily timing is now the named hard problem for step 1.** It is not
an extraction problem, so more careful parsing will not touch it. It needs
either a reconciliation window wider than one month, or acceptance that
monthly multifamily is not comparable at all.

**4. Sub-permit duplication is a first-class data hazard.** One filter moved
Austin's error by a factor of 700. It is undetectable from field names.

**5. Bucket 1 is over-counted at the dataset level**, by 5 of 9 in this check.

**6. Field drift is real and silent.** Mecklenburg abandoned `worktype`
mid-dataset with no signal.

## What this does not establish

**Any national figure.** Three jurisdictions and nine months. The median is
computed over n=9 and must always be quoted with that n. This does not measure
national reconciliation error, and no number here may be presented as one.

**That the tier-1 result transfers to tier-2.** The protocol asked for a
tier-2 jurisdiction for field-availability purposes and **it was not run** -
the tier-2 offices in Spike A are buckets 0, 6 and 7, none of which has a
reachable dataset, and no fresh tier-2 draw was made. So this spike says
nothing about the population the project claims to contribute to. That gap is
unchanged from before the spike and should be closed before the writeup.

**That low-density agreement generalises beyond bucket 1.** Every jurisdiction
here publishes structured open data. A synthesized extractor reading HTML would
add extraction error on top of the definitional error measured here, and that
term is untested.

**That Austin's exact January match is typical.** One month matching to the
unit in two independent structure classes is striking, and might mean Austin's
dataset is the direct source of its BPS filing. It might also be luck. Two
other Austin months disagree by 32% and 44%.

**That the corrected Austin rule is right.** `permittype='BP'` fixed January
decisively but Feb and Mar remain 32% and 44% off, entirely in multifamily. The
ETJ/full-purpose jurisdiction split was identified and not corrected for.

**Anything about revision.** BPS revises published months. All figures here were
read on 2026-09-20 and were not re-read later, so revision drift is unmeasured.

## References

- `data/spike_b/reconciliation.csv` - the error table, one row per scored month
- `data/spike_b/vocabularies.json` - every work-type vocabulary, so the
  classification rules can be disagreed with without re-running anything
- `data/spike_b/manifest.csv` - append-only provenance, 58 rows over 35 pages
- [Spike A](2026-09-20-spike-a-portal-enumerability.md) - the bucket-1 figures
  this qualifies
- `docs/design/history.md` section 8 Spike B protocol; section 9 claim 6
