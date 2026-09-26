# -*- coding: utf-8 -*-
"""Recompute every figure in the 2026-09-26 model-comparison fairness audit.

Offline. Reads the inference ledger and variance cells from the private store
and two OpenRouter snapshots saved beside them:

    data/audit/2026-09-25-openrouter-models.json    GET /api/v1/models
    data/audit/2026-09-25-openrouter-rankings.html  GET /rankings

Both were fetched with plain curl on 2026-09-25; see the report for the
commands. The rankings page embeds its weekly top-20 table in the
server-rendered payload, which is what `rankings_top20` parses. The
per-category (programming) view is rendered client-side and is not in the
snapshot.

    python spikes/audit_model_fairness.py
"""
import collections
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from permits import infer  # noqa: E402

LEDGER = os.path.join(ROOT, "data", "infer", "ledger.jsonl")
VARIANCE = os.path.join(ROOT, "data", "infer", "variance.json")
MODELS = os.path.join(ROOT, "data", "audit", "2026-09-25-openrouter-models.json")
RANKINGS = os.path.join(ROOT, "data", "audit", "2026-09-25-openrouter-rankings.html")

ROSTER_OR = ["qwen/qwen3.5-flash-02-23", "openai/gpt-oss-120b", "qwen/qwen3-coder",
             "moonshotai/kimi-k2-thinking", "z-ai/glm-5.2", "deepseek/deepseek-v4-pro",
             "z-ai/glm-5.3-flash", "deepseek/deepseek-v4-flash"]


def ledger():
    with io.open(LEDGER, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def section(title):
    print("\n== %s" % title)


def reasoning_support(catalogue):
    """F2: which roster models OpenRouter says accept `reasoning`, against
    the harness's own OPENROUTER_REASONING set."""
    section("F2 reasoning support: catalogue vs OPENROUTER_REASONING")
    by = {m["id"]: m for m in catalogue}
    for mid in ROSTER_OR:
        sp = by[mid].get("supported_parameters") or []
        print("  %-32s catalogue=%-5s harness=%-5s max_completion=%s"
              % (mid, "reasoning" in sp, mid in infer.OPENROUTER_REASONING,
                 (by[mid].get("top_provider") or {}).get("max_completion_tokens")))


def output_tokens_per_cell(cells):
    """F1, F2: output tokens per draw against each cell's answer budget."""
    section("F1/F2 output tokens per variance cell (synth_tokens = answer budget)")
    for key, c in sorted(cells.items()):
        outs = sorted(d["output_tokens"] for d in c["detail"] if d.get("output_tokens"))
        if not outs:
            continue
        print("  %-45s synth_tokens=%-6s n=%-3d perfect=%-3d out min/med/max %d/%d/%d"
              % (key, c.get("synth_tokens"), c["draws_attempted"], c["perfect"],
                 outs[0], outs[len(outs) // 2], outs[-1]))


def truncations(rows):
    """F1: every synthesis call that stopped at its ceiling."""
    section("F1 synthesis calls that stopped at max_tokens")
    for r in rows:
        if r.get("call_class") == "synthesis" and r.get("stop_reason") == "max_tokens":
            print("  %s %-32s %-14s out=%d" % (r["at"], r["model"], r.get("tag"),
                                               r.get("output_tokens", 0)))


def kimi(cells):
    """R1: the kimi-k2-thinking Clark cell, draw by draw."""
    section("R1 clarkco|moonshotai/kimi-k2-thinking")
    c = cells["clarkco|moonshotai/kimi-k2-thinking"]
    print("  n=%d perfect=%d outcomes=%s" % (c["draws_attempted"], c["perfect"], c["outcomes"]))
    for d in c["detail"]:
        print("  draw %d %-10s out=%-6s recall_mean=%s"
              % (d["draw"], d.get("outcome"), d.get("output_tokens"), d.get("recall_mean")))


def throughput(rows):
    """F5: slowest OpenRouter calls, and what a full reasoning ceiling would
    take at that rate."""
    section("F5 slowest OpenRouter calls")
    ceiling = infer.ceiling_for("moonshotai/kimi-k2-thinking", 16000)
    orr = [r for r in rows if r.get("provider") == infer.OPENROUTER and r.get("seconds")]
    for r in sorted(orr, key=lambda r: -r["seconds"])[:5]:
        rate = r["output_tokens"] / r["seconds"]
        print("  %-30s %6.1fs %6d tok %6.1f tok/s -> %d-token ceiling in %.0fs (timeout %.0fs)"
              % (r["model"], r["seconds"], r["output_tokens"], rate, ceiling,
                 ceiling / rate, infer.TIMEOUT_S))


def roster_age(catalogue):
    """F9: release dates of the roster and of the newer models it omits."""
    import datetime
    section("F9 release dates (catalogue `created`)")
    by = {m["id"]: m for m in catalogue}
    for mid in ROSTER_OR + ["anthropic/claude-opus-5", "anthropic/claude-opus-5.5",
                            "anthropic/claude-fable-5.1", "anthropic/claude-sonnet-5",
                            "anthropic/claude-haiku-4.5"]:
        m = by.get(mid)
        if not m:
            print("  %-32s not in catalogue" % mid)
            continue
        p = m["pricing"]
        print("  %-32s %s  in %.3f out %.3f $/M"
              % (mid, datetime.date.fromtimestamp(m["created"]),
                 float(p["prompt"]) * 1e6, float(p["completion"]) * 1e6))


def rankings_top20():
    """F9: OpenRouter's weekly top 20 by total tokens, as embedded in the page."""
    section("F9 OpenRouter weekly top 20 by tokens (all categories)")
    with io.open(RANKINGS, encoding="utf-8") as fh:
        s = fh.read().replace('\\"', '"')
    rows = re.findall(r'\{"date":"([0-9-]+) 00:00:00","model_permaslug":"([^"]+)",'
                      r'"variant":"([^"]+)","total_completion_tokens":(\d+),'
                      r'"total_prompt_tokens":(\d+)', s)
    tot = collections.Counter()
    for _date, slug, variant, c, p in rows:
        tot[slug + ("" if variant == "standard" else ":" + variant)] += int(c) + int(p)
    total = sum(tot.values())
    print("  week dated %s, %d rows" % (sorted({r[0] for r in rows})[-1], len(rows)))
    for slug, t in tot.most_common():
        print("  %-52s %5.1f%%" % (slug, 100.0 * t / total))


def main():
    rows = ledger()
    with io.open(VARIANCE, encoding="utf-8") as fh:
        cells = json.load(fh)["cells"]
    with io.open(MODELS, encoding="utf-8") as fh:
        catalogue = json.load(fh)["data"]
    truncations(rows)
    output_tokens_per_cell(cells)
    reasoning_support(catalogue)
    throughput(rows)
    kimi(cells)
    roster_age(catalogue)
    rankings_top20()


if __name__ == "__main__":
    main()
