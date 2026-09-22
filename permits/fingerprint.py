# -*- coding: utf-8 -*-
"""Structural fingerprints for rendered HTML.

Section 9, obligation 3: *"template fingerprinting belongs in step 1, not step
4, because a fingerprint not taken at capture cannot be taken later for a page
that has since changed."* This module is that obligation discharged. It was
written for Spike C and lived in `scripts/spike_c_fingerprint.py` for a day,
where it was import-hacked by three sibling scripts and reachable by no part of
the pipeline.

The fingerprint is the one Spike C pre-registered:

  1. normalized DOM skeleton - text, attribute values and ids all stripped
  2. the set of root-to-leaf tag paths
  3. sha1 over the sorted unique path set

Two comparisons, and the gap between them is the finding rather than noise:

  **exact**    equality of the hash. Brittle by construction - one extra menu
               item in a shared template mints a new fingerprint - so it is a
               strict LOWER bound on how much collapse exists.
  **jaccard**  overlap of the path sets. This is what a structure-keyed cache
               would actually do, and threshold sensitivity is the result:
               Measurement B found cohort size running from 1.0 at J >= 0.95 to
               8.0 at J >= 0.70 over the same pages.

What Spike C established, and what this module must not be read as denying:
**it does not collapse ~20,000 sites onto a few hundred templates.** 1.00
fingerprints per jurisdiction at every threshold down to J = 0.60. The
amortization unit is the tenancy, not the vendor and not the DOM
([ADR-0009](../docs/adr/0009-adapters-first-generic-extraction-second.md)).
The fingerprint remains worth taking for what it *can* do - detect that a
source's template changed under us, and group pages inside one tenancy - and
those are capture-time questions, which is why this now runs at capture.

`VERSION` is the part that did not exist before. A fingerprint is only
comparable to another fingerprint computed by the same rules, and `VOID` and
`OPAQUE` below are exactly the kind of tuning that gets adjusted six months
later without anyone noticing that every stored hash just became
incomparable. A stored fingerprint that does not say which rules produced it
is the same failure as a quoted number that does not say when it was measured.
Bump `VERSION` on any change to the skeleton rules.
"""
import hashlib
import re
from collections import defaultdict
from html.parser import HTMLParser

VERSION = "fp1"

VOID = frozenset(("area", "base", "br", "col", "embed", "hr", "img", "input",
                  "link", "meta", "param", "source", "track", "wbr"))
# svg/math carry inline geometry that swamps page structure; script and style
# carry no structure at all.
OPAQUE = frozenset(("script", "style", "noscript", "svg", "math", "canvas"))

MAX_DEPTH = 200
THRESHOLDS = (0.95, 0.90, 0.80, 0.70, 0.60)


class Skeleton(HTMLParser):
    """Root-to-leaf tag paths, discarding text, attributes and ids."""

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.stack = []
        self.paths = []
        self.opaque_depth = 0
        self.had_child = [False]
        self.nodes = 0

    def handle_starttag(self, tag, attrs):
        if self.opaque_depth:
            return
        if tag in OPAQUE:
            self.opaque_depth = 1
            return
        self.nodes += 1
        if self.had_child:
            self.had_child[-1] = True
        if tag in VOID:
            self.paths.append(">".join([*self.stack, tag]))
            return
        self.stack.append(tag)
        self.had_child.append(False)
        if len(self.stack) > MAX_DEPTH:        # pathological nesting guard
            self.close_one(tag)

    def handle_startendtag(self, tag, attrs):
        if self.opaque_depth or tag in OPAQUE:
            return
        self.nodes += 1
        if self.had_child:
            self.had_child[-1] = True
        self.paths.append(">".join([*self.stack, tag]))

    def close_one(self, tag):
        leaf = not self.had_child[-1] if self.had_child else True
        if leaf:
            self.paths.append(">".join(self.stack))
        if self.stack:
            self.stack.pop()
        if self.had_child:
            self.had_child.pop()

    def handle_endtag(self, tag):
        if self.opaque_depth:
            if tag in OPAQUE:
                self.opaque_depth = 0
            return
        if tag in VOID or tag not in self.stack:
            return
        # Tolerate unclosed tags by unwinding to the matching one. Municipal
        # HTML is not well-formed and a parser that gives up on the first
        # stray </div> fingerprints nothing.
        while self.stack:
            top = self.stack[-1]
            self.close_one(top)
            if top == tag:
                break

    def finish(self):
        while self.stack:
            self.close_one(self.stack[-1])
        return self.paths


