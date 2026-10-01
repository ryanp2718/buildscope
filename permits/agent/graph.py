# -*- coding: utf-8 -*-
"""The agent and the scripted repair loop, as LangGraph state graphs.

**The agent** is a ReAct loop: a model node that calls the model with the
tools in `permits.agent.tools`, and a tool node that runs whatever it asked
for, until it calls `submit` or a limit stops it. The model decides what to
look at, when to run or check a draft, and when it is done; nothing forces it
to check before it submits, and how often it does is one of the things
measured.

**The scripted loop** is the control: the same model, pages, checks and
limits, with the order fixed. Draft, run and check every page; if a check
fails, show the model the failures and the draft's own output and ask for a
corrected module; repeat until the checks pass or a limit is hit. The model
gets no tools and answers with a code block, as in a one-shot draw. It is a
workflow, and is called one.

Both call the model through `permits.infer.Client.converse`, so every turn
is priced, logged, cached and held to the process's spend ceiling. The state
is plain data, so LangGraph's checkpointer can store it and an interrupted
episode resumes at its last finished node. Limits per episode:

- turns: model calls, `Limits.turns`;
- dollars: the list-priced cost of the turns so far (`infer.list_cost`:
  tokens at list price, no cache or host discount), checked before each
  turn, so an episode can overshoot by at most one turn. It depends only on
  the tokens, so a replayed episode stops where the original did, and it
  does not depend on which host served a turn. Purchase cost is kept beside
  it.

The agent is told its budget: every tool result, and every nudge, ends
with the turns and list-priced dollars used against the episode's limits, so
it can pace itself. The scripted loop is not told; its order is fixed.

Each turn is recorded in `trajectory` with its cumulative cost and, in
`summarize`, the latest draft after it, so the runner can read the episode
at any smaller limit B. For the scripted loop that is exactly the first B of
the episode. The agent paced itself for its own limit, so for it a smaller B
is the episode cut off at B, not an agent given B.

Tracing: LangGraph sends a trace to LangSmith when `LANGSMITH_TRACING` and
`LANGSMITH_API_KEY` are set, and each model call is a traced "llm" run with
its tokens and cost. Traces are for reading runs; every reported number comes
from the ledger and the scorer.
"""
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, TypedDict

import langsmith
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from permits import infer, sandbox
from permits.agent import tools as T

AGENT_INSTRUCTIONS = """
HOW TO ANSWER IN THIS TASK. You have tools instead of a single reply. You can
list the portal's pages, read or search them, run a draft module on them, and
check a draft's output. The check has no answer key: it compares the number of
rows you return on each page with the rows that page's grid shows, and looks
for missing or repeated ids, markup left in values and dates that do not look
like dates. When your module is ready, call `submit` with the whole module.
Only a submitted module counts; a code block in a text reply is not an answer.

Each tool result ends with your budget: the turns you have taken and the
dollars spent, against your limits. The task ends when either runs out, and a
module you have not submitted by then does not count. Each turn costs more
than the one before, because the whole conversation is sent again.
"""

BUDGET = "Budget: turn %d of at most %d; $%.4f of $%.2f spent (list price)."

NUDGE = ("Use the tools. When your module is ready, call submit with the "
         "whole module; a code block in a text reply is not an answer here.")

REPAIR = """Your module was run on every page of the portal and checked. The
check has no answer key: it compares the rows you return on each page with the
rows the page's grid shows, and looks for missing or repeated ids, markup in
values and dates that do not look like dates.

{check}

What your module returned:
{run}

Write the corrected module. Reply with the whole module in one fenced python
block."""

NO_CODE = """Your reply had no module in it. Reply with the whole module in one
fenced python block, defining extract(html)."""

MAX_NUDGES = 2


@dataclass(frozen=True)
class Limits:
    turns: int = 30
    usd: float = 0.15
    max_tokens: int = 64000


@dataclass
class Episode:
    """Everything an episode needs that is not state: the client, the task
    and where it runs. `review` turns on the human approval step."""
    client: Any
    model: str
    system: str
    user: str
    workspace: T.Workspace
    run_id: str
    episode: int
    call_class: str
    tag: str
    limits: Limits
    review: bool = False


