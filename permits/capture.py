# -*- coding: utf-8 -*-
"""The capture layer: fetch a page, verify it, record how it was got.

Every byte this project reasons about entered through here. Nothing downstream
re-fetches, so the manifest this writes is the provenance chain for the whole
pipeline.

Spike C found that Spike A's saved bytes did not carry their verdicts, so
pages the Spike A verifier had rejected - an iron castings foundry among them -
walked back into a downstream analysis as municipal websites. The fix is not a
better filter downstream. It is that a page may not exist on disk without a
manifest row written in the same operation, and that every analysis reads the
manifest rather than the directory.

That is the D1 constraint the Spike C report raised, implemented here at the
smallest scale it can be implemented at.

Nothing in this module decides anything. It fetches, it verifies, it records.
The decision rules live in
docs/evidence/2026-09-20-measurement-ab-preregistration.md and were fixed
before any of this ran.

Until 2026-09-22 this was `scripts/measure_fetch.py`, named after the
measurement it was first written for, and twenty-two scripts reached it
through a `sys.path` hack. It is the capture layer, it was always the capture
layer, and it belongs in the package.
"""
import csv
import hashlib
import io
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

from permits import aspnet
from permits import fingerprint as fp
from permits.crawler_identity import user_agent

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "measure")
PAGES = os.path.join(OUT, "pages")
MANIFEST = os.path.join(OUT, "manifest.csv")

PAUSE = 1.5
TIMEOUT = 30
BUDGET = 60           # pre-registered ceiling, enforced not just stated

FIELDS = ["fetched_at", "url", "final_url", "http_status", "content_type",
          "bytes", "sha256", "jurisdiction", "vendor", "page_type",
          "verdict", "verdict_reason", "request_method", "robots_ok", "file",
          "fp"]

# `fp` is section 9 obligation 3: the structural fingerprint, taken at capture
# because it cannot be taken later for a page that has since changed. It is
# stored as "version:hash" so a hash computed under different skeleton rules
# is never silently compared to one computed under these.

_spent = [0]
_robots = {}
_last = {}


# ---------------------------------------------------------------- verdicts
def strip_scripts(html):
    """Accela ships UI strings as JS constants on every page. Matching raw
    HTML for them has now twice nearly inverted a finding, so every verdict
    below is computed against markup with script and style removed."""
    html = re.sub(r"(?is)<script.*?</script>", " ", html)
    return re.sub(r"(?is)<style.*?</style>", " ", html)


RESULT_GRID = re.compile(r"(gdvPermitList|divSearchResultList|"
                         r"Record results|Showing\s*\d+\s*-\s*\d+)", re.I)
# Narrower test, used only to reject a T-DETAIL that is really a result list.
# RESULT_GRID is too broad for that job: a genuine permit detail page carries
# sub-grids (inspections, related records, attachments) that legitimately say
# "Showing 1-3 of 3", and matching those threw away a real Marion County OR
# record on the first run. Same failure family as the "Please enter" JS
# constant - a discriminator that fires on something every page has.
IS_RESULT_LIST = re.compile(r"(gdvPermitList|divSearchResultList)", re.I)
DETAIL_LINK = re.compile(r"CapDetail\.aspx\?[^\"'>]*capID1=", re.I)
DETAIL_BODY = re.compile(r"(PermitDetail|lblPermitNumber|Record\s*Details|"
                         r"CapDetailContent|Work Location|Record Status)", re.I)
SEARCH_FORM = re.compile(r"(generalSearchForm|btnNewSearch|txtGSPermitNumber|"
                         r"SearchButton)", re.I)
BLOCKED = re.compile(r"(just a moment|checking your browser|attention required|"
                     r"access denied|forbidden|are you a robot|"
                     r"verify you are human|page not found|\b404\b)", re.I)


