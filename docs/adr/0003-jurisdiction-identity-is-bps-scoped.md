# ADR-0003: Jurisdiction identity is BPS-scoped, with forward compatibility bought by a view

Status: Accepted

Date: 2026-09-20

## Context

Office identity is `(state_fips, bps_id)` per D3. That key is concrete, but it is *scoped*: it identifies
exactly the entities the Census Building Permits Survey treats as permit-issuing places. Some real
permit issuers are outside that universe, and the question is whether to model them now.

Ranked by how real the gap actually is:

- **Tribal governments** - the substantive case. They do issue building permits on trust land, and BPS
  coverage there is essentially absent. A genuine hole in the frame.
- **Special districts** - weak. Water, school and fire districts overwhelmingly do not issue *building*
  permits; fire districts issue some permits, rarely building ones.
- **Joint powers authorities** - rare for building permits specifically.
- **Contract or consolidated permitting**, where a city contracts issuance to the county. Not raised, and
  the most common of the four by a wide margin. Already present in the data as Mecklenburg/Charlotte, and
  already handled: it is a many-to-one link under [ADR-0001](0001-source-office-link-is-an-evidence-bearing-relation.md),
  not a missing jurisdiction type.

So the case for a general `jurisdiction` table rests almost entirely on tribal governments, which are
real but out of scope for the October decision gate.

## Decision

`(state_fips, bps_id)` remains the office identity. No `jurisdiction` table is built. Two cheap measures
carry the forward compatibility instead:

- **All joins go through an `office` view**, never `bps_frame` directly. Today the view is the frame
  verbatim. Admitting non-BPS jurisdictions later means redefining one view as a `UNION` over a
  `jurisdiction_other` table - no column changes, no data migration, no query rewrites.
- **The ID namespace is reserved now.** BPS IDs are six numeric digits held as `TEXT`. Any synthesized ID
  takes a non-numeric prefix: `T-000123` tribal, `D-000123` district. A synthesized ID therefore cannot
  silently collide with a real BPS office, and a mistaken join fails loudly rather than returning
  plausible garbage.

Non-BPS jurisdictions, when admitted, are a **separate population** and are reported separately.

## Consequences

- Every claim stays denominated against a single, externally-defined, independently-auditable universe.
  This is most of why the coverage figures are defensible at all.
- The cost of deferring is one view definition. That is the entire migration burden, which is the reason
  building the table now is unjustified rather than merely premature.
- The namespace reservation is free today and expensive to retrofit: renumbering identifiers after rows
  reference them means rewriting every link. One sentence of decision buys that.
- **Coverage statistics do not extend to non-BPS jurisdictions - they fork.** `16.63% of national
  authorized units` is defined against the BPS universe; a tribal permit has no BPS unit count to be a
  fraction of. Admitting these jurisdictions creates a second population with its own denominator, and
  conflating them would quietly make the headline number mean something other than what it says. This
  belongs in the writeup, not only in the schema.
- Tribal permits remain uncollected until this is revisited. That is a real, stated coverage gap, not an
  oversight, and it should be named in any completeness claim.

## Alternatives considered

- **A `jurisdiction` table now, with BPS offices as one kind.** The textbook-correct model, and it buys
  nothing before a non-BPS jurisdiction exists to put in it. It costs a join on every query and an
  identity indirection on every debugging session, immediately, in exchange for a migration that the
  `office` view already reduces to one line.
- **Join `bps_frame` directly and migrate later when needed.** Saves writing the view. Pays for it by
  touching every query at migration time, which is the expensive half.
- **Synthesize numeric IDs in an unused BPS range.** Keeps the column numeric and looks tidier. Rejected:
  a collision with a real BPS ID then joins silently and returns a wrong answer, which is the worst
  available failure mode for exactly the kind of error this project keeps making (see ADR-0001, Context).
- **Widen the frame to a non-Census source with broader coverage.** Would address tribal coverage
  directly. Out of scope for the gate, and it would forfeit the BPS control total that the entire
  reconciliation claim in Spike B depends on.

## Revisit when

A permit source is found that serves a jurisdiction with no BPS office - most likely a tribal housing
authority. One real instance justifies `jurisdiction_other` and the `UNION`; zero instances do not.

## References

- `DESIGN.md` §D3 (BPS ID as identity), catalog sweep composition table (9 publishers were real
  government bodies with no BPS office at their level)
- [`docs/design/entity-resolution.md`](../design/entity-resolution.md) - the `office` view
- [ADR-0001](0001-source-office-link-is-an-evidence-bearing-relation.md)
