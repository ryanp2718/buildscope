# -*- coding: utf-8 -*-
"""Export the protocol v2 run to the one data file the results page reads.

    python scripts/export_results.py
    python scripts/export_results.py --out some/other/data.json

Writes `site/results/data.json`:

  models   one record per model on the run: lab, tier, list price
  cells    one record per (target, model, arm, protocol): pass@1 with its
           Wilson interval, field-level pass@1 beside it, cost per draw and
           per success, a simulated 95% range for cost per success,
           re-draws, host failures, excluded draws, hosts
  draws    one record per draw: outcome, whether it agrees on every field,
           tokens, what it cost to buy, host
  excluded one record per draw bought but left out of every figure, with
           the rule that leaves it out (`rollup.EXCLUDED`)
  contrasts  hint minus baseline on Clark (question 5) and v2 minus v1 on
           Clark and St. Johns (question 4), per model, with the
           pre-registered Newcombe interval and whether an effect is claimed
  wall     every glm-5.3-flash v2 synthesis call: how long, which host, and
           whether it finished or the host closed the stream (deviation 2)
  exploratory  figures from analyses outside the pre-registration, each
           with its source: the caption-table test
           (`spikes/v2_results.py --caption`), best-of-5 with the
           reference-free check (`spikes/verifier_offline.py`) and the draws
           that crash on the `html` parameter shadowing the `html` module
           (`spikes/v2_name_clash.py`), when each has been run
  pairs    one record per pair of comparable cells: which is cheaper per
           success, by how much, how likely, and whether that is settled

and, beside it, `tables.html`: the same figures as plain tables, the page's
fallback without JavaScript and the source of its "Show the data" tables.

Every rate and cost comes from `permits/rollup.py` (`aggregate`, and the
per-draw rows it is derived from), the functions `scripts/model_stats.py`
writes the stats table with, so the page, the report and the table cannot
disagree. The cost-per-success range is the method of
docs/evidence/2026-09-27-cost-per-success-intervals.md applied to one cell:
the pass rate drawn from a Beta posterior, the mean cost per draw from a
bootstrap of the cell's draws. It is seeded per cell, so a re-run with no
new draws writes identical bytes, and a new cell does not move the others.

Field-level pass@1 counts a draw that passes and also agrees on every field
of every matched record (v2 pre-registration, deviation 4), from
`data/infer/verifier/field_audit.json` (`scripts/field_audit.py`); without
that file the export stops, so the page never goes out without it.

What goes in is the step 6 roster and the seven v1 models re-run under v2
(docs/evidence/2026-09-27-v2-run-preregistration.md), their v2 cells, and
the v1 baseline cells of the seven, for the v1-to-v2 comparison. Nothing
from `data/` leaves except these figures: no source, no prompt, no path.

No model calls. Reads only what is already on disk.
"""
import argparse
import collections
import html
import io
import json
import os
import random
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from permits import fileio, infer, models, rollup            # noqa: E402
from permits.stats import newcombe                           # noqa: E402

OUT = os.path.join(ROOT, "site", "results", "data.json")
INFER = os.path.join(ROOT, "data", "infer")
CAPTION = os.path.join(INFER, "verifier", "caption.json")
BEST_OF_K = os.path.join(INFER, "verifier", "best_of_k.json")
NAME_CLASH = os.path.join(INFER, "name_clash.json")
WALL_MODEL = "z-ai/glm-5.3-flash"

