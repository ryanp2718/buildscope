# -*- coding: utf-8 -*-
"""Adapter for St. Johns County FL's WATS permit search - the best source yet.

Spike A filed this portal in bucket 4, "search-only, needs a known address,
parcel or permit number", and DESIGN.md's 73.1% unit-weighted reachability
rests on bucket 4 being acquirable. It was misclassified. The form renders
`TextBoxFromDt`/`TextBoxToDt`, a date range is not an address, and a
date-bounded POST returns the whole result set in one request.

On every axis that matters it beats the Accela fleet it was supposed to be
worse than:

                        Accela (Clark County)      St. Johns WATS
  records per request   10                         up to 500
  bytes per record      54.6 KB                    0.76 KB
  structure class       absent                     published per record
  date semantics        record opened              "Issue Dt", explicit
  unit count            absent                     absent (but see below)

**The structure class is the jurisdiction's own published code, not a guess.**
The search form's `ddPU` dropdown renders all 69 Property Use codes with their
labels, so the table below is transcribed from the county stating what its own
codes mean. That is strictly better evidence than keyword-matching a type
string, and it is why this source needs no `STRUCTURE_KEYWORDS` pass at all.

**The 101-105 block is BPS's residential classification exactly. Above 105 the
code space is local and diverges from BPS, sharply.** The county's labels
confirm 101 "1 SINGLE FAMILY(DETACHED)", 102 "1 SINGLE FAMILY (ATTACHED)",
103 "2 FAMILIES", 104 "3 & 4 FAMILIES", 105 "5 OR MORE FAMILIES" - the same
classes BPS counts by, in the same order. But St. Johns' 435 is residential
roofing where BPS's 435 is garages and carports; its 329 is swimming pools
where BPS's 329 is structures other than buildings; its 328 is residential
sheds where BPS's is other nonresidential buildings. So these codes may be
read as BPS classes **only** in the residential block, and this module never
passes one through as a BPS code outside it. Assuming otherwise would have
filed 273 roofing permits as garages and 91 swimming pools as new buildings.

**Three exclusions, each of which would otherwise inflate the comparison.**
700 MOBILE HOME - the Census building permit survey excludes manufactured
housing, which is counted by a separate program, so a mobile home permit is
not a BPS dwelling. 660/665 RESIDENTIAL/COMMERCIAL COMPLETION - a completion
is not an issuance and counting it would double every finished house. 328D
RESIDENTIAL ACCESSORY DWELLINGS - a real dwelling, but whether BPS counts an
ADU as a new unit or as an alteration depends on whether it is a new detached
structure, and the code does not say. Excluded and counted, not guessed at.

**Units are implied, never stated.** There is no unit column anywhere, so
101/102 imply one dwelling and 103 implies two via
`unit_count_source = "implied_by_structure_code"`; 104 ("3 & 4") and 105
("5 or more") name no number and are refused. In 1,051 rows sampled that costs
almost nothing - 168 x 101, 49 x 102, 1 x 103, zero 104 and zero 105 - so this
county's dwelling output is essentially all low-density and essentially all
recoverable. It also means the entire unit total is implied, the drift alarm
says so, and the comparison against BPS is therefore a test of the implication
rule itself: BPS's u1 column for this county counts the same permits, so a gap
between our count and theirs *is* the units-per-permit factor.

**Truncation is a hard error, never a warning.** The portal caps a result set
and says so - "Maximum record retrieved, List is incomplete." A truncated
window that is quietly accepted is a plausible-looking undercount with no
signal, which is the failure this project keeps finding. `pull_window` treats
the banner as a control-flow event and bisects the window until every part
comes back complete.
"""
import re

from .. import aspnet, emit, vocab

ADAPTER_VERSION = "stjohns/1.0"

URL = "https://webapp.sjcfl.us/watswebx/permit/SearchPermit.aspx"
FROM = "ctl00$cphBody$TextBoxFromDt"
TO = "ctl00$cphBody$TextBoxToDt"
SUBMIT = ("ctl00$cphBody$btnSearch", "Search")

