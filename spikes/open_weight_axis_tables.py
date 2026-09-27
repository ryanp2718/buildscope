# -*- coding: utf-8 -*-
"""Every table in docs/evidence/2026-09-25-open-weight-model-axis.md.

Reads data/infer/model_stats.json (run scripts/model_stats.py first) and
data/infer/variance.json, and re-runs the stored Clark extractors to say which
records each failing draw misses. No model calls.

    python spikes/open_weight_axis_tables.py
"""
import collections
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import conformance as C                          # noqa: E402
from permits import infer                        # noqa: E402
from permits.cells import DrawRecord             # noqa: E402
from permits.stats import failure_mode           # noqa: E402

OUT = os.path.join(ROOT, "data", "infer")


def load(name):
    with io.open(os.path.join(OUT, name), encoding="utf-8") as fh:
        return json.load(fh)


def cells_table(stats):
    print("\n## per cell (model_stats.json)")
    print("%-9s %-22s %-8s %3s %3s %6s %-16s %9s %10s"
          % ("target", "model", "cond", "n", "k", "rate", "95% CI", "spend",
             "$/success"))
    for key in sorted(stats):
        e = stats[key]
        print("%-9s %-22s %-8s %3d %3d %5.0f%% [%.3f, %.3f] %9.4f %10s"
              % (e["target"], infer.short_model(e["model"]), e["condition"],
                 e["draws_scored"], e["perfect"],
                 100 * (e["success_rate"] or 0), e["success_ci95"][0],
                 e["success_ci95"][1], e["usd_total"],
                 "%.6f" % e["usd_per_success"]
                 if e["usd_per_success"] else "undefined"))


def clark_regimes(v):
    """Outcome counts, failure modes, and mean recall/precision over the
    draws whose extractor ran on every page."""
    print("\n## clarkco outcomes and failure modes")
    print("%-34s %3s %4s %5s %6s %7s %7s %8s %8s"
          % ("cell", "n", "perf", "loud", "empty", "partial", "format",
             "recall", "prec"))
    for key, cell in sorted(v["cells"].items()):
        if not key.startswith("clarkco|"):
            continue
        modes = collections.Counter()
        ran = []
        for d in cell["detail"]:
            if d.get("outcome") == "not_attempted":
                continue
            m = failure_mode(DrawRecord.from_dict(d))
            # `refused` and `no_code` are the model breaking the output
            # contract - no top-level extract(), or no code at all - which is
            # neither a loud nor a silent extraction failure.
            if d.get("outcome") in ("refused", "no_code"):
                m = "format"
            modes[m] += 1
            if "recall_mean" in d:
                ran.append(d)
        n = sum(modes.values())
        rec = (sum(d["recall_mean"] for d in ran) / len(ran)) if ran else None
        pre = (sum(d["precision_min"] for d in ran) / len(ran)) if ran else None
        print("%-34s %3d %4d %5d %6d %7d %7d %8s %8s"
              % (key[len("clarkco|"):], n, modes["perfect"], modes["loud"],
                 modes["silent_empty"], modes["silent_partial"],
                 modes["format"],
                 "-" if rec is None else "%.3f" % rec,
                 "-" if pre is None else "%.3f" % pre))


def clark_records(v):
    """Re-run each imperfect Clark extractor and name what it got wrong."""
    target = C.TARGETS["clarkco"]
    pages = C.corpus(target)
    refs = {fn: target.reference(C.read(p)) for fn, p in pages}
    corpus_pages = [q for _, q in C.stripped_corpus(target, pages)]
    print("\n## clarkco imperfect draws, per record")
    sigs = collections.Counter()
    empties = collections.Counter()
    for key, cell in sorted(v["cells"].items()):
        if not key.startswith("clarkco|"):
            continue
        for d in cell["detail"]:
            if d.get("outcome") != "imperfect":
                continue
            res, err = C.run_synth(d["source"], corpus_pages)
            if err:
                print("%-34s d%02d  runner error: %s" % (key, d["draw"], err))
                continue
            missed, spurious, rows, keyless = [], 0, 0, 0
            for i in res:
                sc = C.score(target, refs[os.path.basename(i["page"])],
                             i["rows"])
                missed += [(os.path.basename(i["page"]), k)
                           for k in sc["missed"]]
                spurious += sc["n_spurious"]
                rows += len(i["rows"])
                keyless += sum(1 for r in i["rows"]
                               if not isinstance(r, dict)
                               or not C.norm(r.get("native_id")))
            if not d.get("recall_min"):
                # A zero-recall draw either returned no rows, or returned
                # rows with no usable id - the second looks like output.
                kind = "no rows" if rows == 0 else "rows without ids"
                empties[(key, kind)] += 1
                continue
            ids = tuple(sorted({k for _, k in missed}))
            sigs[(len(missed), ids, spurious)] += 1
            print("%-34s d%02d  missed %d  spurious %d  %s"
                  % (key[len("clarkco|"):], d["draw"], len(missed), spurious,
                     ", ".join(ids)))
    print("\n  signatures (count, (missed instances, ids, spurious)):")
    for sig, n in sigs.most_common():
        print("   %2d  %s" % (n, sig))
    print("\n  zero-recall draws:")
    for (key, kind), n in sorted(empties.items()):
        print("   %-34s %-18s %d" % (key[len("clarkco|"):], kind, n))


def main():
    stats = load("model_stats.json")["cells"]
    v = load("variance.json")
    cells_table(stats)
    clark_regimes(v)
    clark_records(v)


if __name__ == "__main__":
    main()
