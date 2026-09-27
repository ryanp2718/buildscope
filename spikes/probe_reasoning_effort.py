# -*- coding: utf-8 -*-
"""What reasoning effort does each OpenRouter host actually apply?

The plan and the reading rules are in
docs/evidence/2026-09-27-openrouter-reasoning-effort.md. Each model's chat
template writes its effective effort into the prompt as text (GLM:
"Reasoning Effort: Max", DeepSeek V4 at max: "Reasoning Effort: Absolute
maximum...", gpt-oss: "Reasoning: medium"), so the model is asked to quote
that line back. One request per (model, request form, endpoint), each pinned
to one endpoint with fallbacks off.

    python spikes/probe_reasoning_effort.py --stage 1       # dry run: plan and worst case
    python spikes/probe_reasoning_effort.py --stage 1 --run --max-spend 0.5
    python spikes/probe_reasoning_effort.py --stage 2 --run --max-spend 3.5
    python spikes/probe_reasoning_effort.py --report

Writes data/audit/2026-09-27-effort-probe.jsonl (one row per call; a re-run
skips calls already recorded without error) and snapshots the endpoint
listing it used to data/audit/2026-09-27-openrouter-endpoints.json.
"""
import argparse
import collections
import datetime
import io
import json
import os
import re
import statistics
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from permits import infer, models  # noqa: E402

AUDIT = os.path.join(ROOT, "data", "audit")
OUT = os.path.join(AUDIT, "2026-09-27-effort-probe.jsonl")
ENDPOINTS = os.path.join(AUDIT, "2026-09-27-openrouter-endpoints.json")

MAX_TOKENS = 4000
# p1 read "before this message" as earlier turns: all 27 stage-1 calls,
# the control included, answered NONE. Kept so its rows stay labelled.
PROMPTS = {
    "p1": ('Before this message, your input may contain a line that begins with '
           'the word "Reasoning". If it does, reply with that line exactly as '
           'written. If it does not, reply NONE. Reply with nothing else.'),
    "p2": ('What reasoning effort level has been set for you in this '
           'conversation (for example low, medium, high or max)? Answer with '
           'that one word, or UNKNOWN if none has been set.'),
    "p3": ('Your system instructions or the text at the very start of your '
           'context may state a reasoning effort, in a line such as '
           '"Reasoning: ..." or "Reasoning Effort: ...". Quote that line '
           'exactly. If your context states no reasoning effort, reply NONE.'),
}
PROMPT_ID = "p1"

# form name -> the fields it adds to the body. "v1" is protocol v1's exact
# shape for these models; the rest are protocol v2's `reasoning` object.
V1 = {"reasoning_effort": "medium"}
FORMS = {
    "z-ai/glm-5.2": ["v1", "none", "enabled", "high", "xhigh", "max"],
    "z-ai/glm-5.3-flash": ["v1", "none", "enabled", "low", "high", "max"],
    "deepseek/deepseek-v4-pro": ["v1", "none", "enabled", "high", "xhigh", "max"],
    "deepseek/deepseek-v4-flash": ["v1", "none", "enabled", "high", "xhigh", "max"],
    # The control: its mapping is known, so the readout must return what is sent.
    "openai/gpt-oss-120b": ["low", "medium", "high"],
}

# Stage 1: one endpoint per model, every form. Whether an unlisted effort is
# mapped or passed through is decided at OpenRouter, so one host answers it;
# the lab's own endpoint where it has one.
STAGE1_HOST = {
    "z-ai/glm-5.2": "z-ai/fp8",
    "z-ai/glm-5.3-flash": "z-ai/fp8",
    "deepseek/deepseek-v4-pro": "novita/fp8",
    "deepseek/deepseek-v4-flash": "novita/fp8",
    "openai/gpt-oss-120b": "deepinfra/bf16",
}
# Stage 2 was to be every endpoint, with v1's form and the form stage 1
# showed reaches the lab's default level. Stage 1 showed the readout fails
# (the gpt-oss control quoted its effort line once in six), but DeepSeek V4's
# Think Max paragraph adds 79 native prompt tokens (49 -> 128), which the
# generation record reports. So stage 2 covers DeepSeek only, on that signal,
# with the forms that separate max from high on every endpoint.
STAGE2_FORMS = ["v1", "none", "high", "xhigh", "max"]
GENERATIONS = os.path.join(AUDIT, "2026-09-27-effort-probe-generations.json")