GRID = "cphBody_gvSearch"
ROWPAT = re.compile(r'(?is)<tr class="Row"[^>]*>(.*?)</tr>')
CELL = re.compile(r"(?is)<td[^>]*>(.*?)</td>")
PERMIT = re.compile(r"(?is)PopPermit\('([^']+)'\)")
TRUNCATED = re.compile(r"(?i)maximum record retrieved|list is incomplete")

# Column order, confirmed against the header row on every page captured.
# Positional because this grid has exactly five unnamed-by-role columns and
# one tenancy; `headers()` below asserts the order still holds rather than
# trusting it.
COLUMNS = ("number", "address", "propuse", "issued", "contractor")
EXPECT_HEADERS = ("permitno", "addr", "propuse", "issue", "contractor")

S = vocab.spec
B = "BUILDING"

# The county's own legend, from the `ddPU` dropdown of its search form.
# Labels are quoted as rendered so a future change to the legend is a visible
# diff rather than a silent reclassification.
PROPUSE = {
    # -- BPS residential classes. Labels confirm the mapping. -------------
    "101":  S("1 SINGLE FAMILY(DETACHED).", emit.SF_DETACHED, "NEW", B, 1),
    "101M": S("SINGLE FAMILY (MODULAR)", emit.SF_DETACHED, "NEW", B, 1),
    "102":  S("1 SINGLE FAMILY (ATTACHED)", emit.SF_ATTACHED, "NEW", B, 1),
    "103":  S("2 FAMILIES", emit.TWO_FAMILY, "NEW", B, 2),
    # 3-4 and 5+ name a range, not a number. Structure is known, units are not.
    "104":  S("3 & 4 FAMILIES.", emit.THREE_FOUR, "NEW", B),
    "105":  S("5 OR MORE FAMILIES", emit.FIVE_PLUS, "NEW", B),
    # Mixed residential/commercial. BPS counts the dwellings in these.
    "601":  S("SINGLE FAMILY W/ATTACHED COMMERCIAL", emit.SF_DETACHED,
              "NEW", B, 1),
    "602":  S("TOWNHOUSE W/ ATTACHED COMMERCIAL", emit.SF_ATTACHED,
              "NEW", B, 1),
    "603":  S("DUPLEX W/ ATTACHED COMMERCIAL", emit.TWO_FAMILY, "NEW", B, 2),
    "604":  S("3 & 4 FAMILIES W/ ATTACHED COMMERCIAL", emit.THREE_FOUR,
              "NEW", B),
    "605":  S("5 OR MORE FAMILIES W/ATTACHED COMM.", emit.FIVE_PLUS,
              "NEW", B),

    # -- excluded from any BPS comparison, with the reason on the record --
    "700":  S("MOBILE HOME", None, "NEW", B,
              exclude="mobile-home: outside the Census building permit survey"),
    "660":  S("RESIDENTIAL COMPLETION", None, "OTHER", B,
              exclude="completion record, not an issuance"),
    "665":  S("COMMERCIAL COMPLETION", None, "OTHER", B,
              exclude="completion record, not an issuance"),
    "328D": S("RESIDENTIAL ACCESSORY DWELLINGS", None, "NEW", B,
              exclude="ADU: new-unit vs alteration not determined by the code"),

    # -- new nonresidential. Real building permits, no dwellings. ---------
    "213":  S("HOTEL/MOTEL", None, "NEW", B),
    "214":  S("NONHOUSEKEEPING SHELTER", None, "NEW", B),
    "318":  S("AMUSEMENT", None, "NEW", B),
    "319":  S("CHURCH", None, "NEW", B),
    "320":  S("INDUSTRIAL/FACTORY", None, "NEW", B),
    "320S": S("INDUSTRIAL/FACTORY SHELL", None, "NEW", B),
    "321":  S("PARKING GARAGES", None, "NEW", B),
    "322":  S("SERV.STATION & REPAIR GAR.", None, "NEW", B),
    "323":  S("HOSPITAL", None, "NEW", B),
    "324":  S("OFFICE BANKS PROFESSIONAL", None, "NEW", B),
    "324M": S("OFFICE, BANKS, PROFESSIONAL, MODULAR", None, "NEW", B),
    "324S": S("OFFICE, BANKS, PROFESSIONAL, SHELL", None, "NEW", B),
    "325":  S("PUBLIC WKS.&UTILITIES", None, "NEW", B),
    "326":  S("SCHOOLS & OTHER EDUC.", None, "NEW", B),
    "326M": S("SCHOOLS/EDUCATION MODULAR", None, "NEW", B),
    "327":  S("STORES/CUSTOMER SERVICES", None, "NEW", B),
    "327S": S("STORES, RESTAURANTS, MALL, SHELL", None, "NEW", B),

    # -- accessory structures, additions, alterations ---------------------
    "328":  S("RESIDENTIAL ACCESSORY STRUCTURE SHED,CARPORT,", None,
              "ADDITION", B),
    "328C": S("COMMERCIAL SHED, ACCESSORY STRUCTURE, CARPORT,", None,
              "ADDITION", B),
    "330":  S("SUMMER KITCHEN", None, "ADDITION", B),
    "335":  S("RESIDENTIAL PORCH, SCREEN ROOM/LANAI, GLASS ROOMS", None,
              "ADDITION", B),
    "434":  S("RESIDENTIAL/ADDITION", None, "ADDITION", B),
    "434E": S("RESIDENTIAL EXTERIOR REPAIRS (WINDOW/DOOR, SIDING)", None,
              "ALTERATION", B),
    "434R": S("RESIDENTIAL RENOVATION/REPAIRS (INTERIOR)", None,
              "ALTERATION", B),
    "435":  S("RESIDENTIAL ROOF (REPAIR, REPLACEMENT, NEW)", None,
              "ALTERATION", B),
    "435C": S("COMMERCIAL ROOF(REPAIR, REPLACEMENT, NEW)", None,
              "ALTERATION", B),
    "437":  S("COMMERCIAL ADDITION", None, "ADDITION", B),
    "437B": S("COMMERCIAL BUILD-OUT (PREVIOUS USE SHELL)", None,
              "ALTERATION", B),
    "437R": S("COMMERCIAL RENOVATION", None, "ALTERATION", B),
    "438":  S("RESIDENTIAL GARAGES/CARPORT (DETACHED)", None, "ADDITION", B),
    "650":  S("CHANGE OF OCCUPANCY/USE CLASSIFICATION", None, "ALTERATION", B),

    # -- demolition --------------------------------------------------------
    "645":  S("DEMOLITION/RESIDENTIAL", None, "DEMOLITION", B),
    "649":  S("DEMOLITION/ALL OTHER BLDGS", None, "DEMOLITION", B),

    # -- not building permits. `kind` OTHER keeps them out of unit totals
    #    by construction, whatever else is ever read off them. -------------
    "329":  S("RESIDENTIAL SWIMMING POOL", None, "NEW"),
    "329A": S("ABOVE GROUND POOL", None, "NEW"),
    "329C": S("COMMERCIAL PUBLIC POOL", None, "NEW"),
    "329E": S("POOL ENCLOSURE", None, "ADDITION"),
    "329H": S("HARDSCAPE", None, "OTHER"),
    "329R": S("SWIMMING POOL REPAIR", None, "ALTERATION"),
    "329S": S("SPA", None, "NEW"),
    "500":  S("MISC", None, "OTHER"),
    "500C": S("COMMERCIAL MISC (DECKS, ENTRY FEATURE, HARDSCAPE)", None,
              "OTHER"),
    "500S": S("SPRINKLER SYSTEM", None, "OTHER"),
    "501":  S("COMMUNICATION TOWERS", None, "NEW"),
    "502":  S("SIGN", None, "OTHER"),
    "503":  S("RETAINING WALL/BULKHEAD", None, "OTHER"),
    "504":  S("Dock,Bulkhead, Boathouse, Bulkhead (Treasure Beach", None,
              "OTHER"),
    "505":  S("TEMPORARY COASTAL ARMORING", None, "OTHER"),
    "670":  S("SOLAR (PANELS, PHOTOVOLTAIC, WATER/POOL HEATER)", None,
              "OTHER"),
    "670C": S("COMMERCIAL SOLAR", None, "OTHER"),
    "800":  S("Storm Damage (Property Owner )", None, "ALTERATION"),
    "801":  S("Storm Damage (Field Inspection)", None, "ALTERATION"),
}


