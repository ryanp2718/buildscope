# -*- coding: utf-8 -*-
"""The export the results page reads.

`scripts/export_results.py` writes the only data the page sees, so the page
can be no more right than this: the cells it exports must be the ones the
stats roll-up computes, a re-run must not move a number, a cell that never
worked must not be given a cost per success, and nothing private in `data/`
may leave in the file.

Synthetic stores throughout, except the last class, which checks the file on
disk when there is one.
"""
import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "spikes"))

import export_results                                         # noqa: E402
from permits import infer, rollup                             # noqa: E402

M = "tencent/hy3"          # on the roster
V1 = "qwen/qwen3-coder"    # a v1 model re-run under v2
DATA = os.path.join(ROOT, "site", "results", "data.json")


def _draw(i, out, perfect, model=M, target="clarkco", host="H"):
    return {"draw": i, "model": model, "target": target,
            "output_tokens": out, "cached": False, "bytes": 100,
            "truncated": False, "usd": 0.01, "host": host,
            "source": "C:\\private\\%s_d%02d.py" % (target, i),
            "outcome": "perfect" if perfect else "imperfect",
            "recall_min": 1.0 if perfect else 0.0}


def _buy(i, out, usd=0.01, model=M, target="clarkco"):
    return infer.LedgerRow(
        at="2026-09-28T00:00:%02dZ" % i, call_class="synthesis",
        tag="%s/var" % target, model=model, provider="openrouter", draw=i,
        ok=True, usd=usd, seconds=2.0, stop_reason="end_turn",
        output_tokens=out, usd_reported=True)


def _cell(draws, model=M, target="clarkco", hint=False, protocol="v2"):
    c = {"target": target, "model": model, "synth_hint": hint,
         "detail": draws}
    if protocol != "v1":
        c["protocol"] = protocol
    return c


def _store():
    cells = {
        "clarkco|%s|v2" % M: _cell([_draw(0, 100, True), _draw(1, 200, False),
                                    _draw(2, 300, True)]),
        "clarkco|%s|hint|v2" % M: _cell([_draw(0, 400, False)], hint=True),
        # A v1 cell of a roster model: not part of the v1-to-v2 comparison.
        "clarkco|%s" % M: _cell([_draw(0, 500, True)], protocol="v1"),
        # A v1 baseline cell of a re-run model: kept.
        "clarkco|%s" % V1: _cell([_draw(0, 600, False, model=V1)],
                                 model=V1, protocol="v1"),
        # A v1 hint cell of a re-run model: not kept.
        "clarkco|%s|hint" % V1: _cell([_draw(0, 700, True, model=V1)],
                                      model=V1, hint=True, protocol="v1"),
        # A model not on the run.
        "clarkco|claude-opus-5": _cell([_draw(0, 800, True,
                                              model="claude-opus-5")],
                                       model="claude-opus-5", protocol="v1"),
    }
    ledger = [_buy(0, 100, 0.02), _buy(1, 200, 0.04), _buy(2, 300, 0.06),
              _buy(0, 400), _buy(0, 500), _buy(0, 600, model=V1),
              _buy(0, 700, model=V1), _buy(0, 800, model="claude-opus-5")]
    return {"cells": cells}, ledger


def _audit(cell, draw, disagree=0, still=True):
    return {"cell": cell, "draw": draw, "ids_still_perfect": still,
            "disagree": {"address": disagree, "status": 0},
            "compared": {"address": 10, "status": 10}, "examples": []}


