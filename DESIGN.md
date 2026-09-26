# BuildScope — Municipal Building Permits Pipeline — Design

**Status:** Design resolved through branch 8. Three blocking spikes not yet run. No code written.
**Last updated:** 2026-09-19

**Scope target (decided 2026-09-19):**

- **Steps 0-2 plus the writeup are the committed floor**, and they are the decision gate: they produce
  the reconciliation number and the honest quality metrics that everything after depends on.
- **Steps 3-4 are the intended continuation, entered as soon as 0-2 lands.** They are *not* deferred
  prose. Nothing in steps 0-2 may be built in a way that makes them expensive to reach.
- **Steps 5-7 are genuinely deferred** and ship as design.

See section 9.

---

## 0. How to use this document

This is a handoff doc. It exists because the next work is three feasibility spikes that will be run in a
separate session, and the results determine which of two fairly different projects this becomes.

**If you are an assistant picking this up cold:** Sections 1–6 are settled context — read them, don't
relitigate them. Section 8 is your actual job. Section 7 lists what is deliberately undecided; do not
decide those items, because they depend on spike results and guessing now would waste the spike.

**Confidence markers used throughout:**

- `[G]` — grounded in a cited source
- `[D]` — derived arithmetically from a `[G]` anchor
- `[F]` — Fermi estimate, wide error bars, **assume wrong until measured**

An earlier version of this plan was built around a different domain and died because a volume figure was
asserted from memory rather than checked. Every `[F]` in section 6 is a candidate for the same failure.
Re-derive rather than inherit.

**Revision 2026-09-19.** Sections 2, 5, 6, 8, 9, 10 and 11 were amended after a verification pass against
Census and vendor sources. The material changes: place-level BPS data turns out to be published *monthly
for the full universe*, which mechanizes Spike B; Spike C was added because nothing previously tested the
load-bearing template-collapse assumption in D8; Spike A's decision rule was re-weighted because the
original weighting was systematically optimistic about the tier that actually matters; and the PII
question in section 11 is now decided rather than deferred. Everything changed is marked with a
`[2026-09-19]` tag.

**Revision 2026-09-20.** All three spikes have been run, the tier-2 classification has been re-run, and
step 1 is underway with three adapters. Two changes to how this document should be read:

- **`docs/` now carries the load.** [`docs/adr/`](docs/adr/) is *why a rule exists* (immutable),
  [`docs/design/`](docs/design/) is *how the system works today* (living), and
  [`docs/evidence/`](docs/evidence/) is *what was measured, and when* (append-only, dated). **Every number
  quoted below should be traceable to a dated report there**; where one is not, treat it as a
  recollection. Decisions D1, D3, D7 and D8 have been back-filled as
  [ADR-0006](docs/adr/0006-the-observation-log-is-the-source-of-truth.md),
  [ADR-0007](docs/adr/0007-office-identity-is-the-bps-office-id.md),
  [ADR-0008](docs/adr/0008-time-is-recorded-twice.md) and
  [ADR-0009](docs/adr/0009-adapters-first-generic-extraction-second.md); for those four the ADR is
  authoritative and the D section carries a dated pointer to it.
- **Section 8 is no longer "your actual job."** The spikes are done. The work is step 1 - the
  reconciliation number, now produced from both the open-data and the crawled-HTML paths - and the
  **named-office list**, which [ADR-0005](docs/adr/0005-a-bucket-is-demonstrated-not-inferred-from-the-search-form.md)
  makes the only thing that can *clear* the gate rather than merely fail to fire it.

**Revision 2026-09-21.** The ADR back-fill is complete, bucket 4 is resolved, and the project has tests.

- **`docs/adr/` is now authoritative for every decision D1-D10**, not just four of them. The D sections
  below are kept as the narrative and each carries a dated pointer to its ADR. Where the two disagree,
  the ADR wins; where a decision turned out to be unimplemented or falsified, its ADR says so rather than
  restating the original reasoning as though it were intact.
- **The gate metric moved down, on evidence.** Unit-weighted reachability is **69.5%**, not 73.1%,
  because Bowling Green KY turned out to publish no permit records at all. Bucket 4 - the cell section 8
  said the whole figure rested on - is now **2.3% of units**, down from 33.9% two days ago. See
  [the bucket-4 report](docs/evidence/2026-09-21-bucket4-resolution.md).
- **There is a test suite**, 307 tests, offline and free, run with `python scripts/run_tests.py`. The part
  that matters for this document: **every headline figure quoted below is recomputed from its source
  artifact by `tests/test_artifacts.py`.** Editing a number here without the artifact, or the artifact
  without the number, now fails. [ADR-0016](docs/adr/0016-tests-are-replay-over-the-raw-store.md),
  [`docs/design/testing.md`](docs/design/testing.md).
- **Refactoring is scheduled rather than pending**, in
  [`docs/design/refactoring.md`](docs/design/refactoring.md), with a ratchet in
  `tests/test_structure.py` that stops the known mess growing while it waits.

Spend to date: **$0, zero model calls.** Everything measured so far came from stdlib HTTP.

---

## 1. Project summary

A pipeline that crawls municipal building-permit portals across the United States, extracts permit records
into one normalized schema, and models each permit's lifecycle as an observation log rather than a
mutable row.

**Primary goals:** systems-engineering depth and a portfolio artifact.
**Secondary, if quality holds:** a public dataset release.
**Explicit non-goal:** a product.

### The core technical claim

There are roughly 20,000 permit-issuing jurisdictions, each with its own portal, vocabulary, and page
structure. Extracting from all of them with one LLM call per page is unaffordable. The claim is that
per-page cost can be converted into per-*template* cost via extractor synthesis, and that this is
measurable as a ratio.

**[2026-09-20] The claim stands; the premise under it does not.** Spike C measured 1.00 fingerprints per
jurisdiction at every threshold down to J = 0.60 - nothing collapses across jurisdictions. The
amortization unit is the **tenancy**, not the vendor and not the DOM skeleton, and **no amortization
multiple may be quoted** until the drift a synthesized extractor tolerates is measured against the golden
set in step 2. See [ADR-0009](docs/adr/0009-adapters-first-generic-extraction-second.md). Step 1 adds a
reason to doubt the framing itself: per-record cost varies **95x between platforms**, so a cost model
denominated in templates or adapters may be measuring the wrong thing.

**[2026-09-21] The conversion is MEASURED, once, within a template.** The
[extractor conformance test](docs/evidence/2026-09-21-extractor-conformance.md) synthesized an
extractor from one stripped page and ran it over the rest of the corpus for zero further calls.
Against the hand-written adapters it scored **1.0000 recall, 1.0000 precision and 1.0000 on every
field** - 4,188 records over 71 pages and two platforms, from two calls costing $0.33.

| | synthesis, once | direct, per page | whole corpus direct | ratio | breakeven |
|---|---:|---:|---:|---:|---:|
| St. Johns, 14 pages | $0.0326 | $0.1494 | $2.09 | **64x** | **0.2 pages** |
| Clark County, 57 pages | $0.2965 | $0.0419 | $2.39 | **8.1x** | **7.1 pages** |

On WATS, synthesis costs less than extracting a **single page** directly. Three qualifications, and
they are the whole of what keeps this from being the headline it looks like:

- **The ratio is not a property of the method.** The numerator is fixed and the denominator is the
  corpus, so 64x is a property of 14 pages. It grows with corpus size and says nothing about a
  template seen once.
- **The prohibition above stands unchanged.** This is amortization *within* one template. Cohort size
  - how many portals one synthesized extractor covers - is still unmeasured, so **no amortization
  multiple may be quoted across templates.** That is the number this claim actually needs and Spike C
  is still the last word on it.
- **It is agreement with a reference, not accuracy.** Both implementations read "Issue Dt" as the
  issue date; neither shows that it is one.

The 95x per-record byte spread reappears as a **58x spread in direct extraction cost per record** and
a **59x spread in synthesis cost per record**, which sharpens rather than answers the doubt above:
platform, not method, is the dominant term in both.

### The differentiating claim

The US Census Building Permits Survey attempts monthly collection from ~8,600 jurisdictions and imputes
the remaining ~11,400. A pipeline that observes the imputed set directly produces numbers that do not
currently exist. This is externally falsifiable against Census for the collected tier, which is unusual
for a project of this kind and is the single strongest thing in the plan.

**It is also the single largest unvalidated assumption.** See Spike B.

**[2026-09-20] No longer unvalidated, on both paths.** Spike B produced **~2-6% low-density error** over
9 jurisdiction-months from open data
([report](docs/evidence/2026-09-20-spike-b-bps-reconciliation.md)); step 1 produced **1.0% / 4.4% /
4.1%** over 3 months from a crawled HTML portal
([report](docs/evidence/2026-09-20-step1-stjohns-reconciliation.md)), qualified because that county's
units are implied rather than stated. Two limits survive and belong next to the claim wherever it is
made: **multifamily is not comparable monthly** - 5+ error is unusable at this granularity - and the
validation exists only for the *collected* tier, which is by construction the tier the claim is not
about. Observing the **imputed** tier remains the interesting half and is still unvalidated, because an
imputed office has no oracle to check against.

---

## 2. Grounded external facts

All from Census BPS documentation (`census.gov/construction/bps/about.html`,
`census.gov/construction/bps/stateannual.html`, and BPS technical documentation). Re-verify before relying
on any of it; methodology has changed repeatedly and recently.

- **Scope of BPS:** national, state, and local statistics on the *number and valuation of new
  privately-owned housing units* authorized by building permits. Residential new construction only — not
  commercial, not alterations, not additions. `[G]`
- **Aggregation levels published:** state, CBSA, county, and permit-issuing place. `[G]`
- **Sample design since Jan 2022:** cut-off sample. Monthly collection attempted on jurisdictions issuing
  more than an average of 5 new unit authorizations over 2018–2020. Jurisdictions averaging fewer than 6
  are imputed monthly. `[G]`
- **Tier sizes:** ~8,600 jurisdictions with monthly collection attempted; ~11,400 without. `[G]`
- **Imputation method:** assumes the ratio of current-month authorizations to year-ago authorizations is
  the same for respondents and nonrespondents. `[G]`
- **Universe basis:** changed from a fixed 2014 basis to an annually updated universe beginning with the
  Jan 2023 release, specifically to handle jurisdictions starting and stopping permit issuance. `[G]`
- **Response is voluntary.** `[G]`
- **Release timing:** monthly data ~12th working day after the reference month; final annual data on the
  first workday of May. `[G]`
- **Form C-404** collects additional detail on residential permits valued at $2M or more, including site
  address and building type. `[G]`

**[2026-09-19] Verified directly, not from documentation:**

- **Place-level data is published MONTHLY for the entire universe, as plain CSV.** `[G]`
  `https://www2.census.gov/econ/bps/Place/{Northeast,Midwest,South,West}%20Region/{ne,mw,so,we}YYMMc.txt`
  (`c` = that month, `y` = year-to-date). Confirmed live through 2026-06 as of 2026-09-19.
- **Columns** `[G]`: Survey Date, State, 6-Digit ID, County, Census Place, FIPS Place, FIPS MCD, Pop, CSA,
  CBSA, Footnote, Central City, Zip, Region, Division, Source, Place Name, then Bldgs / Units / Value for
  each of `1-unit`, `2-units`, `3-4 units`, `5+ units`. **This is exactly the BPS reconciliation target,
  at the right geography, at the right frequency, already split by structure type.**
- **Row count for 2026-06** `[G]`: Northeast 5,565 + Midwest 7,934 + South 4,408 + West 1,990 =
  **19,897 places.** The monthly file covers the *whole* universe, so the imputed tier-2 places are
  present and carry their imputed values. Observed-vs-imputed divergence is therefore computable at
  scale rather than anecdotally, which is a stronger form of the differentiating claim than section 1
  assumes.
- **Name collisions are real and in the data** `[G]`: 2026-06 contains both Phoenix, AZ (pop 1,708,127)
  and Phoenix, OR (pop 4,678). Independent confirmation of D3 - never key on name.
- **FIPS place is NOT the identity either** `[G]` - measured over 24 months of files. The identity is
  field 3, the **six-digit Building Permit Survey ID** ("Six-digit Building Permit Survey ID code", per
  the Place ASCII Documentation). Keying on `(state, FIPS place)` collapses the universe from 20,069 to
  12,980 because FIPS place `00000`/`99990` is reused for offices that are not Census places:
  **1,397 distinct Pennsylvania permit offices share FIPS place `00000`**, and 82 `(state, FIPS place)`
  pairs are shared by more than one office. Four offices change their FIPS place code within the
  24-month window. This is D3's thesis, measured: **crosswalks are attributes, identity is the BPS ID.**
- **Universe size, measured** `[G]`: 20,069 distinct `(state, BPS ID)` offices appear across
  2024-07..2026-06. Slightly above the ~19,900 single-month count, consistent with the annually-updated
  universe adding and dropping offices.
- **The tail is geographically concentrated** `[G]`: Midwest carries 7,934 places against the West's
  1,990. Tier-2 is mostly Midwestern and Northeastern villages and townships, which is also the
  population least likely to run a modern portal. The coverage ceiling has a location.
- **Vendor-level robots posture is permissive, not hostile** `[G]`: `aca.accela.com/robots.txt` and
  `aca-prod.accela.com/robots.txt` both 404; `energovweb.tylertech.com/robots.txt` is empty. Does not
  clear individual tenant subdomains, which must still be checked per source, but the vendor default
  does not block the crawl. Downgrades the corresponding risk in section 10.
- **RESOLVED: the `Source` column is the reported-vs-imputed flag, per place-month.** `[G]` Verbatim
  from the Place ASCII Documentation (Feb 9, 2022), field 16, "Source code identifying source of data":

  | Code | Meaning | Class |
  |---|---|---|
  | 1 | Building Permits C-404 survey form | reported |
  | 2 | Received data in electronic format | reported |
  | 3 | Received residential data via online reporting | reported |
  | 4 | Received residential data from another source - equivalent to reported data | reported |
  | 5 | **No report received, imputed data** | imputed |
  | 9 | **No report received and no imputed data** | absent |

  **This is a per-place-per-month flag, not a per-jurisdiction tier flag**, and that distinction turns
  out to matter more than the tier split does. See the imputation-mass finding below. (`Footnote` is a
  separate, sparse field - ~8% of rows, value `2` - and is not the imputation mechanism.)

### Why this matters structurally

Two tiers, two different uses:

| Tier | n | BPS status | Our use |
|---|---|---|---|
| Monthly-collected | ~8,600 | Self-reported by the permit office | **Calibration.** Score against it. |
| Imputed | ~11,400 | Model output, not an observation | **Contribution.** Divergence is a finding, not an error. |

Calibrate on tier 1, contribute on tier 2.

### [2026-09-19] Measured: what is actually imputed, and how much of it there is

All figures below are computed from 96 downloaded place files (4 regions x 24 months, 2024-07..2026-06),
478,403 place-months, zero malformed rows. They replace the corresponding `[F]`s in section 6.

**National authorized units, 2025-07..2026-06: 1,407,437.** `[G]` Confirms section 6's `~1.4-1.6M` at the
low end. That row is no longer an estimate.

**Where the imputation actually is:**

| Class | Place-months | % of place-months | Units (24mo) | % of units |
|---|---|---|---|---|
| Reported (Source 1-4) | 145,699 | 30.5% | 2,259,366 | **79.3%** |
| Imputed (Source 5) | 331,171 | 69.2% | 590,603 | **20.7%** |
| Absent (Source 9) | 1,533 | 0.3% | 0 | 0.0% |

**This reframes the differentiating claim, and strengthens it.** Section 1 frames the contribution as
"the ~11,400 imputed jurisdictions." That framing understates it and mislocates it:

- Jurisdictions averaging **under 6 units/yr hold only 0.88% of national units** `[G]` (11,252 of 20,069
  offices). If the contribution were really just the small-jurisdiction tier, the project would be
  producing better numbers for under one percent of national housing volume, and any informed reader
  would notice.