class State(TypedDict, total=False):
    messages: list[dict[str, Any]]
    pending: list[dict[str, Any]]
    turns: int
    usd: float
    list_usd: float
    trajectory: list[dict[str, Any]]
    drafts: dict[str, str]
    nudges: int
    stop: str | None
    error: str | None
    submitted: str | None
    last_code: str | None
    log: list[dict[str, Any]]


def initial_state(ep: Episode) -> State:
    return {"messages": [{"role": "user", "content": ep.user}],
            "pending": [], "turns": 0, "usd": 0.0, "list_usd": 0.0,
            "trajectory": [], "drafts": {}, "nudges": 0,
            "stop": None, "error": None, "submitted": None,
            "last_code": None, "log": []}


# ----------------------------------------------------------- model calls
def _llm_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """What a trace shows as a model call's input: the model and the last
    message, not the whole conversation again on every turn."""
    msgs = inputs.get("messages") or []
    return {"model": inputs.get("model"), "turn_messages": len(msgs),
            "last": msgs[-1] if msgs else None}


def _llm_outputs(turn: Any) -> dict[str, Any]:
    c = turn.completion
    return {"text": c.text, "tool_calls": [asdict(t) for t in turn.tool_calls],
            "stop_reason": c.stop_reason, "cached": c.cached,
            "usage_metadata": {"input_tokens": c.usage.input_tokens,
                               "output_tokens": c.usage.output_tokens,
                               "total_tokens": c.usage.input_tokens
                               + c.usage.output_tokens},
            "usd": c.usd, "purchase_usd": turn.purchase_usd}


@langsmith.traceable(run_type="llm", name="converse",
                     process_inputs=_llm_inputs, process_outputs=_llm_outputs)
def _converse(client: Any, *, model: str, system: str,
              messages: list[dict[str, Any]], tools: list[dict[str, Any]],
              **kw: Any) -> Any:
    return client.converse(model, system, messages, tools, **kw)


def budget(ep: Episode, state: State) -> str:
    """The line the agent sees after each turn: what it has used of its
    limits."""
    return BUDGET % (state["turns"], ep.limits.turns, state["list_usd"],
                     ep.limits.usd)


def _turn(ep: Episode, state: State, system: str,
          tools: list[dict[str, Any]]) -> tuple[Any, State]:
    """One model call, or the stop that prevents it. Returns (turn or None,
    state update)."""
    if state["turns"] >= ep.limits.turns:
        return None, {"stop": "turn_limit"}
    if state["list_usd"] >= ep.limits.usd:
        return None, {"stop": "budget"}
    try:
        turn = _converse(
            ep.client, model=ep.model, system=system,
            messages=state["messages"], tools=tools,
            max_tokens=ep.limits.max_tokens, call_class=ep.call_class,
            run_id=ep.run_id, episode=ep.episode,
            tag="%s/t%02d" % (ep.tag, state["turns"]))
    except infer.TransientError as e:
        return None, {"stop": "infra_error", "error": str(e)[:300]}
    except infer.Refused as e:
        return None, {"stop": "refused", "error": str(e)[:300]}
    c = turn.completion
    n = state["turns"] + 1
    usd = round(state["usd"] + turn.purchase_usd, 6)
    list_usd = round(state["list_usd"] + turn.list_usd, 6)
    step = {"turn": n, "usd": usd, "list_usd": list_usd, "host": c.host,
            "input_tokens": c.usage.input_tokens,
            "cache_read_input_tokens": c.usage.cache_read_input_tokens,
            "output_tokens": c.usage.output_tokens,
            "truncated": c.truncated}
    return turn, {"turns": n, "usd": usd, "list_usd": list_usd,
                  "trajectory": [*state["trajectory"], step]}


