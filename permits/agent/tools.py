# -*- coding: utf-8 -*-
"""What the agent can do: look at a portal's pages, run a draft extractor,
check it, and submit it. Every tool returns text for the model and records
what happened for the metrics, and none of them sees a reference.

`Workspace` holds one episode's view of one portal: the stripped pages the
extractor will run on, the grid-row estimate per page, the contract's field
names and a scratch directory for drafts. The caller builds it; nothing here
knows which portal it is.

Outputs are capped so a tool cannot flood the model's context: a page slice
at `MAX_READ` characters, any tool result at `MAX_OUT`.
"""
import hashlib
import io
import json
import os
from dataclasses import dataclass, field
from typing import Any

from permits import sandbox
from permits.agent import verify

MAX_READ = 8000
MAX_OUT = 6000
MAX_MATCHES = 20
SAMPLE_ROWS = 2
RUN_TIMEOUT = 120


def _schema(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


CODE = {"type": "string",
        "description": "The whole Python module, defining extract(html)."}
PAGE = {"type": "integer", "description": "Page number, from list_pages."}

TOOLS: list[dict[str, Any]] = [
    {"name": "list_pages",
     "description": "List the portal's pages: number, file name and size.",
     "parameters": _schema({}, [])},
    {"name": "read_page",
     "description": "Read part of a page's HTML, as the extractor will see "
                    "it. At most %d characters per call." % MAX_READ,
     "parameters": _schema({
         "page": PAGE,
         "start": {"type": "integer", "description": "Character offset."},
         "length": {"type": "integer", "description": "Characters to read."}},
         ["page"])},
    {"name": "search_page",
     "description": "Find a piece of text in a page (case-insensitive, not a "
                    "regular expression). Returns each match's offset with "
                    "some text around it, up to %d matches." % MAX_MATCHES,
     "parameters": _schema({"page": PAGE,
                            "text": {"type": "string"}}, ["page", "text"])},
    {"name": "run_extractor",
     "description": "Run a draft module on some or all pages. Returns per "
                    "page the number of rows or the error, and the first "
                    "rows it returned.",
     "parameters": _schema({
         "code": CODE,
         "pages": {"type": "array", "items": {"type": "integer"},
                   "description": "Page numbers; all pages if omitted."}},
         ["code"])},
    {"name": "check",
     "description": "Run a draft on every page and check its output without "
                    "any answer key: the row count on each page against the "
                    "rows the page's grid shows, ids present and unique, no "
                    "markup in values, dates that look like dates. Also "
                    "notes values with stray angle brackets and fields empty "
                    "on every row. Says ACCEPT or REJECT.",
     "parameters": _schema({"code": CODE}, ["code"])},
    {"name": "submit",
     "description": "Submit the final module. Ends the task.",
     "parameters": _schema({"code": CODE}, ["code"])},
]
TOOL_NAMES = tuple(t["name"] for t in TOOLS)


@dataclass
class Result:
    """A draft run on every page and checked."""
    audit: list[str]
    error: str | None
    pages: list[dict[str, Any]]
    failed: dict[str, list[int]]
    notes: dict[str, Any]

    @property
    def accepted(self) -> bool:
        return not self.audit and self.error is None and not self.failed


@dataclass
class Workspace:
    pages: list[str]
    fields: list[str]
    workdir: str
    timeout: int = RUN_TIMEOUT
    expected: list[int] = field(default_factory=list)
    # What the episode did, for the metrics: each tool call, and each
    # distinct draft checked, by content hash.
    log: list[dict[str, Any]] = field(default_factory=list)
    checked: dict[str, bool] = field(default_factory=dict)
    last_code: str | None = None
    _html: list[str] = field(default_factory=list)
    _runs: dict[str, Result] = field(default_factory=dict)

    def __post_init__(self) -> None:
        os.makedirs(self.workdir, exist_ok=True)
        self._html = [io.open(p, encoding="utf-8", errors="replace").read()
                      for p in self.pages]
        if not self.expected:
            self.expected = verify.expected_rows(self._html)

    # ------------------------------------------------------------ running
    def run(self, code: str) -> Result:
        """Audit, then run on every page and check. Cached by content, so
        `run_extractor` then `check` on one draft runs it once."""
        h = digest(code)
        if h in self._runs:
            return self._runs[h]
        problems, _ = sandbox.audit(code)
        if problems:
            res = Result(problems, None, [], {}, {})
        else:
            path = os.path.join(self.workdir, "draft_%s.py" % h)
            with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(code)
            out, err = sandbox.run_synth(path, self.pages, self.workdir,
                                         timeout=self.timeout,
                                         runner_name="_agent_runner.py")
            res = self._checked(out, err)
        self._runs[h] = res
        return res

    def _checked(self, out: list[dict[str, Any]] | None,
                 err: str | None) -> Result:
        if err is not None or out is None:
            return Result([], err or "no output", [], {}, {})
        failed: dict[str, list[int]] = {}
        pages = []
        rows_ok = []
        for n, (page, want) in enumerate(zip(out, self.expected,
                                             strict=True)):
            if not page["ok"]:
                failed.setdefault("raised", []).append(n)
                pages.append({"page": n, "error": page["error"]})
                continue
            rows = page["rows"]
            rows_ok.append(rows)
            pages.append({"page": n, "rows": len(rows), "grid_rows": want,
                          "sample": rows[:SAMPLE_ROWS]})
            for name in sorted(verify.check_page(rows, want)):
                failed.setdefault(name, []).append(n)
        notes: dict[str, Any] = {}
        edges = [v for rows in rows_ok for v in verify.edge_values(rows)]
        if edges:
            notes["edges"] = edges[:5]
        empty = verify.empty_fields(rows_ok, self.fields)
        if empty:
            notes["empty"] = empty
        return Result([], None, pages, failed, notes)

    # -------------------------------------------------------------- tools
    def call(self, name: str, args: dict[str, Any]) -> tuple[str, bool]:
        """Run one tool call. Returns (text for the model, is_error)."""
        self.log.append({"tool": name,
                         "code": digest(args["code"])
                         if isinstance(args.get("code"), str) else None})
        try:
            if name == "list_pages":
                return self.list_pages(), False
            if name == "read_page":
                return self.read_page(int(args["page"]),
                                      int(args.get("start") or 0),
                                      int(args.get("length") or MAX_READ)), False
            if name == "search_page":
                return self.search_page(int(args["page"]),
                                        str(args["text"])), False
            if name == "run_extractor":
                return self.run_extractor(str(args["code"]),
                                          args.get("pages")), False
            if name == "check":
                return self.check(str(args["code"])), False
        except (KeyError, TypeError, ValueError, IndexError) as e:
            return "bad arguments for %s: %s" % (name, e), True
        return "unknown tool %r; the tools are %s" % (
            name, ", ".join(TOOL_NAMES)), True

    def list_pages(self) -> str:
        return "\n".join("page %d: %s, %d characters"
                         % (n, os.path.basename(p), len(h))
                         for n, (p, h) in enumerate(zip(self.pages, self._html,
                                                        strict=True)))

    def read_page(self, page: int, start: int = 0,
                  length: int = MAX_READ) -> str:
        html = self._html[page]
        start = max(0, start)
        end = min(len(html), start + max(0, min(length, MAX_READ)))
        return "page %d, characters %d-%d of %d:\n%s" % (
            page, start, end, len(html), html[start:end])

    def search_page(self, page: int, text: str) -> str:
        html = self._html[page]
        if not text:
            return "empty search text"
        low, needle = html.lower(), text.lower()
        hits: list[str] = []
        pos = low.find(needle)
        while pos != -1 and len(hits) < MAX_MATCHES:
            a, b = max(0, pos - 100), min(len(html), pos + len(text) + 100)
            hits.append("at %d: ...%s..." % (pos, html[a:b]))
            pos = low.find(needle, pos + 1)
        total = low.count(needle)
        head = "%d matches in page %d" % (total, page)
        return _cap("\n".join([head, *hits]))

    def run_extractor(self, code: str, pages: Any = None) -> str:
        self.last_code = code
        res = self.run(code)
        if res.audit:
            return "refused before running: %s" % "; ".join(res.audit)
        if res.error is not None:
            return "the module failed to run: %s" % res.error
        wanted = ({int(p) for p in pages} if pages
                  else set(range(len(self.pages))))
        lines = []
        for p in res.pages:
            if p["page"] not in wanted:
                continue
            if "error" in p:
                lines.append("page %d: raised %s" % (p["page"], p["error"]))
            else:
                lines.append("page %d: %d rows; first: %s" % (
                    p["page"], p["rows"],
                    json.dumps(p["sample"], ensure_ascii=False)))
        return _cap("\n".join(lines))

    def check(self, code: str) -> str:
        self.last_code = code
        res = self.run(code)
        self.checked[digest(code)] = res.accepted
        if res.audit:
            return "REJECT: refused before running: %s" % "; ".join(res.audit)
        if res.error is not None:
            return "REJECT: the module failed to run: %s" % res.error
        lines = ["ACCEPT" if res.accepted else "REJECT"]
        for name, pages in sorted(res.failed.items()):
            detail = []
            for n in pages[:8]:
                p = res.pages[n]
                detail.append("page %d (%s)" % (
                    n, p["error"] if "error" in p
                    else "%d rows returned, grid shows %d" % (p["rows"],
                                                              p["grid_rows"])))
            lines.append("failed %s on %d page(s): %s" % (
                name, len(pages), "; ".join(detail)))
        if "edges" in res.notes:
            lines.append("note: values with a stray angle bracket, e.g. %s"
                         % json.dumps(res.notes["edges"], ensure_ascii=False))
        if "empty" in res.notes:
            lines.append("note: empty on every row: %s. Right if the pages "
                         "do not print them; if they do, extract them."
                         % ", ".join(res.notes["empty"]))
        return _cap("\n".join(lines))


def digest(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()[:16]


def _cap(text: str) -> str:
    if len(text) <= MAX_OUT:
        return text
    return text[:MAX_OUT] + "\n[... cut at %d characters]" % MAX_OUT