- But imputation is **not confined to small jurisdictions.** Of the place-months belonging to offices
  averaging >=6 units/yr, **41.7% are imputed or absent** `[G]` - large jurisdictions simply fail to
  respond in a given month. That nonresponse is where most of the imputed *volume* lives.
- So the honest headline is: **20.7% of nationally authorized housing units are, in the month they are
  published, a model output rather than an observation** - and that mass is driven by month-to-month
  nonresponse across jurisdictions of every size, not by tier membership.

**Use that as the claim.** It is larger, more defensible, and more interesting than the tier framing, and
it is measured rather than asserted.

**[2026-09-19] The two tiers pull the project in opposite directions, and this is the central structural
tension.** Tier-1 jurisdictions are large, and large jurisdictions are overwhelmingly the ones with open
data portals, stable vendor platforms, and rich index pages - i.e. easy. They are also precisely where
Census already collects, so extracting them contributes nothing new; they are only an oracle. Tier-2 is
where the contribution lives, and tier-2 is simultaneously the hardest to crawl (small, bespoke or absent
portals) and the lowest yield per crawl (fewer than 6 units per year by construction). Any metric
weighted by unit volume will therefore look good while saying nothing about whether the part of the
project that matters is feasible. **Every coverage, bucket, and cost figure in this document must be
reported twice - unit-weighted and jurisdiction-count-weighted - and tier-2 count-weighted is the honest
one.** This generalizes the rule already stated for coverage in section 5.

---

## 3. Resolved design decisions

### D1 — The observation log is the source of truth

Permit portals do not emit events. They render current state. We never observe *"issued on the 14th"*; we
observe *"on the 16th this page said Issued, and on the 9th it said Plan Review."*

Primary table is append-only, one row per successful fetch-and-extract:

```
(source_id, observation_key, observed_at, content_hash, extractor_version, extracted_state)
```

Current-state and lifecycle-transition views are folds over this log. Raw bytes are stored immutably and
every downstream stage is a pure function of them, so improving extraction means replaying, not
re-crawling.

- **Transitions are intervals, never instants.** Schema is
  `transition(from, to, observed_between:[t1,t2])`. Weekly cadence with a five-day lifecycle loses the
  middle states; the schema must not pretend otherwise.
- **`extractor_version` is part of the key.** When v7 disagrees with v4 about the same `content_hash`,
  that disagreement is a queryable fact rather than a silent overwrite. This is what makes measured
  accuracy improvement provable.

*Rejected:* flat current-state table. Cheaper and adequate for aggregate queries, but destroys
point-in-time correctness irrecoverably, and the observation log is nearly free given raw bytes are being
retained regardless.

**[2026-09-20] Back-filled as [ADR-0006](docs/adr/0006-the-observation-log-is-the-source-of-truth.md)**,
which adds what three replays taught: a manifest verdict of `ok` means *the fetch succeeded*, not *the
content is complete*, so **completeness is an adapter question** — only an adapter can read a vendor's
truncation banner. Replay has now paid for itself three times at zero requests.

### D2 — Ingest everything, normalize everything, calibrate one slice

Narrowing was mis-posed as an ingest decision. It isn't: portals don't segregate residential new
construction from reroofs, so a narrow scope is a post-extraction filter and therefore strictly *more*
work.

- **Ingest:** all building-related permits.
- **Normalize:** all of them, to a shared core schema with a canonical work-class ontology.
- **Calibrate:** residential new construction only, against BPS.
- **Children, not records:** trade sub-permits (electrical, plumbing, mechanical) attach to a parent when
  the parent is in scope. Never top-level — jurisdictions disagree on whether they are separate entities
  and flattening double-counts.
- **Out of v1:** planning/zoning applications (months-to-years lifecycle, discretionary approval, agenda-
  driven — a genuinely different pipeline), business licenses, certificates of occupancy.

**The reason breadth is worth it is taxonomy alignment, not row count.** A narrow scope has ~8 work
classes and trivial normalization. Full breadth inherits thousands of mutually incompatible controlled
vocabularies (`RESALT`, `COMTI`, `MECH-RES`, `BLDG-ADD-SFR`) that overlap partially and nowhere
identically. Mapping those onto one ontology with confidence and provenance is real ontology alignment,
is unsolved in this domain, and is the strongest technical claim breadth buys.

**Count units, not permits.** BPS counts housing units; one permit for a 200-unit building is 200 units.
`unit_count` is a required extraction field and is frequently buried in free-text description rather than
exposed as a column.

**`work_class` and `structure_type` are normalized enums from day one.** The entire BPS mapping depends
on separating new construction from alteration and 1-unit from 5+. These are the hardest extraction
targets and the most valuable.

**[2026-09-21] Back-filled as [ADR-0012](docs/adr/0012-ingest-everything-calibrate-one-slice.md)**,
which records that the sub-permit rule is the largest error this project has measured — Austin's 726% —
and names the part that is still only an intention: nothing yet maps two sources' vocabularies onto each
other, so "real ontology alignment" remains unbuilt. It also notes that breadth is what made the St. Johns
reconciliation possible at all: 69 property-use codes, of which 64 exist to be *excluded* correctly.

### D3 — Jurisdiction identity

Internal surrogate `jurisdiction_id`, never derived from any external code. Crosswalks to `census_geoid`
and `bps_office_id` are *attributes with match-confidence and match-method*, not identity.

Permit-issuing jurisdictions do not map cleanly onto Census places: counties issue for unincorporated
areas (not places at all), some offices serve multiple incorporated places, townships and New England
towns sit differently in the FIPS hierarchy, and annexation moves territory mid-year.

- **BPS place-level file seeds the frontier** and supplies the coverage denominator. Coverage becomes
  *jurisdictions with successful extraction ÷ BPS universe*, with the denominator supplied by the federal
  government rather than invented.
- **`is_permit_issuing` is temporal.** A jurisdiction that stood up a portal in 2025 is not a 2023
  coverage failure.

*Rejected:* keying on portal domain. Directly observable and simpler, but collapses when jurisdictions
share a vendor tenant or migrate platforms, and migration is common. Domain is a good discovery signal
and a bad identity.

**[2026-09-20] Back-filled as [ADR-0007](docs/adr/0007-office-identity-is-the-bps-office-id.md)**, which
resolves a discrepancy between D3 as written and what the project does. D3 specifies an internal surrogate
with `bps_office_id` as a crosswalk attribute; in practice the **office** — the frame row — is the unit of
account and `(state_fips, bps_id)` *is* its identity, as [ADR-0003](docs/adr/0003-jurisdiction-identity-is-bps-scoped.md)
and [`docs/design/entity-resolution.md`](docs/design/entity-resolution.md) already assume. No surrogate is
minted while there is exactly one source of rows. **The rule that earned its own ADR: the frame is the
only assigner.** The St. Johns adapter was built with `bps_id = "633000"` copied from a Spike A probe
script — that is **Okeechobee County**, 0 units in 0 of 24 months, where St. Johns is `803000` with 3,637
units. The classification file was right the whole time; a working note had been treated as a source of
record.

### D4 — Tiered crawl cadence

Cadence *is* temporal resolution, so it is a deliberate choice, not a scheduler default.

| Tier | Cadence |
|---|---|
| Top BPS unit-volume decile | Daily |
| Remainder of tier-1 | Weekly |
| Tier-2 (imputed) | Monthly |

Promotion is **churn-driven** — unexpected index-page churn temporarily upgrades a jurisdiction. Base
tier is **volume-driven**. Keying promotion on volume would merely re-derive the base tier.

*Rejected:* uniform cadence. Either wastes fetches on a village issuing four permits a month or
under-resolves Houston.

**[2026-09-21] Back-filled as [ADR-0013](docs/adr/0013-crawl-cadence-is-temporal-resolution.md)**, which
says plainly that none of this is implemented — nothing has been crawled twice, so every `observed_at` is
within hours of every other and a lag figure would be quoting the crawl schedule. One thing has changed
since D4 was written: churn detection now has a mechanism, because the capture layer stores a structural
fingerprint per page. Byte-level change is useless for this; a session token changes every fetch.

### D5 — Two-level permit identity

```
observation_key = (source_id, source_native_id_raw)   # deterministic at fetch time, never inferred
permit_id       = surrogate assigned by entity resolution
```

The naive `(jurisdiction_id, normalized_permit_number)` breaks on: application-number-to-permit-number
renumbering, annual counter resets, rendering instability across index/detail/PDF, vendor migration
renumbering, and records with no native identifier at all.

**Entity resolution output is a derived view, not a fact.** The `observation_key → permit_id` mapping
lives in its own versioned, recomputable table. Writing `permit_id` into the log would mean un-merging
requires rewriting history, which is precisely what this architecture exists to prevent.

Fixed resolution rules:

- **Revisions** (`-R1`, `-REV2`) — same permit, revision is a lifecycle event.
- **Renewals with a new number** — *different* permit, linked by a `supersedes` edge.
- **No native ID** — content-derived key over `(jurisdiction, normalized_address, type, application_date)`,
  flagged low-confidence, excluded from BPS reconciliation if that population is material.

*Note:* for aggregate BPS reconciliation alone, the simple composite key would suffice — a few percent of
identity error washes out in monthly unit counts. The surrogate earns its keep in the transition view,
where a false merge fabricates a status change and a false split hides one. It is justified only because
D6's lifecycle view is a committed deliverable.

**[2026-09-21] Back-filled as [ADR-0010](docs/adr/0010-permit-identity-has-two-levels.md)**, which keeps
D5's own caveat as the honest framing: for aggregate BPS reconciliation *alone* the simple composite key
would do, and **the surrogate is justified only because D6's lifecycle view is a committed deliverable.**
If that is cut, this decision should be reopened rather than kept from habit. Step 1 implements the
deterministic half only and refuses the rest — `MissingIdentifier` has never fired in production.

### D6 — Milestones and activity, not a state machine

A canonical enum with allowed transitions fails: real lifecycles loop (plan review → revisions requested →
resubmitted → plan review), branch, and are frequently invisible. A state machine permitting every
observed transition is a fully connected graph with extra steps.

**Milestones** — stored as *rows, not booleans*:

```
permit_milestones(permit_id, milestone, reported_date, observed_from, observed_to, confidence)
```

Values: `applied`, `issued`, `finaled`, `terminated{reason}`.

Rows rather than flags because a boolean conflates *"this ever happened"* with *"this is currently true"*
— `issued = true` on a revoked permit is a false statement under the ordinary reading. Rows also force
correct handling of absence: no issuance row means **not observed**, which is not the same as **not
issued** (could be an unobserved jurisdiction, coarse cadence, or a portal that never exposes it).

`approved` was **demoted to activity**. Plan-review approval is routinely provisional and never satisfied
monotonicity honestly. Issuance and finalization essentially do not loop.

**Activity** — current non-monotone label: `in_plan_review`, `awaiting_applicant`, `inspecting`,
`on_hold`. Flips freely, no ordering guarantees.

**`authorization_state`** — derived, for readers who just want to know if the permit is live: `active`,
`expired`, `revoked`, `suspended`, `closed`, `unknown`. Return `unknown` wherever the jurisdiction's
expiry rule is unknown, which will be often. Do not compute an expiry you cannot justify.

Properties this buys:

1. **Comparability** — vocabularies differ wildly, but nearly every jurisdiction exposes issuance and
   closure somehow. Milestones are the intersection that actually exists.
2. **Free data-quality alarm** — monotonicity is falsifiable. A milestone regression means an extraction
   error, a false merge, or something genuinely odd. Checked on every write at no cost.
3. **Survives coarse cadence** — a monthly crawl catching `applied → issued → finaled` in one gap records
   all three as latched-by-t2 rather than inventing an ordering.
4. **BPS maps cleanly** — BPS counts units *authorized*, which is a milestone. Reconciliation falls out of
   the model instead of being reverse-engineered from a status string.

**On loops:** the milestone view is a deliberate lossy projection and destroys nothing. Five plan-review
cycles are all present in the observation log and exposed by the transition view; loop count is a query.
State this explicitly in the dataset docs — it converts an apparent limitation into documented intent.

**Vocabulary mapping is per-vocabulary, not per-record.** A jurisdiction has 10–60 distinct status
strings. Collect distinct `(platform, jurisdiction, status_string)`, dedupe globally, map once, cache
permanently. Same amortization trick as template induction on a different axis — worth naming as such in
the writeup, since the symmetry is the architectural argument.

**Disambiguate with the transition graph, not just the model.** `Closed` genuinely means finaled,
withdrawn, or expired depending on jurisdiction. With millions of observed transitions, a string's
*position* in the empirical graph is strong evidence: if `Closed` is usually preceded by `Inspections` and
followed by nothing, it is a finalization. LLM proposes, data adjudicates.

Always retain the native string. Always allow `unmapped`. Track **percent of observations with a
confidently-mapped milestone** as a headline quality metric — force-mapping to avoid an ugly bucket
quietly corrupts the dataset.

**Exclusion flag required:** some jurisdictions never distinguish issue date from application date. Those
cannot participate in BPS reconciliation and need an explicit flag, not a silent guess.

**[2026-09-21] Back-filled as [ADR-0011](docs/adr/0011-milestones-are-rows-with-a-fixed-vocabulary.md)**,
which records that the closed vocabulary caught a real bug *by refusing*: the Clark County adapter emitted
a milestone name outside the four and 20 of 371 records were rejected at the boundary rather than written
with a meaningless lifecycle. It also names the cost of dropping undatable milestones — a date-parsing bug
looks exactly like an absence, which is how `norm_date` nulled 100% of St. Johns' dates.

### D7 — Time is recorded twice, always

Portal-reported date is **valid time**. First observation is **transaction time**. Both stored, neither
overwrites the other.

The gap between them is the **reporting-lag metric** — simultaneously a pipeline health check and one of
the more publishable findings in the dataset (jurisdictional reporting lag, p50/p95, nationally).

**[2026-09-20] Back-filled as [ADR-0008](docs/adr/0008-time-is-recorded-twice.md)**, which states plainly
that this is the least-implemented decision in the document: every permit has been observed exactly once,
so there is no lag distribution, no transition interval and no lifecycle view — only `observed_at` on each
record. It buys nothing today and is justified entirely by the option it preserves, because transaction
time cannot be backfilled: the portal does not remember what it said last week. One thing it already pays
for is precision about the reconciliation error — that comparison is **valid-time-denominated**, so
month-boundary lag sits *inside* the St. Johns 4.1% and is not separable from extraction error.

### D8 — Adapters first, generic extraction second

Hand-written adapters — this project's term for a human-written extractor — for the top 4–5 platforms by
universe share, then LLM extractor synthesis for the rest.

The better argument than velocity: **adapters are the eval oracle for the generic path.** A known-good
Accela adapter lets synthesized extractors be scored on thousands of pages without hand-labeling, which
makes the generic path cheaper to build later rather than more expensive.

Guardrails, because the failure mode — adapters work well enough that generic never happens — is real:

- **Cap at 4–5 adapters**, chosen by universe share. Past that, generic or nothing.
- **Identical emit interface from day one.** If the schema ends up shaped by what Accela exposes, generic
  extraction fights the schema forever.
- **Written trigger:** generic work starts when adapter coverage plateaus or by a fixed date, whichever
  comes first. Without a date this slips silently.

**Template identity is a DOM fingerprint, not a site.** Hundreds of jurisdictions running the same vendor
default render near-identical skeletons. Keying the template cache on structural hash rather than domain
collapses the amortization denominator from ~20,000 sites to plausibly a few hundred distinct vendor
templates `[F]`. This is the strongest argument the full universe is tractable, and it predicts the cost
curve should *bend* as coverage grows rather than rise linearly. **Measure cross-jurisdiction template
reuse as a headline number.**

**[2026-09-20] MEASURED, and the paragraph above is false as written.** Do not build from it.
[Spike C](docs/evidence/2026-09-20-spike-c-template-collision.md) fingerprinted 25 jurisdictions and
found **1.00 fingerprints per jurisdiction at every threshold down to Jaccard 0.60** - nothing merged.
"~20,000 sites collapse to a few hundred templates" is dead, and every cost figure that rested on it has
been withdrawn from sections 5 and 6.

