# Step 1: St. Johns County FL — the first reconciliation figure from the HTML-adapter path

Date:      2026-09-20
Produced:  `spikes/step1_stjohns_run.py` (pull), `spikes/step1_rebuild.py` (replay),
           `spikes/step1_oracle_add.py` (oracle extension), `spikes/step1_reconcile.py` (comparison)
Inputs:    `data/step1/manifest.csv` (43 St. Johns rows, 33 `ok`, 10 `rejected`),
           `data/raw/bps/` (24 months x 4 regions of BPS place files),
           `data/spike_a/classification.csv` (28 rows)
Outputs:   `data/step1/records/stjohns.jsonl` (3,872 records),
           `data/step1/reconciliation.csv` (12 rows), `data/step1/pull_summary.json`
Status:    Current
Cost:      **$0 inference.** 28 HTTP requests in the production run (43 lifetime including probes),
           no model calls.

## Question

Spike B produced a reconciliation figure from five **open-data** jurisdictions. Nothing had ever produced
one from the **crawled HTML** path, which is the path the entire coverage argument depends on — bucket 1
is 0.90% of offices, so almost every office this project claims to reach must be reached by crawling a
portal, not by calling an API.

Two questions, and the second is the load-bearing one:

1. Can an HTML adapter produce a reconciliation number at all?
2. What does it cost per record, against the one HTML adapter that already exists (Accela / Clark County)?

## Why St. Johns, and not Clark County

Clark County cannot answer question 1, and that is a property of the portal rather than of the adapter.
It publishes no unit count on any page reachable without a detail fetch, its index date is the record's
*opened* date rather than its issue date, and its Application Specific Info carries no dwelling-unit field
at all. The drift alarm blocks it and is right to.

St. Johns publishes a per-record **Property Use code** and an explicit **Issue Dt** on the index page
itself. For the classes this county issues in volume, the code names the count.

## Method

**The county publishes its own code legend, for zero requests.** The search form's `ddPU` dropdown renders
all **69** Property Use codes with their labels. That is the county stating what its own codes mean, which
is strictly better evidence than keyword-matching a description field, and it is why this adapter needs no
`STRUCTURE_KEYWORDS` pass at all.

**The code space is BPS-identical only in the 101–105 block.** This corrects a claim made earlier in the
session that `PropUse` *is* the Census class-of-construction code set. It is not:

| code | St. Johns label | BPS meaning | same? |
|---|---|---|---|
| 101 | `1 SINGLE FAMILY(DETACHED).` | 1-unit detached | yes |
| 102 | `1 SINGLE FAMILY (ATTACHED)` | 1-unit attached | yes |
| 103 | `2 FAMILIES` | two-family | yes |
| 104 | `3 & 4 FAMILIES.` | three-four family | yes |
| 105 | `5 OR MORE FAMILIES` | five-plus | yes |
| 435 | **RESIDENTIAL ROOF** | residential garages/carports | **no** |
| 438 | garages | — | diverges |
| 329 | swimming pool | — | local |

Reading the whole space as BPS would have filed **273 roofing permits as garages** and **91 pools as new
buildings**. Only 101–105 are used for the BPS join; everything above is classified from the county's own
label and never mapped to a BPS column.

**Three exclusions come from the legend, each of which would otherwise inflate the count.**

- `700` mobile / manufactured home — outside the Census building permit survey by definition.
- `660` / `665` completion records — a completion is not an issuance; counting them double-counts every
  finished house.
- `328D` accessory dwelling unit — the code does not determine whether the unit is new or an alteration of
  an existing structure, so it is excluded rather than guessed in either direction.

**Windows are weekly, and the width is measured rather than chosen.** The portal caps a result set near
500 rows and announces the cap in the page body. Two sampled weeks ran 245 and 277 rows, so a month would
be roughly 1,100 and would truncate. A week sits inside the cap with headroom; `pull_window` bisects any
window that still returns truncated, and **raises** if a single unsplittable day is still truncated — the
alternative is a known-incomplete day that looks exactly like a complete one downstream. Windows are
clipped to the month so no record is pulled under a month it does not belong to.

**Units are implied, not read.** The county states no unit count anywhere. `implied_by_structure_code`
(`permits/emit.py`) derives one from the published class under four gates: the field must be a controlled
vocabulary, the work class must be `NEW`, the structure rule must be one of four determinate rules, and
the class must be one of the three whose name contains a number — 101→1, 102→1, 103→2. **104 and 105 are
refused**, because "three OR four" and "five or more" name no number. The implication runs *after*
refinement, so it can never feed the classification that produced it.

