# -*- coding: utf-8 -*-
"""The statistics roll-up, and the figures it publishes.

`scripts/model_stats.py` is now the only place a per-model rate is computed.
That makes it the kind of module ADR-0016 says to pin: every number in
`docs/evidence/2026-09-22-cost-per-success.md` comes out of it, and a silent
change to the aggregation would change a published figure without anything
failing.

The rates asserted here were computed independently by
`scripts/conformance.py --variance-report` and `--drift` before this module
existed. They agreeing is the check; if the roll-up is edited and these move,
write a new dated report rather than editing the numbers.
"""
import io
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from permits import infer                                     # noqa: E402
from permits.cells import DrawRecord, Outcome                 # noqa: E402
from permits.stats import failure_mode, pctile, wilson       # noqa: E402

STATS = os.path.join(ROOT, "data", "infer", "model_stats.json")


class TestEstimators(unittest.TestCase):

    def test_wilson_does_not_report_certainty_from_three_draws(self):
        """The reason every rate in this project carries an interval."""
        lo, hi = wilson(3, 3)
        self.assertLess(lo, 0.5)
        self.assertEqual(hi, 1.0)

    def test_wilson_is_defined_at_zero_and_at_n(self):
        self.assertEqual(wilson(0, 0), (0.0, 1.0))
        for x, n in ((0, 20), (20, 20)):
            lo, hi = wilson(x, n)
            self.assertGreaterEqual(lo, 0.0)
            self.assertLessEqual(hi, 1.0)

    def test_pctile_returns_an_observed_value_never_an_invented_one(self):
        vs = [1.0, 2.0, 3.0, 100.0]
        for q in (0.5, 0.95, 1.0):
            self.assertIn(pctile(vs, q), vs)

    def test_pctile_ignores_missing_observations(self):
        self.assertEqual(pctile([None, 5.0, None], 0.5), 5.0)

    def test_an_empty_result_is_silent_not_loud(self):
        """The distinction the whole failure taxonomy rests on: a module that
        returns `[]` does not stop a pipeline."""
        def d(outcome, recall_min=None):
            return DrawRecord(0, "m/x", "clarkco", Outcome(outcome),
                              recall_min=recall_min)
        self.assertEqual(failure_mode(d("imperfect", 0.0)), "silent_empty")
        self.assertEqual(failure_mode(d("imperfect", 0.4)), "silent_partial")
        self.assertEqual(failure_mode(d("raised")), "loud")


def _draw(i, out, perfect, cached=False, usd=0.01):
    return {"draw": i, "model": "m/x", "target": "clarkco",
            "output_tokens": out, "cached": cached, "bytes": 100,
            "truncated": False,
            "usd": 0.0 if cached else usd,
            "outcome": "perfect" if perfect else "imperfect",
            "recall_min": 1.0 if perfect else 0.0}


def _buy(i, out, usd=0.01, model="m/x"):
    return infer.LedgerRow(
        at="2026-09-26T00:00:00Z", call_class="synthesis", tag="clarkco/var",
        model=model, provider="openrouter", draw=i, ok=True, usd=usd,
        seconds=1.0, stop_reason="end_turn", output_tokens=out,
        usd_reported=True)