class TestFieldsAndExclusions(unittest.TestCase):
    """Field-level pass@1 beside pass@1 (v2 pre-registration, deviation 4),
    and draws bought but left out of every figure (deviation 5)."""

    KEY = "clarkco|%s|v2" % M

    def test_field_level_pass_counts_perfect_draws_that_agree_on_every_field(self):
        v, ledger = _store()
        data = export_results.build(v, ledger, [_audit(self.KEY, 0),
                                                _audit(self.KEY, 2, 3)])
        c = {c["key"]: c for c in data["cells"]}[self.KEY]
        self.assertEqual((c["k"], c["k_field"], c["n"]), (2, 1, 3))
        self.assertAlmostEqual(c["rate_field"], 0.3333)
        self.assertAlmostEqual(c["usd_per_field_success"], 0.12)
        self.assertEqual([d["field_perfect"] for d in data["draws"]
                          if d["cell"] == self.KEY], [True, False, False])

    def test_a_perfect_draw_with_no_verdict_leaves_the_field_rate_unstated(self):
        v, ledger = _store()
        data = export_results.build(v, ledger, [_audit(self.KEY, 0)])
        c = {c["key"]: c for c in data["cells"]}[self.KEY]
        self.assertIsNone(c["k_field"])
        self.assertIsNone(c["rate_field"])
        self.assertIsNone(c["usd_per_field_success"])

    def test_a_rerun_that_lost_a_permit_number_is_not_field_perfect(self):
        self.assertFalse(rollup.field_perfect(_audit(self.KEY, 0, still=False)))
        self.assertIsNone(rollup.field_perfect({"cell": self.KEY, "draw": 0,
                                                "error": "timed out"}))

    def test_an_excluded_draw_is_outside_n_and_the_cost_and_listed_apart(self):
        from unittest import mock
        v, ledger = _store()
        with mock.patch.dict(rollup.EXCLUDED, {(self.KEY, 2): "late"}):
            data = export_results.build(v, ledger)
        c = {c["key"]: c for c in data["cells"]}[self.KEY]
        self.assertEqual((c["k"], c["n"], c["draws_excluded"]), (1, 2, 1))
        self.assertAlmostEqual(c["usd_total"], 0.06)
        self.assertEqual([d["draw"] for d in data["draws"]
                          if d["cell"] == self.KEY], [0, 1])
        self.assertEqual(data["excluded"], [{"cell": self.KEY, "draw": 2,
                                             "outcome": "perfect",
                                             "why": "late"}])

    def test_contrasts_are_hint_against_baseline_and_v2_against_v1(self):
        v, ledger = _store()
        v["cells"]["clarkco|%s|v2" % V1] = _cell(
            [_draw(i, 1000 + i, True, model=V1) for i in range(3)], model=V1)
        ledger += [_buy(i, 1000 + i, model=V1) for i in range(3)]
        cs = {(q["kind"], q["model"]): q
              for q in export_results.build(v, ledger)["contrasts"]}
        self.assertEqual(sorted(cs), [("config", V1), ("hint", M)])
        h = cs[("hint", M)]
        self.assertEqual((h["from"], h["to"]), ([2, 3], [0, 1]))
        c = cs[("config", V1)]
        self.assertEqual((c["from"], c["to"]), ([0, 1], [3, 3]))
        self.assertAlmostEqual(c["diff"][0], 1.0)
        self.assertEqual(c["claimed"], c["diff"][1] > 0)

    def test_the_wall_lists_every_call_of_its_model_by_how_it_ended(self):
        rows = [
            infer.LedgerRow(at="t", call_class="synthesis", tag="clarkco/var",
                            model=export_results.WALL_MODEL, provider="openrouter",
                            draw=0, ok=ok, usd=0.0, seconds=s, stop_reason=stop,
                            output_tokens=out, max_tokens=64000, protocol="v2",
                            host="H")
            for ok, s, stop, out in ((True, 50.0, "end_turn", 9000),
                                     (True, 301.2, None, 30000),
                                     (True, 900.0, "max_tokens", 32768),
                                     (True, 1200.0, "max_tokens", 64000),
                                     (False, 3600.0, None, 0))]
        self.assertEqual([w["what"] for w in export_results.wall(rows)], [
            "finished", "closed by the host",
            "stopped by the host below the cap", "reached the output cap",
            "failed with no output"])

    def test_the_excluded_draws_are_the_ones_deviation_5_names(self):
        self.assertEqual(
            sorted(rollup.EXCLUDED),
            [("stjohns|z-ai/glm-5.3|v2", d) for d in (2, 3, 4)])