class StJohnsSource(object):
    def __init__(self, key="stjohns", state_fips="12", bps_id="803000",
                 label="St. Johns County FL (unincorporated)", note=None):
        self.key = key
        self.source_id = "%s|%s|%s" % (state_fips, bps_id, key)
        self.state_fips = state_fips
        self.bps_id = bps_id
        self.label = label
        self.platform = "wats-dotnet"
        self.note = note


# ------------------------------------------------------------------ parsing
def _text(s):
    return aspnet.text(s)


def headers(html):
    """The grid's header texts, lowercased. Used to assert column order."""
    i = html.find(GRID)
    if i < 0:
        return []
    seg = html[i:i + 4000]
    return [_text(t).lower()
            for t in re.findall(r"(?is)<th[^>]*>(.*?)</th>", seg)]


def parse_index(html):
    """(rows, truncated). Rows are dicts keyed by `COLUMNS`.

    Column order is asserted, not assumed. This grid is positional - its cells
    carry no role markers - so a reordered column would silently swap address
    into PropUse and classify every record off a street name. Cheap to check
    once per page, and the alternative has already cost this project a wrong
    answer on a different portal.
    """
    hs = headers(html)
    if hs and len(hs) >= len(EXPECT_HEADERS):
        for want, got in zip(EXPECT_HEADERS, hs, strict=False):
            if want not in got:
                raise ValueError(
                    "St. Johns grid column order changed: expected %r, got %r"
                    % (list(EXPECT_HEADERS), hs))
    rows = []
    for frag in ROWPAT.findall(html):
        cells = [_text(c) for c in CELL.findall(frag)]
        if len(cells) < len(COLUMNS):
            continue
        d = dict(zip(COLUMNS, cells, strict=False))
        m = PERMIT.search(frag)
        if m:
            d["number"] = _text(m.group(1))
        if d.get("number"):
            rows.append(d)
    return rows, bool(TRUNCATED.search(html))


