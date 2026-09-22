# -*- coding: utf-8 -*-
"""Adapter for Accela Citizen Access - the bucket-3 HTML path.

Accela is the largest US local-government permitting vendor, and Spike A
found that every Accela agency accepts an empty search and returns records,
which makes the whole fleet enumerable rather than address-keyed. The probes
in `scripts/step1_accela_probe*.py` then settled the three mechanics this
adapter depends on:

  - the **date filter is real**. A window of 03/02/2026 returns only rows
    dated 03/02/2026. (Probe 1 got byte-identical pages for 1d/7d/31d windows
    and that looked like the filter being ignored; it was the grid's
    date-descending sort putting the same ten rows on top of every window.
    Comparing page sizes could not tell those apart. Reading the rows could.)
  - the **pager works blind**. Accela renders no pager control on a capped
    result set, but the ASP.NET GridView contract - `__EVENTTARGET` = the grid,
    `__EVENTARGUMENT` = `Page$N` - returns rows 11-20 anyway.
  - **"100+" is a display cap, not a result cap.** It rolls over to "200+" at
    page 11 and the walk keeps returning new records.

Two consequences shape the code:

**The index grid is the extraction target, not the detail page.** One index
page carries ten records with date, number, permit type, description, status
and address already separated into cells. A detail page carries one record for
the same ~500KB. Extracting from the index is ten times cheaper per record
before any other saving, and the type strings ("Residential Building New") are
as classifiable as any Socrata `permit_class`.

**Column order is per tenancy, so parsing is header-driven.** Clark County
renders Date|Number|Type|Description|..., Oregon renders |Number|Status|Type|
Agency|Address|Date|... Positional parsing would work on the tenancy it was
written against and silently mis-assign every field on the next one. Oregon's
extra `Agency` column is also how one statewide tenancy is attributed to many
D3 offices.

**Windows must be closed and in the past.** The grid sorts date-descending, so
paginating an open-ended "recent" set means rows shift between pages as new
permits are issued and the walk both duplicates and misses records. A closed
past window cannot change underneath the walk.

As with `opendata.py`: this module locates native strings, `permits.vocab`
interprets them, and `permits.emit` owns normalization. Same interface, second
platform - which is the actual test of section 9's obligation 1.
"""
import re

from .. import aspnet, emit, vocab

ADAPTER_VERSION = "accela/1.0"

PFX = "ctl00$PlaceHolderMain$generalSearchForm$"
GRID = "ctl00$PlaceHolderMain$dgvPermitList$gdvPermitList"
SEARCH_BTN = "ctl00$PlaceHolderMain$btnNewSearch"
HOME = "%s/Cap/CapHome.aspx?module=%s&TabName=%s"

ROWS_PER_PAGE = 10

SHOWING = re.compile(r"Showing\s*(\d+)\s*-\s*(\d+)\s*of\s*([\d,]+)(\+?)", re.I)
ROWPAT = re.compile(r'<tr class="ACA_TabRow_(?:Odd|Even)[^"]*">(.*?)</tr>',
                    re.I | re.S)
CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.I | re.S)
THPAT = re.compile(r"<th[^>]*>(.*?)</th>", re.I | re.S)
NUMSPAN = re.compile(r"lblPermitNumber1?[^>]*>([^<]+)", re.I)
DETAILHREF = re.compile(r'href="([^"]*CapDetail\.aspx\?[^"]*)"', re.I)

# Header text -> the role the column plays. Matched case-insensitively on a
# substring, longest first, so "Permit/Application Number" and "Record Number"
# both land on `number` without an entry each.
ROLES = [
    ("permit/application number", "number"), ("permit number", "number"),
    ("record number", "number"), ("permit no", "number"),
    ("permit type", "type"), ("record type", "type"), ("type", "type"),
    ("project name", "project"),
    ("description", "description"), ("short notes", "notes"),
    ("agency", "agency"),
    ("status", "status"),
    ("expiration", "expires"), ("expires", "expires"),
    # Oregon heads the issue column "Opened", Clark and Yakima head it "Date",
    # St. Johns "Issue Dt". Ordered before the bare "date" so "Expiration
    # Date" cannot win it.
    ("opened", "date"), ("issue", "date"), ("date", "date"),
    ("address", "address"),
    ("action", "action"),
]


