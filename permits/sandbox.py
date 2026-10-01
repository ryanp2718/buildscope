# -*- coding: utf-8 -*-
"""Running generated extractors: reading the code out of a reply, the static
audit, the subprocess runner, and the generic rule for which table rows look
like data.

Moved here from `scripts/conformance.py` on 2026-09-30, verbatim, so that the
agentic extractor (`permits/agent/`) can run and check its drafts without
importing the module that holds the adapters, the references and the scorer.
`conformance.py` re-exports every name, so the harness is unchanged.
"""
import ast
import io
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable
from typing import Any

# ------------------------------------------ executing generated code safely
BANNED_MODULES = {
    "os", "sys", "subprocess", "socket", "urllib", "shutil", "pathlib",
    "importlib", "ctypes", "pickle", "requests", "http", "ftplib", "smtplib",
    "tempfile", "glob", "multiprocessing", "threading", "webbrowser",
    "sqlite3", "marshal", "code", "pty", "signal", "resource"}
BANNED_NAMES = {"open", "exec", "eval", "compile", "__import__", "input",
                "breakpoint"}


def audit(src: str) -> tuple[list[str], list[str]]:
    """Static check on generated source before it is executed.

    A guard, not a sandbox - `re` alone can hang a process and does not need
    `os` to do it, which is why execution also happens in a subprocess under a
    timeout. What the guard buys is that a module reaching outside the
    contract is refused *and reported*, rather than quietly doing something
    the measurement then attributes to extraction quality.
    """
    problems: list[str] = []
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return ["does not parse: %s" % e], []
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imports.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            imports.add((node.module or "").split(".")[0])
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id in BANNED_NAMES:
                problems.append("uses %s()" % node.id)
    for m in sorted(imports & BANNED_MODULES):
        problems.append("imports %s" % m)
    if not any(isinstance(n, ast.FunctionDef) and n.name == "extract"
               for n in tree.body):
        problems.append("defines no top-level extract()")
    return sorted(set(problems)), sorted(imports)


RUNNER = r'''# -*- coding: utf-8 -*-
# The generated module's own stdout is captured and discarded. Importing it
# executes its top level, and `extract` may print too; this runner reports by
# writing JSON to stdout, so one stray print in generated code would corrupt
# that channel and the whole draw would be recorded as "runner produced no
# JSON". Claude was told not to print and did not, which is why this went
# unnoticed - a model that ends its module with a demo call is making a
# formatting choice, not an extraction error, and the measurement should not
# confuse the two. The real stdout is held aside and used only for the report.
import io, json, sys, importlib.util, contextlib
_real_stdout = sys.stdout
_sink = io.StringIO()
spec = importlib.util.spec_from_file_location("synth", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(_sink):
    spec.loader.exec_module(mod)
out = []
for p in sys.argv[2:]:
    html = io.open(p, encoding="utf-8", errors="replace").read()
    try:
        with contextlib.redirect_stdout(_sink):
            rows = mod.extract(html)
        # A non-list return is a contract violation, not a parse of zero
        # records, and it is recorded as a failure for the same reason an
        # exception is: the scorer would otherwise either crash on None or
        # quietly iterate a dict's keys and report a clean zero. The error
        # text names the type so this stays distinguishable from a genuine
        # empty parse in the stored records.
        if not isinstance(rows, list):
            out.append({"page": p, "ok": False,
                        "error": "ContractError: extract() returned %s, "
                                 "not a list" % type(rows).__name__})
        else:
            out.append({"page": p, "ok": True, "rows": rows})
    except Exception as e:
        out.append({"page": p, "ok": False,
                    "error": "%s: %s" % (e.__class__.__name__, e)})
_real_stdout.write(json.dumps(out))
'''


def run_synth(src_path: str, page_paths: Iterable[str], runner_dir: str,
              timeout: int = 300, runner_name: str = "_runner.py"
              ) -> tuple[Any, str | None]:
    """Run `extract` from the module at `src_path` on each page, in a
    subprocess under `timeout`. Returns (per-page results, None) or
    (None, error text)."""
    # Named so two harnesses can run at once. They would otherwise both write
    # one path and collide, which on Windows is a sharing violation that
    # would kill whichever run is currently spending money. The directory is
    # created here because a fresh clone has no data/ tree.
    os.makedirs(runner_dir, exist_ok=True)
    runner = os.path.join(runner_dir, runner_name)
    with io.open(runner, "w", encoding="utf-8") as fh:
        fh.write(RUNNER)
    cmd = [sys.executable, runner, src_path, *list(page_paths)]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "timed out after %ds" % timeout
    if p.returncode != 0:
        return None, p.stderr.decode("utf-8", "replace")[-600:]
    try:
        return json.loads(p.stdout.decode("utf-8", "replace")), None
    except ValueError as e:
        return None, "runner produced no JSON: %s" % e


