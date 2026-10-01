# Spike A: portal enumerability across 28 stratified jurisdictions

Date:      2026-09-20
Produced:  `spikes/spike_a_sample.py`, `spike_a_probe.py`, `spike_a_verify.py`,
           `spike_a_portal_probe.py`, `spike_a_query_probe.py`,
           `spike_a_depth_probe.py`, `spike_a_final_probe.py`, `spike_a_report.py`
Inputs:    `data/frame/bps_frame.csv` (20,069 rows, built 2026-09-19);
           `data/frame/bucket1_candidates.csv` (183 rows, excluded from the sample)
Outputs:   `data/spike_a/sample.csv` (28 rows), `classification.csv` (28 rows),
           `probe.json`, `portal_probe.json`, `query_probe.json`,
           `depth_probe.json`, `final_probe.json`, `html/` (77 files, 8.9 MB)
Status:    Current, EXCEPT the tier-2 figures and the tier-2 caveat below, which are
           superseded by 2026-09-20-tier2-issuing-level-rerun.md. That rerun CONFIRMS
           the 0% at the correct level and DISPROVES this report's Amador County
           example. Finding 1 below is also narrowed there: empty-criteria search is
           a per-tenancy Accela setting, not a property of the vendor.
Cost:      $0 inference. Every step is scripted HTTP; no model calls.

## Question

Can the permit universe be enumerated by crawling, or must it be enumerated by querying? Not pass/fail -
it selects which hard problem is on the critical path.

## Method

28 jurisdictions drawn from the 19,886 offices the catalog sweep did **not** resolve, stratified 10 top
unit-volume decile / 10 mid-volume tier-1 / 8 tier-2, seed fixed at 20260920. The draw landed 28 states
and all four Census regions.

Portal location ran in two stages. A URL-pattern probe guessed hostnames from place names, then every
hit was scored against attributes a name cannot fake - a `.gov`/`.<st>.us` TLD, the correct state
appearing on the page, and negative markers for parking pages and wrong-state matches. **The pattern
probe had a 75% false-positive rate** (21 of 28 rejected), reproducing the Marina/Marin failure from the
catalog sweep in a new form: `Bowling Green KY` matched a Virginia town, `Brazil IN` matched the country,
`Amador City CA` matched a person's homepage. The 21 rejects were then located by web search.

Classification used the portal's own behaviour, not its marketing. The decisive test is the bucket-3
test from the protocol - submit the broadest query the portal accepts and see whether it returns a result
set. For Accela this meant a proper ASP.NET WebForms POST carrying harvested `__VIEWSTATE`, because
Accela is the dominant vendor and guessing its behaviour would have been the weakest link in the spike.

Politeness: one request at a time, 1-2s apart, an identified User-Agent, `robots.txt` fetched per host.
All HTML saved (77 files, 8.9 MB) - this is Spike C's input.

## Result

| bkt | meaning | n | count% | unit% |
|---|---|---|---|---|
| 3 | search-only **but** broad query returns everything | 2 | 7.1% | 28.5% |
| 4 | search-only, needs a known address/parcel/permit no. | 3 | 10.7% | 33.9% |
| 5 | JS-gated, no endpoint without a browser | 1 | 3.6% | 10.6% |
| 6 | no online portal found | 16 | 57.1% | 10.2% |
| **7** | **portal exists but requires registration/login** | **4** | **14.3%** | **10.9%** |
| - | unresolved, not guessed | 2 | 7.1% | 5.9% |

**The three required weightings, buckets 1-3 = enumerable:**

| Weighting | Enumerable |
|---|---|
| Unit-weighted, whole sample | **28.5%** (3,689 of 12,932 units) |
| Count-weighted, whole sample | **7.1%** (2 of 28) |
| **Count-weighted, tier 2 only - drives the decision** | **0.0%** (0 of 8) |
| Count-weighted, tier 1 only | 10.0% (2 of 20) |

## What this establishes

**1. Accela accepts entirely empty search criteria and returns records.** Confirmed mechanically at two
independent instances - Clark County NV and Oregon's statewide portal - both returning
`100+ Record results matching your search results` with real record identifiers (`BD25-05074`). Accela is
the largest permitting vendor in US local government, and this makes every Accela agency a bucket-3
target rather than the bucket-4 target it appears to be. The `100+` is a display cap, so enumeration
still needs date partitioning, which is the adaptive-query-partitioning problem the design anticipated.

**2. Statewide vendor instances are a real leverage point.** McMinnville is served by
`aca-oregon.accela.com`, one Accela tenancy covering many Oregon jurisdictions. One integration, many
offices. This mirrors the 18 statewide portals found in the catalog sweep and is the strongest
cost-per-office lever the project has found so far.

