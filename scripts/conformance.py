# -*- coding: utf-8 -*-
"""Extractor conformance test: a synthesized extractor scored against a
hand-written adapter on pages already in the raw store.

[ADR-0009](../docs/adr/0009-adapters-first-generic-extraction-second.md) sets
the trigger this discharges: *the fourth adapter is the last one built before a
measured generic-versus-adapter comparison exists.* Three adapters of a cap of
five are spent. Nothing further is built until this produces a number.

**This was called "the bake-off" and the name was wrong, in a way that hid
something.** A bake-off has a neutral judge and a winner. This has neither.
The adapter *is* the reference, so what is measured is **conformance to the
adapter** - an agreement rate - and not accuracy. Where the two disagree,
either may be right, and the adapter has been wrong before: it read a
truncated page as a complete one, and it mis-keyed a vocabulary. The thing
that could adjudicate is the golden set of
[ADR-0014](../docs/adr/0014-the-golden-set-precedes-the-pipeline.md), of which
zero records exist. So: a conformance test against a reference implementation,
every figure below is an agreement rate, and none of them may be quoted as an
accuracy figure. The rename is the guardrail - "the synthesized extractor
scored 0.98" invites the wrong reading, "it conformed to the adapter on 0.98
of fields" does not.

## The two arms, and why both

The amortization claim in section 1 is not "a model can read a permit page".
It is that per-*page* cost converts into per-*template* cost. Those are
different mechanisms and only one of them is what section 6 prices:

  **Arm S - synthesis.** One call sees one page and returns *Python source*.
  That program then runs over every other page of the same template for zero
  further calls. Cost is per template. This is the arm D8 describes and the
  schema at DESIGN.md line 651 stores (`extractor_program`, `synthesis_cost`).

  **Arm D - direct extraction.** Every page goes to the model and records come
  back. Cost is per page, forever. This is what synthesis has to beat, and
  without it "synthesis works" is a claim with no denominator.

Running only arm S would measure whether a model can write a parser. Running
both measures what amortization is worth, which is the actual question.

Within one comparison both arms use the **same model**, or the arm and the
model tier are confounded and neither number means anything. The model tier is
a *second axis*, run as a second pass over the same pages.

**That second axis is something DESIGN.md section 6 says cannot be measured
yet, and section 6 is wrong about it.** Lever 6 defers model tiering until the
golden set exists, "because before step 2 there is no way to tell a cost
saving from a quality regression". That is correct about **accuracy** and does
not apply here. The reference is a hand-written parser, so its errors are
*uncorrelated* with any model's - which is exactly the property an
LLM-as-judge lacks, and exactly why D9 forbids LLM-as-judge for headline
numbers. Two models scored against an uncorrelated reference can therefore be
compared to each other, even though neither can be called correct. The claim
available is "the cheap model disagrees with the adapter no more often than
the expensive one does", which is weaker than accuracy and is precisely what
lever 6 needs in order to be pulled.

The sequencing that follows: **run the cheap tier first.** If it conforms as
well as the expensive one, the expensive run buys nothing and is not made. If
it does not, the tier matters and the expensive run has a reason to exist.
Either result is worth more than the arm comparison alone, and the cheap tier
costs about a fifth.

## The seam

Both arms replace `adapter.parse_index()` and nothing else. They return rows
of **native strings exactly as rendered** - no date parsing, no code lookup,
no unit inference. That is not a simplification of the task, it is the task:
`tests/test_structure.py::TestAdaptersStayThin` already forbids an adapter
from normalizing, because `permits/emit.py` owns that and two normalization
paths drift. A synthesized extractor is drop-in the moment it emits the same
dict, so the dict is what gets scored.

The model is told the **target schema** - the roles `permits/emit.py` needs -
and is not told the page's column names. The schema is the part D8 fixes on
day one; the page is the unknown. Handing over the column names would be
scoring the model on a task with the answer in the prompt.

## What is deliberately not measured

- **Accuracy.** See above. Agreement only.
- **Drift.** Every page here is one capture of one template. Whether a
  synthesized extractor survives the portal changing is the step-2 question
  against the golden set, and it is the question that sets the cohort
  threshold Spike C could not pick.
- **Detail pages.** Measurement B put index and detail at J = 0.19 inside one
  portal, so a tenancy needs at least two extractors. This scores one of them.
"""
import argparse
import ast
import csv
import io
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from permits import infer
from permits.stats import ORDER, failure_mode, wilson
from permits import strip as _strip                          # noqa: E402
from permits.adapters import accela, stjohns                 # noqa: E402

PAGES = os.path.join(ROOT, "data", "step1", "pages")
MANIFEST = os.path.join(ROOT, "data", "step1", "manifest.csv")
OUT = os.path.join(ROOT, "data", "infer")
SYNTH = os.path.join(OUT, "synth")

# Defaults. Both arms on one model is the confound-free setting for the
# synthesis-vs-direct question; `--synth-model` / `--direct-model` open the
# second axis. See `--matrix`.
MODEL = "claude-opus-5"


# --------------------------------------------------------------- the schema
# Roles, not column names. Every one is a field permits/emit.py already has a
# home for.
ROLES = [
    ("native_id", "the permit or record number the jurisdiction assigns, "
                  "exactly as printed"),
    ("issued_date", "the date this row carries, as printed, unparsed"),
    ("address", "the work location, as printed"),
    ("permit_type", "the type/category string, if the page prints one"),
    ("status", "the status string, if the page prints one"),
    ("structure_code", "a property-use or occupancy code, if the page "
                       "prints one"),
    ("contractor", "the contractor or applicant name, if the page prints one"),
]

CONTRACT = """You are extracting permit records from a municipal permit portal
index page - one page of a result grid, many records per page.

Return these fields per record. They are roles, not column headings; work out
which part of the page carries each one.

%s

Three rules, each of which exists because breaking it has cost a real project
a wrong answer:

1. Values are returned EXACTLY AS RENDERED. Do not parse dates, expand
   abbreviations, title-case anything, or look codes up. A downstream layer
   owns all normalization and a second normalization path silently drifts from
   the first. Collapse runs of whitespace and decode HTML entities; nothing
   else.
2. A field the page does not print is null. It is NOT an empty string and it
   is NOT a guess from a neighbouring field. "This page has no unit column"
   and "this permit has zero units" are different facts and the difference is
   load-bearing downstream.
3. Every record on the page, in page order, and no rows that are not permit
   records - not the header, not a pagination row, not a totals row.
""" % "\n".join("   - %-16s %s" % (k, v) for k, v in ROLES)


SYNTH_SYSTEM = CONTRACT + """
YOUR TASK: write a Python 3 module, not an answer.

Emit one fenced ```python block containing a module that defines exactly:

    def extract(html: str) -> list[dict]

It takes the full page source as a string and returns the records. Use only
the standard library, and only `re`, `html`, `json`, `collections`,
`itertools`, `string`, `unicodedata`. No file, network, or process access of
any kind - the module is executed, and anything outside that list is treated
as a failure of the task rather than a creative solution.

It will be run against OTHER pages from the same portal that you have not
seen, containing different records. Those pages are put through the exact same
stripping as the excerpt below - same tags removed, same attributes kept, same
whitespace collapsing - but they are WHOLE pages, not excerpts, so your
function must find the grid itself rather than assume where it starts. Write
for the template, not for the rows in front of you. Do not hard-code a permit
number, a date, an address, or a row count.

Prefer failing loudly to guessing: if the structure you keyed on is absent,
raise. A parser that silently returns [] on a changed page is the failure mode
this is being measured against.

Write the block and nothing else after it.
"""

DIRECT_SYSTEM = CONTRACT + """
YOUR TASK: return the records from the page below.

Emit one fenced ```json block containing a JSON array of objects, one object
per record, each with exactly the field names listed above. No commentary
before or after the block.
"""