# The step 6 roster and the v1 models re-run under v2, by registry id, in the
# pre-registration's order. `tests/test_export_results.py` checks this
# against `spikes/preregister_v2_run.py`, which the roster was published from.
ROSTER = [
    "claude-opus-5-5", "claude-sonnet-5", "claude-haiku-4-5-20251001",
    "openai/gpt-6-sol", "openai/gpt-6-luna",
    "google/gemini-3.8-flash", "google/gemini-3.5-flash-lite",
    "x-ai/grok-4.7", "moonshotai/kimi-k3",
    "z-ai/glm-5.3", "z-ai/glm-5.3-flash",
    "qwen/qwen3.8-max-0902", "qwen/qwen3.8-flash",
    "deepseek/deepseek-v4-pro-0813", "deepseek/deepseek-v4.1-flash",
    "xiaomi/mimo-v2.6-pro", "xiaomi/mimo-v2.6-flash",
    "minimax/minimax-m3", "tencent/hy3",
]
V1_RERUN = [
    "z-ai/glm-5.2", "deepseek/deepseek-v4-pro", "deepseek/deepseek-v4-flash",
    "moonshotai/kimi-k2-thinking", "openai/gpt-oss-120b",
    "qwen/qwen3.5-flash-02-23", "qwen/qwen3-coder",
]
# Display names, the page's and the tables'. Every id on the run has one
# (`tests/test_export_results.py`).
NAMES = {
    "claude-opus-5-5": "Claude Opus 5.5", "claude-sonnet-5": "Claude Sonnet 5",
    "claude-haiku-4-5-20251001": "Claude Haiku 4.5",
    "openai/gpt-6-sol": "GPT-6 Sol", "openai/gpt-6-luna": "GPT-6 Luna",
    "google/gemini-3.8-flash": "Gemini 3.8 Flash",
    "google/gemini-3.5-flash-lite": "Gemini 3.5 Flash-Lite",
    "x-ai/grok-4.7": "Grok 4.7", "moonshotai/kimi-k3": "Kimi K3",
    "z-ai/glm-5.3": "GLM-5.3", "z-ai/glm-5.3-flash": "GLM-5.3 Flash",
    "qwen/qwen3.8-max-0902": "Qwen3.8 Max", "qwen/qwen3.8-flash": "Qwen3.8 Flash",
    "deepseek/deepseek-v4-pro-0813": "DeepSeek V4 Pro",
    "deepseek/deepseek-v4.1-flash": "DeepSeek V4.1 Flash",
    "xiaomi/mimo-v2.6-pro": "MiMo V2.6 Pro", "xiaomi/mimo-v2.6-flash": "MiMo V2.6 Flash",
    "minimax/minimax-m3": "MiniMax M3", "tencent/hy3": "Hunyuan 3",
    "z-ai/glm-5.2": "GLM-5.2", "deepseek/deepseek-v4-pro": "DeepSeek V4 Pro (Apr)",
    "deepseek/deepseek-v4-flash": "DeepSeek V4 Flash",
    "moonshotai/kimi-k2-thinking": "Kimi K2 Thinking",
    "openai/gpt-oss-120b": "gpt-oss-120b", "qwen/qwen3.5-flash-02-23": "Qwen3.5 Flash",
    "qwen/qwen3-coder": "Qwen3 Coder",
}
TARGETS = {
    "clarkco": "Clark County, NV",
    "stjohns": "St. Johns County, FL",
    "santabarbara": "Santa Barbara County, CA",
}

N_SIM = 20000
SEED = 20260928
PRIORS = (("jeffreys", 0.5), ("uniform", 1.0))
# The intervals report's thresholds: a ranking is settled at P >= 0.975
# under both priors, over cells of at least 3 scored draws.
SETTLED = 0.975
PAIR_MIN_N = 3


def _r(x, places=6):
    return None if x is None else round(float(x), places)


def wanted(cell):
    """The cells the page draws from: every v2 cell of a model on the run,
    and the v1 baseline cell of each re-run v1 model."""
    if cell["model"] not in ROSTER and cell["model"] not in V1_RERUN:
        return False
    if cell["target"] not in TARGETS:
        return False
    cond = rollup.condition(cell)
    if cond in ("v2", "hint|v2"):
        return True
    return cond == "baseline" and cell["model"] in V1_RERUN


def arm_protocol(cond):
    """`hint|v2` -> (`hint`, `v2`); `baseline` (a v1 cell) -> (`baseline`,
    `v1`)."""
    parts = cond.split("|")
    arm = "hint" if "hint" in parts else "baseline"
    protocol = "v2" if "v2" in parts else "v1"
    return arm, protocol


def quantile(xs, f):
    return xs[int(f * (len(xs) - 1))]


def simulate(key, k, n, costs):
    """Simulated cost per success for one cell, per prior, in the order
    drawn: the pass rate from its Beta posterior, the mean cost per draw from
    a bootstrap of the cell's draws.

    None when the cell never succeeded (no finite cost per success exists)
    or when any draw's purchase is unknown (a partial bill understates it).
    The seed is derived from the cell key, so cells are independent of the
    order they are exported in and of each other."""
    if k == 0 or not costs or any(c is None for c in costs):
        return None
    rng = random.Random(SEED ^ zlib.crc32(key.encode("utf-8")))
    out = {}
    for prior, a0 in PRIORS:
        sims = []
        for _ in range(N_SIM):
            p = rng.betavariate(k + a0, n - k + a0)
            mean = sum(rng.choice(costs) for _ in costs) / len(costs)
            sims.append(mean / p)
        out[prior] = sims
    return out


