# Tier-2 rerun: classifying at the level that actually issues the permit

Date:      2026-09-20
Produced:  `spikes/spike_a_tier2_rerun.py`, `spike_a_tier2_yakima.py`,
           `spike_a_tier2_yakima2.py`, `spike_a_tier2_final.py`,
           `spike_a_tier2_report.py`
Inputs:    `data/spike_a/classification.csv` (28 rows, key columns repaired - see
           Corrections); `data/spike_a/sample.csv` (28 rows, seed 20260920)
Outputs:   `data/spike_a/tier2_reclassification.csv` (8 rows),
           `tier2_rerun.json`, `tier2_yakima.json`, `tier2_yakima2.json`,
           `tier2_final.json`, `html_tier2/` (17 files)
Status:    Current. Supersedes the tier-2 figures and the tier-2 caveat in
           [2026-09-20 Spike A](2026-09-20-spike-a-portal-enumerability.md);
           that report stands for everything else it measured.
Cost:      $0 inference. Scripted HTTP plus hand research; no model calls.

## Question

Spike A classified tier-2 places at the BPS *place* level and recorded a
place-level miss as bucket 6. Because small places often contract permitting out
or leave it to the county, that method could only bias the deciding figure
downward. Does the tier-2 count-weighted figure of 0% survive being measured at
the body that actually issues the permit?

## Method

For each of the 8 tier-2 rows, the issuing authority was established by hand
(web research, recorded per row in `tier2_reclassification.csv`), then that
authority's own pages were probed with the Spike A politeness settings - one
request at a time, 1.5s apart, identified User-Agent, all HTML saved.

Candidate levels considered for every row: the place itself, the parent county
or borough, the parent town, a contracted private code-enforcement firm, and the
state. A bucket was only reassigned on evidence from the issuing body's own
pages.

One row justified a deeper probe. Wapato WA was the single tier-2 place whose
county runs an enumerable portal (Yakima County, Accela), so it was the only
row that could plausibly flip, and it got a direct test.

**Detection correction applied mid-run.** The Spike A no-result detector matched
against raw HTML, and Accela ships `Please enter a key word with more than 2
characters.` as a **JavaScript string constant on every page, including pages
that returned 100+ records**. It reported "no results" on a successful search.
The detector now strips `<script>`/`<style>` first and treats a rendered result
list as decisive (`spikes/spike_a_query_probe.py`, `strip_scripts`). Both
Yakima result pages were re-scored after the fix.

## Result

**Where tier-2 places actually issue, n=8:**

| Issuing level | n | places |
|---|---|---|
| the place itself | 4 | Wapato, Brownville, Kotzebue, Garden City |
| place + private contractor | 2 | Ahnapee (Beining Building Inspection), Amador City (WGA Inc) |
| parent town | 1 | Dresden village -> Town of Torrey |
| **nobody - no permit is issued** | **1** | **Eastbrook** |
| the county | **0** | - |

**Bucket changes: one of eight.** Eastbrook ME moves from bucket 6 to a new
bucket 0. Every other row holds its bucket at the corrected level.

| Weighting | Before | After |
|---|---|---|
| Unit-weighted, whole sample | 28.5% | **28.5%** |
| Count-weighted, whole sample | 7.1% | **7.1%** |
| **Count-weighted, tier 2 - drives the decision** | 0.0% (0 of 8) | **0.0% (0 of 8)** |

**The stratum the gate keys on is worth 0.05% of the sample's units** - 6 units
of 12,932, while being 28.6% of its offices.

## What this establishes

**1. The 0% survives, and the objection raised against it does not.** Spike A
argued the tier-2 figure was biased downward by measuring at the wrong level.
Measured at the right level it is unchanged. The specific worked example used to
support that objection is now disproven: **Amador County's building department
serves the unincorporated county, so it does not cover Amador City.**

**2. No tier-2 place in the sample is served by its county, and there is a
structural reason.** County permit portals are scoped to unincorporated area,
and BPS places are incorporated - the two partition the same territory. Weld
County states it in its own page metadata: *"Search various types of permits on
parcels located in unincorporated Weld County."* The county-picks-up-the-slack
hypothesis is not merely unsupported here; it is the wrong shape.