# ------------------------------------------------------------ the targets
class Target(object):
    def __init__(self, key, jurisdiction, vendor, adapter, roles, label):
        self.key = key
        self.jurisdiction = jurisdiction
        self.vendor = vendor
        self.adapter = adapter
        # role -> the key the adapter's parse_index() puts it under. The only
        # place the two vocabularies are joined, written out rather than
        # inferred so a scoring change is a visible diff.
        self.roles = roles
        self.label = label

    def reference(self, html):
        out = self.adapter.parse_index(html)
        return out[0] if isinstance(out, tuple) else out


TARGETS = {
    "stjohns": Target(
        "stjohns", "stjohns", "wats-dotnet", stjohns,
        {"native_id": "number", "address": "address",
         "structure_code": "propuse", "issued_date": "issued",
         "contractor": "contractor"},
        "St. Johns County FL - WATS/.NET grid"),
    "clarkco": Target(
        "clarkco", "clarkco", "accela-aca", accela,
        {"native_id": "number", "address": "address",
         "permit_type": "type", "status": "status",
         "issued_date": "date"},
        "Clark County NV - Accela ACA grid"),
}


def corpus(target):
    """Pages for a target, from the manifest.

    D1: every analysis reads the manifest, never the directory. A page on disk
    with no row is not evidence, and the row is what says which portal a file
    came from.
    """
    rows = []
    for r in csv.DictReader(io.open(MANIFEST, encoding="utf-8")):
        if (r["jurisdiction"] == target.jurisdiction
                and r["vendor"] == target.vendor
                and r["page_type"].endswith("INDEX")
                and r["http_status"] == "200"):
            p = os.path.join(PAGES, r["file"])
            if os.path.exists(p):
                rows.append((r["file"], p))
    seen, out = set(), []
    for fn, p in sorted(rows):
        if fn not in seen:
            seen.add(fn)
            out.append((fn, p))
    return out


def read(path):
    return io.open(path, encoding="utf-8", errors="replace").read()


def strip(html):
    """Section 6 lever 4: do not send raw HTML.

    Uses `permits/strip.py`'s default keep-list, which includes `class`. The
    original keep-list did not, and on an Accela page that silently deleted
    all 42 `ACA_TabRow` markers - the only thing distinguishing a permit row
    from a layout row - while leaving the rows themselves in place, so the
    page still looked whole. Lever 4's claim of "an order-of-magnitude token
    reduction against identical extraction quality" is true about the
    reduction and was never checked on the quality.
    """
    return _strip.levels(html)["attrs-stripped"]


TR = re.compile(r"(?is)<tr\b.*?</tr>")
TD = re.compile(r"(?i)<t[dh]\b")
MIN_CELLS = 4


def data_rows(s):
    """Spans of `<tr>` elements that look like data rather than layout.

    A layout table's rows carry one or two cells; a results grid's carry many.
    Measured on the Clark page: 31 rows of 2 cells (layout), 11 rows of 8
    (the grid, 10 permits and a header). The cell count separates them
    cleanly and knows nothing about any vendor.
    """
    return [(m.start(), m.end()) for m in TR.finditer(s)
            if len(TD.findall(m.group(0))) >= MIN_CELLS]


def window(html, budget, step=1000):
    """A bounded slice of a stripped page, for synthesis.

    Synthesis does not need to see 500 rows to learn a template; it needs the
    header and enough rows to see the repeat. That asymmetry is not a trick -
    it is *why* synthesis amortizes, and arm D cannot use it, because arm D
    has to return every record.

    **The placement rule had to be measured twice, and was wrong both
    times.** Version one kept the head of the document and then a window
    starting at the first `<table`; on Clark County that ended at character
    24,973 while the permit grid begins at 65,386, because an Accela page
    nests its grid several layout tables deep and 68% of the document
    precedes the data. Version two maximized the count of `<tr` in the window
    and landed on a nav block, because layout tables have more rows than the
    grid does - just smaller ones.

    Version three maximizes the count of *data* rows as defined above. Had
    either earlier version been used, synthesis would have been shown a page
    with no permit rows on it, scored zero, and the number would have
    described this function rather than the model. That is the whole reason
    the coverage percentage and the window offset are printed on every run.
    """
    s = strip(html)
    if len(s) <= budget:
        return s, 1.0, 0
    head = budget // 5
    span = budget - head
    rows = data_rows(s)
    best, best_n = 0, -1
    for i in range(0, max(1, len(s) - span) + step, step):
        n = sum(1 for a, b in rows if a >= i and b <= i + span)
        if n > best_n:
            best, best_n = i, n
    return (s[:head] + "\n...[document elided]...\n" + s[best:best + span],
            float(budget) / len(s), best)


# ------------------------------------------------------------- the scorer
WS = re.compile(r"\s+")


def norm(v):
    """Whitespace-collapse only. Anything stronger would be scoring the
    comparison instead of the extractor - if the model returns '3/2/2026' and
    the adapter returns '3/2/2026 11:06:49 PM', that is a real disagreement,
    and hiding it under a date parser is how an agreement rate gets flattered.
    """
    if v is None:
        return None
    return WS.sub(" ", str(v)).strip() or None


def score(target, ref_rows, cand_rows):
    """Agreement between a candidate parse and the adapter's, on native id."""
    rk = target.roles["native_id"]
    ref = {}
    for r in ref_rows:
        k = norm(r.get(rk))
        if k:
            ref.setdefault(k, r)
    cand = {}
    for r in cand_rows:
        if not isinstance(r, dict):
            continue
        k = norm(r.get("native_id"))
        if k:
            cand.setdefault(k, r)

    both = set(ref) & set(cand)
    missed = sorted(set(ref) - set(cand))
    spurious = sorted(set(cand) - set(ref))

    fields, disagreements = {}, []
    for role, col in sorted(target.roles.items()):
        if role == "native_id":
            continue
        agree = seen = 0
        for k in sorted(both):
            a, b = norm(ref[k].get(col)), norm(cand[k].get(role))
            if a is None and b is None:
                continue
            seen += 1
            if a == b:
                agree += 1
            elif len(disagreements) < 400:
                disagreements.append(
                    {"key": k, "field": role, "adapter": a, "model": b})
        fields[role] = {"agree": agree, "compared": seen,
                        "rate": (agree / float(seen)) if seen else None}
    return {
        "ref_records": len(ref), "cand_records": len(cand),
        "matched": len(both),
        "recall": (len(both) / float(len(ref))) if ref else None,
        "precision": (len(both) / float(len(cand))) if cand else None,
        "missed": missed[:40], "n_missed": len(missed),
        "spurious": spurious[:40], "n_spurious": len(spurious),
        "fields": fields, "disagreements": disagreements,
    }


# ------------------------------------------ executing generated code safely
BANNED_MODULES = {
    "os", "sys", "subprocess", "socket", "urllib", "shutil", "pathlib",
    "importlib", "ctypes", "pickle", "requests", "http", "ftplib", "smtplib",
    "tempfile", "glob", "multiprocessing", "threading", "webbrowser",
    "sqlite3", "marshal", "code", "pty", "signal", "resource"}
BANNED_NAMES = {"open", "exec", "eval", "compile", "__import__", "input",
                "breakpoint"}
CODEBLOCK = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.S)
JSONBLOCK = re.compile(r"```(?:json)?\s*\n(.*?)```", re.S)


FENCE_OPEN = re.compile(r"```[ \t]*(?:python|py|json)?[ \t]*\r?\n", re.I)
# An opening fence is one that names a language. A bare ``` is read as a
# close, which is the convention and the only way to tell the two apart.
FENCE_LANG = re.compile(r"```[ \t]*(?:python|py|json)[ \t]*\r?\n", re.I)


