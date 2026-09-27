# -*- coding: utf-8 -*-
"""Every office identity in every data artifact, checked against the frame.

ADR-0007 makes `(state_fips, bps_id)` the office identity, assigned from
`data/frame/bps_frame.csv` and never from a name, a FIPS place or a portal
domain. This is the check that makes that enforceable rather than aspirational.

Two rules, and the second is the one that matters:

  1. **A key must resolve.** `(state, bps_id)` names a row in the frame.
  2. **A key must agree with the name recorded beside it.** If an artifact
     carries both `12|633000` and "St. Johns County", one of them is wrong,
     and which one is not knowable from the artifact alone.

Rule 1 on its own is close to worthless here, which is the finding that
motivated this file. When `portals.csv` was audited, 21 of its 28 wrong ids
failed rule 1 loudly - but **7 passed it**, because they happened to name a
real office somewhere else in the same state. `12|633000` is Okeechobee County,
a genuine Florida office with genuine BPS rows and zero reported units. An
existence check is satisfied; a join succeeds; the answer is silently about a
different county. Rule 2 is the one that catches that, and it only works
because artifacts record the name alongside the key.

That is also the argument for why the name must keep being recorded even though
the key is the identity. The name is not the identity and must never be joined
on - but as a *redundant* field it is the only thing that makes the identity
falsifiable.

Known-wrong keys in dated artifacts are registered in `data/corrections.csv`
and reported separately rather than failing the run. A captured artifact is not
rewritten to make a checker pass; that is the history rewrite D1 exists to
prevent. The registry is how a wrong key stays visible and stays accounted for.

Exit status is 1 if any unregistered mismatch exists.
"""
import csv
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRAME = os.path.join(ROOT, "data", "frame", "bps_frame.csv")
CORRECTIONS = os.path.join(ROOT, "data", "corrections.csv")
DATA = os.path.join(ROOT, "data")

KEY = re.compile(r"^(\d{2})\|(\d{6})$")
NAME_KEYS = ("place", "place_name", "label", "jurisdiction_name", "name")
# Artifacts that are inputs to the identity system rather than consumers of it.
SKIP = {"bps_frame.csv", "corrections.csv"}


def load_frame():
    frame = {}
    with io.open(FRAME, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            frame[(r["state"], r["bps_id"])] = r["place_name"]
    return frame


def load_corrections():
    reg = set()
    if not os.path.exists(CORRECTIONS):
        return reg
    with io.open(CORRECTIONS, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            reg.add((r["artifact"].replace("\\", "/"), r["key_as_recorded"]))
    return reg


def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def check_pair(frame, state, bps, name):
    """Returns None if fine, else a reason string."""
    if (state, bps) not in frame:
        return "not in frame"
    if name and norm(name) != norm(frame[(state, bps)]):
        return "frame says %r" % frame[(state, bps)]
    return None


def scan_csv(path, frame):
    out = []
    try:
        with io.open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    except (IOError, ValueError, UnicodeDecodeError):
        return out
    if not rows:
        return out
    cols = rows[0].keys()
    if "state" not in cols or "bps_id" not in cols:
        return out
    namecol = next((c for c in NAME_KEYS if c in cols), None)
    for i, r in enumerate(rows, 2):
        st, bp = (r.get("state") or "").strip(), (r.get("bps_id") or "").strip()
        if not KEY.match("%s|%s" % (st, bp)):
            continue
        why = check_pair(frame, st, bp, r.get(namecol) if namecol else None)
        if why:
            out.append(("%s|%s" % (st, bp), r.get(namecol, ""), "row %d" % i,
                        why))
    return out


def scan_json(path, frame):
    out = []
    try:
        with io.open(path, encoding="utf-8") as fh:
            d = json.load(fh)
    except (IOError, ValueError, UnicodeDecodeError):
        return out
    if not isinstance(d, dict):
        return out
    for k, v in d.items():
        m = KEY.match(k if isinstance(k, str) else "")
        if not m:
            continue
        name = None
        if isinstance(v, dict):
            name = next((v[n] for n in NAME_KEYS if isinstance(v.get(n), str)),
                        None)
        why = check_pair(frame, m.group(1), m.group(2), name)
        if why:
            out.append((k, name or "", "key", why))
    return out


def main():
    if not os.path.exists(FRAME):
        # Every office identity in this project is a key into the Census
        # frame, and the frame is part of the unpublished raw store. Without
        # it there is no oracle, so there is nothing to check and nothing to
        # complain about - a checker that tracebacks on a missing input is
        # reporting its own bug, not a finding.
        sys.stdout.write(
            "identity check skipped: %s is not in this checkout. The raw "
            "store is not published (ADR-0015), so there is no frame to "
            "resolve office identities against.\n"
            % os.path.relpath(FRAME, ROOT).replace("\\", "/"))
        return 0
    frame = load_frame()
    reg = load_corrections()
    failures, known, scanned = [], [], 0

    for dirpath, dirnames, filenames in os.walk(DATA):
        dirnames[:] = [d for d in dirnames if d not in ("pages", "html",
                                                        "html_tier2", "raw",
                                                        "records")]
        for fn in sorted(filenames):
            if fn in SKIP or not fn.endswith((".csv", ".json")):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            hits = (scan_csv(path, frame) if fn.endswith(".csv")
                    else scan_json(path, frame))
            scanned += 1
            for key, name, where, why in hits:
                rec = (rel, key, name, where, why)
                (known if (rel, key) in reg else failures).append(rec)

    print("identity check: %d artifacts scanned, %d frame offices" %
          (scanned, len(frame)))
    if known:
        arts = len({k[0] for k in known})
        coll = sum(1 for k in known if k[4].startswith("frame says"))
        print("  %d registered corrections across %d artifacts "
              "(%d of them silent collisions with a real office)"
              % (len(known), arts, coll))
    if not failures:
        print("  no unregistered identity mismatches")
        return 0
    print("\n%d UNREGISTERED identity mismatches:" % len(failures))
    for rel, key, name, _where, why in failures:
        print("  %-42s %-11s %-34s %s" % (rel, key, (name or "-")[:34], why))
    print("\nEither the key is wrong, or the name is. Fix the artifact if it "
          "is live;\nregister it in data/corrections.csv if it is a dated "
          "capture that must not be rewritten.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
