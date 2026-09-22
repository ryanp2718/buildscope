# Measurements A and B: index/detail template collision, and Accela cohort size

Date:      2026-09-20
Produced:  `scripts/measure_fetch.py` (now `permits/capture.py`), `spikes/measure_a_run.py`,
           `spikes/measure_b_accela.py`,
           `measure_import.py`, `measure_reverify.py`, `measure_analyze.py`
Inputs:    `docs/evidence/2026-09-20-measurement-ab-preregistration.md` (rules fixed
           before the data existed), `data/spike_a/html/` (imported control pages)
Outputs:   `data/measure/manifest.csv` (44 rows, append-only),
           `data/measure/pages/` (37 pages), `data/measure/analysis.json`
Status:    Current
Cost:      $0 inference. 42 HTTP requests (36 pages + 6 robots.txt) against a
           pre-registered ceiling of 60. No model calls.

## Question

[Spike C](2026-09-20-spike-c-template-collision.md) measured fingerprints ÷ jurisdictions = 1.00 and
killed D8 as stated - but over municipal home pages and portal landing pages, with **zero permit detail
pages** and five index pages across three jurisdictions. The page types an extractor actually sees had
never been fingerprinted. Two questions followed:

- **A.** Do permit **index** and **detail** pages collapse across jurisdictions, even though home pages
  do not?
- **B.** Accela's Clark County NV / Yakima County WA pair scored 0.766, so cohorts exist. **How big is a
  cohort?** That number carries most of the amortization estimate.

All decision rules, page types and controls were fixed in the
[pre-registration](2026-09-20-measurement-ab-preregistration.md) before any page was fetched.

## Corpus and provenance

37 distinct pages, **30 usable** (`verdict = ok`): 16 `T-SEARCH`, 8 `T-INDEX`, 6 `T-DETAIL`. Seven
excluded, each with a recorded reason: four Accela tenancies that have no `Building` module at the probed
path, one 403, one Yakima empty-criteria query that legitimately returns nothing, and one non-Accela page
that turned out to be a login screen.

**Every page carries its verdict in the manifest, written in the same operation as the bytes** - the D1
constraint Spike C surfaced, implemented at capture rather than as a downstream filter. The analysis
reads the manifest and never the directory.

**The mechanism was exercised twice on the first run, which is the useful part:**

1. The capture verifier rejected all three index POSTs. Accela had answered with *"Potential cross-site
   request forgery attacks. The Referer and Origin headers are missing"* and a 58KB stub. Without a
   capture-time verdict those stubs would have been fingerprinted as result pages.
2. The verifier then **false-rejected a real page**: `oregon_detail2_MARION_CO` is permit
   555-26-006952-ELEC, a genuine Residential Electrical record. It was thrown out because the rejection
   test matched `Showing 1-3 of 3`, which a real detail page emits from its own inspections sub-grid -
   the same failure family as Accela's `Please enter a key word...` JavaScript constant, a discriminator
   that fires on something every page has.

The correction was **appended, not edited**: `measure_reverify.py` re-read the stored bytes under the
narrowed rule and wrote a new row. The manifest therefore contains 44 rows for 37 pages, and the first
judgement, the corrected judgement, and the reason for the change are all still on the record.

## Controls

Run before any finding was believed, with expectations fixed in advance.

| ID | Control | n | Result | Pre-registered expectation |
|---|---|---|---|---|
| **C1** | Same portal, two queries, `T-INDEX` | 7 | **0.984 - 1.000** | >= 0.80 - met |
| **C2** | Same portal, two permits, `T-DETAIL` | 3 | **0.863 - 0.979** | >= 0.80 - met |
| **C3** | Same portal, `T-INDEX` vs `T-DETAIL` | 16 | **0.183 - 0.200** | LOW - met |
| **C4** | Cross-vendor, same type | 0 | **NOT RUN** | - |
| **C5** | Cross-jurisdiction baseline | 395 | **p95 = 0.802** | ~0.08 - **FAILED** |

**C4 was not run.** The corpus holds no non-Accela result-index page. Spike A's only non-Accela
candidate, St Johns County's WATS .NET portal, turns out to be a login/landing page (`txtLogName`,
`txtPassword`, `btnLogin`) rather than a search form, and extracting an index from it means first solving
a bucket-4 portal. Reported as not run rather than quietly substituted with something weaker.