def cost_per_success_range(sims):
    """Median and 95% range of a cell's simulated cost per success, per
    prior."""
    if sims is None:
        return None
    out = {}
    for prior, _ in PRIORS:
        xs = sorted(sims[prior])
        out[prior] = [_r(quantile(xs, .025)), _r(quantile(xs, .5)),
                      _r(quantile(xs, .975))]
    return out


def pairs(cells, sims):
    """Every pair of cells on the same target, arm and protocol that both
    have a cost per success, with how sure the data is which is cheaper.

    The method of docs/evidence/2026-09-27-cost-per-success-intervals.md:
    `a` is the cheaper per success at the point estimate, `ratio` is how
    many times cheaper (b's cost per success over a's, median and 95%
    range), `p_a_cheaper` the share of simulations in which a is cheaper.
    The two cells' simulations are independent, so pairing them draw for
    draw samples the ratio. A ranking is `settled` when a is cheaper with
    probability at least 0.975 under both priors. Cells with fewer than
    `PAIR_MIN_N` draws are left out, as the report left them out."""
    groups = collections.defaultdict(list)
    for c in cells:
        if sims.get(c["key"]) is not None and c["n"] >= PAIR_MIN_N:
            groups[(c["target"], c["arm"], c["protocol"])].append(c)
    out = []
    for (target, arm, protocol), members in sorted(groups.items()):
        members.sort(key=lambda c: (c["usd_per_success"], c["model"]))
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                sa, sb = sims[a["key"]], sims[b["key"]]
                p, ratio = {}, {}
                for prior, _ in PRIORS:
                    rs = [y / x for x, y in zip(sa[prior], sb[prior], strict=True)]
                    p[prior] = _r(sum(1 for r in rs if r > 1) / len(rs), 4)
                    rs.sort()
                    ratio[prior] = [_r(quantile(rs, f), 4) for f in (.025, .5, .975)]
                out.append({
                    "target": target, "arm": arm, "protocol": protocol,
                    "a": a["model"], "b": b["model"],
                    "p_a_cheaper": p, "ratio": ratio,
                    "settled": min(p.values()) >= SETTLED,
                })
    return out


def contrasts(cells):
    """Questions 4 and 5 per model: hint minus baseline on Clark, and v2
    minus v1 on Clark and St. Johns, with Newcombe intervals. An effect is
    claimed only where the interval excludes 0, as pre-registered."""
    at = {(c["target"], c["model"], c["arm"], c["protocol"]): c
          for c in cells}
    out = []
    for (target, model, arm, protocol), a in sorted(at.items()):
        if arm == "hint" and protocol == "v2" and target == "clarkco":
            kind, b = "hint", at.get((target, model, "baseline", "v2"))
        elif arm == "baseline" and protocol == "v2":
            kind, b = "config", at.get((target, model, "baseline", "v1"))
        else:
            continue
        if not (b and a["n"] and b["n"]):
            continue
        d, lo, hi = newcombe(a["k"], a["n"], b["k"], b["n"])
        out.append({"kind": kind, "target": target, "model": model,
                    "from": [b["k"], b["n"]], "to": [a["k"], a["n"]],
                    "diff": [_r(d, 4), _r(lo, 4), _r(hi, 4)],
                    "claimed": lo > 0 or hi < 0})
    return out


# Hosts as their providers write them; a direct API call records the lab's
# lowercase client name.
HOST_NAMES = {"anthropic": "Anthropic"}


def _host(h):
    return HOST_NAMES.get(h, h)


def wall(ledger):
    """Every v2 synthesis call of the model whose hosts closed streams early,
    by duration, so the fixed points at which they did can be seen."""
    out = []
    for r in ledger:
        if not (r.model == WALL_MODEL and r.protocol == "v2"
                and r.call_class == "synthesis" and r.tag.endswith("/var")):
            continue
        if r.stop_reason in infer.NATURAL_STOPS:
            what = "finished"
        elif r.stop_reason == "max_tokens" and r.max_tokens \
                and r.output_tokens < r.max_tokens:
            what = "stopped by the host below the cap"
        elif r.stop_reason == "max_tokens":
            what = "reached the output cap"
        elif r.output_tokens and (not r.max_tokens
                                  or r.output_tokens < r.max_tokens):
            what = "closed by the host"
        else:
            what = "failed with no output"
        out.append({"seconds": _r(r.seconds, 1), "host": _host(r.host),
                    "output_tokens": r.output_tokens, "what": what})
    return sorted(out, key=lambda w: (w["seconds"], w["host"] or ""))


