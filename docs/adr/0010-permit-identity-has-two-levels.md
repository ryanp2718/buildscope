# ADR-0010: Permit identity has two levels — a deterministic observation key and a resolved permit id

Status: Accepted

Date: 2026-09-21

*Back-fill. The decision is D5 in `DESIGN.md` and predates this directory. It is the most load-bearing of
the remaining back-fills because the headline reconciliation metric is computed downstream of it.*

## Context

A permit needs an identity before anything can be counted, and the obvious key does not work. The naive
`(jurisdiction_id, normalized_permit_number)` breaks on five separate mechanisms, each of which occurs in
real portals:

- **application-number-to-permit-number renumbering** — the record changes its own key on issuance
- **annual counter resets** — `2026-0001` is a different permit from last year's `2025-0001`, and some
  jurisdictions drop the year
- **rendering instability** — index page, detail page and PDF disagree on spacing, prefixes and case
- **vendor migration renumbering** — a portal replatform re-keys the entire back catalogue
- **records with no native identifier at all**

Each of these is a *different* failure, and none is detectable from a single observation.

The deeper problem is that the fix and the fact are different kinds of thing. Deciding that two
observations are the same permit is an inference; recording that a fetch returned a page bearing a
particular string is not. Storing both in one column means an inference can never be revised without
rewriting what was observed.

## Decision

**Two levels, and only one of them is a fact.**

```
observation_key = (source_id, source_native_id_raw)   # deterministic at fetch time, never inferred
permit_id       = surrogate assigned by entity resolution
```

- **`observation_key` is computed at capture and never inferred.** It is the raw string the source
  rendered, paired with the source that rendered it. Two portals showing the same permit produce two
  observation keys, which is correct — they are two observations.
- **Entity resolution output is a derived view, not a fact.** The `observation_key -> permit_id` mapping
  lives in its own versioned, recomputable table. Writing `permit_id` into the log would mean un-merging
  requires rewriting history, which is precisely what [ADR-0006](0006-the-observation-log-is-the-source-of-truth.md)
  exists to prevent.
- **Fixed resolution rules.** Revisions (`-R1`, `-REV2`) are the same permit and the revision is a
  lifecycle event. A renewal with a new number is a *different* permit, linked by a `supersedes` edge. A
  record with no native ID gets a content-derived key over
  `(jurisdiction, normalized_address, type, application_date)`, flagged low-confidence and excluded from
  BPS reconciliation if that population is material.

**Step 1 implements the first level only, and refuses rather than approximating the second.**
`permits/emit.py` raises `MissingIdentifier` for a row with no native ID, and that exception is its own
type rather than a message string, because it is the only `EmitError` an adapter may legitimately count
and continue past — it is a property of the source data rather than a bug in the adapter. Distinguishing
them by message text was tried and is too fragile for an interface a synthesized extractor also has to
satisfy.

## Consequences

- **The surrogate is not built yet and nothing in step 1 needs it.** Every source pulled so far publishes
  a native identifier on every record; `MissingIdentifier` has not fired in production. The decision is
  currently paying only for the discipline of not minting a surrogate, which costs nothing.
- **D5's own caveat is the honest framing and it still holds.** For aggregate BPS reconciliation *alone*,
  the simple composite key would suffice — a few percent of identity error washes out in monthly unit
  counts. The surrogate earns its keep in the transition view, where a false merge fabricates a status
  change and a false split hides one. **It is justified only because
  [D6's](0011-milestones-are-rows-with-a-fixed-vocabulary.md) lifecycle view is a committed deliverable.**
  If that deliverable is cut, this decision should be reopened rather than kept out of habit.
- **Cross-portal duplication is an ordering problem, not an identity problem.** That is
  [ADR-0002](0002-no-mirror-relation.md)'s separate decision, and it works *because* observation keys are
  per-source: the dedup happens in the observation layer over distinct keys rather than by pretending two
  sources produced one row.
- **Content-derived keys are a step-1 refusal, not a step-1 feature.** The rule is written down and
  unimplemented. A record with no identifier is dropped loudly and counted. That is the right direction of
  error — a dropped record is visible in a reconciliation gap, a wrongly-merged one is not — but it is a
  known unmeasured population.
- **`observation_key` is a string join, not a tuple.** `emit.py` renders it as `source_id|native_id`,
  which is convenient and is a latent problem the first time a `source_id` or a native id contains a pipe.
  Recorded here rather than fixed, because no current source does.

## Alternatives considered

- **One level: normalize the permit number and use it as the identity.** Simplest, and sufficient for the
  only metric the project currently publishes. Rejected on the five failure mechanisms above, all of which
  are silent — the key still joins, it just joins the wrong things.
- **Content-derived keys for everything, ignoring native identifiers.** Uniform, and immune to
  renumbering. Rejected because it throws away the strongest available signal in favour of a weaker one
  everywhere, in order to handle a minority case; and because address normalization is itself an unsolved
  problem that would then sit under every record rather than under the few that need it.
- **Assign `permit_id` at capture and repair it later.** Rejected as the specific thing the architecture
  exists to prevent: it makes un-merging a history rewrite. The asymmetry is the same one in
  [ADR-0006](0006-the-observation-log-is-the-source-of-truth.md) — a derived view can be recomputed, a
  log cannot be un-written.
- **Fail the run on a record with no native ID, rather than counting and continuing.** Rejected because
  the condition is a property of the source rather than of the code, and a source that legitimately
  publishes some unidentified records would be unpullable. Hence `MissingIdentifier` as a distinct type:
  countable, but only that one.

## Revisit when

The first source appears whose records genuinely lack native identifiers at a material rate — at which
point the content-derived key stops being a written rule and has to be built and scored. Also revisit if
D6's lifecycle view is cut from scope, because the surrogate's entire justification goes with it and
carrying an unbuilt second level would then be cargo.

## References

- `DESIGN.md` §D5, §D6, §4 (data model sketch)
- [ADR-0006](0006-the-observation-log-is-the-source-of-truth.md) — why a derived view may not be written
  into the log
- [ADR-0002](0002-no-mirror-relation.md) — cross-portal duplication as observation-layer dedup
- [ADR-0007](0007-office-identity-is-the-bps-office-id.md) — the *office* half of identity
- `permits/emit.py` — `observation_key`, `MissingIdentifier`
- [`docs/design/entity-resolution.md`](../design/entity-resolution.md)
