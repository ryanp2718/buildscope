# ADR-0007: Office identity is `(state_fips, bps_id)`, assigned from the frame and never from a name, a domain, or a probe artifact

Status: Accepted

Date: 2026-09-20

*Back-fill. The decision is D3 in `DESIGN.md` and predates this directory;
[ADR-0003](0003-jurisdiction-identity-is-bps-scoped.md) already builds on it and settles its **scope**.
This ADR records the base decision — what the key is, and where it is allowed to come from — and resolves
a discrepancy between D3 as written and what the project actually does.*

## Context

Every claim this project makes is denominated per permit-issuing office: coverage is *offices covered ÷
offices that issue permits*, the reconciliation is a join against one office's monthly BPS figure, and the
unit weights that drive the gate are the frame's `units_12mo` per office. If office identity is wrong,
every one of those is wrong in a way that still looks like a number.

The obvious candidate keys all fail, and they fail in the same direction — they look right and join to
something plausible:

- **Name.** Name-similarity matching has failed in this project four separate times: the catalog sweep
  matched *Marina* to *Marin*, the Spike A URL probe had a **75% false-positive rate** (21 of 28 hits
  rejected by the verifier — `Bowling Green KY` matched a Virginia town, `Brazil IN` matched the country,
  `Amador City CA` matched a person's homepage), and entity resolution matched *Los Angeles County* to
  *Los Angeles city*. The fix has been an authoritative attribute every single time.
- **FIPS place.** A BPS office is not a municipality. Charlotte — a top-20 city — has **no BPS office**
  and reports as Mecklenburg County. New York City is **five borough offices**. Memphis has none. Fulton
  County GA has 15 municipal offices and no county office. Counties issue for unincorporated area, which
  is not a place at all.
- **Portal domain.** Directly observable and simple, and it collapses whenever jurisdictions share a
  vendor tenancy — an Oregon statewide Accela tenancy serves many jurisdictions from one host — or migrate
  platforms, which is common. Domain is a good discovery signal and a bad identity.

**The incident that makes this concrete, and it happened after all of the above was known.** The St. Johns
County adapter was built with `bps_id = "633000"`, copied from the hardcoded key in a Spike A probe
script. `12|633000` is **Okeechobee County FL** — population 36,635, zero units, zero of 24 months
reported. St. Johns is `12|803000` — population 255,059, 3,637 units/12mo, 23 of 24 months. The
classification file carried the correct key throughout; the wrong one came from a *working note* that had
been treated as a source of record.

## Decision

**Office identity is the composite `(state_fips, bps_id)`.** Six numeric digits held as `TEXT`, taken from
the Census BPS frame. Name, FIPS place, county, and portal domain are **attributes**, carried with
match-method and match-confidence, and are never identity.

**The frame is the only assigner.** `data/frame/bps_frame.csv` and the classification file derived from it
are the sources of record. Probe JSONs, scratch scripts, prior run outputs, and adapter constructors are
working notes: **no code may take a `bps_id`, a `state_fips` or a label from one.** Every run script
writes D3 identity into its summary so downstream stages read it from one place.

**A fuzzy match may never create an identity.** It may propose a link, which is then adjudicated and
recorded with its evidence ([ADR-0001](0001-source-office-link-is-an-evidence-bearing-relation.md)).

**Resolving the discrepancy in D3 as written.** D3 specifies an internal surrogate `jurisdiction_id` with
`bps_office_id` as a crosswalk attribute. The project does not do that and should not pretend to: the
**office** — the frame row — is the unit of account, and it is identified by the composite BPS key
directly. No surrogate is minted, because [ADR-0003](0003-jurisdiction-identity-is-bps-scoped.md) defers
the `jurisdiction` table until a non-BPS issuer exists to put in it, and a surrogate with exactly one
source of rows is an indirection with no second case to justify it. D3's *reasoning* — that identity must
not be derived from an external code that means something else — survives intact and is the reason name
and FIPS place are excluded here.

## Consequences

- **The coverage denominator is supplied by the federal government rather than invented**, which is most
  of why the coverage figures are defensible at all.
- **A wrong key fails loudly in the common case and silently in the rare one.** Okeechobee reports zero
  months, so the join found no oracle row and the reconciliation would have reported nothing — benign. The
  malign version is a wrong key that *does* find a row, producing a fully-formed error figure comparing
  one county's permits to another county's BPS filing. Nothing in the current code detects that. The
  mitigation is the assignment rule above, not a check, and that is a weaker guarantee than it sounds.
- **`is_permit_issuing` is temporal.** A jurisdiction that stood up a portal in 2025 is not a 2023
  coverage failure, so the flag is an interval and not a boolean.
- **Offices outside the BPS universe cannot be identified at all** — tribal governments most substantively.
  That is a stated coverage gap, scoped by ADR-0003, not an oversight.
- **Six digits as `TEXT`, never as an integer.** Leading zeros are real: `021000` is Clark County. A single
  `int()` anywhere in the pipeline silently re-identifies an office as a different one.
- **The rule costs a small, permanent friction.** Every new adapter must look its office up in the frame
  rather than pasting a key from whatever probe produced the portal URL, which is precisely the convenient
  path that produced this incident.

## Alternatives considered

- **An internal surrogate with the BPS key as a crosswalk attribute**, as D3 literally specifies. Correct
  if multiple identity authorities existed. There is one, ADR-0003 defers the second indefinitely, and the
  indirection costs a join on every query and an extra hop in every debugging session. Rejected as
  premature, with the migration path kept cheap by the `office` view.
- **Keying on portal domain.** Observable without any frame at all. Rejected: tenancy sharing and platform
  migration both break it, and both are common rather than edge cases.
- **Keying on name plus state.** The intuitive choice and the one that has failed four times in this
  project already. Rejected on measured evidence, not on principle.
- **Synthesizing numeric IDs for offices outside the frame.** Rejected in ADR-0003 — a collision with a
  real BPS ID joins silently and returns a wrong answer.
- **Adding a runtime assertion that an adapter's `bps_id` exists in the frame with non-zero reported
  months.** Would have caught the Okeechobee substitution. Not adopted here because it encodes a
  *plausibility* heuristic into an identity check — an office with zero reported months is a legitimate
  frame row, and the check would have to be advisory. Worth revisiting; noted rather than done.

## Revisit when

A permit source is found serving a jurisdiction with no BPS office (ADR-0003's trigger), **or** a second
wrong-key incident occurs — at which point the assignment rule has failed as a control and the advisory
frame check above should be built rather than considered.

## References

- `DESIGN.md` §D3, §2 (frame composition), §8 (Spike A method note on name matching)
- [`docs/design/entity-resolution.md`](../design/entity-resolution.md) — "Problem 1 is solved and closed",
  the `source_office_link` schema, and the `office` view
- [`docs/evidence/2026-09-20-step1-stjohns-reconciliation.md`](../evidence/2026-09-20-step1-stjohns-reconciliation.md)
  — the Okeechobee substitution
- [ADR-0001](0001-source-office-link-is-an-evidence-bearing-relation.md),
  [ADR-0003](0003-jurisdiction-identity-is-bps-scoped.md),
  [ADR-0005](0005-a-bucket-is-demonstrated-not-inferred-from-the-search-form.md)