class AccelaSource(object):
    """One Accela tenancy, optionally narrowed to one agency within it.

    `agency_code` exists because a statewide tenancy such as `aca-oregon`
    serves many D3 offices from one instance. The rows carry the agency, so
    one crawl can be folded to several offices - but a source is still one
    office, because `(state_fips, bps_id)` is the identity and a row belonging
    to YAMHILL_CO is not a McMinnville permit.
    """

    def __init__(self, key, state_fips, bps_id, label, base, module="Building",
                 tab="Building", agency_code=None, note=None,
                 controlled_type_column=True):
        self.key = key
        self.source_id = "%s|%s|%s" % (state_fips, bps_id, key)
        self.state_fips = state_fips
        self.bps_id = bps_id
        self.label = label
        self.base = base.rstrip("/")
        self.module = module
        self.tab = tab
        self.agency_code = agency_code
        self.platform = "accela-aca"
        self.note = note
        # Accela's Permit Type is a controlled four-level hierarchy -
        # Group/Type/Subtype/Category, e.g. "Building/Building Permit/
        # Residential/New" - which is visible in the search form's own
        # `ddlGSPermitType` option values on every tenancy checked. That is
        # what makes it safe to let the class it maps to imply a unit count.
        # A tenancy that turns out to render operator free text in that column
        # sets this False and the implication stops for that source only.
        self.controlled_type_column = controlled_type_column

    @property
    def home(self):
        return HOME % (self.base, self.module, self.tab)


# ------------------------------------------------------------------ parsing
def _text(s):
    return aspnet.text(s)


def headers(html):
    """Column roles, in order, from the grid's header row."""
    ths = [_text(t) for t in THPAT.findall(html)]
    out = []
    for h in ths:
        low = h.lower()
        role = None
        for needle, r in ROLES:
            if needle in low:
                role = r
                break
        out.append(role)
    return out, ths


def parse_index(html):
    """(rows, stated_total, capped) - rows are dicts keyed by column role.

    Unmapped columns are kept under `col<i>` rather than dropped, so a field
    this adapter does not yet understand is still visible in the raw record
    instead of silently disappearing.
    """
    roles, _raw_headers = headers(html)
    rows = []
    for frag in ROWPAT.findall(html):
        cells = CELL.findall(frag)
        d = {}
        for i, c in enumerate(cells):
            role = roles[i] if i < len(roles) else None
            val = _text(c)
            if role and role not in d:
                d[role] = val
            elif val:
                d.setdefault("col%d" % i, val)
        m = NUMSPAN.search(frag)
        if m:
            d["number"] = _text(m.group(1))
        h = DETAILHREF.search(frag)
        if h:
            d["detail_href"] = aspnet.unescape(h.group(1))
        # The trailing unlabeled column is the work location on every tenancy
        # seen so far; claim it only if no header did.
        if "address" not in d:
            tail = [v for k, v in d.items() if k.startswith("col")]
            for v in tail:
                if re.search(r"\d{2,}\s+\w|,\s*[A-Z]{2}\b", v or ""):
                    d["address"] = v
                    break
        if d.get("number"):
            rows.append(d)
    m = SHOWING.search(html)
    total = int(m.group(3).replace(",", "")) if m else None
    capped = bool(m and m.group(4) == "+")
    return rows, total, capped


# ------------------------------------------------------------------ detail
LABELVAL = re.compile(
    r">\s*([A-Z][A-Za-z0-9 /#\.\-\(\)]{2,48})\s*:\s*</[^>]+>\s*"
    r"(?:<[^>]+>\s*)*([^<>]{0,80})", re.S)
# A label names a dwelling-unit count if it ENDS in "unit"/"units". The
# previous version anchored the whole string - `^(?:number of )?...units?$` -
# and so matched "Number of Residential Units" but not "Existing Number of
# Residential Units", which is the exact pair Santa Barbara County publishes.
# That made this adapter report "no unit field" for a tenancy that has one,
# and it is the same failure family as comparing page sizes to test a date
# filter: the instrument was wrong, not the world. Anchoring the tail rather
# than the head also rejects "Unit Number", "Unit Size" and "Unit Type", which
# are address and equipment fields and were the reason for the head anchor.
UNIT_LABEL = re.compile(r"(?i)\bunits?$|^unit count$|^#\s*of\s*units?$")

# ...unless the units are equipment. "Number of Units" on a mechanical permit
# is air handlers. Nothing here may be counted as a dwelling.
NOT_DWELLING = re.compile(
    r"(?i)\b(?:a/?c|air|hvac|condens|heat|cool|furnace|rooftop|roof-top|"
    r"mechanical|electrical|lighting|storage|parking|solar|pv|panel|"
    r"refrigerat|boiler|compressor|fixture|equipment|sign|tank|meter)\b")

# Which side of an existing/proposed pair a label is on. Santa Barbara County
# states parcel-level totals before and after, not the permit's own delta.
EXISTING = re.compile(r"(?i)\bexisting\b|\bcurrent\b|\bprior\b|\bprevious\b")
PROPOSED = re.compile(r"(?i)\bproposed\b|\bnew\b|\bafter\b|\btotal\b|\bfinal\b")


