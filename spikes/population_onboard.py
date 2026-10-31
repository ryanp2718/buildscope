# -*- coding: utf-8 -*-
"""Portal population, onboarding: the usability check, crawled.

For each portal the queue (`population_probe.py --sample`) marks "check" and
the crawler can fetch, run the pre-registered search rule, save the first 4
result pages to data/population/corpus/ (the same corpus and manifest as the
pages saved by hand), and record the result in data/population/usability.csv.

The search rule: building permits (the Building or Permits module where the
portal asks for one), dates 2026-08-01 to 2026-08-31 on the date the form
offers, sort order and page size left at their defaults. A portal is usable
when the search returns a list of records over at least 2 pages; pages 2
onward are what catch an extractor that hard-codes page 1.

Which date the form filters on is read off the results, not assumed: the
column whose every value falls in August is the one the search used, and its
header is recorded as the date field.

`accela-export` fetches the reference for each usable Accela portal: the
portal's own "Download results" CSV of the whole search, fetched the way the
page's script fetches it. It is saved to data/population/corpus/exports/ with
a row in exports.csv, and checked against the 4 pages already saved: their
records should be the export's first rows, in the same order (pre-registered
as the alignment check before an export is relied on).

`amanda-export` does the same for each usable AMANDA portal: the same search
in the browser, then the result list's Export, a CSV the page builds from the
search's own data.

`reference` builds the answer key for each tested portal with an export, in
data/population/reference/: each saved page's records taken from the export
by permit number, mapped to the contract's fields by the export's headers, and
the automatic checks on them.

Everything goes through `permits.capture`: robots.txt honoured, the crawler's
identity sent, the host's pause kept, one manifest row per response.

Usage:
    python spikes/population_onboard.py accela           # every Accela check
    python spikes/population_onboard.py accela 2 6       # these orders again
    python spikes/population_onboard.py accela-export [ORDER ...]
    python spikes/population_onboard.py smartgov         # in the browser
    python spikes/population_onboard.py logis
    python spikes/population_onboard.py clariti          # in the browser
    python spikes/population_onboard.py amanda           # in the browser
    python spikes/population_onboard.py amanda-export [ORDER ...]
    python spikes/population_onboard.py reference        # from the exports, no request
    python spikes/population_onboard.py posse            # in the browser
"""
import csv
import datetime
import hashlib
import io
import json
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from permits import aspnet                     # noqa: E402
from permits import capture                    # noqa: E402
from permits.adapters import accela as acc     # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "data", "population")
SAMPLE = os.path.join(DIR, "sample.csv")
PROBE = os.path.join(DIR, "probe.json")
PORTALS = os.path.join(DIR, "portals.csv")
USABILITY = os.path.join(DIR, "usability.csv")
FIELDS = ["order", "place", "product", "usable", "search", "pages", "rows",
          "stated_total", "date_field", "in_window", "reason", "needs",
          "reference", "checked_on", "by"]

LO, HI = "08/01/2026", "08/31/2026"
PAGES = 4
PER_PORTAL = 10          # requests: robots, search page(s), 4 result pages
BROWSER_LOAD = 60        # one page load in a browser: about 40 (Fresno, 2026-10-06)
# A search built in the browser: the form, the search and 3 more pages, each
# a full page load; about 65 requests each on SmartGov (Banning, 2026-10-20).
BROWSER_PORTAL = 500

# SmartGov's Advanced Search takes a date range as its field's own text,
# "Start To End". Typing into the field opens a picker that covers the Search
# button, so the text is set in the page instead, as the picker would set it.
SG_SEARCH = "/ApplicationPublic/ApplicationSearchAdvanced"
SG_SET_ISSUED = """range => {
    const shown = document.getElementById('IssuedOn.Display');
    const field = document.getElementById('IssuedOn');
    shown.value = range;
    shown.dispatchEvent(new Event('input', {bubbles: true}));
    shown.dispatchEvent(new Event('change', {bubbles: true}));
    if (!field.value) { field.value = range; }
    return field.value;
}"""
SG_NUMBER = re.compile(r'(?s)class="search-result-title">\s*<a[^>]*>\s*([^<]+?)\s*</a>')
SG_TOTAL = re.compile(r"(?i)\b([\d,]+)\s+results?\b")

# LOGIS ePermits (Minnesota cities on one host) is a Telerik grid behind an
# ASP.NET form. ASP.NET renders a downlevel page for the crawler's User-Agent,
# without the script the page's controls need, so the Search button's own
# check stops before it posts. The postback the button sends is sent directly,
# with each date picker's fields as its script fills them.
LG_FIELD = "m$m$b$b$"
LG_PICKER = ('{"enabled":true,"emptyMessage":"","validationText":"%s-00-00-00",'
             '"valueAsString":"%s-00-00-00","minDateStr":"1980-01-01-00-00-00",'
             '"maxDateStr":"2099-12-31-00-00-00","lastSetTextBoxValue":"%s"}')
LG_PAGE = re.compile(r"__doPostBack\(&#39;(m\$m\$b\$b\$grd\$[^&]+)&#39;,&#39;&#39;\)"
                     r"\"><span>(\d+)</span>")
LG_ROW = re.compile(r'(?is)<tr class="rg(?:Alt)?Row"[^>]*>(.*?)</tr>')
LG_TH = re.compile(r'(?is)<th[^>]*class="rgHeader[^"]*"[^>]*>(.*?)</th>')
LG_TD = re.compile(r"(?is)<td[^>]*>(.*?)</td>")
LG_TOTAL = re.compile(r"(?i)rgInfoPart\">\s*\d+ to \d+ of ([\d,]+)")

# Clariti (Phoenix's SHAPE PHX, a Salesforce site) builds its Data / Reports
# search in the browser: category Permit, then the issued date range; each
# cell names its column in data-label.
CL_SEARCH = "/s/advanced-search"
CL_ROW = re.compile(r'(?is)<tr[^>]*class="slds-hint-parent"[^>]*>(.*?)</tr>')
CL_CELL = re.compile(r'(?is)<t[dh][^>]*data-label="([^"]+)"[^>]*>(.*?)</t[dh]>')
CL_PAGES = re.compile(r"Page \d+ of ([\d,]+)")