**3. The tier-tension thesis is confirmed, and the three-way reporting rule earned its place.** The same
sample reads 28.5% enumerable unit-weighted and 0% enumerable on tier-2 count. A single headline number
would have been actively misleading in whichever direction it was chosen. This is the clearest empirical
vindication of a design decision made before the data existed.

**4. The 6-bucket taxonomy has a missing cell.** 4 of 28 portals (14%) exist and are neither JS-gated nor
absent - they are behind registration or login (Avolve ProjectDox, SagesGov, CommunityCore, iWorQ). This
is proposed as **bucket 7**, because the operational consequence differs from both neighbours: unlike
bucket 5 a browser does not help, and unlike bucket 6 the data demonstrably exists in a structured system.

**5. Small jurisdictions frequently contract permitting out.** Ontelaunee Township PA issues permits
through `kraftcodeservices.com`, a private code-enforcement firm. Amador City CA staffs its building
office nine hours a week. The permit-issuing *function* does not always sit where the BPS office sits.

## What this does not establish

**That permits is the wrong domain, despite the threshold tripping.** The tier-2 count-weighted figure of
0% crosses the `buckets 1-3 < 30% -> revisit procurement` line in the protocol. It should not be acted on,
for four reasons, the first of which is serious:

- **The classification may be measuring at the wrong jurisdictional level, and the bias runs one way.**
  For tier-2 places the permit-issuing function is often the county's or a contractor's, and this spike
  looked for a portal at the *place* level. Amador City CA was classified bucket 6, but Amador County
  runs a building permit portal that may well cover it. This is the many-to-one structural finding from
  the catalog sweep reappearing, and it biases the tier-2 figure **downward** - precisely the figure the
  decision rests on. This must be re-run at the correct level before the number is trusted.
- **A 0-of-8 result is not 0%.** By the rule of three the 95% upper bound on 0/8 is roughly 37%. The
  honest statement is "under ~37%", which spans the 30% threshold rather than clearing it.
- **The portal-location method has a demonstrated miss rate.** Galloway Township NJ, population 35,487,
  was not located at all within the time budget. A method that can miss a township of that size can miss
  portals elsewhere, and every miss is recorded as bucket 6.
- **Some bucket-6 and bucket-7 rows may be access-gating rather than absence.** iWorQ returned 403 to an
  identified research client; Kotzebue and Eastbrook returned 403 on pages that exist. "We could not
  reach it" and "it is not there" are different findings and are not fully separated here.

**Nothing about buckets 1 and 2.** No jurisdiction in this sample landed in either, but the sample
deliberately excluded the 183 offices already known to be bucket 1, so this is by construction and not a
measurement.

**No usable frame-wide percentage.** Reconstructing unconditionally gives ~8.0% of offices enumerable,
but at +/-18pp sampling error the interval is 0.9% to 25.8%. That is too wide to plan against and should
not be quoted.

**Nothing about result caps beyond Accela's `100+` display limit.** True cap depth, pagination behaviour
at depth, and index-versus-detail field availability were not measured, so the fetch-amplification factor
driving the cost model in `docs/design/history.md` §6 remains unmeasured.

## Recommendation

> **[2026-09-20] This recommendation was carried out.** The rerun found the 0%
> unchanged, no tier-2 place served by its county, and one place that issues no
> permit at all - and it disproves the Amador County example used above. See
> [the tier-2 rerun](2026-09-20-tier2-issuing-level-rerun.md).

**Do not treat the threshold as tripped. Re-run tier-2 classification at the jurisdictional level that
actually issues the permits** - for each tier-2 place, check the parent county and any contracted code
-enforcement firm before recording bucket 6. That is roughly half a day, costs nothing, and either
overturns the 0% or confirms it with the one systematic bias removed. The decision gate should not be
approached on the current number.

On the critical path, the evidence so far points at **adaptive query partitioning rather than template
induction**: buckets 4 and 3-with-a-cap together are 17.8% of the sample by count and 62.4% by units, and
both need query partitioning rather than page templates. Template induction is not yet ruled in or out -
Spike C, which runs over the 77 HTML files saved here at no cost, is the next cheapest thing to do.

## References

- `data/spike_a/classification.csv` - all 28 rows with vendor, confidence and the basis for each call
- `data/spike_a/html/` - 77 saved pages, the input to Spike C
- `docs/design/history.md` Spike A protocol, bucket taxonomy, decision thresholds
- [ADR-0001](../adr/0001-source-office-link-is-an-evidence-bearing-relation.md) - why the two
  unresolved rows are recorded rather than guessed
