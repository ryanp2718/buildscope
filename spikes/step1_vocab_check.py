# -*- coding: utf-8 -*-
"""Score permits.vocab against the real vocabularies Spike B pulled.

No HTTP, no model calls. This is the cheapest possible check on the mapping
layer: every native string in `data/spike_b/vocabularies.json` arrives with the
number of records that carry it, so coverage is weighted by how much of the
jurisdiction each rule actually accounts for rather than by how many distinct
strings it happens to match. An unweighted count would make a rule that catches
one string used 400,000 times look identical to one catching a string used
twice.

It also quantifies the omission that prompted the rewrite: Spike B's Austin
rule enumerated structure-class prefixes by hand and missed two of them.
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from permits import vocab  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Which native fields carry each signal, per jurisdiction, as observed in the
# dump. Stated rather than guessed.
#
# `default_kind` is the source-level declaration: these datasets contain
# building permits and nothing else, so there is no per-record string to
# classify. Austin is deliberately absent from that list - its single dataset
# carries BP/EP/MP/PP together, which is what produced the 4x overcount, and it
# must classify per record.
FIELDS = {
    "austin": {"structure": ("permit_class",), "work": ("work_class",),
                   "kind": ("permittype",), "default_kind": None},
    "charlotte": {"structure": ("permittype",), "work": ("worktype",),
                      "kind": ("permittype",), "default_kind": "BUILDING"},
    "columbus": {"structure": ("GENERAL_TYPE", "B1_PER_TYPE"),
                     "work": ("GENERAL_TYPE",), "kind": ("B1_PER_TYPE",),
                     "default_kind": "BUILDING"},
    "nashville": {"structure": ("Permit_Type_Description",),
                      "work": ("Permit_Type_Description",),
                      "kind": ("Permit_Type_Description",),
                      "default_kind": "BUILDING"},
}

# Spike B's hand-enumerated Austin prefixes, kept only so the omission can be
# measured. Not used anywhere else.
SPIKE_B_AUSTIN = ("R- 101", "R- 102", "R- 103", "R- 104", "C- 105", "R- 105")


def get(row, names):
    return tuple(row.get(n) for n in names)


def main():
    p = os.path.join(ROOT, "data", "spike_b", "vocabularies.json")
    V = json.load(io.open(p, encoding="utf-8"))

    print("=" * 88)
    print("VOCABULARY COVERAGE  (record-weighted; n = historical record count)")
    print("=" * 88)

    for key in sorted(V):
        rows = V[key]
        f = FIELDS[key]
        vb = vocab.Vocabulary(key, "test", default_kind=f["default_kind"])
        tot = struct_ok = work_ok = kind_ok = joint = 0
        kind_present = any(any(r.get(n) for n in f["kind"]) for r in rows)
        miss = {}
        for r in rows:
            n = int(r.get("n") or 0)
            tot += n
            s, _ = vb.structure(*get(r, f["structure"]))
            w, _ = vb.work(*get(r, f["work"]))
            k, _ = vb.kind(*get(r, f["kind"]))
            if s:
                struct_ok += n
            else:
                miss["structure: %s" % (" | ".join(
                    x for x in get(r, f["structure"]) if x) or "(blank)")] = \
                    miss.get("structure: %s" % (" | ".join(
                        x for x in get(r, f["structure"]) if x)
                        or "(blank)"), 0) + n
            if w != "UNKNOWN":
                work_ok += n
            else:
                lbl = "work: %s" % (" | ".join(
                    x for x in get(r, f["work"]) if x) or "(blank)")
                miss[lbl] = miss.get(lbl, 0) + n
            if k != "UNKNOWN":
                kind_ok += n
            if s and w == "NEW" and k == "BUILDING":
                joint += n

        print("\n-- %s   (%d distinct strings, %s records)"
              % (key, len(rows), "{:,}".format(tot)))
        pc = lambda h: 100.0 * h / tot if tot else 0
        print("     %-14s %6.1f%%" % ("structure", pc(struct_ok)))
        print("     %-14s %6.1f%%" % ("work class", pc(work_ok)))
        if kind_present:
            print("     %-14s %6.1f%%%s" % ("permit kind", pc(kind_ok),
                  "  (source-declared)" if f["default_kind"] else ""))
        else:
            print("     %-14s   n/a - the field that carries it (%s) is not "
                  "in this dump" % ("permit kind", ", ".join(f["kind"])))
        print("     %-14s %s records are NEW + BUILDING + a structure class"
              % ("joint:", "{:,}".format(joint)))
        if miss:
            print("     top unmapped, by records affected:")
            for s, c in sorted(miss.items(), key=lambda kv: -kv[1])[:4]:
                print("        %-56s %10s" % (s[:56], "{:,}".format(c)))

    # ---- the specific omission -----------------------------------------
    print("\n" + "=" * 88)
    print("THE AUSTIN OMISSION: hand-enumerated prefixes vs. the BPS code")
    print("=" * 88)
    missed, caught = [], 0
    for r in V["austin"]:
        pcls = r.get("permit_class") or ""
        n = int(r.get("n") or 0)
        if not vocab.BPS_CODE.search(pcls):
            continue
        caught += n
        if not any(pcls.startswith(c) for c in SPIKE_B_AUSTIN):
            missed.append((pcls, n))
    print("Records whose permit_class carries a BPS structure code: %s"
          % "{:,}".format(caught))
    print("Of those, records Spike B's prefix list did NOT match:")
    for pcls, n in sorted(missed, key=lambda x: -x[1]):
        print("   %-44s %10s" % (pcls, "{:,}".format(n)))
    tm = sum(n for _, n in missed)
    print("   %-44s %10s   (%.1f%% of coded records)"
          % ("TOTAL MISSED", "{:,}".format(tm),
             100.0 * tm / caught if caught else 0))
    print("\nBoth are structure classes filed under the commercial prefix. The")
    print("prefix is not a reliable guide to what the structure is; the code "
          "is.")

    # ---- the open-ended-range refusal ----------------------------------
    print("\n" + "=" * 88)
    print("NASHVILLE FREE TEXT: what units_from_text does with it")
    print("=" * 88)
    vb = vocab.Vocabulary("nashville", "test")
    for s in ("Multifamily, Apt / Twnhome > 5 Unit Bldg",
              "Single Family Residence",
              "Duplex - 2 Unit Bldg",
              "Apartment 24 Unit Building"):
        u, rule = vb.units_from_text(s)
        print("   %-42s -> %-6s %s" % (s, u, rule or "no match"))
    print("\n'> 5 Unit' is refused rather than read as 5. A refused record "
          "keeps\nunit_count_source='absent' and is excluded from "
          "reconciliation, not counted as 5.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