class TestRoster(unittest.TestCase):

    def test_the_roster_is_the_one_the_preregistration_published(self):
        import preregister_v2_run as pre
        ids = [pre.LEDGER_ID.get(mid, mid) for _, _, mid, _ in pre.ROSTER]
        self.assertEqual(export_results.ROSTER, ids)
        self.assertEqual(export_results.V1_RERUN, pre.BRIDGE)


class TestExport(unittest.TestCase):

    def setUp(self):
        self.v, self.ledger = _store()
        self.data = export_results.build(self.v, self.ledger)
        self.cells = {c["key"]: c for c in self.data["cells"]}

    def test_only_the_run_is_exported(self):
        self.assertEqual(sorted(self.cells), sorted([
            "clarkco|%s|v2" % M, "clarkco|%s|hint|v2" % M,
            "clarkco|%s" % V1]))
        self.assertEqual(
            {d["cell"] for d in self.data["draws"]}, set(self.cells))

    def test_cells_are_the_stats_rollups_figures(self):
        rows = rollup.rows_from_variance(self.v, self.ledger)
        rows += rollup.rows_from_ledger(self.ledger)
        agg = rollup.aggregate(rows)
        for key, c in self.cells.items():
            e = agg[key]
            self.assertEqual((c["k"], c["n"]), (e["perfect"],
                                                e["draws_scored"]))
            self.assertEqual(c["ci95"], e["success_ci95"])
            self.assertAlmostEqual(c["usd_total"], e["usd_total"])
            self.assertEqual(c["usd_per_success"], e["usd_per_success"])

    def test_cost_is_what_the_draws_cost_to_buy(self):
        c = self.cells["clarkco|%s|v2" % M]
        self.assertAlmostEqual(c["usd_per_draw"], 0.04)
        self.assertAlmostEqual(c["usd_per_success"], 0.06)
        self.assertEqual([d["usd"] for d in self.data["draws"]
                          if d["cell"] == c["key"]], [0.02, 0.04, 0.06])

    def test_arm_and_protocol_are_split_out(self):
        self.assertEqual(
            {k: (c["arm"], c["protocol"]) for k, c in self.cells.items()},
            {"clarkco|%s|v2" % M: ("baseline", "v2"),
             "clarkco|%s|hint|v2" % M: ("hint", "v2"),
             "clarkco|%s" % V1: ("baseline", "v1")})

    def test_a_cell_that_never_worked_has_no_cost_per_success(self):
        """It goes on the page's never-worked shelf, not at a price."""
        c = self.cells["clarkco|%s|hint|v2" % M]
        self.assertEqual(c["k"], 0)
        self.assertIsNone(c["usd_per_success"])
        self.assertIsNone(c["usd_per_success_range"])

    def test_the_range_brackets_the_point_estimate(self):
        c = self.cells["clarkco|%s|v2" % M]
        for prior in ("jeffreys", "uniform"):
            lo, mid, hi = c["usd_per_success_range"][prior]
            self.assertLess(lo, mid)
            self.assertLess(mid, hi)
            self.assertLess(lo, c["usd_per_success"])
            self.assertGreater(hi, c["usd_per_success"])

    def test_an_unpriced_draw_leaves_the_cost_unstated(self):
        v, ledger = _store()
        data = export_results.build(v, ledger[1:])   # draw 0's purchase lost
        c = {c["key"]: c for c in data["cells"]}["clarkco|%s|v2" % M]
        self.assertEqual(c["draws_unpriced"], 1)
        self.assertIsNone(c["usd_per_draw"])
        self.assertIsNone(c["usd_per_success"])
        self.assertIsNone(c["usd_per_success_range"])

    def test_a_rerun_writes_identical_bytes(self):
        again = export_results.build(*_store())
        self.assertEqual(export_results.render(self.data),
                         export_results.render(again))

    def test_a_new_cell_does_not_move_another_cells_range(self):
        v, ledger = _store()
        v["cells"]["stjohns|%s|v2" % M] = _cell(
            [_draw(0, 900, True, target="stjohns")], target="stjohns")
        ledger.append(_buy(0, 900, target="stjohns"))
        more = {c["key"]: c for c in export_results.build(v, ledger)["cells"]}
        key = "clarkco|%s|v2" % M
        self.assertEqual(more[key]["usd_per_success_range"],
                         self.cells[key]["usd_per_success_range"])

    def test_hosts_are_counted_per_cell(self):
        self.assertEqual(self.cells["clarkco|%s|v2" % M]["hosts"], {"H": 3})

    def test_no_source_or_local_path_leaves(self):
        text = export_results.render(self.data)
        self.assertNotIn("source", text)
        self.assertNotIn("private", text)


