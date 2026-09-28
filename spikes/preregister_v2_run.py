# -*- coding: utf-8 -*-
"""Inputs to the step 6 pre-registration: the roster rule applied to today's
catalogue, the frozen prompt's hash, and the cost projection.

Offline. Reads snapshots saved on 2026-09-27 and the inference ledger:

    data/audit/2026-09-27-openrouter-models.json    GET /api/v1/models
    data/audit/2026-09-27-openrouter-rankings.html  GET /rankings (curl -A "Mozilla/5.0")
    data/infer/ledger.jsonl
    data/infer/model_stats.json      (v1 pass rates, for the stopping estimate)

    python spikes/preregister_v2_run.py

Prints; writes nothing. The report is
docs/evidence/2026-09-27-v2-run-preregistration.md.
"""
import collections
import datetime
import hashlib
import io
import json
import os
import re
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import conformance  # noqa: E402

MODELS = os.path.join(ROOT, "data", "audit", "2026-09-27-openrouter-models.json")
RANKINGS = os.path.join(ROOT, "data", "audit", "2026-09-27-openrouter-rankings.html")
LEDGER = os.path.join(ROOT, "data", "infer", "ledger.jsonl")
STATS = os.path.join(ROOT, "data", "infer", "model_stats.json")

CAP = 64000
N = 20          # baseline draws per cell, at most
STAGE1 = 10     # two-stage rule: stop at 10 when 0/10 or 10/10
HINT_N = 10     # hint ablation, Clark only, fixed n
TARGETS = ("clarkco", "stjohns")     # targets with ledger history

# The pre-registered plan: (target, condition, draws, who). `draws` is an int
# for a fixed n, or "two-stage". `who` is the set of tiers the cell runs for;
# "v1" is the BRIDGE set. Chosen 2026-09-27 (option "B+C" plus the held-out
# target): Clark baseline two-stage; St. Johns fixed at 10; the hint on Clark
# for every tier but the top; Santa Barbara, held out, at 5 for the roster.
ROSTER_TIERS = {"top", "mid", "cheap"}
PLAN = [
    ("clarkco", "baseline", "two-stage", ROSTER_TIERS | {"v1"}),
    ("stjohns", "baseline", 10, ROSTER_TIERS | {"v1"}),
    ("clarkco", "hint", HINT_N, {"mid", "cheap", "v1"}),
    ("santabarbara", "baseline", 5, ROSTER_TIERS),
]
# The alternatives the plan was chosen from, for the record.
_SJ_TWO_STAGE = ("stjohns", "baseline", "two-stage", ROSTER_TIERS | {"v1"})
ALTERNATIVES = [
    ("A: no hint arm", [PLAN[0], _SJ_TWO_STAGE]),
    ("B: hint below the top tier, St. Johns two-stage",
     [PLAN[0], _SJ_TWO_STAGE, PLAN[2]]),
    ("B+C: and St. Johns fixed at 10", PLAN[:3]),
    ("B+C + Santa Barbara at 5 (pre-registered)", PLAN),
]
# A held-out target has no ledger history; its draws are costed as Clark's,
# the same vendor and the same 24,000-character window.
PROXY = {"santabarbara": "clarkco"}

# The roster rule: each lab's current generally available model at each
# position in its own lineup. Tier is the lab's positioning, not a price
# band; price is the x-axis of the result. Preview, stealth, `:free`,
# `:batch`, moving aliases (`~...-latest`) and task variants (image, vision,
# omni, code, ultraspeed) are excluded. `-pro` siblings priced the same as
# their base are excluded as unexplained duplicates, and so are speed
# variants of the same weights (`-prime`, `-flashx`), which the catalogue
# describes as such.
#
# (lab, tier, catalogue id, why this one)
ROSTER = [
    ("anthropic", "top", "anthropic/claude-opus-5.5", "replaces Opus 5 (2026-09-22)"),
    ("anthropic", "mid", "anthropic/claude-sonnet-5", ""),
    ("anthropic", "cheap", "anthropic/claude-haiku-4.5", "no successor; 2025-10"),
    ("openai", "mid", "openai/gpt-6-sol", ""),
    ("openai", "cheap", "openai/gpt-6-luna", ""),
    ("google", "mid", "google/gemini-3.8-flash", ""),
    ("google", "cheap", "google/gemini-3.5-flash-lite", ""),
    ("x-ai", "top", "x-ai/grok-4.7", "xAI's one current general model"),
    ("moonshotai", "top", "moonshotai/kimi-k3", ""),
    ("z-ai", "top", "z-ai/glm-5.3", "Z.ai's flagship; was glm-5.3-prime"),
    ("z-ai", "cheap", "z-ai/glm-5.3-flash", "already in the registry"),
    ("qwen", "top", "qwen/qwen3.8-max-0902", "dated Max snapshot; was -prime"),
    ("qwen", "cheap", "qwen/qwen3.8-flash", ""),
    ("deepseek", "mid", "deepseek/deepseek-v4-pro-0813", "pinned snapshot"),
    ("deepseek", "cheap", "deepseek/deepseek-v4.1-flash", "v4.1 has no dated id"),
    ("xiaomi", "mid", "xiaomi/mimo-v2.6-pro", ""),
    ("xiaomi", "cheap", "xiaomi/mimo-v2.6-flash", ""),
    ("minimax", "mid", "minimax/minimax-m3", ""),
    ("tencent", "cheap", "tencent/hy3", "hy4 is a preview"),
]