def fenced_blocks(text):
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
    out, pos = [], 0
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


def extract_block(text, pat, must_contain=None):
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
    position, so a trailing usage example does not win for being last.
    """
    blocks = fenced_blocks(text)
    if not blocks:
        m = pat.search(text)
        return m.group(1) if m else text
    if must_contain:
        named = [b for b in blocks if must_contain in b]
        if named:
            return named[-1]
    return max(blocks, key=len)


def audit(src):
    """Static check on generated source before it is executed.

    A guard, not a sandbox - `re` alone can hang a process and does not need
    `os` to do it, which is why execution also happens in a subprocess under a
    timeout. What the guard buys is that a module reaching outside the
    contract is refused *and reported*, rather than quietly doing something
    the measurement then attributes to extraction quality.
    """
    problems = []
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return ["does not parse: %s" % e], []
    imports = set()
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


def stripped_corpus(target, pages):
    """Write the stripped form of every page and return those paths.

    The synthesized extractor is *shown* a stripped page, so it must be *run*
    on stripped pages. Handing it raw HTML instead would score it on a
    representation it never saw - attribute order, inline styles and the
    whitespace it was told had been collapsed all differ - and a failure there
    would be an artifact of the harness, not a fact about synthesis. Stripping
    is deterministic and free, so a real pipeline would do it on both sides
    too.
    """
    d = os.path.join(OUT, "stripped", target.key)
    if not os.path.isdir(d):
        os.makedirs(d)
    out = []
    for fn, p in pages:
        q = os.path.join(d, fn)
        if not os.path.exists(q) or os.path.getmtime(q) < os.path.getmtime(p):
            with io.open(q, "w", encoding="utf-8") as fh:
                fh.write(strip(read(p)))
        out.append((fn, q))
    return out


def run_synth(src_path, page_paths, timeout=300, runner_name="_runner.py"):
    # Named so two harnesses can run at once. They would otherwise both write
    # one path and collide, which on Windows is a sharing violation that
    # would kill whichever run is currently spending money.
    runner = os.path.join(SYNTH, runner_name)
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


# ------------------------------------------------------- scorer validation
def validate_scorer(target, rows):
    """Prove the instrument before spending money through it.

    A scorer that reports 1.000 on identical input has shown nothing; a scorer
    that *fails* to is broken. Both directions are checked: identity must
    score perfect, and four mutations must each move the number they are
    supposed to move and leave the others alone.
    """
    out = []
    ident = [{role: r.get(col) for role, col in target.roles.items()}
             for r in rows]
    s = score(target, rows, ident)
    out.append(("identity -> recall 1.0", s["recall"] == 1.0))
    out.append(("identity -> precision 1.0", s["precision"] == 1.0))
    out.append(("identity -> every field 1.0",
                all(f["rate"] in (1.0, None) for f in s["fields"].values())))

    dropped = ident[:-3] if len(ident) > 3 else ident[:-1]
    s2 = score(target, rows, dropped)
    out.append(("drop 3 records -> recall falls", s2["recall"] < 1.0))
    out.append(("drop 3 records -> precision holds", s2["precision"] == 1.0))

    invented = [*ident, dict(ident[0], native_id="ZZZ-NOT-A-PERMIT")]
    s3 = score(target, rows, invented)
    out.append(("invent 1 record -> precision falls", s3["precision"] < 1.0))
    out.append(("invent 1 record -> recall holds", s3["recall"] == 1.0))

    fld = next(k for k in target.roles if k != "native_id")
    bent = [dict(r) for r in ident]
    for r in bent[:5]:
        r[fld] = (r.get(fld) or "") + " XX"
    s4 = score(target, rows, bent)
    out.append(("corrupt %r -> that field falls" % fld,
                (s4["fields"][fld]["rate"] or 1.0) < 1.0))
    out.append(("corrupt %r -> others hold" % fld,
                all(v["rate"] in (1.0, None)
                    for k, v in s4["fields"].items() if k != fld)))
    return out


# ------------------------------------------------------------------- main
# Output tokens one extracted record costs as JSON. **Measured, after the
# first estimate truncated two calls.** A guess of 45 killed both St. Johns
# arm-D pages; Clark's two successful calls billed 1003 and 958 output tokens
# for 10 records each, which is ~98 with the array wrapper amortized. 110
# carries headroom for a long address.
TOKENS_PER_RECORD = 110


def direct_budget(n_records):
    """`max_tokens` for one arm-D call, from the reference record count.

    Sized per page rather than fixed, because the record density of these two
    platforms differs by 26x - a St. Johns page carries ~260 rows and a Clark
    page carries 10. A single ceiling would either truncate one or authorize
    26x the necessary spend on the other, and `Budget` tests the worst case,
    which is what `max_tokens` authorizes.

    Truncation here is not a degraded answer, it is an unparseable one: the
    JSON array never closes, so the whole page scores zero and the call is
    billed in full. Erring high costs nothing unless the model uses it.
    """
    return max(2000, min(48000, int(n_records * TOKENS_PER_RECORD) + 2000))


def plan(target, pages, refs, args):
    """What the run would cost, from the real bytes, before any call."""
    win, frac, at = window(read(pages[0][1]), args.synth_window)
    syn_in = infer.tokens(SYNTH_SYSTEM) + infer.tokens(win)
    syn = infer.estimate(args.synth_model, syn_in, args.synth_tokens)

    direct = []
    for fn, p in pages[:args.direct_pages]:
        n_in = infer.tokens(DIRECT_SYSTEM) + infer.tokens(strip(read(p)))
        cap = direct_budget(len(refs[fn]))
        direct.append((fn, n_in, cap,
                       infer.estimate(args.direct_model, n_in, cap)))
    return {"synth_in": syn_in, "synth_window_frac": frac,
            "synth_window_at": at, "synth_usd": syn, "direct": direct,
            "direct_usd": sum(d[3] for d in direct)}


def matrix(targets, args):
    """Projected worst-case cost of each arm on each priced model.

    Printed rather than argued, because the interesting fact about the second
    axis is how cheap it is: the arms differ in cost by the ratio of one page
    to one corpus, while the models now differ by more than two orders of
    magnitude. Those are very different levers and only one of them is a
    tradeoff.

    **[2026-09-23] The model axis used to stop at 5x**, which is the spread
    across the three Claude tiers. A claim about cost per success measured
    only inside a 5x band cannot say whether it survives a wider one, and the
    open-weight rows reach roughly 90x below Opus 5. That is the whole reason
    they are here; see the `permits/infer.py` docstring.
    """
    priced = dict(infer.PRICES)
    priced.update(infer.OPENROUTER_PRICES)
    # Free endpoints are excluded: this table plans measurements, and a free
    # route does not promise a fixed upstream or quantization, so a cell drawn
    # from one is not a sample of a single condition. It would also sort to
    # the top and make the cheapest-tier line below quote a zero.
    for m in infer.OPENROUTER_FREE:
        priced.pop(m, None)
    rows = []
    for model in sorted(priced, key=lambda m: priced[m][0]):
        s_usd = d_usd = 0.0
        for key in targets:
            t = TARGETS[key]
            pages = corpus(t)
            if not pages:
                continue
            refs = {fn: t.reference(read(p)) for fn, p in pages}
            win, _, _ = window(read(pages[0][1]), args.synth_window)
            s_usd += infer.estimate(
                model, infer.tokens(SYNTH_SYSTEM) + infer.tokens(win),
                args.synth_tokens)
            for fn, p in pages[:args.direct_pages]:
                d_usd += infer.estimate(
                    model,
                    infer.tokens(DIRECT_SYSTEM) + infer.tokens(strip(read(p))),
                    direct_budget(len(refs[fn])))
        rows.append((model, s_usd, d_usd))
    print("\nprojected worst case")
    print("  Anthropic  %s" % infer.PRICES_AS_OF)
    print("  OpenRouter %s\n" % infer.OPENROUTER_PRICES_AS_OF)
    print("  %-30s %9s %9s %9s %8s"
          % ("model", "arm S", "arm D", "both", "vs dearest"))
    dearest = max(r[1] + r[2] for r in rows) or 1.0
    for model, s, d in rows:
        print("  %-30s %9s %9s %9s %7.1fx"
              % (model, "$%.3f" % s, "$%.3f" % d, "$%.3f" % (s + d),
                 dearest / (s + d) if (s + d) else 0.0))
    cheap = rows[0]
    dear = rows[-1]
    print("\n  full 2x2 (%s and %s, both arms): $%.3f"
          % (infer.short_model(cheap[0]), infer.short_model(dear[0]),
             sum(cheap[1:]) + sum(dear[1:])))
    print("  cheap tier first, then decide:         $%.3f now, $%.3f held back"
          % (sum(cheap[1:]), sum(dear[1:])))


def main():
    ap = argparse.ArgumentParser(
        description="extractor conformance test (ADR-0009 trigger)")
    ap.add_argument("--targets", default="stjohns,clarkco")
    ap.add_argument("--run", action="store_true",
                    help="make model calls. Without this nothing is sent.")
    ap.add_argument("--max-spend", type=float, default=2.00)
    ap.add_argument("--synth-window", type=int, default=24000,
                    help="chars of stripped page shown to synthesis")
    ap.add_argument("--synth-tokens", type=int, default=8000)
    ap.add_argument("--direct-pages", type=int, default=2,
                    help="whole pages per target sent to the model for arm D")
    ap.add_argument("--key-file", default=None,
                    help="file holding the Anthropic API key (default %s)"
                         % infer.KEY_FILE)
    ap.add_argument("--openrouter-key-file", default=None,
                    help="file holding the OpenRouter API key (default %s). "
                         "Any model id containing a slash is routed there."
                         % infer.OPENROUTER_KEY_FILE)
    ap.add_argument("--synth-model", default=MODEL)
    ap.add_argument("--direct-model", default=MODEL)
    ap.add_argument("--variance-report", action="store_true",
                    help="failure taxonomy from variance.json. Reads "
                         "the file; sends nothing.")
    ap.add_argument("--drift", action="store_true",
                    help="injected-drift robustness eval. No model "
                         "calls: mutates stored pages and re-runs the "
                         "extractors already on disk.")
    ap.add_argument("--drift-pages", type=int, default=5)
    ap.add_argument("--drift-variance", action="store_true",
                    help="also drift-test every synthesis draw that "
                         "passed conformance, for a survival rate "
                         "across extractors rather than one point")
    ap.add_argument("--cells", default=None,
                    help="variance allocation as target:model:draws, "
                         "comma separated. Every cell runs inside one "
                         "session so --max-spend caps the whole "
                         "experiment rather than each cell separately.")
    ap.add_argument("--draws", type=int, default=1,
                    help="synthesis draws per cell. >1 runs the "
                         "variance experiment: arm S only, results to "
                         "variance.json")
    ap.add_argument("--matrix", action="store_true",
                    help="print projected cost per arm per model and exit")
    args = ap.parse_args()

    if getattr(args, "variance_report", False):
        variance_report()
        return

    if args.drift:
        run_drift(args)
        return

    if args.matrix:
        matrix([k.strip() for k in args.targets.split(",")], args)
        return

    if not os.path.isdir(SYNTH):
        os.makedirs(SYNTH)
    client = infer.Client(ROOT, args.max_spend, dry_run=not args.run,
                          key_file=args.key_file,
                          openrouter_key_file=args.openrouter_key_file)
    if args.run:
        # Check the credential for every provider this run will actually use,
        # not just Anthropic's. Having one of the two configured must not read
        # as having the other, or the run dies partway through an allocation
        # with some cells paid for and some not.
        need = {args.synth_model, args.direct_model}
        if args.cells:
            for cell in args.cells.split(","):
                bits = cell.strip().split(":", 1)
                if len(bits) == 2 and bits[1].count(":"):
                    need.add(bits[1].rsplit(":", 1)[0])
        for m in sorted(need):
            if not client.key_for(m):
                prov = infer.provider_for(m)
                raise SystemExit(
                    "no API key for %s, needed by %s. Set %s or write it to "
                    "%s, then re-run. Nothing has been sent."
                    % (prov, m,
                       "OPENROUTER_API_KEY" if prov == infer.OPENROUTER
                       else "ANTHROPIC_API_KEY",
                       infer.OPENROUTER_KEY_FILE
                       if prov == infer.OPENROUTER else infer.KEY_FILE))
    report = {"targets": {}, "prices_as_of": infer.PRICES_AS_OF,
              "synth_model": args.synth_model,
              "direct_model": args.direct_model,
              "note": "agreement with the adapter, "
                                      "not accuracy - see module docstring"}

    if args.cells:
        run_cells(client, args)
        return

    for key in args.targets.split(","):
        target = TARGETS[key.strip()]
        pages = corpus(target)
        print("\n=== %s: %s" % (target.key, target.label))
        print("    %d index pages in the manifest" % len(pages))
        if not pages:
            continue

        refs, total = {}, 0
        for fn, p in pages:
            refs[fn] = target.reference(read(p))
            total += len(refs[fn])
        print("    adapter reference: %d records over %d pages (%.0f/page)"
              % (total, len(pages), total / float(len(pages))))

        checks = validate_scorer(target, refs[pages[0][0]])
        bad = [n for n, ok in checks if not ok]
        for n, ok in checks:
            print("      scorer %-40s %s" % (n, "ok" if ok else "FAILED"))
        if bad:
            raise SystemExit("scorer is broken; no calls made")

        if args.draws > 1:
            per = plan(target, pages, refs, args)["synth_usd"]
            print("    variance: %d draws x $%.4f worst case = $%.2f ceiling"
                  % (args.draws, per, args.draws * per))
            if args.run:
                run_variance(client, target, pages, refs, args)
            else:
                print("    (dry run - nothing sent; add --run)")
            continue

        pl = plan(target, pages, refs, args)
        print("    arm S  1 call, ~%.1fk in (%.0f%% of the page, window at "
              "char %d), <= %dk out  ->  $%.3f worst case"
              % (pl["synth_in"] / 1000.0, 100 * pl["synth_window_frac"],
                 pl["synth_window_at"], args.synth_tokens // 1000,
                 pl["synth_usd"]))
        for fn, n_in, cap, usd in pl["direct"]:
            print("    arm D  %-34s ~%.1fk in, <= %.1fk out  ->  $%.3f"
                  % (fn, n_in / 1000.0, cap / 1000.0, usd))
        rep = report["targets"][target.key] = {
            "pages": len(pages), "reference_records": total,
            "plan": {k: v for k, v in pl.items() if k != "direct"},
        }
        if args.run:
            run_target(client, target, pages, refs, args, rep)

    rows = client.ledger.rows()
    print("\nledger: %d calls, $%.4f lifetime"
          % (len(rows), sum(r.get("usd", 0.0) for r in rows)))
    for cls, a in sorted(client.ledger.by_class().items()):
        print("  %-12s %3d calls  $%7.4f  in %8d  out %7d  cache-read %8d"
              % (cls, a["calls"], a["usd"], a["in"], a["out"],
                 a["cache_read"]))
    # Merge rather than overwrite, keyed by target and model tier. A run at
    # the cheap tier and a run at the expensive one are the comparison; a
    # writer that clobbers means the second run destroys the thing the first
    # was for. Learned by doing it.
    path = os.path.join(OUT, "conformance.json")
    prior = {}
    if os.path.exists(path):
        try:
            prior = json.load(io.open(path, encoding="utf-8"))
        except ValueError:
            prior = {}
    runs = prior.get("runs", {})
    for key, rep in report["targets"].items():
        for arm in ("arm_s", "arm_d"):
            if arm not in rep:
                continue
            model = rep[arm].get("model") or (
                args.synth_model if arm == "arm_s" else args.direct_model)
            runs["%s|%s|%s" % (key, arm, model)] = rep[arm]
    out = {"runs": runs, "prices_as_of": infer.PRICES_AS_OF,
           "note": report["note"],
           "reference": {k: {"pages": v["pages"],
                                  "records": v["reference_records"]}
                             for k, v in report["targets"].items()}}
    out["reference"].update(prior.get("reference", {}))
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(out, indent=1, sort_keys=True, default=str))
    print("wrote data/infer/conformance.json (%d runs recorded)" % len(runs))


# ----------------------------------------------------- variance over draws
def run_variance(client, target, pages, refs, args):
    """k independent draws of one identical synthesis request: a pass@1 rate,
    in the pass@k family (Chen et al., 2021) of repeated-sampling code-gen
    evaluation.

    Every figure in the published conformance run is a single draw from a
    stochastic process, so none of them carries a variance and "Haiku fails
    Accela synthesis" is one observation rather than a rate. This measures
    the rate.

    Sampling here is not controlled, it is *pinned*: extended thinking
    permits only temperature 1.0 - measured 2026-09-21, the API answers
    anything else with a 400. That is the setting the published run used, so
    these draws sample the same condition and are comparable to it rather
    than being a different experiment.

    A draw succeeds only if the generated module clears the AST audit, runs
    on every page without raising, and agrees with the adapter perfectly on
    every page. Anything less is a failure. A strict criterion is the honest
    one when the alternative is partial credit nobody can act on.
    """
    win, _frac, _at = window(read(pages[0][1]), args.synth_window)
    tier = infer.short_model(args.synth_model)
    prompt = ("Portal page excerpt (one page of the result grid, stripped of "
              "scripts, styles and non-structural attributes):\n\n" + win)
    vdir = os.path.join(SYNTH, "variance")
    if not os.path.isdir(vdir):
        os.makedirs(vdir)
    corpus_pages = [q for _, q in stripped_corpus(target, pages)]

    draws, usd = [], 0.0
    for d in range(args.draws):
        rec = {"draw": d, "model": args.synth_model, "target": target.key}
        try:
            text, usage, meta = client.message(
                args.synth_model, SYNTH_SYSTEM, prompt, args.synth_tokens,
                "synthesis", thinking=True,
                tag="%s/var" % target.key, draw=d)
        except (infer.Refused, infer.ApiError) as e:
            # Out of budget or out of credit. Stop this cell, keep every draw
            # already paid for, and record which of the two it was.
            rec["outcome"] = "not_attempted"
            rec["why"] = str(e)[:200]
            draws.append(rec)
            print("      draw %2d  STOPPED: %s" % (d, str(e)[:88]))
            break
        usd += meta["usd"]
        rec.update({"usd": meta["usd"], "cached": meta["cached"],
                    "truncated": meta.get("truncated"),
                    "output_tokens": usage.get("output_tokens", 0)})
        src = extract_block(text, CODEBLOCK, "def extract(")
        rec["bytes"] = len(src)
        if not src:
            rec["outcome"] = "no_code"
        else:
            problems, imports = audit(src)
            rec["imports"] = imports
            rec["audit_problems"] = problems
            if problems:
                rec["outcome"] = "refused"
            else:
                sp = os.path.join(vdir, "%s_%s_d%02d.py"
                                  % (target.key, tier, d))
                with io.open(sp, "w", encoding="utf-8") as fh:
                    fh.write(src)
                rec["source"] = sp
                res, err = run_synth(sp, corpus_pages)
                if err:
                    rec["outcome"] = "exec_error"
                    rec["error"] = err[:300]
                else:
                    raised = [i for i in res if not i["ok"]]
                    rec["raised_on"] = len(raised)
                    if raised:
                        rec["outcome"] = "raised"
                        rec["error"] = (raised[0].get("error") or "")[:200]
                    else:
                        sc = [score(target,
                                    refs[os.path.basename(i["page"])],
                                    i["rows"]) for i in res]
                        rr = [x["recall"] or 0.0 for x in sc]
                        pp = [x["precision"] or 0.0 for x in sc]
                        rec["recall_min"] = min(rr)
                        rec["recall_mean"] = sum(rr) / len(rr)
                        rec["precision_min"] = min(pp)
                        rec["pages_scored"] = len(sc)
                        rec["outcome"] = ("perfect"
                                          if min(rr) == 1.0 and min(pp) == 1.0
                                          else "imperfect")
        draws.append(rec)
        print("      draw %2d  %-12s %5d bytes  out=%-6s $%.4f%s"
              % (d, rec["outcome"], rec.get("bytes", 0),
                 rec.get("output_tokens", "-"), rec.get("usd", 0.0),
                 "  (replayed)" if rec.get("cached") else ""))
        # Saved after every draw: a key that dies at draw 14 of 20 must leave
        # 14 measurements behind, not nothing.
        save_variance(target, args, draws, usd)

    ok = sum(1 for r in draws if r.get("outcome") == "perfect")
    n = sum(1 for r in draws if r.get("outcome") != "not_attempted")
    lo, hi = wilson(ok, n)
    print("    %s x %s: %d/%d perfect   rate %.2f   95%% CI [%.3f, %.3f]"
          "   $%.4f" % (target.key, tier, ok, n,
                        (float(ok) / n) if n else 0.0, lo, hi, usd))
    return draws, usd


def save_variance(target, args, draws, usd):
    """Merge this cell into data/infer/variance.json, keyed target|model."""
    path = os.path.join(OUT, "variance.json")
    prior = {}
    if os.path.exists(path):
        try:
            prior = json.load(io.open(path, encoding="utf-8"))
        except ValueError:
            prior = {}
    cells = prior.get("cells", {})
    ok = sum(1 for r in draws if r.get("outcome") == "perfect")
    n = sum(1 for r in draws if r.get("outcome") != "not_attempted")
    lo, hi = wilson(ok, n)
    counts = {}
    for r in draws:
        counts[r.get("outcome")] = counts.get(r.get("outcome"), 0) + 1
    cells["%s|%s" % (target.key, args.synth_model)] = {
        "target": target.key, "model": args.synth_model,
        "draws_attempted": n, "perfect": ok,
        "rate": (float(ok) / n) if n else None,
        "ci95": [round(lo, 4), round(hi, 4)],
        "outcomes": counts, "usd": round(usd, 6),
        "synth_tokens": args.synth_tokens,
        "synth_window": args.synth_window,
        "temperature": "1.0 (pinned by extended thinking)",
        "detail": draws,
    }
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"cells": cells,
                             "prices_as_of": infer.PRICES_AS_OF,
                             "note": "agreement with the adapter, not "
                                     "accuracy; success = perfect on "
                                     "every page"},
                            indent=1, sort_keys=True, default=str))


def run_cells(client, args):
    """Run an explicit target x model x draws allocation in one session.

    The point of one session is the budget. `Budget` accumulates `spent` per
    process, so five separate invocations would each get a fresh ceiling and
    five times the authorized spend - which is not a ceiling at all. One
    process means `--max-spend` caps the experiment.

    Draws are not spread evenly. A cell already at a ceiling cannot vary
    informatively, so draws go where the outcome can still move: most to the
    cheap cell that failed, fewest to the expensive cell already known to
    work.
    """
    spec = []
    for cell in args.cells.split(","):
        # Split off the target at the first colon and the draw count at the
        # last, rather than splitting on every colon: an OpenRouter model id
        # may contain one itself, as in `openai/gpt-oss-120b:batch`, and a
        # three-way split would reject the cheapest models on the menu.
        cell = cell.strip()
        if cell.count(":") < 2:
            raise SystemExit("bad --cells entry %r, want target:model:draws"
                             % cell)
        tkey, rest = cell.split(":", 1)
        model, draws = rest.rsplit(":", 1)
        try:
            n = int(draws)
        except ValueError:
            raise SystemExit("bad draw count %r in --cells entry %r"
                             % (draws, cell)) from None
        spec.append((tkey, model, n))

    loaded = {}
    total_worst = 0.0
    print("\nallocation")
    for tkey, model, n in spec:
        if tkey not in loaded:
            target = TARGETS[tkey]
            pages = corpus(target)
            refs = {}
            for fn, q in pages:
                refs[fn] = target.reference(read(q))
            checks = validate_scorer(target, refs[pages[0][0]])
            bad = [nm for nm, ok in checks if not ok]
            if bad:
                raise SystemExit("scorer broken for %s: %s; no calls made"
                                 % (tkey, ", ".join(bad)))
            loaded[tkey] = (target, pages, refs)
            print("  %-9s %d pages, %d reference records, scorer %d/%d ok"
                  % (tkey, len(pages), sum(len(v) for v in refs.values()),
                     len(checks) - len(bad), len(checks)))
        target, pages, refs = loaded[tkey]
        saved = args.synth_model
        args.synth_model = model
        try:
            worst = plan(target, pages, refs, args)["synth_usd"] * n
        except infer.Refused as e:
            # An unpriced model is a refusal, not a crash. It is the most
            # likely thing to be wrong about a hand-typed --cells line, and a
            # traceback buries the one sentence that says how to fix it.
            raise SystemExit("%s Nothing has been sent." % e) from None
        finally:
            args.synth_model = saved
        total_worst += worst
        print("  %-9s %-26s %2d draws   <= $%.2f worst case"
              % (tkey, model, n, worst))
    print("  %-37s %s   <= $%.2f worst case, ceiling $%.2f"
          % ("TOTAL", sum(n for _, _, n in spec), total_worst,
             args.max_spend))
    if not args.run:
        print("\n  dry run - nothing sent. Add --run.")
        return

    for tkey, model, n in spec:
        target, pages, refs = loaded[tkey]
        args.synth_model = model
        args.draws = n
        print("\n=== %s x %s, %d draws" % (tkey, model, n))
        run_variance(client, target, pages, refs, args)

    rows = client.ledger.rows()
    print("\nledger: %d calls, $%.4f lifetime"
          % (len(rows), sum(r.get("usd", 0.0) for r in rows)))
    print("this session: $%.4f of $%.2f ceiling"
          % (client.budget.spent, client.budget.ceiling))


# ------------------------------------------------------------------- drift
# Realistic template drift, not adversarial noise. Every mutation preserves
# the records a human reads off the page and changes only how they are
# marked up, which is what makes this eval free: the adapter's parse of the
# *clean* page stays the correct answer, so nothing needs labelling.
#
# Each one is a thing portals actually do. ASP.NET renumbers control ids when
# the control hierarchy changes; a restyle renames classes; a vendor upgrade
# adds a wrapper or a column. None of these is a content change, and an
# extractor that survives them is one that keyed on structure rather than on
# the literal bytes of one capture.
QUOTED = r'("[^"]*"|\'[^\']*\')'


def _requote(raw, inner):
    return raw[0] + inner + raw[0]


def m_id_suffix(h):
    """ctl00_X -> ctl00_ctl99_X. The single most common real drift on .NET."""
    return re.sub(r'\b(id|name)\s*=\s*' + QUOTED,
                  lambda m: '%s=%s' % (m.group(1),
                                       _requote(m.group(2),
                                                "ctl99_" + m.group(2)[1:-1])),
                  h)


def m_class_rename(h):
    return re.sub(r'\bclass\s*=\s*' + QUOTED,
                  lambda m: 'class=%s' % _requote(
                      m.group(1),
                      " ".join(v + "_x" for v in m.group(1)[1:-1].split())),
                  h)


def m_attr_reorder(h):
    """Reverse attribute order inside every start tag."""
    attr = re.compile(r'([\w:-]+)(\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>]+))?')

    def tag(m):
        name, body = m.group(1), m.group(2)
        found = [x.group(0) for x in attr.finditer(body) if x.group(0).strip()]
        return "<%s %s>" % (name, " ".join(reversed(found))) if found \
            else m.group(0)
    return re.sub(r'(?s)<([a-zA-Z][\w:-]*)((?:"[^"]*"|\'[^\']*\'|[^>"\'])*)>',
                  tag, h)


def m_wrapper_div(h):
    h = re.sub(r'(?i)<table\b', '<div class="pnlWrap"><table', h)
    return re.sub(r'(?i)</table\s*>', '</table></div>', h)


INNER = '<table class="innerLayout"><tr><td></td></tr></table>'


def m_nested_table(h):
    """A nested table in the first cell of each row.

    This is the shape that killed the published Haiku extractor: a non-greedy
    `</table>` match closes on the inner table and captures nothing.
    """
    def row(m):
        return re.sub(r'(?i)(<td\b[^>]*>)', r'\1' + INNER, m.group(0), count=1)
    return TR.sub(row, h)


def m_whitespace(h):
    return re.sub(r'>\s*<', '>\n  <', h)


def m_column_append(h):
    def row(m):
        r = m.group(0)
        cell = "<th>Extra</th>" if re.search(r'(?i)<th\b', r) else "<td>-</td>"
        return re.sub(r'(?i)</tr\s*>$', cell + "</tr>", r)
    return TR.sub(row, h)


def m_header_case(h):
    return re.sub(r'(?is)(<th\b[^>]*>)(.*?)(</th>)',
                  lambda m: m.group(1) + m.group(2).upper() + m.group(3), h)


MUTATORS = [
    ("id_suffix", m_id_suffix),
    ("class_rename", m_class_rename),
    ("attr_reorder", m_attr_reorder),
    ("wrapper_div", m_wrapper_div),
    ("nested_table", m_nested_table),
    ("whitespace", m_whitespace),
    ("column_append", m_column_append),
    ("header_case", m_header_case),
]


# ------------------------------------------- how a draw failed, not just if
# The published conformance run credited the "fail loudly" instruction in the
# synthesis prompt with turning a silent zero into a visible one, on the
# strength of one draw that did exactly that. Whether that generalises is a
# question about the *distribution* of failure modes, and it is the question
# this taxonomy exists to answer.
#
# The distinction that matters operationally is not perfect-versus-broken. It
# is loud-versus-silent. A module that raises stops a pipeline and gets
# noticed; a module that returns [] for a page looks like a quiet week in the
# permit office, and every downstream count is wrong with nothing to show for
# it. D1 exists because of that failure family.
def variance_report():
    path = os.path.join(OUT, "variance.json")
    if not os.path.exists(path):
        raise SystemExit("no variance.json; run --cells first")
    cells = json.load(io.open(path, encoding="utf-8"))["cells"]
    print("\nfailure taxonomy by cell   (success = perfect on every page)")
    print("%-42s %5s %8s %8s %8s %8s   %-18s %s"
          % ("cell", "n", "perfect", "s-part", "s-empty", "loud",
             "success 95% CI", "silent"))
    for key, c in sorted(cells.items()):
        det = [d for d in c["detail"]
               if d.get("outcome") != "not_attempted"]
        if not det:
            continue
        counts = dict.fromkeys(ORDER, 0)
        for d in det:
            counts[failure_mode(d)] = counts.get(failure_mode(d), 0) + 1
        n = len(det)
        lo, hi = wilson(counts["perfect"], n)
        silent = counts["silent_partial"] + counts["silent_empty"]
        slo, shi = wilson(silent, n)
        print("%-42s %5d %8d %8d %8d %8d   [%.2f, %.2f]       %d/%d [%.2f, %.2f]"
              % (key, n, counts["perfect"], counts["silent_partial"],
                 counts["silent_empty"], counts["loud"], lo, hi,
                 silent, n, slo, shi))
    print("\n  s-part  returned rows, some missing, no exception")
    print("  s-empty returned zero rows on a page, no exception")
    print("  loud    raised, or refused by the AST audit")

    # The denominator is failures, not draws. Dividing silent failures
    # by every draw understates the rate whenever a cell mostly
    # succeeds, and the question is only about the failures: when this
    # goes wrong, does it say so, or does it hand back a quiet zero.
    allsil = allfail = alln = 0
    for c in cells.values():
        for d in c["detail"]:
            m = failure_mode(d)
            if m == "not_attempted":
                continue
            alln += 1
            if m == "perfect":
                continue
            allfail += 1
            if m in ("silent_partial", "silent_empty"):
                allsil += 1
    if allfail:
        lo, hi = wilson(allsil, allfail)
        print("\n  %d draws, %d failures, %d of them SILENT (%.0f%%)"
              "   95%% CI [%.2f, %.2f]"
              % (alln, allfail, allsil, 100.0 * allsil / allfail,
                 lo, hi))
        print("  the published run saw one loud failure and credited "
              "the prompt instruction for it")


def variance_pool(target_key, model=None):
    """The synthesized extractors that passed the conformance test.

    Drift survival is only a meaningful question about an extractor that
    worked in the first place. A draw that was already broken on the clean
    corpus would count as a drift failure and drag the rate down for a reason
    that has nothing to do with drift, so the pool is exactly the draws whose
    outcome was `perfect`.

    That makes the population an honest one to name: *among synthesized
    extractors that passed conformance, how many survive template drift?*
    """
    path = os.path.join(OUT, "variance.json")
    if not os.path.exists(path):
        return []
    try:
        cells = json.load(io.open(path, encoding="utf-8")).get("cells", {})
    except ValueError:
        return []
    out = []
    for _key, cell in sorted(cells.items()):
        if cell.get("target") != target_key:
            continue
        if model and cell.get("model") != model:
            continue
        tier = infer.short_model(cell["model"])
        for d in cell.get("detail", []):
            if d.get("outcome") == "perfect" and d.get("source"):
                if os.path.exists(d["source"]):
                    out.append(("draw %s d%02d" % (tier, d["draw"]),
                                d["source"]))
    return out


def faithful(target, ref_rows, mutated):
    """Positive control: did the mutation keep the records?

    A mutation that deletes content would score every extractor to zero and
    look like a devastating robustness finding. So each mutated page is
    checked for the adapter's own native ids before anything is scored, and a
    mutation that loses any of them is reported as broken rather than run.
    This is the control the stripper never had.
    """
    rk = target.roles["native_id"]
    ids = [norm(r.get(rk)) for r in ref_rows]
    return sum(1 for i in ids if i and i not in mutated), len(
        [i for i in ids if i])


def drift_pages(target, pages, name, fn):
    """Mutated copies, raw and stripped, written where they can be read."""
    draw = os.path.join(OUT, "drift", target.key, name)
    if not os.path.isdir(draw):
        os.makedirs(draw)
    out = []
    for f, q in pages:
        mut = fn(read(q))
        rawp = os.path.join(draw, f)
        strp = os.path.join(draw, "stripped_" + f)
        with io.open(rawp, "w", encoding="utf-8") as fh:
            fh.write(mut)
        with io.open(strp, "w", encoding="utf-8") as fh:
            fh.write(strip(mut))
        out.append((f, rawp, strp, mut))
    return out


def perfect(scores):
    return bool(scores) and all(
        (s.get("recall") or 0.0) == 1.0 and (s.get("precision") or 0.0) == 1.0
        for s in scores)


def run_drift(args):
    """Every extractor against every mutation. No model calls at all.

    The reference is the adapter's parse of the *clean* page, so the
    hand-written adapter is scored here on exactly the same footing as the
    synthesized ones - which makes this the first head-to-head measurement of
    whether a synthesized extractor is more or less brittle than the parser a
    human wrote for the same grid.
    """
    report = {}
    for key in args.targets.split(","):
        target = TARGETS[key.strip()]
        pages = corpus(target)[:args.drift_pages]
        if not pages:
            continue
        refs = {}
        for f, q in pages:
            refs[f] = target.reference(read(q))
        n_ref = sum(len(v) for v in refs.values())
        print("\n=== drift: %s, %d pages, %d reference records"
              % (target.key, len(pages), n_ref))

        cands = [("adapter (hand-written)", None)]
        for f in sorted(os.listdir(SYNTH)):
            if f.startswith(target.key) and f.endswith("_extract.py"):
                cands.append(("synth " + f[len(target.key) + 1:-11],
                              os.path.join(SYNTH, f)))
        pool = variance_pool(target.key) if args.drift_variance else []
        cands.extend(pool)
        print("    candidates: %d (%d published, %d conformance-passing "
              "draws)" % (len(cands), len(cands) - len(pool), len(pool)))

        rows = {}
        for name, fn in [("clean", lambda x: x), *MUTATORS]:
            muts = drift_pages(target, pages, name, fn)
            lost = sum(faithful(target, refs[f], m)[0] for f, _, _, m in muts)
            tot = sum(faithful(target, refs[f], m)[1] for f, _, _, m in muts)
            if lost:
                print("    %-14s CONTROL FAILED: %d/%d record ids lost; "
                      "not scored" % (name, lost, tot))
                rows[name] = {"control": "failed", "ids_lost": lost}
                continue
            cell = {}
            for label, src in cands:
                if src is None:
                    sc = []
                    for f, rawp, _, _ in muts:
                        try:
                            sc.append(score(target, refs[f],
                                            _as_rows(target,
                                                     target.reference(
                                                         read(rawp)))))
                        except Exception as e:
                            sc.append({"recall": 0.0, "precision": 0.0,
                                       "error": str(e)[:120]})
                else:
                    res, err = run_synth(src, [t for _, _, t, _ in muts],
                                         runner_name="_drift_runner.py")
                    if err:
                        cell[label] = {"survived": False, "why": "exec_error"}
                        continue
                    sc = []
                    for item in res:
                        f = os.path.basename(item["page"])[len("stripped_"):]
                        if not item["ok"]:
                            sc.append({"recall": 0.0, "precision": 0.0,
                                       "error": (item.get("error") or "")[:120]})
                        else:
                            sc.append(score(target, refs[f], item["rows"]))
                cell[label] = {
                    "survived": perfect(sc),
                    "recall_min": min((s.get("recall") or 0.0) for s in sc),
                    "precision_min": min((s.get("precision") or 0.0)
                                         for s in sc),
                    "errors": sum(1 for s in sc if "error" in s),
                }
            rows[name] = cell
            print("    %-14s %s" % (name, "  ".join(
                "%s=%s" % (name.split()[-1],
                           "OK " if cell[name].get("survived")
                           else "BREAK")
                for name, _ in cands)))
        report[target.key] = {"pages": len(pages), "reference_records": n_ref,
                              "candidates": [c for c, _ in cands],
                              "pool": [c for c, _ in pool],
                              "mutations": rows}

    path = os.path.join(OUT, "drift.json")
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"targets": report,
                             "note": "reference is the adapter's parse of "
                                     "the CLEAN page; mutations preserve "
                                     "records and are control-checked"},
                            indent=1, sort_keys=True, default=str))
    print("\nwrote data/infer/drift.json")
    summarize_drift(report)


def _as_rows(target, rows):
    """Adapter output re-keyed into the role names the scorer compares."""
    out = []
    for r in rows:
        out.append({role: r.get(col)
                        for role, col in target.roles.items()})
    return out


def summarize_drift(report):
    print("\n--- survival matrix (OK = perfect agreement on every page) ---")
    for tkey, rep in sorted(report.items()):
        cands = rep["candidates"]
        print("\n%s" % tkey)
        print("  %-14s %s" % ("mutation",
                              "  ".join("%-22s" % c for c in cands)))
        for name, cell in rep["mutations"].items():
            if cell.get("control") == "failed":
                print("  %-14s %s" % (name, "(control failed)"))
                continue
            print("  %-14s %s" % (name, "  ".join(
                "%-22s" % ("OK" if cell.get(c, {}).get("survived")
                           else "BREAK r=%.2f" % cell.get(c, {}).get(
                               "recall_min", 0.0))
                for c in cands)))
        pool = rep.get("pool") or []
        muts = [(k, v) for k, v in rep["mutations"].items()
                if k != "clean" and v.get("control") != "failed"]
        for c in cands:
            if c in pool:
                continue
            n = sum(1 for _, v in muts if v.get(c, {}).get("survived"))
            lo, hi = wilson(n, len(muts))
            print("  survived %-24s %d/%d   95%% CI [%.2f, %.2f]"
                  % (c, n, len(muts), lo, hi))
        if pool:
            print("\n  conformance-passing draws, n=%d extractors:" % len(pool))
            for name, _ in sorted((k, v) for k, v in rep["mutations"].items()
                                  if k != "clean"):
                cell = rep["mutations"][name]
                if cell.get("control") == "failed":
                    continue
                k = sum(1 for c in pool if cell.get(c, {}).get("survived"))
                lo, hi = wilson(k, len(pool))
                print("    %-14s %2d/%-2d survived   95%% CI [%.2f, %.2f]"
                      % (name, k, len(pool), lo, hi))
            tot = sum(1 for c in pool for _, v in muts
                      if v.get(c, {}).get("survived"))
            den = len(pool) * len(muts)
            lo, hi = wilson(tot, den)
            print("    %-14s %2d/%-2d overall     95%% CI [%.2f, %.2f]"
                  % ("ALL", tot, den, lo, hi))
            allsurv = sum(1 for c in pool
                          if all(v.get(c, {}).get("survived") for _, v in muts))
            lo, hi = wilson(allsurv, len(pool))
            print("    %-14s %2d/%-2d survived every mutation   "
                  "95%% CI [%.2f, %.2f]" % ("perfect", allsurv, len(pool),
                                            lo, hi))


def run_target(client, target, pages, refs, args, rep):
    # ---- arm S ---------------------------------------------------------
    win, frac, _at = window(read(pages[0][1]), args.synth_window)
    tier = infer.short_model(args.synth_model)
    text, usage, meta = client.message(
        args.synth_model, SYNTH_SYSTEM,
        "Portal page excerpt (one page of the result grid, stripped of "
        "scripts, styles and non-structural attributes):\n\n" + win,
        args.synth_tokens, "synthesis", thinking=True, tag=target.key)
    src = extract_block(text, CODEBLOCK, "def extract(")
    # Keyed by model: a second tier's extractor must not overwrite the first's,
    # or the two are not comparable afterwards and the cheap run has destroyed
    # the artifact the expensive one produced.
    path = os.path.join(SYNTH, "%s_%s_extract.py" % (target.key, tier))
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(src)
    problems, imports = audit(src)
    print("    arm S: %d bytes, imports %s%s"
          % (len(src), ", ".join(imports) or "nothing",
             ("; REFUSED: " + "; ".join(problems)) if problems else ""))
    rep["arm_s"] = {"model": args.synth_model, "usd": meta["usd"],
                    "cached": meta["cached"], "source": path,
                    "bytes": len(src), "imports": imports,
                    "audit_problems": problems, "window_frac": frac,
                    "truncated": meta.get("truncated"),
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0)}
    if not problems:
        res, err = run_synth(path, [q for _, q in stripped_corpus(target,
                                                                  pages)])
        if err:
            rep["arm_s"]["error"] = err
            print("    arm S: execution failed: %s" % err[:300])
        else:
            per, agg = {}, []
            for item in res:
                fn = os.path.basename(item["page"])
                if not item["ok"]:
                    per[fn] = {"error": item["error"]}
                    continue
                per[fn] = score(target, refs[fn], item["rows"])
                agg.append(per[fn])
            rep["arm_s"]["pages"] = per
            rep["arm_s"]["raised_on"] = sorted(
                f for f, v in per.items() if "error" in v)
            summarize("arm S", agg, len(pages))

    # ---- arm D ---------------------------------------------------------
    # Whole pages, always. A truncated page would make recall an artifact of
    # the truncation, and the question of whether direct extraction quietly
    # drops records once a page is long is one of the things worth knowing.
    d_scores, d_usd = [], 0.0
    for fn, p in pages[:args.direct_pages]:
        cap = direct_budget(len(refs[fn]))
        text, usage, meta = client.message(
            args.direct_model, DIRECT_SYSTEM,
            "Portal page (stripped of scripts, styles and non-structural "
            "attributes):\n\n" + strip(read(p)),
            cap, "extraction", tag="%s/%s" % (target.key, fn))
        d_usd += meta["usd"]
        try:
            rows = json.loads(extract_block(text, JSONBLOCK))
        except ValueError as e:
            d_scores.append({"page": fn, "error": "bad JSON: %s" % e,
                             "truncated": meta.get("truncated"),
                             "usd": meta["usd"]})
            print("    arm D: %s -> unparseable output (truncated=%s)"
                  % (fn, meta.get("truncated")))
            continue
        if not isinstance(rows, list):
            # Valid JSON that is not an array. `null` would crash the scorer
            # and an object would iterate its keys, match nothing, and report
            # a clean zero - the silent-failure mode this project exists to
            # measure, arriving through the harness instead of the model.
            d_scores.append({"page": fn,
                             "error": "not a JSON array: %s"
                                      % type(rows).__name__,
                             "truncated": meta.get("truncated"),
                             "usd": meta["usd"]})
            print("    arm D: %s -> output was %s, not an array"
                  % (fn, type(rows).__name__))
            continue
        sc = score(target, refs[fn], rows)
        sc.update({"page": fn, "usd": meta["usd"],
                   "truncated": meta.get("truncated"),
                   "input_tokens": usage.get("input_tokens", 0),
                   "output_tokens": usage.get("output_tokens", 0)})
        d_scores.append(sc)
    rep["arm_d"] = {"usd": d_usd, "pages": d_scores}
    summarize("arm D", [s for s in d_scores if "recall" in s],
              args.direct_pages)


def summarize(label, scores, n_pages):
    if not scores:
        print("    %s: nothing scored" % label)
        return
    rec = [s["recall"] for s in scores if s.get("recall") is not None]
    pre = [s["precision"] for s in scores if s.get("precision") is not None]
    tot = sum(s["ref_records"] for s in scores)
    print("    %s: %d/%d pages parsed, %d reference records, "
          "recall %.4f, precision %.4f"
          % (label, len(scores), n_pages, tot,
             sum(rec) / len(rec) if rec else 0,
             sum(pre) / len(pre) if pre else 0))
    fields = {}
    for s in scores:
        for k, v in s.get("fields", {}).items():
            a = fields.setdefault(k, [0, 0])
            a[0] += v["agree"]
            a[1] += v["compared"]
    for k in sorted(fields):
        agree, comp = fields[k]
        print("        %-16s %6d/%-6d  %s"
              % (k, agree, comp,
                 ("%.4f" % (agree / float(comp))) if comp else "-"))


if __name__ == "__main__":
    main()
