# -*- coding: utf-8 -*-
"""Snapshot the sources the step 6 roster's registry entries are set from.

For each roster model not yet in `permits/models.py`:

- its OpenRouter endpoint listing (hosts, precisions, prices, parameters);
- for an open-weight model (the catalogue names a Hugging Face id), the
  repo's `config.json`, `generation_config.json`, model card and chat
  template.

The v1 models re-run under v2 get their endpoint listing too, so every
OpenRouter entry is checked against one day's listing
(`tests/test_models.py`).

    python spikes/fetch_roster_sources.py

Writes
    data/audit/2026-09-27-roster-endpoints.json   {model id: endpoint listing}
    data/audit/2026-09-27-roster-hf.json          {model id: {hf, dtype, quantization_config,
                                                   generation_config, files}}
    data/audit/2026-09-27-roster-cards/<org>_<repo>_README.md
    data/audit/2026-09-27-roster-cards/<org>_<repo>_chat_template.jinja

Public, unauthenticated GETs; no key is sent. A re-run overwrites.
"""
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT = os.path.join(ROOT, "data", "audit")
CATALOGUE = os.path.join(AUDIT, "2026-09-27-openrouter-models.json")
ENDPOINTS = os.path.join(AUDIT, "2026-09-27-roster-endpoints.json")
HF = os.path.join(AUDIT, "2026-09-27-roster-hf.json")
CARDS = os.path.join(AUDIT, "2026-09-27-roster-cards")
UA = {"User-Agent": "buildscope-audit"}

# The 17 roster models the registry lacked in the pre-registration
# (docs/evidence/2026-09-27-v2-run-preregistration.md), and qwen3.8-max-0902,
# which replaced qwen3.8-max-prime when the two "-prime" picks were found to be
# speed variants of the same weights.
# Opus 5.5 is called on Anthropic's API; its OpenRouter listing is still
# snapshotted, for the catalogue's efforts and output limit.
NEW = [
    "anthropic/claude-opus-5.5", "openai/gpt-6-sol", "openai/gpt-6-luna",
    "google/gemini-3.8-flash", "google/gemini-3.5-flash-lite", "x-ai/grok-4.7",
    "moonshotai/kimi-k3", "z-ai/glm-5.3-prime", "z-ai/glm-5.3",
    "qwen/qwen3.8-max-prime", "qwen/qwen3.8-max-0902", "qwen/qwen3.8-flash",
    "deepseek/deepseek-v4-pro-0813", "deepseek/deepseek-v4.1-flash",
    "xiaomi/mimo-v2.6-pro", "xiaomi/mimo-v2.6-flash", "minimax/minimax-m3",
    "tencent/hy3",
]
BRIDGE = [
    "z-ai/glm-5.2", "deepseek/deepseek-v4-pro", "deepseek/deepseek-v4-flash",
    "moonshotai/kimi-k2-thinking", "openai/gpt-oss-120b",
    "qwen/qwen3.5-flash-02-23", "qwen/qwen3-coder", "z-ai/glm-5.3-flash",
]


def get(url, parse=True):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        return {"_error": e.code}
    finally:
        time.sleep(0.5)
    return json.loads(body) if parse else body.decode("utf-8", "replace")


def main():
    with io.open(CATALOGUE, encoding="utf-8") as fh:
        cat = json.load(fh)
    by = {m["id"]: m for m in (cat["data"] if isinstance(cat, dict) else cat)}

    eps = {}
    for mid in NEW + BRIDGE:
        eps[mid] = get("https://openrouter.ai/api/v1/models/%s/endpoints" % mid)
        n = len(((eps[mid].get("data") or {}).get("endpoints")) or [])
        print("endpoints %-34s %d" % (mid, n))
    with io.open(ENDPOINTS, "w", encoding="utf-8") as fh:
        json.dump(eps, fh, indent=1)

    os.makedirs(CARDS, exist_ok=True)
    hf = {}
    for mid in NEW:
        repo = by[mid].get("hugging_face_id")
        if not repo:
            continue
        base = "https://huggingface.co/%s/resolve/main/" % repo
        info = get("https://huggingface.co/api/models/%s" % repo)
        cfg = get(base + "config.json")
        gen = get(base + "generation_config.json")
        card = get(base + "README.md", parse=False)
        template = get(base + "chat_template.jinja", parse=False)
        for suffix, text in (("_README.md", card),
                             ("_chat_template.jinja", template)):
            if isinstance(text, str):
                name = repo.replace("/", "_") + suffix
                with io.open(os.path.join(CARDS, name), "w",
                             encoding="utf-8") as fh:
                    fh.write(text)
        hf[mid] = {
            "hf": repo,
            "dtype": cfg.get("torch_dtype") or cfg.get("dtype"),
            "quantization_config": cfg.get("quantization_config"),
            "config_error": cfg.get("_error"),
            "generation_config": gen,
            "files": sorted(s["rfilename"] for s in info.get("siblings", [])
                            if not s["rfilename"].endswith(".safetensors")),
            "card_chars": len(card) if isinstance(card, str) else card,
        }
        print("hf        %-34s %s dtype=%s quant=%s" % (
            mid, repo, hf[mid]["dtype"],
            (cfg.get("quantization_config") or {}).get("quant_method")))
    with io.open(HF, "w", encoding="utf-8") as fh:
        json.dump(hf, fh, indent=1)


if __name__ == "__main__":
    sys.exit(main())
