# Entity resolution: sources, offices, and permits

**Status: living.** How the system works today. The decisions behind it are fixed in
[ADR-0001](../adr/0001-source-office-link-is-an-evidence-bearing-relation.md),
[ADR-0002](../adr/0002-no-mirror-relation.md) and
[ADR-0003](../adr/0003-jurisdiction-identity-is-bps-scoped.md) - read those for *why*, and amend this
document freely for *what*. The measurements it rests on are in
[`docs/evidence/`](../evidence/).

Everything below was derived from the 2026-09-19 catalog sweep of 443 publisher names. Where a figure
appears, it is that sweep's; re-running the sweep supersedes it with a new dated evidence report rather
than an edit here.

## Three distinct problems, not one

The catalog sweep forced this into the open, so it is recorded here as a design constraint rather than a
matching detail. **The project contains three separate entity-resolution problems. They have different
keys, different error tolerances, and different correct answers, and conflating them is how the sweep
produced a wrong number twice.**

| # | Problem | Link | If it is wrong |
|---|---|---|---|
| 1 | **Office identity** - which permit office is this? | six-digit BPS ID (D3) | Everything downstream is misattributed |
| 2 | **Publisher linkage** - which office does this portal belong to? | name + geography, no shared key | A jurisdiction is double-counted or silently missed |
| 3 | **Permit identity** - which observations are the same permit? | `observation_key` -> `permit_id` (D5) | The headline reconciliation metric is corrupted |

**Problem 1 is solved and closed.** The BPS ID is the identity; name and FIPS place are attributes, both
measurably non-unique (section 2). Nothing further is needed.

**Problem 2 is what the sweep ran into**, and it is classic record linkage: two datasets, no shared key,
only a human-written label on each side. Four things that worked, in order of how much they mattered:

1. **Prefer an authoritative attribute over string similarity.** ArcGIS item extents give a bounding box;
   its centroid through the FCC Area API gives an authoritative state and county. That resolved 233
   publishers geographically and made "which Victoria / which Springfield / which Aurora" a lookup rather
   than a guess. **String similarity was the last resort, not the first.**
2. **Block on the hard attribute, match on the soft one.** Restrict candidates to the geocoded state and
   county *first*, then compare names inside that block. Fuzzy matching across the whole country is how
   *City of Charlotte* becomes a town in New Hampshire.
3. **Require type agreement on both sides.** A county-level publisher may only match a county-level
   office. This is the trap below, and it recurred a second time in a form the first fix did not cover.
4. **Leave the genuinely ambiguous unresolved.** 19 names are the same in several states with no
   geography to separate them. They are reported as unresolved rather than guessed, and the count is
   quoted as a lower bound. **A wrong link is far more expensive than a missing one** - a missing link
   costs coverage, a wrong link silently attributes one jurisdiction's permits to another.

**The structural finding, which matters well beyond the sweep: a BPS office is not a municipality, and
the linkage is many-to-one.** Measured:

- **Mecklenburg County NC is the only permit office in the county.** Charlotte - a top-20 US city - has
  no BPS office of its own. *City of Charlotte* open data links to the **county** office.
- **New York City is five borough offices**, not one. One portal, five offices.
- **Memphis has no BPS office**; Shelby County TN has three and none of them is Memphis.
- **Fulton County GA has 15 municipal offices and no county office.** The county portal publishes permit
  data for permits the county does not issue.

**Consequences to carry into steps 1-4:**

- The frame's office is the unit of account, and a source may cover **several** offices or **part of**
  one. The source-to-office link therefore needs its own table with cardinality, not a column on either
  side. Seven offices already have more than one publisher mapped to them.
- **D5 inherits this.** If one portal covers five borough offices, `observation_key` must carry the
  office, not the portal - otherwise permits from different offices collide in the same key space.
- **Spike B inherits it too.** Reconciling a city portal against "the BPS figure for that city" is
  incoherent where no such office exists. Sample only offices whose boundary matches a real source.

**Problem 3 (D5) is unchanged in design but now has a measured reason to be strict.** Same lesson: prefer
an authoritative key, block before you match, and never let a fuzzy match create an identity.