# AMANDA's citizen portal (Austin's AB+C, Volusia's Connect Live) builds its
# public search in the browser, set up per site. Austin's date range is on its
# second tab and will not search on dates alone ("Please enter at least one
# search field"), so it takes the one type allowed, Building Permit. Volusia's
# Open Folders search takes its Permits folder type; its field asks for
# YYYY-MM-DD, but only MM/DD/YYYY returned records (2026-10-20). Both filter on
# the application date (one record opened on each). Each site's server answers
# every route of the app but its root with 404 and the app, so each page's row
# keeps that status.
AM_SEARCH = "/citizenportal/app/public-search"
AM_SITES = {
    "abc.austintexas.gov": ("Property / Project Name / Types / Date Range",
                            "Building Permit", "%m-%d-%Y"),
    "connectlivepermits.org": ("", "Permits", "%m/%d/%Y"),
}
AM_SET_TYPE = """name => {
    const s = document.getElementById('folderType_ID');
    const o = Array.from(s.options).find(o => o.text.trim() == name);
    s.value = o.value;
    s.dispatchEvent(new Event('change', {bubbles: true}));
    return o.value;
}"""
AM_FIRST = """prev => {
    const c = document.querySelector('datatable-body-row datatable-body-cell');
    return c && c.innerText.trim() && c.innerText.trim() != prev;
}"""
AM_ROW = re.compile(r"(?is)<datatable-body-row\b.*?</datatable-body-row>")
AM_CELL = re.compile(r"(?is)<datatable-body-cell\b.*?</datatable-body-cell>")
AM_HEAD = re.compile(r"(?is)<datatable-header-cell\b.*?</datatable-header-cell>")
AM_TOTAL = re.compile(r"([\d,]+) Results?\b")
AM_EXPORT = "button[title^='Export']"     # Volusia's "Export", Austin's "Export Results"

# Philadelphia's eCLIPSE (Computronix POSSE) builds its Permit Search by Date
# in the browser. The month, and Aug 3-14 with no type, both answer "More
# results were found than can be displayed", as does the month with one type;
# Aug 3-14 with Residential Building Permit, the type chosen by its name,
# returns a list (2026-10-20). The list is an ag-grid whose cells name their
# column in col-id.
PX_SEARCH = "/phillylmsprod/pub/webui/#/search/3607494"
PX_TYPE = "Residential Building Permit"
PX_FROM, PX_TO = "Aug 3, 2026", "Aug 14, 2026"
PX_ROW = re.compile(r'<div role="row" row-index="\d+"')
PX_CELL = re.compile(r'(?is)<div role="gridcell" col-id="([^"]+)"[^>]*>(.*?)'
                     r'(?=<div role="gridcell"|$)')
PX_TOTAL = re.compile(r"\b\d+-\d+ of ([\d,]+)")
PX_FIRST = """prev => {
    const c = document.querySelector('[col-id=PermitNumber] a');
    return c && c.innerText.trim() && c.innerText.trim() != prev;
}"""

START = acc.PFX + "txtGSStartDate"
TYPE = acc.PFX + "ddlGSPermitType"
OPTION = re.compile(r'(?is)<option[^>]*value="([^"]+)"[^>]*>([^<]*)')
MODULE_LINK = re.compile(r"(?i)CapHome\.aspx\?module=([^&\"'#]+)&(?:amp;)?"
                         r"TabName=([^&\"'#]+)")
BASE_END = re.compile(r"(?i)/(default|welcome)\.aspx|/angularui/")
# Where a tenancy sends a visitor who must sign in: its own Login.aspx, or
# Accela's sign-in for the new Public Portal (Fresno and Santa Rosa, 2026).
LOGIN_PAGE = re.compile(r"(?i)/login\.aspx|//login\.accela\.com/")
DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})")

EXPORT_BTN = acc.GRID + "$gdvPermitListtop4btnExport"
EXPORTS = os.path.join(DIR, "corpus", "exports")
EXPORT_INDEX = os.path.join(DIR, "corpus", "exports.csv")
EXPORT_FIELDS = ["file", "order", "export", "rows", "id_column", "on_page",
                 "in_order", "sha256", "saved_at"]
ID_HEADER = re.compile(r"(?i)\b(case|record|permit|application)\s*(number|no\.?|#|id)\b")
EXPORT_TIMEOUT = 180     # seconds: a month's export took over 30 on Baltimore

# The reference (answer key) from an export: a field is scored on a portal
# only where its export has a column for it. Tempe's page shows its address in
# an unheaded last column that its export leaves empty, so Tempe's address is
# not scored. Accela headers name their field as the adapter reads a grid's
# headers (`acc.ROLES`). Only the export and the record numbers the alignment
# check used are read here: the adapter's own output is the pipeline's key in
# the bias check, frozen before it is compared with an export (pre-registration,
# "Without the owner's review"). AMANDA's headers differ by site and are named
# one by one; Volusia's Name and Austin's Project Name hold the address.
REFERENCE = os.path.join(DIR, "reference")
# A value the export has but the page does not show is corrected to the page's
# by hand, one row each with its reason: the page is what an extractor reads.
CORRECTIONS = os.path.join(DIR, "reference_corrections.csv")
ACC_FIELDS = {"date": "issued_date", "address": "address", "type": "permit_type",
              "status": "status"}
AM_FIELDS = {"Type": "permit_type", "Sub Type / Work Type": "permit_type",
             "Date": "issued_date", "Name": "address", "Project Name": "address",
             "Status": "status"}
# EnerGov's Export Current View (Carlsbad, saved by hand 2026-10-31): one
# export per page, its headers the page's labels. Issued Date is the date the
# search filters on.
EG_FIELDS = {"Type": "permit_type", "Issued Date": "issued_date",
             "Address": "address", "Status": "status"}
REF_ROLES = {
    "Accela": lambda h: ACC_FIELDS.get(next(
        (r for needle, r in acc.ROLES if needle in h.lower()), None)),
    "AMANDA": lambda h: AM_FIELDS.get(h.strip()),
    "Tyler EnerGov": lambda h: EG_FIELDS.get(h.strip()),
}
# Where a portal has no export its reference is a parser, column -> field:
# Boise's is the Accela adapter, the pipeline's own; Phoenix's and
# Philadelphia's read the cells their onboarding checks read, by the column
# each names (data-label, col-id). Phoenix's Permit Type, not its Permit Work
# Type, is the type; Philadelphia's rows carry three dates, and the issue date
# is the one its search filters on.
PARSED = {
    "Accela": {"number": "native_id", "date": "issued_date", "address": "address",
               "type": "permit_type", "status": "status"},
    "Clariti": {"Permit Number": "native_id", "Permit Type": "permit_type",
                "Address": "address", "Issued Start Date": "issued_date",
                "Status": "status", "Registered Contractor Name": "contractor"},
    "Computronix POSSE": {"PermitNumber": "native_id",
                          "ObjectDefDescription": "permit_type",
                          "Location": "address", "StatusDescription": "status",
                          "IssueDate": "issued_date"},
}
PX_RANGE = re.compile(r"\b(\d+)-(\d+) of [\d,]+")
# EnerGov's result list: one <div class="row ng-scope"> per record, its
# permit number in the label-CaseNumber cell.
EG_ROW = re.compile(r'<div[^>]*\bclass="row ng-scope"')
EG_NUMBER = re.compile(r'(?s)name="label-CaseNumber".*?<span[^>]*>([^<]+)</span>')


def accela_base(url):
    """The tenancy's root: the address up to Default.aspx, Welcome.aspx or the
    Angular landing page the probe was sent to."""
    m = BASE_END.search(url)
    return (url[:m.start()] if m else url).rstrip("/")


