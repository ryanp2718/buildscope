# -*- coding: utf-8 -*-
"""The capture layer, exercised over a real HTTP server on loopback.

`docs/design/testing.md` said for a long time that this surface could not be
tested without either making requests or mocking `urllib` — "and a mock of
`urllib` tests the mock". That was the right objection and the wrong
conclusion. A `ThreadingHTTPServer` bound to 127.0.0.1 costs a millisecond,
touches no network, and exercises the real opener, the real cookie jar, the
real `HTTPError` path and a real `robots.txt` round trip. Nothing below is
stubbed.

This file matters more than its size suggests. `permits/capture.py` writes the
manifest, and every analysis in this project reads the manifest rather than the
directory ([ADR-0006](../docs/adr/0006-the-observation-log-is-the-source-of-truth.md)).
A defect here does not crash anything; it produces a provenance log that
disagrees with what is on disk, which is the Spike C failure the module's own
docstring says it exists to prevent.

It was not preventing it. `test_a_page_is_never_written_without_its_row` failed
the first time it was run: `fetch()` wrote the page and *then* the row, and
`_migrate()` raises between the two, so a refused schema migration left an
unrecorded page on disk. That is the entire argument for writing these tests
before the move rather than after — the bug was sitting in the most
load-bearing module in the project and cost one minute to find once anything
was actually pointed at it.
"""
import csv
import io
import os
import re
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from permits import capture                              # noqa: E402
from permits import crawler_identity                      # noqa: E402

# --------------------------------------------------------------------------
# A page long enough to clear the 2,000-byte floor, carrying none of the
# vendor markers the verdict rules look for. Filler text is deliberately
# boring: "Showing 1 - 20" or "Record results" anywhere in it would make the
# structural-fallback tests pass for the wrong reason.
FILLER = "<div>parcel information and other page chrome</div>" * 60

GRID_ROWS = "".join(
    "<tr><td>BLD2026-%04d</td><td>01/%02d/2026</td>"
    "<td>Residential Alteration</td><td>Issued</td></tr>" % (i, i)
    for i in range(1, 6))

# St. Johns County's result grid: a real 500-row record list with none of
# Accela's control ids on it. The Accela-specific tests stamped this
# "rejected" once, permanently, in a log downstream analyses read.
STRUCTURAL_GRID = ("<html><body>" + FILLER +
                   '<table id="ctl00_PlaceHolderMain_ResultsGrid">' +
                   GRID_ROWS + "</table></body></html>")

# Accela's: the markers are present, so the vendor-specific path fires first.
ACCELA_GRID = ("<html><body>" + FILLER +
               '<div id="gdvPermitList"></div>'
               "<a href=\"CapDetail.aspx?capID1=26CAP-00000-001\">detail</a>"
               "</body></html>")

# A genuine permit detail page that carries sub-grids — inspections, related
# records — which legitimately say "Showing 1 - 3 of 3". Matching that threw
# away a real Marion County OR record on the first run.
DETAIL_WITH_SUBGRID = ("<html><body>" + FILLER +
                       "<span id='lblPermitNumber'>BLD2026-0042</span>"
                       "<div>Inspections: Showing 1 - 3 of 3</div>"
                       "</body></html>")

BASE_ROUTES = {
    "/robots.txt": (200, "text/plain", "User-agent: *\nDisallow: /admin\n"),
    "/index": (200, "text/html", ACCELA_GRID),
    "/other": (200, "text/html", ACCELA_GRID),
    "/admin/index": (200, "text/html", ACCELA_GRID),
}

ROUTES = {}
PORT = [0]


class _Handler(BaseHTTPRequestHandler):

    def do_GET(self):
        status, ctype, body = ROUTES.get(
            self.path, (404, "text/html", "<html><body>gone</body></html>"))
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        """The suite prints its own output; an access log on top is noise."""


_server = [None]


def setUpModule():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    PORT[0] = srv.server_address[1]
    _server[0] = srv
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def tearDownModule():
    if _server[0] is not None:
        _server[0].shutdown()
        _server[0].server_close()