# --------------------------------------------------------------- agent
def build_agent(ep: Episode, checkpointer: Any = None) -> Any:
    system = ep.system + AGENT_INSTRUCTIONS
    ws = ep.workspace

    def model(state: State) -> State:
        turn, upd = _turn(ep, state, system, T.TOOLS)
        if turn is None:
            return upd
        msgs = [*state["messages"], turn.message]
        calls = [asdict(c) for c in turn.tool_calls]
        upd.update({"messages": msgs, "pending": calls})
        if not calls:
            if state["nudges"] >= MAX_NUDGES:
                upd["stop"] = "no_tool_call"
            else:
                upd["messages"] = [*msgs, {"role": "user", "content":
                                           NUDGE + "\n\n" + budget(ep, upd)}]
                upd["nudges"] = state["nudges"] + 1
        return upd

    def run_tools(state: State) -> State:
        results, log = [], list(state["log"])
        drafts = dict(state["drafts"])
        submitted = None
        last = state["last_code"]
        for c in state["pending"]:
            entry: dict[str, Any] = {"turn": state["turns"], "tool": c["name"]}
            if submitted is not None:
                text, err = "not run: the task ended at submit", True
            elif c.get("error"):
                text, err = "your call to %s was not run: %s" % (
                    c["name"], c["error"]), True
            elif c["name"] == "submit":
                code = c["arguments"].get("code")
                if isinstance(code, str) and code.strip():
                    submitted = code
                    entry["code"] = T.digest(code)
                    drafts[entry["code"]] = code
                    text, err = "submitted", False
                else:
                    text, err = "submit needs the whole module as code", True
            else:
                text, err = ws.call(c["name"], c["arguments"])
                code = c["arguments"].get("code")
                if isinstance(code, str):
                    entry["code"] = T.digest(code)
                    drafts[entry["code"]] = code
                    last = code
                    if c["name"] == "check":
                        entry["accepted"] = ws.run(code).accepted
            entry["is_error"] = err
            log.append(entry)
            results.append({"id": c["id"], "content": text, "is_error": err})
        if submitted is None and results:
            results[-1]["content"] += "\n\n" + budget(ep, state)
        upd: State = {"messages": [*state["messages"],
                                   {"role": "tool", "results": results}],
                      "pending": [], "log": log, "last_code": last,
                      "drafts": drafts}
        if submitted is not None:
            upd.update({"submitted": submitted, "stop": "submitted"})
        return upd

    def review(state: State) -> State:
        approved = interrupt({"code": state["submitted"]})
        return {} if approved else {"stop": "rejected_in_review"}

    def after_model(state: State) -> str:
        if state.get("stop"):
            return END
        return "tools" if state["pending"] else "model"

    def after_tools(state: State) -> str:
        if state.get("stop") == "submitted":
            return "review" if ep.review else END
        return END if state.get("stop") else "model"

    g = StateGraph(State)
    g.add_node("model", model)
    g.add_node("tools", run_tools)
    g.add_node("review", review)
    g.add_edge(START, "model")
    g.add_conditional_edges("model", after_model, ["tools", "model", END])
    g.add_conditional_edges("tools", after_tools, ["model", "review", END])
    g.add_edge("review", END)
    return g.compile(checkpointer=checkpointer)


# ----------------------------------------------------- scripted loop
def build_scripted(ep: Episode, checkpointer: Any = None) -> Any:
    ws = ep.workspace

    def draft(state: State) -> State:
        turn, upd = _turn(ep, state, ep.system, [])
        if turn is None:
            return upd
        code = sandbox.extract_block(turn.completion.text, sandbox.CODEBLOCK,
                                     "def extract(")
        msgs = [*state["messages"], turn.message]
        upd.update({"messages": msgs, "pending": [{"code": code}]})
        return upd

    def check(state: State) -> State:
        code = state["pending"][0]["code"] if state["pending"] else ""
        log = list(state["log"])
        if "def extract(" not in code:
            log.append({"turn": state["turns"], "tool": "check",
                        "code": None, "accepted": False})
            return {"pending": [], "log": log, "messages": [
                *state["messages"], {"role": "user", "content": NO_CODE}]}
        res = ws.run(code)
        h = T.digest(code)
        log.append({"turn": state["turns"], "tool": "check",
                    "code": h, "accepted": res.accepted})
        upd: State = {"pending": [], "log": log, "last_code": code,
                      "drafts": {**state["drafts"], h: code}}
        if res.accepted:
            upd.update({"submitted": code, "stop": "submitted"})
            return upd
        prompt = REPAIR.format(check=ws.check(code),
                               run=ws.run_extractor(code, [0, 1, 2]))
        upd["messages"] = [*state["messages"],
                           {"role": "user", "content": prompt}]
        return upd

    def after_draft(state: State) -> str:
        return END if state.get("stop") else "check"

    def after_check(state: State) -> str:
        return END if state.get("stop") else "draft"

    g = StateGraph(State)
    g.add_node("draft", draft)
    g.add_node("check", check)
    g.add_edge(START, "draft")
    g.add_conditional_edges("draft", after_draft, ["check", END])
    g.add_conditional_edges("check", after_check, ["draft", END])
    return g.compile(checkpointer=checkpointer)


