# -*- coding: utf-8 -*-
"""Before the agent run spends anything on Polk County and Oregon: is the
instrument sound on the two held-back portals? No model calls.

    python spikes/heldout_selfcheck.py

Both were fetched and their references hand-checked for the v2 run, then
held back unspent (v2 pre-registration, "Targets"). The agent run's
pre-registration uses them as fresh test portals, so before it is written
this checks, per portal, with the code the run will use:

- the corpus: pages and reference records, as the pre-registration states
  (4 pages and 40 records each);
- the scorer's self-check (`harness.validate_scorer`, the gate
  `scripts/agent_eval.py` runs before any call) on every page, not only the
  first;
- the excerpt a model is shown (`harness.window` at 24,000 characters, the
  v2 setting): how many reference records it holds, and whether the
  header fallback fired;
- the verifier's expected row count (`verify.expected_rows`, its rule fixed
  on the development portals) against the reference count on every page,
  and the four checks on the reference's own output, which must pass;
- which contract fields the reference leaves empty on every row, so a
  verifier note about empty columns is read against what the page prints.

Nothing here reads a model's output on these portals; none exists.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from permits import harness as H                             # noqa: E402
from permits.agent import verify                             # noqa: E402

TARGETS = ("polkco", "oregon")
WINDOW = 24000


def main():
    bad = 0
    for key in TARGETS:
        t = H.TARGETS[key]
        pages = H.corpus(t)
        html = [H.read(p) for _, p in pages]
        refs = [t.reference(h) for h in html]
        print("== %s (%s)" % (key, t.label))
        print("  pages %d, reference records %d (per page %s)"
              % (len(pages), sum(len(r) for r in refs),
                 [len(r) for r in refs]))
        for (fn, _), r in zip(pages, refs, strict=True):
            fails = [nm for nm, ok in H.validate_scorer(t, r) if not ok]
            bad += bool(fails)
            print("  scorer self-check %-36s %s" % (fn, "ok" if not fails
                                                     else "FAILED: %s" % fails))
        win, frac, at = H.window(html[0], WINDOW)
        ids = [H.norm(r.get(t.roles["native_id"])) for r in refs[0]]
        shown = sum(1 for i in ids if i and i in win)
        print("  excerpt: %d chars from char %s (%.0f%% of page 1); "
              "holds %d of %d page-1 records"
              % (len(win), at, 100 * frac, shown, len(ids)))
        print("  nested caption table (Clark's trap) in the excerpt: %s"
              % ("aca_gridview_caption" in win))
        stripped = [H.read(q) for _, q in H.stripped_corpus(t, pages)]
        exp = verify.expected_rows(stripped)
        match = [e == len(r) for e, r in zip(exp, refs, strict=True)]
        bad += not all(match)
        print("  verifier expected rows %s against reference %s: %s"
              % (exp, [len(r) for r in refs],
                 "match" if all(match) else "MISMATCH"))
        as_model = [[{role: r.get(col) for role, col in t.roles.items()}
                     for r in rr] for rr in refs]
        failed = set()
        for rows, e in zip(as_model, exp, strict=True):
            failed |= verify.check_page(rows, e)
        bad += bool(failed)
        print("  verifier checks on the reference's output: %s"
              % ("all pass" if not failed else "FAILED: %s" % sorted(failed)))
        print("  contract fields empty on every reference row: %s"
              % (verify.empty_fields(as_model, list(t.roles)) or "none"))
    print("\n%s" % ("all checks pass" if not bad else "%d problems" % bad))


if __name__ == "__main__":
    main()
