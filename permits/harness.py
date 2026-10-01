# -*- coding: utf-8 -*-
"""The conformance harness's task: the targets and their pages, the synthesis
prompt, and the scorer that grades an extractor against the adapters.

Moved verbatim from `scripts/conformance.py` on 2026-09-30, so that a second
tool, `scripts/agent_eval.py`, scores the agent's extractors with the code
that scored the v2 run's draws; `conformance.py` re-exports every name.
`permits/agent/` may not import this module, since it holds the reference
parsers and the scorer (`tests/test_structure.py`).
"""
import csv
import io
import os
import re

from permits import strip as _strip
from permits.adapters import accela, stjohns
from permits.sandbox import TD, data_rows

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = os.path.join(ROOT, "data", "step1", "pages")
MANIFEST = os.path.join(ROOT, "data", "step1", "manifest.csv")
OUT = os.path.join(ROOT, "data", "infer")


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

# ------------------------------------------------------------ the targets
class Target(object):
    def __init__(self, key, jurisdiction, vendor, adapter, roles, label,
                 split="dev", prefix=None):
        self.key = key
        self.jurisdiction = jurisdiction
        self.vendor = vendor
        self.adapter = adapter
        # role -> the key the adapter's parse_index() puts it under. The only
        # place the two vocabularies are joined, written out rather than
        # inferred so a scoring change is a visible diff.
        self.roles = roles
        self.label = label
        # "dev": prompts, including the hint, were written while reading this
        # target's pages and model output on them. "test": held out - no
        # prompt was written against it, and it is only ever scored.
        self.split = split
        # Only manifest files whose name starts with this. A held-out target
        # is one closed window's walk; an earlier one-off page of the same
        # portal is a different sample and stays out of its corpus.
        self.prefix = prefix

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
    # Held out: pages fetched by spikes/heldout_fetch.py, one closed window
    # each. Same vendor as Clark, different template - column set, column
    # order, or which rows carry a detail link - so a pass here says the
    # extractor learned the grid rather than Clark's layout.
    "santabarbara": Target(
        "santabarbara", "santabarbara", "accela-aca", accela,
        {"native_id": "number", "address": "address",
         "permit_type": "type", "status": "status",
         "issued_date": "date"},
        "Santa Barbara CA - Accela ACA grid (held out)",
        split="test", prefix="acc_santabarbara_ho"),
    "polkco": Target(
        "polkco", "POLKCO", "accela-aca", accela,
        {"native_id": "number", "address": "address",
         "permit_type": "type", "status": "status",
         "issued_date": "date"},
        "Polk County - Accela ACA grid (held out)",
        split="test", prefix="acc_POLKCO_ho"),
    "oregon": Target(
        "oregon", "oregon", "accela-aca", accela,
        {"native_id": "number", "address": "address",
         "permit_type": "type", "status": "status",
         "issued_date": "date"},
        "Oregon statewide - Accela ACA grid (held out)",
        split="test", prefix="acc_oregon_ho"),
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
                and r["http_status"] == "200"
                and r["verdict"] == "ok"
                and r["file"].startswith(target.prefix or "")):
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

    **Version three failed too, on the first held-out page** (Santa Barbara,
    2026-09-27, before any model saw it). Its search form puts seven 4- and
    5-cell layout rows near the top, and its record rows are long enough that
    a span over the grid holds only six, so the window showed the form and
    none of the ten records. Clark and Polk County had escaped by 7 to 5 and
    6 to 5. The fallback: a results grid's rows share one width, the most
    common cell count among data rows. If the chosen window holds fewer than
    `MIN_GRID_ROWS` of them, it starts at the first one, the grid's header,
    instead. Where version three worked the window is unchanged, byte for
    byte, on every stored page of both development targets; a different
    selection rule was tried first and moved every Clark window.
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
    grid = grid_rows(s, rows)
    if grid and sum(1 for a, b in grid
                    if a >= best and b <= best + span) < MIN_GRID_ROWS:
        best = grid[0][0]
    return (s[:head] + "\n...[document elided]...\n" + s[best:best + span],
            float(budget) / len(s), best)


MIN_GRID_ROWS = 3


def grid_rows(s, rows):
    """The data rows of the grid's width: the most common cell count among
    `rows`, the wider on a tie."""
    width = [len(TD.findall(s[a:b])) for a, b in rows]
    if not width:
        return []
    counts = {w: width.count(w) for w in width}
    top = max(counts.values())
    w_grid = max(w for w, n in counts.items() if n == top)
    return [r for r, w in zip(rows, width, strict=True) if w == w_grid]


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
