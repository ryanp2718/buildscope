# -*- coding: utf-8 -*-
"""Import specific Spike A pages into the Measurement manifest. No HTTP.

Two controls need pages that already exist on disk, and re-fetching them would
spend budget to obtain bytes this project already has:

  C1  needs two T-INDEX pages from the SAME portal from DIFFERENT queries.
      Measurement A fetched one index per portal; Spike A saved two.
  C4  needs a non-Accela page of a matched type. Spike A's St Johns County
      capture is the only non-Accela search page in the corpus.

The import is not a free pass. Each page gets a verdict computed now, and the
manifest records that the verdict was assigned **at import from stored bytes**
rather than at capture - because that is the weaker provenance, and the whole
point of the manifest is that a reader can tell the difference without asking.
"""
import io
import os
import sys
import time
import hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from permits import capture as mf  # noqa: E402

ROOT = mf.ROOT
SRC = os.path.join(ROOT, "data", "spike_a", "html")

# (source file, jurisdiction, vendor, page_type, why it is being imported)
IMPORTS = [
    ("q_clarkco_accela_empty_criteria.html", "clarkco", "accela-aca",
     "T-INDEX", "C1 pair member: empty criteria"),
    ("q_clarkco_accela_date_range_only.html", "clarkco", "accela-aca",
     "T-INDEX", "C1 pair member: date range"),
    ("q_oregon_accela_empty_criteria.html", "oregon", "accela-aca",
     "T-INDEX", "C1 pair member: empty criteria"),
    ("q_oregon_accela_date_range_only.html", "oregon", "accela-aca",
     "T-INDEX", "C1 pair member: date range"),
    ("q_YAKIMACO_empty.html", "YAKIMACO", "accela-aca",
     "T-INDEX", "C1 pair member: empty criteria"),
    ("q_YAKIMACO_wapato.html", "YAKIMACO", "accela-aca",
     "T-INDEX", "C1 pair member: city=WAPATO"),
    ("q_stjohns_wats.html", "stjohns", "wats-dotnet",
     "T-SEARCH", "C4 cross-vendor control: non-Accela search page"),
]


def main():
    mf.ensure_dirs()
    n = 0
    print("IMPORT - Spike A pages into the Measurement manifest (no HTTP)\n")
    for src, juris, vendor, ptype, why in IMPORTS:
        p = os.path.join(SRC, src)
        if not os.path.exists(p):
            print("  MISSING %s" % src)
            continue
        raw = io.open(p, "rb").read()
        html = raw.decode("utf-8", "replace")
        verdict, reason = mf.verify(ptype, html, 200)
        dst = "imported_" + src
        io.open(os.path.join(mf.PAGES, dst), "w", encoding="utf-8",
                newline="").write(html)
        mf._write(dict(
            fetched_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            url="file://data/spike_a/html/" + src,
            final_url="file://data/spike_a/html/" + src,
            http_status=200, content_type="text/html", bytes=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(), jurisdiction=juris,
            vendor=vendor, page_type=ptype, verdict=verdict,
            verdict_reason=("IMPORTED from Spike A; verdict assigned at import "
                            "from stored bytes, not at capture. %s. %s"
                            % (why, reason)),
            request_method="IMPORT", robots_ok=True, file=dst))
        print("  %-9s %-44s %-9s %s" % (verdict.upper(), src, ptype, why))
        n += 1
    print("\nimported %d pages, 0 HTTP requests" % n)


if __name__ == "__main__":
    main()