What replaces it, from
[Measurements A and B](docs/evidence/2026-09-20-measurement-ab-results.md):

- **The cache key is vendor + version + configuration, discovered by clustering - not pure DOM
  structure, and not the vendor name.** Two CivicPlus sites of matched type score 0.255; two Accela
  tenancies score 0.766. The vendor name alone predicts nothing.
- **The amortization unit is the TENANCY.** Two different Oregon jurisdictions inside one statewide
  Accela tenancy render permit detail pages at **J = 0.863**. That is the cross-jurisdiction reuse this
  paragraph was reaching for; it exists, but it lives inside multi-jurisdiction tenancies rather than
  across a vendor's whole fleet. Spike A counted 18 statewide portals.
- **Index and detail are separate templates** (J = 0.19 within one portal), so a tenancy needs **at least
  two** extractors, not one.
- **Cohort size is a curve - 1.00 at J >= 0.95, 8.00 at J >= 0.70 - and structure cannot pick the
  threshold.** It depends on how much drift a synthesized extractor tolerates, which is a step-2 question
  against the golden set. Until that is measured, no amortization multiple may be quoted.

The instruction to *measure cross-jurisdiction template reuse as a headline number* was right and is
kept. It is what killed the claim above.

**[2026-09-20] Back-filled as [ADR-0009](docs/adr/0009-adapters-first-generic-extraction-second.md)**,
which records the decision that survived, the premise that did not, and **sets the written trigger D8
required and never got** — the silent slippage D8 itself predicted. The trigger is an artifact, not a
date: **the fourth adapter is the last one built before a measured generic-versus-adapter comparison
exists.** No fifth adapter until the conformance test produces a number. Three adapters of the cap of five are
now spent (open-data, Accela, WATS). Two further consequences from step 1 that belong here:

- **The emit interface survived a third platform** — one new `UNIT_SOURCES` value, no schema change. §9
  obligation 1 is discharged for now. The cost side, which nobody writes down: a shared interface is a
  shared bug. `norm_date` lives in the common layer and nulled **100%** of one county's dates at once.
- **"Number of adapters" is the wrong unit of coverage.** Per-record cost varies **95x between
  platforms** — 0.76 KB/record for WATS against 72.3 KB for Accela. An adapter's value depends on the
  page density of the tenancies it unlocks, not on the platform's share of the office count.
- **A hypothesis pointing somewhere D8 did not.** St. Johns' entire structure classification came from a
  **code table the county publishes in its own search form**, 69 codes with labels, for zero requests —
  not from page structure at all. If that generalizes, the expensive thing for a synthesized extractor to
  learn is a source's **controlled vocabulary**, not its DOM. One portal, so it is written here as a
  hypothesis; it is the most interesting thing step 1 turned up about the generic path.

### D9 — Golden set precedes the pipeline

- **Record-level labeling**, not page-level. One index page yields ~50 records; page-level labeling leaves
  per-field metrics badly correlated.
- **Drawn from the raw store**, never live fetches, or the set isn't replayable against future extractor
  versions.
- **Stratified** by platform, jurisdiction tier, page type, and work class. Uniform sampling oversamples
  reroofs and says nothing about the tail, which is where extraction fails.
- **Labeled blind** from the rendered page, never by correcting extractor output. Correction-labeling
  anchors to the extractor's mistakes and inflates measured accuracy.
- **Self-agreement check:** double-label ~50 records two weeks apart. Failure to agree with yourself on
  `work_class` means the field is underspecified and no extractor can be honestly scored on it.
- **Dev and test frozen separately.** Iterate on dev, touch test rarely. Failure cases go to a growing
  *regression* set, never into dev or test, or you overfit to your own bugs.
- **Size:** 500–1,000 records for v1. Realistically 15–25 hours of labeling.

LLM-as-judge may be used to *triage* which records deserve human attention. It must not produce headline
numbers — its errors correlate with the extractor's, so it flatters exactly where the pipeline is wrong.

**[2026-09-21] Back-filled as [ADR-0014](docs/adr/0014-the-golden-set-precedes-the-pipeline.md)**, which
adds the distinction that matters now that a test suite exists: `tests/test_adapters.py` replays adapters
over stored pages and is a **regression** set, not a golden set. It checks that behaviour has not
*changed*; it says nothing about whether the behaviour is *correct*. Letting the free one stand in for the
15–25-hour one is how a project stops measuring accuracy. Zero records are labelled.

### D10 - The raw store is permanently private; only derived tables are releasable `[2026-09-19]`

D1 makes raw bytes the source of truth and every downstream stage a pure function of them, so extraction
improves by replaying rather than re-crawling. Section 11 separately establishes that owner-builder
permits carry an individual's name attached to their home address. **Those names are in the raw HTML.**
The two facts together force a boundary the earlier draft left implicit:

- **The raw store is never published.** Not as a torrent, not as a requester-pays bucket, not on request.
- **Replayability is an internal property.** Third parties get the derived dataset and the extractor
  source; they do not get the ability to re-derive it. External reproduction means re-crawling, which is
  not reproducible against a changing web. **State this plainly in the dataset documentation** rather
  than implying a reproducibility guarantee the architecture cannot honor.
- **Individual-vs-business classification happens at extraction time, not release time.** The
  classification is stored; the raw applicant-name string stays in the raw store and never lands in
  `permits` or any other derived table. A release-time filter over a derived table that already holds the
  names is a strictly weaker posture, because it depends on the filter being correct forever rather than
  on the data never being there.

*Rejected:* publishing a redacted raw store. Redacting names out of arbitrary municipal HTML reliably
enough to publish nationally is a harder NLP problem than the extraction pipeline itself, and failure is
unrecoverable once distributed.

---

**[2026-09-21] Back-filled as [ADR-0015](docs/adr/0015-the-raw-store-is-permanently-private.md)**, which
records that this has now been confirmed live rather than reasoned about: the St. Louis bucket-4 probe
returned a parcel table carrying **owner names against residential addresses**, from a portal that
publishes no permit records at all. The PII arrives while *classifying a portal*, before any extraction
decision is made — which is exactly why the boundary sits at the store and not at the extractor.

---

## 4. Data model sketch

```
jurisdictions(jurisdiction_id PK, name, state, is_permit_issuing_from, is_permit_issuing_to, ...)
jurisdiction_crosswalk(jurisdiction_id, target_system, target_id, confidence, method, valid_from, valid_to)
                       -- target_system ∈ {census_geoid, bps_office}

sources(source_id PK, jurisdiction_id FK, platform, base_url, enumerability_class, result_cap, robots_posture)

raw_fetches(content_hash PK, source_id, url, fetched_at, status, headers, body_ref)   -- immutable

observations(source_id, observation_key, observed_at, content_hash, extractor_version,
             extracted_state JSON)                                                    -- append-only

entity_resolution(observation_key, source_id, permit_id, confidence, method, resolver_version)  -- derived

permits(permit_id PK, jurisdiction_id, work_class, structure_type, unit_count,
        valuation, address_normalized, ...)                                           -- derived fold

permit_milestones(permit_id, milestone, reported_date, observed_from, observed_to, confidence)

permit_activity(permit_id, activity, observed_from, observed_to, native_string)

permit_edges(from_permit_id, to_permit_id, edge_type)   -- supersedes, parent_of

status_vocabulary(platform, jurisdiction_id, native_string, mapped_milestone,
                  mapped_activity, confidence, mapping_version)

templates(template_hash PK, platform, extractor_program, synthesized_at, synthesis_cost, status)
```

---

## 5. Metrics

**Coverage** — jurisdictions with ≥1 successful extraction ÷ BPS universe. Reported **twice**: unweighted,
and weighted by BPS unit volume. The weighted figure is the honest one; covering Los Angeles is not
equivalent to covering a village of 300. Reporting both unprompted signals statistical honesty.

**Quality**
- Field-level precision / recall / F1 against the golden set
- BPS reconciliation error `|ours − BPS| / BPS` per jurisdiction-month, tier-1 only
- Per-field null rate per template — the drift alarm
- Percent of observations with a confidently-mapped milestone

**Cost**
- `$ / 1K records`
- **Template amortization ratio** = pages extracted ÷ LLM calls made. The honest one-number summary of
  whether the architecture works. **[2026-09-20] PROVISIONAL — no value may be quoted.** The metric is
  well specified and entirely unmeasured: it has never been computed from real calls, and the only
  estimate this document ever carried (20–60×) was withdrawn in section 6 after Spike C measured its
  governing term at 1.00 fingerprints per jurisdiction. Until cohort structure is measured, the
  defensible statement is that the ratio is somewhere at or above the ~3× single-jurisdiction floor,
  which is not a number worth putting in a writeup.
- **Cross-jurisdiction template reuse rate** `[2026-09-19]` = distinct template fingerprints ÷ distinct
  jurisdictions covered. **This is the term the amortization ratio actually depends on, and it deserves
  to be reported separately.** Within a single tier-2 jurisdiction issuing ~40 permits a year, one
  synthesis call amortizes over perhaps three index pages - roughly 3x, which is not a story. The 20-60x
  range in section 6 was carried *entirely* by the same template recurring across many jurisdictions. If
  reuse is near 1:1, the architecture's reason for existing is gone regardless of how good the
  extractors are. Measured by Spike C, before step 4 is built.

  **[2026-09-20] MEASURED at 1.00 — exactly the 1:1 case named above.** Spike C found
  fingerprints ÷ jurisdictions = 1.00 on tier-2 and pooled, at every threshold down to Jaccard 0.60,
  median cluster size 1. **Pure DOM structure is not a viable cache key across jurisdictions.** What
  survives is narrower and real: two Accela tenancies (Clark County NV / Yakima County WA) score 0.766
  against a 0.077 cross-jurisdiction p95, so reuse does happen *inside a vendor-version-configuration
  cohort*. This metric is therefore re-specified as **within-cohort reuse rate**, reported with the
  cohort size distribution beside it, cohorts discovered by clustering rather than assumed from the
  vendor name — two CivicPlus sites of matched type score only 0.255, so the vendor name alone is not
  the cohort.

  **[2026-09-20] Measurement B returned a curve, not a number.** 16 Accela tenancies cluster into 16 / 14
  / 6 / 2 groups at J >= 0.95 / 0.90 / 0.80 / 0.70, i.e. mean cohort size **1.00 to 8.00 depending on the
  tolerance chosen**, and structure alone cannot choose it. Report this metric as the *curve* plus the
  tolerance assumed, never as a bare multiple. The one clean cross-jurisdiction datapoint is **J = 0.863
  between two different Oregon jurisdictions inside one statewide tenancy**, which is why the reuse unit
  should be the **tenancy**. Note also that index and detail pages of the same portal score 0.19 against
  each other, so the per-tenancy extractor count is **at least two**.
- **Fallback fraction** = share of pages no synthesized extractor handles. This is the term that dominates
  total cost.
- Naive baseline, **computed but never spent** — measure it on a sample rather than asserting it.

**Freshness** — observation lag between portal-reported date and first observation, p50/p95.

**Health** — fetch outcome distribution by class, p99 latency, queue lag, poison-queue depth, per-host
politeness compliance.

---

## 6. Scale estimates — LOW CONFIDENCE

**Every number in this section is `[F]` unless marked otherwise. Re-derive from spike data before using
any of it in a writeup, a resume line, or an architecture decision.**

The one conclusion that is robust: **this is not a throughput problem.** Steady-state fetch rate for the
full national universe is single-digit requests per second. That is one machine. The difficulty is
concurrency across twenty thousand slow, flaky, individually rate-limited hosts — a file-descriptor and
connection-lifecycle problem, not a bandwidth one. **Size for fan-out, not volume.**

| Quantity | Estimate | Conf |
|---|---|---|
| Permit-issuing offices | ~20,000 | `[G]` |
| Housing units authorized / yr | **1,407,437** (2025-07..2026-06) | `[G]` **measured**, see section 2 |
| New residential permits / yr | ~1.0M | `[D]` |
| All permit records / yr | 20–40M | `[F]` |
| Backfill population (5–10 yr) | 150–300M | `[F]` |
| Steady-state request rate | ~3 req/s | `[D]` |
| Raw bytes @ ~120KB/page | ~30 GB/day, ~5 GB/day compressed | `[F]` |
| Backfill raw | ~24 TB, ~3.5 TB compressed | `[F]` |
| Observation log | 600M–1B rows, 60–150 GB Parquet | `[F]` |

**[2026-09-19] The units figure is no longer a Fermi estimate - compute it.** Summing the `Units`
columns across all four regional place files for twelve consecutive months yields the national annual
authorized-unit count exactly, from the same source BPS itself publishes. Do this before writing any
number in this table into a writeup. The same sum, grouped by the tier flag, gives true tier-1/tier-2
sizes and the unit-volume distribution that D4's cadence tiering and the section 5 weighting both depend
on. It is a download and a `groupby`, not an estimate.

### [2026-09-19] Inference cost strategy

**[2026-09-19] BUDGET CAP, DECIDED: $40 total inference spend to reach the October decision gate.**
Standing instruction from the owner: keep it low, justify anything non-trivial. Treat the cap as a design
input on the same footing as the scale figures.

**The cap is not the binding constraint, and it is worth saying so plainly.** Modelled against the actual
gate scope (`cost_model.py` in the project root, assumptions stated inline and editable in one
place; the scratchpad copy is session-temporary and will vanish):

| Scenario | Cost of the October gate |
|---|---|
| Fallback 5% (the designed behaviour), 2x contingency | **$9.36** |
| Fallback 25%, 2x contingency | $14.86 |
| Fallback 50%, 2x contingency | $21.74 |
| Fallback 100% - i.e. template induction fails completely | $35.49 |

**Even total architectural failure lands under $40.** The gate needs roughly a quarter of the cap. So the
cap should not be allowed to distort sequencing decisions, and there is no reason to trade quality for
cost anywhere in steps 0-2. Spend where it buys a defensible claim.

**What the cap does do is convert the fallback fraction into a tripwire.** The table above is a monotone
function of one number - the share of pages the synthesized extractor cannot handle. If measured spend
starts tracking the 50-100% rows, the arithmetic is not the problem; **D8 is not working**, and that is a
design finding worth having early rather than a budget overrun. Log spend per call class from the first
call so the tripwire is readable.

**Where the money actually is, and it is not here:** a national crawl is $53-267 in synthesis alone
(depending on template amortization: 1 template per 20 offices vs per office) plus $77-1,155/yr in
fallback extraction at 2-30% fallback. **That is a different decision with a different budget, and it is
not due by October.** Do not let national-scale figures leak into gate planning.

**[2026-09-20] The low end of that range is unsupported and the base is wrong in the other direction.**
"1 template per 20 offices" assumed cross-jurisdiction template collapse; Spike C measured 1.00
fingerprints per jurisdiction. Read the national synthesis figure as **$267, an unbounded-above point
estimate**, not as a range, until a cohort size exists. Offsetting this: only ~36% of sampled offices
have a portal to template at all, so the ~20,000-office base should be nearer **~7,000**. The two
corrections push in opposite directions and neither has been quantified, which is precisely why no
national figure should be quoted yet.

Stated constraint: **minimize inference spend without trading away quality.** The levers below are
ordered so that the free ones are exhausted before any quality tradeoff is considered.

**Rates** (Anthropic first-party, as of 2026-06-24 - re-verify before quoting): Opus 5 $5/$25 per MTok
in/out; Sonnet 5 $2/$10; Haiku 4.5 $1/$5. Prompt-cache reads bill at 0.1x input; cache writes at 1.25x
(5-minute TTL) or 2x (1-hour). Batch API is 50% off both directions.

**Free levers, in order. These do not touch quality.**

1. **The cheapest call is the one never made.** Bucket-1 jurisdictions (documented API or bulk download)
   cost **zero inference, permanently** - the data arrives already structured, so take every one of them.
   **[Amended twice; this is the settled version.]** The first draft called this the single largest cost
   lever, which was wrong on office count. The first correction then under-rated it, because the sweep's
   unmatched names were concentrated in the biggest publishers. Resolved: **180 offices, 0.90% of the
   universe, 16.63% of national units** (section 8). So: a free lever covering a sixth of national volume
   for about 1% of the crawl targets - clearly worth exhausting first - but **~83% of units still have to
   be crawled**, so levers 2-4 and template amortization still carry the cost story.