## Result

**3,627 records in 28 requests across 14 weekly windows. Zero truncations, zero bisections, zero unmapped
codes.** Null rates: `permit_kind` 0%, `work_class` 0%, `date_issued` 0%.

### Reconciliation against BPS

| month | ours | BPS | \|err\| | low-density \|err\| | BPS `Source` |
|---|---|---|---|---|---|
| 2026-01 | 194 | 192 | **1.0%** | 1.0% | 4 |
| 2026-02 | 259 | 248 | **4.4%** | 4.4% | 4 |
| 2026-03 | 256 | 246 | **4.1%** | 4.1% | 4 |

All three months carry `Source = 4` — a real report, not imputation. Median low-density error **4.1%**,
**marked qualified**: every countable unit is implied, so the comparison tests the implication rule itself
and may not be quoted as a measured extraction figure. It sits **beside** the headline median, never
inside it.

The nine pre-existing open-data jurisdiction-months are unchanged — median low-density error **3.0%**.

**There is no 5+ figure.** The county issued no 105 permits in the quarter, so `u5p` is empty on our side
and the column reports `n/a` rather than 0% — an absence, not an agreement.

### Cost per record, against the only other HTML adapter

Index pages only, so the comparison is like for like:

| | St. Johns (WATS/.NET) | Clark County (Accela) | ratio |
|---|---|---|---|
| index pages | 14 | 57 | |
| index bytes | 2.71 MB | 37.48 MB | |
| records | 3,627 | 531 | |
| **KB per record** | **0.76** | **72.3** | **95x** |
| **records per index page** | **259** | **9.3** | **28x** |

All-in, including the form `GET` each window needs for fresh ViewState, St. Johns is **1.06 KB/record** and
**129.5 records per request**. A figure of "54.6 KB/record, 10 records/request" quoted for Clark earlier in
the session was computed against a different denominator; **72.3 KB/record and 9.3 records per index page**
are the numbers the manifest supports. The direction is unchanged.

**This is a portal property, not a platform property.** Accela renders a heavyweight ASP.NET shell around
ten records; WATS renders a bare `GridView` of 259. A second Accela tenancy would likely look like Clark
and a second WATS tenancy like St. Johns, but neither is measured here.

### The bucket reclassification

Spike A classified St. Johns as **bucket 4** — *search-only, needs a known address/parcel/permit number* —
from the rendered search form. The pull demonstrates otherwise: a date range alone returns the complete
set, the cap is announced, and partitioning stays under it. That is the bucket-3 definition. Recomputed
over the same 28-office sample with bucket 0 excluded from the denominator (n = 27, 12,931 units):

| aggregate | before (count% / unit%) | after (count% / unit%) |
|---|---|---|
| Enumerable (1–3) | 7.4% / **28.5%** | 11.1% / **56.7%** |
| Acquirable with work (4–5) | 14.8% / 44.6% | 11.1% / 16.4% |
| Reachable (1–5) — the gate metric | 22.2% / **73.1%** | 22.2% / **73.1%** |
| bucket 3 | 2 offices / 28.5% | 3 offices / **56.7%** |
| bucket 4 | 3 offices / 33.9% | 2 offices / **5.8%** |
| **Enumerable without bucket 4 (1–3 + 5)** | 11.1% / **39.2%** | 14.8% / **67.3%** |

**The gate metric itself does not move** — a row travelling from 4 to 3 stays inside "reachable". What
moves is the **fallback floor**: DESIGN.md's revised gate names 39.2% as what reachability collapses to if
bucket-4 partitioning fails, and 39.2% is below the 50% halting line. That floor is now **67.3%**, above
the line. The stated bucket-4 dependency is discharged.

### Four defects found, each of which would otherwise have shipped silently

1. **`emit.norm_date` sliced a fixed width.** St. Johns renders `3/2/2026 11:06:49 PM` — single-digit month
   and day, with a time. The width-based slice handed `strptime` the string `3/2/2026 1`, which fails every
   format, so **100% of `date_issued` came back `None`** while the adapter looked like it was working.
   Fixed by trying the whitespace-delimited first token before the width slice; regression-tested across 11
   inputs including epoch millis, ISO, `Mar 5, 2026`, junk and `None`. This is shared code and would have
   silently nulled any M/D/YYYY source.