def best_of_5(bok):
    """Per cell, pass@1 beside the chance that the first of five draws the
    reference-free check accepts is perfect, and an oracle's pass@5."""
    out = []
    for c in bok["cells"]:
        arm, protocol = arm_protocol(c["condition"])
        k1, k5 = c["k"]["1"], c["k"]["5"]
        out.append({"target": c["target"], "model": c["model"], "arm": arm,
                    "protocol": protocol, "n": c["n"], "k": c["perfect"],
                    "best5": k5["success"], "oracle5": k5["pass_at_k"],
                    "usd_per_success_1": k1["usd_per_success"],
                    "usd_per_success_5": k5["usd_per_success"]})
    return sorted(out, key=lambda r: (r["target"], r["model"], r["arm"]))


def name_clash(nc):
    """Per cell, the scored draws that crash on the `html` parameter
    shadowing the `html` module, and how many of them pass once only that
    reference is patched."""
    return sorted(({k: c[k] for k in ("target", "model", "arm", "protocol", "crashes",
                                      "pass_patched")} for c in nc["crashes_by_cell"]),
                  key=lambda r: (r["target"], r["model"], r["arm"], r["protocol"]))


def build(v, ledger, audit=(), caption=None, bok=None, clash=None):
    cells = {k: c for k, c in v["cells"].items() if wanted(c)}
    fields = rollup.field_verdicts(audit)
    rows = rollup.rows_from_variance({"cells": cells}, ledger, fields)
    rows += rollup.rows_from_ledger(ledger)
    agg = rollup.aggregate(rows)

    per_draw = collections.defaultdict(dict)
    for r in rows:
        if r["experiment"] == "variance":
            key = rollup.cell_name(r["target"], r["model"],
                                        r["condition"])
            per_draw[(key, r["unit_id"])][r["metric"]] = r["value"]

    out_cells, out_draws, out_excluded, sims = [], [], [], {}
    for key in sorted(cells):
        cell = cells[key]
        e = agg[key]
        arm, protocol = arm_protocol(e["condition"])
        draws = rollup.draws_of(cell)
        hosts = collections.Counter(_host(d.host) for d in draws
                                    if d.scored() and d.host)
        costs = [per_draw[(key, "d%02d" % d.draw)].get("usd_purchase")
                 for d in draws if d.scored()]
        n, k = e["draws_scored"], e["perfect"]
        known = [c for c in costs if c is not None]
        sims[key] = simulate(key, k, n, costs)
        out_cells.append({
            "key": key, "target": cell["target"], "model": cell["model"],
            "arm": arm, "protocol": protocol,
            "n": n, "k": k,
            "rate": _r(e["success_rate"], 4),
            "ci95": e["success_ci95"],
            "k_field": e["field_perfect"],
            "rate_field": _r(e["field_success_rate"], 4),
            "ci95_field": e["field_success_ci95"],
            "usd_per_field_success": _r(e["usd_per_field_success"]),
            "usd_total": _r(e["usd_total"]),
            "usd_per_draw": (_r(sum(known) / n)
                             if n and len(known) == n else None),
            "usd_per_success": _r(e["usd_per_success"]),
            "usd_per_success_range": cost_per_success_range(sims[key]),
            "draws_unpriced": e["draws_unpriced"],
            "draws_redrawn": e["draws_redrawn"],
            "draws_truncated": e["draws_truncated"],
            "draws_infra_error": e["draws_infra_error"],
            "draws_excluded": e["draws_excluded"],
            "usd_failed_calls": _r(e["usd_failed_calls"]),
            "silent_failures": e["silent_failures"],
            "reasoning_tokens_p50": e["reasoning_tokens_p50"],
            "hosts": dict(sorted(hosts.items())),
        })
        for d in draws:
            m = per_draw[(key, "d%02d" % d.draw)]
            why = rollup.EXCLUDED.get((key, d.draw))
            if why:
                out_excluded.append({"cell": key, "draw": d.draw,
                                     "outcome": rollup.failure_mode(d),
                                     "why": why})
                continue
            fp = m.get("field_perfect")
            out_draws.append({
                "cell": key, "draw": d.draw,
                "outcome": rollup.failure_mode(d),
                "field_perfect": None if fp is None else bool(fp),
                "output_tokens": d.output_tokens,
                "reasoning_tokens": d.reasoning_tokens,
                "usd": _r(m.get("usd_purchase")),
                "seconds": _r(m.get("seconds"), 1),
                "host": _host(d.host),
                "redrawn": bool(d.redraw_max_tokens),
                "recall_min": _r(d.recall_min, 4),
            })

    on_run = set(ROSTER) | set(V1_RERUN)
    out_models = []
    for mid in ROSTER + V1_RERUN:
        s = models.get(mid)
        out_models.append({
            "id": mid, "name": NAMES[mid], "short": s.short, "lab": s.lab,
            "tier": str(s.tier),
            "group": "roster" if mid in ROSTER else "v1_rerun",
            "price_in": s.list_price[0], "price_out": s.list_price[1],
            # What protocol v2 sent: the reasoning effort, and the sampling
            # settings; None where nothing is sent and the lab's default rules.
            "effort": s.effort, "temperature": s.temperature,
            "top_p": s.top_p,
        })
    assert {m["id"] for m in out_models} == on_run

    return {
        # The last purchase behind an exported draw, not the last ledger row:
        # later calls of other experiments are not this data.
        "as_of": max((ledger[i].at for i in
                      rollup.purchases({"cells": cells}, ledger).values()
                      if i is not None), default=None),
        "note": ("pass@1 is perfect agreement with a hand-written adapter on "
                 "every page of the target; agreement is not accuracy. Costs "
                 "are what each draw cost to buy, in USD. Prices are list "
                 "USD per million tokens (input, output)."),
        "method": {
            "interval": "Wilson 95%",
            "cost_per_success_range": ("Beta posterior on the rate x "
                                       "bootstrap of cost per draw, "
                                       "2.5/50/97.5 percentiles"),
            "priors": [p for p, _ in PRIORS], "n_sim": N_SIM, "seed": SEED,
            "pairs": ("same target, arm and protocol, n >= %d; settled when "
                      "P(a cheaper per success) >= %.3f under both priors"
                      % (PAIR_MIN_N, SETTLED)),
        },
        "targets": TARGETS,
        "models": out_models,
        "cells": out_cells,
        "draws": out_draws,
        "excluded": out_excluded,
        "pairs": pairs(out_cells, sims),
        "contrasts": contrasts(out_cells),
        "wall": wall(ledger),
        # Counts only: the file that holds them names its producer under
        # `source`, a key nothing in this export may carry.
        "exploratory": dict(
            ({"caption": {
                "silent_empty": caption["silent_empty"],
                "rows_back": caption["rows_back"], "pass": caption["pass"],
                "producer": "spikes/v2_results.py --caption"}} if caption else {}),
            **({"best_of_5": {
                "cells": best_of_5(bok), "orders": bok["orders"], "seed": bok["seed"],
                "producer": "spikes/verifier_offline.py"}} if bok else {}),
            **({"name_clash": {
                "cells": name_clash(clash),
                "producer": "spikes/v2_name_clash.py"}} if clash else {})),
    }


