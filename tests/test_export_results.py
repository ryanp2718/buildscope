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

    def test_draw_counts_match_their_cells(self):
        scored = {}
        for d in self.data["draws"]:
            if d["outcome"] not in ("infra_error", "not_attempted"):
                scored[d["cell"]] = scored.get(d["cell"], 0) + 1
        for c in self.data["cells"]:
            self.assertEqual(scored.get(c["key"], 0), c["n"], c["key"])


if __name__ == "__main__":
    unittest.main()