**C5 failed its pre-registered expectation and the reason matters.** It was expected near p95 0.08 and
came in at 0.802 - an order of magnitude high. The cause is that this corpus is **mono-vendor by
construction**: bucket 3 in the Spike A sample is entirely Accela, so "cross-jurisdiction pairs" here are
overwhelmingly *same-vendor* pairs, which is the quantity under test. Using C5 as the negative control
would have been circular and would have mechanically returned "no collapse" for everything. The
heterogeneous baseline from Spike C (p95 **0.077** over 4,782 pairs across 25 unrelated jurisdictions) is
used instead, and both are reported. **This is a limitation of the sample, not a rescue of the result** -
see below.

## Result A: index and detail pages

**The distributions are bimodal, and a median is the wrong summary of them.** Reporting only the median
would have shown 0.208 and 0.162 and concealed the actual structure.

| Page type | low mode | high mode | gap | high-mode pairs |
|---|---|---|---|---|
| `T-INDEX` | n=15, 0.150 - 0.213 | **n=6, 0.752 - 0.766** | 0.539 | Clark County NV ~ Yakima County WA |
| `T-DETAIL` | n=8, 0.124 - 0.167 | **n=4, 0.737 - 0.768** | 0.570 | Clark County NV ~ Yakima County WA |

Against the heterogeneous baseline of 0.077 this is **partial collapse** on the pre-registered rule, for
both page types. But the bimodality says something sharper than "partial": with three tenancies there are
three jurisdiction pairs, and **one of the three collapses at ~0.75 while the other two sit near 0.15.**
There is no gradient. The cohort boundary is a cliff.

**Detail pages behave exactly like index pages.** Same cohort boundary, same cliff, same members. The
pre-registration said detail governs if the two disagree; they do not disagree.

### Two findings that were not the question

**1. Index and detail are different templates - C3 is 0.19, not 0.9.** Within a single portal, the result
grid and the record page share almost no structure. This is the confound check, and it passes, but it
also means **each tenancy needs at least two synthesized extractors, not one.** No cost estimate in
`DESIGN.md` has ever counted that factor. It is a straight multiplier on synthesis cost.

**2. Cross-jurisdiction template reuse is real - inside a statewide tenancy.** The weakest C2 pair,
0.863, is `oregon_detail1_TALENT` vs `oregon_detail2_MARION_CO`: two records belonging to **two different
jurisdictions** - the City of Talent and Marion County - served by one Accela tenancy at
`aca-oregon.accela.com/oregon`, rendering the same template. That is a direct measurement of the thing
D8 claimed and Spike C could not find, and it says the **unit of template reuse is the tenancy, not the
vendor and not the jurisdiction.** Spike A's catalog sweep already found 18 statewide portals. This is
the amortization lever, and it is a different lever from the one D8 described.

## Result B: Accela cohort size

16 tenancies, one `T-SEARCH` page each, slugs discovered from public references rather than guessed.

| Threshold | clusters | mean cohort size | cluster sizes |
|---|---|---|---|
| exact hash | 16 | 1.00 | all singletons |
| J >= 0.95 | 16 | **1.00** | all singletons |
| J >= 0.90 | 14 | 1.14 | 2, 2, then singletons |
| J >= 0.80 | 6 | **2.67** | **11**, 1, 1, 1, 1, 1 |
| J >= 0.70 | 2 | **8.00** | 15, 1 |
| J >= 0.60 | 2 | 8.00 | 15, 1 |

The 11-tenancy cohort at J >= 0.80: BOCC, San Antonio TX, Indianapolis IN, ONE, Pima County AZ, Polk
County, Sacramento CA, Walnut Creek CA, Yakima County WA, Santa Barbara city and Santa Barbara County.
Outside it: Salt Lake City, Monterey County, Placer County, Clark County NV, Oregon.

**The single tenancy that never joins anything is Oregon**, at 0.173 - 0.271 against all fifteen others.
It is a statewide multi-jurisdiction tenancy on its own hostname with its own skin - structurally its own
cohort, while internally serving many jurisdictions identically. Both halves of that sentence are
load-bearing.