def module_for(html):
    """The search tab for building permits, from the tenancy's own tab links:
    Building, else Permits, else the first tab that names either, else
    Development (Fort Worth files building permits under Development
    Services)."""
    tabs = MODULE_LINK.findall(html or "")
    for want in (r"^building$", r"^permits?$", r"build", r"permit",
                 r"^development$"):
        for module, tab in tabs:
            if re.search(want, module, re.I):
                return module, tab
    return None


def permit_type(html):
    """For a form that will not search without a criterion: the one permit
    type likely to have the most housing records, chosen by its name before
    any row is read. "Residential" itself, else the first residential
    building type."""
    i = html.find(TYPE)
    options = OPTION.findall(html[i:html.find("</select>", i)]) if i >= 0 else []
    for want in (r"^residential$", r"residential.*build|build.*residential",
                 r"residential"):
        for value, label in options:
            if re.search(want, label.strip(), re.I):
                return value
    return None


def date_column(pages):
    """(header, in_window, dated) for the column whose values fall in the
    search window: the date the search filtered on."""
    best = ("", 0, 0)
    for header in {h for html in pages for h in acc.headers(html)[1] if h}:
        role_rows = []
        for html in pages:
            _, raw = acc.headers(html)
            if header not in raw:
                continue
            i = raw.index(header)
            for frag in acc.ROWPAT.findall(html):
                cells = acc.CELL.findall(frag)
                if i < len(cells):
                    role_rows.append(aspnet.text(cells[i]))
        dated = [DATE.match(v) for v in role_rows]
        dated = [m for m in dated if m]
        hits = sum(1 for m in dated if m.group(3) == "2026" and int(m.group(1)) == 8)
        if dated and (hits, len(dated)) > best[1:]:
            best = (header, hits, len(dated))
    return best


def column_dates(pages, header):
    """One column's dates in page order, as (year, month, day), None for a
    row without one."""
    out = []
    for html in pages:
        _, raw = acc.headers(html)
        if header not in raw:
            continue
        i = raw.index(header)
        for frag in acc.ROWPAT.findall(html):
            cells = acc.CELL.findall(frag)
            if i < len(cells):
                m = DATE.match(aspnet.text(cells[i]))
                out.append((int(m.group(3)), int(m.group(1)), int(m.group(2)))
                           if m else None)
    return out


def no_date_verdict(pages, header):
    """The rule for a portal with no date field (owner, 2026-10-07): usable
    if every row shows a date and the list is in date order, so a pipeline
    could page back to any month; a list with no dates is lookup only."""
    dates = column_dates(pages, header) if header else []
    if not dates or None in dates:
        return {"usable": "no", "outcome": "lookup_only", "reason": "no date "
                "field, and the list does not show a date on every row"}
    if dates not in (sorted(dates), sorted(dates, reverse=True)):
        return {"usable": "no", "reason": "no date field, and the list is "
                "not in date order"}
    span = ["%02d/%02d/%04d" % (m, d, y) for y, m, d in (dates[0], dates[-1])]
    return {"usable": "yes", "needs": "", "reason": "no date field: the list is "
            "dated and in date order (%s to %s), saved as a snapshot" % tuple(span)}


def check_accela(p, op, final_url):
    order = int(p["order"])
    base = accela_base(final_url or p["url"])
    name = "acc_%04d" % order

    def fetch(url, suffix, page_type, data=None):
        return capture.fetch(op, url, "%s_%s" % (name, suffix), p["place"],
                             "Accela", page_type, data=data,
                             headers=aspnet.headers_for(url) if data else None)

    home = acc.HOME % (base, "Building", "Building")
    html, row = fetch(home, "search", "T-SEARCH")
    if html is not None and START not in html and not LOGIN_PAGE.search(row["final_url"]):
        pick = module_for(html)
        if not pick:
            # No tab links on an error page ("Invalid Module param value":
            # Fort Worth has no Building module); the home page has them.
            front, _ = fetch(base + "/Default.aspx", "home", "T-SEARCH")
            pick = module_for(front)
        if pick and pick != ("Building", "Building"):
            home = acc.HOME % (base, *pick)
            html, row = fetch(home, "search2", "T-SEARCH")
    if html is None:
        return {"usable": "", "reason": "search page: %s" % row["verdict_reason"]}
    if "fa-login-panel" in row["final_url"]:
        # The new Public Portal builds its page in the browser: ask one.
        with capture.Browser(p["place"], "Accela") as b:
            b.go(home)
            _, row = b.save(name + "_browser", "T-SEARCH")
        if not LOGIN_PAGE.search(row["final_url"]):
            return {"usable": "", "needs": "playwright", "reason": "the new "
                    "Public Portal answered a browser without asking it to sign "
                    "in; its search is not scripted yet"}
    if LOGIN_PAGE.search(row["final_url"]):
        return {"usable": "no", "outcome": "login", "reason": "login: the "
                "search sends every anonymous visitor to sign in (%s)"
                % row["final_url"].split("?")[0]}
    hidden = aspnet.hidden_fields(html)
    no_date = START not in html
    if no_date:
        # No date field: one permit type, newest records first, saved as a
        # snapshot (Santa Barbara in v2), under the rule the owner approved
        # on 2026-10-07 (no_date_verdict).
        ptype = permit_type(html)
        if not ptype:
            return {"usable": "", "reason": "the search form has no date fields "
                    "and no permit type to choose"}
        body = aspnet.body(hidden, event_target=acc.SEARCH_BTN,
                           criteria={TYPE: ptype})
    else:
        body = acc.search_body(hidden, LO, HI)
    html, row = fetch(home, "p1", "T-INDEX", data=aspnet.encode(body))
    pages, seen, stated = [], set(), ""
    n = 1
    while html is not None:
        rows, total, capped = acc.parse_index(html)
        if n == 1:
            stated = "%s%s" % ("" if total is None else total, "+" if capped else "")
        fresh = [r for r in rows if r.get("number") not in seen]
        if not fresh:
            break
        seen.update(r["number"] for r in fresh)
        pages.append(html)
        if len(rows) < acc.ROWS_PER_PAGE or n >= PAGES:
            break
        n += 1
        html, row = fetch(home, "p%d" % n, "T-INDEX", data=aspnet.encode(
            acc.page_body(aspnet.hidden_fields(html), n)))
    header, hits, dated = date_column(pages)
    out = {"search": home.split("?", 1)[1], "pages": len(pages),
           "rows": len(seen), "stated_total": stated,
           "date_field": header, "in_window": "%d of %d" % (hits, dated)}
    if no_date:
        out["search"] += "; no date field: type %s, no window" % ptype
        out["in_window"] = "n/a"
    if len(pages) >= 2 and no_date:
        out.update(no_date_verdict(pages, header))
    elif len(pages) >= 2:
        out.update(usable="yes", reason="")
    elif pages:
        out.update(usable="no", reason="%d records: fewer than 2 pages" % len(seen))
    else:
        out.update(usable="", reason="no result list: %s" % (
            row["verdict_reason"] if html is None else "page 1 has no records"))
    return out