def dead_port():
    """A port nothing is listening on, for the transport-failure path."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class CaptureCase(unittest.TestCase):
    """Points the capture layer at a temp tree and resets its module state."""

    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="buildscope-capture-")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.tmp = tmp

        # `retarget()` is deliberately ROOT-relative — it exists to keep Spike
        # B's provenance chain out of Measurement A/B's, not to escape the
        # tree — so the globals are set directly here rather than widening
        # production code to accommodate a test.
        saved = (capture.OUT, capture.PAGES, capture.MANIFEST,
                 capture.PAUSE, capture.BUDGET)

        def restore():
            (capture.OUT, capture.PAGES, capture.MANIFEST,
             capture.PAUSE, capture.BUDGET) = saved
        self.addCleanup(restore)

        capture.OUT = tmp
        capture.PAGES = os.path.join(tmp, "pages")
        capture.MANIFEST = os.path.join(tmp, "manifest.csv")
        capture.PAUSE = 0.0
        capture.ensure_dirs()

        # Module-level caches. A robots verdict or a spend count leaking
        # between tests makes one test's result depend on another's order.
        capture._spent[0] = 0
        capture._robots.clear()
        capture._last.clear()
        capture._migrated.clear()

        prev = os.environ.get(crawler_identity.CONTACT_ENV)

        def unset():
            if prev is None:
                os.environ.pop(crawler_identity.CONTACT_ENV, None)
            else:
                os.environ[crawler_identity.CONTACT_ENV] = prev
        self.addCleanup(unset)
        os.environ[crawler_identity.CONTACT_ENV] = "https://example.invalid/tests"

        ROUTES.clear()
        ROUTES.update(BASE_ROUTES)

    # ------------------------------------------------------------ helpers
    def url(self, path, port=None):
        return "http://127.0.0.1:%d%s" % (port or PORT[0], path)

    def opener(self):
        return capture._opener()

    def rows(self):
        if not os.path.exists(capture.MANIFEST):
            return []
        with io.open(capture.MANIFEST, encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    def pages(self):
        return sorted(os.listdir(capture.PAGES))

    def write_manifest(self, fields, rows=()):
        with io.open(capture.MANIFEST, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in rows:
                w.writerow(r)


class TestTheManifestIsWrittenWithThePage(CaptureCase):
    """D1: a page may not exist on disk without a row recording how it got
    there. Every test in this class is that one sentence from a different
    angle, because it is the only property of this module that everything
    downstream depends on."""

    def test_a_successful_fetch_writes_one_page_and_one_row(self):
        html, _row = capture.fetch(self.opener(), self.url("/index"),
                                  "acc_index", "TEST", "accela", "T-INDEX")
        self.assertIsNotNone(html)
        self.assertEqual(self.pages(), ["acc_index.html"])
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["file"], "acc_index.html")
        self.assertEqual(rows[0]["verdict"], "ok")
        self.assertEqual(rows[0]["http_status"], "200")
        self.assertEqual(rows[0]["request_method"], "GET")
        self.assertEqual(int(rows[0]["bytes"]), len(ACCELA_GRID))
        # The fingerprint is taken at capture because it cannot be taken later
        # for a page that has since changed — section 9, obligation 3.
        self.assertTrue(rows[0]["fp"], "no capture-time fingerprint recorded")
        self.assertIn(":", rows[0]["fp"], "fingerprint must carry its version")

    def test_a_page_is_never_written_without_its_row(self):
        """The one place the invariant can actually break, and did.

        A manifest carrying a column this version of the code does not know
        about means the code went backwards relative to the data, so
        `_migrate()` refuses and raises. It raises from inside `_write()` —
        which used to run *after* the page had already been saved, leaving an
        unrecorded page on disk. That is the Spike C failure exactly: bytes
        with no verdict attached, which a later analysis reads off the
        directory as if they had been accepted.
        """
        self.write_manifest([*capture.FIELDS, "captured_by"])
        with self.assertRaises(SystemExit):
            capture.fetch(self.opener(), self.url("/index"),
                          "acc_index", "TEST", "accela", "T-INDEX")
        self.assertEqual(self.pages(), [],
                         "a page was left on disk with no manifest row")

    def test_a_rejected_page_is_still_recorded(self):
        """A rejection is a verdict about content, not a reason to forget the
        content. `verify()` said no; the bytes and the fingerprint are still
        the evidence for why."""
        ROUTES["/thin"] = (200, "text/html", "<html><body>hi</body></html>")
        _html, row = capture.fetch(self.opener(), self.url("/thin"),
                                  "thin", "TEST", "accela", "T-INDEX")
        self.assertEqual(row["verdict"], "rejected")
        self.assertEqual(self.pages(), ["thin.html"])
        self.assertEqual(len(self.rows()), 1)

    def test_an_http_error_body_is_captured_not_discarded(self):
        """A 403 interstitial is the most interesting page a crawl produces.
        `urllib` raises on it; `fetch` reads the body off the exception."""
        ROUTES["/gone"] = (404, "text/html", "<html><body>not here</body></html>")
        _html, row = capture.fetch(self.opener(), self.url("/gone"),
                                  "gone", "TEST", "accela", "T-INDEX")
        self.assertEqual(row["http_status"], 404)
        self.assertEqual(row["verdict"], "rejected")
        self.assertEqual(row["verdict_reason"], "http 404")
        self.assertEqual(self.pages(), ["gone.html"])


class TestRobots(CaptureCase):

    def test_a_disallowed_path_produces_a_row_and_no_page(self):
        html, _row = capture.fetch(self.opener(), self.url("/admin/index"),
                                  "admin", "TEST", "accela", "T-INDEX")
        self.assertIsNone(html)
        self.assertEqual(self.pages(), [])
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["verdict"], "rejected")
        self.assertIn("robots", rows[0]["verdict_reason"])
        # Recorded, never silent: "we did not fetch this" is itself a finding
        # and has to survive into the log.
        self.assertEqual(rows[0]["robots_ok"], "False")

    def test_an_allowed_path_under_the_same_host_is_unaffected(self):
        html, _ = capture.fetch(self.opener(), self.url("/index"),
                                "ok", "TEST", "accela", "T-INDEX")
        self.assertIsNotNone(html)

    def test_robots_is_read_once_per_host(self):
        op = self.opener()
        capture.allowed(self.url("/index"), op)
        after_first = capture.spent()
        capture.allowed(self.url("/other"), op)
        self.assertEqual(capture.spent(), after_first,
                         "robots.txt re-fetched for the same host")

    def test_an_unreachable_robots_does_not_block_the_fetch(self):
        """A host with no robots.txt is not a host that forbids everything.
        The failure is swallowed deliberately and an empty rule set is
        cached, so the decision is made once."""
        ROUTES.pop("/robots.txt")
        self.assertTrue(capture.allowed(self.url("/index"), self.opener()))

    def test_a_group_naming_this_crawler_is_obeyed(self):
        """The opt-out `site/index.html` tells operators to use. It used to be
        ignored: only `User-agent: *` groups were read, so an operator who
        followed the published instructions was still crawled."""
        ROUTES["/robots.txt"] = (200, "text/plain",
                                 "User-agent: PermitsResearchBot\n"
                                 "Disallow: /\n")
        self.assertFalse(capture.allowed(self.url("/index"), self.opener()))

    def test_the_named_group_replaces_the_wildcard_group(self):
        """RFC 9309 section 2.2.1: a crawler obeys the group that names it,
        and only that group."""
        ROUTES["/robots.txt"] = (200, "text/plain",
                                 "User-agent: *\nDisallow: /\n\n"
                                 "User-agent: PermitsResearchBot\n"
                                 "Disallow: /admin\n")
        op = self.opener()
        self.assertTrue(capture.allowed(self.url("/index"), op))
        self.assertFalse(capture.allowed(self.url("/admin/index"), op))

    def test_another_crawlers_group_is_not_ours(self):
        ROUTES["/robots.txt"] = (200, "text/plain",
                                 "User-agent: Googlebot\nDisallow: /\n")
        self.assertTrue(capture.allowed(self.url("/index"), self.opener()))

    def test_the_published_opt_out_stops_the_crawler(self):
        """The robots.txt block on the crawler's public page, verbatim. If the
        page and the parser ever disagree, this fails rather than an operator
        finding out from their logs."""
        page = os.path.join(ROOT, "site", "index.html")
        with io.open(page, encoding="utf-8") as f:
            block = re.search(r'<pre id="opt-out">(.*?)</pre>', f.read(),
                              re.S)
        self.assertIsNotNone(block, "no opt-out block on the crawler page")
        ROUTES["/robots.txt"] = (200, "text/plain", block.group(1))
        self.assertFalse(capture.allowed(self.url("/index"), self.opener()))


class TestTransportFailure(CaptureCase):

    def test_a_refused_connection_produces_a_row_and_no_page(self):
        port = dead_port()
        html, _row = capture.fetch(self.opener(), self.url("/x", port),
                                  "dead", "TEST", "accela", "T-INDEX")
        self.assertIsNone(html)
        self.assertEqual(self.pages(), [])
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["verdict"], "rejected")
        self.assertTrue(rows[0]["verdict_reason"].startswith("transport:"),
                        rows[0]["verdict_reason"])


class TestBudget(CaptureCase):
    """The ceiling is pre-registered in
    docs/evidence/2026-09-20-measurement-ab-preregistration.md. A ceiling that
    prints a warning and carries on is not a ceiling."""

    def test_the_ceiling_raises_rather_than_continuing(self):
        capture.BUDGET = 2
        op = self.opener()
        capture.fetch(op, self.url("/index"), "one", "TEST", "accela",
                      "T-INDEX")
        self.assertEqual(capture.spent(), 2)      # robots.txt, then the page
        with self.assertRaises(SystemExit) as cm:
            capture.fetch(op, self.url("/other"), "two", "TEST", "accela",
                          "T-INDEX")
        self.assertIn("budget", str(cm.exception))
        self.assertEqual(self.pages(), ["one.html"])
        self.assertEqual(len(self.rows()), 1)

    def test_robots_requests_count_against_the_budget(self):
        """They are requests to somebody's server. A budget that only counts
        the interesting ones understates what the run actually cost the host."""
        capture.allowed(self.url("/index"), self.opener())
        self.assertEqual(capture.spent(), 1)


class TestPoliteness(CaptureCase):

    def test_the_pause_is_honoured_between_fetches(self):
        capture.PAUSE = 0.3
        op = self.opener()
        capture.allowed(self.url("/index"), op)   # warm robots; not the point
        capture.fetch(op, self.url("/index"), "one", "TEST", "accela",
                      "T-INDEX")
        start = time.time()
        capture.fetch(op, self.url("/other"), "two", "TEST", "accela",
                      "T-INDEX")
        self.assertGreater(time.time() - start, 0.25)

    def test_the_pause_is_per_host_not_global(self):
        """Waiting 1.5s between two different councils' servers is not
        politeness, it is a crawl that takes nine times as long as it should
        and is no gentler on either host."""
        capture.PAUSE = 0.3
        capture._polite("http://a.example/1")
        start = time.time()
        capture._polite("http://b.example/1")
        self.assertLess(time.time() - start, 0.25)
        start = time.time()
        capture._polite("http://a.example/2")
        self.assertGreater(time.time() - start, 0.25)

    def test_a_longer_crawl_delay_replaces_the_pause(self):
        """Crawl-delay is how an operator asks for slower rather than none."""
        ROUTES["/robots.txt"] = (200, "text/plain",
                                 "User-agent: PermitsResearchBot\n"
                                 "Crawl-delay: 1\n")
        op = self.opener()
        capture.fetch(op, self.url("/index"), "one", "TEST", "accela",
                      "T-INDEX")
        start = time.time()
        capture.fetch(op, self.url("/other"), "two", "TEST", "accela",
                      "T-INDEX")
        self.assertGreater(time.time() - start, 0.9)

    def test_a_shorter_crawl_delay_does_not_speed_the_crawler_up(self):
        ROUTES["/robots.txt"] = (200, "text/plain",
                                 "User-agent: *\nCrawl-delay: 1\n")
        capture.PAUSE = 3.0
        capture.allowed(self.url("/index"), self.opener())
        self.assertEqual(capture.pause_for(self.url("/index")), 3.0)


class TestSchemaMigration(CaptureCase):
    """Appending a 16-field row under a 15-column header does not fail. csv
    writes the extra value and every later `DictReader` silently misaligns —
    the quiet corruption this project keeps meeting."""

    def test_a_missing_column_is_added_and_rows_are_preserved(self):
        old = [f for f in capture.FIELDS if f != "fp"]
        self.write_manifest(old, [dict.fromkeys(old, "x")])
        capture._migrate(capture.MANIFEST)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(list(rows[0].keys()), capture.FIELDS)
        self.assertEqual(rows[0]["fp"], "")
        self.assertEqual(rows[0]["url"], "x")

    def test_an_unknown_column_refuses_and_changes_nothing(self):
        """'Refusing to rewrite it' has to mean the bytes on disk are
        untouched, or the refusal is just a slower version of the damage."""
        self.write_manifest([*capture.FIELDS, "captured_by"])
        before = io.open(capture.MANIFEST, "rb").read()
        with self.assertRaises(SystemExit) as cm:
            capture._migrate(capture.MANIFEST)
        self.assertIn("captured_by", str(cm.exception))
        self.assertEqual(io.open(capture.MANIFEST, "rb").read(), before)

    def test_migration_runs_before_the_first_append(self):
        """Not on import, and not once per row: the check has to sit between
        an existing manifest and the first row written into it."""
        old = [f for f in capture.FIELDS if f != "fp"]
        self.write_manifest(old, [dict.fromkeys(old, "x")])
        capture.fetch(self.opener(), self.url("/index"), "one", "TEST",
                      "accela", "T-INDEX")
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(list(rows[1].keys()), capture.FIELDS)
        self.assertTrue(rows[1]["fp"])


class TestVerdicts(unittest.TestCase):
    """`verify()` is pure, so it needs no server. Each test below is a
    discriminator that fired on something every page has, and the cost of each
    was a real record thrown away or a real non-record kept."""

    def test_non_200_is_rejected_before_anything_is_parsed(self):
        self.assertEqual(capture.verify("T-INDEX", ACCELA_GRID, 500),
                         ("rejected", "http 500"))

    def test_an_interstitial_is_rejected(self):
        page = "<html><body>Just a moment...</body></html>" + FILLER
        verdict, _ = capture.verify("T-INDEX", page, 200)
        self.assertEqual(verdict, "rejected")

    def test_a_javascript_constant_does_not_decide_a_verdict(self):
        """Accela ships UI strings as JS constants on every page. Matching raw
        HTML for them has twice nearly inverted a finding, so every verdict is
        computed against markup with script and style removed."""
        page = ACCELA_GRID.replace(
            "<body>", "<body><script>var msg = 'Access Denied';</script>")
        self.assertEqual(capture.verify("T-INDEX", page, 200)[0], "ok")

    def test_a_result_grid_without_vendor_markup_still_verifies(self):
        """St. Johns County: a 500-row result grid with none of Accela's
        control ids on it, stamped 'rejected' by a vendor-specific test in a
        vendor-neutral verdict."""
        verdict, reason = capture.verify("T-INDEX", STRUCTURAL_GRID, 200)
        self.assertEqual(verdict, "ok", reason)
        self.assertIn("dated rows", reason)

    def test_a_page_with_no_grid_at_all_is_rejected(self):
        verdict, _ = capture.verify("T-INDEX", "<html><body>" + FILLER +
                                    "</body></html>", 200)
        self.assertEqual(verdict, "rejected")

    def test_a_detail_page_may_carry_sub_grids(self):
        """A genuine permit record has inspections and related records on it,
        and they say 'Showing 1 - 3 of 3'. Rejecting on that threw away a real
        Marion County OR record."""
        self.assertEqual(capture.verify("T-DETAIL", DETAIL_WITH_SUBGRID, 200)[0],
                         "ok")

    def test_a_result_list_is_not_a_detail_page(self):
        self.assertEqual(capture.verify("T-DETAIL", ACCELA_GRID, 200),
                         ("rejected", "this is a result list, not a record"))

    def test_api_responses_are_not_subject_to_the_size_floor(self):
        """A correct JSON response can be 181 bytes. The floor false-rejected
        Seattle's work-type vocabulary, which was valid and complete."""
        verdict, reason = capture.verify("API-DATA", '{"results": [{"a": 1}]}', 200)
        self.assertEqual((verdict, reason), ("ok", "1 records"))

    def test_an_empty_api_envelope_is_rejected(self):
        """The silent failure in API shape: 200, valid JSON, zero records, and
        a pipeline that records a quiet month in a city that issued four
        hundred permits."""
        self.assertEqual(capture.verify("API-DATA", '{"results": []}', 200),
                         ("rejected", "endpoint returned 0 records"))

    def test_unparseable_json_is_rejected_not_crashed(self):
        verdict, _ = capture.verify("API-DATA", "<html>error</html>", 200)
        self.assertEqual(verdict, "rejected")

    def test_an_unrecognised_shape_is_unknown_not_rejected(self):
        """'I cannot tell' and 'this is bad' are different verdicts, and
        collapsing them loses the pages worth looking at by hand."""
        verdict, _ = capture.verify("API-DATA", '{"count": 7}', 200)
        self.assertEqual(verdict, "unknown")


if __name__ == "__main__":
    unittest.main()