def render(data):
    """Bytes as written: sorted keys, one level of indent, a final newline,
    so a re-run with nothing new is byte-identical and a diff is readable."""
    return json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


# ---- tables.html: the charts' figures as plain tables -----------------------
# The page's fallback without JavaScript, and the source of the "Show the
# data" tables under each chart, which the page lifts from this file by id.
# Written from the same dict as data.json, so the two cannot disagree.

OUTCOME_COLUMNS = [
    ("perfect", "Passed"),
    ("silent_empty", "No rows on some page"),
    ("silent_partial", "Wrong or missing rows"),
    ("loud", "Raised an error or wrote no program"),
    ("infra_error", "Host failed (not counted)"),
]

TABLES_CSS = """
  :root { --bg: #f6f7f5; --ink: #17191c; --mut: #62666d; --rule: #d9dcd8;
          --sans: "Libre Franklin", "Helvetica Neue", Arial, sans-serif; }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) { color-scheme: dark; --bg: #121416; --ink: #e7e9ea;
                                      --mut: #a0a5ab; --rule: #2e3236; }
  }
  :root[data-theme="dark"] { color-scheme: dark; --bg: #121416; --ink: #e7e9ea;
                             --mut: #a0a5ab; --rule: #2e3236; }
  body { margin: 0 auto; max-width: 62rem; padding: 1.5rem 16px 3rem; background: var(--bg);
         color: var(--ink); font: 15px/1.5 var(--sans); }
  h1 { font-size: 1.5rem; margin: 0 0 .5rem; }
  h2 { font-size: 1.1rem; margin: 2.2rem 0 .3rem; }
  p { color: var(--mut); margin: 0 0 .8rem; max-width: 44rem; }
  .scroll { overflow-x: auto; }
  table { border-collapse: collapse; font-variant-numeric: tabular-nums; font-size: 13.5px; }
  caption { text-align: left; color: var(--mut); padding-bottom: .4rem; }
  th, td { padding: .3rem .7rem .3rem 0; border-bottom: 1px solid var(--rule); text-align: right;
           white-space: nowrap; vertical-align: top; }
  th:first-child, td:first-child, th.l, td.l { text-align: left; }
  thead th { font-weight: 600; border-bottom-color: var(--ink); }
  a { color: inherit; }
"""