def check_smartgov(p, final_url):
    """SmartGov's Advanced Search, in the browser: Issued between the window's
    dates, everything else at its default, then the result pages as rendered.
    The list shows each record's status and that status's date, not the
    issued date, so the window cannot be read back off the rows."""
    name = "sgv_%04d" % int(p["order"])
    base = "/".join((final_url or p["url"]).split("/")[:3])
    pages, seen, stated = [], set(), ""
    with capture.Browser(p["place"], "SmartGov") as b:
        if b.go(base + SG_SEARCH):
            b.page.evaluate(SG_SET_ISSUED, "%s To %s" % (LO, HI))
            b.act(lambda page: page.click("#Search"))
        for n in range(1, PAGES + 1):
            if n > 1:
                link = b.page.locator(".search-results-paging a",
                                      has_text=re.compile(r"^\s*%d\s*$" % n))
                if not link.count():
                    break
                b.act(lambda page: link.first.click())
            html, row = b.save("%s_p%d" % (name, n), "T-INDEX")
            if html is None:
                break
            fresh = [x for x in SG_NUMBER.findall(html) if x not in seen]
            if not fresh:
                break
            if n == 1:
                m = SG_TOTAL.search(re.sub(r"<[^>]+>", " ", html))
                stated = m.group(1) if m else ""
            seen.update(fresh)
            pages.append(html)
    out = {"search": "%s, Issued %s To %s" % (SG_SEARCH, LO, HI),
           "pages": len(pages), "rows": len(seen), "stated_total": stated,
           "date_field": "Issued (the filter; the list shows status dates)",
           "in_window": "not shown"}
    if len(pages) >= 2:
        out.update(usable="yes", reason="")
    elif pages:
        out.update(usable="no", reason="%d records: fewer than 2 pages" % len(seen))
    else:
        out.update(usable="", reason="no result list: %s" % row["verdict_reason"])
    return out


def check_logis(p, op, final_url):
    """LOGIS's search on the issued date, everything else blank, then the
    grid's page links, each sent with the same criteria as the form keeps."""
    url = final_url or p["url"]
    name = "lgs_%04d" % int(p["order"])

    def fetch(suffix, page_type, data=None):
        return capture.fetch(op, url, "%s_%s" % (name, suffix), p["place"],
                             "LOGIS ePermits", page_type, data=data,
                             headers=aspnet.headers_for(url) if data else None)

    html, row = fetch("search", "T-SEARCH")
    if html is None:
        return {"usable": "", "reason": "search page: %s" % row["verdict_reason"]}
    crit = {k: "" for k, v in aspnet.form_fields(html, LG_FIELD).items()
            if v[1] not in ("submit", "button", "image", "checkbox", "radio")}
    for picker, when in (("dpIssuedDateFrom", LO), ("dpIssuedDateTo", HI)):
        m, d, y = when.split("/")
        iso, shown = "%s-%s-%s" % (y, m, d), "%d/%d/%s" % (int(m), int(d), y)
        crit[LG_FIELD + picker] = iso
        crit[LG_FIELD + picker + "$dateInput"] = shown
        crit["m_m_b_b_%s_dateInput_ClientState" % picker] = LG_PICKER % (iso, iso, shown)
    target = LG_FIELD + "btnSearch"
    pages, seen, stated, header, dates, repeats = [], set(), "", [], [], 0
    for n in range(1, PAGES + 1):
        body = aspnet.body(aspnet.hidden_fields(html), event_target=target, criteria=crit)
        html, row = fetch("p%d" % n, "T-INDEX", data=aspnet.encode(body))
        if html is None:
            break
        rows = [[aspnet.text(c) for c in LG_TD.findall(r)] for r in LG_ROW.findall(html)]
        fresh = [r for r in rows if r and r[0] not in seen]
        if not fresh:
            break
        # Rows tied on the sort date can come back in a different order on the
        # next page's query, so a page may repeat a record from the one before.
        repeats += len(rows) - len(fresh)
        if n == 1:
            m = LG_TOTAL.search(html)
            stated = m.group(1).replace(",", "") if m else ""
            header = [aspnet.text(h) for h in LG_TH.findall(html)]
        seen.update(r[0] for r in fresh)
        pages.append(html)
        if "Issued Date" in header:
            i = header.index("Issued Date")
            dates += [DATE.match(r[i]) for r in fresh if i < len(r)]
        links = {int(k): t for t, k in LG_PAGE.findall(html)}
        if n + 1 not in links:
            break
        target = links[n + 1]
    dated = [d for d in dates if d]
    hits = sum(1 for d in dated if d.group(3) == "2026" and int(d.group(1)) == 8)
    out = {"search": "%s, Issued Date %s to %s" % (url.split("/")[-1], LO, HI),
           "pages": len(pages), "rows": len(seen), "stated_total": stated,
           "date_field": "Issued Date", "in_window": "%d of %d" % (hits, len(dated))}
    if len(pages) >= 2:
        out.update(usable="yes", reason="" if not repeats else "%d record(s) "
                   "repeated on a later page (rows tied on the sort date)" % repeats)
    elif pages:
        out.update(usable="no", reason="%d records: fewer than 2 pages" % len(seen))
    else:
        out.update(usable="", reason="no result list: %s" % (
            row["verdict_reason"] if html is None else "page 1 has no records"))
    return out