class TestCellsAreConditions(unittest.TestCase):
    """Synthetic store, so these hold whatever the live data says.

    Written after the roll-up grouped on (target, model): the hinted glm-5.2
    draws landed in the baseline cell and turned 0/10 into 1/15, and the
    cell's cost summed every variance call the model had ever made."""

    def run_stats(self, cells, ledger):
        import model_stats
        v = {"cells": cells}
        rows = (model_stats.rows_from_variance(v, ledger)
                + model_stats.rows_from_ledger(ledger))
        return model_stats, model_stats.aggregate(rows)

    def cell(self, draws, hint=False):
        return {"target": "clarkco", "model": "m/x", "synth_hint": hint,
                "detail": draws}

    def test_a_hinted_cell_does_not_pool_into_its_baseline(self):
        _, agg = self.run_stats(
            {"clarkco|m/x": self.cell([_draw(0, 100, False),
                                       _draw(1, 200, False)]),
             "clarkco|m/x|hint": self.cell([_draw(0, 300, True)], hint=True)},
            [_buy(0, 100), _buy(1, 200), _buy(0, 300)])
        self.assertEqual(sorted(agg), ["clarkco|m/x", "clarkco|m/x|hint"])
        self.assertEqual(agg["clarkco|m/x"]["perfect"], 0)
        self.assertEqual(agg["clarkco|m/x"]["draws_scored"], 2)
        self.assertIsNone(agg["clarkco|m/x"]["usd_per_success"])
        self.assertEqual(agg["clarkco|m/x|hint"]["usd_total"], 0.01)

    def test_a_redrawn_draw_costs_both_attempts(self):
        """The cut-off attempt was paid for, so it is part of the cell's
        cost, and it is not left over as an unclaimed purchase."""
        d = dict(_draw(0, 900, True, usd=0.03), redraw_max_tokens=128000,
                 truncated_output_tokens=640)
        ledger = [_buy(0, 640, usd=0.02), _buy(0, 900, usd=0.03)]
        ms, agg = self.run_stats({"clarkco|m/x": self.cell([d])}, ledger)
        e = agg["clarkco|m/x"]
        self.assertEqual((e["usd_total"], e["draws_redrawn"],
                          e["draws_unpriced"]), (0.05, 1, 0))
        self.assertEqual(ms.unclaimed({"cells": {"clarkco|m/x":
                                                 self.cell([d])}}, ledger),
                         [])

    def test_a_redrawn_draw_missing_its_first_purchase_is_unpriced(self):
        d = dict(_draw(0, 900, True), redraw_max_tokens=128000,
                 truncated_output_tokens=640)
        _, agg = self.run_stats({"clarkco|m/x": self.cell([d])},
                                [_buy(0, 900)])
        self.assertEqual(agg["clarkco|m/x"]["draws_unpriced"], 1)
        self.assertIsNone(agg["clarkco|m/x"]["usd_per_success"])

    def test_a_replayed_draw_is_priced_at_what_it_cost_to_buy(self):
        _, agg = self.run_stats(
            {"clarkco|m/x": self.cell([_draw(0, 100, True, cached=True)])},
            [_buy(0, 100, usd=0.05)])
        e = agg["clarkco|m/x"]
        self.assertEqual(e["usd_this_run"], 0.0)
        self.assertEqual(e["usd_per_success"], 0.05)
        self.assertTrue(e["usd_is_replayed"])

    def test_superseded_and_duplicate_purchases_are_not_a_cells_cost(self):
        """An earlier ceiling's draw 0 and a second purchase of draw 1 were
        both paid for; neither produced a response this cell was scored on."""
        ledger = [_buy(0, 16000, usd=0.08),     # older, lower ceiling
                  _buy(1, 7563, usd=0.015),     # bought twice concurrently
                  _buy(0, 4415, usd=0.01),
                  _buy(1, 7831, usd=0.015)]     # the one the cache kept
        cells = {"clarkco|m/x": self.cell([_draw(0, 4415, True, cached=True),
                                           _draw(1, 7831, False,
                                                 cached=True)])}
        ms, agg = self.run_stats(cells, ledger)
        self.assertAlmostEqual(agg["clarkco|m/x"]["usd_total"], 0.025)
        self.assertEqual(ms.unclaimed({"cells": cells}, ledger), [0, 1])

    def test_a_draw_with_no_purchase_row_makes_the_cost_unstated(self):
        """Half a bill over the full success count would understate it."""
        _, agg = self.run_stats(
            {"clarkco|m/x": self.cell([_draw(0, 100, True, cached=True),
                                       _draw(1, 200, True, cached=True)])},
            [_buy(0, 100)])
        self.assertEqual(agg["clarkco|m/x"]["draws_unpriced"], 1)
        self.assertIsNone(agg["clarkco|m/x"]["usd_per_success"])