# The $10 / $50 flagships, anthropic/claude-fable-5.1 and openai/gpt-6-astra,
# are left out for cost: together about half the projected spend. Opus 5.5 is
# Anthropic's top entry instead, and OpenAI has no top-tier entry. Decided
# 2026-09-27.
#
# Google's only Pro model is google/gemini-3.1-pro-preview. The rule excludes
# previews, since a preview id can change under a run, so Google has no top
# tier. Decided 2026-09-27.

# Amended 2026-09-27, before any draw: the first roster took
# z-ai/glm-5.3-prime (top) and qwen/qwen3.8-max-prime (top). The catalogue
# describes both as higher-throughput variants of the same weights as
# glm-5.3 and qwen3.8-max, which the rule excludes, as it already excluded
# glm-5.3-flashx. glm-5.3 moves to Z.ai's top tier, leaving Z.ai no mid entry;
# Qwen's top is the dated Max snapshot.

# Models with v1 cells that are not on the roster. Run under v2 they measure
# what the configuration fixes alone did to a pass rate, holding the model
# fixed. Opus 5 is left out for cost (about $15 of the $20 this set would
# cost); Opus 5.5 is on the roster. Decided 2026-09-27.
BRIDGE = [
    "z-ai/glm-5.2", "deepseek/deepseek-v4-pro",
    "deepseek/deepseek-v4-flash", "moonshotai/kimi-k2-thinking",
    "openai/gpt-oss-120b", "qwen/qwen3.5-flash-02-23", "qwen/qwen3-coder",
]

# Ledger names for the models the harness has called, by catalogue id.
LEDGER_ID = {
    "anthropic/claude-opus-5": "claude-opus-5",
    "anthropic/claude-opus-5.5": "claude-opus-5-5",
    "anthropic/claude-sonnet-5": "claude-sonnet-5",
    "anthropic/claude-haiku-4.5": "claude-haiku-4-5-20251001",
}

EXCLUDE = re.compile(r"preview|stealth|:free|:batch|^~|image|vision|omni|-code\b|"
                     r"ultraspeed|multi-agent|lyria|gemma|-mt\d|-prime\b|-flashx\b")

# Output tokens per draw for a model never called: the observed range of the
# reasoning models on the v1 roster, Clark and St. Johns pooled. p50 of the
# per-model medians is about 8,000 and the largest p90 about 30,000.
UNSEEN_P50, UNSEEN_P90 = 10000, 30000