def check_clariti(p, final_url):
    """Clariti's Data / Reports search in the browser: category Permit, the
    window on Issued Start and End Date, everything else blank; then Next Page."""
    name = "clr_%04d" % int(p["order"])
    base = "/".join((final_url or p["url"]).split("/")[:3])
    lo, hi = [datetime.datetime.strptime(d, "%m/%d/%Y") for d in (LO, HI)]
    shown = ["%s %d, %d" % (d.strftime("%b"), d.day, d.year) for d in (lo, hi)]
    pages, seen, stated, dates = [], set(), "", []
    with capture.Browser(p["place"], "Clariti") as b:
        if b.go(base + CL_SEARCH):
            b.act(lambda page: page.click('button:has-text("Select a Search Category")'))
            b.act(lambda page: page.get_by_role("option", name="Permit", exact=True).click())
            b.act(lambda page: page.get_by_label("Issued Start Date", exact=True).fill(shown[0]))
            b.act(lambda page: page.get_by_label("Issued End Date", exact=True).fill(shown[1]))
            b.act(lambda page: page.locator('button:has-text("Search")').last.click())
        for n in range(1, PAGES + 1):
            if n > 1:
                def turn(page, n=n):
                    page.locator('button:has-text("Next Page")').first.click()
                    page.get_by_text("Page %d of" % n).wait_for()
                if not b.act(turn):
                    break
            html, row = b.save("%s_p%d" % (name, n), "T-INDEX")
            if html is None:
                break
            rows = [{k: aspnet.text(v) for k, v in CL_CELL.findall(r)}
                    for r in CL_ROW.findall(html)]
            fresh = [r for r in rows if r.get("Permit Number") not in seen]
            if not fresh:
                break
            if n == 1:
                m = CL_PAGES.search(aspnet.text(html))
                stated = "%s pages" % m.group(1) if m else ""
            seen.update(r.get("Permit Number") for r in fresh)
            dates += [r.get("Issued Start Date", "") for r in fresh]
            pages.append(html)
    dated = [d for d in dates if re.match(r"\d{4}-\d{2}-\d{2}$", d)]
    hits = sum(1 for d in dated if d.startswith("2026-08-"))
    out = {"search": "%s, category Permit, Issued Start Date %s to %s"
           % (CL_SEARCH, shown[0], shown[1]),
           "pages": len(pages), "rows": len(seen), "stated_total": stated,
           "date_field": "Issued Start Date", "in_window": "%d of %d" % (hits, len(dated))}
    if len(pages) >= 2:
        out.update(usable="yes", reason="")
    elif pages:
        out.update(usable="no", reason="%d records: fewer than 2 pages" % len(seen))
    else:
        out.update(usable="", reason="no result list: %s" % row["verdict_reason"])
    return out


def amanda_search(b, base):
    """Run AMANDA's public search in browser b, set up as AM_SITES says for
    the site; returns the search as usability.csv records it."""
    tab, kind, fmt = AM_SITES[base.split("/")[2]]
    lo, hi = [datetime.datetime.strptime(d, "%m/%d/%Y").strftime(fmt) for d in (LO, HI)]
    if b.go(base + AM_SEARCH):
        if tab:
            b.act(lambda page: page.click("text=" + tab))
        b.act(lambda page: page.locator("#folderType_ID").wait_for())
        b.act(lambda page: page.evaluate(AM_SET_TYPE, kind))
        b.act(lambda page: page.type("#inDateFrom_ID", lo, delay=30))
        b.act(lambda page: page.type("#inDateTo_ID", hi, delay=30))
        b.act(lambda page: page.locator("button:has-text('Search')").last.click())
        b.act(lambda page: page.locator("datatable-body-row").first.wait_for())
    return "%s%s, %s, dates %s to %s" % (AM_SEARCH, ", tab " + tab if tab else "",
                                         kind, lo, hi)


def check_amanda(p, final_url):
    """AMANDA's public search in the browser, then the pager's page numbers.
    Austin's list shows no dates."""
    name = "amd_%04d" % int(p["order"])
    base = "/".join((final_url or p["url"]).split("/")[:3])
    pages, seen, stated, header, dates = [], set(), "", [], []
    with capture.Browser(p["place"], "AMANDA") as b:
        search = amanda_search(b, base)
        first = ""
        for n in range(1, PAGES + 1):
            if n > 1:
                def turn(page, n=n, first=first):
                    page.locator("datatable-pager li.pages a",
                                 has_text=re.compile(r"^\s*%d\s*$" % n)).first.click()
                    page.wait_for_function(AM_FIRST, arg=first)
                if not b.act(turn):
                    break
            html, row = b.save("%s_p%d" % (name, n), "T-INDEX")
            if html is None:
                break
            rows = [[aspnet.text(c) for c in AM_CELL.findall(r)] for r in AM_ROW.findall(html)]
            fresh = [r for r in rows if r and r[0] not in seen]
            if not fresh:
                break
            if n == 1:
                m = AM_TOTAL.search(aspnet.text(html))
                stated = m.group(1).replace(",", "") if m else ""
                header = [aspnet.text(h) for h in AM_HEAD.findall(html)]
            first = fresh[0][0]
            seen.update(r[0] for r in fresh)
            pages.append(html)
            if "Date" in header:
                i = header.index("Date")
                dates += [r[i] for r in fresh if i < len(r)]
    dated = [d for d in dates if re.match(r"\d{4}-\d{2}-\d{2}$", d)]
    hits = sum(1 for d in dated if d.startswith("2026-08-"))
    out = {"search": search, "pages": len(pages), "rows": len(seen), "stated_total": stated,
           "date_field": "Application Date (the filter%s)" % (
               "" if dates else "; the list shows no dates"),
           "in_window": "%d of %d" % (hits, len(dated)) if dates else "not shown"}
    if len(pages) >= 2:
        out.update(usable="yes", reason="")
    elif pages:
        out.update(usable="no", reason="%d records: fewer than 2 pages" % len(seen))
    else:
        out.update(usable="", reason="no result list: %s" % row["verdict_reason"])
    return out


def check_posse(p, final_url):
    """eCLIPSE's Permit Search by Date in the browser: Issued Date over the
    shorter window and one type, as PX_ says; then Next page."""
    name = "psx_%04d" % int(p["order"])
    base = "/".join((final_url or p["url"]).split("/")[:3])
    pages, seen, stated, dates = [], set(), "", []
    with capture.Browser(p["place"], "Computronix POSSE") as b:
        if b.go(base + PX_SEARCH):
            b.act(lambda page: page.get_by_label("Issued Date From", exact=True).wait_for())
            b.act(lambda page: page.get_by_label("Issued Date From", exact=True).fill(PX_FROM))
            b.act(lambda page: page.get_by_label("Issued Date To", exact=True).fill(PX_TO))
            b.act(lambda page: page.press("body", "Tab"))
            b.act(lambda page: page.locator(
                "[role=combobox][aria-labelledby$='-label']").last.click())
            b.act(lambda page: page.locator(
                "[role=option]", has_text=PX_TYPE).first.click())
            b.act(lambda page: page.locator("button:has-text('SEARCH') >> visible=true").click())
            b.act(lambda page: page.locator("[col-id=PermitNumber] a").first.wait_for())
        first = ""
        for n in range(1, PAGES + 1):
            if n > 1:
                def turn(page, first=first):
                    page.locator("button[aria-label='Next page']").click()
                    page.wait_for_function(PX_FIRST, arg=first)
                if not b.act(turn):
                    break
            html, row = b.save("%s_p%d" % (name, n), "T-INDEX")
            if html is None:
                break
            chunks = PX_ROW.split(html)[1:]
            rows = [{k: aspnet.text(v) for k, v in PX_CELL.findall(c)} for c in chunks]
            fresh = [r for r in rows if r.get("PermitNumber") and r["PermitNumber"] not in seen]
            if not fresh:
                break
            if n == 1:
                m = PX_TOTAL.search(aspnet.text(html))
                stated = m.group(1).replace(",", "") if m else ""
            first = fresh[0]["PermitNumber"]
            seen.update(r["PermitNumber"] for r in fresh)
            dates += [r.get("IssueDate", "") for r in fresh]
            pages.append(html)
    lo, hi = [datetime.datetime.strptime(d, "%b %d, %Y") for d in (PX_FROM, PX_TO)]
    dated = []
    for d in dates:
        try:
            dated.append(datetime.datetime.strptime(d, "%b %d, %Y"))
        except ValueError:
            pass
    hits = sum(1 for d in dated if lo <= d <= hi)
    out = {"search": "%s, Issued Date %s to %s, Permit Type %s" % (
               PX_SEARCH, PX_FROM, PX_TO, PX_TYPE),
           "pages": len(pages), "rows": len(seen), "stated_total": stated,
           "date_field": "Issue Date", "in_window": "%d of %d" % (hits, len(dated))}
    if len(pages) >= 2:
        out.update(usable="yes", reason="")
    elif pages:
        out.update(usable="no", reason="%d records: fewer than 2 pages" % len(seen))
    else:
        out.update(usable="", reason="no result list: %s" % row["verdict_reason"])
    return out


