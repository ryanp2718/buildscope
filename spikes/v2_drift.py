# -*- coding: utf-8 -*-
"""Template drift on the v2 run's working extractors. No model calls.

    python spikes/v2_drift.py

The repair-under-drift experiment in the backlog starts each episode from an
extractor a page change broke. This finds them: every v2 draw scored
perfect is re-run on its portal's first 5 pages under each of the drift
mutations of `scripts/conformance.py` (`MUTATORS`, the v1 drift report's
set), scored against the adapter's parse of the clean page, as `--drift`
scores. A mutation whose control fails (it loses a reference record) is
not scored.

It is also the v1 drift question asked of v2: of extractors that worked,
how many survive each change.

Writes `data/infer/drift_v2.json`, one entry per (draw, mutation), keyed by
the extractor's content hash so a re-run only runs what is new. It does not
touch `data/infer/drift.json`, which holds the v1 drift figures that
`scripts/model_stats.py` reads. Mutated pages go to a temporary directory.
"""
import collections
import hashlib
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import conformance as cf                                     # noqa: E402
from permits import fileio, rollup, sandbox                  # noqa: E402

OUT = os.path.join(ROOT, "data", "infer", "drift_v2.json")
TARGETS = ("clarkco", "stjohns", "santabarbara")
PAGES = 5


def sha(path):
    with io.open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()[:16]


def mutated(target, pages, refs, tmp):
    """Per mutation: stripped mutated pages on disk, or None when the
    mutation's control failed."""
    out = {}
    for name, fn in cf.MUTATORS:
        d = os.path.join(tmp, target.key, name)
        os.makedirs(d, exist_ok=True)
        paths, lost = [], 0
        for f, q in pages:
            m = fn(cf.read(q))
            lost += cf.faithful(target, refs[f], m)[0]
            p = os.path.join(d, f)
            with io.open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(cf.strip(m))
            paths.append(p)
        out[name] = None if lost else paths
        print("  %-14s %s" % (name, "control failed: %d ids lost" % lost
                              if lost else "ok"), flush=True)
    return out


def main():
    v = fileio.read_json(os.path.join(ROOT, "data", "infer", "variance.json"))
    old = {}
    if os.path.exists(OUT):
        old = {(e["cell"], e["draw"], e["mutation"]): e
               for e in fileio.read_json(OUT)}
    tmp = tempfile.mkdtemp(prefix="drift_v2_")
    entries = []
    for key in TARGETS:
        target = cf.TARGETS[key]
        pages = cf.corpus(target)[:PAGES]
        refs = {f: target.reference(cf.read(q)) for f, q in pages}
        print("== %s: %d pages" % (key, len(pages)), flush=True)
        muts = mutated(target, pages, refs, tmp)
        for ckey, cell in sorted(v["cells"].items()):
            if cell["target"] != key or "v2" not in rollup.condition(cell):
                continue
            for d in rollup.draws_of(cell):
                if d.outcome != "perfect" or not d.source \
                        or (ckey, d.draw) in rollup.EXCLUDED:
                    continue
                h = sha(d.source)
                for name, paths in muts.items():
                    if paths is None:
                        continue
                    prev = old.get((ckey, d.draw, name))
                    if prev and prev.get("sha") == h:
                        entries.append(prev)
                        continue
                    res, err = sandbox.run_synth(d.source, paths, tmp,
                                                 runner_name="_drift_v2.py")
                    e = {"cell": ckey, "draw": d.draw, "model": d.model,
                         "target": key, "mutation": name, "sha": h}
                    if err:
                        e.update(survived=False, error=err[:200])
                    else:
                        sc = []
                        for item, (f, _) in zip(res, pages, strict=True):
                            if not item["ok"]:
                                sc.append({"recall": 0.0, "precision": 0.0,
                                           "error": True})
                            else:
                                sc.append(cf.score(target, refs[f],
                                                   item["rows"]))
                        e.update(survived=cf.perfect(sc),
                                 recall_min=min(s["recall"] or 0.0
                                                for s in sc),
                                 raised=sum(1 for s in sc if s.get("error")))
                    entries.append(e)
                print("  %-48s d%02d done" % (ckey, d.draw), flush=True)
    fileio.atomic_write(OUT, json.dumps(entries, indent=1) + "\n",
                        newline="\n")
    report(entries)


def report(entries):
    by_mut = collections.defaultdict(lambda: [0, 0])
    by_model = collections.defaultdict(lambda: [0, 0])
    for e in entries:
        by_mut[(e["target"], e["mutation"])][0] += e["survived"]
        by_mut[(e["target"], e["mutation"])][1] += 1
        by_model[(e["target"], e["model"])][0] += e["survived"]
        by_model[(e["target"], e["model"])][1] += 1
    print("\nsurvival by target and mutation (perfect extractors that stay "
          "perfect)")
    for (t, m), (k, n) in sorted(by_mut.items()):
        print("  %-13s %-14s %4d / %-4d %.2f" % (t, m, k, n, k / n))
    print("\nsurvival by target and model, over all mutations")
    for (t, m), (k, n) in sorted(by_model.items()):
        print("  %-13s %-32s %4d / %-4d %.2f" % (t, m, k, n, k / n))
    broken = sum(1 for e in entries if not e["survived"])
    print("\n%d (draw, mutation) pairs, %d broken: the repair experiment's "
          "starting pool" % (len(entries), broken))


if __name__ == "__main__":
    main()
