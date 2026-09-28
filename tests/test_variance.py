"""Tests for the variance experiment and the injected-drift eval.

Both of these measure something, so both of them can be wrong in the quiet
way an instrument is wrong: by reporting a clean number that means nothing.
The tests here are aimed at exactly that.

Two properties are load-bearing and neither is obvious from reading the
code.

The first is that the *replay cache must not answer a variance experiment*.
Replay exists so a finished experiment re-runs for nothing, and it works by
hashing the request. k draws of one cell are k identical requests, so a cache
that did its normal job would return one answer k times and the experiment
would report zero variance at full confidence - a broken instrument whose
output looks like an excellent result. The draw index is therefore mixed into
the key and kept out of the body, and `draw=0` still has to hash exactly as
it did before the index existed or every response already paid for is
orphaned.

The second is that *a mutation must not delete records*. The drift eval is
free precisely because the adapter's parse of the clean page stays the right
answer after mutation. A mutation that dropped rows would make every
extractor look catastrophically brittle, and the number would be an artifact
of the mutator. `faithful()` is that control, and these tests check the
control itself against a mutation built to fail it.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from permits import infer                                     # noqa: E402

GRID = """<html><body>
<table id="ctl00_Main_gdvPermits" class="grid">
<tr class="hdr"><th>Permit No</th><th>Address</th><th>Issue Dt</th></tr>
<tr class="row"><td>B24-001</td><td>1 MAIN ST</td><td>01/02/2026</td></tr>
<tr class="alt"><td>B24-002</td><td>2 OAK AVE</td><td>01/03/2026</td></tr>
</table></body></html>"""


class TestDrawIsInTheKeyAndNotTheRequest(unittest.TestCase):
    """The cache must not be allowed to answer a variance experiment."""

    def setUp(self):
        import tempfile
        self.c = infer.Client(tempfile.mkdtemp(), 1.0, dry_run=True)
        self.body = self.c.build("claude-opus-5", "sys", "usr", 8000)

    def test_draw_zero_hashes_as_it_did_before_draws_existed(self):
        """Every response bought before this argument must still replay.

        If this fails, the experiment silently re-buys work already paid for.
        """
        self.assertEqual(self.c._key_for(self.body, 0),
                         self.c._key_for(self.body))

    def test_each_draw_gets_its_own_key(self):
        keys = [self.c._key_for(self.body, d) for d in range(12)]
        self.assertEqual(len(set(keys)), 12)

    def test_the_draw_index_never_reaches_the_wire(self):
        """It is a label on a sample, not part of the question asked."""
        import json
        for _d in (0, 1, 7):
            self.assertNotIn("draw", json.dumps(
                self.c.build("claude-opus-5", "s", "u", 8000)))

    def test_message_passes_the_draw_to_the_key(self):
        import inspect
        src = inspect.getsource(self.c.message)
        self.assertIn("self._key_for(body, draw)", src)


class TestThinkingPinsTemperature(unittest.TestCase):
    """Measured 2026-09-21: the API 400s on any temperature but 1.0 while
    extended thinking is on. Dropping the argument quietly would misreport
    the experiment as controlled sampling, so it is refused instead."""

    def setUp(self):
        import tempfile
        self.c = infer.Client(tempfile.mkdtemp(), 1.0, dry_run=True)

    def test_a_real_temperature_with_thinking_is_refused(self):
        for t in (0.0, 0.2, 0.7):
            self.assertRaises(infer.Refused, self.c.build,
                              "claude-opus-5", "s", "u", 8000, True, t)

    def test_refusal_is_not_an_api_error(self):
        """Nothing was sent, so nothing was billed. The distinction is the
        whole point of `Refused` being its own type."""
        self.assertFalse(issubclass(infer.Refused, infer.ApiError))

    def test_temperature_one_with_thinking_changes_no_bytes(self):
        """Writing the default in would rehash every prior request."""
        a = self.c.build("claude-opus-5", "s", "u", 8000, True)
        b = self.c.build("claude-opus-5", "s", "u", 8000, True, 1.0)
        self.assertEqual(a, b)
        self.assertNotIn("temperature", b)

    def test_temperature_without_thinking_is_sent(self):
        b = self.c.build("claude-opus-5", "s", "u", 8000, False, 0.0)
        self.assertEqual(b["temperature"], 0.0)


class TestWilson(unittest.TestCase):

    def setUp(self):
        import conformance
        self.w = conformance.wilson

    def test_known_values(self):
        lo, hi = self.w(2, 2)
        self.assertAlmostEqual(lo, 0.342, places=2)
        self.assertAlmostEqual(hi, 1.000, places=2)
        lo, hi = self.w(2, 3)
        self.assertAlmostEqual(lo, 0.208, places=2)
        self.assertAlmostEqual(hi, 0.939, places=2)

    def test_a_perfect_small_sample_is_not_certainty(self):
        """The reason every rate in this experiment carries an interval."""
        lo, _ = self.w(3, 3)
        self.assertLess(lo, 0.45)

    def test_interval_tightens_with_more_draws(self):
        wide = self.w(9, 10)
        narrow = self.w(90, 100)
        self.assertLess(narrow[1] - narrow[0], wide[1] - wide[0])

    def test_zero_draws_is_total_ignorance(self):
        self.assertEqual(self.w(0, 0), (0.0, 1.0))


class TestMutationsPreserveRecords(unittest.TestCase):
    """The control that makes the drift eval free, and a check on the
    control itself."""

    def setUp(self):
        import conformance
        self.C = conformance

    def test_every_mutation_keeps_every_record_id(self):
        for name, fn in self.C.MUTATORS:
            out = fn(GRID)
            for rid in ("B24-001", "B24-002"):
                self.assertIn(rid, out,
                              "%s deleted record %s" % (name, rid))

    def test_every_mutation_actually_changes_the_page(self):
        """A mutator that silently no-ops would report a fake survival."""
        for name, fn in self.C.MUTATORS:
            self.assertNotEqual(fn(GRID), GRID, "%s changed nothing" % name)

    def test_the_faithfulness_control_catches_a_deleting_mutation(self):
        """Negative control. Spike C's fingerprint got one of these; the
        stripper did not, and it deleted every Accela row marker."""
        class T(object):
            roles = {"native_id": "num"}
        lost, total = self.C.faithful(T(), [{"num": "B24-001"},
                                            {"num": "B24-002"}],
                                      GRID.replace("B24-002", "GONE"))
        self.assertEqual((lost, total), (1, 2))

    def test_the_faithfulness_control_passes_a_clean_page(self):
        class T(object):
            roles = {"native_id": "num"}
        lost, total = self.C.faithful(T(), [{"num": "B24-001"}], GRID)
        self.assertEqual((lost, total), (0, 1))

    def test_nested_table_reproduces_the_shape_that_broke_haiku(self):
        """A non-greedy </table> match closes on the inner table."""
        import re
        out = self.C.m_nested_table(GRID)
        self.assertGreater(out.count("</table>"), GRID.count("</table>"))
        m = re.search(r'(?is)<table[^>]*gdvPermits[^>]*>(.*?)</table>', out)
        self.assertIsNotNone(m)
        self.assertNotIn("B24-002", m.group(1))

    def test_id_suffix_moves_every_control_id(self):
        out = self.C.m_id_suffix(GRID)
        self.assertNotIn('id="ctl00_Main_gdvPermits"', out)
        self.assertIn("ctl99_", out)


class TestDriftHarnessIsolation(unittest.TestCase):

    def test_drift_uses_its_own_runner_file(self):
        """Two harnesses writing one runner path is a sharing violation on
        Windows, and it would kill whichever run is spending money."""
        import inspect
        import conformance
        self.assertIn('runner_name="_drift_runner.py"',
                      inspect.getsource(conformance.run_drift))
        self.assertIn("runner_name",
                      inspect.getsource(conformance.run_synth))


if __name__ == "__main__":
    unittest.main()


class TestTheHarnessDoesNotDecideTheAnswer(unittest.TestCase):
    """Three harness assumptions that held only because Claude was the sole
    caller, each found on 2026-09-24 by the first open-weight draws.

    All three point the same way - they turn a working extractor into a
    recorded failure - and all three would have landed hardest on the tier
    this experiment was widened to measure. A harness artifact that biases
    every cell in one direction is indistinguishable, in the published table,
    from a fact about the models.
    """

    def setUp(self):
        import conformance
        self.C = conformance

    def test_the_last_block_wins_not_the_first(self):
        """A model whose reasoning lands in `content` emits drafts first."""
        text = ("thinking about it\n\n```python\ndef extract(html):\n"
                "    pass  # first attempt\n```\n\n"
                "wait, that misses the header row\n\n"
                "```python\ndef extract(html):\n    return [1, 2, 3]\n```\n")
        src = self.C.extract_block(text, self.C.CODEBLOCK, "def extract(")
        self.assertIn("return [1, 2, 3]", src)
        self.assertNotIn("first attempt", src)

    def test_a_block_without_the_contract_does_not_win_on_position(self):
        text = ("```python\ndef extract(html):\n    return []\n```\n"
                "and to call it:\n\n```python\nrows = extract(page)\n```\n")
        src = self.C.extract_block(text, self.C.CODEBLOCK, "def extract(")
        self.assertIn("def extract", src)
        self.assertNotIn("rows = extract(page)", src)

    def test_unbalanced_fences_do_not_walk_out_of_phase(self):
        """The real failure: nine fences, one of them opening where a close
        was due, which reassigned the answer's closing fence to a sketch."""
        text = ("```python\nsketch = 1\n"
                "```python\ndef extract(html):\n    return ['real']\n```\n")
        blocks = self.C.fenced_blocks(text)
        self.assertGreaterEqual(len(blocks), 2)
        src = self.C.extract_block(text, self.C.CODEBLOCK, "def extract(")
        self.assertIn("'real'", src)

    def test_a_module_that_prints_is_not_an_execution_failure(self):
        """The runner reports by writing JSON to stdout, so a stray print in
        generated code corrupted the channel and the draw was recorded as
        "runner produced no JSON" - a formatting habit scored as an
        extraction error."""
        import io
        import tempfile
        d = tempfile.mkdtemp()
        src = os.path.join(d, "noisy.py")
        page = os.path.join(d, "p.html")
        with io.open(page, "w", encoding="utf-8") as fh:
            fh.write("<html></html>")
        with io.open(src, "w", encoding="utf-8") as fh:
            fh.write("print('loading')\n"
                     "def extract(html):\n"
                     "    print('parsing')\n"
                     "    return [{'native_id': 'A1'}]\n"
                     "print('demo:', extract(''))\n")
        res, err = self.C.run_synth(src, [page],
                                    runner_name="_test_runner.py", runner_dir=d)
        self.assertIsNone(err)
        self.assertTrue(res[0]["ok"])
        self.assertEqual(res[0]["rows"], [{"native_id": "A1"}])

    def test_a_non_list_return_is_a_failure_not_a_clean_zero(self):
        """`None` would crash the scorer and a dict would iterate its keys,
        match nothing and report a confident zero."""
        import io
        import tempfile
        for body, name in (("    return None\n", "NoneType"),
                           ("    return {'a': 1}\n", "dict")):
            d = tempfile.mkdtemp()
            src = os.path.join(d, "bad.py")
            page = os.path.join(d, "p.html")
            with io.open(page, "w", encoding="utf-8") as fh:
                fh.write("<html></html>")
            with io.open(src, "w", encoding="utf-8") as fh:
                fh.write("def extract(html):\n" + body)
            res, err = self.C.run_synth(src, [page],
                                        runner_name="_test_runner.py", runner_dir=d)
            self.assertIsNone(err)
            self.assertFalse(res[0]["ok"])
            self.assertIn(name, res[0]["error"])