def _usd(x):
    """As the page formats money: more places the smaller it is."""
    if x is None:
        return "n/a"
    return "$%.2f" % x if x >= 0.1 else "$%.3f" % x if x >= 0.01 else "$%.4f" % x


def _price(x):
    return "$%.2f" % x if x < 1 or x % 1 else "$%d" % x


def _pct(x):
    return "%d%%" % round(x * 100)


def _times(x):
    sign = chr(0xD7)                  # the multiplication sign
    return ("%d" % round(x) if x >= 10 else "%.1f" % x) + sign


def _table(tid, caption, head, rows, left=1, wrap=()):
    """One table; the first `left` columns are text, the rest figures. Columns
    in `wrap` hold long text and wrap rather than widen the table."""
    esc = html.escape
    th = "".join('<th scope="col"%s>%s</th>' % (' class="l"' if i < left or i in wrap else "",
                                                 esc(h))
                 for i, h in enumerate(head))
    body = []
    for r in rows:
        tds = ['<th scope="row">%s</th>' % esc(str(r[0]))]
        tds += ['<td%s>%s</td>' % (' class="wrap"' if i + 1 in wrap
                                   else ' class="l"' if i + 1 < left else "", esc(str(c)))
                for i, c in enumerate(r[1:])]
        body.append("<tr>%s</tr>" % "".join(tds))
    return ('<div class="scroll"><table id="%s">\n<caption>%s</caption>\n'
            "<thead><tr>%s</tr></thead>\n<tbody>\n%s\n</tbody>\n</table></div>"
            % (tid, esc(caption), th, "\n".join(body)))