class TestPublishedCellStatistics(unittest.TestCase):
    """Pinned figures. These fail when a measurement changes, which is the
    point - the failure is the reminder to write a new evidence report."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(STATS):
            raise unittest.SkipTest(
                "no model_stats.json; run scripts/model_stats.py")
        with io.open(STATS, encoding="utf-8") as fh:
            cls.cells = json.load(fh)["cells"]

    def cell(self, target, model):
        return self.cells["%s|%s" % (target, model)]

    def published(self):
        """The cells the 2026-09-21 report describes: the Anthropic ones.

        The aggregates below pin that report's totals, and a second provider
        adds cells to the same store, so summing everything would make each
        new open-weight draw fail a test about a finished experiment. Scoping
        by provider keeps the guardrail pointed at what it was written to
        guard - a change in the Claude numbers still fails here - and the
        open-weight run gets its own pinned figures when it is published.
        The same holds for protocol v2 cells of the Claude models, which the
        step 6 run adds, so the report's cells are also the baseline ones.
        """
        return {k: e for k, e in self.cells.items()
                if "/" not in e["model"] and e["condition"] == "baseline"}

    def test_success_rates_match_the_variance_experiment(self):
        expected = {
            ("stjohns", "claude-haiku-4-5-20251001"): (15, 15),
            ("stjohns", "claude-sonnet-5"): (5, 5),
            ("clarkco", "claude-opus-5"): (3, 3),
            ("clarkco", "claude-sonnet-5"): (2, 12),
            ("clarkco", "claude-haiku-4-5-20251001"): (1, 20),
        }
        for (target, model), (k, n) in expected.items():
            with self.subTest(target=target, model=model):
                e = self.cell(target, model)
                self.assertEqual(e["perfect"], k)
                self.assertEqual(e["draws_scored"], n)

    def test_fifty_five_draws_in_total(self):
        self.assertEqual(
            sum(e["draws_scored"] for e in self.published().values()), 55)

    def test_cost_per_success_inverts_the_price_list_on_the_hard_page(self):
        """The finding this module was written to expose.

        Opus 5 bills 5x Haiku 4.5 per token and is the cheaper model per
        *working extractor* on Accela, because Haiku succeeds once in twenty.
        A per-call cost comparison cannot see this, and a per-call comparison
        is what the project reported until 2026-09-22.
        """
        haiku = self.cell("clarkco", "claude-haiku-4-5-20251001")
        opus = self.cell("clarkco", "claude-opus-5")
        self.assertLess(opus["usd_per_success"], haiku["usd_per_success"])
        self.assertGreater(haiku["usd_per_success"] / opus["usd_per_success"],
                           2.0)

    def test_the_ordering_reverses_on_the_easy_page(self):
        """And it must, or the finding would be 'Opus is always cheaper',
        which is not what was measured. Page difficulty decides."""
        haiku = self.cell("stjohns", "claude-haiku-4-5-20251001")
        sonnet = self.cell("stjohns", "claude-sonnet-5")
        self.assertLess(haiku["usd_per_success"], sonnet["usd_per_success"])

    def test_every_rate_carries_an_interval(self):
        for name, e in self.cells.items():
            with self.subTest(cell=name):
                self.assertEqual(len(e["success_ci95"]), 2)
                self.assertLessEqual(e["success_ci95"][0],
                                     e["success_rate"])
                self.assertGreaterEqual(e["success_ci95"][1],
                                        e["success_rate"])

    def test_a_cell_that_never_succeeded_reports_no_cost_per_success(self):
        """Dividing a bill by zero successes is how a broken cell gets
        quoted as free."""
        for name, e in self.cells.items():
            with self.subTest(cell=name):
                if e["perfect"] == 0:
                    self.assertIsNone(e["usd_per_success"])
                else:
                    # Positive even when this run billed nothing. A cell
                    # re-scored against the response cache is free to repeat
                    # and was not free to buy, so the denominator is what the
                    # cell's draws cost, joined from the ledger rows that
                    # bought them.
                    self.assertGreater(e["usd_per_success"], 0)
                    self.assertEqual(e["draws_unpriced"], 0)
                    self.assertGreaterEqual(e["usd_total"],
                                            e["usd_this_run"])

    def test_silent_failures_dominate_where_there_are_failures(self):
        """55 draws, 29 failures, 25 silent. Asserted per-cell so a change in
        one model's failure character is visible rather than averaged away."""
        total_f = sum(e["failures"] for e in self.published().values())
        total_s = sum(e["silent_failures"] for e in self.published().values())
        self.assertEqual(total_f, 29)
        self.assertEqual(total_s, 25)


