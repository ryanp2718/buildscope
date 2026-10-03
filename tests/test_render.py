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
# Where the opening's replay button sits on the page, and its size.
HERO_BTN = """() => { const r = document.getElementById('hero-replay').getBoundingClientRect();
    return [r.x, r.y + window.scrollY, r.width, r.height]; }"""

OFF_SCREEN = """() => [...document.querySelectorAll(`#hero-chart text, #price-chart text,
    #slope-chart text, #ports-chart text, #effects-chart text, #bo5-chart text, #wall-chart text`)]
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
    cap = (data.get("exploratory") or {}).get("caption") or {}
    best = ((data.get("exploratory") or {}).get("best_of_5") or {}).get("cells", [])
    bo5 = sum(1 for c in best if c["arm"] == "baseline" and c["protocol"] == "v2"
              and c["model"] in points)
    hero = [d for d in data["draws"] if d["draw"] < 10
            and d["cell"] in {"clarkco|%s|v2" % m for m in points}]
    passed = sum(1 for d in hero if d["outcome"] == "perfect")
    return {"points": len(points), "squares": squares, "held": len(held),
            "ports": ports, "contrasts": len(data.get("contrasts", [])),
            "wall": len(data.get("wall", [])), "rescued": cap.get("rows_back"),
            "bo5": bo5, "hero": len(hero), "hero_passed": passed}


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

    def _open(self, w, h, scheme, js=True, path="index.html", motion="reduce"):
        """With `motion="reduce"` (the default) every figure is drawn in its
        finished state at once, which is what the counts and screenshots
        want; the scene test turns motion on."""
        ctx = self.browser.new_context(viewport={"width": w, "height": h},
                                       color_scheme=scheme, java_script_enabled=js,
                                       reduced_motion=motion)
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
                self.assertEqual(page.locator("#bo5-chart g.bo-cell").count(), self.want["bo5"])
                self.assertEqual(page.locator("#hero-chart rect:not(.hx-page)").count(),
                                 self.want["hero"])
                self.assertEqual(page.locator("#hero-chart rect.hx-slot").count(), 0)
                self.assertEqual(page.locator("#hero-tally b").first.text_content(),
                                 str(self.want["hero_passed"]))
                self.assertEqual(page.locator("[data-table] table").count(), 8)
                # With motion off the replay button is invisible but keeps its
                # place, so turning motion on shifts nothing.
                self.assertEqual(page.evaluate("""() => { const b = document.getElementById('hero-replay');
                    return [getComputedStyle(b).visibility, b.offsetWidth > 0]; }"""), ["hidden", True])
                # Leader lines are dotted, unlike the solid interval bars.
                self.assertEqual(page.evaluate("""() => [...document.querySelectorAll('#price-chart line.leader')]
                    .filter(l => getComputedStyle(l).strokeDasharray === 'none').length"""), 0)
                if w >= 900:
                    page.evaluate("document.querySelectorAll('details.data').forEach(d => d.open = true)")
                    self.assertEqual(page.evaluate("""() => [...document.querySelectorAll('details.data .scroll')]
                        .filter(s => s.querySelector('#t-settings') && s.scrollWidth > s.clientWidth + 1)
                        .length"""), 0)
                    page.evaluate("document.querySelectorAll('details.data').forEach(d => d.open = false)")
                # Every number the prose fills in was filled.
                self.assertEqual(page.evaluate(
                    "[...document.querySelectorAll('[data-q]')].filter(e => !e.textContent.trim())"
                    ".map(e => e.dataset.q)"), [])
                self.assertEqual(page.evaluate(OFF_SCREEN), [])
                self.assertFalse(page.evaluate(H_OVERFLOW))
                self._shot(page, tag + "_top")
                self._shot(page, tag + "_slope", ".slope-fig")
                self._shot(page, tag + "_units", "#unit-chart")
                for sec in ("what", "caption", "ports", "effects", "select", "fair", "next"):
                    self._shot(page, tag + "_" + sec, "#" + sec)
                self._shot(page, tag + "_how", "figure.how")
                self.assertEqual(errors, [])

    def test_scrolling_switches_the_price_chart_to_cost_per_success(self):
        for tag, w, h, scheme in VIEWS:
            with self.subTest(view=tag):
                page, errors = self._open(w, h, scheme)
                page.wait_for_selector("#price-chart g.pt")
                self.assertEqual(page.locator("#price-chart .ylabel").text_content(), "pass@1")
                self._to_step(page, w, "price", 3)
                page.wait_for_timeout(1200)
                self.assertIn("Cost per working extractor",
                              page.locator("#price-chart .ylabel").text_content())
                self.assertEqual(page.locator("#price-chart .shelf-lbl").count(), 1)
                self.assertEqual(page.evaluate(OFF_SCREEN), [])
                self._shot(page, tag + "_step3")
                self.assertEqual(errors, [])

    @staticmethod
    def _to_step(page, w, scene, i):
        """Scroll step `i` of `scene` into the trigger band: the middle tenth
        of the screen on a desktop, 78-88% of the way down on a phone."""
        band = 0.47 if w >= 900 else 0.80
        page.evaluate("""([sel, f]) => { const r = document.querySelector(sel)
            .getBoundingClientRect();
            window.scrollBy(0, r.top - window.innerHeight * f); }""",
                      ['#%s .step[data-step="%d"]' % (scene, i), band])

    def _state(self, page, scene):
        return page.evaluate("s => document.getElementById(s).dataset.state", scene)

    def test_each_scene_plays_through_to_its_last_state(self):
        """With motion on, scroll every scene a step at a time and every
        entrance figure into view, and check each ends where it should."""
        for tag, w, h, scheme in VIEWS:
            with self.subTest(view=tag):
                page, errors = self._open(w, h, scheme, motion="no-preference")
                page.wait_for_selector("#slope-chart path.sl-line")
                page.evaluate("document.fonts.ready")

                # The opening replay runs while it is on screen and ends with
                # every draw landed and the tally complete. Its button reads
                # Skip, then Replay, and never moves or resizes.
                self.assertEqual(page.locator("#hero-replay").text_content(), "Skip")
                box = page.evaluate(HERO_BTN)
                page.wait_for_function(
                    "document.getElementById('hero-replay').textContent === 'Replay'", timeout=30000)
                for a, b in zip(box, page.evaluate(HERO_BTN), strict=True):
                    self.assertAlmostEqual(a, b, delta=0.5)
                self.assertEqual(page.locator("#hero-chart rect.hx-slot").count(), 0)
                self.assertEqual(page.locator("#hero-tally b").first.text_content(),
                                 str(self.want["hero_passed"]))
                self._shot(page, tag + "_scene_hero", "#hero")

                # A portal not yet shown answers no pointer: its marks sit
                # stacked under Clark's.
                self.assertEqual(page.evaluate("""() => [...document.querySelectorAll(
                    '#ports-chart .p-mark1, #ports-chart .p-mark2')]
                    .filter(m => getComputedStyle(m).pointerEvents !== 'none').length"""), 0)

                # The two rankings: the dots travel to the right-hand list.
                for i in range(3):
                    self._to_step(page, w, "rank", i)
                    page.wait_for_timeout(1700)
                    self.assertEqual(self._state(page, "rank"), str(i))
                self.assertEqual(page.locator("#slope-chart svg.emph").count(), 1)
                xs = page.evaluate("""() => [...document.querySelectorAll('#slope-chart g > g')]
                    .map(g => [g.querySelector('path.sl-line').getPointAtLength(1e9).x,
                               g.querySelectorAll('circle')[1].getCTM().e])""")
                self.assertEqual(len(xs), self.want["points"])
                for end, mover in xs:
                    self.assertAlmostEqual(end, mover, delta=1)
                self._shot(page, tag + "_scene_rank")

                # The caption table: the read stops with no rows, then reaches
                # the permits once the small table is out, then the count.
                self._to_step(page, w, "cap-scene", 1)
                page.wait_for_timeout(2200)
                self.assertEqual(page.locator("#cap-rows").text_content(), "0")
                self._to_step(page, w, "cap-scene", 2)
                page.wait_for_timeout(4200)
                self.assertEqual(page.locator("#cap-rows").text_content(), "10")
                self._to_step(page, w, "cap-scene", 3)
                page.wait_for_timeout(2000)
                self.assertEqual(page.locator("#cap-count").text_content(),
                                 str(self.want["rescued"]))
                self.assertNotIn("off", page.locator("#cap-big").get_attribute("class"))
                self._shot(page, tag + "_scene_caption")

                # The three portals: every mark shown, the two named rows lit.
                for i in range(4):
                    self._to_step(page, w, "ports-scene", i)
                    page.wait_for_timeout(1600)
                    self.assertEqual(self._state(page, "ports-scene"), str(i))
                self.assertEqual(page.evaluate("""() => [...document.querySelectorAll(
                    '#ports-chart path.p-mark')].filter(m => +m.getAttribute('opacity') < 1).length"""),
                    0)
                self.assertEqual(page.locator("#ports-chart .p-row:not(.dim)").count(), 2)
                self._shot(page, tag + "_scene_ports")

                # Figures that play once on coming into view.
                for fig in ("unit-chart", "effects-chart", "bo5-chart", "wall-chart"):
                    page.locator("#" + fig).scroll_into_view_if_needed()
                    page.wait_for_timeout(4000)
                    self.assertEqual(page.evaluate(
                        "s => document.getElementById(s).dataset.played", fig), "1")
                self.assertEqual(page.evaluate("""() => [...document.querySelectorAll(
                    `#unit-chart rect, #effects-chart .ef-head, #effects-chart .ef-zero,
                     #bo5-chart .ef-head, #bo5-chart .ef-zero`)]
                    .filter(m => +m.getAttribute('opacity') < 1).length"""), 0)
                self.assertEqual(page.evaluate("""() => [...document.querySelectorAll(
                    '#wall-chart circle')].filter(m => +m.getAttribute('opacity') < 0.8).length"""), 0)
                self.assertEqual(page.evaluate(OFF_SCREEN), [])
                self.assertFalse(page.evaluate(H_OVERFLOW))
                self.assertEqual(errors, [])

    def test_reduced_motion_is_the_default_and_the_switch_overrides_it(self):
        """Under the system's reduced-motion setting the page starts still and
        says why; the header's switch turns motion on, and the opening
        replay starts at once."""
        page, errors = self._open(1280, 860, "light")
        page.wait_for_selector("#hero-chart rect")
        self.assertTrue(page.evaluate("document.documentElement.classList.contains('still')"))
        self.assertEqual(page.locator("#motion").text_content(), "Turn animations on")
        self.assertIn("reduced motion", page.locator("#motion-why").text_content())
        self.assertEqual(page.locator("#hero-chart rect.hx-slot").count(), 0)
        page.locator("#motion").click()
        page.wait_for_timeout(600)
        self.assertFalse(page.evaluate("document.documentElement.classList.contains('still')"))
        self.assertEqual(page.locator("#motion").get_attribute("aria-pressed"), "true")
        self.assertGreater(page.locator("#hero-chart rect.hx-slot").count(), 0)
        self.assertEqual(page.locator("#hero-replay").text_content(), "Skip")
        page.locator("#hero-replay").click()
        self.assertEqual(page.locator("#hero-chart rect.hx-slot").count(), 0)
        self.assertEqual(page.locator("#hero-replay").text_content(), "Replay")
        page.locator("#hero-replay").click()
        self.assertGreater(page.locator("#hero-chart rect.hx-slot").count(), 0)
        page.locator("#motion").click()
        self.assertEqual(page.locator("#hero-chart rect.hx-slot").count(), 0)
        self.assertEqual(page.evaluate(
            "getComputedStyle(document.getElementById('hero-replay')).visibility"), "hidden")
        self.assertEqual(errors, [])

    def test_without_javascript_the_tables_are_one_link_away(self):
        page, errors = self._open(390, 844, "light", js=False)
        self.assertTrue(page.locator("noscript a[href='tables.html']").first.is_visible())
        self.assertFalse(page.locator("details.data").first.is_visible())
        self.assertEqual(errors, [])

    def test_the_tables_page_fits_a_phone(self):
        page, errors = self._open(390, 844, "dark", path="tables.html")
        for tid in ("t-price", "t-rank", "t-draws", "t-ports", "t-effects", "t-best",
                    "t-settings", "t-wall"):
            self.assertEqual(page.locator("table#%s" % tid).count(), 1)
        self.assertFalse(page.evaluate(H_OVERFLOW))
        self._shot(page, "phone_tables")
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
