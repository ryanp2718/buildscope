# -*- coding: utf-8 -*-
"""The production check: is an extractor's output plausible, with no reference
to compare it against?

It sees a portal's pages and an extractor's output, never the adapter, the
reference records or the scorer. Validated offline on the v2 run's stored
extractors (docs/evidence/2026-09-29-agentic-extractor-plan.md, step 1):
0.6% of the extractors it accepts fail the scorer, and it rejects 0.8% of
the ones the scorer passes. Moved here from `spikes/verifier_offline.py` on
2026-09-30, unchanged, so the agent can call it.

**Checks** decide acceptance. All per page:

- rows: the number of rows returned equals the page's grid rows, counted by a
  generic rule fixed on the development targets before Santa Barbara was
  looked at: of the `<tr>` elements with at least four cells and at least one
  `<td>`, those whose cell count is the most common across the portal's
  pages. It matched the reference count on all 71 development pages.
- ids: every row has a non-empty `native_id`, and no two rows on a page share
  one.
- clean: every value is a string or None, and none contains markup.
- dates: at least 90% of the non-null `issued_date` values look like a date.

**Notes** do not decide acceptance. They were written after the offline
validation, from failure cases 5 and 6 in `docs/design/failure-cases.md`, so
they are post hoc, and each has a legitimate exception a check could not
tell apart:

- edges: values that start or end with `<` or `>`, the remains of a tag cut
  in the wrong place (failure case 6).
- empty: fields that are null on every row of every page. The contract says a
  field the page does not print is null, so this is right on some portals
  and a dropped column on others (failure case 5).
"""
import collections
import re
from typing import Any

from permits.sandbox import TD, data_rows

HAS_TD = re.compile(r"(?i)<td\b")
MARKUP = re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>")
DATE = re.compile(r"\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}|"
                  r"[A-Za-z]{3,9}\.? \d{1,2},? \d{2,4}")
CHECK_NAMES = ("rows", "ids", "clean", "dates")
NOTE_NAMES = ("edges", "empty")


def row_shapes(html: str) -> list[int]:
    """Cell counts of the rows that look like data: at least four cells
    (`sandbox.data_rows`) and at least one `<td>`."""
    return [len(TD.findall(html[a:b])) for a, b in data_rows(html)
            if HAS_TD.search(html[a:b])]


def expected_rows(pages_html: list[str]) -> list[int]:
    """Grid rows per page: rows of the portal's most common shape."""
    shapes = [row_shapes(h) for h in pages_html]
    common = collections.Counter(n for s in shapes for n in s).most_common(1)
    mode = common[0][0] if common else None
    return [sum(1 for n in s if n == mode) for s in shapes]


def check_page(rows: list[Any], expected: int) -> set[str]:
    """Which checks one page's output fails. Sees the output and the page's
    row estimate, nothing else."""
    failed: set[str] = set()
    if len(rows) != expected:
        failed.add("rows")
    ids = [r.get("native_id") if isinstance(r, dict) else None for r in rows]
    if (any(not isinstance(i, str) or not i.strip() for i in ids)
            or len(set(ids)) != len(ids)):
        failed.add("ids")
    for r in rows:
        if not isinstance(r, dict) or any(
                v is not None and (not isinstance(v, str) or MARKUP.search(v))
                for v in r.values()):
            failed.add("clean")
            break
    dates: list[str] = [r["issued_date"] for r in rows if isinstance(r, dict)
             and isinstance(r.get("issued_date"), str) and r["issued_date"]]
    if dates and sum(1 for d in dates if DATE.search(d)) < 0.9 * len(dates):
        failed.add("dates")
    return failed


def edge_values(rows: list[Any]) -> list[str]:
    """Values that start or end with a stray angle bracket."""
    return [v for r in rows if isinstance(r, dict) for v in r.values()
            if isinstance(v, str) and v.strip()
            and (v.strip()[0] in "<>" or v.strip()[-1] in "<>")]


def empty_fields(pages_rows: list[list[Any]], fields: list[str]) -> list[str]:
    """Contract fields that are null or empty on every row of every page,
    among pages that returned rows."""
    rows = [r for page in pages_rows for r in page if isinstance(r, dict)]
    if not rows:
        return []
    return [f for f in fields
            if all(r.get(f) in (None, "") for r in rows)]