2. **Batch API for everything.** This workload is a background crawl - nothing is latency-sensitive, no
   human waits on any response. That is a **flat 50% off** with no quality cost whatsoever. Every
   synthesis and fallback call should go through Batches unless there is a specific reason not to.
3. **Prompt caching on the synthesis prefix.** Extractor synthesis resends a large stable prefix - the
   target schema, the work-class ontology, the few-shot examples - against a small variable suffix (the
   page). Put one explicit breakpoint after the stable prefix and the resends bill at 0.1x. Anthropic's
   published agent-loop measurements put caching at a 2.5-3.7x cost reduction at 81-90% hit rates; this
   workload's prefix/suffix ratio is unusually favorable. **Verify with `cache_read_input_tokens`, not
   by reading the code** - if it is zero across repeated calls, something in the prefix is varying.

   **[2026-09-23] VERIFIED, as instructed, and this lever is worth about 2% of spend - not 2.5-3.7x.**
   Across all 67 calls in `data/infer/ledger.jsonl`, **5 had any cache activity at all**, every one of
   them Opus 5 on `clarkco`. Haiku and Sonnet show zero cache *writes*, not merely zero reads, so the
   breakpoint never engaged on them.

   Nothing in the prefix is varying. **The prefix/suffix claim is inverted.** The stable part is
   `SYNTH_SYSTEM` - schema, ontology, few-shots - and it measures **889 tokens against a 13,535-token
   request, 6.6%**. The variable part is the page, and it is the other 93%. Anthropic's agent-loop
   figures describe a long stable conversation history against short turns; this is one shot over a
   large document, which is the same ratio the other way up. Even at a 100% hit rate on every call the
   ceiling is 0.9 x 6.6% of input spend, and input is 35% of the bill: **~2% of total.**

   Where the money actually is, measured over the same 67 calls: **output tokens are 51-75% of spend
   in every call class.** A lever that only touches input cannot be the top of this list. Lever 2 is,
   and it is worth restating that **lever 2 has never been implemented** - there is no Batch code path
   in `permits/` or `scripts/`, so all 67 calls were billed at full rate, while `cost_model.py` prices
   the entire project with `batch=True` as its default argument. Every planned figure in this section
   is a batched number and every measured figure is not.
4. **Do not send raw HTML to the model.** Strip scripts, styles, comments, and attribute noise before
   the page enters a prompt. On municipal portal HTML this is routinely an order-of-magnitude token
   reduction against identical extraction quality, and it compounds with everything above.

   **[2026-09-21] MEASURED. Both halves of that sentence are wrong, in opposite directions.**

   *"An order-of-magnitude reduction"* overstates it. Measured over 12 pages per family with the
   keep-list as it stood: **Accela index 8.3x, Accela detail 6.3x, WATS 3.0x.** The range is 3-8x, and
   the platform with the cheapest bytes per record is also the one that strips worst - so the lever is
   real and worth pulling, and no figure resting on 10x holds.

   *"Against identical extraction quality"* was never checked, and as implemented it was false. The
   keep-list inherited from `spikes/measure_tokens.py` was `id, name, href, value, type`, chosen to
   preserve *navigation* of an ASP.NET form - a different job from *reading a grid*. An Accela ACA
   results grid marks its data rows with `class="ACA_TabRow_Odd"` and nothing else: no id, no name.
   Stripping deleted all 42 markers on a Clark County page and left the rows in place, so the page
   still looked complete with its only row signal gone. Same silent-instrument family as the
   fixed-width date slice and the substring field classifier. `class` is kept by default now
   ([`permits/strip.py`](permits/strip.py), pinned by `tests/test_infer.py`), which costs **24% of the
   stripped Accela index page, 46% of a detail page and 5% of a WATS page**, taking the reduction to
   **6.7x / 4.3x / 2.9x**. The original list is frozen as `LEGACY_KEEP` because the published token
   figures were measured with it.

   **The lesson is this lever stated backwards: a stripping rule is an extraction decision.** Its
   quality cost has to be measured on the platform it will be applied to, not inferred from the byte
   count - and 24-46% of the saving was buying nothing but the loss of the signal.
5. **Amortize on both axes, as already designed.** D8 amortizes per template; D6 amortizes vocabulary
   mapping per `(platform, jurisdiction, status_string)` rather than per record. Both are cost
   architecture, and both are already in the design - hold the line on them.

**Quality tradeoffs, deferred until step 2 exists.**

6. **Model tiering by call class.** The section 5 amortization ratio counts "LLM calls" as fungible, and
   they are not - a synthesis call and a fallback extraction call differ by roughly 5x in unit price.
   The natural split is a strong model for *synthesis* (few calls, hard reasoning, high leverage - an
   error here propagates to every page that template touches) and a cheap model for *fallback
   extraction* (many calls, mechanical). **Report cost per call class, not blended**, or the headline
   ratio hides which half the money went to.

**The sequencing constraint that governs all of the above:** cost per *completed task* is the real
metric, not cost per token. A cheap model that mis-extracts `unit_count` still bills its tokens, and
then corrupts the reconciliation number - the project's headline - at a cost no saving repays.
**Therefore lever 6 cannot be evaluated until the golden set exists**, because before step 2 there is no
way to tell a cost saving from a quality regression. Levers 1-5 are safe now; lever 6 waits for step 2.
The committed scope already sequences these correctly - do not reorder them to save money sooner.

**[2026-09-21] MEASURED, and the deferral above was wrong.** The
[extractor conformance test](docs/evidence/2026-09-21-extractor-conformance.md) evaluated lever 6 for
$1.2751 without a golden set. The reasoning that blocked it holds for *accuracy* and does not apply to
a *comparison between two models*: the reference is a hand-written parser, so its errors are
**uncorrelated** with any model's - which is exactly the property an LLM-as-judge lacks, and exactly
why D9 forbids LLM-as-judge for headline numbers. Two models scored against an uncorrelated reference
can be compared to each other even though neither can be called correct.

Lever 6's split is **confirmed, with the platform as a third term**:

- **Direct extraction: the cheap tier is sufficient.** Haiku 4.5 scored 1.0000 recall, precision and
  every field on both platforms, including a 259-record page returned as one JSON array. No measured
  reason to pay Opus prices for this call class. (Opus was never run on this arm, so this is a
  ceiling, not a demonstration that Opus is no better.)
- **Synthesis: the tier is decisive.** Haiku failed Accela completely; Opus was perfect on the same
  window of the same page. The easy template (WATS) synthesized correctly at the cheap tier and the
  hard one did not, so the right variable is template difficulty, not call class alone.
- **The asymmetry is observed, not argued.** One bad synthesis call broke **all 57 pages**. A cheap
  extraction error costs one page; a cheap synthesis error costs the template. That is the entire
  basis of the lever and it now has a number behind it.

What has *not* changed: this is agreement with a reference implementation, and lever 6's real question
- whether a cheap model **mis-extracts `unit_count`** and corrupts the reconciliation headline - is a
question about accuracy that still needs D9. The lever may now be pulled on *parsing*. It may not be
pulled on *semantics*.

**Attachments are the single biggest lever.** Plan sets run 50–500MB each. Fetching them multiplies
storage by one to two orders of magnitude and buys almost nothing in v1. **Record attachment URLs and
metadata; do not fetch bytes.** Hard v1 boundary.

**On the cost reduction factor:** an earlier draft of this plan floated "340×" as an illustrative figure.
It was invented and should not be repeated. A later draft replaced it with a "realistic disciplined
range" of **20–60×**, dominated almost entirely by fallback fraction.

**[2026-09-20] The 20–60× range is withdrawn.** It rested entirely on D8's claim that ~20,000 sites
collapse onto a few hundred templates, and [Spike C](docs/evidence/2026-09-20-spike-c-template-collision.md)
measured **fingerprints ÷ jurisdictions = 1.00** at every clustering threshold down to Jaccard 0.60,
median cluster size 1. **There is now no supportable cost-reduction multiple anywhere in this document.**
Do not quote one — not 340×, not 20–60×, and not the ~3× single-jurisdiction figure, which is a floor
rather than an estimate. A range may be re-derived once a vendor-cohort size has been measured
(Measurement B, section 8); until then the honest answer to "how much does this architecture save" is
**unmeasured**, and that is the answer that goes in a writeup. Compute the naive baseline empirically
when there is something to compare it against.

**[2026-09-20] Measurement B has run and the answer is still not a single number.** Accela cohort size is
**1.00 at J >= 0.95 and 8.00 at J >= 0.70**, and nothing measured so far picks the threshold - that
depends on how much structural drift a synthesized extractor tolerates, which is a step-2 question
against the golden set. **So the supportable statement is a range of 1x to 8x on the tenancy axis, which
is too wide to put in a writeup.** Two corrections to the arithmetic underneath it, both new:

- **Multiply synthesis cost by at least 2 per tenancy.** Index and detail pages of the same portal share
  almost no structure (J = 0.19), so each tenancy needs two extractors minimum. No figure in this section
  ever counted that.
- **Count tenancies, not offices.** Two different Oregon jurisdictions inside one statewide Accela
  tenancy render detail pages at J = 0.863. The denominator for synthesis is the number of *tenancies*,
  and statewide tenancies collapse many offices into one. Spike A counted 18 statewide portals; that is
  the lever, and it is a different lever from the one D8 described.

### Scoped v1

| Parameter | Value |
|---|---|
| Jurisdictions | 200–500, stratified across platforms and BPS tiers |
| History | 2 years |
| Records | 3–8M `[F]` |
| Raw compressed | 100–200 GB `[F]` |
| Steady-state fetch | <1 req/s |
| Infrastructure | One box + object storage |

**[2026-09-19] The v1 scope is validated against the measured volume curve** `[G]` (from
`data/frame/bps_frame.csv`):

| v1 targets top N offices by volume | Share of national authorized units |
|---|---|
| 50 | 21.5% |
| 100 | 30.5% |
| 200 | 41.5% |
| 500 | **58.5%** |
| 1,000 | 71.9% |

So the scoped 200-500 jurisdictions cover roughly **42-59% of national housing volume**. That is a
strong, quotable coverage figure for a v1, and it means the reconciliation claim can be made against a
majority of national unit volume rather than a token sample. Note this is the *unit-weighted* figure -
report the jurisdiction-count-weighted and tier-2 figures beside it per section 2.

**[2026-09-19] Two structural surprises in the top of the volume distribution, both of which change how
Spike A should pick targets:**

- **Four of the ten highest-volume permit offices in the country are unincorporated county areas** -
  Harris County Unincorporated TX (15,725 units/yr, rank 2), Manatee County Unincorporated FL, Montgomery
  County Unincorporated TX, Fort Bend County Unincorporated TX. These are county permit departments, not
  city ones, and they are not Census places at all. A jurisdiction list built from city portals misses
  some of the largest issuers in the United States. D3 predicted this; the frame confirms it is
  top-of-distribution, not a tail case.
- **One portal can serve several BPS offices.** Brooklyn and Bronx boroughs are separate BPS offices
  (ranks 8 and 9) but NYC DOB is a single portal covering all five. The `source -> jurisdiction`
  relationship is many-to-many from the very top of the list, so `sources` must not assume one source
  per jurisdiction. The schema in section 4 already allows this; the crawl frontier must not undo it.

Stratify deliberately. Picking the 500 easiest jurisdictions builds a system that works on the 500
easiest.

**On infrastructure restraint:** 3 req/s does not need Kafka, Spark, Airflow, and Kubernetes. Build the
right-sized system and *document the scale-out path* — partition key, queue boundary, and the exact point
where sharding becomes necessary. Over-engineering reads as inexperience to precisely the audience worth
impressing.

---

## 7. Deliberately undecided

Do not resolve these before the spikes. They depend on spike outcomes.

- **Critical path:** template induction vs. adaptive query partitioning. Determined by Spike A.
- **Fallback strategy** for pages no synthesized extractor handles.
- **Drift detection thresholds** — what null-rate delta triggers re-synthesis.
- **Headless browser policy** — whether, when, and at what cost.
- **Backfill depth** — how far back to go, and whether it's worth it at all.
- **Address normalization** — likely needs a real geocoding dependency; unscoped.

---

## 8. Spike protocols

**This is the actionable section.** All three spikes are blocking. Together they are about two days of
work and they determine whether the project as designed is viable.

Run **Spike A first** - it determines which project this is. Run **Spike C** on Spike A's saved HTML -
it is nearly free and it tests whether the architecture has a reason to exist. Run **Spike B** - it
determines whether the headline claim exists.

**[2026-09-19] Step zero, before any of them: build the frame.** Download the place-level monthly files
(4 regions × 24 months), parse to one table, resolve the footnote/imputation flag, and compute true tier
sizes and the unit-volume distribution. This is pure scripting against public data, costs no crawling,
converts three `[F]`s in section 6 into `[G]`s, and produces the sampling frame Spike A draws from. It is
also throwaway-safe: nothing downstream depends on its implementation.

While running either spike, **save every raw HTML page fetched.** These become the seed of the golden set
and re-fetching later is wasted work.

---

### Spike A — Enumerability

**Question:** can the permit universe be enumerated by crawling, or must it be enumerated by querying?

This is not pass/fail. It selects which hard problem is on the critical path.

**[2026-09-19] The catalog sweep has been RUN, and then fully resolved by hand. Final numbers below.**

Harvested 2026-09-19 from the Socrata catalog API and ArcGIS Hub (`search/v1`), matched against the
20,069-office frame, then every unresolved publisher name was adjudicated individually.
Artifacts: `data/frame/bucket1_candidates.csv` (the matches),
`data/frame/bucket1_audit.csv` (every rejection with its reason).

| | Count |
|---|---|
| ArcGIS Hub datasets matching permit queries | 6,375 |
| ...with "building/construction permit" in the title | 851 |
| distinct publishing orgs behind those | 388 |
| Socrata permit datasets / distinct US domains | 141 / 55 |
| publisher names requiring adjudication | 443 |
| **Offices matched, confidence A+B** | **180** |
| ...their share of the 20,069 offices | **0.90%** |
| ...**their share of national authorized units** | **16.63%** |
| offices incl. confidence C (volume-disambiguated) | 183 / 16.79% |
| left deliberately unresolved (same name, no geography) | 19 |

Confidence tiers are carried in the CSV: **A** = geography-confirmed or nationally unique name,
**B** = hand-adjudicated against the county's office list, **C** = disambiguated only by picking the
higher-volume office among same-name candidates. Quote A+B; mention C separately or not at all.

**[Correction] The earlier figure in this section - 112 offices / 5.0% of units - was a substantial
undercount, and the unit figure was the part that mattered.** Resolution by hand roughly tripled measured
unit coverage, from 5.0% to 16.63%. The office count barely moved (0.56% -> 0.90%); what changed is that
the misses were concentrated in the *largest* publishers, because large jurisdictions are exactly the ones
whose publisher name does not look like their Census place name. New York City alone (five borough
offices, ~27,300 units) was missing because the frame has no office called "New York".

**What the resolved sweep establishes:**

- **Bucket-1 jurisdictions are ~18x overrepresented in volume** - 0.90% of offices, 16.63% of units.
  Measured confirmation of the tier-tension thesis in section 2, and about twice as strong as the first
  pass suggested.
- **Crawling is still unavoidable.** ~99% of offices and ~83% of national units are not in bucket 1. The
  ceiling on offices via this route stays near **448, ~2.2% of the universe**.
- **Spike A's manual half is still MORE important, not less.** Enumerability is decided in buckets 2-5,
  and nothing about buckets 2-5 is visible from a catalog.

**What the 443 names actually contained** - worth recording, because the composition is the finding:

