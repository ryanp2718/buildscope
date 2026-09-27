# -*- coding: utf-8 -*-
"""Atomic writes and locks on the harness's shared files (audit step 4).

The races are between processes, so the concurrency tests start real ones.
"""
import io
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from permits import fileio, infer  # noqa: E402


def _spawn(code, *args):
    return subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(code), *args],
        cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
        env=dict(os.environ, PYTHONPATH=ROOT))


class TestAtomicWrite(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "entry.json")

    def test_a_write_cut_off_leaves_the_old_file_whole(self):
        fileio.atomic_write(self.path, '{"old": 1}')
        with mock.patch.object(os, "fsync", side_effect=OSError("power cut")):
            with self.assertRaises(OSError):
                fileio.atomic_write(self.path, '{"new": 2, "half')
        self.assertEqual(fileio.read_json(self.path), {"old": 1})
        self.assertEqual(os.listdir(self.dir), ["entry.json"])

    def test_the_cache_store_is_atomic(self):
        c = infer.Client(self.dir, 1.0, api_key="", openrouter_key="",
                         dry_run=True)
        with mock.patch.object(infer.fileio, "atomic_write") as w:
            c._store("k", {"text": "x"})
        self.assertEqual(w.call_args[0][0],
                         os.path.join(c.cache_dir, "k.json"))


class TestUpdateJson(unittest.TestCase):

    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "variance.json")

    def test_an_unreadable_file_raises_rather_than_being_emptied(self):
        """`save_variance` used to read a corrupt file as `{}` and write one
        cell over every other."""
        with io.open(self.path, "w", encoding="utf-8") as fh:
            fh.write('{"cells": {"a": 1')
        with self.assertRaises(ValueError):
            fileio.update_json(self.path, lambda d: {"cells": {"b": 2}})
        with io.open(self.path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), '{"cells": {"a": 1')

    def test_concurrent_writers_keep_each_others_updates(self):
        """Two processes merging different cells into one file: without the
        lock one read-merge-write overwrites the other's."""
        code = """
            import sys
            from permits import fileio
            path, who = sys.argv[1], sys.argv[2]
            def add(i):
                def merge(d):
                    d.setdefault("cells", {})["%s-%d" % (who, i)] = i
                    return d
                return merge
            for i in range(25):
                fileio.update_json(path, add(i))
            """
        ps = [_spawn(code, self.path, w) for w in ("a", "b")]
        for p in ps:
            _, err = p.communicate(timeout=120)
            self.assertEqual(p.returncode, 0, err)
        self.assertEqual(len(fileio.read_json(self.path)["cells"]), 50)


class TestRunLock(unittest.TestCase):

    def test_a_second_run_of_a_cell_is_refused_at_once(self):
        path = os.path.join(tempfile.mkdtemp(), "locks", "cell.lock")
        holder = _spawn("""
            import sys
            from permits import fileio
            with fileio.run_lock(sys.argv[1], "cell x"):
                print("held", flush=True)
                sys.stdin.readline()
            """, path)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "held")
            with self.assertRaises(fileio.Busy) as ctx:
                with fileio.run_lock(path, "cell x"):
                    pass
            self.assertIn("Nothing was sent", str(ctx.exception))
        finally:
            holder.communicate("\n", timeout=60)
        # Released when the holder is done.
        with fileio.run_lock(path, "cell x"):
            pass


class TestLedgerAppends(unittest.TestCase):

    def test_concurrent_appends_stay_whole_lines(self):
        path = os.path.join(tempfile.mkdtemp(), "ledger.jsonl")
        code = """
            import sys
            from permits import infer
            led = infer.Ledger(sys.argv[1])
            for i in range(100):
                led.write(infer.LedgerRow(
                    at="t", call_class="c", tag=sys.argv[2] * 400, model="m",
                    provider="openrouter", draw=i, ok=True, usd=0.0,
                    seconds=0.0, stop_reason="stop", usd_reported=True))
            """
        ps = [_spawn(code, path, w) for w in ("a", "b")]
        for p in ps:
            _, err = p.communicate(timeout=120)
            self.assertEqual(p.returncode, 0, err)
        rows = infer.Ledger(path).rows()
        self.assertEqual(len(rows), 200)


if __name__ == "__main__":
    unittest.main()