def accela_export(p, op, u):
    """Download results for one usable portal, in a new session: the search
    as it was run, page 1, the export button's postback, then Export2CSV.ashx,
    which is what the page's ExportCSV script loads into a hidden frame."""
    order = int(p["order"])
    base = accela_base(p["home"])
    home = "%s/Cap/CapHome.aspx?%s" % (base, u["search"].split(";")[0])
    name = "acc_%04d_x" % order

    def fetch(url, suffix, page_type, data=None, headers=None):
        return capture.fetch(op, url, name + suffix, p["place"], "Accela",
                             page_type, data=data, headers=headers or (
                                 aspnet.headers_for(url) if data else None))

    html, row = fetch(home, "search", "T-SEARCH")
    if html is None:
        return {"reference": "export: search page %s" % row["verdict_reason"]}
    hidden = aspnet.hidden_fields(html)
    ptype = re.search(r"type (.+?), no window", u["search"])
    if ptype:
        body = aspnet.body(hidden, event_target=acc.SEARCH_BTN,
                           criteria={TYPE: ptype.group(1)})
    else:
        body = acc.search_body(hidden, LO, HI)
    html, row = fetch(home, "p1", "T-INDEX", data=aspnet.encode(body))
    if html is None or EXPORT_BTN not in html:
        return {"reference": "export: no Download results on page 1"}
    timeout, capture.TIMEOUT = capture.TIMEOUT, EXPORT_TIMEOUT
    try:
        _, row = fetch(home, "post", "T-INDEX", data=aspnet.encode(
            aspnet.body(aspnet.hidden_fields(html), event_target=EXPORT_BTN)))
        text, row = fetch(base + "/Export2CSV.ashx?flag=1", "csv", "EXPORT",
                          headers={"Accept": "*/*", "Referer": home})
    finally:
        capture.TIMEOUT = timeout
    if text is None or row["content_type"] != "text/csv":
        return {"reference": "export: %s %s" % (row["http_status"],
                                                row["content_type"])}
    page_ids = []
    for n in range(1, PAGES + 1):
        path = os.path.join(capture.PAGES, "acc_%04d_p%d.html" % (order, n))
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                page_ids += [r["number"] for r in acc.parse_index(fh.read())[0]]
    return {"reference": "export: " + keep_export(order, text, text.encode("utf-8"),
                                                  page_ids, row["fetched_at"])}


def amanda_export(p, final_url):
    """The reference for a usable AMANDA portal: the result list's Export, a
    CSV the page builds from the search's own data, after the same search in
    a new session. The requests the Export click sends are counted, and any
    to reCAPTCHA named."""
    order = int(p["order"])
    base = "/".join((final_url or p["url"]).split("/")[:3])
    got, sent = {}, []
    with capture.Browser(p["place"], "AMANDA") as b:
        amanda_search(b, base)
        b.page.on("request", lambda r: sent.append(r.url))

        def export(page):
            with page.expect_download(timeout=EXPORT_TIMEOUT * 1000) as d:
                page.locator(AM_EXPORT).first.click()
            got["raw"] = open(d.value.path(), "rb").read()
        b.act(export)
        _, row = b.save("amd_%04d_x" % order, "T-INDEX")
    if "raw" not in got:
        return {"reference": "export: no download: %s" % row["verdict_reason"]}
    page_ids = []
    for n in range(1, PAGES + 1):
        path = os.path.join(capture.PAGES, "amd_%04d_p%d.html" % (order, n))
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                for r in AM_ROW.findall(fh.read()):
                    cells = AM_CELL.findall(r)
                    if cells:
                        page_ids.append(aspnet.text(cells[0]))
    captcha = [u for u in sent if "recaptcha" in u.lower()]
    hosts = sorted({urllib.parse.urlsplit(u).hostname or u[:20] for u in sent})
    how = keep_export(order, got["raw"].decode("utf-8-sig"), got["raw"], page_ids,
                      row["fetched_at"])
    return {"reference": "export, built in the page (the click sent %d request%s%s%s): %s"
            % (len(sent), "" if len(sent) == 1 else "s",
               " to " + ", ".join(hosts) if hosts else "",
               ", %d to reCAPTCHA" % len(captcha) if captcha else "", how)}


def keep_export(order, text, raw, page_ids, saved_at):
    """Save an export as the portal's reference, with its row in exports.csv,
    and say where the saved pages' records are in it: its first rows, in the
    same order, is the alignment check pre-registered before an export is
    relied on."""
    rows = [r for r in csv.reader(io.StringIO(text)) if any(r)]
    header, body = rows[0], rows[1:]
    col = next((i for i, h in enumerate(header) if ID_HEADER.search(h)), 0)
    ids = [r[col] for r in body if col < len(r)]
    aligned = ids[:len(page_ids)] == page_ids
    on_page = len(set(page_ids) & set(ids))
    # A snapshot with no date window (Manatee) gains records between the
    # pages and the export; its pages should then still be in the export in
    # the same order, with the new records between them.
    first = {}
    for i, x in enumerate(ids):
        first.setdefault(x, i)
    at = [first[x] for x in page_ids if x in first]
    gaps = (not aligned and on_page == len(page_ids) and at == sorted(at)
            and at[-1] - len(page_ids) + 1)
    # An export can list the search in another order than its pages (Austin's
    # AMANDA); the pages are then its first rows once it is sorted by the id
    # column as they are.
    order_by = ""
    if not aligned and not gaps and on_page == len(page_ids):
        for desc in (True, False):
            if sorted(ids, reverse=desc)[:len(page_ids)] == page_ids:
                order_by = "descending" if desc else "ascending"
    fn = "crl_%04d_all.csv" % order
    os.makedirs(EXPORTS, exist_ok=True)
    new = not os.path.exists(EXPORT_INDEX)
    with io.open(EXPORT_INDEX, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=EXPORT_FIELDS)
        if new:
            w.writeheader()
        w.writerow({"file": fn, "order": order, "export": "all",
                    "rows": len(body), "id_column": header[col],
                    "on_page": on_page,
                    "in_order": ("yes" if aligned or gaps else
                                 "sorted " + order_by if order_by else "no"),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "saved_at": saved_at})
    with open(os.path.join(EXPORTS, fn), "wb") as fh:
        fh.write(raw)
    if aligned:
        how = "are its first rows, in order"
    elif gaps:
        how = ("are in it in the same order, with %d other rows among them "
               "(records added since the pages were saved)" % gaps)
    elif order_by:
        how = ("are its first rows, in order, once it is sorted by %s %s, as the "
               "pages are" % (header[col], order_by))
    else:
        how = "are NOT its first rows: %d of them are in it" % on_page
    return "%d rows (%d unique %s); the %d saved page rows %s" % (
        len(body), len(set(ids)), header[col], len(page_ids), how)


