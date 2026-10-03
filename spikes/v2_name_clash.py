# -*- coding: utf-8 -*-
"""The `html` parameter that shadows the `html` module. No model calls.

    python spikes/v2_name_clash.py

The synthesis prompt asks for `def extract(html: str)` and allows the
`html` module, whose `unescape` decodes entities. Inside `extract`, `html`
is the page, so a module that does `import html` and calls `html.unescape`
there gets the string and raises AttributeError on every page. This:

1. counts the scored draws that crash that way, per model, arm and
   protocol;
2. reads each stored v2 module's syntax tree for how it reaches the module
   (an aliased import, `from html import`, a renamed parameter, helpers
   defined outside `extract`, a helper nested inside it, a rebind inside
   it);
3. re-runs every crashed draw with one change - the module imported under
   an alias, and the references the parameter hides pointed at it - and
   scores it as a v2 draw is scored (`scripts/agent_eval.py`, `score_code`),
   field-level too;
4. on Clark, lists the pages each patched draw that still fails fails on,
   against the pages that carry a temporary permit (a permit-number span
   whose id ends `lblPermitNumber`, where an issued permit's ends
   `lblPermitNumber1`);
5. recomputes questions 1-5 of the v2 results report with the patched
   rates, from `site/results/data.json`.

The patch approximates a prompt whose parameter has another name; such a
prompt would draw different code. Writes `data/infer/name_clash.json`;
patched modules go to `data/infer/synth/name_clash/`.
"""
import ast
import collections
import io
import itertools
import json
import math
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import agent_eval as ae                                      # noqa: E402
from permits import fileio, sandbox                          # noqa: E402
from permits import harness as H                             # noqa: E402
from permits.stats import newcombe, wilson                   # noqa: E402

INFER = os.path.join(ROOT, "data", "infer")
OUT = os.path.join(INFER, "name_clash.json")
PATCHED = os.path.join(INFER, "synth", "name_clash")
DATA = os.path.join(ROOT, "site", "results", "data.json")
SEED = 20261001   # the seed of `spikes/v2_results.py`

# The three ways the clash surfaces: the attribute lookup on the string, and
# two attempts to reach the module under another name from inside extract.
CRASH = re.compile(r"no attribute 'unescape'|name '__import_html' is not defined"
                   r"|name 'html_module' is not defined")
TMP_ID = re.compile(r'id="[^"]*lblPermitNumber"')


def protocol(cell):
    return cell.get("protocol") or "v1"


def arm(cell):
    return "hint" if cell.get("synth_hint") else "baseline"


# ------------------------------------------------------------ how a module reaches `html`
def _attr_on(node, names, attrs=("unescape", "escape")):
    return (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id in names and node.attr in attrs)


