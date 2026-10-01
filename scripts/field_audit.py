# -*- coding: utf-8 -*-
"""Field agreement for every v2 draw scored perfect. No model calls.

    python scripts/field_audit.py

A draw is scored `perfect` when, on every page, the set of permit numbers
it returns equals the adapter's (v2 pre-registration, deviation 4). The
scorer also compares every other field of each matched record, but the
outcome does not depend on it, and `variance.json` keeps only the record
figures. This re-runs each perfect draw's stored extractor on its target's
stripped corpus, scores it with the same `harness.score`, and keeps the
per-field disagreement counts.

Writes `data/infer/verifier/field_audit.json`, one entry per perfect draw:

  cell, draw, target, model
  ids_still_perfect   the re-run agrees with the stored outcome
  disagree            per field, matched records whose values differ
  compared            per field, matched records where either side has one
  examples            up to three disagreements, adapter beside model
  sha                 the extractor's content hash

`rollup.field_perfect` reads an entry: the draw passes and also agrees on
every field of every matched record. `scripts/export_results.py` reports it
beside pass@1 as field-level pass@1, and `scripts/agent_eval.py` beside its
best-of-k figures. An entry whose extractor is unchanged is kept, so a
re-run only runs new draws.
"""
import collections
import hashlib
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from permits import fileio, harness as H, rollup, sandbox    # noqa: E402

OUT = os.path.join(H.OUT, "verifier", "field_audit.json")
RUNNER_DIR = os.path.join(H.OUT, "verifier")


def sha(path):
    with io.open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()[:16]


def audit_draw(target, src, stripped, refs):
    """Score one extractor on every page, keeping field disagreements."""
    res, err = sandbox.run_synth(src, stripped, RUNNER_DIR,
                                 runner_name="_field_runner.py")
    if err:
        return {"error": err[:200]}
    disagree, compared = collections.Counter(), collections.Counter()
    still, examples = True, []
    for r, ref in zip(res, refs, strict=True):
        if not r["ok"]:
            still = False
            continue
        s = H.score(target, ref, r["rows"])
        if s["recall"] != 1.0 or s["precision"] != 1.0:
            still = False
        for f, v in s["fields"].items():
            compared[f] += v["compared"]
            disagree[f] += v["compared"] - v["agree"]
        examples += s["disagreements"][:2]
    return {"ids_still_perfect": still, "disagree": dict(disagree),
            "compared": dict(compared), "examples": examples[:3]}


def main():
    v = fileio.read_json(os.path.join(H.OUT, "variance.json"))
    old = {}
    if os.path.exists(OUT):
        old = {(e["cell"], e["draw"]): e for e in fileio.read_json(OUT)}
    corp, out, ran = {}, [], 0
    for key, cell in sorted(v["cells"].items()):
        if "v2" not in rollup.condition(cell):
            continue
        for d in rollup.draws_of(cell):
            if d.outcome != "perfect":
                continue
            h = sha(d.source)
            prev = old.get((key, d.draw))
            if prev and prev.get("sha") == h and "error" not in prev:
                out.append(prev)
                continue
            t = H.TARGETS[d.target]
            if t.key not in corp:
                pages = H.corpus(t)
                corp[t.key] = ([q for _, q in H.stripped_corpus(t, pages)],
                               [t.reference(H.read(p)) for _, p in pages])
            stripped, refs = corp[t.key]
            e = {"cell": key, "draw": d.draw, "target": t.key,
                 "model": d.model, "sha": h}
            e.update(audit_draw(t, d.source, stripped, refs))
            out.append(e)
            ran += 1
            print("%4d  %-48s d%02d  %s" % (
                len(out), key, d.draw,
                e.get("error") or sum(e["disagree"].values())), flush=True)
    fileio.atomic_write(OUT, json.dumps(out, indent=1) + "\n", newline="\n")

    ok = [e for e in out if "error" not in e]
    print("\nperfect v2 draws: %d (%d re-run now), errors %d, ids still "
          "perfect %d" % (len(out), ran, len(out) - len(ok),
                          sum(e["ids_still_perfect"] for e in ok)))
    for t in sorted({e["target"] for e in ok}):
        tt = [e for e in ok if e["target"] == t]
        print("  %-13s field-perfect %d of %d"
              % (t, sum(rollup.field_perfect(e) for e in tt), len(tt)))
    fields = collections.Counter(f for e in ok
                                 for f, n in e["disagree"].items() if n)
    print("  draws with a disagreement, by field: %s" % dict(fields))


if __name__ == "__main__":
    main()
