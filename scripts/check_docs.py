# -*- coding: utf-8 -*-
"""Check docs/ for the drift a hand-maintained index always eventually accumulates.

Verifies, and exits non-zero on any failure:
  1. every ADR file appears in the adr/README.md index, and vice versa
  2. ADR statuses come from the permitted set
  3. 'Superseded by ADR-NNNN' names an ADR that exists
  4. every relative markdown link inside docs/ resolves on disk
  5. every evidence report carries the required front matter and a non-empty
     'What this does not establish' section

Usage: python scripts/check_docs.py
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
ADR = os.path.join(DOCS, "adr")
EVID = os.path.join(DOCS, "evidence")

STATUSES = ("Proposed", "Accepted", "Deprecated")
FRONT = ("Date:", "Produced:", "Inputs:", "Outputs:", "Status:")

problems = []


def fail(where, msg):
    problems.append("%s: %s" % (where, msg))


def read(path):
    return io.open(path, encoding="utf-8").read()


def adr_files():
    if not os.path.isdir(ADR):
        return []
    return sorted(f for f in os.listdir(ADR)
                  if re.match(r"^\d{4}-.+\.md$", f) and not f.startswith("0000-"))


# ---------------------------------------------------------------- 1, 2, 3
files = adr_files()
index_src = read(os.path.join(ADR, "README.md")) if os.path.isdir(ADR) else ""
indexed = set(re.findall(r"\]\((\d{4}-[^)]+\.md)\)", index_src))
numbers = set()

for f in files:
    if f not in indexed:
        fail("adr/README.md", "%s is on disk but missing from the index" % f)
    n = f[:4]
    if n in numbers:
        fail("adr/", "duplicate ADR number %s" % n)
    numbers.add(n)

    body = read(os.path.join(ADR, f))
    m = re.search(r"^Status:\s*(.+)$", body, re.M)
    if not m:
        fail(f, "no 'Status:' line")
    else:
        st = m.group(1).strip()
        sup = re.match(r"^Superseded by ADR-(\d{4})$", st)
        if sup:
            if not any(g.startswith(sup.group(1)) for g in files):
                fail(f, "superseded by ADR-%s, which does not exist" % sup.group(1))
        elif st not in STATUSES:
            fail(f, "status %r is not one of %s or 'Superseded by ADR-NNNN'"
                 % (st, ", ".join(STATUSES)))
    if not re.search(r"^Date:\s*\d{4}-\d{2}-\d{2}\s*$", body, re.M):
        fail(f, "no 'Date: YYYY-MM-DD' line")

for f in sorted(indexed):
    if f not in files:
        fail("adr/README.md", "index lists %s, which is not on disk" % f)

# ---------------------------------------------------------------- 4
LINK = re.compile(r"\[[^\]]*\]\(([^)#]+)(?:#[^)]*)?\)")
for dirpath, _dirnames, filenames in os.walk(DOCS):
    for name in filenames:
        if not name.endswith(".md"):
            continue
        path = os.path.join(dirpath, name)
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        for target in LINK.findall(read(path)):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("//"):
                continue
            if not os.path.exists(os.path.normpath(os.path.join(dirpath, target))):
                fail(rel, "broken link -> %s" % target)

# ---------------------------------------------------------------- 5
if os.path.isdir(EVID):
    for name in sorted(os.listdir(EVID)):
        if not name.endswith(".md") or name == "README.md":
            continue
        if not re.match(r"^\d{4}-\d{2}-\d{2}-.+\.md$", name):
            fail("evidence/" + name, "filename is not YYYY-MM-DD-slug.md")
        body = read(os.path.join(EVID, name))
        for key in FRONT:
            if not re.search(r"^%s" % re.escape(key), body, re.M):
                fail("evidence/" + name, "front matter missing %r" % key)
        m = re.search(r"^#+\s*What this does not establish\s*$(.*?)(?=^#|\Z)",
                      body, re.M | re.S)
        if not m:
            fail("evidence/" + name, "no 'What this does not establish' section")
        elif not m.group(1).strip():
            fail("evidence/" + name, "'What this does not establish' is empty")

# ----------------------------------------------------------------
if problems:
    print("docs check FAILED (%d)" % len(problems))
    for p in problems:
        print("  - " + p)
    sys.exit(1)
print("docs check ok: %d ADRs, %d evidence reports"
      % (len(files), len([n for n in (os.listdir(EVID) if os.path.isdir(EVID) else [])
                          if n.endswith(".md") and n != "README.md"])))
