# -*- coding: utf-8 -*-
"""The results page, rendered in a real browser before anything is published.

Serves `site/results/` locally and loads it at a desktop and a phone width,
in light and dark, and once with JavaScript off. It checks what a person
looking at a screenshot would catch: script errors, charts drawn with the
wrong number of marks, text running off the screen, a page wider than the
phone. The checks are counted against `data.json`, so a chart that silently
drops a model fails here.

It loads the page's D3 from cdnjs and its fonts from Google Fonts, so unlike
the rest of the suite it needs the network, and it runs only when asked:

    RENDER_CHECK=1 uv run pytest tests/test_render.py

with the `render` dependency group installed and a browser, system Chrome if
there is one, else Playwright's own (`uv run playwright install chromium`).
Otherwise it skips, and the suite stays offline. CI runs it as its own job.

Set RENDER_SHOTS to a directory to also save the screenshots for review.
"""
import functools
import http.server
import json
import os
import threading
import unittest

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright
except ImportError:                                        # pragma: no cover
    sync_playwright = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site", "results")
SHOTS = os.environ.get("RENDER_SHOTS")

VIEWS = [("desktop", 1280, 860, "light"), ("phone", 390, 844, "dark")]

# Chart text that runs past either edge of the viewport.
OFF_SCREEN = """() => [...document.querySelectorAll(`#price-chart text, #slope-chart text,
    #ports-chart text, #effects-chart text, #wall-chart text`)]
    .map(t => [t.textContent, t.getBoundingClientRect()])
    .filter(([s, r]) => r.width && (r.left < -0.5 || r.right > window.innerWidth + 0.5))
    .map(([s, r]) => s)"""
H_OVERFLOW = "document.documentElement.scrollWidth > window.innerWidth"


def _expected(data):
    """Mark counts the page should draw, from the data it reads."""
    roster = [m["id"] for m in data["models"] if m["group"] == "roster"]
    ids = {m["id"] for m in data["models"]}
    cells = {c["key"]: c for c in data["cells"]}
    points = [m for m in roster if "clarkco|%s|v2" % m in cells]
    squares = sum(1 for d in data["draws"]
                  if d["cell"].endswith("|v2") and "|hint|" not in d["cell"]
                  and d["cell"].split("|")[1] in ids)
    held = set()
    price = {m["id"]: m["price_out"] for m in data["models"]}
    for q in data.get("pairs", []):
        if (q["target"] == "clarkco" and q["arm"] == "baseline" and q["protocol"] == "v2"
                and q["settled"] and q["a"] in points and q["b"] in points
                and price[q["a"]] > price[q["b"]]):
            held.update((q["a"], q["b"]))
    ports = sum(1 for m in points for t in ("clarkco", "stjohns", "santabarbara")
                if "%s|%s|v2" % (t, m) in cells)
    return {"points": len(points), "squares": squares, "held": len(held),
            "ports": ports, "contrasts": len(data.get("contrasts", [])),
            "wall": len(data.get("wall", []))}


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@unittest.skipUnless(os.environ.get("RENDER_CHECK") == "1",
                     "needs the network; set RENDER_CHECK=1 to run")