**The trap, recorded twice because it recurred.** Normalizing "county" out of both sides joins *County of
Los Angeles* to *Los Angeles city* and *Miami-Dade County* to *Miami city* - different offices, very
different volumes. The first fix required a county/municipality flag to agree on both sides. **It then
recurred anyway** on Socrata hosts, because `\bcounty\b` cannot see the word inside `sandiegocounty.gov`:
`data.marincounty.gov` matched **Marina**, a different city 150 miles away. Detection must handle
`county` glued inside a token. Both runs are in `bucket1_audit.csv`.

## Schema: `source` and `source_office_link`

Falls directly out of the measured finding above - a source may cover several offices, an office may have
several sources, and the relationship carries its own metadata - so it **cannot** be a column on either
side. All three forks below were adjudicated on 2026-09-20; the DDL reflects the decisions.

```sql
-- A thing we can fetch from. ONE ROW PER ENDPOINT, not per jurisdiction.
-- The grain matters: the partial unique index below depends on it (see 'Mirrors').
CREATE TABLE source (
  source_id          TEXT PRIMARY KEY,   -- surrogate; stable across renames
  source_type        TEXT NOT NULL,      -- socrata | arcgis | portal_html | api | bulk_file
  endpoint           TEXT NOT NULL,      -- domain + dataset id, or base URL
  publisher_label    TEXT,               -- the catalog's human string, verbatim, never parsed for identity
  robots_posture     TEXT,               -- as observed, with observed_at
  status             TEXT NOT NULL,      -- active | dead | superseded
  first_observed_at  TIMESTAMP NOT NULL, -- transaction time (D7)
  last_observed_at   TIMESTAMP NOT NULL
);

-- The entity-resolution artifact. Many-to-many, append-only, evidence-bearing.
CREATE TABLE source_office_link (
  link_id          TEXT PRIMARY KEY,
  source_id        TEXT NOT NULL REFERENCES source(source_id),
  state_fips       TEXT NOT NULL,        -- (state_fips, bps_id) is the office identity, per D3
  bps_id           TEXT NOT NULL,

  coverage         TEXT NOT NULL,        -- full | partial | unknown
  coverage_note    TEXT,                 -- e.g. 'permits from 2019 only', 'residential only'

  link_method      TEXT NOT NULL,        -- geo_confirmed | name_unique | hand_adjudicated
                                         -- | volume_heuristic | unresolved
  confidence       TEXT,                 -- NULLABLE: A | B | C, and NULL exactly when unresolved
  evidence         JSONB NOT NULL,       -- centroid, county FIPS, catalog record id, adjudicator note

  fetch_precedence INT NOT NULL DEFAULT 100,  -- lower wins when one office has several live sources

  valid_from       DATE NOT NULL,        -- VALID time: when the link became true of the world
  valid_to         DATE,                 -- NULL = still true
  asserted_at      TIMESTAMP NOT NULL,   -- TRANSACTION time: when we came to believe it
  superseded_at    TIMESTAMP,            -- when we stopped believing it (denormalized, see below)
  superseded_by    TEXT REFERENCES source_office_link(link_id),

  -- Downstream cannot silently drop the unresolved set if the schema refuses to
  -- let an unresolved row carry a confidence tier, or a resolved row omit one.
  CONSTRAINT unresolved_iff_no_confidence
    CHECK ((link_method = 'unresolved') = (confidence IS NULL)),
  CONSTRAINT partial_needs_note
    CHECK (coverage <> 'partial' OR coverage_note IS NOT NULL),
  CONSTRAINT retraction_is_paired
    CHECK ((superseded_by IS NULL) = (superseded_at IS NULL)),
  CONSTRAINT valid_interval_ordered
    CHECK (valid_to IS NULL OR valid_to > valid_from)
);

-- At most one LIVE link per (source, office). This is the constraint that stops a
-- resolver re-run from quietly producing two live rows and double-counting units.
CREATE UNIQUE INDEX one_live_link
  ON source_office_link (source_id, state_fips, bps_id)
  WHERE superseded_by IS NULL AND valid_to IS NULL;

-- Indirection, not a table (fork 3). Today it is the frame verbatim; if non-BPS
-- jurisdictions ever enter scope they are UNIONed in here and no query changes.
CREATE VIEW office AS
  SELECT state_fips, bps_id, place_name, units_12mo FROM bps_frame;

CREATE VIEW link_live AS
  SELECT * FROM source_office_link
   WHERE superseded_by IS NULL AND valid_to IS NULL AND link_method <> 'unresolved';

CREATE VIEW link_worklist AS
  SELECT * FROM source_office_link
   WHERE superseded_by IS NULL AND link_method = 'unresolved';

-- Coverage carries its own uncertainty in the SAME ROW, so a consumer has to
-- actively discard the caveat rather than merely forget it.
CREATE VIEW coverage_stat AS
  SELECT (SELECT count(*) FROM (SELECT DISTINCT state_fips, bps_id FROM link_live) t)
           AS offices_linked,
         (SELECT sum(o.units_12mo) FROM office o WHERE EXISTS (
            SELECT 1 FROM link_live l
             WHERE l.state_fips = o.state_fips AND l.bps_id = o.bps_id))
           AS units_linked,
         (SELECT count(*) FROM link_worklist)
           AS sources_unresolved;   -- >0 means every figure above is a LOWER BOUND
```

