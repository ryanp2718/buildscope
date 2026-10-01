# -*- coding: utf-8 -*-
"""Check that an agent episode's trace reaches LangSmith, before any paid
episode. No model calls, $0.

    python spikes/tracing_check.py

Runs one agent episode against a scripted fake model over a synthetic page
(read the page, run a draft, check it, submit), traced to the
`buildscope-agent-dev` project of docs/evidence/2026-09-29-agentic-extractor-plan.md,
then reads the trace back and prints what arrived: the runs by type and
name, and whether the model calls carry their token counts and cost.

The key comes from `LANGSMITH_API_KEY` or `~/.langsmith_key`
(`permits.agent.graph.enable_tracing`); it is never printed. The trace holds
only the synthetic page and the fake model's replies.
"""
import io
import os
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from permits import infer                                     # noqa: E402
from permits.agent import graph as G                          # noqa: E402
from permits.agent import tools as T                          # noqa: E402

PROJECT = "buildscope-agent-dev"
FIELDS = ["native_id", "issued_date", "address", "permit_type", "status",
          "structure_code", "contractor"]
PAGE = ("<html><body><table><tr><th>Permit</th><th>Issued</th>"
        "<th>Address</th><th>Type</th></tr>%s</table></body></html>" % "".join(
            "<tr><td>B-%d</td><td>01/0%d/2026</td><td>%d Main St</td>"
            "<td>Residential</td></tr>" % (n, n, 100 + n) for n in (1, 2, 3)))
CODE = '''import re

def extract(html):
    out = []
    for tr in re.findall(r"<tr>(.*?)</tr>", html):
        cells = re.findall(r"<td>(.*?)</td>", tr)
        if len(cells) == 4:
            out.append({"native_id": cells[0], "issued_date": cells[1],
                        "address": cells[2], "permit_type": cells[3],
                        "status": None, "structure_code": None,
                        "contractor": None})
    return out
'''
STEPS = [[("read_page", {"page": 0})],
         [("run_extractor", {"code": CODE})],
         [("check", {"code": CODE})],
         [("submit", {"code": CODE})]]


class ScriptedModel(object):
    """Replies with the next scripted tool calls; costs a nominal $0.001 a
    turn so the trace shows where cost lands."""

    def __init__(self, steps):
        self.steps = list(steps)
        self.n = 0

    def converse(self, model, system, messages, tools, **kw):
        self.n += 1
        calls = tuple(infer.ToolCall("c%d_%d" % (self.n, i), name, args)
                      for i, (name, args) in enumerate(self.steps.pop(0)))
        done = infer.Completion(
            text="", usage=infer.Usage(1000, 50), model=model,
            provider=infer.OPENROUTER, cached=False, usd=0.001,
            stop_reason="tool_use", truncated=False)
        return infer.Turn(done, calls, {"role": "assistant", "native": {
            "role": "assistant", "content": None}}, 0.001, 0.001)


def main():
    if not G.enable_tracing():
        print("No LangSmith key: set LANGSMITH_API_KEY or write the key to "
              "%s, then re-run." % G.LANGSMITH_KEY_FILE)
        return 1
    from langchain_core.tracers.langchain import wait_for_all_tracers
    from langsmith import Client

    d = tempfile.mkdtemp()
    page = os.path.join(d, "page0.html")
    with io.open(page, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(PAGE)
    run_id = "tracecheck-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    ep = G.Episode(client=ScriptedModel(STEPS), model="fake/scripted",
                   system="Write an extractor for this portal.",
                   user="Write extract(html).",
                   workspace=T.Workspace([page], FIELDS, os.path.join(d, "w")),
                   run_id=run_id, episode=0, call_class="agent",
                   tag="%s/agent/e00" % run_id, limits=G.Limits())
    summary = G.run(ep, "agent", project=PROJECT)
    print("episode: stop=%s turns=%s submitted=%s" % (
        summary.get("stop"), summary.get("turns"),
        bool(summary.get("submitted"))))
    wait_for_all_tracers()

    client = Client()
    roots = []
    for _ in range(15):
        roots = list(client.list_runs(
            project_name=PROJECT, is_root=True,
            filter='has(tags, "%s")' % run_id, limit=5))
        if roots:
            break
        time.sleep(2)
    if not roots:
        print("FAIL: no trace tagged %s in %s after 30 s" % (run_id, PROJECT))
        return 1
    root = roots[0]
    runs = []
    for _ in range(10):
        runs = list(client.list_runs(project_name=PROJECT,
                                     trace_id=root.trace_id))
        if sum(r.run_type == "llm" for r in runs) >= len(STEPS):
            break
        time.sleep(2)
    print("trace: %s (%d runs)" % (root.name, len(runs)))
    for (kind, name), n in sorted(Counter(
            (r.run_type, r.name) for r in runs).items()):
        print("  %-6s %-24s %d" % (kind, name, n))
    llm = [r for r in runs if r.run_type == "llm"]
    tokens = all((r.outputs or {}).get("usage_metadata") for r in llm)
    cost = all((r.outputs or {}).get("usd") is not None for r in llm)
    print("model calls: %d of %d; token counts on all: %s; cost on all: %s"
          % (len(llm), len(STEPS), tokens, cost))
    print("url: %s" % client.get_run_url(run=root, project_name=PROJECT))
    ok = len(llm) == len(STEPS) and tokens and cost
    print("OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