| Class | n | Disposition |
|---|---|---|
| Matched to a BPS office | 180 | bucket 1 |
| Personal ArcGIS accounts (`jsmith_gis`, student emails) | 90 | rejected |
| Non-government (consultancies, universities, a permits startup) | 42 | rejected |
| State / federal / regional agencies (DOT, EPA, COGs, MPOs) | 34 | rejected |
| Non-US (27 confirmed via `region` on the org record, rest by centroid) | 52 | rejected |
| Statewide portals, not a single office | 18 | rejected |
| **Real publisher, but BPS has no office at that level** | **9** | rejected |
| Unidentifiable / ambiguous | 22 | unresolved |

One whole class of ArcGIS "publishers" turned out to be a Boise State GIS course: seven student accounts
publishing coursework that matches a permit-title query. **Any catalog-derived count that does not filter
personal accounts is inflated**, and by a lot - they were 20% of all publisher names here.

**Spend the manual budget only where automation cannot reach.** Draw the Spike A manual sample from the
~19,890 offices the sweep does not resolve.

### Entity resolution

Three separate entity-resolution problems live in this project - office identity, publisher linkage, and
permit identity - with different keys and different error tolerances. The catalog sweep conflated them
and produced a wrong number twice as a result.

**Moved to [`docs/design/entity-resolution.md`](docs/design/entity-resolution.md)**, which carries the
linkage method, the many-to-one structural finding (Mecklenburg/Charlotte, the five NYC boroughs,
Memphis, Fulton County), the recurring county/municipality trap, and the full `source` /
`source_office_link` schema. The decisions behind that schema are fixed in
[ADR-0001](docs/adr/0001-source-office-link-is-an-evidence-bearing-relation.md),
[ADR-0002](docs/adr/0002-no-mirror-relation.md) and
[ADR-0003](docs/adr/0003-jurisdiction-identity-is-bps-scoped.md).

Two consequences are load-bearing here and repeated so this section stands alone:

- **D5 inherits the many-to-one finding.** One portal can cover five borough offices, so
  `observation_key` must carry the office, not the portal, or permits from different offices collide in
  one key space.
- **Spike B inherits it too.** Reconciling a city portal against "the BPS figure for that city" is
  incoherent where no such office exists. Sample only offices whose boundary matches a real source.

**Sample:** 25–30 jurisdictions, **stratified, not uniform random**:

- ~10 from the top BPS unit-volume decile (tier-1)
- ~10 mid-volume tier-1
- ~8 tier-2 (imputed, <6 avg annual units)
- Spread across at least 8 states and both coasts + interior

Draw the frame from the BPS place-level annual file. Verify the file's actual layout rather than assuming
field names.

**For each jurisdiction, classify the portal into exactly one bucket:**

| # | Bucket | Implication |
|---|---|---|
| **0** | **No permit is issued; no record exists at any level** | **Not a coverage gap.** Changes the denominator, not the numerator. |
| 1 | Bulk download or documented API (Socrata, ArcGIS, CKAN, open data portal) | Free and perfect. Best case. |
| 2 | Browsable index — paginated list, no query required | Template induction is the problem. |
| 3 | Search-only, but empty / wildcard / date-range query returns everything | **Effectively enumerable.** Easy to miss — test it explicitly. |
| 4 | Search-only, requires a known address / parcel / permit number | Query enumeration becomes critical path. |
| 5 | JS-gated, no accessible endpoint without a browser | Headless cost dominates. |
| 6 | No online portal found | Coverage ceiling. Record exists, offline. |
| **7** | **Portal exists, behind registration or login** | **Permission, not technique.** A browser does not help. |

**Buckets 1–6 are an ordered ladder of acquisition difficulty. Buckets 0 and 7 are off-ladder terminal
states** — do not read 0 as "worse than 6" or 7 as "worse than 6". Both were added by measurement; see
[ADR-0004](docs/adr/0004-bucket-taxonomy-gains-a-no-record-and-an-access-gated-cell.md).

**Report the distribution in three aggregates, never one number:** enumerable (1–3), acquirable with work
(4–5), blocked (6, 7) — and bucket 0 *separately from all three*, because it shrinks the denominator.

**Bucket 0 requires a positive basis, never absence of evidence** — a statutory exemption, or the
jurisdiction saying no permit is required. "We could not find anything" is bucket 6. Bucket 0 is the only
cell that *improves* the coverage statistic by being assigned, so it carries the strictest evidence bar.

**Bucket 3 is the one people miss.** Many nominally search-only portals accept an empty criteria set or a
broad date range. Test this deliberately on every bucket-4 candidate before classifying it as 4. Note
from the tier-2 rerun that this is a **per-tenancy** setting even within one vendor: two Accela instances
accepted empty criteria and a third rejected them, so read the rendered form rather than assuming.

**Also record, per portal:**

- **Result cap** — does the index truncate at N results? *This matters more than it appears:* a capped
  index is not enumerable without partitioning queries until each partition falls under the cap.
- Pagination style (offset, cursor, page number) and whether deep pages remain accessible
- `robots.txt` posture, and any ToS language about automated access
- Platform vendor fingerprint (Accela, Tyler EnerGov, CivicPlus, OpenGov, eTRAKiT, custom)
- Whether detail pages have stable, constructible URLs
- **Which fields appear on the index vs. only on detail** — specifically `unit_count`, `work_class`,
  `valuation`, `status`. This drives the fetch-amplification factor and therefore all of section 6.
- Approximate record count visible, and earliest date available

**Decision thresholds.**

**[2026-09-19] The original weighting was wrong and the original thresholds were unresolvable at this
sample size.** Two corrections, both load-bearing:

*On weighting.* Unit-volume weighting lets a handful of large jurisdictions determine the answer, and
large jurisdictions are the easy ones (see the tier-tension note in section 2). A unit-weighted bucket
distribution will look encouraging even in the world where every tier-2 portal is bucket 5 or 6 - which
is the world where the project has no contribution. **Report the distribution three ways: unit-weighted
over the whole sample, count-weighted over the whole sample, and count-weighted over tier-2 alone. The
tier-2 count-weighted figure drives the decision.**

*On power.* At n=25–30 a proportion carries roughly ±18pp of sampling error, and under unit-weighting
the effective n for the weighted figure is closer to 10. A 60%-versus-30% threshold cannot be resolved
there. Either raise n cheaply via the catalog sweep above, or read the thresholds below as *directional
indicators requiring a written judgment call*, never as a computation. Do not report a weighted
percentage to two significant figures off 28 observations.

- **Buckets 1–3 ≥ 60%** → proceed as designed. Template induction is the critical path.
- **Bucket 4 dominant** → the critical path becomes **adaptive query partitioning**: recursively split
  date ranges to stay under an unknown result cap while minimizing total requests, per host, with the cap
  discovered empirically. This is a *better* algorithmic story than template induction, not a worse one —
  do not treat it as failure. Re-plan around it.
- **Bucket 5 heavy** → headless browser cost dominates the budget. Major re-scope needed; compare against
  procurement as an alternative domain before committing.
- **Buckets 1–3 < 30%** → permits is likely the wrong domain. Revisit procurement.
  **[2026-09-20] SUPERSEDED by the revised gate immediately below.** Left in place rather than edited,
  because a threshold revised *after* it trips has to show its own history or it is worthless.

#### [2026-09-20] The revised gate

Spike A and the tier-2 rerun both put tier-2 count-weighted buckets 1–3 at **0 of 8**, tripping the rule
above on a number that survived being re-measured at the correct jurisdictional level. **It is not being
fired.** The reason is not that the result is inconvenient; it is that the rule was found to measure
something other than what it was written to measure. Three defects, each on its own fatal to the rule as
stated:

1. **It counts offices, and offices are not what gets covered.** Tier-2 is 28.6% of sample offices and
   **0.05% of sample units** (6 of 12,932). The rule was written to catch *"permit data is
   unreachable."* What it caught is *"the smallest issuing bodies in America have no software"* — true,
   already known, and nearly weightless in any metric a user cares about.
2. **Its denominator counts records that do not exist.** Bucket 0 — no permit is issued at all — was
   discovered after this rule was written ([ADR-0004](docs/adr/0004-bucket-taxonomy-gains-a-no-record-and-an-access-gated-cell.md)).
   Eastbrook ME issues no permits and its single BPS unit is *imputed*. A denominator that treats
   non-existent documents as uncovered can be driven arbitrarily low by sampling more small towns, and
   no amount of engineering moves it.
3. **It is unresolvable at this n.** 0 of 8 carries a rule-of-three 95% upper bound near 38%, which
   spans the 30% line from both sides. The rerun removed a *bias*; it did not shrink the *interval*.

**The replacement. It binds exactly as the old rule did.**

- **Bucket 0 leaves every coverage denominator and is reported on its own line.** Coverage is
  `offices covered ÷ offices that issue a permit at all`. Bucket 0 is an *existence* fact about the
  world — reported as "N sampled offices issue no permit; their BPS units are imputed" — and is never
  netted into a coverage percentage in either direction. This is ADR-0004's positive-basis rule reaching
  the gate: bucket 0 is the one assignment that flatters the statistic, so it may never be inferred from
  a failure to find something.
- **The halting metric is unit-weighted reachability over permit-issuing offices.** Reachable = buckets
  1–5 (enumerable, or acquirable with known work). **Below 50% → the domain is wrong; revisit
  procurement.**

  | Aggregate | count% | **unit%** |
  |---|---|---|
  | Enumerable (1–3) | 7.4% | 28.5% |
  | Acquirable with work (4–5) | 14.8% | 44.6% |
  | **Reachable (1–5) — the gate metric** | **22.2%** | **73.1%** |
  | Blocked (6–7) | 70.4% | 21.1% |
  | Unresolved | 7.4% | 5.9% |
  | *Bucket 0 — reported separately, excluded above* | *n=1* | *1 unit* |

  **Current value 69.5%. The gate does not fire.** `[2026-09-21]` The table above is the 2026-09-20
  state and is kept for the arithmetic; **both revisions below supersede it.** 73.1% held after the
  St. Johns reclassification, which moved a row *within* the reachable set; it then fell to 69.5%
  when Bowling Green was demonstrated to publish no permit records at all.
- **The tier-2 count-weighted figure is retained as a reported diagnostic and demoted from a threshold.**
  It answers "can this project say anything about small jurisdictions" — a real question whose honest
  current answer is *no, and partly because for some of them there is nothing to say*. It does not
  answer "is this domain worth working in," which is the only thing a gate is for.
- **A named-office test is added and it outranks everything above.** Coverage of the specific offices a
  prospective user names is the only one of these numbers with an external consumer. Until that list
  exists the gate is **unresolved, not passed**, and no amount of favourable sampling changes that.

**What this revision does not do.** It does not move a line in order to clear it, and it does not make
the gate softer. It relocates the load-bearing risk, and names it: **73.1% depends entirely on bucket 4
being acquirable.** If adaptive query partitioning fails, or costs more than the budget allows, reachable
collapses to buckets 1–3 plus 5 = **39.2% unit-weighted, which is below 50% and fires the gate.**

So the next gate-relevant measurement is no longer template collapse — Spike C settled that — it is
**whether bucket-4 portals can be enumerated by partitioned querying within budget.** That is now the
single most decision-relevant unknown in this document, and nothing in sections 9–10 currently schedules
it.

**[2026-09-20] The bucket-4 dependency is partly discharged, and the paragraph above is now half
answered.** Step 1 pulled **St. Johns County FL** — classified bucket 4 by Spike A from its rendered
search form — and enumerated the entire county from a date range alone: **3,627 records in 28 requests,
zero truncations, zero bisections.** That is the bucket-3 definition. Full report:
[`docs/evidence/2026-09-20-step1-stjohns-reconciliation.md`](docs/evidence/2026-09-20-step1-stjohns-reconciliation.md).

St. Johns is 3,637 of bucket 4's 4,386 units — **83% of the bucket.** Recomputed over the same 28-office
sample, bucket 0 excluded from the denominator (n=27, 12,931 units):

| Aggregate | before | **after** |
|---|---|---|
| Enumerable (1–3) | 28.5% | **56.7%** |
| Acquirable with work (4–5) | 44.6% | 16.4% |
| **Reachable (1–5) — the gate metric** | **73.1%** | **73.1% — unchanged** |
| bucket 3 / bucket 4 | 28.5% / 33.9% | **56.7% / 5.8%** |
| **Fallback floor (1–3 plus 5), if partitioning fails** | **39.2% — fires** | **67.3% — does not fire** |

**The gate metric itself does not move** — a row travelling from 4 to 3 stays inside "reachable". What
moves is the **fallback floor named two paragraphs above**: 39.2%, below the 50% line, is now 67.3%,
above it. **The gate no longer fires on bucket-4 failure**, which was the single stated load-bearing risk
of this revision.

**Three things this does not mean, and they matter more than the number does.**

1. **Bucket-4 portals have not been shown to be enumerable.** St. Johns was *misfiled*, not cracked. The
   pull proved a classification wrong; it did not prove a capability against a portal that genuinely
   demands a known address. The two remaining bucket-4 rows — 749 units, 5.8% — are untested, and are now
   the cheapest measurement that can still move this number. **`[2026-09-21]` Both have since been
   tested and neither was cracked either — one is genuinely parcel-keyed, the other is not a
   permit-record portal at all — so this paragraph's claim stands unchanged: no bucket-4 portal
   has been shown enumerable by this project. See the revision below.**
2. **One row of 28 carries 28% of the sample's units.** A 39.2 → 67.3 swing from a single
   reclassification is not a robust statistic. It is a demonstration that a unit-weighted percentage over
   28 offices cannot carry a halting decision by itself.
3. **The classification error runs one way.** Reading a form can only *under*-classify: a portal that does
   enumerate can look like one that does not, but not the reverse. So 28.5% was a lower bound — and 56.7%
   is one too.

[ADR-0005](docs/adr/0005-a-bucket-is-demonstrated-not-inferred-from-the-search-form.md) makes this
binding. A bucket read off a form is **provisional**; only a demonstrated pull **confirms** one. And the
unit-weighted metric **may fire the gate but may not clear it** — at this n it is precise enough to catch
a domain that is obviously unreachable and nowhere near precise enough to certify one that is reachable.
Clearing still requires the named-office test.

**[2026-09-21] Bucket 4 is resolved, and the number went down.** Both remaining bucket-4 offices were
probed. Full report: [`docs/evidence/2026-09-21-bucket4-resolution.md`](docs/evidence/2026-09-21-bucket4-resolution.md).

- **Bowling Green KY** (458 units) is **not bucket 4, and never was a permit-record source at all.** Its
  portal is Tyler eSuite at `esuites.bgky.org` — not the unreachable `www2.bgky.org` the classification
  recorded — and its own front page says it "allows licensed contractors to apply for Electrical permits
  and make payment". Contractor login, no search, no records. Recorded **bucket 7**. *The real host was
  in Spike A's own saved bytes the whole time; finding it cost zero requests.*
- **St. Louis MO** (291 units) is **bucket 4, demonstrated.** Empty and wildcard queries are both
  refused; a known address returns a parcel-disambiguation table, not permits. Its new 2026 portal,
  `stlcitypermits.com`, turns out to be an apply-and-pay catalogue with no record search either.

| Aggregate | 2026-09-20 | **2026-09-21** |
|---|---|---|
| Enumerable (1–3) | 56.7% | **56.7%** |
| Acquirable with work (4–5) | 16.4% | **12.9%** |
| **Reachable (1–5) — the gate metric** | **73.1%** | **69.5%** |
| Bucket 4 alone | 5.8% | **2.3%** |
| Fallback floor (1–3 plus 5) | 67.3% | **67.3% — unchanged** |
| **Confirmed-reachable alone** | — | **58.9%** |

**The load-bearing risk this section named is retired.** A few paragraphs above, this document says
"73.1% depends entirely on bucket 4 being acquirable." Bucket 4 is now **2.3% of units and one office**.
Whether parcel-keyed portals can be enumerated is still unknown, and it no longer matters to the gate.

Three things this revision adds that the previous one could not say:

1. **The headline fell on evidence, 73.1% → 69.5%.** A revision process that only ever revises upward is
   not measuring anything. This one cost 3.6 points.
2. **The gate survives its own provisional rows.** `classification.csv` now carries a `status` column per
   ADR-0005. Five offices are `confirmed` — settled by a query whose *response* decided the bucket — and
   those five alone are **58.9% reachable**, above the 50% line. Every one of the 23 provisional rows
   sits in an *unreachable* bucket, so provisional error can only move the number **up**.
