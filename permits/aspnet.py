# -*- coding: utf-8 -*-
"""ASP.NET WebForms postback mechanics, shared by every bucket-3/4 adapter.

Most municipal permit portals that are not an open-data API are WebForms
apps - Accela ACA, the WATS .NET app St. Johns County FL runs, CityView's
server-rendered pages. They all share one calling convention, and getting it
subtly wrong produces a 200 OK with a stub page rather than an error, which is
the worst possible failure mode: it looks like "no records".

Three mechanics live here because each one has already cost a wrong answer:

1. **ViewState can be split across numbered fields.** St. Johns renders
   `__VIEWSTATE` plus `__VIEWSTATE1..5` at 4000 chars each with
   `__VIEWSTATEFIELDCOUNT=6`. A hidden-field regex of `__[A-Z]+[A-Za-z]*`
   matches the first and silently drops the other five; the server then
   redirects to `ErrPage.aspx` with a 474-byte body. Names here allow digits.

2. **A postback needs Referer and Origin.** Accela answers a POST without them
   with "Potential cross-site request forgery attacks" and a stub.

3. **A submit button posts its own name/value; a link posts `__EVENTTARGET`.**
   These are not interchangeable. `btnSearch` is an `<input type=submit>` and
   must appear in the body as `name=value`; a GridView pager is a
   `__doPostBack` link and must go through `__EVENTTARGET`/`__EVENTARGUMENT`.

Nothing here decides anything. It builds request bodies and reads tables.
"""
import re
import urllib.parse

HIDDEN = re.compile(
    r'<input[^>]+type="hidden"[^>]*name="(__[A-Za-z][A-Za-z0-9]*)"[^>]*value="([^"]*)"',
    re.I)
HIDDEN_REV = re.compile(
    r'<input[^>]+name="(__[A-Za-z][A-Za-z0-9]*)"[^>]+value="([^"]*)"[^>]*type="hidden"',
    re.I)
NAMED = re.compile(r'<(input|select|textarea)\b([^>]*)>', re.I)
ATTR = re.compile(r'(\w[\w-]*)\s*=\s*"([^"]*)"')

TABLE = re.compile(r'<table[^>]*\bid="([^"]+)"[^>]*>(.*?)</table>', re.I | re.S)
TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.I | re.S)
TD = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.I | re.S)
DATE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")


def unescape(s):
    return (s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
             .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " "))


def text(html):
    """Tag-stripped, whitespace-collapsed text of a fragment."""
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html))).strip()


def hidden_fields(html):
    """Every `__`-prefixed hidden field, chunked ViewState included.

    Returns them exactly as rendered. The caller must not reassemble chunked
    ViewState into one field - the server expects the same split back.
    """
    d = {}
    for pat in (HIDDEN, HIDDEN_REV):
        for k, v in pat.findall(html):
            d.setdefault(k, unescape(v))
    n = d.get("__VIEWSTATEFIELDCOUNT")
    if n and n.isdigit():
        missing = [i for i in range(1, int(n))
                   if ("__VIEWSTATE%d" % i) not in d]
        if missing:
            raise ValueError(
                "__VIEWSTATEFIELDCOUNT says %s chunks but %s are missing from "
                "the parsed form; posting this would be silently rejected"
                % (n, missing))
    return d


def form_fields(html, prefix=None):
    """Named inputs/selects on the page -> {name: (tag, type, value)}."""
    out = {}
    for tag, attrs in NAMED.findall(html):
        a = dict(ATTR.findall(attrs))
        name = a.get("name")
        if not name or (prefix and not name.startswith(prefix)):
            continue
        out[name] = (tag.lower(), a.get("type", "").lower(),
                     unescape(a.get("value", "")))
    return out


def body(hidden, event_target=None, event_argument="", submit=None,
         criteria=None):
    """Assemble a postback body.

    `submit` is an (name, value) pair for an `<input type=submit>`; use it or
    `event_target`, never both, because the two are different controls and a
    page that expects one ignores the other.
    """
    b = dict(hidden)
    if event_target is not None:
        b["__EVENTTARGET"] = event_target
        b["__EVENTARGUMENT"] = event_argument
    if submit is not None:
        b[submit[0]] = submit[1]
    b.update(criteria or {})
    return b


def encode(b):
    return urllib.parse.urlencode(b).encode("utf-8")


def headers_for(url):
    return {"Referer": url, "Origin": "://".join(urllib.parse.urlsplit(url)[:2])}


# ------------------------------------------------------------------ tables
def tables(html):
    """(table_id, rows) for every id'd table, rows as lists of cell text."""
    out = []
    for tid, tbody in TABLE.findall(html):
        rows = [[text(c) for c in TD.findall(r)] for r in TR.findall(tbody)]
        out.append((tid, [r for r in rows if r]))
    return out


def result_grids(html, min_rows=3, min_cols=3):
    """Tables that plausibly hold records, not chrome.

    A table qualifies only if it has enough rows, enough columns, and at least
    one row carrying a date. St. Johns' *form* page has 44 `<tr>` spread over
    layout tables and no result grid at all; a bare `<tr>` count read that as
    15 records once already. The date test is what separates a record list
    from a menu.
    """
    out = []
    for tid, rows in tables(html):
        wide = [r for r in rows if len(r) >= min_cols]
        if len(wide) < min_rows:
            continue
        dated = [r for r in wide if DATE.search(" ".join(r))]
        if not dated:
            continue
        out.append((tid, wide, dated))
    return out
