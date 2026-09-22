# ADR-0009: Adapters first, generic extraction second — and the template-identity premise is withdrawn

Status: Accepted

Date: 2026-09-20

*Back-fill. The decision is D8 in `DESIGN.md` and predates this directory. Unlike the other back-fills,
part of D8's stated rationale has since been **measured and falsified**; this ADR records the decision that
survives, the premise that did not, and what replaced it.*

## Context

There are two ways to extract permit records from ~20,000 portals: write an adapter per platform, or
synthesize an extractor per template with a model. Adapters are fast to write and do not generalize;
synthesis generalizes and has no oracle to be scored against until something known-good exists.

The ordering argument that decides it is **not velocity**. It is that **adapters are the eval oracle for
the generic path.** A known-good Accela adapter lets synthesized extractors be scored on thousands of
pages without hand-labeling, which makes the generic path *cheaper* to build later rather than more
expensive. Building synthesis first means building it blind.

The failure mode is equally clear and entirely predictable: **adapters work well enough that generic never
happens.** Each one delivers visible coverage for a day's work; the generic path delivers nothing until it
works at all.

D8 also carried a second, separate claim, and it was the strongest cost argument in the document:
*template identity is a DOM fingerprint, not a site*, collapsing the amortization denominator from ~20,000
sites to *"plausibly a few hundred distinct vendor templates"*, which would make the cost curve **bend**
as coverage grew.

## Decision

**Hand-written adapters for the top platforms by universe share, then LLM extractor synthesis**, in that
order, with three guardrails:

- **Cap at 4–5 adapters**, chosen by universe share. Past that, generic or nothing.
- **An identical emit interface from day one.** If the schema ends up shaped by what one platform exposes,
  generic extraction fights the schema forever.
- **A written trigger** for when generic work starts, because without one it slips silently.

**The DOM-fingerprint premise is withdrawn.** It was measured and it is false as stated — see below. The
instruction that killed it, *"measure cross-jurisdiction template reuse as a headline number"*, is kept
verbatim, because it did its job.

**The written trigger, set here for the first time.** D8 required one and none was ever written, which is
exactly the silent slippage D8 predicted. It is: **the fourth adapter is the last one built before a
measured generic-versus-adapter comparison exists.** No fifth adapter is written until the bake-off — a
synthesized extractor scored against an existing adapter on the same stored pages — has produced a number.
This is tied to an artifact rather than a calendar date because an artifact cannot be quietly
renegotiated, and the artifact is cheap: the pages are already on disk and the comparison costs cents.

## Consequences

### What the measurement did to the premise

[Spike C](../evidence/2026-09-20-spike-c-template-collision.md) fingerprinted 25 jurisdictions and found
**1.00 fingerprints per jurisdiction at every threshold down to Jaccard 0.60.** Nothing merged. "~20,000
sites collapse to a few hundred templates" is dead, and every cost figure that rested on it has been
withdrawn from `DESIGN.md` §§5–6.

[Measurements A and B](../evidence/2026-09-20-measurement-ab-results.md) supply the replacement:

- **The cache key is vendor + version + configuration, discovered by clustering** — not pure DOM
  structure, and not the vendor name. Two CivicPlus sites of matched type score 0.255; two Accela
  tenancies score 0.766. The vendor name alone predicts nothing.
- **The amortization unit is the tenancy.** Two Oregon jurisdictions inside one statewide Accela tenancy
  render detail pages at **J = 0.863**. The cross-jurisdiction reuse D8 reached for is real, and it lives
  *inside* multi-jurisdiction tenancies rather than across a vendor's fleet. Spike A counted 18 statewide
  portals.
- **Index and detail are separate templates** (J = 0.19 within one portal), so a tenancy needs **at least
  two** extractors, not one.
- **Cohort size is a curve — 1.00 at J ≥ 0.95, 8.00 at J ≥ 0.70 — and structure cannot pick the
  threshold.** It depends on how much drift a synthesized extractor tolerates, which is a step-2 question
  against the golden set. **Until that is measured, no amortization multiple may be quoted.**

### What step 1 added

- **The emit interface survived a third platform, which is the first real test of it.** Three adapters now
  exist — open-data (Socrata/ArcGIS), Accela, and St. Johns' WATS/.NET — and adding the third required one
  new `UNIT_SOURCES` value and **no schema change**
  ([step 1 evidence](../evidence/2026-09-20-step1-stjohns-reconciliation.md)). §9 obligation 1 is
  discharged for now.
- **A shared interface is also a shared bug, and this is the cost side nobody writes down.** `norm_date`
  lives in the common layer and its fixed-width slice nulled **100%** of St. Johns' dates while the adapter
  looked like it was working. One bug in shared code is one bug in every jurisdiction at once — which is
  the same property that makes the interface worth having, seen from the other side.