def detail_fields(html):
    """Label -> value for the fields an Accela record detail renders.

    Accela renders Application Specific Info per record type, so the field set
    differs between a 'Residential Building New' and a 'Miscellaneous
    Structure'. Everything found is returned; choosing among them is the
    caller's job.
    """
    body = re.sub(r"(?is)<script.*?</script>", " ", html)
    out = {}
    for k, v in LABELVAL.findall(body):
        k = _text(k)
        v = _text(v)
        if k and v and k not in out:
            out[k] = v
    return out


def units_from_detail(fields):
    """(units, basis) from a detail field set, or (None, reason).

    Only an explicitly unit-named field counts. Square footage, valuation and
    'Construction Type' are not unit counts, and guessing from them is how a
    reconciliation number gets quietly manufactured.

    **A unit field is not necessarily a unit count.** Santa Barbara County
    publishes `Existing Number of Residential Units` and `Proposed Number of
    Residential Units`, and those are parcel-level totals, not what this permit
    adds. On one of three records sampled both read 185 - an alteration to an
    existing 185-unit property. Taking the proposed figure would have put 185
    phantom dwellings into the reconciliation from a single record. That is the
    Austin sub-permit overcount wearing a different hat, so the pair is
    subtracted and an unpaired "proposed" is refused rather than trusted:
    without an existing count there is no way to tell a total from a delta, and
    the two differ by the entire existing building.
    """
    found = []
    for k, v in fields.items():
        k = (k or "").strip()
        if not UNIT_LABEL.search(k) or NOT_DWELLING.search(k):
            continue
        n = emit.norm_int(v)
        if n is not None:
            found.append((k, n))
    if not found:
        return None, None

    existing = [(k, n) for k, n in found if EXISTING.search(k)]
    proposed = [(k, n) for k, n in found if PROPOSED.search(k)
                and not EXISTING.search(k)]
    plain = [(k, n) for k, n in found
             if not EXISTING.search(k) and not PROPOSED.search(k)]

    if len(existing) == 1 and len(proposed) == 1:
        delta = proposed[0][1] - existing[0][1]
        basis = "%s - %s" % (proposed[0][0], existing[0][0])
        if delta < 0:
            # A net loss of dwellings. Real (conversion, demolition), but not
            # a count of new units, and the pairing may simply be wrong. Either
            # way a negative is not an answer to the question asked.
            return None, "refused:negative-delta (%s)" % basis
        return delta, basis
    if proposed and not existing:
        return None, "refused:proposed-without-existing (%s)" % proposed[0][0]
    if len(plain) == 1 and not existing and not proposed:
        return plain[0][1], plain[0][0]
    if plain and len({n for _, n in plain}) == 1:
        return plain[0][1], plain[0][0]
    return None, "refused:ambiguous (%s)" % ", ".join(k for k, _ in found)


# ------------------------------------------------------------------ record
def build(src, row, vb, content_hash):
    """One index row to one PermitRecord. All interpretation via vocab."""
    rec = emit.PermitRecord(
        source_id=src.source_id, state_fips=src.state_fips,
        bps_id=src.bps_id, native_id=row.get("number"),
        platform=src.platform, extractor_version=ADAPTER_VERSION,
        content_hash=content_hash, native=None)

    ptype = row.get("type") or ""
    desc = " | ".join(x for x in (row.get("description"), row.get("project"),
                                  row.get("notes")) if x)
    rec.description = emit.norm_text(desc)
    rec.address = emit.norm_text(row.get("address"))

    # Classify from the Permit Type column ONLY. That column is Accela's
    # controlled vocabulary; description, project name and short notes are
    # operator free text, and feeding them to these classifiers was measurably
    # wrong on the first unfiltered day pulled:
    #   - "Residential Building Addition" and "Residential Building Remodel
    #     Repair" both classified NEW, because a stray "new" in the narrative
    #     outranked the type.
    #   - "Commercial Building New" classified DEMOLITION on one row and
    #     ELECTRICAL on another, for the same reason.
    #   - 43 records got structure_type "101" from vocab's BPS-code regex
    #     matching a lot number or a street address - "LOT 101" is not
    #     "single-family detached".
    # The free text stays on the record; it just may not decide anything.
    rec.permit_kind, _ = vb.kind(ptype)
    rec.work_class, _ = vb.work(ptype)
    structure, structure_rule = vb.structure(ptype)

    # No unit field exists on an index row. `absent` is the honest value and
    # the drift alarm is what turns it into a blocked error figure rather than
    # a fabricated one. A detail pass may overwrite this later.
    u, _rule = vb.units_from_text(rec.description)
    if u is not None:
        rec.units(u, "parsed_from_text")
    else:
        rec.units(None, "absent")

    structure, refine_rule = vb.refine(structure, rec.unit_count,
                                       rec.work_class)
    rec.structure_type = structure

    # Last resort, and only where the class names a number: a 101 is one
    # dwelling by definition. Runs after `refine` so it can never feed the
    # refinement that would otherwise derive the class back out of the count,
    # and only when nothing was actually stated - a real number always wins.
    imply_rule = None
    if rec.unit_count is None:
        n, imply_rule = vb.imply_units(structure, rec.work_class,
                                       structure_rule,
                                       src.controlled_type_column)
        if n is not None:
            rec.units(n, "implied_by_structure_code")

    rec.native = {"structure_rule": refine_rule or structure_rule,
                  "unit_rule": imply_rule or _rule,
                  "native_type": ptype,
                  "native_status": row.get("status"),
                  "agency": row.get("agency") or src.agency_code,
                  "detail_href": row.get("detail_href")}

    # D6's milestone vocabulary is fixed ("applied", "issued", "finaled",
    # "terminated"); a native status string is not a milestone and mapping one
    # to the other is a per-(platform, jurisdiction) vocabulary decision, not
    # something this adapter may decide. The native string is carried instead.
    rec.milestone("issued", row.get("date"), native_string=row.get("date"))
    return rec


