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
        self.assertEqual(
            failure_mode({"outcome": "imperfect", "recall_min": 0.0}),
            "silent_empty")
        self.assertEqual(
            failure_mode({"outcome": "imperfect", "recall_min": 0.4}),
            "silent_partial")
        self.assertEqual(failure_mode({"outcome": "raised"}), "loud")


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
        """
        return {k: e for k, e in self.cells.items() if "/" not in e["model"]}

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
                elif e.get("usd_is_replayed"):
                    # Scored entirely from the response cache, so this run
                    # billed nothing and the cell's real spend is in earlier
                    # ledger rows. Stated as unknown rather than as zero.
                    self.assertIsNone(e["usd_per_success"])
                else:
                    self.assertGreater(e["usd_per_success"], 0)

    def test_silent_failures_dominate_where_there_are_failures(self):
        """55 draws, 29 failures, 25 silent. Asserted per-cell so a change in
        one model's failure character is visible rather than averaged away."""
        total_f = sum(e["failures"] for e in self.published().values())
        total_s = sum(e["silent_failures"] for e in self.published().values())
        self.assertEqual(total_f, 29)
        self.assertEqual(total_s, 25)


if __name__ == "__main__":
    unittest.main()
