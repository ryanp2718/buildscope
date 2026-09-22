# Pre-registration: Measurements A and B (permit page types, Accela cohort size)

Date:      2026-09-20
Produced:  written before any page was fetched; `scripts/measure_a_fetch.py`,
           `spikes/measure_b_accela.py`, `spikes/measure_analyze.py`
Inputs:    `data/spike_a/query_probe.json` (bucket-3 portals already identified),
           `data/spike_a/classification.csv`
Outputs:   `data/measure/pages/` + `data/measure/manifest.csv` (bytes with verdicts),
           `data/measure/analysis.json`
Status:    Pre-registered - decision rules below were fixed before the data existed

## Why this exists

[Spike C](2026-09-20-spike-c-template-collision.md) returned 1.00 fingerprints per jurisdiction and
killed D8 as stated, but it did so over the wrong corpus: **5 result-index pages across 3 jurisdictions
and zero detail pages.** The Spike C protocol asked for index and detail templates fingerprinted
separately and warned that conflating them flatters the result. That test has never been run. Spike C's
headline therefore rests on municipal home pages and portal landing pages, which are a *proxy* for the
D8 claim rather than the claim itself.

Two things could still rescue a reduced version of the amortization story, and both are cheap:

- **A.** Permit *index* and *detail* pages might collapse across jurisdictions even though home pages do
  not - those are the only two page types an extractor ever sees.
- **B.** The Clark County NV / Yakima County WA pair scored 0.766, so Accela cohorts exist. Nobody knows
  whether Accela is two cohorts or fifty, and that single number carries most of the cost model.

Writing the rules down first is not ceremony. Spike A's threshold was revised after it tripped, and that
revision is only defensible because the original is still on the page. The same has to be true here,
especially since I already have a stake in the outcome: I published the 1.00 result.

## Pre-registered page types

Fingerprinted **separately**. Pooling them is the specific error the Spike C protocol named.

| Code | Page type | Definition |
|---|---|---|
| `T-SEARCH` | Search form | The module's search entry page (Accela: `Cap/CapHome.aspx`). Carries the form, no records. |
| `T-INDEX` | Result list | The page returned by a broad query: many records, one row each. |
| `T-DETAIL` | Permit record | One permit's own page (Accela: `Cap/CapDetail.aspx`). |

A page that cannot be assigned a type with certainty is recorded with `page_type=unknown` and excluded
from every ratio, not guessed into the nearest bucket.

## Pre-registered controls

Declared before fetching, with their expected direction. A control that comes out backwards voids the
measurement it guards - it does not get explained away.

| ID | Control | Pair | Expected |
|---|---|---|---|
| **C1** | Positive, within-portal, `T-INDEX` | Same portal, two different queries | **J >= 0.80** (Spike C measured 0.808-0.992 for this) |
| **C2** | Positive, within-portal, `T-DETAIL` | Same portal, two different permits | **J >= 0.80** |
| **C3** | **Confound**, within-portal, cross-type | `T-INDEX` vs `T-DETAIL`, same portal | **LOW.** If high, the fingerprint is measuring shared site chrome. |
| **C4** | Negative, cross-vendor, within-type | Accela `T-INDEX` vs non-Accela `T-INDEX` | **LOW** |
| **C5** | Baseline | All cross-jurisdiction pairs | median ~0.04, p95 ~0.08 (Spike C) |

**C2 is the load-bearing one.** It is simultaneously a control and the direct measurement of
within-jurisdiction amortization - the "~3x floor" that section 5 quotes and nobody has measured. If two
permit detail pages from the *same* portal do not collapse, then no cache key works at any scope and the
entire D8 family is dead, not just its cross-jurisdiction form.

**C3 is the confound that has never been checked.** Municipal pages share nav bars, headers and footers.
If index and detail pages of the same portal score high *because of chrome rather than record layout*,
then every same-vendor number in Spike C and in this measurement is inflated, and so is any conclusion
drawn from them. C3 high means the fingerprint gets re-specified before anything is reported.

## Pre-registered decision rules - Measurement A

Primary quantity: **median cross-jurisdiction, same-vendor Jaccard, computed within a single page type**,
reported separately for `T-INDEX` and `T-DETAIL`. Let `P` = the relevant positive-control floor (C1 for
index, C2 for detail) and `B` = the C5 cross-jurisdiction p95.

- **median >= P - 0.10** -> **cohort collapse confirmed for that page type.** Vendor+version+config
  keying is viable; step 4 is re-planned around discovered cohorts and the cost model is re-derived from
  cohort size.