def verify(page_type, html, status):
    """Return (verdict, reason). Assigned here, at capture, never later."""
    if status != 200:
        return "rejected", "http %s" % status
    m = strip_scripts(html)
    head = m[:4000]
    if BLOCKED.search(head):
        return "rejected", "interstitial or error page"
    # The size floor is an HTML-page heuristic and must not reach API types:
    # a correct JSON response can be 181 bytes. It false-rejected Seattle's
    # work-type vocabulary, which was valid and complete. API page types carry
    # their own emptiness check below, on record count.
    if not page_type.startswith("API-") and len(m) < 2000:
        return "rejected", "body too small (%d bytes stripped)" % len(m)

    if page_type == "T-SEARCH":
        if SEARCH_FORM.search(m):
            return "ok", "search form present"
        # Same vendor-specificity problem as T-INDEX below: SEARCH_FORM spells
        # out Accela control ids, and St. Johns County's form - which renders
        # a date range, a permit-type select and a Search button - fails all
        # four. Structural fallback: a POST form carrying a submit control and
        # several named text inputs is a search form whoever built it.
        named = aspnet.form_fields(m)
        submits = [n for n, (tag, typ, _) in named.items()
                   if typ in ("submit", "image") or tag == "button"]
        texts = [n for n, (tag, typ, _) in named.items()
                 if tag == "select" or typ in ("text", "date", "")]
        if submits and len(texts) >= 3:
            return "ok", ("search form present (%d inputs, %d submits)"
                          % (len(texts), len(submits)))
        return "rejected", "no search form found"
    if page_type == "T-INDEX":
        if RESULT_GRID.search(m) and DETAIL_LINK.search(m):
            return "ok", "result grid with record links"
        if RESULT_GRID.search(m):
            return "unknown", "grid present but no record links"
        # The two tests above are Accela's markup. They stamped St. Johns
        # County's 500-row result grid "rejected" - a perfectly good record
        # list, permanently marked unusable, in a log that downstream analyses
        # read instead of the directory. That is the Spike C failure running
        # in the opposite direction, and a vendor-specific discriminator in a
        # vendor-neutral verdict is the bug. Fall back to a structural test:
        # an id'd table with enough rows, enough columns, and dates in them.
        try:
            grids = aspnet.result_grids(m)
        except Exception:                                   # noqa: BLE001
            grids = []
        if grids:
            tid, _wide, dated = max(grids, key=lambda g: len(g[2]))
            return "ok", "result grid %s, %d dated rows" % (tid[:40], len(dated))
        return "rejected", "no rendered result list"
    if page_type in ("API-CATALOG", "API-DATA"):
        # Spike B fetches JSON from open-data APIs rather than HTML. The
        # verdict is the same question in a different shape: did the endpoint
        # actually return records, or a polite empty envelope?
        try:
            j = json.loads(html)
        except ValueError:
            return "rejected", "response is not valid JSON"
        n = None
        if isinstance(j, list):
            n = len(j)
        elif isinstance(j, dict):
            for k in ("results", "features", "data", "dataset"):
                if isinstance(j.get(k), list):
                    n = len(j[k])
                    break
            if n is None and "resultRecordCount" in j:
                n = j["resultRecordCount"]
        if n is None:
            return "unknown", "JSON parsed but no recognised record array"
        if n == 0:
            return "rejected", "endpoint returned 0 records"
        return "ok", "%d records" % n
    if page_type == "T-DETAIL":
        if IS_RESULT_LIST.search(m):
            return "rejected", "this is a result list, not a record"
        if DETAIL_BODY.search(m):
            return "ok", "record detail markers present"
        return "unknown", "no detail markers matched"
    return "unknown", "unrecognised page type"


# ---------------------------------------------------------------- fetching
def _opener():
    op = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar()))
    op.addheaders = [("User-Agent", user_agent()),
                     ("Accept", "text/html,application/xhtml+xml"),
                     ("Accept-Language", "en-US,en;q=0.9")]
    return op


def robots_ok(url, op):
    """Read robots.txt once per host. Recorded per page, never silently."""
    host = urllib.parse.urlsplit(url)[:2]
    key = urllib.parse.urlunsplit((*host, "", "", ""))
    if key in _robots:
        return _robots[key]
    try:
        _spent[0] += 1
        r = op.open(key + "/robots.txt", timeout=TIMEOUT)
        body = r.read(200000).decode("utf-8", "replace")
        dis = []
        agent_all = False
        for line in body.splitlines():
            line = line.split("#")[0].strip()
            if not line:
                continue
            k, _, v = line.partition(":")
            k, v = k.strip().lower(), v.strip()
            if k == "user-agent":
                agent_all = (v == "*")
            elif k == "disallow" and agent_all and v:
                dis.append(v)
        _robots[key] = dis
    except Exception:
        _robots[key] = []
    return _robots[key]


def allowed(url, op):
    path = urllib.parse.urlsplit(url).path or "/"
    for d in robots_ok(url, op):
        if d == "/" or path.startswith(d):
            return False
    return True


def _polite(url):
    host = urllib.parse.urlsplit(url).netloc
    gap = time.time() - _last.get(host, 0)
    if gap < PAUSE:
        time.sleep(PAUSE - gap)
    _last[host] = time.time()