class Fingerprint(object):
    """A page's structure, and what it is comparable to."""

    __slots__ = ("hash", "n_nodes", "n_paths", "paths", "version")

    def __init__(self, h, paths, n_paths, n_nodes):
        self.hash = h
        self.paths = paths
        self.n_paths = n_paths
        self.n_nodes = n_nodes
        self.version = VERSION

    def __eq__(self, other):
        return (isinstance(other, Fingerprint) and self.version == other.version
                and self.hash == other.hash)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash((self.version, self.hash))

    def __repr__(self):
        return "<Fingerprint %s:%s paths=%d nodes=%d>" % (
            self.version, self.hash, len(self.paths), self.n_nodes)

    def similarity(self, other):
        if self.version != other.version:
            raise ValueError(
                "fingerprint versions %r and %r are not comparable; a "
                "similarity across skeleton rule changes is meaningless"
                % (self.version, other.version))
        return jaccard(self.paths, other.paths)

    @property
    def is_structural(self):
        """Did this page have any DOM at all?

        A JSON body, a PDF or an empty response yields zero paths, and the
        sha1 of the empty string - `da39a3ee5e6b` - which is a real-looking
        hash that every one of them shares. The first back-fill over the raw
        store duly reported a template "shared across" Austin, Charlotte,
        Columbus, Nashville and Seattle: five unrelated open-data APIs that
        have no HTML in common because they have no HTML at all.

        A fingerprint that collides on absence is worse than no fingerprint,
        because it reads as a finding. Callers store `mark()`, which is empty
        for these.
        """
        return self.n_nodes > 0 and bool(self.paths)

    def mark(self):
        """The `version:hash` string to store, or "" if there is no structure."""
        return "%s:%s" % (self.version, self.hash) if self.is_structural else ""

    def as_dict(self):
        return {"fp": self.mark(),
                "fp_paths": self.n_paths, "fp_nodes": self.n_nodes}


def fingerprint(html):
    """Fingerprint a page. Never raises on malformed markup.

    Returns a `Fingerprint`. The legacy 4-tuple `(hash, paths, n_paths,
    n_nodes)` is still available by unpacking `raw()`, which is what the Spike
    C scripts consume; their published numbers must keep reproducing exactly.
    """
    p = Skeleton()
    try:
        p.feed(html or "")
    except Exception:                                   # noqa: BLE001
        # A parser blowup is a property of the page, not a reason to lose it.
        # The paths collected before the failure are still the page's structure
        # as far as it was readable.
        pass
    paths = p.finish()
    uniq = sorted(set(paths))
    h = hashlib.sha1("\n".join(uniq).encode("utf-8")).hexdigest()[:12]
    return Fingerprint(h, frozenset(uniq), len(paths), p.nodes)


def raw(html):
    """The pre-lift tuple shape: (hash, frozenset(paths), n_paths, n_nodes)."""
    f = fingerprint(html)
    return f.hash, f.paths, f.n_paths, f.n_nodes


def jaccard(a, b):
    if not a and not b:
        return 1.0
    return len(a & b) / float(len(a | b))


def cluster(keys, sets, t):
    """Single-linkage clustering at Jaccard >= t.

    Single-linkage is deliberate and is a stated weakness: it chains, so one
    intermediate page can merge two groups that do not resemble each other.
    Spike C used it because it is the generous choice, and a generous method
    that still finds no collapse is a stronger negative result than a strict
    one that finds none.
    """
    keys = list(keys)
    parent = {k: k for k in keys}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if jaccard(sets[a], sets[b]) >= t:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[ra] = rb
    groups = defaultdict(list)
    for k in keys:
        groups[find(k)].append(k)
    return list(groups.values())


_FP = re.compile(r"^([a-z0-9]+):([0-9a-f]{6,40})$")


def parse(s):
    """Read back a stored `version:hash` string. Returns (version, hash)."""
    m = _FP.match((s or "").strip())
    if not m:
        raise ValueError("not a fingerprint: %r" % (s,))
    return m.group(1), m.group(2)


def comparable(a, b):
    """Two stored fingerprint strings computed under the same rules?"""
    try:
        return parse(a)[0] == parse(b)[0]
    except ValueError:
        return False
