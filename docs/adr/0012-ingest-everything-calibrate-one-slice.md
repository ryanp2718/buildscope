# ADR-0012: Ingest everything, normalize everything, calibrate one slice

Status: Accepted

Date: 2026-09-21

*Back-fill. The decision is D2 in `DESIGN.md` and predates this directory.*

## Context

The scope question was originally posed as "should this project cover only residential new construction?"
and that framing is wrong, because it treats narrowing as an *ingest* decision. It is not. Portals do not
segregate residential new construction from reroofs — a jurisdiction's search returns whatever matches the
query, and the classification that would narrow it is only available *after* extraction.

So a narrow scope is a post-extraction filter, and is therefore strictly **more** work than a broad one:
the same pages, the same parsing, plus a discard step.

That reframing settles the mechanics but not the value question, which is what the breadth is *for*.

## Decision

Three verbs, deliberately separated, each with its own scope:

- **Ingest** all building-related permits.
- **Normalize** all of them, to a shared core schema with a canonical work-class ontology.
- **Calibrate** residential new construction only, against BPS.

With three boundaries:

- **Trade sub-permits are children, never records.** Electrical, plumbing and mechanical attach to a
  parent when the parent is in scope. Never top-level — jurisdictions disagree on whether they are
  separate entities, and flattening double-counts.
- **Out of v1:** planning and zoning applications (months-to-years lifecycle, discretionary approval,
  agenda-driven — a genuinely different pipeline), business licenses, certificates of occupancy.
- **Count units, not permits.** BPS counts housing units; one permit for a 200-unit building is 200 units.

**The reason breadth is worth it is taxonomy alignment, not row count.** A narrow scope has ~8 work
classes and trivial normalization. Full breadth inherits thousands of mutually incompatible controlled
vocabularies — `RESALT`, `COMTI`, `MECH-RES`, `BLDG-ADD-SFR` — that overlap partially and nowhere
identically. Mapping those onto one ontology with confidence and provenance is real ontology alignment, is
unsolved in this domain, and is the strongest technical claim breadth buys.

## Consequences

- **The sub-permit rule is not theoretical; it is the largest error this project has measured.** Austin
  publishes Building, Electrical, Mechanical and Plumbing permits in one dataset and **every one carries a
  populated `housing_units` value**. Summing naively counted dwellings up to four times: **726% error**
  against BPS. `permits/emit.py` encodes the rule as `countable_units`, which returns zero for anything
  that is not `permit_kind == BUILDING`, rather than as a filter someone has to remember to apply.
- **"Calibrate one slice" means the other slices are unvalidated, and that has to keep being said.** The
  pipeline normalizes reroofs and mechanical permits and nothing checks them against anything, because no
  external oracle for them exists. The BPS error figure describes residential new construction and no
  other part of the dataset.
- **Breadth is what makes the reconciliation possible at all**, which is the argument's quiet half.
  St. Johns' reconciliation required classifying 69 property-use codes, of which only five map to BPS
  structure classes — the other 64 exist to be *excluded* correctly. A narrow crawl could not have
  distinguished them; it would have had to guess which codes it was not fetching.
- **The ontology claim is the one that has not been tested.** Three adapters exist and each maps its own
  source's vocabulary. Nothing yet maps two sources' vocabularies onto each other and measures whether the
  result is coherent. Until that happens, "real ontology alignment" is an intention.
- **Ingest breadth has a storage cost and it is already visible.** 218 manifest rows and 149 MB for seven
  sources at one quarter. The byte economics differ 95x between platforms
  ([step 1 evidence](../evidence/2026-09-20-step1-stjohns-reconciliation.md)), so this scales by tenancy
  page density rather than by office count.
- **`work_class` and `structure_type` are normalized enums from day one**, because the entire BPS mapping
  depends on separating new construction from alteration and 1-unit from 5+. They are the hardest
  extraction targets and the most valuable, and they are closed vocabularies in `emit.py` for that reason.

## Alternatives considered

- **Narrow to residential new construction at ingest.** The intuitive scoping, and it is what the project
  was originally posed as. Rejected on mechanics: portals do not offer that filter, so the "narrow" crawl
  fetches the same pages and then discards. It is more work for less data.
- **Narrow at normalization — extract everything, normalize only the calibrated slice.** A real middle
  option that would save genuine effort, since normalization is where the vocabulary work is. Rejected
  because it forfeits the differentiating claim: the raw strings would be retained but unmapped, and an
  unmapped corpus is not a dataset. It also defers the ontology work to a point where there is no oracle
  to check it against.
- **Include planning and zoning applications.** They are the earliest signal in the development pipeline
  and would be the most valuable data here if they were comparable. Rejected because the lifecycle is
  months to years, approval is discretionary, and the records are agenda-driven rather than
  transactional — the milestone model in
  [ADR-0011](0011-milestones-are-rows-with-a-fixed-vocabulary.md) does not fit them, and forcing them in
  would corrupt it.
- **Treat trade sub-permits as top-level records.** Simpler ingestion, and some jurisdictions genuinely
  model them that way. Rejected by measurement: it is the 726% error.

## Revisit when

Two sources' vocabularies are actually mapped onto each other and scored — that is the first real test of
whether the breadth argument buys what it claims. Revisit sooner if storage or crawl budget forces a cut,
in which case the honest move is to narrow *calibration* further rather than narrow ingest, since ingest
breadth is nearly free and the discard is not.

## References

- `DESIGN.md` §D2, §1 (the differentiating claim), §5 (work-class ontology)
- [`docs/evidence/2026-09-20-spike-b-bps-reconciliation.md`](../evidence/2026-09-20-spike-b-bps-reconciliation.md)
  — the 726% Austin sub-permit error
- [`docs/evidence/2026-09-20-step1-stjohns-reconciliation.md`](../evidence/2026-09-20-step1-stjohns-reconciliation.md)
  — 69 property-use codes, 5 of which map to BPS
- `permits/emit.py` — `PERMIT_KINDS`, `countable_units`; `permits/vocab.py`
