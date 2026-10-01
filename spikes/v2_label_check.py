# -*- coding: utf-8 -*-
"""Re-read every stored v2 reply with the current `extract_block` and list
the draws whose label changes. No model calls.

    python spikes/v2_label_check.py

Since 2026-10-01 `extract_block` returns nothing for a reply that never
contains `def extract(`, so the draw is `no_code` rather than handed to the
static audit and recorded as `refused` (docs/design/failure-cases.md, case
1). This checks that the change moves only those draws: each scored draw's
reply is found through the ledger row that bought it (`rollup.purchases`)
and its response id in the response cache, the block is re-read, and its
length is compared with the stored `bytes`.

Both labels are format failures and count the same way in pass@1 and on the
page ("loud" in `stats.failure_mode`), so no rate changes; the per-outcome
counts in the reports do.

Also lists every `refused` draw whose module does not parse, with the
line the parser stopped on (case 9).
"""
import ast
import collections
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from permits import fileio, infer, rollup, sandbox             # noqa: E402

INFER = os.path.join(ROOT, "data", "infer")


def replies():
    out = {}
    for f in glob.glob(os.path.join(INFER, "cache", "*.json")):
        try:
            d = fileio.read_json(f)
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and d.get("response_id"):
            out[d["response_id"]] = d.get("text") or ""
    return out


def main():
    v = fileio.read_json(os.path.join(INFER, "variance.json"))
    ledger = infer.Ledger(os.path.join(INFER, "ledger.jsonl")).rows()
    bought = rollup.purchases(v, ledger)
    text_of = replies()
    seen, missing, changed, unparsed = 0, [], [], []
    for key, cell in sorted(v["cells"].items()):
        if "v2" not in rollup.condition(cell):
            continue
        for d in rollup.draws_of(cell):
            if not d.scored():
                continue
            i = bought.get((key, d.draw))
            text = text_of.get(ledger[i].response_id) if i is not None else None
            if text is None:
                missing.append((key, d.draw))
                continue
            seen += 1
            src = sandbox.extract_block(text, sandbox.CODEBLOCK, "def extract(")
            if len(src) != (d.bytes or 0):
                changed.append((key, d.draw, d.outcome, len(src), d.bytes,
                                (d.audit_problems or [""])[0]))
            elif d.outcome == "refused" and src:
                try:
                    ast.parse(src)
                except SyntaxError as e:
                    line = src.splitlines()[e.lineno - 1].strip()
                    unparsed.append((key, d.draw, e.msg, e.lineno, line))

    print("scored v2 draws re-read: %d; reply not in the cache: %d"
          % (seen, len(missing)))
    for k, n in missing:
        print("  missing  %s  d%02d" % (k, n))

    print("\nlabel changes (stored bytes -> bytes now):")
    by = collections.Counter()
    for key, n, outcome, now, was, why in changed:
        new = "no_code" if now == 0 else "?"
        by[(outcome, new)] += 1
        print("  %-48s d%02d  %s -> %s  (%s -> %d)  %s"
              % (key, n, outcome, new, was, now, why[:60]))
    for (a, b), c in sorted(by.items()):
        print("  %s -> %s: %d" % (a, b, c))

    print("\nrefused, module does not parse: %d" % len(unparsed))
    for key, n, msg, ln, line in unparsed:
        print("  %-40s d%02d  line %d: %s\n      %s"
              % (key, n, ln, msg, line[:110]))


if __name__ == "__main__":
    main()
