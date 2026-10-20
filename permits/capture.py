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
import email.utils
import hashlib
import io
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from http.cookiejar import CookieJar

from protego import Protego

from permits import aspnet
from permits import fingerprint as fp
from permits.crawler_identity import NAME as CRAWLER_NAME
from permits.crawler_identity import user_agent

try:
    from playwright.sync_api import Error as BrowserError
    from playwright.sync_api import sync_playwright
except ImportError:                                         # pragma: no cover
    BrowserError = sync_playwright = None

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
_robots_failed = {}
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


BLOCK_DATE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2}|(Jan|Feb|"
                        r"Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? "
                        r"\d{1,2}, \d{4})\b")
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr"}


class _Tree(HTMLParser):
    """A light element tree: each node's tag and class, children, own text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = {"sig": ("", ""), "kids": [], "text": []}
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = {"sig": (tag, dict(attrs).get("class") or ""), "kids": [],
                "text": []}
        self.stack[-1]["kids"].append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        # Close back to the nearest open tag of this name; a stray end tag
        # closes nothing.
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i]["sig"][0] == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1]["text"].append(data)


def record_blocks(markup, min_blocks=3):
    """The largest run of same-tag, same-class siblings that each carry a
    date, as (tag, class, count), or None.

    A result list need not be a table. Tyler EnerGov's is a column of record
    cards (Kyle TX, 2026-10-03), and the table-only fallback below stamped a
    page of ten permits "no rendered result list". Same failure as St. Johns'
    grid against the Accela markers: a layout-specific test in a
    vendor-neutral verdict. Records repeat a template and carry a date; a menu
    repeats but carries none, and a date picker carries day numbers, not
    dates.
    """
    tree = _Tree()
    tree.feed(markup)
    # Subtree text, children before parents, without recursion.
    order, todo = [], [tree.root]
    while todo:
        n = todo.pop()
        order.append(n)
        todo.extend(n["kids"])
    for n in reversed(order):
        n["all"] = "".join(n["text"]) + " ".join(k["all"] for k in n["kids"])
    best = None
    for n in order:
        groups = {}
        for k in n["kids"]:
            if BLOCK_DATE.search(k["all"]):
                groups[k["sig"]] = groups.get(k["sig"], 0) + 1
        for sig, count in groups.items():
            if count >= min_blocks and (best is None or count > best[2]):
                best = (sig[0], sig[1], count)
    return best


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
        blocks = record_blocks(m)
        if blocks:
            tag, cls, count = blocks
            return "ok", ("%d dated record blocks <%s class=\"%s\">"
                          % (count, tag, cls[:40]))
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


def _host_key(url):
    host = urllib.parse.urlsplit(url)[:2]
    return urllib.parse.urlunsplit((*host, "", "", ""))


ROBOTS_ACCEPT = "text/plain, */*;q=0.8"
ALLOW_ALL = Protego.parse("")
DISALLOW_ALL = Protego.parse("User-agent: *\nDisallow: /\n")


def robots_for(url, op):
    """Read robots.txt once per host. Recorded per page, never silently.

    Matched under RFC 9309 by Protego (Scrapy's parser): a group naming
    `PermitsResearchBot` replaces the `*` group, `*` and `$` are wildcards,
    and a rule keeps its query, so Google's `Disallow: /?` blocks only "/?..."
    URLs. The standard library's parser, used until 2026-10-20, read that rule
    as `Disallow: /` and ignored wildcards, and a leading byte-order mark hid
    the file's first group from it.

    Asked for as text: a server that honours Accept answered the page's
    text/html with 406 (LOGIS, 2026-10-20). Per RFC 9309 section 2.3.1, a 4xx
    means there are no rules; a 5xx or no answer means assume none of the site
    may be fetched.
    """
    key = _host_key(url)
    if key in _robots:
        return _robots[key]
    req = urllib.request.Request(key + "/robots.txt",
                                 headers={"Accept": ROBOTS_ACCEPT})
    _robots_failed[key] = ""
    try:
        _spent[0] += 1
        r = op.open(req, timeout=TIMEOUT)
        # "utf-8-sig": a byte-order mark otherwise hides the first line, and
        # SmartGov's first line is its only `User-agent: *` (2026-10-20).
        rp = Protego.parse(r.read(500000).decode("utf-8-sig", "replace"))
    except urllib.error.HTTPError as e:
        rp = ALLOW_ALL if 400 <= e.code < 500 else DISALLOW_ALL
    except Exception as e:
        # No answer at all: nothing is fetched, and the page's row says the
        # host could not be reached rather than that it refused.
        rp = DISALLOW_ALL
        _robots_failed[key] = "transport: robots.txt %s" % type(e).__name__
    _robots[key] = rp
    return rp


def robots_failed(url):
    """Why the host's robots.txt got no answer, or "" if it got one."""
    return _robots_failed.get(_host_key(url), "")


def allowed(url, op):
    return robots_for(url, op).can_fetch(url, CRAWLER_NAME)


def pause_for(url):
    """PAUSE, or the host's Crawl-delay where that is longer. Never shorter:
    Crawl-delay is a request to slow down, not permission to speed up."""
    rp = _robots.get(_host_key(url))
    delay = rp.crawl_delay(CRAWLER_NAME) if rp else None
    return max(PAUSE, float(delay or 0))


def _polite(url):
    host = urllib.parse.urlsplit(url).netloc
    pause = pause_for(url)
    gap = time.time() - _last.get(host, 0)
    if gap < pause:
        time.sleep(pause - gap)
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
    if not ok_robots and robots_failed(url):
        row = _row(url, url, None, "", "", "", jurisdiction, vendor, page_type,
                   "rejected", robots_failed(url), "POST" if data else "GET",
                   True, "")
        _write(row)
        print("  ERR     %-34s %s" % (name, robots_failed(url)))
        return None, row
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
    return _keep(raw, html, url, final, status, ctype, name, jurisdiction,
                 vendor, page_type, method)


def _keep(raw, html, url, final, status, ctype, name, jurisdiction, vendor,
          page_type, method, note=""):
    """Verify a page, save it and write its manifest row. One operation."""
    verdict, reason = verify(page_type, html, status)
    if note:
        reason = "%s; %s" % (reason, note)
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


# ------------------------------------------------------- fetching, rendered
# Never requested by a browser session: no record is read from them, and
# leaving them out spares the office's server.
SKIP_TYPES = {"image", "font", "media"}
# Kept for as long as the server says they may be cached. Intercepting
# requests, which the robots.txt check needs, turns the browser's own cache
# off: without this, every page load fetched every script again
# (2026-10-07, a script cacheable for an hour, 3 loads, 3 requests).
CACHED_TYPES = {"script", "stylesheet"}
MAX_AGE = re.compile(r"max-age=(\d+)")
LOAD_MS = 60000       # a navigation or an action
SETTLE_MS = 15000     # waiting for the page's own requests to finish
QUIET_MS = 500        # no request in flight for this long: the page has settled
NET_ERROR = re.compile(r"net::ERR_[A-Z_]+")


def fresh_until(headers, now=None):
    """When a response stops being fresh under its Cache-Control or Expires
    header, or None if it may not be kept. No heuristic freshness: a browser
    may keep a response that names no lifetime; this does not."""
    now = time.time() if now is None else now
    cc = (headers.get("cache-control") or "").lower()
    if "no-store" in cc or "no-cache" in cc:
        return None
    m = MAX_AGE.search(cc)
    if m:
        return now + int(m.group(1)) if int(m.group(1)) > 0 else None
    try:
        expires = email.utils.parsedate_to_datetime(headers.get("expires") or "")
    except (TypeError, ValueError):
        return None
    t = expires.timestamp()
    return t if t > now else None


class Browser:
    """A headless browser, for portals that build their search in the page.

    Some portals answer the crawler but build their search or their result
    list with JavaScript: Fresno's and Santa Rosa's Accela searches send the
    crawler to a script-built login panel, and EnerGov, MGO Connect,
    Cityworks and SmartGov render their lists in the browser. This fetches
    them under the same rules as `fetch()`:

    - the crawler's identity is the User-Agent on every request;
    - robots.txt is read for every request the page makes, its scripts and
      API calls included; a disallowed one is withheld and counted in the
      page's verdict reason;
    - each navigation and each action waits out the host's pause. The
      requests a page load makes count against BUDGET but are not paused;
    - images, fonts and media are never requested, and scripts and
      stylesheets are fetched once for as long as the server lets them be
      cached, as a browser's cache keeps them;
    - a page is saved as rendered, with its manifest row written in the same
      operation and request_method "BROWSER".

    One session per portal, so no cookie carries from one portal to another.
    Call `save` even after `go` was refused, so the refusal is on record:

        with capture.Browser("Fresno", "Accela") as b:
            if b.go(url):
                b.act(lambda page: page.click("#search"))
            html, row = b.save("crl_0012_p1", "T-INDEX")
    """

    def __init__(self, jurisdiction, vendor, headless=True):
        self.jurisdiction, self.vendor, self.headless = jurisdiction, vendor, headless
        self.page = None
        self._op = _opener()          # robots.txt is read the ordinary way
        self._pw = self._browser = None
        self._over = False
        self._pending = set()
        self._cache = {}              # url -> (fresh until, body, headers, status)
        self._sent = 0                # requests sent since the last save
        self._start(None)

    def _start(self, url):
        self._url, self._status, self._ctype = url, None, ""
        self._refused, self._error, self._withheld = False, "", 0

    def __enter__(self):
        if sync_playwright is None:
            raise SystemExit("the browser path needs Playwright: "
                             "uv sync --group render")
        ua = user_agent()             # raises before any request without a contact
        self._pw = sync_playwright().start()
        try:
            try:
                self._browser = self._pw.chromium.launch(channel="chrome",
                                                         headless=self.headless)
            except BrowserError:
                self._browser = self._pw.chromium.launch(headless=self.headless)
            # Service workers would fetch outside the route below, unseen by
            # the robots.txt check and the budget.
            context = self._browser.new_context(user_agent=ua, locale="en-US",
                                                service_workers="block")
            context.route("**/*", self._route)
            self.page = context.new_page()
            self.page.set_default_timeout(LOAD_MS)
            self.page.on("response", self._response)
            self.page.on("requestfinished", self._done)
            self.page.on("requestfailed", self._done)
        except BaseException:
            self.__exit__()           # a Playwright left running breaks the next session
            raise
        return self

    def __exit__(self, *exc):
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._pw is not None:
            self._pw.stop()
            self._pw = None

    def _route(self, route, request):
        url = request.url
        if request.resource_type in SKIP_TYPES:
            route.abort("blockedbyclient")
        elif not allowed(url, self._op):
            self._withheld += 1
            route.abort("blockedbyclient")
        elif _spent[0] >= BUDGET:
            self._over = True
            route.abort("blockedbyclient")
        else:
            self._fetch(route, request)

    def _fetch(self, route, request):
        url, kept = request.url, request.resource_type in CACHED_TYPES
        hit = self._cache.get(url) if kept else None
        if hit and hit[0] > time.time():
            _, body, headers, status = hit
            route.fulfill(status=status, headers=headers, body=body)
            return
        _spent[0] += 1
        self._sent += 1
        self._pending.add(request)
        if not kept:
            route.continue_()
            return
        # No redirects followed here: the browser makes the next request
        # itself, through this route and its robots.txt check.
        response = route.fetch(max_redirects=0)
        body = response.body()
        until = fresh_until(response.headers)
        if response.status == 200 and until:
            self._cache[url] = (until, body, response.headers, response.status)
        route.fulfill(response=response, body=body)

    def _done(self, request):
        self._pending.discard(request)

    def _response(self, response):
        if (response.request.resource_type == "document"
                and response.frame == self.page.main_frame):
            self._status = response.status
            self._ctype = (response.headers.get("content-type") or "").split(";")[0]

    def _step(self, url, action):
        if _spent[0] >= BUDGET:
            raise SystemExit("request budget of %d exhausted - pre-registered "
                             "ceiling, not a suggestion" % BUDGET)
        _polite(url)
        try:
            action()
        except BrowserError as e:
            # Chromium's own code says why (net::ERR_NAME_NOT_RESOLVED); the
            # exception's class is the same "Error" whatever went wrong.
            code = NET_ERROR.search(str(e))
            self._error = "transport: %s" % (code.group(0) if code
                                             else type(e).__name__)
            return False
        self._settle()
        if self._over:
            raise SystemExit("request budget of %d exhausted during a page "
                             "load - pre-registered ceiling" % BUDGET)
        return True

    def _settle(self):
        """Wait until no request is in flight for QUIET_MS, or SETTLE_MS in
        all for a page that keeps polling. Not Playwright's "networkidle": a
        page that has gone idle once answers it at once, while a click's own
        request is still out."""
        start = quiet = time.time()
        while time.time() - start < SETTLE_MS / 1000.0:
            self.page.wait_for_timeout(100)
            if self._pending:
                quiet = time.time()
            elif time.time() - quiet >= QUIET_MS / 1000.0:
                return

    def go(self, url):
        """Open url. False if robots.txt disallows it or it failed to load."""
        self._start(url)
        if not allowed(url, self._op):
            if robots_failed(url):
                self._error = robots_failed(url)
            else:
                self._refused = True
            return False
        return self._step(url, lambda: self.page.goto(url, wait_until="load"))

    def act(self, action):
        """Run action(page), a click or a fill, after the host's pause, then
        let the page settle. False if it failed; the next save records why."""
        return self._step(self.page.url, lambda: action(self.page))

    def save(self, name, page_type):
        """Save the page as rendered and write its manifest row, or write a
        rejected row for a refused or failed load. Returns (html, row) or
        (None, row), as `fetch()` does."""
        method = "BROWSER"
        if self._refused or self._error:
            reason = ("robots.txt disallows this path" if self._refused
                      else self._error)
            row = _row(self._url, self._url, None, "", "", "", self.jurisdiction,
                       self.vendor, page_type, "rejected", reason, method,
                       not self._refused, "")
            _write(row)
            print("  %-7s %-34s %s" % ("ROBOTS" if self._refused else "ERR",
                                       name, reason))
            return None, row
        html = self.page.content()
        # What getting the page cost the host, on its row: the report gives
        # the requests per portal.
        note = "%d requests sent" % self._sent
        if self._withheld:
            note += ", %d withheld for robots.txt" % self._withheld
        self._sent = self._withheld = 0
        return _keep(html.encode("utf-8"), html, self._url, self.page.url,
                     self._status, self._ctype or "text/html", name,
                     self.jurisdiction, self.vendor, page_type, method, note)


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