**Why each non-obvious column is there:**

- **`confidence` lives on the link, not the source.** One portal can link confidently to one office and
  speculatively to another. The A/B/C tiers from the resolved sweep populate this directly.
- **`evidence` is mandatory and structured.** Every wrong link in this project so far was recoverable
  only because the evidence was inspectable. `bucket1_audit.csv` is the flat-file ancestor of this column.
- **`link_method = 'unresolved'` rows are kept, not dropped.** The 19 ambiguous names become rows with a
  candidate list in `evidence`. That makes the unresolved set a **worklist** rather than silent
  under-coverage, and it makes the lower-bound claim auditable.
- **Bitemporal, consistent with D7 and D1.** Jurisdictions migrate platforms and consolidate offices;
  links are corrected. Append + supersede, never update in place, so a past claim stays reproducible.
- **`publisher_label` is stored verbatim and never parsed for identity.** It is evidence, not a key.

### `valid_to` vs `superseded_by`: the two are not interchangeable

This is the single most confusable pair in the schema, so state it once, precisely:

| | `valid_to` set | `superseded_by` set |
|---|---|---|
| Means | The link **stopped being true** of the world | The link **was never true**; we were wrong |
| Example | Portland migrates Socrata -> ArcGIS, 2024-03-01 | `data.marincounty.gov` -> Marina (the glued-`county` bug) |
| The old row is | **Still correct** about its interval; keep querying it for that period | **Never** usable, for any period |
| Axis | Valid time | Transaction time |

The two are orthogonal and both can be set on one row. The rules that follow:

- **Every query filters `superseded_by IS NULL` unconditionally**, then filters valid time for the
  as-of date. Retraction is not a time-travel dimension; it is a correction.
- **A retraction never sets `valid_to`.** The retracted row keeps its original claimed interval. Closing
  it would assert the link *was* true until some date, which is exactly the false claim being retracted.
- **`superseded_at` is denormalized** from the successor's `asserted_at`. Strictly it is derivable by a
  self-join, but the belief-state query ("what did we think on date T") then needs that join on every
  read. One redundant timestamp, guarded by `retraction_is_paired`, buys a scan instead.

### Rolling `confidence` up to the source

The rollup is **MIN, i.e. pessimistic**, and it is **a view, never a stored column.**

Pessimistic because a source resolving to five offices with one guess among them is not an A-confidence
source; taking the MAX would launder the guess into the other four. Never stored because a denormalized
confidence that drifts out of date is precisely the class of silent error the rest of this architecture
exists to prevent, and recomputation is cheap. Triage reads `worst_confidence`; `best_confidence` is
reported alongside it only so a mixed source is visibly mixed.

### Adjudicated forks

1. **`coverage = 'partial'` direction - DECIDED: flat enum, no direction.** Enforced by
   `partial_needs_note`, so the ambiguity is resolved in prose at write time rather than inferred at read
   time. Revisit only if step 1 turns up a third shape.
2. **Rows for offices with no source - DECIDED: no.** Absence is an anti-join against `office`.
3. **FK target - DECIDED: the frame, via the `office` view.** See the next section for why the view is
   the whole forward-compatibility story.

## Cross-portal duplication

**Answer: no new table, one new column (`fetch_precedence`), and the dedup happens somewhere else.**