- **B < median < P - 0.10** -> **partial collapse.** Cohorts are real but need version/config
  discrimination. Report the cohort count, not a single reuse multiple.
- **median <= B** -> **no collapse even within one vendor.** Per-jurisdiction synthesis is the only
  option, amortization is the ~3x within-jurisdiction floor, and the architecture's stated cost
  justification is gone. Say so plainly rather than looking for a fourth framing.
- **If C3 >= 0.60, every result above is reported as VOID** pending a chrome-stripped re-specification.

If index and detail disagree, **detail governs**, because detail pages are where the fields the schema
needs actually live and are the larger share of fetches.

## Pre-registered decision rules - Measurement B

Population: Accela ACA tenancies. **Slugs are discovered from public references, never guessed** - brute
forcing agency codes means 404-spamming a vendor that has done nothing wrong, and this project has a
politeness posture to keep. One `T-SEARCH` GET per tenancy.

Quantity: **cohort size = mean cluster size**, clustering `T-SEARCH` fingerprints at the threshold C1
justifies. This number replaces "a few hundred distinct vendor templates" in section 6.

- **mean cluster size >= 5** -> the amortization story survives in reduced form; re-derive the cost model.
- **2 - 5** -> marginal. Amortization is real but small; the writeup says single digits.
- **~1** -> Accela tenancies are individually skinned and the vendor name buys nothing. Combined with
  Spike C, D8 is finished in every form.

**Declared limitation, in advance:** `T-SEARCH` is a *proxy* for `T-INDEX`. Measurement A tests whether
that proxy holds. If A shows the two types cluster differently, B's number is reported as a proxy
estimate with this caveat attached to it, not as a cohort size.

## Provenance rule (the D1 constraint, applied)

Spike C found that Spike A's saved bytes did not carry their verdicts, so verifier-rejected pages -
including an iron castings foundry - re-entered a downstream analysis as municipal websites. That must
not recur, so it is fixed at the point of capture rather than by a filter bolted on afterwards.

**Every fetch writes the bytes and a manifest row in the same operation.** No page exists on disk
without a row. Manifest fields:

`fetched_at, url, final_url, http_status, content_type, bytes, sha256, jurisdiction, vendor, page_type,
verdict, verdict_reason, request_method, robots_ok`

`verdict` is one of `ok` / `rejected` / `unknown`, assigned by an automated check at capture time
(does the page actually contain a rendered result list / a record detail / a search form?), and **the
analysis reads the manifest, never the directory.** A page with `verdict != ok` cannot enter a ratio.

## Budget and politeness

- **Ceiling: 60 HTTP requests total** across both measurements. Nothing is fetched twice; saved pages are
  reused.
- 1.5s pause between requests to the same host; `PermitsResearchBot/0.1` with a contact address.
- Public, unauthenticated pages only. **No registration, no login, no bucket-7 portal** - that decision is
  explicitly deferred per ADR-0004 and is not reopened here.
- **$0 inference.** No model calls; stdlib HTTP and stdlib parsing only.

## What this does not establish

**Anything national.** A handful of tenancies cannot estimate a collapse ratio over 20,000 offices, and
no number produced here may be quoted as a national rate. This is the same limit Spike C carried.

**Anything about non-Accela vendors.** Bucket 3 in the Spike A sample is *entirely* Accela, so
Measurement A's cross-jurisdiction comparison is a measurement of **Accela**, not of municipal permit
portals. Tyler EnerGov, CityView, eTRAKiT and CentralSquare are untouched. If Accela cohorts collapse,
that supports a cost model for the Accela share of the universe and says nothing about the rest.

**Whether a synthesized extractor would actually transfer.** Structural similarity is necessary, not
sufficient. Two pages can share a DOM skeleton and still label their columns differently. A high Jaccard
score licenses *trying* a shared extractor, not asserting one works; that requires step 2 and a golden
set.

**Anything about bucket 4, 5, 6 or 7 portals**, which is now the gate-relevant unknown. The revised gate
in DESIGN.md section 8 turns on whether bucket-4 portals can be enumerated by partitioned querying
within budget. Neither measurement here touches that question.

**That the discovered tenancy list is representative.** Tenancies that are publicly linked and reachable
without login are, by construction, the more open end of Accela's customer base. A cohort size measured
over them is an estimate for that end, and is likely optimistic for the rest.