3. **All of the enumerable mass is confirmed.** 56.7% enumerable is 56.7% confirmed-enumerable.

**What still does not clear the gate.** ADR-0005's rule is unchanged: the metric may fire but may not
clear. 69.5% is a lower bound for the same one-way reason 73.1% and 28.5% were. Clearing requires the
named-office test, which does not exist.

**A gap the taxonomy now has.** Both offices probed here run modern, well-built **apply-and-pay** portals
that publish no permit records whatsoever, and both would read as healthy portals to any vendor-detection
sweep. Bucket 7 — "permission, not technique" — is the closest cell and does not fit: registering as a
Bowling Green contractor would yield no records, because there are none to yield. A defect in ADR-0004's
taxonomy, recorded and not yet fixed.

**Time budget:** **[2026-09-19] one full day, revised up.** Half a day across 25–30 portals is ~10
minutes each to locate the portal, fingerprint the vendor, probe empty-query behavior, probe the result
cap, walk pagination, and record per-field index-vs-detail availability. That is optimistic by roughly
2–3x. The catalog sweep is what buys the time back, not working faster.

**Deliverable:** a table of 25–30 rows with the fields above, the bucket distribution reported all three
ways, and a one-paragraph recommendation.

### [2026-09-20] Spike A has been RUN. n=28. Full report: [`docs/evidence/2026-09-20-spike-a-portal-enumerability.md`](docs/evidence/2026-09-20-spike-a-portal-enumerability.md)

Cost: **$0** - every step is scripted HTTP, no model calls. 77 HTML pages saved (8.9 MB); Spike C's input
now exists.

| bkt | meaning | n | count% | unit% |
|---|---|---|---|---|
| 3 | search-only **but** broad query returns everything | 2 | 7.1% | 28.5% |
| 4 | search-only, needs a known address/parcel/permit no. | 3 | 10.7% | 33.9% |
| 5 | JS-gated | 1 | 3.6% | 10.6% |
| 6 | no online portal found | 16 | 57.1% | 10.2% |
| **7 [NEW]** | **portal exists, behind registration/login** | **4** | **14.3%** | **10.9%** |
| - | unresolved, not guessed | 2 | 7.1% | 5.9% |

**The three weightings, buckets 1-3 = enumerable: unit-weighted 28.5%, count-weighted 7.1%,
tier-2 count-weighted 0.0% (0 of 8).**

**Four findings:**

1. **Accela accepts an entirely empty search criteria set and returns records.** Mechanically confirmed
   at two independent instances - Clark County NV and Oregon's statewide portal - both returning
   `100+ Record results` with real record ids. Accela is the largest US local-government permitting
   vendor, so **every Accela agency is a bucket-3 target, not the bucket-4 target it appears to be.**
   The `100+` is a display cap, so enumeration still needs date partitioning.
2. **Statewide vendor instances are the strongest cost-per-office lever found so far.** McMinnville is
   served by `aca-oregon.accela.com`, one tenancy covering many Oregon jurisdictions. Mirrors the 18
   statewide portals from the catalog sweep.
3. **The three-way reporting rule earned its place.** The same sample reads 28.5% enumerable
   unit-weighted and 0% on tier-2 count. Any single headline number would have been actively misleading.
   This is the clearest empirical vindication of a design decision made before the data existed.
4. **The 6-bucket taxonomy has a missing cell.** 14% of portals are neither JS-gated nor absent - they
   are behind registration (Avolve ProjectDox, SagesGov, CommunityCore, iWorQ). Proposed as **bucket 7**:
   unlike bucket 5 a browser does not help, and unlike bucket 6 the data demonstrably exists.

**[Do not act on the tripped threshold.]** Tier-2 count-weighted 0% crosses the
`buckets 1-3 < 30% -> revisit procurement` line. It should not be acted on yet, for one serious reason
and three supporting ones:

- **The classification may be measuring at the wrong jurisdictional level, and the bias runs one way.**
  For tier-2 places the issuing function is often the county's or a contractor's, and this spike looked
  for a portal at the *place* level. Ontelaunee PA issues through `kraftcodeservices.com`, a private
  firm; Amador City CA staffs its office nine hours a week while Amador County runs a portal. **This is
  the many-to-one structural finding reappearing, and it biases the deciding figure downward.**
- A 0-of-8 result is not 0%: the rule-of-three 95% upper bound is ~37%, which spans the threshold.
- The portal-location method demonstrably misses - Galloway Township NJ (pop 35,487) was never located.
- Some bucket-6/7 rows may be access-gating, not absence; iWorQ 403s an identified research client.

**Recommendation: re-run tier-2 classification at the level that actually issues the permits** before
approaching the gate. Half a day, $0, and it either overturns the 0% or confirms it with the systematic
bias removed.

### [2026-09-20] The tier-2 rerun HAS BEEN RUN. Full report: [`docs/evidence/2026-09-20-tier2-issuing-level-rerun.md`](docs/evidence/2026-09-20-tier2-issuing-level-rerun.md)

Cost: **$0**. Every tier-2 row was re-probed at the body that actually issues its permits.

**The 0% survives, and the argument made against it above does not.** All three weightings are
unchanged (28.5% / 7.1% / 0.0%). Only one row moved bucket. The worked example used to doubt the
figure is disproven: Amador County's building department serves the *unincorporated* county, so it
never covered Amador City.

| Issuing level | n | places |
|---|---|---|
| the place itself | 4 | Wapato, Brownville, Kotzebue, Garden City |
| place + private contractor | 2 | Ahnapee, Amador City |
| parent town | 1 | Dresden village -> Town of Torrey |
| **nobody - no permit is issued** | **1** | **Eastbrook** |
| the county | **0** | - |

**Why the county never helps.** County permit portals are scoped to unincorporated area and BPS places
are incorporated: the two partition the same territory. Weld County says so in its own page metadata -
*"permits on parcels located in unincorporated Weld County"*. Yakima County runs Accela, but all ten
first-page records for `city=WAPATO` are rural addresses (US Hwy 97, Fort Rd, Campbell Rd) - the city
itself publishes a PDF application and takes permits at City Hall.

**A bucket is missing at the bottom of the scale, not just the top. Proposed bucket 0: no permit is
issued at all.** Maine mandates MUBEC enforcement only at 4,000+ population; ~370 of its 488
municipalities fall below. Eastbrook (pop 416) has a town website with **zero occurrences of "permit",
"code" or "build"**, and BPS carries 1 *imputed* unit for it. That unit was never a permit document
anywhere. Bucket 6 says the record is offline; bucket 0 says there is no record. Part of the tier-2 gap
is therefore not a coverage problem and cannot be closed at any price.

**Two corrections to claims made above.**

1. **"Every Accela agency is a bucket-3 target" is too strong.** Yakima's tenancy renders an
   address-shaped general search with no date fields and returns nothing for empty criteria, where
   Clark County and Oregon return records. Empty-criteria search is a per-tenancy setting. An
   extractor must read the rendered form rather than assume field names.
2. **The no-result detector was giving false negatives.** Accela ships `Please enter a key word with
   more than 2 characters.` as a JavaScript constant on *every* page, including pages returning 100+
   records. `spike_a_query_probe.py` now strips `<script>` before matching and treats a rendered
   result list as decisive. This is the second time this exact string has nearly inverted a finding.

**[The gate should be revised, not fired.]** `buckets 1-3 < 30% -> wrong domain` is now tripped on a
correctly measured number. But the tier-2 stratum is **28.6% of sample offices and 0.05% of sample
units** (6 of 12,932). The rule was written to catch "the permit data is unreachable"; what was found
is "tier-2 permits are issued by micro-entities with no software, and sometimes not issued at all".
The threshold is measuring reachability and scoring it as value. It should be rewritten to ask a
question worth halting on - unit-weighted coverage, or coverage of the offices a customer names -
before it is consulted. Note also that 0 of 8 still carries a rule-of-three upper bound near 38%:
the rerun removed a *bias*, it did not shrink the *interval*.
**[2026-09-20] Done — see "The revised gate" in the Spike A protocol above.** Bucket 0 is out of the
denominator, the halting metric is unit-weighted reachability (**69.5% `[2026-09-21]`**, does not fire), tier-2
count-weighted is demoted to a diagnostic, and a named-office test now outranks all of them. On the critical path, evidence so far favours **adaptive query partitioning over template
induction** - buckets 4 and 3-with-a-cap were 17.8% by count and 62.4% by units at the time, and both need
partitioning rather than page templates. Spike C is the next cheapest step and its input already exists.

**Method note worth carrying forward: the URL-pattern probe had a 75% false-positive rate** (21 of 28
rejected by the verifier). `Bowling Green KY` matched a Virginia town, `Brazil IN` the country,
`Amador City CA` a person's homepage. This is the Marina/Marin error from the catalog sweep in a new
form, caught this time by an automated verifier scoring each hit against attributes a name cannot fake.
**Name-similarity matching keeps failing in this project; the fix is always an authoritative attribute.**

---

### Spike C — Template collision rate `[2026-09-19]`

**Question:** do ~20,000 portals actually collapse onto a few hundred templates, or does every
jurisdiction render its own thing?

**Why this exists.** D8 asserts that keying the template cache on DOM structure rather than domain
"collapses the amortization denominator from ~20,000 sites to plausibly a few hundred distinct vendor
templates `[F]`." Every cost figure in section 6 and the headline amortization ratio in section 5 rest on
that one sentence, and **nothing in the original spike plan tested it.** Spike A records a *vendor name*,
which is not the same claim: two Accela tenants can be themed and configured into structurally different
pages, and the cache is keyed on structure. The naive prior also cuts against the claim - small towns
having bespoke sites is exactly what you would expect of small towns.

**Why it runs now rather than at step 4.** Under the current scope target step 4 is near-term, not
hypothetical. A premise check is worth most when it can still redirect the work it underwrites, and this
one costs a few hours against HTML that Spike A saves anyway. Discovering at step 4 that templates do not
collapse means having built the synthesis path to find out.

**Cost: near zero.** It runs over the HTML Spike A already saves. No additional fetching.

**Procedure:**

1. For each saved index page, compute a structural fingerprint: normalized DOM skeleton with all text
   content, attribute *values*, and IDs stripped; shingle over root-to-leaf tag paths; hash.
2. Compute the same over detail pages, separately - index and detail templates collapse differently and
   conflating them will flatter the result.
3. Report **distinct fingerprints ÷ distinct jurisdictions**, and the fingerprint cluster size
   distribution.
4. Cross-tabulate fingerprint against the vendor label from Spike A. **The interesting cell is
   same-vendor / different-fingerprint** - that is the cell that decides whether vendor identity is a
   usable proxy for template identity or a misleading one.
5. Report the same figures for tier-1 and tier-2 separately. Tier-2 is the population that matters and
   is the one most likely to fragment.

**Decision thresholds** (on tier-2, not the pooled sample):

- **Median cluster size ≥ 3, or fingerprints ÷ jurisdictions ≤ 0.4** → the amortization story holds at
  this scale. Proceed to step 4 as planned, and report reuse rate as a headline number alongside the
  ratio.
- **Fingerprints ÷ jurisdictions between 0.4 and 0.8** → partial collapse. Amortization is real but the
  20–60x range in section 6 is too optimistic; re-derive it from the measured cluster distribution before
  it goes in any writeup, and re-scope step 4 against the lower number.
- **Fingerprints ÷ jurisdictions > 0.8** (near 1:1, e.g. 26 templates across 28 jurisdictions) →
  **the core technical claim is dead as stated.** Templates do not amortize across jurisdictions, and
  per-jurisdiction amortization alone is ~3x, which is not a project. **Step 4 must be re-planned before
  it is built, not after.** The likely replacement is to key synthesis on vendor-plus-config rather than
  pure structure, or to abandon synthesis for adapter generation with human review - but decide that
  against the measured cluster distribution rather than in advance.

**Caveat on n.** 28 jurisdictions cannot measure a collapse ratio over 20,000, and no threshold above
should be reported as a national figure. What Spike C can do is *falsify* the claim cheaply: near-1:1
collision at n=28 is strong evidence against collapse, while low collision at n=28 is only weak evidence
for it. Treat it as a one-sided test and state it that way.

**Time budget:** two to three hours, entirely offline. **Deliverable:** the ratio, the cluster size
distribution, the vendor cross-tab, and a go / re-derive / re-plan verdict on step 4.

### [2026-09-20] Spike C has been RUN. Verdict: **RE-PLAN step 4.** Full report: [`docs/evidence/2026-09-20-spike-c-template-collision.md`](docs/evidence/2026-09-20-spike-c-template-collision.md)

Cost: **$0** - offline, stdlib only, no fetching and no model calls.

**Fingerprints / jurisdictions = 1.00 on tier-2 and 1.00 pooled, at every clustering threshold down to
Jaccard 0.60. Median cluster size is 1 in every corpus. Nothing merges.** That crosses the
`> 0.8 -> the core technical claim is dead as stated` line set in advance.

| Corpus | juris | exact fps | ratio | at J>=0.60 |
|---|---|---|---|---|
| Municipal websites | 22 | 22 | **1.00** | **1.00** |
| Permit portal landing pages | 23 | 23 | **1.00** | **1.00** |
| Tier-1 sites | 14 | 14 | **1.00** | **1.00** |
| **Tier-2 sites - drives the decision** | **8** | **8** | **1.00** | **1.00** |
| Permit result-index pages | 3 | 3 | 1.00 | 0.67 |

**The instrument was validated before its verdict was believed**, because a ratio of 1.00 is equally
consistent with a real finding and a broken fingerprint. Positive control (same portal, two queries)
scores **0.808-0.992**; 4,782 cross-jurisdiction pairs have median **0.036** and p95 **0.077**. The
fingerprint discriminates by an order of magnitude, so same-vendor pairs landing near baseline are a real
absence of collapse.

**The constructive finding: vendor cohorts are real, pure structure is not the key.** Clark County NV and
Yakima County WA Accela result pages score **0.766** - near the positive-control floor. Oregon, also
Accela, scores **0.155** and **0.213** against them, because it is a statewide tenancy with its own skin.
Two CivicPlus permits pages of matched type score **0.255** - above baseline, far below reuse. So
**vendor identity alone is a weak proxy for template identity**, and the replacement is synthesis keyed on
**vendor + version + configuration**, with cohorts discovered by clustering rather than assumed.

**The denominator was wrong anyway.** D8 amortizes across ~20,000 sites, but 15 of 28 sampled
jurisdictions have no portal and one issues no permit; only **~36% of the sample has a portal to
template** at all. The real denominator is ~7,000 offices, and those are the vendor-concentrated ones.
**The 20-60x amortization range in section 6 is not supported by anything measured and should not appear
in a writeup until re-derived from cohort structure.**

**A constraint on D1 fell out of this.** Spike A saved every page it fetched, including the 15 its own
verifier rejected, and the first run of this analysis silently fingerprinted an iron castings foundry as
a municipal website. Provenance did not travel with the bytes. **The observation log must store the
verification verdict alongside the raw bytes, and folds must filter on it**, or every downstream analysis
re-admits rejected data by default. 25 of 100 saved pages were dropped by the trust filter.

**[What this does NOT settle.]** The corpus holds **5 result-index pages across 3 jurisdictions, all
Accela, and zero detail pages** - Spike A never fetched an individual permit record. The protocol asks
for index and detail fingerprinted separately, so the 1.00 headline rests mainly on municipal websites
and portal landing pages, which are a *proxy* for the D8 claim rather than the claim itself. Two cheap
measurements should precede the re-plan: **fetch result and detail pages from the bucket-3 portals**
(~20-40 requests) and **measure Accela cohort size** across more tenancies, since that single number
carries most of the amortization estimate.

### [2026-09-20] Measurements A and B have been RUN. Full report: [`docs/evidence/2026-09-20-measurement-ab-results.md`](docs/evidence/2026-09-20-measurement-ab-results.md)