# ------------------------------------------------ reading generated code
CODEBLOCK = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.S)
JSONBLOCK = re.compile(r"```(?:json)?\s*\n(.*?)```", re.S)


FENCE_OPEN = re.compile(r"```[ \t]*(?:python|py|json)?[ \t]*\r?\n", re.I)
# An opening fence is one that names a language. A bare ``` is read as a
# close, which is the convention and the only way to tell the two apart.
FENCE_LANG = re.compile(r"```[ \t]*(?:python|py|json)[ \t]*\r?\n", re.I)


def fenced_blocks(text: str) -> list[str]:
    """Every fenced region, tolerant of fences that do not pair.

    A regex pair like ```(.*?)``` assumes the fences alternate. Replies from
    models that deliberate in prose do not: a draft is abandoned mid-block, so
    the next thing seen is another *opening* fence where a close was due. The
    pair regex takes it as the close, and from there every fence is off by
    one - which is how the closing fence of the real answer gets assigned to
    an earlier sketch and the answer disappears entirely.

    So a fence that names a language is treated as an opening even when a
    close was expected: the unclosed block ends there and scanning resumes at
    it rather than past it. An unterminated final block runs to end of text,
    which degrades to a truncated block rather than the wrong one.
    """
    out: list[str] = []
    pos = 0
    while True:
        m = FENCE_OPEN.search(text, pos)
        if not m:
            return out
        start = m.end()
        close = text.find("```", start)
        if close == -1:
            out.append(text[start:])
            return out
        out.append(text[start:close])
        pos = close if FENCE_LANG.match(text, close) else close + 3


def extract_block(text: str, pat: re.Pattern[str],
                  must_contain: str | None = None) -> str:
    """The model's answer, from a reply that may hold several blocks.

    Prefers the LAST block that satisfies the contract rather than the first
    that matches a fence. A model whose chain of thought lands in `content`
    emits drafts - a sketch, a correction, then the finished module - and the
    first fenced block is an abandoned attempt. Claude puts that deliberation
    in a separate thinking channel and emits one block, so `search` was
    sufficient until 2026-09-24, when an open-weight reasoning model returned
    nine fences and was scored on a 154-character fragment of its first
    draft: 10,236 output tokens of a working extractor, recorded as a refusal.

    That is a harness artifact that would have been read as a fact about the
    model, and it points the same direction on every model in the open-weight
    tier - which is exactly the comparison this experiment exists to make.

    `must_contain` selects on the contract the prompt asked for instead of on
    position, so a trailing usage example does not win for being last. A reply
    that never contains it has no answer, and gets "": a sentence announcing a
    plan was otherwise handed to the static audit, failed to parse and was
    recorded as a refusal (grok-4.7, Clark draw 5 of the v2 run).
    """
    if must_contain and must_contain not in text:
        return ""
    blocks = fenced_blocks(text)
    if not blocks:
        m = pat.search(text)
        return m.group(1) if m else text
    if must_contain:
        named = [b for b in blocks if must_contain in b]
        if named:
            return named[-1]
    return max(blocks, key=len)


# ------------------------------------------------------------ table rows
TR = re.compile(r"(?is)<tr\b.*?</tr>")
TD = re.compile(r"(?i)<t[dh]\b")
MIN_CELLS = 4


def data_rows(s: str) -> list[tuple[int, int]]:
    """Spans of `<tr>` elements that look like data rather than layout.

    A layout table's rows carry one or two cells; a results grid's carry many.
    Measured on the Clark page: 31 rows of 2 cells (layout), 11 rows of 8
    (the grid, 10 permits and a header). The cell count separates them
    cleanly and knows nothing about any vendor.
    """
    return [(m.start(), m.end()) for m in TR.finditer(s)
            if len(TD.findall(m.group(0))) >= MIN_CELLS]