def fields(form):
    if form == "v1":
        return dict(V1)
    if form == "none":
        return {}
    if form == "enabled":
        return {"reasoning": {"enabled": True}}
    return {"reasoning": {"effort": form}}


def readout(text):
    """The effort the reply quotes, normalised to the lab's level name."""
    t = (text or "").strip()
    if re.search(r"absolute maximum", t, re.I):
        return "max"
    m = re.search(r"Reasoning Effort:\s*(\w+)", t, re.I) or re.search(r"Reasoning:\s*(\w+)", t, re.I)
    if m:
        return m.group(1).lower()
    if re.fullmatch(r"\W*(none|unknown)\W*", t, re.I):
        return "none"
    m = re.fullmatch(r"\W*(minimal|low|medium|high|xhigh|max|maximum)\W*", t, re.I)
    if m:
        return {"maximum": "max"}.get(m.group(1).lower(), m.group(1).lower())
    return "other" if t else "empty"


def fetch_endpoints(refresh):
    if os.path.exists(ENDPOINTS) and not refresh:
        with io.open(ENDPOINTS, encoding="utf-8") as fh:
            return json.load(fh)
    out = {}
    for mid in FORMS:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/models/%s/endpoints" % mid,
            headers={"User-Agent": "buildscope-audit"})
        out[mid] = json.load(urllib.request.urlopen(req, timeout=30))
    with io.open(ENDPOINTS, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    return out


def plan(endpoints, stage):
    calls = []
    for mid, forms in FORMS.items():
        if stage == 1:
            calls += [(mid, STAGE1_HOST[mid], f) for f in forms]
            continue
        if not mid.startswith("deepseek/"):
            continue
        slugs = []
        for e in endpoints[mid]["data"]["endpoints"]:
            if e["tag"] not in slugs:
                slugs.append(e["tag"])
        calls += [(mid, s, f) for s in slugs for f in STAGE2_FORMS]
    return calls


def done():
    rows = {}
    if os.path.exists(OUT):
        with io.open(OUT, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    r = json.loads(line)
                    if r.get("prompt", "p1") == PROMPT_ID:
                        rows[(r["model"], r["slug"], r["form"])] = r
    return rows


def body(mid, slug, form):
    b = {"model": mid, "max_tokens": MAX_TOKENS,
         "messages": [{"role": "user", "content": PROMPTS[PROMPT_ID]}]}
    b.update(fields(form))
    provider = {"only": [slug], "allow_fallbacks": False}
    if form != "v1":
        # v2's routing, minus the precision filter the pin replaces.
        provider["require_parameters"] = True
        s = models.get(mid)
        b["temperature"], b["top_p"] = s.temperature, s.top_p
    b["provider"] = provider
    return b


def call(client, b):
    extra = {k: b[k] for k in ("reasoning", "provider") if k in b}
    kw = {k: v for k, v in b.items() if k not in extra}
    r = client.chat.completions.create(extra_body=extra, timeout=600, **kw)
    d = r.model_dump()
    u = d.get("usage") or {}
    msg = d["choices"][0]["message"] if d.get("choices") else {}
    return {
        "id": d.get("id"),
        "host": d.get("provider"),
        "reply": msg.get("content"),
        "reasoning": msg.get("reasoning"),
        "finish": d["choices"][0].get("finish_reason") if d.get("choices") else None,
        "completion_tokens": u.get("completion_tokens"),
        "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens"),
        "cost": u.get("cost"),
        "prompt_tokens": u.get("prompt_tokens"),
    }


def run(calls, max_spend):
    import openai
    client = openai.OpenAI(base_url=infer.OPENROUTER_BASE_URL,
                           api_key=infer.read_openrouter_key(), max_retries=1)
    have = done()
    spent = sum((r.get("cost") or 0) for r in have.values())
    todo = [c for c in calls if c not in have or have[c].get("error")]
    print("%d calls, %d to do, $%.4f already spent" % (len(calls), len(todo), spent))
    for i, (mid, slug, form) in enumerate(todo):
        if spent >= max_spend:
            print("stopped at --max-spend $%.2f" % max_spend)
            break
        b = body(mid, slug, form)
        row = {"at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
               "model": mid, "slug": slug, "form": form, "prompt": PROMPT_ID,
               "sent": b}
        try:
            row.update(call(client, b))
            row["readout"] = readout(row["reply"])
        except Exception as e:  # recorded, and retried on the next run
            row["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
            row["status"] = getattr(e, "status_code", None)
        spent += row.get("cost") or 0
        with io.open(OUT, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
        print("%4d/%d %-28s %-22s %-8s -> %-6s rt=%s $%.4f %s" % (
            i + 1, len(todo), mid, slug, form, row.get("readout", "ERR"),
            row.get("reasoning_tokens"), spent, row.get("error", "")[:80]))


def generations():
    """Fetch OpenRouter's record of every probe call not fetched yet. Free.
    `native_tokens_prompt` is the host's own count of the rendered prompt."""
    import time
    have = {}
    if os.path.exists(GENERATIONS):
        with io.open(GENERATIONS, encoding="utf-8") as fh:
            have = {g["id"]: g for g in json.load(fh)}
    key = infer.read_openrouter_key()
    rows = []
    with io.open(OUT, encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    for r in rows:
        if not r.get("id") or (r["id"] in have and "gen" in have[r["id"]]):
            continue
        rec = {"id": r["id"], "model": r["model"], "slug": r["slug"], "form": r["form"],
               "prompt": r.get("prompt", "p1")}
        for _ in range(5):
            try:
                req = urllib.request.Request(
                    "https://openrouter.ai/api/v1/generation?id=" + r["id"],
                    headers={"Authorization": "Bearer " + key})
                rec["gen"] = json.load(urllib.request.urlopen(req, timeout=30))["data"]
                break
            except Exception as e:  # the record can lag the response
                rec["error"] = str(e)[:200]
                time.sleep(3)
        have[r["id"]] = rec
    with io.open(GENERATIONS, "w", encoding="utf-8") as fh:
        json.dump(list(have.values()), fh, indent=1)
    return have


def report():
    rows = list(done().values())
    by = collections.defaultdict(list)
    for r in rows:
        by[(r["model"], r["form"])].append(r)
    for (mid, form), rs in sorted(by.items()):
        ok = [r for r in rs if not r.get("error")]
        reads = collections.Counter(r["readout"] for r in ok)
        rt = [r["reasoning_tokens"] for r in ok if r.get("reasoning_tokens") is not None]
        errs = collections.Counter(str(r.get("status")) for r in rs if r.get("error"))
        print("%-28s %-8s n=%-3d readout=%s reasoning_p50=%s errors=%s" % (
            mid, form, len(ok), dict(reads), statistics.median(rt) if rt else None,
            dict(errs) or "-"))
    print("\nper host, where a form's readout is not unanimous:")
    for (mid, form), rs in sorted(by.items()):
        ok = [r for r in rs if not r.get("error")]
        if len({r["readout"] for r in ok}) > 1:
            for r in sorted(ok, key=lambda r: r["slug"]):
                print("  %-28s %-8s %-22s %-6s rt=%s host=%s" % (
                    mid, form, r["slug"], r["readout"], r.get("reasoning_tokens"), r.get("host")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--generations", action="store_true")
    ap.add_argument("--refresh-endpoints", action="store_true")
    ap.add_argument("--stage", type=int, choices=(1, 2), default=1)
    ap.add_argument("--prompt", choices=sorted(PROMPTS), default="p1")
    ap.add_argument("--only", help="restrict to one model id")
    ap.add_argument("--max-spend", type=float, default=0.0)
    a = ap.parse_args()
    global PROMPT_ID
    PROMPT_ID = a.prompt
    if a.generations:
        return generations()
    if a.report:
        return report()
    calls = plan(fetch_endpoints(a.refresh_endpoints), a.stage)
    if a.only:
        calls = [c for c in calls if c[0] == a.only]
    worst = sum(models.get(m).price[1] * MAX_TOKENS / 1e6 + models.get(m).price[0] * 200 / 1e6
                for m, _, _ in calls)
    per = collections.Counter(m for m, _, _ in calls)
    for m, n in per.items():
        print("  %-28s %4d calls  worst $%.2f" % (m, n, n * (models.get(m).price[1] * MAX_TOKENS
                                                             + models.get(m).price[0] * 200) / 1e6))
    print("%d calls, worst case $%.2f at %d output tokens each" % (len(calls), worst, MAX_TOKENS))
    if a.run:
        run(calls, a.max_spend)


if __name__ == "__main__":
    main()