**The answer to "how big is a cohort" is a curve, not a number, and the curve is the finding.** Spike C's
equivalent curve was **flat at 1.00 from 0.95 down to 0.60** - nothing ever merged at any tolerance.
Accela's fleet is **steep**: 16 -> 14 -> 6 -> 2. That is the difference between *"cohorts do not exist"*
and *"cohorts exist and their boundary depends on how much structural drift an extractor tolerates."*

Which threshold is correct **cannot be settled by structure**. The pre-registered rule said to cluster at
the threshold C1 justifies; C1 is 0.984, which gives cohort size **1.00** and the pre-registered verdict
*"the vendor name buys nothing."* But C1 compares the same page re-rendered with a different query, which
is far tighter than the real question - whether one synthesized extractor survives moving to a sibling
tenancy. **Taken literally, the pre-registered rule returns cohort size 1.00.** Taken at a plausible
working tolerance of 0.80, it returns 2.67. The honest report is both numbers and the reason they differ.

## What this establishes

**1. Spike C's 1.00 does not generalise to the page types that matter.** Home and landing pages never
collapsed at any threshold. Index and detail pages collapse for one tenancy pair in three, at ~0.75, and
form a steep cluster curve across 16 tenancies. **The corpus Spike C ran on was the wrong corpus for the
claim, exactly as its own "what this does not establish" section warned.** Spike C's verdict on D8 *as
stated* still stands - ~20,000 sites do not become a few hundred templates - but its implied "nothing
amortizes anywhere" does not.

**2. The amortization unit is the tenancy.** Two different Oregon jurisdictions share one template at
0.863. Spike A found 18 statewide portals. A cost model keyed on tenancies rather than on offices or on
vendors is the one consistent with everything measured so far.

**3. Each tenancy costs at least two extractors, not one.** C3 = 0.19 between index and detail within the
same portal.

**4. The open question is now well posed, and it is an extraction question, not a structure question.**
"How much structural drift does a synthesized extractor tolerate?" is answerable in step 2 against the
golden set, cheaply, and it converts the cohort curve into a single defensible number. Until then no
amortization multiple should be quoted - the supportable range spans 1.0x to 8.0x depending entirely on a
tolerance nobody has measured.

## What this does not establish

**Any national figure.** 16 Accela tenancies and 3 index/detail tenancies cannot estimate anything over
20,000 offices. No number here may be quoted as a national rate.

**Anything about non-Accela vendors.** Bucket 3 in the Spike A sample is entirely Accela, so this is a
measurement **of Accela**. Tyler EnerGov, CityView, eTRAKiT, CentralSquare and the rest are untouched,
and C4 - the control that would have tested whether index pages merely look alike because they are index
pages - **could not be run at all.** The cross-vendor confound remains open.

**That the cohort boundary means extractor transfer.** Structural similarity is necessary and not
sufficient. Two pages can share a DOM skeleton and label their columns differently. J = 0.766 licenses
*trying* a shared extractor, never asserting one works.

**That the 0.863 statewide result generalises.** It is **one pair, inside one tenancy**. Two jurisdictions
sharing a template in Oregon does not establish that the other 17 statewide portals behave the same way,
and the finding deserves a direct test before any cost model leans on it.

**That the tenancy sample is representative.** Tenancies that are publicly linked and reachable without a
login are the open end of Accela's customer base, and 5 of 18 probed tenancies did not even expose a
`Building` module at the standard path. A cohort size measured over the reachable ones is likely
optimistic.

**That C1 is the right clustering threshold - or that 0.80 is.** This is the central unresolved
parameter and the reason B returns a curve rather than a number.

**Anything about bucket 4, 5, 6 or 7 portals.** The revised gate in `DESIGN.md` section 8 turns on
whether bucket-4 portals can be enumerated by partitioned querying within budget. Neither measurement
here touches that question, and it is now the most decision-relevant unknown in the project.

## References

- [Pre-registration](2026-09-20-measurement-ab-preregistration.md) - page types, controls and decision
  rules, fixed before the data existed
- [Spike C](2026-09-20-spike-c-template-collision.md) - the 1.00 result this qualifies, and the source of
  the heterogeneous 0.077 baseline
- [Spike A](2026-09-20-spike-a-portal-enumerability.md) - the bucket-3 portals and the 18 statewide
  tenancies
- `data/measure/manifest.csv` - append-only provenance log, including the false rejection and its
  correction
- `data/measure/analysis.json` - full pair distributions and cluster memberships