**3. Yakima County's Accela does not reach inside Wapato.** A `city=WAPATO`
search returns `100+ Record results`, but all 10 first-page records are rural
addresses - 67831 US Highway 97, 8191 Fort Rd, 3600 Campbell Rd, 3451 S Wapato
Rd - i.e. unincorporated parcels carrying a Wapato ZIP. The City of Wapato
publishes its own Building Permit application PDF and takes permits at City
Hall.

**4. Accela's acceptance of empty search criteria is per-tenancy, not universal.**
Yakima renders an address-shaped general search with **no date fields at all**
and returns nothing for empty criteria, where Clark County NV and Oregon accept
empty criteria and return records. Two consequences: the Spike A claim that
"every Accela agency is a bucket-3 target" is **too strong and is narrowed here**
to "Accela tenancies are commonly bucket 3, and the form must be read rather than
assumed"; and an Accela extractor cannot hard-code field names across tenancies.

**5. At this size the issuing system is often a person, not software.** Ahnapee's
town page directs permit applicants to `ahnapeezoning@gmail.com`, with
inspections by a one-person private firm. Amador City's inspector is reachable
at a private consultancy's address. There is no portal to find because there is
no system.

**6. A new bucket 0 is needed: no permit is issued at all.** Maine requires MUBEC
adoption and enforcement only at 4,000+ population; roughly 370 of Maine's 488
municipalities fall below it. Eastbrook (pop 416) publishes a town website
containing **zero occurrences of "permit", "code" or "build"**. BPS carries 1
imputed unit for it. That unit was never a permit document anywhere, so it is
not reachable by any crawler at any cost. This is categorically different from
bucket 6, where a record exists on paper in a filing cabinet.

## What this does not establish

**That the gate should now fire.** The threshold `buckets 1-3 < 30% -> wrong
domain` is tripped on a correctly-measured number, but the number does not mean
what the threshold assumes. The rule was written to catch "the permit data is
unreachable". What was found is that tier-2 permits are issued by micro-entities
with no software, and sometimes not issued at all - while that entire stratum
carries 0.05% of the sample's units. The threshold is measuring reachability and
treating it as value. **Recommendation: revise the threshold before consulting
it, rather than acting on it or quietly ignoring it.**

**That Wapato is certainly outside the county Accela.** The evidence is strong
but circumstantial: 10 of 10 first-page addresses are rural, and the city
publishes its own application. It is not parcel-proven. A definitive answer needs
the addresses tested against the city-limits boundary, or the Yakima County
interlocal agreement list read directly. If Wapato is in fact county-served the
tier-2 figure becomes 1 of 8 (12.5%), which still does not clear 30%.

**That 0 of 8 is 0%.** Unchanged from the first report: the rule-of-three 95%
upper bound is about 38%, which still spans the threshold. Re-measuring at the
right level removed a *bias*; it did not shrink the *interval*. A tier-2 figure
that can be planned against needs a materially larger sample.

**That bucket 0 has been measured.** One instance was found and the Maine
statutory basis is documented, but the frame-wide share of places that issue no
permit at all is unknown. It is plausibly large - Maine alone has ~370
sub-threshold municipalities - and it bears directly on what national coverage
can ever mean. It has not been quantified here.

**Nothing about tier 1.** Only tier-2 rows were re-examined. Tier-1 rows keep
their original place-level classification, and the same many-to-one concern
applies to them untested.

**That the two unresolved rows were retried.** Lafayette Parish LA and Galloway
Township NJ are tier-1 and were left as recorded.

## Corrections

**`data/spike_a/classification.csv` had a wrong `bps_id` on all 28 rows.** Place
names and unit counts were correct and every published figure is unaffected, but
the identity key did not match `sample.csv`, so the file could not be joined to
the frame - the exact failure `(state_fips, bps_id)` identity exists to prevent.
Repaired from `sample.csv` by place name (28/28 matched, unit counts asserted
equal), and `county` and `state_abbr` added. Backup at `classification.csv.bak`.

## References

- `data/spike_a/tier2_reclassification.csv` - all 8 rows with issuer, level, and basis
- `data/spike_a/html_tier2/` - 17 saved pages
- [2026-09-20 Spike A](2026-09-20-spike-a-portal-enumerability.md) - the report this revises
- [ADR-0003](../adr/0003-jurisdiction-identity-is-bps-scoped.md) - why the issuing
  body is not the identity, even when it is a county, a parent town or a private firm