class TestBestOf5(unittest.TestCase):
    """Best-of-5 with the reference-free check rides along from the
    verifier's file: its condition split like a cell's, its `source` left
    behind."""

    @staticmethod
    def _k(p1, usd1, p5, usd5, oracle5):
        return {"1": {"success": p1, "usd_per_success": usd1, "pass_at_k": p1},
                "5": {"success": p5, "usd_per_success": usd5, "pass_at_k": oracle5}}

    def setUp(self):
        self.bok = {"source": "spikes/verifier_offline.py", "seed": 1, "orders": 2000, "cells": [
            {"target": "stjohns", "model": M, "condition": "v2", "n": 10, "perfect": 0,
             "k": self._k(0.0, None, 0.0, None, 0.0)},
            {"target": "clarkco", "model": M, "condition": "hint|v2", "n": 10, "perfect": 2,
             "k": self._k(0.21, 0.37, 0.78, 0.32, 0.78)}]}
        self.v, self.ledger = _store()

    def test_each_cell_carries_its_arm_protocol_and_rates(self):
        bo = export_results.build(self.v, self.ledger, bok=self.bok)["exploratory"]["best_of_5"]
        self.assertEqual([(c["target"], c["arm"], c["protocol"], c["k"], c["n"], c["best5"],
                           c["oracle5"], c["usd_per_success_5"]) for c in bo["cells"]],
                         [("clarkco", "hint", "v2", 2, 10, 0.78, 0.78, 0.32),
                          ("stjohns", "baseline", "v2", 0, 10, 0.0, 0.0, None)])
        self.assertEqual(bo["orders"], 2000)

    def test_the_source_stays_behind(self):
        text = export_results.render(export_results.build(self.v, self.ledger, bok=self.bok))
        self.assertNotIn('"source"', text)

    def test_without_the_file_there_is_no_best_of_5(self):
        self.assertNotIn("best_of_5", export_results.build(self.v, self.ledger)["exploratory"])

    def test_the_table_lists_baseline_cells_only(self):
        html = export_results.render_tables(export_results.build(self.v, self.ledger, bok=self.bok))
        best = html.split('id="t-best"')[1].split("</table>")[0]
        self.assertEqual(best.count("<tr>") - 1, 1)
        self.assertIn("0 of 10", best)


class TestNameClash(unittest.TestCase):
    """The draws that crash on the `html` parameter ride along from the
    spike's file as counts per cell: its `source`, and the per-draw rows
    that carry local paths, left behind."""

    def setUp(self):
        self.clash = {"source": "spikes/v2_name_clash.py", "v2_crashes": 3,
                      "draws": [{"path": "C:/private/data/infer/synth/x.py"}],
                      "crashes_by_cell": [
                          {"target": "stjohns", "model": M, "arm": "baseline", "protocol": "v2",
                           "crashes": 1, "pass_patched": 1},
                          {"target": "clarkco", "model": M, "arm": "baseline", "protocol": "v2",
                           "crashes": 2, "pass_patched": 0}]}
        self.v, self.ledger = _store()

    def test_counts_per_cell_and_nothing_else(self):
        nc = export_results.build(self.v, self.ledger, clash=self.clash)["exploratory"]["name_clash"]
        self.assertEqual([(c["target"], c["crashes"], c["pass_patched"]) for c in nc["cells"]],
                         [("clarkco", 2, 0), ("stjohns", 1, 1)])
        self.assertEqual(set(nc), {"cells", "producer"})

    def test_no_source_or_local_path_leaves(self):
        text = export_results.render(export_results.build(self.v, self.ledger, clash=self.clash))
        self.assertNotIn('"source"', text)
        self.assertNotIn("private", text)

    def test_without_the_file_there_is_no_name_clash(self):
        self.assertNotIn("name_clash", export_results.build(self.v, self.ledger)["exploratory"])