def page_records(product, html, parse=False):
    """(permit number, record text, fields) for each record on a saved result
    page, and the page's own count of its records. With parse, fields are the
    contract's, read by the portal's parser (PARSED); otherwise None."""
    def cells(found, names):
        values = {names[k]: aspnet.text(v) or None for k, v in found if k in names}
        return values if parse else None

    if product == "Accela":
        parsed = {r["number"]: r for r in acc.parse_index(html)[0]} if parse else {}
        out = []
        for frag in acc.ROWPAT.findall(html):
            m = acc.NUMSPAN.search(frag)
            if m:
                rid = aspnet.text(m.group(1))
                row = parsed.get(rid, {})
                fields = ({f: row[k] or None for k, f in PARSED["Accela"].items()
                           if k in row} if parse else None)
                out.append((rid, aspnet.text(frag), fields))
        m = acc.SHOWING.search(html)
        return out, (int(m.group(2)) - int(m.group(1)) + 1) if m else None
    if product == "Clariti":
        rows = CL_ROW.findall(html)
        out = [(aspnet.text(dict(CL_CELL.findall(r)).get("Permit Number", "")),
                aspnet.text(r), cells(CL_CELL.findall(r), PARSED[product]))
               for r in rows]
        blocks = capture.record_blocks(html)
        return out, blocks[2] if blocks else None
    if product == "Computronix POSSE":
        rows = PX_ROW.split(html)[1:]
        out = [(aspnet.text(dict(PX_CELL.findall(r)).get("PermitNumber", "")),
                aspnet.text(r), cells(PX_CELL.findall(r), PARSED[product]))
               for r in rows]
        m = PX_RANGE.search(aspnet.text(html))
        return out, (int(m.group(2)) - int(m.group(1)) + 1) if m else None
    if product == "Tyler EnerGov":
        rows = [r for r in EG_ROW.split(html)[1:] if EG_NUMBER.search(r)]
        out = [(aspnet.text(EG_NUMBER.search(r).group(1)), aspnet.text(r), None)
               for r in rows]
        blocks = capture.record_blocks(html)
        return out, blocks[2] if blocks else None
    # AMANDA states only the search's total; each record has one Detail button.
    rows = [r for r in AM_ROW.findall(html) if AM_CELL.search(r)]
    out = [(aspnet.text(AM_CELL.findall(r)[0]), aspnet.text(r), None) for r in rows]
    return out, sum(1 for r in rows if re.search(r">\s*Detail\s*<", r))


