# -*- coding: utf-8 -*-
"""Reduce a portal page to the part an extractor needs.

docs/design/history.md section 6, lever 4: *"Do not send raw HTML to the model. Strip
scripts, styles, comments, and attribute noise before the page enters a
prompt. On municipal portal HTML this is routinely an order-of-magnitude token
reduction against identical extraction quality."* The reduction is real - a
Clark County page goes from 695 KB to 78 KB - and it is why any inference over
these pages is affordable at all.

**"Against identical extraction quality" is the part that was not measured,
and on one platform it is false.** The keep-list this module inherited from
`scripts/measure_tokens.py` was `id, name, href, value, type`, chosen because
"a field's id/name is how you address it and href is how you reach the next
page". That reasoning is about *navigating* an ASP.NET form. It is not about
*reading a grid*, and an Accela ACA results grid marks its data rows with
`class="ACA_TabRow_Odd"` and nothing else - no id, no name. Stripping `class`
deleted all 42 row markers from the page and left the rows themselves in
place, so the page still looked complete and the one signal that separates a
permit row from a layout row was gone.

That is the same failure family as the rest of this project's history: the
instrument was wrong, not the world, and the damage was silent. `class` is
therefore kept by default now. It costs about 4% of the stripped page.

`measure_tokens.KEEP_ATTR` is preserved as `LEGACY_KEEP` because the published
token figures in
[the measurement report](../docs/evidence/2026-09-20-measurement-ab-results.md)
were produced with it, and a figure whose inputs changed underneath it is the
re-quoting failure the evidence directory exists to prevent. Anything
re-deriving those numbers passes `LEGACY_KEEP` explicitly.
"""
import re

SCRIPT = re.compile(r"<script\b.*?</script\s*>", re.I | re.S)
STYLE = re.compile(r"<style\b.*?</style\s*>", re.I | re.S)
COMMENT = re.compile(r"<!--.*?-->", re.S)
ATTR = re.compile(r"""\s+([-\w:]+)\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""")
TAG = re.compile(r"<[^>]+>")
WS = re.compile(r"\s+")

# What `scripts/measure_tokens.py` used, and what the published token figures
# were measured with. Do not change; pass it to reproduce them.
LEGACY_KEEP = ("id", "name", "href", "value", "type")

# The default. `class` is the addition and the docstring above is the reason.
KEEP_ATTR = ("id", "name", "href", "value", "type", "class")

# A VIEWSTATE payload is a single base64 attribute value that can run to tens
# of KB. Pure overhead: required to POST the next request, carries no permit
# data whatsoever.
VIEWSTATE = re.compile(
    r"""id="(__VIEWSTATE|__EVENTVALIDATION|__VIEWSTATEGENERATOR)"[^>]*"""
    r"""value="([^"]*)\"""", re.I)

MAX_ATTR = 120


def strip_attrs(tag, keep):
    """Drop every attribute on one tag except the keep-list."""
    open_ = re.match(r"<\s*([-\w:]+)", tag)
    if not open_:
        return tag
    kept = []
    for a in ATTR.finditer(tag):
        if a.group(1).lower() in keep:
            v = a.group(2).strip("\"'")
            # A kept value can still be a base64 blob. Truncate rather than
            # drop: the extractor needs to know the field exists, not what is
            # in it.
            if len(v) > MAX_ATTR:
                v = v[:MAX_ATTR] + "...[%d chars elided]" % (len(v) - MAX_ATTR)
            kept.append('%s="%s"' % (a.group(1), v))
    return "<%s%s%s>" % (open_.group(1),
                         (" " + " ".join(kept)) if kept else "",
                         "/" if tag.rstrip().endswith("/>") else "")


def levels(html, keep=KEEP_ATTR):
    """Three strip levels, cheapest transformation first."""
    a = COMMENT.sub("", STYLE.sub("", SCRIPT.sub("", html)))
    b = WS.sub(" ", TAG.sub(lambda m: strip_attrs(m.group(0), keep), a))
    # Text-only is the floor: it discards the DOM structure an extractor needs
    # to tell a label from a value, so it is a bound, not a proposal.
    c = WS.sub(" ", re.sub(r"<[^>]+>", " ", b))
    return {"raw": html, "no-js/css": a, "attrs-stripped": b, "text-only": c}


def viewstate_bytes(html):
    return sum(len(m.group(2)) for m in VIEWSTATE.finditer(html))
