# -*- coding: utf-8 -*-
"""The portal population run's test portals, as the arms and the checker
see them: each portal's reference (`data/population/reference/`), its
stripped pages, the excerpt the arms are shown and the check.

Moved here from `scripts/population_eval.py` on 2026-10-27 so the runner
and the reference checker (`scripts/population_check.py`) read the portals
the same way.
"""
import glob
import os

from permits import fileio
from permits import harness as H
from permits.agent import tools as T
from permits.agent import verify
from permits.arms import SYNTH_WINDOW

POP = os.path.join(H.ROOT, "data", "population")
REFS = os.path.join(POP, "reference")
PAGES = os.path.join(POP, "corpus", "pages")
# Where the runner keeps the check's workspaces.
EVAL = os.path.join(POP, "eval")


class Portal:
    """One test portal: its reference, stripped pages, excerpt and check."""

    def __init__(self, path):
        d = fileio.read_json(path)
        self.order, self.place = int(d["order"]), d["place"]
        self.product, self.source = d["product"], d["source"]
        self.key = "p%04d" % self.order
        self.target = H.Target(self.key, self.key, self.product, None,
                               {f: f for f in sorted(d["fields"])},
                               self.place, split="test")
        raw = [(p["file"], os.path.join(PAGES, p["file"])) for p in d["pages"]]
        self.corpus = [q for _, q in H.stripped_corpus(self.target, raw)]
        self.refs = {p["file"]: p["rows"] for p in d["pages"]}
        bad = [nm for nm, ok in H.validate_scorer(self.target,
                                                  d["pages"][0]["rows"])
               if not ok]
        if bad:
            raise SystemExit("scorer broken for %s: %s; no calls made"
                             % (self.key, ", ".join(bad)))
        self.expected = verify.expected_records(
            [H.read(q) for q in self.corpus])
        self.window, _frac, _at = H.window(H.read(raw[0][1]), SYNTH_WINDOW)
        self.user = ("Portal page excerpt (one page of the result grid, "
                     "stripped of scripts, styles and non-structural "
                     "attributes):\n\n" + self.window)
        self._ws = None

    @property
    def loaded(self):
        return self.target, self.corpus, self.refs, self.user

    def counts(self):
        """Records per page in the reference."""
        return [len(self.refs[os.path.basename(q)]) for q in self.corpus]

    def in_window(self):
        """Reference records of the first page whose permit number is in
        the excerpt: an excerpt with none shows the model no record."""
        rows = self.refs[os.path.basename(self.corpus[0])]
        return sum(1 for r in rows if r["native_id"] in self.window), len(rows)

    def check(self, path):
        """The check's verdict on a module on disk: (accepted, what failed)."""
        if self._ws is None:
            self._ws = T.Workspace(self.corpus,
                                   os.path.join(EVAL, "work", "check", self.key),
                                   expected=list(self.expected))
        res = self._ws.run(H.read(path))
        failed = sorted(res.failed)
        if res.audit:
            failed.append("audit")
        if res.error:
            failed.append("error")
        return res.accepted, failed


def load_portals(orders=None):
    out = []
    for f in sorted(glob.glob(os.path.join(REFS, "ref_*.json"))):
        p = Portal(f)
        if orders is None or p.order in orders:
            out.append(p)
    return out