2. **The replay ingested a truncated page.** `step1_rebuild.py` replayed the 500-row control page from the
   earlier probe — an arbitrary slice belonging to no window — inflating `u1` from 751 to 866. The manifest
   verdict on that page is `ok`, and correctly so: the *fetch* succeeded. Only an adapter can read a
   "Maximum record retrieved" banner, so both adapters now expose `page_is_complete(html)` and the replay
   skips incomplete pages. Accela's returns `True` unconditionally: its `100+` is a display cap, not a
   result cap, and conflating the two would discard good pages.
3. **The reconciler skipped every source not declared in `permits.sources`.** It iterated a hardcoded list,
   so Clark County — the one jurisdiction that failed loudest — was invisible in the report that decides
   what may be quoted, and St. Johns would have been too. It now enumerates `pull_summary.json`, which
   every run script already writes with D3 identity and a label.
4. **A D3 identity error carried from a probe artifact**, below.

### The D3 identity error

The adapter inherited `bps_id = "633000"` from the hardcoded key in Spike A's portal probe. `12|633000` is
**Okeechobee County FL**: population 36,635, `units_12mo = 0`, **0 of 24 months reported**. St. Johns is
`12|803000`: population 255,059, 3,637 units/12mo, 23 of 24 months reported.

`data/spike_a/classification.csv` carried the correct `803000` throughout, so the reachability arithmetic
above was never corrupted — only the three Spike A probe JSONs and the adapter built from them. Had the
wrong key survived to the join, the reconciliation would have found **no oracle row at all** and reported
nothing, which is the benign failure; the malign version is a wrong key that *does* find a row.

## What this establishes

- **The HTML-adapter path produces a reconciliation figure.** 1.0% / 4.4% / 4.1%, median low-density
  **4.1%**, qualified. Previously this was true only of the open-data path.
- **The "one 101 permit = one dwelling" implication holds for this county to within ~4%** over three
  months. That is the first test the rule has had.
- **A third platform went through the shared emit interface unchanged**, which is the first real test of
  §9 obligation 1. The interface needed one new `UNIT_SOURCES` value and no schema change.
- **Adaptive date partitioning under an announced result cap works**, at 0.76 KB and 1/130th of a request
  per record. This is the bucket-4 critical-path algorithm, run in production for the first time.
- **St. Johns is bucket 3, not bucket 4**, and the gate's fallback floor is 67.3% rather than 39.2%.

## What this does not establish

- **It is not a measured unit count.** Every countable unit is implied from a structure class. A
  jurisdiction whose entire unit total is implied has not been *measured* against BPS; it has been checked
  for *consistency with* BPS. The figure is real, and it is not the same kind of object as Seattle's 3.0%.
- **It does not establish that the implication is safe in general.** `IMPLIED_UNITS` assumes one permit
  covers one building. A single permit for ten detached houses is ten units and ten 101 structures, and
  implying 1 undercounts it tenfold. St. Johns is a low-rise county where that is evidently rare; a
  production-builder market may not be.
- **The 4.1% is not extraction error alone.** Ours is a count of what the county's public portal shows;
  BPS is what the county mailed to the Census Bureau. They share a taxonomy, not a measurement. Month
  boundary lag, permits the county did not report, and multi-building permits all live inside that 4.1%
  and are not separated here.
- **n = 3 months, one county, one quarter.** No seasonality, no multi-year drift, and no 5+ figure at all.
- **It does not establish that bucket-4 portals are enumerable.** St. Johns was never a hard bucket-4
  case — it was *misfiled*, and the pull proved the filing wrong rather than proving a capability against a
  portal that genuinely demands a known address. The two remaining bucket-4 rows (749 units, 5.8%) are
  untested, and the honest reading is that the fallback floor rose because a row moved, not because the
  hard case was cracked.
- **The gate arithmetic is fragile at this n.** One row of 28 carries 28% of sample units. A 39.2 → 67.3
  swing from a single reclassification is not a robust statistic; it is a demonstration that a
  unit-weighted percentage over 28 offices cannot carry a halting decision by itself.
- **The byte economics are one portal's**, not the platform's, and not a national projection.
- **Nothing here validates the county's legend above code 105.** Those codes are classified from the
  county's own labels and never joined to BPS, so an error there would not surface in this comparison.