Rules fixed in advance: [pre-registration](docs/evidence/2026-09-20-measurement-ab-preregistration.md).
Cost: **$0 inference**, 42 HTTP requests against a pre-registered ceiling of 60.

**Spike C's 1.00 does not generalise to the page types an extractor actually sees.** Spike C ran on
municipal home pages and portal landing pages with zero detail pages, and said so in its own limits
section. Measured now on the real page types:

| Page type | low mode | high mode | high-mode pair |
|---|---|---|---|
| `T-INDEX` | n=15, 0.150-0.213 | **n=6, 0.752-0.766** | Clark County NV ~ Yakima County WA |
| `T-DETAIL` | n=8, 0.124-0.167 | **n=4, 0.737-0.768** | Clark County NV ~ Yakima County WA |

**The distribution is bimodal, so the median is a lie.** One tenancy pair in three collapses at ~0.75
while the other two sit near 0.15. The cohort boundary is a cliff, not a gradient. Detail pages behave
identically to index pages - same cliff, same members.

**Accela cohort size is a curve, and the curve is the finding.** 16 tenancies, one search page each:

| J >= | 0.95 | 0.90 | 0.80 | 0.70 |
|---|---|---|---|---|
| clusters | 16 | 14 | **6** | **2** |
| mean cohort size | **1.00** | 1.14 | **2.67** | **8.00** |

Spike C's equivalent curve was **flat at 1.00 from 0.95 down to 0.60** - nothing ever merged. Accela's
fleet is steep. That is the difference between *cohorts do not exist* and *cohorts exist and their
boundary depends on how much drift an extractor tolerates.* **Which threshold is right cannot be settled
by structure.** Read literally, the pre-registered rule clusters at C1 = 0.984 and returns cohort size
**1.00**; at a plausible working tolerance of 0.80 it returns **2.67**. Both are reported because the
difference is a real unknown, not a choice.

**Three findings that were not the question:**

1. **The amortization unit is the tenancy, not the vendor and not the jurisdiction.** Two *different*
   Oregon jurisdictions - the City of Talent and Marion County - served by one statewide Accela tenancy
   render permit detail pages at **J = 0.863**. That is the cross-jurisdiction reuse D8 claimed and
   Spike C could not find; it lives inside statewide tenancies. Spike A's catalog sweep already counted
   **18 statewide portals**. One pair, so this needs a direct test before any cost model leans on it.
2. **Each tenancy needs at least two extractors, not one.** Index and detail pages of the *same* portal
   score **0.19** against each other. No cost estimate in section 6 has ever counted this multiplier.
3. **The open question is now an extraction question, not a structure question.** "How much structural
   drift does a synthesized extractor tolerate?" is answerable in step 2 against the golden set, and it
   converts the cohort curve into one defensible number.

**Two controls are worth recording as method.** The negative control **failed its pre-registered
expectation** - p95 0.802 against an expected ~0.08 - because the corpus is mono-vendor by construction,
so its "cross-jurisdiction" pairs are mostly same-vendor pairs. Using it would have been circular and
would have mechanically returned "no collapse" for everything; Spike C's heterogeneous 0.077 was used
instead and both are reported. And **C4, the cross-vendor control, could not be run at all** - there is
no non-Accela result-index page in the corpus - so the confound *"index pages look alike merely because
they are index pages"* remains open. All of this is a measurement **of Accela**, not of municipal permit
portals.

---

### Spike B — BPS reconciliation feasibility

**Question:** can portal-visible permit data actually be aggregated into something comparable to Census
unit counts?

This underwrites the best claim in the project and is completely untested.

**[2026-09-19] Half of this spike is now mechanical.** The comparison target is a CSV download (section
2), published monthly, at place level, already split by structure type. Steps 1, 4 and 5 below are a
script. The manual effort belongs entirely in steps 2 and 3 - deciding what counts as new residential
construction from portal data, and finding unit counts - which is where the real uncertainty was all
along.

**[2026-09-19] CRITICAL - the comparison target is itself imputed most of the time, and the original
protocol would have silently scored against it.** `Source` is per-place-month (section 2). A tier-1
jurisdiction is *not* reliably reported: **41.7% of the place-months of offices averaging >=6 units/yr
are imputed or absent.** Computing `|ours - BPS| / BPS` against a Source-5 month compares our
observation to Census's model and books the difference as *our* extraction error. That would have
corrupted the headline metric in a direction that flatters nothing and explains nothing.

**Two binding rules for the sample:**

1. **Draw only from the 2,916 offices with a fully reported 24-month history** `[G]` - 33.2% of the
   >=6 units/yr set. These are the only jurisdictions where every month is a true oracle. The frame
   built in step zero identifies them directly. (Earlier drafts said 2,918; recomputed from
   `data/frame/bps_frame.csv` the figure is **2,916**, matching the claims table in section 9.)
   **[2026-09-20] Those 2,916 offices carry 54.9% of national authorized units** `[G]`, and the ten
   largest include Los Angeles, Harris County Unincorporated TX, Houston and Phoenix. The clean-oracle
   set is not a fringe to calibrate on and then extrapolate from - it *is* the majority of national
   volume, which makes the reconciliation claim considerably stronger than "a sample of well-behaved
   small places" would be. Say so in the writeup.
2. **Filter per month, not just per jurisdiction.** Even within the sample, check `Source` for each
   specific month used and drop any month that is 5 or 9.

Report `n` months actually compared alongside the error figures - a median over 15 months is a different
claim than a median over 4.

**[2026-09-19] Add a sixth jurisdiction from tier-2.** The original sample is tier-1 only, which is
correct for *calibration* - tier-1 is the only tier with a self-reported figure to score against. But it
means the spike never touches the population the project claims to contribute to, and a tier-2 portal
may fail on unit counts for reasons no tier-1 portal exhibits. The tier-2 jurisdiction produces no error
figure; it answers the field-availability questions only. Record it separately and do not pool it into
the median.

**Sample:** 5 tier-1 jurisdictions drawn from buckets 1–3 in Spike A, varying by platform vendor and
state, **plus 1 tier-2 jurisdiction for field availability only.**

**Procedure**, per jurisdiction:

1. Pick 3 recent complete months with BPS data published.
2. From the portal, manually identify all **new residential construction** permits issued in each month.
3. Count **housing units**, not permits. Note where the unit count came from — a structured field, the
   description text, or nowhere.
4. Pull the corresponding BPS place-level monthly figure from the regional place file - **join on the
   six-digit BPS ID, never on name and never on FIPS place** (both are measurably non-unique; see
   section 2). Sum `Units` across the four structure-type groups, and **record the structure-type split
   too**: a large error concentrated in the `5+ units` column is a different diagnosis than a uniform
   one. **Check `Source` for that place-month and discard the month if it is 5 or 9** - see below.
5. Compute `|ours − BPS| / BPS`.

**Record for each jurisdiction:**

- Can new construction be distinguished from alteration/addition from portal data alone? By what field?
- Can unit counts be obtained at all, or only permit counts?
- Does the portal expose an *issue* date distinct from an *application* date?
- Does the jurisdiction's permit-office boundary appear to match the BPS place? (Check unincorporated-area
  handling and any multi-place office arrangements.)
- Does the portal show full history or only recent records?
- Percent error, per month

**Decision thresholds:**

- **Median absolute error < 20% on ≥3 of 5** → headline claim is viable. Proceed.
- **20–50%** → viable but needs framing as a *comparison* rather than a *validation*. Investigate whether
  error is systematic (a fixable mapping problem) or random (a data-availability problem).
- **> 50%, or unit counts unobtainable on most** → **the BPS angle is dead.** Say so plainly and stop.
  The project then needs a different validation spine, and that is a significant re-plan — better
  discovered now than in week fifteen.

**[2026-09-19] The replacement spine is named in advance: D7's reporting-lag metric.** The original text
said a re-plan would be needed without saying to what, which is the kind of gap that turns a bad spike
result into a week of drift. Lag is the right fallback and is arguably underrated even if Spike B
succeeds:

- It needs no BPS comparison at all, so it cannot be killed by the same failure.
- It is **robust to exactly the extraction errors that sink reconciliation.** Lag is a difference between
  two dates on the same record; systematic errors in `work_class`, `unit_count`, or entity resolution
  mostly cancel. Reconciliation needs an absolute count to be right; lag does not.
- Jurisdictional permit reporting lag at national scale, p50/p95, is a statistic that does not currently
  exist, which is the same novelty argument the BPS angle rests on.

If Spike B returns *dead*, promote D7 to the headline and keep going. Do not re-plan from scratch.

**Time budget:** half a day. **Deliverable:** 5 jurisdictions × 3 months of error figures, the per-field
availability notes, and a clear go / reframe / dead verdict.

### [2026-09-20] Spike B has been RUN. Verdict: **GO, with the claim scoped to structure type.** Full report: [`docs/evidence/2026-09-20-spike-b-bps-reconciliation.md`](docs/evidence/2026-09-20-spike-b-bps-reconciliation.md)

Cost: **$0 inference**, 57 HTTP requests. Step 0 is now complete.

**The differentiating claim survives, and it survives scoped.** Portal data reconciles against
`Source`-checked BPS months at **~2-6% for low-density residential construction**. It does not reconcile
for multifamily at monthly granularity, and the blended figure hides that completely.

| Jurisdiction | 2026-01 | 2026-02 | 2026-03 |
|---|---|---|---|
| Austin TX | **1.0%** | 32.2% | 44.1% |
| Seattle WA | 7.9% | **2.2%** | 5.7% |
| Columbus OH | 230.1% | **2.1%** | **0.1%** |

**n = 9 months, median |error| 5.7%** - and that median is the wrong number to quote. Split by structure
type, which is what the protocol demanded and what the result turns on:

| | low-density (1 + 2 + 3-4) | 5+ units |
|---|---|---|
| errors | 2.0%, 2.1%, 2.4%, 3.0%, 5.9%, 14.6% | 0.0%, 0.0%, 48.8%, 86.0%, 600.0% |
| **median** | **2.7%** | unusable |

Columbus lands **within one unit of BPS on 1-3 family in all three months.** Austin's January matches
**exactly** on single-family (157 = 157) *and* on 5+ (314 = 314). For low-density work the portal and
the Census figure are measuring the same thing and agreeing.

**Multifamily is now the named hard problem for step 1**, and it is not an extraction problem - errors
are bidirectional, so more careful parsing will not touch it. One 200-unit building moves a whole
month. It needs a wider reconciliation window, or an admission that monthly multifamily is not
comparable.

**The largest trap found, and it nearly produced a confident wrong headline.** Austin scored **726%
error** on the first run: 3,991 units against BPS's 483. Austin issues Electrical, Mechanical and
Plumbing sub-permits alongside each Building Permit and **every one carries a populated `housing_units`
value**. Filtering to `permittype='BP'` took January from 726% to **1.0%**. Nothing in the field names
warns you - `housing_units` is populated, plausible and wrong. **Sub-permit duplication must be checked
per jurisdiction before any count is trusted, and the check belongs in D9's golden set.**

**Two of five sampled offices could not be scored at all**, for reasons worth carrying forward:

- **Nashville-Davidson has no unit field.** Units exist only inside free text
  (`Permit_Subtype_Description` = "Multifamily, Apt / Twnhome > 5 Unit Bldg"). Permit counts only.
- **Mecklenburg County abandoned `worktype` mid-dataset.** It is populated 123,262 times historically
  and **blank in every one of the 500 records issued in Q1 2026.** New construction cannot be
  distinguished from alteration for the comparison period. This is section 5's *per-field null rate -
  the drift alarm* firing in a live production dataset, which settles whether that alarm is optional.

**[Claim 3b is now an upper bound.]** `bucket1_candidates.csv` matched **publishers**, not datasets.
Checked at dataset level, **5 of 9 bucket-1 offices publish no building permits at all** - Madison WI
has parking permits, Miami-Dade Unincorporated has building *violations*, Osceola County has parcels and
contours. So *"bucket 1 is 0.90% of offices but 16.6% of national units"* is a publisher-level figure and
should be quoted as an upper bound until re-derived at dataset level. This also cost the sample its
unincorporated-county slot - both unincorporated counties tried publish no permits, and four of the ten
highest-volume offices in the country are unincorporated county areas.

**[What was NOT run.]** The protocol's **tier-2 field-availability jurisdiction was skipped**: Spike A's
tier-2 offices are buckets 0, 6 and 7 and none has a reachable dataset, and no fresh tier-2 draw was
made. **So Spike B says nothing about the population this project claims to contribute to.** That gap is
unchanged and should be closed before the writeup. Every jurisdiction scored here also publishes
structured open data, so extraction error sits on top of everything measured and is untested.

---

### What to bring back

1. **[2026-09-19]** The parsed BPS frame, with true tier sizes and the unit-volume distribution
2. **[2026-09-19]** Catalog-sweep results: bucket-1 classifications across the full frame
3. Spike A classification table + bucket distribution **reported all three ways**
4. Spike A recommendation on critical path
5. **[2026-09-19]** Spike C: reuse ratio, cluster distribution, vendor cross-tab, step-4 verdict
6. Spike B error table + verdict, with structure-type split
7. Saved raw HTML for every page fetched
8. Any assumption in sections 2–6 that the spikes contradicted — **especially** anything in section 6
9. **[2026-09-19]** A stated dollar budget (see section 6)

---

## 9. Sequencing

Build for the demo, not for the architecture. Each layer adds exactly one defensible claim, and the
project remains complete and honest if time runs out at any layer boundary.

**[2026-09-19 revised] Operating principle: maximize the number of independently defensible claims by
October, rather than completing a layer.** Each claim below stands on its own evidence and survives the
others failing. Steps 0-2 remain the committed floor and 3-4 the intended continuation; the difference is
that partial progress into a layer still counts if it banks a claim.

Claims banked so far, with no pipeline built:

| # | Claim | Status | Cost |
|---|---|---|---|
| 1 | 20.7% of national authorized units are published as imputation, not observation | **banked** `[G]` | $0 |
| 2 | Only 2,916 of 20,069 offices are a clean monthly oracle for calibration | **banked** `[G]` | $0 |
| 3 | Open-data bucket 1 tops out near 2.2% of offices; crawling is unavoidable | **banked** `[G]` | $0 |
| 3b | Bucket 1 is 0.90% of offices but **16.6% of national units** - an ~18x volume skew | **banked, but an UPPER BOUND** `[G]` - **[2026-09-20]** measured at publisher level; 5 of 9 checked publishers have no permit dataset (Spike B) | $0 |
| 3c | A BPS office is not a municipality: Charlotte reports as Mecklenburg County, NYC as five boroughs, Memphis not at all | **banked** `[G]` | $0 |
| 3d | ~20% of "government" open-data permit publishers are personal accounts; unfiltered catalog counts are inflated | **banked** `[G]` | $0 |
| 4 | Templates do collapse / do not collapse across jurisdictions | **banked** `[G]` **[2026-09-20]** - they do not, as D8 stated it; reuse is real at tenancy level, cohort size 1.0-8.0x (Spike C + Measurements A/B) | $0 |
| 4b | Measured fallback fraction; doubles as the budget tripwire (section 6) | step 1 | ~$0 |
| 5 | Portal enumerability distribution | **banked** `[G]` **[2026-09-21]** - 8 buckets, three-way weighting, unit-weighted reachability **69.5%**, of which **58.9% is confirmed by demonstrated query** rather than read off a form. Revised twice since first publication: St. Johns 4 -> 3 moved enumerable 28.5% -> 56.7% and the fallback floor 39.2% -> 67.3%; Bowling Green 4 -> 7 moved reachability 73.1% -> 69.5%. Bucket 4 is now one office and 2.3% of units. Recomputed from `classification.csv` by `tests/test_artifacts.py` | $0 |
| 6 | Reconciliation error vs. a clean oracle | **banked** `[G]` **[2026-09-20]** - ~2-6% for low-density, n=9 months; multifamily not comparable monthly (Spike B) | $0 |
| 6b | **The same error figure from the crawled-HTML path, not just open data** | **banked, QUALIFIED** `[G]` **[2026-09-20]** - 1.0% / 4.4% / 4.1%, median low-density 4.1% over 3 months of St. Johns County FL. Qualified because every countable unit is *implied* from a published structure class rather than read, so it tests the implication rule and is reported beside the measured median, never inside it (step 1) | $0 |
| 6c | **Crawled-HTML cost per record, measured across two platforms** | **banked** `[G]` **[2026-09-20]** - 0.76 KB/record and 259 records per index page for WATS against 72.3 KB and 9.3 for Accela: a **95x** spread that makes "number of adapters" the wrong unit of coverage (step 1) | $0 |
| 7 | National jurisdictional reporting lag, p50/p95 | step 6, approximable earlier | medium |