@unittest.skipIf(sync_playwright is None, "the render dependency group is not installed")
class TestResultsPage(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(SITE, "data.json"), encoding="utf-8") as fh:
            cls.want = _expected(json.load(fh))
        handler = functools.partial(_Quiet, directory=SITE)
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d/" % cls.server.server_address[1]
        cls.pw = sync_playwright().start()
        cls.browser = None
        for kw in ({"channel": "chrome"}, {}):
            try:
                cls.browser = cls.pw.chromium.launch(**kw)
                break
            except PlaywrightError:
                continue
        if cls.browser is None:
            cls.tearDownClass()
            raise unittest.SkipTest("no browser: install Chrome or run "
                                    "`uv run playwright install chromium`")

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "browser", None):
            cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()
        cls.server.server_close()

    def _open(self, w, h, scheme, js=True, path="index.html"):
        ctx = self.browser.new_context(viewport={"width": w, "height": h},
                                       color_scheme=scheme, java_script_enabled=js)
        self.addCleanup(ctx.close)
        page = ctx.new_page()
        errors = []
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("requestfailed", lambda r: errors.append("failed: " + r.url))
        page.goto(self.base + path, wait_until="networkidle")
        return page, errors

    def _shot(self, page, name, locator=None):
        if SHOTS:
            os.makedirs(SHOTS, exist_ok=True)
            target = page.locator(locator) if locator else page
            target.screenshot(path=os.path.join(SHOTS, name + ".png"))

    def test_the_page_draws_every_mark_and_fits_the_screen(self):
        for tag, w, h, scheme in VIEWS:
            with self.subTest(view=tag):
                page, errors = self._open(w, h, scheme)
                page.wait_for_selector("#price-chart g.pt")
                page.wait_for_selector("[data-table] table", state="attached")
                page.evaluate("document.fonts.ready")
                page.wait_for_timeout(300)

                self.assertEqual(page.locator("#price-chart g.pt").count(), self.want["points"])
                self.assertEqual(page.locator("#slope-chart path.sl-line").count(),
                                 self.want["points"])
                self.assertEqual(page.locator("#slope-chart path.sl-line.held").count(),
                                 self.want["held"])
                self.assertEqual(page.locator("#unit-chart rect").count(), self.want["squares"])
                self.assertEqual(page.locator("#ports-chart path.p-mark").count(), self.want["ports"])
                self.assertEqual(page.locator("#effects-chart g.ef-row").count(),
                                 self.want["contrasts"])
                self.assertEqual(page.locator("#wall-chart circle").count(), self.want["wall"])
                self.assertEqual(page.locator("[data-table] table").count(), 7)
                # Every number the prose fills in was filled.
                self.assertEqual(page.evaluate(
                    "[...document.querySelectorAll('[data-q]')].filter(e => !e.textContent.trim())"
                    ".map(e => e.dataset.q)"), [])
                self.assertEqual(page.evaluate(OFF_SCREEN), [])
                self.assertFalse(page.evaluate(H_OVERFLOW))
                self._shot(page, tag + "_top")
                self._shot(page, tag + "_slope", ".slope-fig")
                self._shot(page, tag + "_units", "#unit-chart")
                for sec in ("what", "caption", "ports", "effects", "fair", "next"):
                    self._shot(page, tag + "_" + sec, "#" + sec)
                self._shot(page, tag + "_how", "figure.how")
                self.assertEqual(errors, [])

    def test_scrolling_switches_the_price_chart_to_cost_per_success(self):
        for tag, w, h, scheme in VIEWS:
            with self.subTest(view=tag):
                page, errors = self._open(w, h, scheme)
                page.wait_for_selector("#price-chart g.pt")
                self.assertEqual(page.locator("#price-chart .ylabel").text_content(), "pass@1")
                # Into the step trigger band: the middle tenth of the screen on
                # a desktop, 78-88% of the way down on a phone.
                band = 0.47 if w >= 900 else 0.80
                page.evaluate("""f => { const r = document.querySelector('.step[data-step="3"]')
                    .getBoundingClientRect();
                    window.scrollBy(0, r.top - window.innerHeight * f); }""", band)
                page.wait_for_timeout(1200)
                self.assertIn("Cost per working extractor",
                              page.locator("#price-chart .ylabel").text_content())
                self.assertEqual(page.locator("#price-chart .shelf-lbl").count(), 1)
                self.assertEqual(page.evaluate(OFF_SCREEN), [])
                self._shot(page, tag + "_step3")
                self.assertEqual(errors, [])

    def test_without_javascript_the_tables_are_one_link_away(self):
        page, errors = self._open(390, 844, "light", js=False)
        self.assertTrue(page.locator("noscript a[href='tables.html']").first.is_visible())
        self.assertFalse(page.locator("details.data").first.is_visible())
        self.assertEqual(errors, [])

    def test_the_tables_page_fits_a_phone(self):
        page, errors = self._open(390, 844, "dark", path="tables.html")
        for tid in ("t-price", "t-rank", "t-draws", "t-ports", "t-effects", "t-settings",
                    "t-wall"):
            self.assertEqual(page.locator("table#%s" % tid).count(), 1)
        self.assertFalse(page.evaluate(H_OVERFLOW))
        self._shot(page, "phone_tables")
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