M2 = "xiaomi/mimo-v2.6-flash"


def _pair_store():
    """Three priced cells on one target and arm: M, cheap and always right;
    M2, dearer and right a third of the time; and V1 under v2, cheap and
    right at 2 of 3. One v1 cell of V1 (another protocol), one M hint cell
    that never worked, and one M2 cell of 2 draws."""
    v, ledger = {"cells": {}}, []

    def add(key, model, outcomes, usd, target="clarkco", hint=False,
            protocol="v2"):
        v["cells"][key] = _cell(
            [_draw(i, 100 + i, ok, model=model, target=target)
             for i, ok in enumerate(outcomes)],
            model=model, target=target, hint=hint, protocol=protocol)
        ledger.extend(_buy(i, 100 + i, usd, model=model, target=target)
                      for i in range(len(outcomes)))

    add("clarkco|%s|v2" % M, M, [True] * 6, 0.01)
    add("clarkco|%s|v2" % M2, M2, [True, False, False] * 2, 0.05)
    add("clarkco|%s|v2" % V1, V1, [True, True, False], 0.01)
    add("clarkco|%s" % V1, V1, [True, True, True], 0.01, protocol="v1")
    add("clarkco|%s|hint|v2" % M, M, [False] * 3, 0.01, hint=True)
    add("stjohns|%s|v2" % M2, M2, [True, True], 0.01, target="stjohns")
    return v, ledger


class TestPairs(unittest.TestCase):

    def setUp(self):
        self.v, self.ledger = _pair_store()
        self.pairs = export_results.build(self.v, self.ledger)["pairs"]
        self.by = {(p["a"], p["b"]): p for p in self.pairs}

    def test_only_cells_with_a_cost_per_success_are_paired(self):
        """Same target, arm and protocol; no cell that never worked, and
        none under the report's 3 draws."""
        self.assertEqual(sorted(self.by), sorted([(M, M2), (M, V1), (V1, M2)]))
        self.assertTrue(all((p["target"], p["arm"], p["protocol"])
                            == ("clarkco", "baseline", "v2")
                            for p in self.pairs))

    def test_the_cheaper_at_the_point_estimate_comes_first(self):
        for p in self.pairs:
            for prior in ("jeffreys", "uniform"):
                self.assertGreaterEqual(p["p_a_cheaper"][prior], 0.5)
                self.assertGreaterEqual(p["ratio"][prior][1], 1.0)

    def test_settled_needs_both_priors(self):
        for p in self.pairs:
            self.assertEqual(p["settled"],
                             min(p["p_a_cheaper"].values()) >= 0.975)
        # Fifteen times cheaper per success at the point estimate, on 6 and 6
        # draws: settled. 1.5 times, on 6 and 3: not.
        self.assertTrue(self.by[(M, M2)]["settled"])
        self.assertFalse(self.by[(M, V1)]["settled"])

    def test_the_ratio_range_brackets_its_median(self):
        for p in self.pairs:
            for prior in ("jeffreys", "uniform"):
                lo, mid, hi = p["ratio"][prior]
                self.assertLess(lo, mid)
                self.assertLess(mid, hi)

    def test_a_new_cell_does_not_move_an_existing_pair(self):
        v, ledger = _pair_store()
        m3 = "openai/gpt-6-luna"
        v["cells"]["clarkco|%s|v2" % m3] = _cell(
            [_draw(i, 900 + i, True, model=m3) for i in range(3)], model=m3)
        ledger.extend(_buy(i, 900 + i, model=m3) for i in range(3))
        more = {(p["a"], p["b"]): p
                for p in export_results.build(v, ledger)["pairs"]}
        self.assertEqual(len(more), 6)
        self.assertEqual(more[(M, M2)], self.by[(M, M2)])