def load():
    with io.open(MODELS, encoding="utf-8") as fh:
        cat = {m["id"]: m for m in json.load(fh)["data"]}
    with io.open(LEDGER, encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    return cat, rows


def created(m):
    return datetime.datetime.fromtimestamp(m.get("created", 0), datetime.UTC).date()


def price(m):
    p = m["pricing"]
    return float(p["prompt"]) * 1e6, float(p["completion"]) * 1e6


def section(title):
    print("\n== %s" % title)


def prompt_hashes():
    section("Frozen prompt")
    for name in ("CONTRACT", "SYNTH_SYSTEM", "SYNTH_HINT"):
        s = getattr(conformance, name)
        print("  %-13s sha256=%s  %d chars" % (name, hashlib.sha256(s.encode("utf-8")).hexdigest(),
                                               len(s)))


def roster_check(cat):
    """Each roster entry exists, and no generally available model from the
    same lab is newer in a way the rule would have picked instead."""
    section("Roster against the 2026-09-27 catalogue")
    for lab, tier, mid, why in ROSTER:
        m = cat.get(mid)
        if m is None:
            print("  MISSING %s" % mid)
            continue
        pi, po = price(m)
        r = m.get("reasoning") or {}
        tp = m.get("top_provider") or {}
        print("  %-10s %-5s %-34s %s  $%6.3f / $%6.2f  efforts=%s default=%s mandatory=%s"
              "  max_out=%s  %s"
              % (lab, tier, mid, created(m), pi, po, r.get("supported_efforts"),
                 r.get("default_effort"), r.get("mandatory"), tp.get("max_completion_tokens"),
                 why))
    section("Other generally available models from roster labs, released since the "
            "lab's oldest roster pick")
    chosen = {mid for _, _, mid, _ in ROSTER}
    by_lab = collections.defaultdict(list)
    for mid, m in cat.items():
        by_lab[mid.split("/")[0]].append(m)
    for lab in sorted({lab for lab, _, _, _ in ROSTER}):
        oldest = min(created(cat[mid]) for la, _, mid, _ in ROSTER if la == lab and mid in cat)
        for m in sorted(by_lab[lab], key=created, reverse=True):
            if m["id"] in chosen or EXCLUDE.search(m["id"]) or created(m) <= oldest:
                continue
            pi, po = price(m)
            print("  %-10s %-40s %s  $%6.3f / $%6.2f" % (lab, m["id"], created(m), pi, po))


def rankings():
    section("OpenRouter weekly top 20 by tokens, by lab (all categories)")
    with io.open(RANKINGS, encoding="utf-8") as fh:
        s = fh.read().replace('\\"', '"')
    rows = re.findall(r'\{"date":"([0-9-]+) 00:00:00","model_permaslug":"([^"]+)",'
                      r'"variant":"([^"]+)","total_completion_tokens":(\d+),'
                      r'"total_prompt_tokens":(\d+)', s)
    lab = collections.Counter()
    for _d, slug, _v, c, p in rows:
        lab[slug.split("/")[0]] += int(c) + int(p)
    total = sum(lab.values())
    print("  week dated %s, %d rows" % (sorted({r[0] for r in rows})[-1], len(rows)))
    print("  " + ", ".join("%s %.1f%%" % (k, 100.0 * v / total) for k, v in lab.most_common()))


def observed(rows):
    """Per (ledger model, target): median input tokens, and output p50/p90."""
    agg = collections.defaultdict(lambda: ([], []))
    for r in rows:
        if r.get("call_class") != "synthesis" or not r.get("output_tokens"):
            continue
        tag = r.get("tag", "")
        tgt = "clarkco" if "clark" in tag else "stjohns" if "stjohns" in tag else None
        if tgt is None:
            continue
        i, o = agg[(r["model"], tgt)]
        i.append(r.get("input_tokens", 0) + r.get("cache_read_input_tokens", 0)
                 + r.get("cache_creation_input_tokens", 0))
        o.append(r["output_tokens"])
    out = {}
    for k, (i, o) in agg.items():
        o = sorted(o)
        out[k] = (statistics.median(i), statistics.median(o), o[int(0.9 * (len(o) - 1))], len(o))
    return out


def input_tokens(obs):
    """Largest per-model median input on each target: the prompt plus the
    window, in the least efficient tokenizer seen."""
    n_in = {t: max(v[0] for k, v in obs.items() if k[1] == t) for t in TARGETS}
    n_in.update({t: n_in[src] for t, src in PROXY.items()})
    return n_in


def pass_rates():
    """Observed v1 baseline pass rate per (ledger model, target), cells of
    five or more scored draws. Used only to estimate how often the two-stage
    rule stops a cell at stage 1."""
    with io.open(STATS, encoding="utf-8") as fh:
        cells = json.load(fh)["cells"]
    return {(c["model"], c["target"]): c["perfect"] / c["draws_scored"]
            for c in cells.values()
            if c["condition"] == "baseline" and c["draws_scored"] >= 5}


def stop_prob(p, n1=STAGE1):
    """P(stage 1 ends 0/n1 or n1/n1) for a true pass rate p."""
    return p ** n1 + (1 - p) ** n1


def expected_draws(mid, tgt, rates, rule):
    if rule != "two-stage":
        return float(rule)
    p = rates.get((LEDGER_ID.get(mid, mid), tgt))
    if p is not None:
        stop = stop_prob(p)
    else:
        prior = [r for (_m, t), r in rates.items() if t == tgt]
        stop = sum(stop_prob(r) for r in prior) / len(prior)
    return STAGE1 + (N - STAGE1) * (1 - stop)


def cell_cost(mid, tgt, k, out_tokens, cat, n_in, cache, batch):
    """Cost of a k-draw cell. Every draw of a cell sends identical input, so
    with an Anthropic cache breakpoint on it the first draw writes the cache
    (1.25x input) and the rest read it (0.1x, 0.05x on Opus 5.5). Other
    providers' automatic caching is not counted."""
    pi, po = price(cat[mid])
    anthropic = mid.startswith("anthropic/")
    read = 0.05 if mid == "anthropic/claude-opus-5.5" else 0.1
    if cache and anthropic and k > 0:
        inp = n_in[tgt] * pi * (1.25 + read * (k - 1))
    else:
        inp = n_in[tgt] * pi * k
    usd = (inp + k * out_tokens * po) / 1e6
    return usd * (0.5 if batch and anthropic else 1.0)


def model_cost(mid, tier, plan, cat, obs, rates, n_in, which, cache=True, batch=False):
    """Every cell of `plan` this model's tier runs, at output p50, p90 or
    the cap. At the cap a two-stage cell is charged all N draws."""
    total = 0.0
    for tgt, _cond, rule, who in plan:
        if tier not in who:
            continue
        src = PROXY.get(tgt, tgt)
        seen = obs.get((LEDGER_ID.get(mid, mid), src))
        p50, p90 = (seen[1], seen[2]) if seen and seen[3] >= 5 else (UNSEEN_P50, UNSEEN_P90)
        out = {"p50": p50, "p90": p90, "cap": CAP}[which]
        if rule == "two-stage":
            k = N if which == "cap" else expected_draws(mid, src, rates, rule)
        else:
            k = float(rule)
        total += cell_cost(mid, src, k, out, cat, n_in, cache, batch)
    return total


def source(mid, obs):
    seen = [bool(obs.get((LEDGER_ID.get(mid, mid), t))) and obs[(LEDGER_ID.get(mid, mid), t)][3] >= 5
            for t in TARGETS]
    return "ledger" if all(seen) else "Clark from ledger" if seen[0] else "assumed"


STAGES = [("1: cheap + v1", {"cheap", "v1"}), ("2: mid", {"mid"}), ("3: top", {"top"})]


def projection(cat, obs):
    rates = pass_rates()
    n_in = input_tokens(obs)
    members = ([(mid, tier) for _, tier, mid, _ in ROSTER] + [(mid, "v1") for mid in BRIDGE])
    section("The plan")
    for tgt, cond, rule, who in PLAN:
        print("  %-13s %-9s %-10s %s" % (tgt, cond, rule, ", ".join(sorted(who))))
    section("Cost per model under the plan (two-stage, Anthropic cache, no batch)")
    print("  input tokens per draw: %s; Santa Barbara costed as Clark; output at the cap: %d"
          % (n_in, CAP))
    print("  output per draw where unobserved: p50 %d, p90 %d" % (UNSEEN_P50, UNSEEN_P90))
    print("  %-36s %-5s %8s %8s %8s  %s" % ("model", "tier", "p50", "p90", "worst", "tokens"))
    for mid, tier in members:
        a, b, c = (model_cost(mid, tier, PLAN, cat, obs, rates, n_in, w)
                   for w in ("p50", "p90", "cap"))
        print("  %-36s %-5s %8.2f %8.2f %8.2f  %s" % (mid, tier, a, b, c, source(mid, obs)))
    section("Totals by stage and billing account, and running total")
    print("  %-14s %-10s %8s %8s %8s   %s" % ("stage", "billed by", "p50", "p90", "worst",
                                             "running p50 / p90 / worst"))
    run = [0.0, 0.0, 0.0]
    for name, tiers in STAGES:
        for who, pick in (("anthropic", True), ("openrouter", False)):
            tot = [sum(model_cost(mid, tier, PLAN, cat, obs, rates, n_in, w)
                       for mid, tier in members
                       if tier in tiers and mid.startswith("anthropic/") is pick)
                   for w in ("p50", "p90", "cap")]
            run = [r + t for r, t in zip(run, tot, strict=True)]
            print("  %-14s %-10s %8.2f %8.2f %8.2f   %.2f / %.2f / %.2f"
                  % (name, who, *tot, *run))
    section("Alternatives considered (all models, p50 / p90)")
    for name, plan in ALTERNATIVES:
        tot = [sum(model_cost(mid, tier, plan, cat, obs, rates, n_in, w)
                   for mid, tier in members) for w in ("p50", "p90")]
        print("  %-48s %8.2f %8.2f" % (name, *tot))
    section("Expected baseline draws per Clark cell under the two-stage rule")
    prior = sorted(r for (_m, t), r in rates.items() if t == "clarkco")
    print("  v1 rates %s -> %.1f draws for a model with no v1 cell"
          % (["%.2f" % r for r in prior], expected_draws("unseen", "clarkco", rates, "two-stage")))
    section("Synthesis window per target (sha256 of page 1's window, 24,000 characters)")
    for key, t in conformance.TARGETS.items():
        pages = conformance.corpus(t)
        if not pages:
            continue
        html = conformance.read(pages[0][1])
        win, frac, at = conformance.window(html, 24000)
        ids = [r.get(t.roles["native_id"]) for r in t.reference(html)]
        print("  %-13s %-5s %-40s at %6d  records %2d of %3d  pages %2d  %s"
              % (key, t.split, pages[0][0], at, sum(1 for i in ids if i and i in win),
                 len(ids), len(pages), hashlib.sha256(win.encode("utf-8")).hexdigest()[:16]))


def main():
    cat, rows = load()
    prompt_hashes()
    roster_check(cat)
    rankings()
    projection(cat, observed(rows))


if __name__ == "__main__":
    main()