def render_tables(data):
    models_ = {m["id"]: m for m in data["models"]}
    cells = {(c["target"], c["model"], c["arm"], c["protocol"]): c for c in data["cells"]}
    roster = sorted((m for m in data["models"] if m["group"] == "roster"),
                    key=lambda m: (m["price_out"], m["name"]))
    by_price = roster + sorted((m for m in data["models"] if m["group"] != "roster"),
                               key=lambda m: (m["price_out"], m["name"]))

    price_rows = []
    for m in roster:
        c = cells.get(("clarkco", m["id"], "baseline", "v2"))
        if c is None:
            continue
        r = c["usd_per_success_range"]
        price_rows.append([
            m["name"], _price(m["price_out"]), "%d of %d" % (c["k"], c["n"]),
            _pct(c["rate"]), "%s to %s" % (_pct(c["ci95"][0]), _pct(c["ci95"][1])),
            _usd(c["usd_per_draw"]),
            _usd(c["usd_per_success"]) if c["k"] else "none passed",
            "%s to %s" % (_usd(r["jeffreys"][0]), _usd(r["jeffreys"][2])) if r else "",
        ])

    rank_rows = []
    on_roster = {m["id"] for m in roster}
    for q in data["pairs"]:
        if not (q["target"] == "clarkco" and q["arm"] == "baseline"
                and q["protocol"] == "v2" and q["settled"]
                and q["a"] in on_roster and q["b"] in on_roster):
            continue
        a, b = models_[q["a"]], models_[q["b"]]
        lo, mid, hi = q["ratio"]["jeffreys"]
        rank_rows.append([
            a["name"], b["name"],
            "%s against %s" % (_price(a["price_out"]), _price(b["price_out"])),
            "yes" if a["price_out"] > b["price_out"] else "no",
            "%s (%s to %s)" % (_times(mid), _times(lo), _times(hi)),
            "%.3f / %.3f" % (q["p_a_cheaper"]["jeffreys"], q["p_a_cheaper"]["uniform"]),
        ])
    rank_rows.sort(key=lambda r: (r[3] != "yes", r[0], r[1]))

    counts = collections.defaultdict(collections.Counter)
    for d in data["draws"]:
        counts[d["cell"]][d["outcome"]] += 1
    draw_rows = []
    for m in by_price:
        for t, label in data["targets"].items():
            c = cells.get((t, m["id"], "baseline", "v2"))
            if c is None:
                continue
            k = counts[c["key"]]
            draw_rows.append([m["name"], label.split(",")[0], c["n"]]
                             + [k[o] for o, _ in OUTCOME_COLUMNS])

    def rate(c):
        if c is None:
            return "not run"
        return "%d of %d (%s to %s)" % (c["k"], c["n"], _pct(c["ci95"][0]),
                                        _pct(c["ci95"][1]))
    port_rows = [[m["name"]] + [rate(cells.get((t_, m["id"], "baseline", "v2")))
                                for t_ in data["targets"]]
                 for m in roster]

    names = {m["id"]: m["name"] for m in data["models"]}
    effect_rows = []
    for q in sorted(data.get("contrasts", []),
                    key=lambda q: (q["kind"], q["target"], names[q["model"]])):
        d, lo, hi = q["diff"]
        effect_rows.append([
            names[q["model"]],
            ("hint, " if q["kind"] == "hint" else "v1 to v2, ")
            + data["targets"][q["target"]].split(",")[0],
            "%d of %d" % tuple(q["from"]), "%d of %d" % tuple(q["to"]),
            "%+d points (%+d to %+d)" % (round(d * 100), round(lo * 100),
                                         round(hi * 100)),
            "yes" if q["claimed"] else "no"])

    bo5 = (data.get("exploratory") or {}).get("best_of_5") or {"cells": []}
    order = {t: i for i, t in enumerate(data["targets"])}
    best_rows = [[names[r["model"]], data["targets"][r["target"]].split(",")[0],
                  "%d of %d" % (r["k"], r["n"]), _pct(r["k"] / r["n"]),
                  _pct(r["best5"]), _pct(r["oracle5"])]
                 for r in sorted(bo5["cells"], key=lambda r: (order[r["target"]],
                                                             names[r["model"]]))
                 if r["arm"] == "baseline" and r["protocol"] == "v2"]

    wall_rows = [[w["host"] or "unknown", "%.0f" % w["seconds"],
                  w["output_tokens"], w["what"]] for w in data.get("wall", [])]

    setting_rows = []
    for m in by_price:
        mc = [c for c in data["cells"] if c["model"] == m["id"]
              and c["protocol"] == "v2"]
        hosts = collections.Counter()
        for c in mc:
            hosts.update(c["hosts"])
        setting_rows.append([
            m["name"], m["effort"] or "lab default",
            "lab default" if m["temperature"] is None else m["temperature"],
            "lab default" if m["top_p"] is None else m["top_p"],
            sum(c["draws_redrawn"] for c in mc),
            # A host's count in brackets, unbroken: "Mancer 2 (2)".
            ", ".join(("%s (%d)" % hc).replace(" ", chr(0xA0)) for hc in hosts.most_common())])

    parts = [
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Results as Tables</title>\n"
        '<link rel="icon" href="data:,">\n'
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Libre+Franklin:'
        'wght@400;600&display=swap">\n'
        "<style>%s</style>\n</head>\n<body>\n" % TABLES_CSS,
        "<h1>The price of a working program: the figures</h1>\n"
        "<p>Every figure behind the charts on <a href=\"index.html\">the results page</a>, "
        "from the same data file (<a href=\"data.json\">data.json</a>), as of %s.</p>\n"
        % html.escape((data["as_of"] or "").replace("T", " ").replace("Z", " UTC")),
        "<h2>Clark County: pass@1 and cost per working extractor</h2>\n"
        "<p>Roster models under protocol v2, by list price per million output tokens. "
        "Intervals are 95% Wilson; the cost range is the 95% range of the simulation "
        "(Jeffreys prior).</p>\n",
        _table("t-price", "Clark County, protocol v2, baseline prompt",
               ["Model", "$ / M output", "Passed", "pass@1", "95% interval",
                "Cost per draw", "Cost per success", "95% range"], price_rows),
        "<h2>Clark County: rankings the data settles</h2>\n"
        "<p>Pairs of roster models where the probability that the first is cheaper per "
        "working extractor is at least 0.975 under both priors. \"Reverses\" marks the pairs "
        "where the first costs more per token.</p>\n",
        _table("t-rank", "Settled rankings, cheaper per success first",
               ["Cheaper per success", "Dearer per success", "Price per token",
                "Reverses", "Times cheaper (95% range)", "P (Jeffreys / uniform)"],
               rank_rows, left=2),
        "<h2>Every draw, by outcome</h2>\n"
        "<p>Protocol v2, baseline prompt. A host failure is a draw the host failed twice; it "
        "is retried and not counted in the rate.</p>\n",
        _table("t-draws", "Draws per model and portal",
               ["Model", "Portal", "Draws"] + [h for _, h in OUTCOME_COLUMNS],
               draw_rows, left=2),
        "<h2>Pass here, fail there</h2>\n"
        "<p>Each roster model's pass@1 on the three portals, protocol v2, baseline prompt. "
        "Santa Barbara was held out: no prompt was written against it.</p>\n",
        _table("t-ports", "pass@1 by portal, with 95% Wilson intervals",
               ["Model"] + [v.split(",")[0] for v in data["targets"].values()],
               port_rows, left=1),
        "<h2>The hint, and the v1 settings against v2</h2>\n"
        "<p>Differences in pass@1 with 95% Newcombe intervals. An effect is claimed only "
        "where the interval excludes zero.</p>\n",
        _table("t-effects", "Hint minus baseline, and v2 minus v1",
               ["Model", "Comparison", "Before", "After", "Difference (95%)",
                "Effect claimed"], effect_rows, left=2),
        "<h2>Keeping the first of five draws a check accepts</h2>\n"
        "<p>Offline, on the draws already bought. Per cell, five draws in a random order, "
        "keeping the first that a check with no reference accepts: the chance the kept "
        "extractor passes, averaged over %d orders, beside an oracle's pass@5.</p>\n"
        % bo5.get("orders", 0),
        _table("t-best", "pass@1 and best-of-5 with the check, protocol v2, baseline prompt",
               ["Model", "Portal", "Passed", "pass@1", "Best of 5, check", "pass@5, oracle"],
               best_rows, left=2),
        "<h2>Settings and hosts</h2>\n"
        "<p>What each model was sent under protocol v2, the hosts that served its scored "
        "draws, and the draws re-drawn at a higher output cap after a cut-off.</p>\n",
        _table("t-settings", "Settings per model",
               ["Model", "Reasoning effort", "Temperature", "top_p", "Re-drawn", "Hosts"],
               setting_rows, left=2, wrap=(5,)),
        "<h2>GLM-5.3 Flash's calls, by duration</h2>\n"
        "<p>Every protocol v2 synthesis call of the model whose hosts closed streams "
        "early.</p>\n",
        _table("t-wall", "Calls by duration",
               ["Host", "Seconds", "Output tokens", "What happened"], wall_rows, left=1),
        "\n</body>\n</html>\n",
    ]
    return "".join(parts)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    vpath = os.path.join(INFER, "variance.json")
    if not os.path.exists(vpath):
        raise SystemExit("no data/infer/variance.json; run the experiments first")
    v = fileio.read_json(vpath)
    lpath = os.path.join(INFER, "ledger.jsonl")
    ledger = infer.Ledger(lpath).rows() if os.path.exists(lpath) else []
    apath = os.path.join(INFER, "verifier", "field_audit.json")
    if not os.path.exists(apath):
        raise SystemExit("no %s; run scripts/field_audit.py first"
                         % os.path.relpath(apath, ROOT))
    caption = fileio.read_json(CAPTION) if os.path.exists(CAPTION) else None
    bok = fileio.read_json(BEST_OF_K) if os.path.exists(BEST_OF_K) else None
    clash = fileio.read_json(NAME_CLASH) if os.path.exists(NAME_CLASH) else None
    data = build(v, ledger, fileio.read_json(apath), caption, bok, clash)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with io.open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render(data))
    tables = os.path.join(os.path.dirname(os.path.abspath(args.out)), "tables.html")
    with io.open(tables, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_tables(data))
    print("wrote %s  (%d models, %d cells, %d draws, %d pairs, as of %s)"
          % (os.path.relpath(args.out, ROOT), len(data["models"]),
             len(data["cells"]), len(data["draws"]), len(data["pairs"]),
             data["as_of"]))


if __name__ == "__main__":
    main()