Worth first rejecting the premise I was handed, because it points at the wrong layer. Duplication does
**not** clutter the bitemporal history. Two portals publishing Austin produce two live link rows, and that
is *correct* - there really are two places to fetch from, neither row is churning, and neither is a
correction of the other. Portal migration does add rows over time, but those rows are the reproducibility
guarantee, not clutter; discarding them is what would break D7.

The real damage duplication does is one layer down and considerably worse than untidiness: **fetching
both and folding both double-counts Austin's permits.** That is a data-integrity bug, and it would surface
in Spike B as a ~2x discrepancy against the BPS control total.

So the question is not "are these the same source" but two separate operational questions:

- *Which do I fetch from?* -> an **ordering**. `fetch_precedence`, lowest wins. Zero new tables.
- *Are these the same permit?* -> **`observation_key`**, already in the design (D5). Dedup belongs at the
  observation layer where actual records can be compared, not at the source layer where it is a guess.

**Why not assert a `mirrors` relation:** "mirror" is almost never exact. The county's copy of city data
typically has different fields, different update latency, and shallower history. Asserting equivalence
between two sources is a strong claim that is usually false in detail, and it would be an *unevidenced*
claim in a schema whose whole discipline is that claims carry evidence. If a real overlap is ever
*measured* - "source B's records are a strict subset of source A's, checked over N months" - that is an
empirical finding and earns its own table with the measurement attached. Not before.

Known duplication shapes already visible in the sweep, all handled by precedence alone: city Socrata vs
county ArcGIS aggregation; the 18 statewide publishers republishing municipal data; a dead endpoint left
live through a migration; the same ArcGIS item surfaced under several org pages.

## Is `(state_fips, bps_id)` a concrete jurisdiction ID?

Yes, and it is **deliberately scoped**: it identifies exactly the things BPS treats as permit-issuing
places, which is the right scope while every claim is denominated against BPS. Special districts, joint
powers authorities and tribal governments are a real gap, and the correct move is to make the gap cheap to
close later rather than to model it now.

**Ranking the gap honestly**, since the three named cases are not equally real:

- **Tribal governments** - the substantive one. They do issue building permits on trust land, and BPS
  coverage there is essentially absent. A genuine hole in the frame, not a hypothetical.
- **Special districts** - weakest. Water, fire and school districts overwhelmingly do not issue *building*
  permits. Fire districts issue some permits, rarely building ones.
- **JPAs** - rare for building permits specifically.
- **The case not named, and the most common of all**: contract or consolidated permitting, where a city
  contracts issuance to the county. Already in the data (Mecklenburg/Charlotte), and already handled - it
  is a many-to-one link, not a missing jurisdiction type.

**The forward-compatible move, at near-zero cost today: the `office` view above.** Everything joins the
view, never `bps_frame` directly. Admitting non-BPS jurisdictions later means redefining one view as a
UNION over a `jurisdiction_other` table. No column changes, no data migration, no query rewrites. That is
the entire cost of not building it now, and it is why building it now is unjustified.

**One decision to take today, because it is annoying to retrofit: reserve the ID namespace.** BPS IDs are
six numeric digits held as TEXT. Any synthesized ID gets a non-numeric prefix - `T-000123` tribal,
`D-000123` district. A synthesized ID then cannot silently collide with, or accidentally join against, a
real BPS office; a mistaken join fails loudly instead of returning plausible garbage.

**The caveat that actually matters, and belongs in the writeup:** adding these jurisdictions does not
extend the coverage statistic, it creates a **second population**. "16.63% of national units" is defined
against the BPS universe; a tribal permit has no BPS unit count to be a fraction of. Non-BPS jurisdictions
must be counted and reported separately or the headline number quietly stops meaning what it says.

## Open items

- **19 publisher names remain unresolved** - the same name in several states, no geography available.
  They become `link_method = 'unresolved'` rows and are a worklist, not a silence. Every coverage figure
  quoted from this data is a lower bound until they are adjudicated.
- **3 tier-C matches are volume-disambiguated only.** Quote A+B; mention C separately or not at all.
- **`fetch_precedence` has no defaulting rule yet.** It currently defaults to 100 for every row, which
  means ties are unordered wherever an office has two live sources. A rule derived from `coverage` and
  `confidence` is the obvious candidate; it is not written because no office has yet needed it.