def reference(product, u, ex):
    """One portal's reference: each saved page's records, taken from its
    export by permit number under the fields REF_ROLES finds in the export's
    headers, or read by its parser where it has no export (ex None). Checked
    automatically: the page's own count of records, each value verbatim in
    its record's text on the page, permit numbers unique."""
    order = int(u["order"])
    by_id, cols = {}, {}
    if ex:
        # One export of the whole search, or one per page (EnerGov), read as
        # one: a record on two pages has the same values in both.
        header, body = None, []
        for f in ex["files"]:
            with open(os.path.join(EXPORTS, f), "rb") as fh:
                text = fh.read().decode("utf-8-sig")
            rows = [r for r in csv.reader(io.StringIO(text)) if any(r)]
            if header not in (None, rows[0]):
                raise SystemExit("%s: headers differ from %s" % (f, ex["files"][0]))
            header = rows[0]
            body += rows[1:]
        fields = {"native_id": ex["id_column"]}
        for h in header:
            role = REF_ROLES[product](h)
            if role and role not in fields:
                fields[role] = h
        cols = {role: header.index(h) for role, h in fields.items()}
        for r in body:
            by_id.setdefault(r[cols["native_id"]].strip(), r)
    fixes = {}
    if os.path.exists(CORRECTIONS):
        with open(CORRECTIONS, newline="", encoding="utf-8") as fh:
            fixes = {(c["file"], c["native_id"], c["field"]): c
                     for c in csv.DictReader(fh) if c["order"] == u["order"]}
    pages, seen, dup = [], set(), 0
    prefix = {"Accela": "acc", "AMANDA": "amd", "Clariti": "clr",
              "Computronix POSSE": "psx", "Tyler EnerGov": "man"}[product]
    for n in range(1, PAGES + 1):
        name = "%s_%04d_p%d.html" % (prefix, order, n)
        path = os.path.join(capture.PAGES, name)
        if not os.path.exists(path):
            break
        with open(path, encoding="utf-8") as fh:
            records, count = page_records(product, fh.read(), parse=not ex)
        page = {"file": name, "count": count, "rows": [], "not_in_export": [],
                "not_verbatim": [], "corrected": []}
        for rid, rtext, parsed in records:
            dup += rid in seen
            seen.add(rid)
            if parsed is not None:
                rec = dict(parsed)
            elif rid in by_id:
                r = by_id[rid]
                rec = {role: (" ".join(r[i].split()) or None) if i < len(r) else None
                       for role, i in cols.items()}
            else:
                page["not_in_export"].append(rid)
                continue
            for role in rec:
                fix = fixes.get((name, rid, role))
                # Applied only while the source still says what was corrected.
                if fix and (rec[role] or "") == fix["export"]:
                    rec[role] = fix["reference"] or None
                    page["corrected"].append([rid, role, fix["export"], rec[role]])
            page["rows"].append(rec)
            page["not_verbatim"] += [[rid, role, v] for role, v in rec.items()
                                     if v and v not in rtext]
        pages.append(page)
    if not ex:
        # A field is scored only where the page has a column for it, as on an
        # export: Boise's grid has no record type.
        fields = {f: k for k, f in PARSED[product].items()
                  if any(f in r for p in pages for r in p["rows"])}
    out = {"order": u["order"], "place": u["place"], "product": product,
           "source": "export %s" % " ".join(ex["files"]) if ex else "parser",
           "export_sha256": " ".join(ex["sha256s"]) if ex else None,
           "access": "by hand" if prefix == "man" else "crawler", "fields": fields,
           "duplicate_ids": dup, "pages": pages}
    os.makedirs(REFERENCE, exist_ok=True)
    with open(os.path.join(REFERENCE, "ref_%04d.json" % order), "w",
              encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    return out


def references():
    """The reference for every tested portal, and its checks."""
    # A portal's export of the whole search, or else its exports of each
    # saved page (EnerGov's Export Current View).
    with open(EXPORT_INDEX, newline="", encoding="utf-8") as fh:
        index = list(csv.DictReader(fh))
    exs = {}
    for o in {r["order"] for r in index}:
        rs = ([r for r in index if r["order"] == o and r["export"] == "all"]
              or sorted((r for r in index if r["order"] == o
                         and re.match(r"p\d$", r["export"])),
                        key=lambda r: r["export"]))
        exs[o] = {"files": [r["file"] for r in rs],
                  "sha256s": [r["sha256"] for r in rs],
                  "id_column": rs[0]["id_column"]}
    with open(SAMPLE, newline="", encoding="utf-8") as fh:
        tested = [r for r in csv.DictReader(fh) if r["role"] == "tested"]
    capture.retarget(os.path.join("population", "corpus"))
    print("%-5s %-28s %-7s %5s %5s %-8s %-13s %5s %-6s %s" % (
        "order", "place", "source", "pages", "rows", "counts", "verbatim", "fixed",
        "unique", "fields"))
    for u in tested:
        ex = exs.get(u["order"]) if u["product"] in REF_ROLES else None
        if not ex and u["product"] not in PARSED:
            print("%-5s %-28s no export and no parser" % (u["order"], u["place"][:28]))
            continue
        ref = reference(u["product"], u, ex)
        pages = ref["pages"]
        rows = sum(len(p["rows"]) for p in pages)
        counts = sum(len(p["rows"]) == p["count"] and not p["not_in_export"]
                     for p in pages)
        cells = sum(1 for p in pages for r in p["rows"] for v in r.values() if v)
        bad = sum(len(p["not_verbatim"]) for p in pages)
        fixed = sum(len(p["corrected"]) for p in pages)
        print("%-5s %-28s %-7s %5d %5d %d of %-3d %5d of %-5d %5d %-6s %s" % (
            u["order"], u["place"][:28], "export" if ex else "parser", len(pages),
            rows, counts, len(pages), cells - bad, cells, fixed,
            "yes" if not ref["duplicate_ids"] else "no",
            ", ".join(f for f in ref["fields"] if f != "native_id")))


def set_outcome(order, outcome, reason):
    """An outcome found at onboarding that holds whoever fetches the portal
    (login only) replaces the probe's in portals.csv, as one the owner finds
    in a browser does."""
    with open(PORTALS, newline="", encoding="utf-8") as fh:
        r = csv.DictReader(fh)
        fields, rows = r.fieldnames, list(r)
    for row in rows:
        if row["order"] == order and row["status"] == "located":
            row["status"] = outcome
            row["note"] = "; ".join(x for x in (
                "onboarding check %s: %s" % (datetime.date.today().isoformat(),
                                             reason), row["note"]) if x)
    with open(PORTALS, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def record(p, result):
    result = dict(result)
    if "outcome" in result:
        set_outcome(p["order"], result.pop("outcome"), result["reason"])
    have, mine = [], dict.fromkeys(FIELDS, "")
    if os.path.exists(USABILITY):
        with open(USABILITY, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r["order"] == p["order"]:
                    mine.update(r)
                else:
                    have.append(r)
    have.append(dict(mine, order=p["order"], place=p["place"],
                     product=p["product"], checked_on=datetime.date.today().isoformat(),
                     by="crawler", **result))
    with open(USABILITY, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(sorted(have, key=lambda r: int(r["order"])))


def exports(product, only):
    """The export for each usable portal of product that has none yet."""
    with open(PROBE, encoding="utf-8") as fh:
        probe = json.load(fh)
    with open(USABILITY, newline="", encoding="utf-8") as fh:
        todo = [u for u in csv.DictReader(fh) if u["product"] == product
                and int(u["pages"] or 0) >= 2
                and (u["order"] in only if only else not u["reference"])]
    with open(SAMPLE, newline="", encoding="utf-8") as fh:
        urls = {r["order"]: r["url"] for r in csv.DictReader(fh)}
    capture.retarget(os.path.join("population", "corpus"))
    capture.BUDGET = capture.spent() + (5 if product == "Accela"
                                        else BROWSER_PORTAL) * len(todo)
    for u in todo:
        final = probe.get(u["order"], {}).get("final_url")
        p = dict(u, home=final or urls[u["order"]], url=urls[u["order"]])
        print("-- %s %s" % (u["order"], u["place"]))
        if product == "Accela":
            result = accela_export(p, capture._opener(), u)
        else:
            result = amanda_export(p, final)
        print("   %s" % result["reference"])
        record(p, result)


def main(argv):
    if argv[0] == "reference":
        return references()
    if argv[0] in ("accela-export", "amanda-export"):
        return exports({"accela-export": "Accela", "amanda-export": "AMANDA"}[argv[0]],
                       set(argv[1:]))
    product = {"accela": "Accela", "smartgov": "SmartGov",
               "logis": "LOGIS ePermits", "clariti": "Clariti",
               "amanda": "AMANDA", "posse": "Computronix POSSE"}[argv[0]]
    only = set(argv[1:])
    with open(SAMPLE, newline="", encoding="utf-8") as fh:
        queue = [r for r in csv.DictReader(fh) if r["product"] == product
                 and r["access"] == "crawler"
                 and (r["order"] in only if only else r["role"] == "check")]
    with open(PROBE, encoding="utf-8") as fh:
        probe = json.load(fh)
    done = set()
    if os.path.exists(USABILITY) and not only:
        with open(USABILITY, newline="", encoding="utf-8") as fh:
            done = {r["order"] for r in csv.DictReader(fh)}
    queue = [p for p in queue if p["order"] not in done]
    capture.retarget(os.path.join("population", "corpus"))
    per = {"Accela": PER_PORTAL + BROWSER_LOAD,
           "LOGIS ePermits": PER_PORTAL}.get(product, BROWSER_PORTAL)
    capture.BUDGET = capture.spent() + per * len(queue)
    for p in queue:
        print("-- %s %s  %s" % (p["order"], p["place"], p["url"]))
        final = probe.get(p["order"], {}).get("final_url")
        if product == "Accela":
            # A fresh session per portal: tenancies on one host share its cookies.
            result = check_accela(p, capture._opener(), final)
        elif product == "LOGIS ePermits":
            result = check_logis(p, capture._opener(), final)
        elif product == "Clariti":
            result = check_clariti(p, final)
        elif product == "AMANDA":
            result = check_amanda(p, final)
        elif product == "Computronix POSSE":
            result = check_posse(p, final)
        else:
            result = check_smartgov(p, final)
        print("   %s" % result)
        record(p, result)


if __name__ == "__main__":
    main(sys.argv[1:])