# ------------------------------------------------------------------ record
def build(src, row, vb, content_hash):
    rec = emit.PermitRecord(
        source_id=src.source_id, state_fips=src.state_fips,
        bps_id=src.bps_id, native_id=row.get("number"),
        platform=src.platform, extractor_version=ADAPTER_VERSION,
        content_hash=content_hash, native=None)

    rec.address = emit.norm_text(row.get("address"))
    code = (row.get("propuse") or "").strip().upper()
    spec, rule = vb.by_code(code)

    if spec is None:
        # An unrecognized code is not an excuse to classify from something
        # else. There is no description field here to fall back to, and
        # inventing one would be the free-text mistake again.
        rec.units(None, "absent")
        rec.structure_type = None
    else:
        rec.permit_kind = spec.kind
        rec.work_class = spec.work
        rec.structure_type = spec.structure
        if spec.units is not None and not spec.exclude:
            rec.units(spec.units, "implied_by_structure_code")
        else:
            rec.units(None, "absent")

    rec.native = {"native_code": code,
                  "code_label": spec.label if spec else None,
                  "code_rule": rule,
                  "bps_excluded": spec.exclude if spec else None,
                  "contractor": emit.norm_text(row.get("contractor"))}

    # The column is labelled "Issue Dt" and carries a timestamp; a window of
    # 03/02/2026 returns only rows dated 03/02/2026. This is the explicit
    # issue date the Accela index grid does not have.
    rec.milestone("issued", row.get("issued"),
                  native_string=row.get("issued"))
    return rec


