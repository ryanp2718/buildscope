# Spike C: structural template collision across jurisdictions

Date:      2026-09-20
Produced:  `spikes/spike_c_corpus.py`, `spikes/spike_c_fingerprint.py`,
           `spikes/spike_c_validate.py`
Inputs:    `data/spike_a/html/` + `html_tier2/` (100 saved pages, 13.0 MB),
           `data/spike_a/probe.json` (Spike A verifier verdicts),
           `data/spike_a/classification.csv` (28 rows)
Outputs:   `data/spike_a/spike_c_corpus.csv` (100-row trust manifest),
           `data/spike_a/spike_c_fingerprints.json`
Status:    Current for home and landing pages. QUALIFIED for permit index and
           detail pages by 2026-09-20-measurement-ab-results.md, which measured the
           page types this report could not: they DO collapse across some
           jurisdictions (J 0.74-0.77) and Accela cohort size runs 1.00-8.00
           depending on threshold. The verdict on D8 as stated is unchanged.
Cost:      $0 inference. Offline, stdlib only; no fetching, no model calls.

## Question

D8 claims that keying the extractor cache on DOM structure rather than domain
"collapses the amortization denominator from ~20,000 sites to plausibly a few hundred distinct vendor
templates". Every cost figure in `DESIGN.md` section 6 and the headline amortization ratio in section 5
rest on that sentence, and nothing had tested it. Do jurisdictions actually collapse onto shared
templates?

## Method

Fingerprint per the protocol: normalized DOM skeleton with all text, attribute *values* and ids stripped;
shingle over root-to-leaf tag paths; hash. `<script>`, `<style>` and `<svg>` subtrees are dropped - svg
carries inline geometry that swamps page structure.

Two numbers per corpus. **EXACT** is a sha1 over the sorted unique path set and is brittle by
construction - one extra menu item mints a new fingerprint - so it is a *lower bound* on collapse.
**JACCARD** is single-linkage clustering on path-set overlap at thresholds from 0.95 down to 0.60, which
is what a structure-keyed cache would actually do. The threshold sensitivity is the finding, not noise
around it.

**The corpus was filtered before analysis, and the filter is the first result.** Spike A saved every page
it fetched, including the ones its own verifier rejected - the URL-pattern probe had a 75% false-positive
rate and the rejects were written to disk beside the hits. Of 100 saved pages, **25 were dropped: 15
verifier-rejected pattern hits, 7 non-content pages (Cloudflare interstitials, 403/404), and 3 pages from
jurisdictions Spike A recorded as unresolved.** The dropped set includes an iron castings foundry, a
C-suite media network, a church, a Rod & Gun Club and a realty firm. 75 pages over 25 jurisdictions
remain.

**The instrument was validated before its verdict was believed.** A ratio near 1.00 is either a real
finding or a broken fingerprint, and the headline number cannot tell you which.

| Control | Jaccard |
|---|---|
| Positive - same portal, two different queries (3 pairs) | **0.808 - 0.992** |
| Negative - 4,782 cross-jurisdiction pairs | median **0.036**, p95 **0.077** |

Pages that are the same template score above 0.80; unrelated pages sit near 0.04. The fingerprint
discriminates by roughly an order of magnitude, so a same-vendor pair landing near baseline is a real
absence of collapse rather than an artifact.

## Result

**Fingerprints ÷ jurisdictions, at every clustering threshold tested:**

| Corpus | jurisdictions | exact fps | ratio | ratio at J>=0.60 |
|---|---|---|---|---|
| Municipal websites | 22 | 22 | **1.00** | **1.00** |
| Permit portal landing pages | 23 | 23 | **1.00** | **1.00** |
| Tier-1 sites | 14 | 14 | **1.00** | **1.00** |
| **Tier-2 sites - drives the decision** | **8** | **8** | **1.00** | **1.00** |
| Permit result-index pages | 3 | 3 | 1.00 | 0.67 |

Median cluster size is **1** in every corpus. Nothing merges, even at a permissive 0.60.

**Same-vendor pairs, like-for-like page types:**

| Pair | Jaccard |
|---|---|
| Accela result page: Clark County NV vs **Yakima County WA** | **0.766** |
| Accela result page: Oregon vs Yakima County WA | 0.213 |
| Accela result page: Clark County NV vs Oregon | 0.155 |
| Accela landing page: Clark County NV vs Oregon | 0.258 |
| CivicPlus permits page vs CivicPlus permits page (Mission TX / Story County IA) | 0.255 |

## What this establishes

**1. The D8 claim is false as stated, on the threshold the protocol set in advance.** The rule was
`fingerprints ÷ jurisdictions > 0.8 -> the core technical claim is dead as stated`. The measured value is
**1.00 on tier-2 and 1.00 pooled**, at every threshold down to 0.60. Templates do not collapse across
jurisdictions in this sample. **Step 4 must be re-planned before it is built.**