Claims 1-3 are already writeup-ready and cost nothing to obtain. **That is the pattern to keep**: prefer
claims that are cheap, measured, and independent of whether the pipeline ever reaches scale.

**[2026-09-19] Scope target, decided:**

| Steps | Status |
|---|---|
| 0–2 + writeup | **Committed floor and decision gate.** Strictly required. |
| 3–4 | **Intended continuation**, entered as soon as 0–2 lands. Not deferred. |
| 5–7 | Deferred; ship as design. |

The earlier draft left the stopping layer unnamed while carrying a hard October date, and those two
things were in open contradiction: steps 0–7 is a multi-month plan, D9 alone budgets 15–25 hours of
labeling, and as of 2026-09-19 there are roughly six weeks left. Naming the layer matters because it
changes what gets built in week one, not just what gets abandoned later.

**0–2 is the gate because it is what produces a decision.** Steps 3–4 are worth doing and are expected
to follow, but they are bets placed *on the numbers 0–2 produces* - adapter coverage is only worth
extending if the reconciliation number says extraction is meaningful, and synthesis is only worth
building if Spike C says templates amortize. Running 0–2 first is not caution, it is the only order in
which 3–4 are informed rather than speculative.

**Because 3–4 are near-term, steps 0–2 must not foreclose them.** Three concrete obligations, all of
which are cheap now and expensive to retrofit:

1. **D8's shared emit interface is binding from the first adapter**, not aspirational. The step-1 adapter
   must emit through the same interface a synthesized extractor will, or the schema silently takes the
   shape of whatever that one platform exposes and the generic path fights it forever.
2. **Raw HTML retention from day one**, including during the spikes. Step 4 needs a corpus to synthesize
   against and step 2's golden set must be drawn from the raw store, not from live fetches (D9).
3. **Template fingerprinting runs in step 1**, even though nothing consumes it until step 4. It is a hash
   over pages already being fetched, and it turns step 4's cost curve into something measured over months
   of real data rather than estimated at the moment it is needed.

**[2026-09-20] Status of the three obligations, now that step 1 has three adapters:**

| # | Obligation | Status |
|---|---|---|
| 1 | Shared emit interface | **Discharged for now.** Three platforms - open-data, Accela, WATS/.NET - emit through one interface. The third cost one new `UNIT_SOURCES` value and no schema change. Watch the other edge: shared code means a shared bug, and `norm_date` nulled 100% of one county's dates from the common layer. |
| 2 | Raw HTML retention | **Holding.** 218 manifest rows, 149.1 MB, every page carrying provenance written in the same operation. Replay has been exercised three times for zero requests. |
| 3 | Template fingerprinting in step 1 | **NOT DONE.** Spike C's fingerprinter exists in `scripts/` and has never been lifted into `permits/` or wired into the capture path. This is the one obligation still open, it is the cheapest of the three, and it is the one whose value decays - a fingerprint not taken at capture time cannot be taken later for pages that have since changed. |

**[2026-09-21] Obligation 3 is discharged. All three are now closed.**

The fingerprinter is `permits/fingerprint.py`, lifted from `spikes/spike_c_fingerprint.py` and verified
to reproduce that file's hashes on all **137 pages** of the Spike A and Measurement A/B corpora before
the spike script was rewritten to delegate to it — so every number in the Spike C report still
reproduces. `permits.capture.fetch()` now fingerprints every page it keeps, including rejected ones, and
the manifests gained an `fp` column through an additive migration that refuses to drop a column it does
not recognise. 329 already-captured pages were back-filled from the raw store.

Two things the discharge added that the obligation did not ask for, and both are load-bearing:

- **The fingerprint is versioned** (`fp1:<hash>`). `VOID` and `OPAQUE` are exactly the kind of tuning
  that gets adjusted later, and a stored hash that does not say which rules produced it is the same
  failure as a quoted number that does not say when it was measured.
- **A body with no DOM stores nothing.** The first back-fill reported a template "shared across" Austin,
  Charlotte, Columbus, Nashville and Seattle — five unrelated open-data APIs whose JSON bodies all
  fingerprint to the sha1 of the empty path set. A fingerprint that collides on *absence* is worse than
  no fingerprint, because it reads as a finding.

Back-filling was legitimate here and it is worth saying why, since this project refuses a back-filled
`observed_at` on the same subject. **A fingerprint is a pure function of bytes D1 holds immutable**, so
recomputing it gives the answer it would have given at capture. A transaction timestamp is not a
function of the bytes — it is a fact about an event that is over. That asymmetry, not convenience,
is what makes one fine and the other forbidden.


**Note the claim ordering this implies.** Amortization - the "core technical claim" of section 1 - lands
at step 4. BPS reconciliation, the differentiating claim, lands at step 1, and reporting lag falls out of
step 6 but is cheaply approximable earlier. So for the duration of the committed floor the differentiating
claim *is* the headline, and the cost story arrives later. Write the writeup in that order rather than
front-loading an architecture argument whose evidence does not exist yet.

**Verify the actual deadline before trusting it.** The October date is itself marked as an assumption in
this document. Application windows vary widely by company and by whether the target is new-grad or
experienced-hire, and many roll through the fall and winter. Check the real dates for the actual target
list - if the date is softer than assumed, the boundary between "intended continuation" and "deferred"
moves, and this table should be revisited rather than inherited.

| # | Step | Unlocks |
|---|---|---|
| 0 | Spike A, then Spike B | Whether to proceed, and as which project |
| 1 | Crude end-to-end, 50 jurisdictions, 1 adapter, no synthesis, no bitemporality | **The reconciliation number** |
| 2 | Golden set construction | Honest quality metrics |
| 3 | Remaining 3–4 adapters | Coverage baseline + generic-path oracle |
| 4 | Template synthesis + fingerprint-keyed cache | **The cost story** |
| 5 | Scale to 200–500 jurisdictions | **The coverage story** |
| 6 | Full observation log + lifecycle view | Point-in-time correctness, reporting-lag finding |
| 7 | Dataset release + writeup | The artifact anyone actually reads |

**[2026-09-20] Where step 1 actually stands.** Seven sources pulled, three platforms, **$0**.

| source | platform | records | status |
|---|---|---|---|
| Austin TX | Socrata | 13,162 | error figure |
| Columbus OH | ArcGIS | 8,872 | error figure |
| Seattle WA | Socrata | 324 | error figure |
| **St. Johns County FL** | **WATS/.NET** | **3,872** | **error figure, QUALIFIED** - units implied, not stated |
| Charlotte / Mecklenburg NC | ArcGIS | 500 | **blocked** - `work_class` null in 100% of records |
| Nashville TN | ArcGIS | 2,407 | **blocked** - no usable unit field in 99% of records |
| Clark County NV | Accela | 531 | **blocked** - no unit field in 96%, and every implied unit is un-measured |

**Four of seven produce a figure and three are blocked by the drift alarm.** That ratio is the finding,
not a shortfall: the alarm exists so that a jurisdiction whose records cannot be classified produces *no
number* rather than a confident wrong one, and it has now stopped three.

`tripped` and `qualified` are different verdicts and the distinction was forced by St. Johns.
**Tripped** means the source cannot be scored at all. **Qualified** means the number is real and may not
be quoted bare - St. Johns' units are implied from a published structure class, so its 4.1% tests the
implication rule rather than measuring extraction. Qualified figures print separately and stay out of the
headline median. The check that this was principled rather than convenient: it weakens no blocking case -
Clark County has no unit field on 96% of records and is still stopped by the coverage alarm.

**Not done in step 1:** the 50-jurisdiction target (7 so far), template fingerprinting (§9 obligation 3),
and the named-office list. The reconciliation number - the thing step 1 exists to unlock - is in hand from
both the open-data and the crawled-HTML path.

**`[2026-09-21]`** Fingerprinting is now done (§9 obligation 3 above). **Still not done: the
50-jurisdiction target and the named-office list**, and the second of those is the one that matters -
ADR-0005 makes it the only thing that can *clear* the gate rather than merely fail to fire it. Worth
recording plainly: **the gate denominator and the extraction corpus overlap in exactly two offices.**
Five of the seven sources pulled in step 1 are not in the Spike A 28 at all, so "we pulled seven sources"
and "reachability is 69.5%" are statements about almost disjoint sets of offices.

**The failure mode is the reverse order:** three months of infrastructure, no numbers, and a demo showing
a dashboard of a pipeline processing nothing interesting.

**Start the writeup in week one and keep it as a running log.** Reconstructing reasoning at the end is
much harder than recording it as it happens, and the writeup is a first-class deliverable — it is what
people who won't read the code will read instead.

**Hard date:** big-tech applications generally open in the fall, so anything not shipped by roughly
October misses that cycle. Verify actual dates for target companies rather than assuming.

---

## 10. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Portals not enumerable | **Critical** | Spike A. Re-plan around query partitioning if needed. **[2026-09-20]** Partitioning now runs in production - St. Johns, 3,627 records in 28 requests, zero bisections - and the bucket-4 fallback floor is 67.3% rather than 39.2%. Downgraded in practice, not in principle: the two genuinely hard bucket-4 rows are still untested. **[2026-09-21]** Both now tested. Bucket 4 is **2.3% of units and one office**, so the risk is retired *as a gate dependency* - but neither was cracked, so the underlying capability question is still unanswered and simply no longer load-bearing. |
| **The bucket distribution is 26/28 provisional** `[2026-09-20]` | **High** | Buckets read off a rendered form can only *under*-classify, and one row of 28 carrying 28% of units swung the fallback floor by 28pp. [ADR-0005](docs/adr/0005-a-bucket-is-demonstrated-not-inferred-from-the-search-form.md): a form-read bucket is provisional, only a pull confirms, and the metric **may fire the gate but may not clear it**. Cheapest mitigation is to demonstrate the two remaining bucket-4 rows. **[2026-09-21] Downgraded to Medium.** `classification.csv` now carries `status`; five offices are confirmed and they are **62.4% of the denominator**, including *all* of the enumerable mass. The 23 provisional rows all sit in unreachable buckets, so provisional error can only move the number up. Residual risk is that 23 rows still rest on a form read. |
| **A reconciliation figure built on implied units gets quoted bare** `[2026-09-20]` | **High** | St. Johns states no unit count; its 4.1% is derived from the BPS taxonomy and tests the implication rule rather than measuring extraction. The alarm marks it `qualified` (distinct from `tripped`), the reconciler keeps it out of the headline median and prints it separately. The residual risk is a human quoting it from the table. |
| **Apply-and-pay portals read as permit portals** `[2026-09-21]` | **High** | Both bucket-4 offices probed run modern transactional portals - Tyler eSuite, a custom ASP.NET app - that publish **no permit records at all**. Vendor detection, form detection and every automated signal Spike A used score them as healthy portals. Any coverage figure built from portal *detection* rather than a demonstrated record query is inflated by an unknown amount. ADR-0004's bucket 7 does not distinguish this case and needs revising. |
| **An office identity is silently substituted** `[2026-09-21]` | **High** | All 28 office ids in `portals.csv` were wrong and **7 resolved to a real, different office** - `12|633000` is Okeechobee County, not St. Johns. An existence check passes on every one. Mitigation is `scripts/check_identity.py`, which checks the key *against the name recorded beside it* and runs in the test suite; known-wrong keys in dated captures are registered in `data/corrections.csv` rather than rewritten. |
| **The regression suite is mistaken for a golden set** `[2026-09-21]` | Medium | 307 tests assert that behaviour has not *changed*; none asserts it is *correct*. D9's 500-1,000 blind-labelled records remain unstarted and unmeasured, and the cheap suite makes deferring the expensive one feel safer than it is. See [ADR-0014](docs/adr/0014-the-golden-set-precedes-the-pipeline.md). |
| **The capture layer is untested** `[2026-09-21, closed 2026-09-22]` | Closed | `permits/capture.py` writes the provenance log everything downstream trusts and had **no tests**. `tests/test_capture.py` now covers robots handling, the per-host pause, the budget ceiling, schema migration and the verdict rules against a loopback HTTP server - no mock, real `urllib`. It failed on its first run against the one invariant the module exists to enforce: `fetch()` wrote the page and then the row, so a refused schema migration left an unrecorded page on disk, which is the Spike C failure reintroduced inside the code written to prevent it. Fixed by writing the row first and promoting the page only afterwards. **Residual:** the ASP.NET postback path - viewstate, the CSRF headers, the session cookie across a paged grid - is still only exercised by replay. |
| BPS reconciliation infeasible | **Critical** | Spike B. **[2026-09-19]** Fall back to D7 reporting lag as the validation spine; do not re-plan from scratch. |
| **Templates do not collapse across jurisdictions** `[2026-09-19]` | **Critical** | **Spike C**, run before step 4 is built. Untested until now. Kills the amortization claim, i.e. the stated reason the architecture exists. |
| **Easy jurisdictions are the ones that don't need us** `[2026-09-19]` | High | Structural, not fixable - manage by reporting every figure tier-2 count-weighted as well as unit-weighted. See section 2. |
| **Steps 0-2 foreclose steps 3-4** `[2026-09-19]` | High | Shared emit interface, raw retention, and fingerprinting all binding from step 1. See section 9. |
| **Raw store is unpublishable, so external replay is impossible** `[2026-09-19]` | Medium | D10. Document the limit in the dataset docs rather than implying a reproducibility guarantee. |
| Adapters crowd out generic path | High | Cap at 5, written trigger date, shared emit interface. **[2026-09-20]** The trigger D8 required was never written; [ADR-0009](docs/adr/0009-adapters-first-generic-extraction-second.md) now sets it as an artifact rather than a date - **the fourth adapter is the last one built before a measured generic-versus-adapter comparison exists.** Three of five are spent. |
| Attachment bytes explode storage | High | Metadata only in v1. Hard boundary. |
| Time overrun past October | High | Layered sequencing; every boundary is a valid stopping point |
| Template drift silently nulls fields | Medium | Per-field null rate per template as a monitored alarm |
| Entity resolution false merges | Medium | Resolution is derived and recomputable; monotonicity check catches some |
| Over-engineering reads as inexperience | Medium | Right-size to measured load; document scale-out separately |
| ~~Vendor robots.txt blocks the crawl~~ | ~~Medium~~ → **Low** `[2026-09-19]` | Partially retired: Accela and Tyler serve no robots.txt at the vendor level (section 2). Still check per tenant. |

---

## 11. Legal and ethical constraints

- **Identify the crawler.** Real user agent with a contact address.
- **Honor `robots.txt`.** Record posture per source in the `sources` table.
- **Per-host token bucket and adaptive backoff.** These are small government servers; being a good citizen
  is both correct and self-interested.
- **PII is the real issue.** Contractors are businesses and fine to publish. **Owner-builder permits carry
  an individual's name attached to their home address.** Aggregating that nationally is a materially
  different privacy posture than any single jurisdiction's portal, even though each source is public.
  - **[2026-09-19] Decided - see D10.** The earlier text said "decide this now" and then did not decide,
    which is how this kind of thing ends up retrofitted. The decision: **classify individual-vs-business
    at extraction time; store the classification; never write the raw applicant-name string into
    `permits` or any other derived table.** The name stays in the raw store, and the raw store is never
    published. A release-time filter is strictly weaker because it depends on the filter staying correct
    forever rather than on the data never being there to leak.
  - **[2026-09-19]** Consequence to state in the dataset docs: the published dataset is not externally
    re-derivable, because re-deriving it would require the raw store. See D10.
- **Check state-level restrictions.** Some states restrict bulk access to public records; verify before
  release rather than before crawling.