class TestTables(unittest.TestCase):
    """tables.html: the page without JavaScript, and the source of its
    "Show the data" tables, which the page finds by id."""

    def setUp(self):
        self.v, self.ledger = _pair_store()
        self.data = export_results.build(self.v, self.ledger)
        self.html = export_results.render_tables(self.data)

    def test_every_model_on_the_run_has_a_display_name(self):
        self.assertEqual(set(export_results.NAMES),
                         set(export_results.ROSTER) | set(export_results.V1_RERUN))

    def test_the_page_finds_each_table_by_id(self):
        for tid in ("t-price", "t-rank", "t-draws", "t-best"):
            self.assertEqual(self.html.count('<table id="%s">' % tid), 1)

    def test_one_price_row_per_roster_cell_on_clark(self):
        price = self.html.split('id="t-price"')[1].split("</table>")[0]
        self.assertEqual(price.count("<tr>") - 1, 2)      # header + M, M2
        self.assertIn("6 of 6", price)

    def test_a_cell_that_never_worked_is_listed_without_a_cost(self):
        v, ledger = _pair_store()
        for d in v["cells"]["clarkco|%s|v2" % M2]["detail"]:
            d["outcome"], d["recall_min"] = "imperfect", 0.0
        html = export_results.render_tables(export_results.build(v, ledger))
        row = html.split('<th scope="row">MiMo V2.6 Flash</th>')[1].split("</tr>")[0]
        self.assertIn("0 of 6", row)
        self.assertIn("none passed", row)

    def test_only_settled_rankings_are_listed(self):
        rank = self.html.split('id="t-rank"')[1].split("</table>")[0]
        settled = [p for p in self.data["pairs"] if p["settled"]
                   and p["a"] != V1 and p["b"] != V1]
        self.assertEqual(rank.count("<tr>") - 1, len(settled))

    def test_a_rerun_writes_identical_bytes(self):
        again = export_results.render_tables(export_results.build(*_pair_store()))
        self.assertEqual(self.html, again)

    def test_no_source_or_local_path_leaves(self):
        self.assertNotIn("private", self.html)
        self.assertIsNone(re.search(r"[A-Za-z]:\\\\|/Users/|/home/", self.html))


@unittest.skipUnless(os.path.exists(DATA), "no exported data.json")
class TestTheExportedFile(unittest.TestCase):
    """The file that would be published, whatever run it came from."""

    def setUp(self):
        with open(DATA, encoding="utf-8") as fh:
            self.text = fh.read()
        self.data = json.loads(self.text)

    def test_nothing_private_is_in_it(self):
        self.assertIsNone(re.search(r"[A-Za-z]:\\\\|/Users/|/home/", self.text))
        self.assertIsNone(re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", self.text))
        self.assertNotIn('"source"', self.text)

    def test_every_draw_belongs_to_an_exported_cell(self):
        keys = {c["key"] for c in self.data["cells"]}
        self.assertTrue(all(d["cell"] in keys for d in self.data["draws"]))

    def test_every_cell_is_of_a_model_on_the_run(self):
        ids = {m["id"] for m in self.data["models"]}
        self.assertTrue(all(c["model"] in ids for c in self.data["cells"]))

    def test_every_pair_is_of_two_exported_cells_that_worked(self):
        cells = {(c["target"], c["arm"], c["protocol"], c["model"]): c
                 for c in self.data["cells"]}
        for p in self.data.get("pairs", []):
            g = (p["target"], p["arm"], p["protocol"])
            a, b = cells[(*g, p["a"])], cells[(*g, p["b"])]
            self.assertTrue(a["k"] and b["k"])
            self.assertLessEqual(a["usd_per_success"], b["usd_per_success"])

    def test_draw_counts_match_their_cells(self):
        scored = {}
        for d in self.data["draws"]:
            if d["outcome"] not in ("infra_error", "not_attempted"):
                scored[d["cell"]] = scored.get(d["cell"], 0) + 1
        for c in self.data["cells"]:
            self.assertEqual(scored.get(c["key"], 0), c["n"], c["key"])


if __name__ == "__main__":
    unittest.main()