# ------------------------------------------------------------------- pull
def search_body(hidden, lo, hi):
    b = aspnet.body(hidden, criteria={FROM: lo, TO: hi})
    b[SUBMIT[0]] = SUBMIT[1]
    return b


def _fmt(d):
    return d.strftime("%m/%d/%Y")


def pull_window(src, lo, hi, fetch, emitter, vb, tag="", depth=0,
                max_depth=6, stats=None):
    """Pull [lo, hi] complete, bisecting on truncation. MM/DD/YYYY, inclusive.

    One request returns the whole window when it fits under the portal's cap.
    When it does not the portal says so, and the window is split rather than
    accepted short. Bisection instead of a fixed daily partition because the
    right granularity is a property of the jurisdiction's volume, which is not
    known in advance and changes across the year: a week of St. Johns is 245
    to 277 records, comfortably inside the cap, and paying 7x the requests to
    guarantee that would be a fixed cost against a rare event.
    """
    import datetime
    if stats is None:
        stats = {"requests": 0, "rows": 0, "emitted": 0, "rejected": 0,
                 "splits": 0, "windows": [], "seen": set()}

    html, _ = fetch(URL, "sj_%s_form%s" % (src.key, tag), "T-SEARCH")
    if html is None:
        stats.setdefault("errors", []).append("no form for %s..%s" % (lo, hi))
        return stats
    hidden = aspnet.hidden_fields(html)
    stats["requests"] += 1

    name = "sj_%s_%s_%s" % (src.key, lo.replace("/", ""), hi.replace("/", ""))
    html, prov = fetch(URL, name, "T-INDEX",
                       data=aspnet.encode(search_body(hidden, lo, hi)),
                       headers=aspnet.headers_for(URL))
    stats["requests"] += 1
    if html is None:
        stats.setdefault("errors", []).append("no result for %s..%s" % (lo, hi))
        return stats

    rows, truncated = parse_index(html)
    if truncated:
        d0 = datetime.datetime.strptime(lo, "%m/%d/%Y").date()
        d1 = datetime.datetime.strptime(hi, "%m/%d/%Y").date()
        if d0 >= d1 or depth >= max_depth:
            # A single day over the cap cannot be split further by date, and
            # the adapter has no second axis to narrow on. Refusing is the
            # only honest option: the alternative is a known-incomplete day
            # that looks exactly like a complete one downstream.
            raise ValueError(
                "St. Johns truncated an unsplittable window %s..%s (depth %d)"
                " - this window cannot be pulled completely" % (lo, hi, depth))
        mid = d0 + (d1 - d0) // 2
        stats["splits"] += 1
        pull_window(src, lo, _fmt(mid), fetch, emitter, vb, tag, depth + 1,
                    max_depth, stats)
        pull_window(src, _fmt(mid + datetime.timedelta(days=1)), hi, fetch,
                    emitter, vb, tag, depth + 1, max_depth, stats)
        return stats

    for r in rows:
        num = r.get("number")
        if num in stats["seen"]:
            continue
        stats["seen"].add(num)
        stats["rows"] += 1
        try:
            rec = build(src, r, vb, (prov or {}).get("sha256"))
            emitter.emit(rec)
            stats["emitted"] += 1
        except emit.MissingIdentifier:
            stats["rejected"] += 1
    stats["windows"].append({"lo": lo, "hi": hi, "rows": len(rows)})
    return stats


def vocabulary_for(src):
    return vocab.Vocabulary(src.source_id, src.platform, default_kind=None,
                            code_table=PROPUSE)


def page_is_complete(html):
    """False when the portal says it truncated this result set.

    A replay needs this as much as a crawl does. The truncated control page
    from the reclassification probe is a perfectly valid capture - its
    manifest row says `ok`, because the fetch succeeded and a result grid was
    rendered - but its *content* declares itself an arbitrary 500 rows. Only
    the adapter can read that declaration, so re-deriving records from stored
    bytes has to ask it rather than trusting the verdict alone.
    """
    return not TRUNCATED.search(html)
