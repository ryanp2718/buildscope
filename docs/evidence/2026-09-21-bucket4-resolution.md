# Bucket 4 resolved: the two offices St. Johns left behind

Date:      2026-09-21
Produced:  `spikes/step1_bucket4_probe2.py` (entry pages), `spikes/step1_bucket4_probe3.py`
           (second hop), `spikes/spike_a_reclassify.py` (verdicts applied to the artifact)
Inputs:    `data/spike_a/classification.csv` (28 offices, 12,932 units),
           `data/spike_a/html/depth_21_087000_*.html` (a Spike A capture, re-read rather than re-fetched),
           `data/frame/bps_frame.csv`
Outputs:   `data/step1/manifest.csv` (12 new rows), `data/step1/pages/b4[bcde]_*.html`,
           `data/spike_a/classification.csv` (now carries a `status` column)
Status:    Current
Cost:      **$0.** 12 HTTP requests, no model calls.

## Question

After St. Johns moved from bucket 4 to bucket 3, two offices remained in bucket 4 — St. Louis MO and
Bowling Green KY, 749 units and 5.8% of the gate denominator between them. Neither had ever been sent a
query. Does either of them enumerate?

Bucket 4 mattered out of proportion to its size. `DESIGN.md` §8 said the 73.1% reachability figure
"rests entirely on that bucket turning out to be acquirable", and ADR-0005 named probing these two rows
as the cheapest remaining measurement that could still move the number.

## Method

Entry page, then one hop, then one query, stopping as soon as the bucket was decided. Every request went
through the capture layer, so every page has a manifest row and a verdict written in the same operation.

Two corrections were made mid-run and both are the same kind of error:

- **A substring field classifier reported three login controls as date fields**, because
  `contractorLogin` contains `to`. Field names are matched on token boundaries in probe III. This is the
  same failure family as Accela's "Please enter" JS constant and Spike C's raw `<tr>` count — a
  discriminator that fires on something every page has.
- **A `<table>`-shaped result detector could not see a `<div>` repeater.** St. Louis's public page was
  read as empty and was not; its items were server-rendered in a repeater the whole time.

## Result

### Bowling Green KY — `21|045000`, 458 units

The classification recorded *vendor unknown, basis inferred, "www2.bgky.org did not respond to our
client"*. **The portal was never unreachable.** `https://esuites.bgky.org/eSuite.permits/WelcomePage.aspx`
was sitting in Spike A's own saved bytes for that office, on disk since 2026-09-20, never extracted. It
answers in 13.8 KB.

What it is: **Tyler Technologies eSuite**, and its own text says the rest —

> *"Currently, this portal allows licensed contractors to apply for Electrical permits and make payment"*

Contractor login, no date criterion, no permit-number criterion, no search links, one service-address
box. It is an apply-and-pay portal for electrical permits. **No permit record search exists for any
visitor**, so there is nothing to enumerate and nothing an address would retrieve.

Recorded as **bucket 7** (portal exists, behind registration) rather than bucket 6 (no portal found),
because a portal was found. See the limitation below: bucket 7 as defined does not fit this well.

### St. Louis MO — `29|607000`, 291 units

Two portals, and the note in `classification.csv` was wrong about both.

The **2026 portal**, recorded as "announced, not yet probed", is `https://www.stlcitypermits.com/`. Its
`PublicPermits.aspx` page is 58.9 KB and renders a nine-item repeater — which turns out to be a catalogue
of *applications you can begin* (Building Permit, Home Occupation Waiver, Food Truck Permit, Short-Term
Rental…), not a record index. Apply-and-pay, like Bowling Green.

The **old portal** is the one that publishes records, and the note said it posts to `/searchresults.cfm`.
It does not — `/searchresults.cfm` is the site-wide search box. The permit form posts to itself and
carries `streetAddress` (marked `required`), `findByAddress`, and a hidden `everyWhere` flag that looked
like it might mean "no address filter".

| query | bytes | result |
|---|---|---|
| empty `streetAddress` | 34,177 | form re-rendered, no grid |
| wildcard `%` | 36,234 | `notFound='true'` |
| `1520 Market` | 37,635 | a parcel table: Parcel ID / Address / Owner Name, **zero permit fields** |