def fetch(op, url, name, jurisdiction, vendor, page_type, data=None,
          headers=None):
    """Fetch, save bytes, and write the manifest row. One operation.

    Returns (html, row) or (None, row). Never returns bytes without having
    recorded a verdict for them.
    """
    if _spent[0] >= BUDGET:
        raise SystemExit("request budget of %d exhausted - pre-registered "
                         "ceiling, not a suggestion" % BUDGET)
    ok_robots = allowed(url, op)
    if not ok_robots:
        row = _row(url, url, None, "", "", "", jurisdiction, vendor, page_type,
                   "rejected", "robots.txt disallows this path",
                   "POST" if data else "GET", False, "")
        _write(row)
        print("  ROBOTS  %-34s %s" % (name, "disallowed"))
        return None, row

    _polite(url)
    _spent[0] += 1
    method = "POST" if data is not None else "GET"
    req = urllib.request.Request(url, data=data)
    if data is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    # ASP.NET WebForms apps commonly enforce a same-origin check on postbacks;
    # Accela answers a POST without them with "Potential cross-site request
    # forgery attacks. The Referer and Origin headers are missing" and a stub
    # page. These are the headers an ordinary browser sends.
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        r = op.open(req, timeout=TIMEOUT)
        raw = r.read()
        status, final, ctype = r.getcode(), r.geturl(), r.headers.get_content_type()
    except urllib.error.HTTPError as e:
        raw, status, final = e.read(), e.code, url
        ctype = e.headers.get_content_type() if e.headers else ""
    except Exception as e:
        row = _row(url, url, None, "", "", "", jurisdiction, vendor, page_type,
                   "rejected", "transport: %s" % type(e).__name__, method, True, "")
        _write(row)
        print("  ERR     %-34s %s" % (name, type(e).__name__))
        return None, row

    html = raw.decode("utf-8", "replace")
    verdict, reason = verify(page_type, html, status)
    fn = "%s.html" % name
    # Fingerprint every page we keep, including rejected ones: a rejection is
    # a verdict about content, and "what did the blocking page look like"
    # is answerable only if the bytes were fingerprinted when they arrived.
    # `mark()` is empty for a body with no DOM - a JSON API response, a PDF -
    # rather than the sha1 of the empty path set, which every one of them
    # would otherwise share and which reads as a template collision.
    mark = fp.fingerprint(html).mark()
    row = _row(url, final, status, ctype, len(raw),
               hashlib.sha256(raw).hexdigest(), jurisdiction, vendor, page_type,
               verdict, reason, method, True, fn, mark)
    # The page lands under a temporary name and is promoted only once its row
    # is on disk. Written the other way round - which is how this stood until
    # 2026-09-22 - a refused schema migration raises out of `_write` between
    # the two steps and leaves an unrecorded page behind: the exact Spike C
    # failure this module exists to prevent, reintroduced by the module
    # itself. `tests/test_capture.py` holds the case that found it.
    part = os.path.join(PAGES, fn + ".part")
    with io.open(part, "w", encoding="utf-8", newline="") as f:
        f.write(html)
    try:
        _write(row)
    except BaseException:
        os.remove(part)
        raise
    os.replace(part, os.path.join(PAGES, fn))
    print("  %-7s %-34s %s  %6dB  %s"
          % (verdict.upper(), name, page_type, len(raw), reason))
    return html, row


def _row(url, final, status, ctype, nbytes, sha, juris, vendor, ptype,
         verdict, reason, method, rob, fn, mark=""):
    return {"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "url": url, "final_url": final, "http_status": status or "",
                "content_type": ctype, "bytes": nbytes, "sha256": sha,
                "jurisdiction": juris, "vendor": vendor, "page_type": ptype,
                "verdict": verdict, "verdict_reason": reason, "request_method": method,
                "robots_ok": rob, "file": fn, "fp": mark}


def _migrate(path):
    """Bring an existing manifest up to the current FIELDS, once.

    Appending a 16-field row under a 15-column header does not fail - csv
    writes the extra value and every subsequent DictReader silently
    misaligns. That is the quiet variety of corruption this project keeps
    running into, so the column set is reconciled before any append rather
    than assumed.

    Only additive migration is allowed. A column that exists on disk but not
    in FIELDS means the code went backwards relative to the data, and the
    right response is to stop, not to drop the column.
    """
    with io.open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        f.seek(0)
        have = next(csv.reader(f), [])
    if have == FIELDS:
        return
    lost = [c for c in have if c not in FIELDS]
    if lost:
        raise SystemExit(
            "manifest %s has columns the code no longer knows about (%s). "
            "Refusing to rewrite it - a capture log is not dropped to make "
            "the writer happy." % (path, ", ".join(lost)))
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    print("  manifest migrated: %s gained %s"
          % (os.path.basename(path), ", ".join(c for c in FIELDS
                                               if c not in have)))


_migrated = set()


def _write(row):
    new = not os.path.exists(MANIFEST)
    if not new and MANIFEST not in _migrated:
        _migrate(MANIFEST)
        _migrated.add(MANIFEST)
    with io.open(MANIFEST, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def retarget(subdir):
    """Point the capture layer at a different data/<subdir>/ tree.

    Spike B writes its own corpus and its own manifest; sharing Measurement
    A/B's would mix two provenance chains into one log and make neither
    auditable.
    """
    global OUT, PAGES, MANIFEST
    OUT = os.path.join(ROOT, "data", subdir)
    PAGES = os.path.join(OUT, "pages")
    MANIFEST = os.path.join(OUT, "manifest.csv")
    ensure_dirs()


def ensure_dirs():
    for d in (OUT, PAGES):
        if not os.path.isdir(d):
            os.makedirs(d)


def spent():
    return _spent[0]