def reach(src):
    """How this module reaches the html module, one label per module."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return "does not parse"
    plain = aliased = from_ = False
    for n in tree.body:
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name == "html":
                    if a.asname in (None, "html"):
                        plain = True
                    else:
                        aliased = True
        elif isinstance(n, ast.ImportFrom) and n.module == "html":
            from_ = True
    ext = next((n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "extract"), None)
    if ext is None:
        return "no extract"
    param = ext.args.args[0].arg if ext.args.args else None
    if from_:
        return "from html import"
    if aliased and not plain:
        return "aliased import"
    if not plain:
        return "no html import"
    if param != "html":
        return "parameter renamed"
    bound = {t.id for n in ast.walk(tree) if isinstance(n, ast.Assign)
             for t in n.targets if isinstance(t, ast.Name)}
    bound |= {a.arg for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.Lambda))
              for a in n.args.args}
    rebind = [n for n in ast.walk(ext) if isinstance(n, ast.Assign)
              and isinstance(n.value, ast.Name) and n.value.id in ("html", "__import_html")]
    unbound = [n for n in ast.walk(ext) if isinstance(n, ast.Attribute)
               and n.attr == "unescape" and isinstance(n.value, ast.Name)
               and n.value.id not in bound and n.value.id != "html"]
    if rebind or unbound:
        return "rebinds the module inside extract"
    inside = [n for n in ast.walk(ext) if _attr_on(n, ("html",))]
    if inside:
        nested = {id(a) for f in ast.walk(ext)
                  if isinstance(f, (ast.FunctionDef, ast.Lambda)) and f is not ext
                  for a in ast.walk(f)}
        return ("calls it from a helper nested in extract"
                if all(id(a) in nested for a in inside) else "calls it in extract")
    outside = any(_attr_on(a, ("html",)) for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name != "extract"
                  for a in ast.walk(n))
    return "helpers outside extract" if outside else "imports it, never calls it"


def patch(src):
    """Point every module reference the parameter hides at an alias; change
    nothing else."""
    src = re.sub(r"\bhtml\.(unescape|escape)\b", r"_htmlmod.\1", src)
    for m in list(re.finditer(r"^(\s*)(\w+)\s*=\s*(html|__import_html)\s*$", src, re.M)):
        if re.search(r"\b%s\.unescape\b" % re.escape(m.group(2)), src):
            src = src.replace(m.group(0), "%s%s = _htmlmod" % (m.group(1), m.group(2)), 1)
    head = ["import html as _htmlmod"]
    for name in sorted(set(re.findall(r"\b(\w+)\.unescape\b", src)) - {"_htmlmod"}):
        if not re.search(r"\b%s\s*=|import html as %s\b|def \w+\([^)]*\b%s\b"
                         % (name, name, name), src):
            head.append("import html as %s" % name)
    return "\n".join(head) + "\n" + src


# ------------------------------------------------------------ re-scoring
_targets = {}


def target(key):
    if key not in _targets:
        _targets[key] = ae.load_target(key)
    return _targets[key]


def pages_failed(key, path):
    """The corpus pages a module raises on or scores short of perfect on."""
    tg, corpus, refs, _user = target(key)
    res, err = sandbox.run_synth(path, corpus, PATCHED)
    if err:
        return None
    bad = []
    for item in res:
        fn = os.path.basename(item["page"])
        if not item["ok"]:
            bad.append(fn)
            continue
        sc = H.score(tg, refs[fn], item["rows"])
        if sc["recall"] != 1.0 or sc["precision"] != 1.0:
            bad.append(fn)
    return sorted(bad)


def tmp_pages(key):
    _tg, corpus, _refs, _user = target(key)
    out = []
    for p in corpus:
        with io.open(p, encoding="utf-8") as fh:
            if TMP_ID.search(fh.read()):
                out.append(os.path.basename(p))
    return sorted(out)


# ------------------------------------------------------------ the report's questions
def ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for t in range(i, j + 1):
            r[order[t]] = (i + j) / 2.0 + 1
        i = j + 1
    return r


def spearman(a, b):
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else float("nan")


def spearman_ci(a, b):
    """Bootstrap over models, as `spikes/v2_results.py` question 3 does it."""
    rng = random.Random(SEED)
    boots = []
    for _ in range(5000):
        idx = [rng.randrange(len(a)) for _ in a]
        r = spearman([a[i] for i in idx], [b[i] for i in idx])
        if not math.isnan(r):
            boots.append(r)
    boots.sort()
    return [round(boots[int(.025 * len(boots))], 2), round(boots[int(.975 * len(boots))], 2)]


def questions(data, gain):
    """Questions 1-5's figures, as scored and with `gain` (extra passes per
    (target, model, arm, protocol)) added."""
    models = {m["id"]: m for m in data["models"]}
    # In `spikes/v2_results.py`'s order, so the bootstrap draws the same resamples.
    roster = sorted((m for m in models if models[m]["group"] == "roster"),
                    key=lambda m: (models[m]["price_out"], m))
    cells = {(c["target"], c["model"], c["arm"], c["protocol"]): c for c in data["cells"]}

    def k(key, patched):
        c = cells[key]
        return c["k"] + (gain.get(key, 0) if patched else 0), c["n"]

    out = {}
    for label, patched in (("as_scored", False), ("patched", True)):
        cl = [(m, k(("clarkco", m, "baseline", "v2"), patched)) for m in roster]
        iv = {m: wilson(*kn) for m, kn in cl}
        sep = sorted((models[a]["name"], models[b]["name"]) for a, b in itertools.permutations(iv, 2)
                     if iv[a][0] > iv[b][1])
        cps, point = {}, {}
        for m, (kk, n) in cl:
            per = cells[("clarkco", m, "baseline", "v2")]["usd_per_draw"]
            if kk and per is not None:
                cps[m] = (per / iv[m][1], per / iv[m][0])
                point[m] = per * n / kk
        rev = sorted((models[a]["name"], models[b]["name"]) for a in cps for b in cps
                     if models[a]["price_out"] > models[b]["price_out"]
                     and point[a] < point[b] and cps[a][1] < cps[b][0])
        xs, ys, pf, fp = [], [], [], []
        for m, (ka, na) in cl:
            if ("santabarbara", m, "baseline", "v2") not in cells:
                continue
            kb, nb = k(("santabarbara", m, "baseline", "v2"), patched)
            xs.append(ka / na)
            ys.append(kb / nb)
            if wilson(ka, na)[0] >= 0.5 and kb == 0:
                pf.append(models[m]["name"])
            if ka == 0 and wilson(kb, nb)[0] >= 0.5:
                fp.append(models[m]["name"])
        contrasts = []
        for c in data["contrasts"]:
            if c["kind"] == "config":
                a, b = (c["target"], c["model"], "baseline", "v1"), (c["target"], c["model"], "baseline", "v2")
            else:
                a, b = (c["target"], c["model"], "baseline", "v2"), (c["target"], c["model"], "hint", "v2")
            (k1, n1), (k2, n2) = k(a, patched), k(b, patched)
            d, lo, hi = newcombe(k2, n2, k1, n1)
            contrasts.append({"kind": c["kind"], "model": models[c["model"]]["name"],
                              "target": c["target"], "from": [k1, n1], "to": [k2, n2],
                              "diff": [round(d, 2), round(lo, 2), round(hi, 2)],
                              "claimed": lo > 0 or hi < 0})
        out[label] = {"q1_separable": len(sep), "q2_reversals": rev,
                      "q3_spearman": round(spearman(xs, ys), 2),
                      "q3_spearman_ci95": spearman_ci(xs, ys),
                      "q3_pass_clark_fail_sb": pf, "q3_fail_clark_pass_sb": fp,
                      "contrasts": contrasts, "_sep": sep}
    a, b = out["as_scored"], out["patched"]
    sa, sb = set(a.pop("_sep")), set(b.pop("_sep"))
    out["q1_pairs_lost"] = sorted(sa - sb)
    out["q1_pairs_gained"] = sorted(sb - sa)
    out["contrasts_moved"] = [(x, y) for x, y in zip(a["contrasts"], b["contrasts"], strict=True)
                              if x["to"] != y["to"] or x["from"] != y["from"]]
    return out


# ------------------------------------------------------------ main
def main():
    v = fileio.read_json(os.path.join(INFER, "variance.json"))
    data = fileio.read_json(DATA)
    names = {m["id"]: m["name"] for m in data["models"]}
    os.makedirs(PATCHED, exist_ok=True)

    crashes = collections.Counter()      # (model, target, arm, protocol)
    reach_of = collections.defaultdict(collections.Counter)   # v2 baseline, by model
    crash_reach = collections.Counter()  # how the crashed v2 draws reach the module
    models_v2 = set()
    gain = collections.Counter()
    gain_field = collections.Counter()
    patched_rows = []
    for key, cell in sorted(v["cells"].items()):
        proto, a = protocol(cell), arm(cell)
        if proto == "v2":
            models_v2.add(cell["model"])
        for d in cell["detail"]:
            if d["outcome"] in ("not_attempted", "infra_error"):
                continue
            src = None
            if d.get("source") and os.path.exists(d["source"]):
                with io.open(d["source"], encoding="utf-8") as fh:
                    src = fh.read()
            how = reach(src) if src else "no module stored"
            if proto == "v2" and a == "baseline":
                reach_of[cell["model"]][how] += 1
            if not CRASH.search(d.get("error") or ""):
                continue
            ck = (cell["target"], cell["model"], a, proto)
            crashes[ck] += 1
            if proto == "v2":
                crash_reach[how] += 1
            name = "%s_%s_%s_%s_d%02d.py" % (proto, cell["target"],
                                             cell["model"].split("/")[-1], a, d["draw"])
            path = os.path.join(PATCHED, name)
            tg, corpus, refs, _user = target(cell["target"])
            sc = ae.score_code(tg, patch(src), corpus, refs, path)
            outcome = str(sc["outcome"].value if hasattr(sc["outcome"], "value") else sc["outcome"])
            row = {"cell": key, "draw": d["draw"], "model": cell["model"], "target": cell["target"],
                   "arm": a, "protocol": proto, "error": d["error"][:120], "reach": how,
                   "patched": outcome, "field_perfect": bool(sc.get("field_perfect")),
                   "patched_error": (sc.get("error") or "")[:120], "path": path}
            if outcome == "perfect":
                gain[ck] += 1
                gain_field[ck] += int(bool(sc.get("field_perfect")))
            elif cell["target"] == "clarkco":
                row["pages_failed"] = pages_failed("clarkco", path)
            patched_rows.append(row)

    tmp = tmp_pages("clarkco")
    clark_left = [r for r in patched_rows if r["target"] == "clarkco" and "pages_failed" in r
                  and r["protocol"] == "v2"]
    only_tmp = [r for r in clark_left if r["pages_failed"] and set(r["pages_failed"]) <= set(tmp)]

    # GPT-6 Sol on Clark: every baseline draw, patched where it crashed.
    sol = []
    cell = v["cells"]["clarkco|openai/gpt-6-sol|v2"]
    for d in cell["detail"]:
        row = next((r for r in patched_rows if r["cell"] == "clarkco|openai/gpt-6-sol|v2"
                    and r["draw"] == d["draw"]), None)
        path = row["path"] if row else d["source"]
        failed = pages_failed("clarkco", path)
        sol.append({"draw": d["draw"], "clash": bool(row), "pages_failed": failed,
                    "only_temporary_pages": bool(failed) and set(failed) <= set(tmp)})

    q = questions(data, dict(gain))

    cells_changed = []
    by_cell = {(c["target"], c["model"], c["arm"], c["protocol"]): c for c in data["cells"]}
    for ck in sorted(set(gain)):
        c = by_cell.get(ck)
        if not c:
            continue
        cells_changed.append({"target": ck[0], "model": names.get(ck[1], ck[1]), "arm": ck[2],
                              "protocol": ck[3], "as_scored": [c["k"], c["n"]],
                              "field_as_scored": [c["k_field"], c["n"]],
                              "patched": [c["k"] + gain[ck], c["n"]],
                              "field_patched": [None if c["k_field"] is None   # v1 cells
                                                else c["k_field"] + gain_field[ck], c["n"]]})

    per_model = collections.Counter()
    for (m, _t, _a, proto), n in [((k[1], k[0], k[2], k[3]), n) for k, n in crashes.items()]:
        if proto == "v2":
            per_model[m] += n
    out = {
        "note": "Draws that crash on the `html` parameter shadowing the `html` module, and "
                "the same draws re-scored with only that reference patched. Exploratory.",
        "v2_crashes": sum(n for k, n in crashes.items() if k[3] == "v2"),
        "v1_crashes": sum(n for k, n in crashes.items() if k[3] == "v1"),
        "v2_models": len(models_v2),
        "v2_models_crashing": len(per_model),
        "v2_crashes_by_model": {names.get(m, m): n for m, n in per_model.most_common()},
        "source": "spikes/v2_name_clash.py",
        "crashes_by_cell": [{"target": k[0], "model": k[1], "arm": k[2], "protocol": k[3],
                             "crashes": n, "pass_patched": gain[k]}
                            for k, n in sorted(crashes.items())],
        "reach_v2_baseline": {names.get(m, m): dict(c.most_common())
                              for m, c in sorted(reach_of.items())},
        "reach_of_v2_crashes": dict(crash_reach.most_common()),
        "cells_changed": cells_changed,
        "clark_temporary_pages": tmp,
        "clark_still_failing": len(clark_left),
        "clark_still_failing_only_temporary_pages": len(only_tmp),
        "clark_still_failing_other": [(r["model"], r["arm"], r["draw"], r["patched_error"][:60])
                                      for r in clark_left if r not in only_tmp],
        "sol_clark": sol,
        "questions": q,
        "draws": patched_rows,
    }
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)

    print("v2: %d scored draws crash on the clash, %d of %d models; v1: %d"
          % (out["v2_crashes"], out["v2_models_crashing"], out["v2_models"], out["v1_crashes"]))
    print("  by model:", out["v2_crashes_by_model"])
    print("  how the crashed v2 draws reach the module:", out["reach_of_v2_crashes"])
    print("\nHow each model's v2 baseline modules reach `html`:")
    for m, c in out["reach_v2_baseline"].items():
        print("  %-24s %s" % (m, c))
    print("\nCells that change (pass@1, field-level):")
    for c in cells_changed:
        print("  %-12s %-22s %-8s %s  %d/%d (%s) -> %d/%d (%s)" % (
            c["target"], c["model"], c["arm"], c["protocol"], c["as_scored"][0], c["as_scored"][1],
            c["field_as_scored"][0], c["patched"][0], c["patched"][1], c["field_patched"][0]))
    print("\nClark v2, patched draws still failing: %d; only on the %d temporary-permit pages: %d; other: %s"
          % (out["clark_still_failing"], len(tmp), out["clark_still_failing_only_temporary_pages"],
             out["clark_still_failing_other"]))
    print("GPT-6 Sol, Clark: %s" % [(s["draw"], s["clash"], len(s["pages_failed"] or []),
                                     s["only_temporary_pages"]) for s in sol])
    for label in ("as_scored", "patched"):
        x = q[label]
        print("\n%s: Q1 separable %d; Q2 reversals %d; Q3 rho %.2f %s, pass-Clark-fail-SB %s, reverse %s"
              % (label, x["q1_separable"], len(x["q2_reversals"]), x["q3_spearman"],
                 x["q3_spearman_ci95"], x["q3_pass_clark_fail_sb"], x["q3_fail_clark_pass_sb"]))
    print("Q1 pairs no longer separable:", q["q1_pairs_lost"])
    print("Q1 pairs newly separable:", q["q1_pairs_gained"])
    print("Q2 reversals added:", sorted(set(map(tuple, q["patched"]["q2_reversals"]))
                                        - set(map(tuple, q["as_scored"]["q2_reversals"]))))
    print("Contrasts that move:")
    for x, y in q["contrasts_moved"]:
        print("  %-6s %-22s %-12s %s %s -> %s %s%s" % (
            x["kind"], x["model"], x["target"], x["diff"], "claimed" if x["claimed"] else "",
            y["diff"], "claimed" if y["claimed"] else "",
            "" if x["claimed"] == y["claimed"] else "  <- claim changes"))


if __name__ == "__main__":
    main()