**2. But vendor cohorts are real, and that is the constructive finding.** Clark County NV and Yakima
County WA score **0.766** - close to the 0.808 positive-control floor, and ten times the 0.077 baseline.
Two Accela tenancies *can* be near-identical. Oregon, also Accela, scores 0.155 and 0.213 against those
two, because it is a statewide multi-jurisdiction tenancy with its own skin. **Structure-keyed caching
works within a vendor-version-configuration cohort and not outside one** - which is precisely the
"vendor-plus-config" replacement the protocol named in advance as the likely fix.

**3. Vendor identity alone is a weak proxy for template identity.** The protocol called same-vendor /
different-fingerprint the deciding cell. Two same-vendor CivicPlus pages of matched type score 0.255:
above baseline, so there *is* a shared-CMS signal, but far below reuse. Knowing a site runs CivicPlus
does not let you reuse an extractor written for another CivicPlus site.

**4. The amortization denominator was the wrong number anyway.** D8 divides across ~20,000 sites, but 15
of 28 sampled jurisdictions have no portal at all and one issues no permit. Only about **36% of the
sample has a portal to template** (buckets 3, 4, 5, 7). The denominator that matters is ~7,000 offices,
not 20,000, and those are the vendor-concentrated ones. The claim is wrong as stated; the operational
picture is less bleak than the raw ratio suggests, but the section 6 cost figures must be re-derived from
the measured cohort structure rather than from "a few hundred templates".

**5. Saved bytes must carry their verdict.** 15 verifier-rejected pages sat in the corpus directory
indistinguishable from good ones, and the first run of this analysis silently included them - a foundry's
website was being fingerprinted as a municipal site. Provenance did not travel with the bytes. This is a
direct constraint on D1: the observation log stores raw bytes immutably, and it must store the
verification verdict alongside them, with folds filtering on it, or every downstream analysis re-admits
rejected data by default.

## What this does not establish

**That templates never collapse.** This is a one-sided test, as the protocol specified. Near-1:1
collision at n=25 is strong evidence *against* collapse; it cannot prove collapse is impossible at scale,
and the Clark/Yakima pair shows cohorts exist. What it kills is the *stated* claim - that ~20,000 sites
reduce to a few hundred templates - not the weaker claim that vendor cohorts amortize.

**Almost nothing about permit index pages specifically, and nothing at all about detail pages.** This is
the significant gap. The protocol asks for index and detail templates fingerprinted separately and warns
that conflating them flatters the result. The corpus holds **5 result-index pages across 3 jurisdictions,
all Accela, and zero detail pages** - Spike A never fetched an individual permit record. The 1.00 headline
therefore rests mainly on *municipal websites and portal landing pages*, which are a proxy for the D8
claim, not the claim itself. A jurisdiction's home page being bespoke says less than its permit result
grid being bespoke would.

**That the 0.766 pair generalises.** One high-scoring pair out of three Accela comparisons is not a
cohort-size estimate. Whether Accela tenancies form two cohorts or fifty is unmeasured, and cohort size
is exactly what the re-derived cost model needs.

**Any national figure.** 25 jurisdictions cannot measure a collapse ratio over 20,000. No number here
should be quoted as a national rate.

**That the filtered-out pages were all genuinely wrong.** The filter trusts Spike A's verifier plus title
heuristics. A correct municipal page with an unlucky title ("...Error...") would be dropped. The manifest
at `data/spike_a/spike_c_corpus.csv` records every decision for audit.

## Recommendation

**Re-plan step 4 before building it, per the threshold.** The evidence does not support synthesis keyed
on pure DOM structure across jurisdictions. It does support **synthesis keyed on vendor + version +
configuration**, with the cohort discovered by clustering rather than assumed - the Clark/Yakima result
is what that looks like when it works.

Two measurements should precede the re-plan, and both are cheap:

1. **Fetch permit result and detail pages from the reachable portals** and re-run this analysis on them.
   This is the test the protocol actually specified, and it is currently unanswered. Roughly 20-40
   requests against portals already identified as bucket 3.
2. **Measure Accela cohort size** across more tenancies. The cost model needs cohort size, and Accela is
   the dominant vendor, so this single number carries most of the amortization estimate.

Until those exist, no amortization ratio should appear in a writeup. The 20-60x range in section 6 is
not supported by anything measured.

## References

- `data/spike_a/spike_c_corpus.csv` - the 100-row trust manifest, with a reason for every drop
- `data/spike_a/spike_c_fingerprints.json` - full cluster distributions at all thresholds
- [Spike A](2026-09-20-spike-a-portal-enumerability.md) - the corpus this ran over, and the 75%
  pattern-probe false-positive rate that made the trust filter necessary
- [Tier-2 rerun](2026-09-20-tier2-issuing-level-rerun.md) - the bucket distribution behind finding 4
- `DESIGN.md` D8, section 5 amortization ratio, section 6 cost model - all three depend on this result