- **"Number of adapters" is the wrong unit of coverage.** Per-record cost varies **95x between platforms**
  — 0.76 KB/record for WATS against 72.3 KB for Accela. An adapter's value depends on the page density of
  the tenancies it unlocks, not on the platform's share of the office count, and no coverage plan that
  counts adapters can see that.
- **A finding that points somewhere D8 did not.** St. Johns' entire structure classification comes from a
  **code table the county publishes in its own search form** — 69 codes with labels, fetched for zero
  requests — not from page structure at all. If that generalizes, the expensive thing for a synthesized
  extractor to learn is a source's **controlled vocabulary**, not its DOM, and vocabularies are cheaper to
  acquire and easier to verify than layouts. This is a hypothesis from one portal and is written here as
  one, but it is the most interesting thing step 1 turned up about the generic path.

### Standing costs

- **Three adapters of a cap of five are spent**, and the two remaining are the whole budget for platform
  coverage before the generic path must carry it.
- **The oracle argument only pays off if the bake-off actually runs.** An adapter that is never used to
  score a synthesized extractor is just an adapter, and the entire ordering rationale evaporates.

## Alternatives considered

- **Generic synthesis first, adapters only where it fails.** Fewer moving parts and a better story.
  Rejected: nothing can score the synthesized extractor, so "where it fails" is unmeasurable, and the
  project would be committing its scarcest budget to the component with no feedback signal.
- **Adapters only; abandon synthesis.** Honest, shippable, and it forfeits the "core technical claim" of
  §1 — amortization — leaving only the reconciliation claim. Rejected as a plan, retained as the
  acknowledged fallback if the bake-off returns a bad number.
- **Keep the DOM-fingerprint cache key and tune the threshold.** Rejected by measurement: at J ≥ 0.60
  nothing merged, and a threshold loose enough to merge is loose enough to be meaningless.
- **Key the template cache on vendor name.** The obvious replacement once DOM structure failed, and it is
  wrong by the same measurement — two CivicPlus sites score 0.255. The vendor name predicts nothing.
- **A calendar date for the trigger**, as D8 literally specified. Rejected in favour of the artifact-based
  trigger above: a date with no artifact attached is renegotiated the week it arrives, and the October gate
  already supplies whatever time pressure a date would have.

## Revisit when

~~The bake-off produces a number.~~

**[2026-09-21] IT HAS. The trigger is discharged** —
[extractor conformance test](../evidence/2026-09-21-extractor-conformance.md), $1.2751. The name
"bake-off" retires with it: a bake-off implies a neutral judge, the adapter *is* the reference, and every
figure is an agreement rate rather than an accuracy rate.

Synthesized extractors reached **1.0000 recall, 1.0000 precision and 1.0000 on every field against both
adapters** — 4,188 records over 71 pages, from two calls costing $0.33 combined. Amortization measured at
**64x** (St. Johns, 14 pages) and **8.1x** (Clark, 57 pages), breakeven at 0.2 and 7.1 pages. That is the
"scores near the adapter" branch, so **the cap of five moves from a constraint to a formality** and §1's
amortization claim survives — narrowly, and with the limits below.

Three things the result invites and does not license:

- **It is not accuracy.** Both implementations read the column headed "Issue Dt" as the issue date;
  neither shows that it is one. [ADR-0014](0014-the-golden-set-precedes-the-pipeline.md) survives intact
  and is now the binding constraint on the extraction claim as a whole.
- **It gives no cohort size.** Every page scored is one capture of one template. The threshold Spike C
  could not pick is still unpicked, so **no amortization multiple may be quoted across templates** — only
  within one.
- **A template with no adapter cannot be scored this way at all.** The oracle argument works precisely
  where an oracle already exists. That is the boundary of the method, not a gap in this run.

The load-bearing operational finding is the model tier: **direct extraction ran perfectly on Haiku 4.5;
synthesis failed completely on Accela at that tier and was perfect on Opus 5.** One bad synthesis call
broke all 57 pages — §6 lever 6's asymmetry, observed rather than argued, and the reason that lever's
deferral is retired.

Revisit if a fourth adapter is proposed anyway. On this evidence the case for one has to be about *reach*
— a platform synthesis cannot see — and not about extraction quality, which is no longer the binding
constraint.

## References

- `DESIGN.md` §D8, §1 (the core technical claim), §9 obligations 1–3, §10 (adapter-crowd-out risk)
- [`docs/evidence/2026-09-20-spike-c-template-collision.md`](../evidence/2026-09-20-spike-c-template-collision.md)
  — 1.00 fingerprints per jurisdiction
- [`docs/evidence/2026-09-20-measurement-ab-results.md`](../evidence/2026-09-20-measurement-ab-results.md)
  — the tenancy as the amortization unit
- [`docs/evidence/2026-09-20-step1-stjohns-reconciliation.md`](../evidence/2026-09-20-step1-stjohns-reconciliation.md)
  — the third adapter, the shared-bug cost, and the published-vocabulary hypothesis
- `permits/emit.py`, `permits/vocab.py`, `permits/adapters/`