# ------------------------------------------------------------- running
BUILDERS: dict[str, Callable[..., Any]] = {"agent": build_agent,
                                           "scripted": build_scripted}


def summarize(state: State) -> dict[str, Any]:
    """An episode's outcome and behaviour, from its final state: what is
    scored (the submitted module, else the last draft) and what the
    plan's behaviour metrics count."""
    log = state.get("log") or []
    checked = {e["code"]: e.get("accepted") for e in log
               if e["tool"] == "check" and e.get("code")}
    sub = state.get("submitted")
    h = T.digest(sub) if sub else None
    # The latest draft after each turn: the last code any tool call of that
    # turn or an earlier one carried.
    trajectory, latest = [], None
    by_turn: dict[int, str] = {}
    for e in log:
        if e.get("code"):
            by_turn[e["turn"]] = e["code"]
    for step in state.get("trajectory") or []:
        latest = by_turn.get(step["turn"], latest)
        trajectory.append(dict(step, draft=latest))
    return {
        "stop": state.get("stop"), "error": state.get("error"),
        "turns": state.get("turns", 0), "usd": state.get("usd", 0.0),
        "list_usd": state.get("list_usd", 0.0),
        "trajectory": trajectory, "drafts": dict(state.get("drafts") or {}),
        "nudges": state.get("nudges", 0),
        "submitted": sub is not None,
        "code": sub if sub is not None else state.get("last_code"),
        "checked_before_submit": h in checked if h else None,
        "accepted_at_submit": checked.get(h) if h else None,
        "tool_calls": len(log),
        "tool_errors": sum(1 for e in log if e.get("is_error")),
        "checks": sum(1 for e in log if e["tool"] == "check"),
        "pages_read": sum(1 for e in log
                          if e["tool"] in ("read_page", "search_page")),
    }


# Same rule as infer.KEY_FILE: outside the project tree, never printed or
# logged, sent to one host. The environment's key wins when both are set.
LANGSMITH_KEY_FILE = os.path.join(os.path.expanduser("~"), ".langsmith_key")


def enable_tracing(key_file: str = LANGSMITH_KEY_FILE) -> bool:
    """Turn LangSmith tracing on for this process when a key is available,
    from `LANGSMITH_API_KEY` or else `key_file`. Returns whether it is on.
    Call before the first traced run: langsmith caches what it reads from
    the environment."""
    if not os.environ.get("LANGSMITH_API_KEY"):
        try:
            with open(key_file, encoding="utf-8-sig") as fh:
                key = fh.read().strip()
        except OSError:
            return False
        if not key:
            return False
        os.environ["LANGSMITH_API_KEY"] = key
    os.environ["LANGSMITH_TRACING"] = "true"
    return True


def thread_id(ep: Episode, arm: str) -> str:
    return "%s/%s/%s/e%02d" % (ep.run_id, arm, ep.model, ep.episode)


def run(ep: Episode, arm: str, checkpointer: Any = None,
        project: str | None = None) -> dict[str, Any]:
    """Run (or resume) one episode of `arm` and summarize it. With a
    checkpointer, calling this again for the same episode resumes it."""
    graph = BUILDERS[arm](ep, checkpointer)
    config = {"configurable": {"thread_id": thread_id(ep, arm)},
              "run_name": "%s %s e%02d" % (arm, ep.model, ep.episode),
              "tags": [arm, ep.model, ep.run_id],
              "metadata": {"arm": arm, "model": ep.model, "run_id": ep.run_id,
                           "episode": ep.episode, "tag": ep.tag},
              "recursion_limit": 4 * ep.limits.turns + 10}
    start: State | None = initial_state(ep)
    if checkpointer is not None:
        snap = graph.get_state(config)
        if snap.values:
            start = None
    with langsmith.tracing_context(
            project_name=project or os.environ.get("LANGSMITH_PROJECT")):
        final = graph.invoke(start, config)
    return summarize(final)