A known address returns a **parcel disambiguation step**, not permits — so it is parcel-keyed and
two-step. Empty and wildcard are both refused. **Bucket 4, demonstrated** — the first bucket-4 assignment
in this project resting on a demonstrated refusal rather than on reading a form.

### What it does to the gate

`classification.csv` gained a `status` column in the same operation, per ADR-0005: `confirmed` means a
query was sent and its *response* settled the bucket; `provisional` is everything else.

| Aggregate | 2026-09-20 published | **2026-09-21** |
|---|---|---|
| Enumerable (1–3) | 56.7% | **56.7%** |
| Acquirable (4–5) | 16.4% | **12.9%** |
| **Reachable (1–5) — the gate metric** | **73.1%** | **69.5%** |
| Bucket 4 alone | 5.8% | **2.3%** |
| Fallback floor (1–3 plus 5) | 67.3% | **67.3%** |
| Confirmed share of the denominator | — | **62.4%** |
| **Confirmed-reachable alone** | — | **58.9%** |

Each aggregate is rounded from the raw share of 12,932 units, so the rows do not add: enumerable is
56.65% and acquirable 12.88%, which sum to 69.53% and print as 69.5%, not 69.6%. Every figure in the
table is recomputed from `classification.csv` by `tests/test_artifacts.py`, which is what keeps this
table and the artifact from drifting apart.

Five offices are now `confirmed` (Clark County, McMinnville, St. Johns, St. Louis, Bowling Green) and
23 are `provisional`.

## What this establishes

- **The gate does not fire, and no longer depends on an unexamined cell.** Bucket 4 was 33.9% of units two
  days ago and is 2.3% now. The proposition `DESIGN.md` §8 said the metric rested on has been retired by
  measurement rather than by argument.
- **69.5% is a real decrease and it is the honest direction.** The headline fell 3.6 points because an
  office was demoted on evidence. A revision process that only ever revises upward is not measuring.
- **The gate survives its own provisional rows.** Confirmed-reachable alone is 58.9%, still above the 50%
  threshold. Every provisional row sits in an *unreachable* bucket, so the provisional mass can only move
  the number up — the safe direction.
- **All of the enumerable mass is confirmed.** 56.7% enumerable is 56.7% confirmed-enumerable.
- **Replay beat fetching for the fourth time.** Bowling Green's real portal cost zero requests to find; it
  needed someone to read bytes already on disk. The three prior instances are the Clark milestone
  vocabulary bug, the `norm_date` null-out, and the truncated page.
- **"Apply-and-pay" is a distinct portal species and it is not rare.** Two of two offices probed here run
  a modern, well-built transactional portal that publishes no permit records at all. Both would read as
  healthy portals to any automated vendor-detection sweep.

## What this does not establish

- **It is not a bucket-4 rate.** Two offices. The finding is about these two, and the honest general
  statement is only that bucket 4 was over-assigned in this sample.
- **Bucket 7 does not fit Bowling Green and the taxonomy has not been fixed.** ADR-0004 frames bucket 7 as
  "permission, not technique" — implying registration would obtain the records. Here registration is a
  contractor credential for filing electrical applications and would yield no records at all. The row is
  recorded as 7 because that is the closest existing cell, and the mismatch is a defect in the taxonomy,
  not in the observation.
- **Bowling Green may still publish permits somewhere else.** The city permits page carries 29 PDF links
  that were never examined. A monthly PDF report would be a different bucket and a different extraction
  problem. This is a lead, not a finding.
- **St. Louis's parcel step was not walked.** The probe established that an address returns parcels rather
  than permits; it did not follow a parcel through to a permit list, so "records exist behind two hops" is
  inferred from the portal's own framing and not demonstrated.
- **`confirmed` is not uniform.** McMinnville's empty-criteria query returned a result set but no records
  were ever pulled from it — enumerable is confirmed, extractable is not. Clark County and St. Johns have
  both.
- **23 of 28 rows remain provisional** and ADR-0005's rule still binds: the metric may fire the gate but
  may not clear it. 69.5% is a lower bound in the same sense 73.1% was, and for the same reason — reading
  a form can only under-classify.
- **The sample is still the Spike A 28**, and five of the seven sources actually pulled in step 1 are not
  in it. The gate denominator and the extraction corpus overlap in exactly two offices.
- **Nothing here re-measures units.** The unit weights come from the frame and are BPS's numbers, carried
  unchanged.