class TestOpenWeightAxisFigures(unittest.TestCase):
    """Pinned figures for docs/evidence/2026-09-25-open-weight-model-axis.md.

    That report's front matter said it was pinned before anything pinned it,
    and its tables went stale in exactly the way that allows: kimi-k2-thinking
    stayed at 0/2 in two sections after the cell had reached 2/10. If one of
    these moves, the report is out of date."""

    # (target, model, condition): (perfect, scored, $/success or None)
    CELLS = {
        ("stjohns", "openai/gpt-oss-120b", "baseline"): (18, 20, 0.001016),
        ("stjohns", "qwen/qwen3.5-flash-02-23", "baseline"): (10, 20,
                                                              0.006789),
        ("stjohns", "qwen/qwen3-coder", "baseline"): (7, 20, 0.007514),
        ("clarkco", "moonshotai/kimi-k2-thinking", "baseline"): (2, 10,
                                                                 0.173813),
        ("clarkco", "deepseek/deepseek-v4-flash", "baseline"): (1, 10,
                                                                0.05662),
        ("clarkco", "z-ai/glm-5.3-flash", "baseline"): (2, 10, 0.014129),
        ("clarkco", "deepseek/deepseek-v4-pro", "baseline"): (0, 10, None),
        ("clarkco", "z-ai/glm-5.2", "baseline"): (0, 10, None),
        ("clarkco", "openai/gpt-oss-120b", "baseline"): (0, 20, None),
        ("clarkco", "qwen/qwen3-coder", "baseline"): (0, 20, None),
        ("clarkco", "qwen/qwen3.5-flash-02-23", "baseline"): (0, 20, None),
        ("clarkco", "z-ai/glm-5.2", "hint"): (1, 5, 0.136135),
        ("clarkco", "z-ai/glm-5.3-flash", "hint"): (2, 5, 0.006224),
        ("clarkco", "deepseek/deepseek-v4-flash", "hint"): (0, 5, None),
    }

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(STATS):
            raise unittest.SkipTest(
                "no model_stats.json; run scripts/model_stats.py")
        with io.open(STATS, encoding="utf-8") as fh:
            cls.cells = json.load(fh)["cells"]

    def test_cells_match_the_report(self):
        for (target, model, cond), (k, n, per) in self.CELLS.items():
            name = "%s|%s" % (target, model) + (
                "" if cond == "baseline" else "|" + cond)
            with self.subTest(cell=name):
                e = self.cells[name]
                self.assertEqual((e["perfect"], e["draws_scored"]), (k, n))
                if per is None:
                    self.assertIsNone(e["usd_per_success"])
                else:
                    self.assertAlmostEqual(e["usd_per_success"], per,
                                           places=6)

    def test_opus_is_not_the_only_model_to_solve_clark(self):
        """The claim the report carried, and R1 in the 2026-09-26 audit."""
        solved = sorted(e["model"] for e in self.cells.values()
                        if e["target"] == "clarkco"
                        and e["condition"] == "baseline" and e["perfect"])
        self.assertEqual(len(solved), 6, solved)


if __name__ == "__main__":
    unittest.main()