# ------------------------------------------------------------------- pull
def search_body(hidden, lo, hi):
    return aspnet.body(hidden, event_target=SEARCH_BTN, event_argument="",
                       criteria={PFX + "txtGSStartDate": lo,
                                 PFX + "txtGSEndDate": hi})


def page_body(hidden, n):
    return aspnet.body(hidden, event_target=GRID, event_argument="Page$%d" % n)


def pull_window(src, lo, hi, fetch, emitter, vb, max_pages=400, tag=""):
    """Walk one closed date window to exhaustion. Returns a summary.

    `lo`/`hi` are MM/DD/YYYY and inclusive, matching what the form accepts.
    `fetch(url, name, page_type, data=None, headers=None) -> (body, prov)`.
    """
    home = src.home
    hdrs = aspnet.headers_for(home)
    html, _ = fetch(home, "acc_%s_%s_home" % (src.key, tag), "T-SEARCH")
    if html is None:
        return {"error": "no search page", "emitted": 0, "rows_seen": 0,
                "pages": 0}
    hidden = aspnet.hidden_fields(html)

    html, prov = fetch(home, "acc_%s_%s_p1" % (src.key, tag), "T-INDEX",
                       data=aspnet.encode(search_body(hidden, lo, hi)),
                       headers=hdrs)
    if html is None:
        return {"error": "search rejected", "emitted": 0, "rows_seen": 0,
                "pages": 0}

    seen = set()
    n_rows = n_emit = n_rej = 0
    stated = capped = None
    page = 1
    records = []
    while page <= max_pages:
        rows, total, cap = parse_index(html)
        if stated is None:
            stated, capped = total, cap
        fresh = [r for r in rows if r.get("number") not in seen]
        for r in fresh:
            seen.add(r["number"])
            n_rows += 1
            try:
                rec = build(src, r, vb, (prov or {}).get("sha256"))
                emitter.emit(rec)
                records.append(rec)
                n_emit += 1
            except emit.EmitError as e:
                # Only one EmitError is an expected property of the DATA: a
                # row with no native identifier, which D5 says may not be
                # given one here. Every other EmitError is a bug in this
                # adapter, and swallowing it into the same counter turns a
                # code error into a plausible-looking data statistic. That
                # already happened once: `milestone("status", ...)` is not in
                # D6's vocabulary, it threw on every row with a non-blank
                # status, and the run reported "351 rejected_no_id" - which
                # reads like a portal quirk and is nothing of the kind.
                if isinstance(e, emit.MissingIdentifier):
                    n_rej += 1
                else:
                    raise
        if not fresh or len(rows) < ROWS_PER_PAGE:
            break
        page += 1
        hidden = aspnet.hidden_fields(html)
        html, prov = fetch(home, "acc_%s_%s_p%d" % (src.key, tag, page),
                           "T-INDEX",
                           data=aspnet.encode(page_body(hidden, page)),
                           headers=hdrs)
        if html is None:
            break
    return {"rows_seen": n_rows, "emitted": n_emit, "rejected_no_id": n_rej,
            "pages": page, "stated_total": stated, "display_capped": capped,
            "records": records}


def vocabulary_for(src):
    return vocab.Vocabulary(src.source_id, src.platform, default_kind=None)


def page_is_complete(html):
    """Always true for Accela: "100+" is a display cap, not a result cap.

    Probe 2 established that the counter rolls to "200+" at page 11 and the
    `Page$N` walk keeps returning new records, so a capped-looking index page
    is complete in itself - the walk, not the page, is what has to reach the
    end.
    """
    return True
