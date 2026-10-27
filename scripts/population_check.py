# -*- coding: utf-8 -*-
"""Stage 1 of the portal population run: the checker models read every
saved page's records straight from the page, without writing code, and
their reading is compared with the reference field by field
(docs/evidence/2026-10-04-portal-population-preregistration.md, "Without
the owner's review").

    python scripts/population_check.py
    python scripts/population_check.py --run --registered <OSF link>
    python scripts/population_check.py --report

**Checkers.** Claude Sonnet 5.5 reads every page of all 16 test portals.
OpenAI's GPT-6 Sol reads the portals whose reference is the portal's own
export (11 Accela, 2 AMANDA), the same way. Neither sees the reference or
the export. Each call is the contract (`harness.CONTRACT`) and the whole
page, as v2's direct-extraction arm asked, with the model's default
reasoning. The page is the stripped page with every attribute dropped and
its option lists removed (`bare`): the tags stay, so a cell is still a cell
and an empty one is still there, at under a quarter of the tokens. Every
reference value on the 64 pages is still in it verbatim. Plain text was
cheaper still but loses empty cells, and with them which column a value
sits in.

**What it gives.** On the export portals, each checker's error rate
against the export, which no model wrote: a parser and a checker can only
agree on a wrong value where the checker is wrong. On the parser portals
(Boise, Phoenix, Philadelphia), the parser-checker disagreements, grouped
by portal and field. Both checkers' readings are kept as answer keys for
the bias estimate.

Every call has a ledger row, and each response is cached and saved under
`data/population/checker/<model>/`, so everything here can be recomputed
without paying again. Without `--run` the exact requests are priced and
nothing is sent; `--run` needs the pre-registration's OSF link.
"""
import argparse
import collections
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from permits import fileio, infer, sandbox                    # noqa: E402
from permits import harness as H                              # noqa: E402
from permits.population import POP, load_portals              # noqa: E402

OUT = os.path.join(POP, "checker")
SONNET = "claude-sonnet-5-5"
SOL = "openai/gpt-6-sol"
CHECKERS = (SONNET, SOL)
LIMIT = 12.0
SYSTEM = H.CONTRACT + """
YOUR TASK: return the records from the page below.

Emit one fenced ```json block containing a JSON array of objects, one object
per record, each with exactly the field names listed above. No commentary
before or after the block.
"""
# Output tokens a record costs as JSON, from v2's direct-extraction arm
# (`conformance.TOKENS_PER_RECORD`), for the dry run's estimate only.
TOKENS_PER_RECORD = 110
# Reasoning tokens per page, a guess for the estimate only: the price is
# whatever the ledger records.
REASONING_PER_PAGE = 3000
EXAMPLES = 3
TAG = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)[^>]*>")
LISTS = re.compile(r"(?is)<(select|option|svg|noscript|template)\b.*?</\1>")


def reads(model, portal):
    return model == SONNET or portal.source.startswith("export")


def bare(html):
    """The stripped page with every tag's attributes dropped and its option
    lists removed."""
    return TAG.sub(lambda m: "<%s%s>" % (m.group(1), m.group(2).lower()),
                   LISTS.sub(" ", html))


def user_text(path):
    return ("Portal page (one page of the result list, with scripts, styles, "
            "attributes and option lists removed):\n\n" + bare(H.read(path)))


def out_path(model, page):
    return os.path.join(OUT, infer.short_model(model),
                        os.path.splitext(os.path.basename(page))[0] + ".json")


def read_page(client, args, model, portal, path):
    """One checker call on one page, saved; returns the saved record."""
    done = out_path(model, path)
    if os.path.exists(done):
        return fileio.read_json(done)
    c = client.message(model, SYSTEM, user_text(path),
                       infer.output_cap(model), call_class="checker",
                       thinking=True, tag="checker/%s/%s" % (
                           infer.short_model(model), os.path.basename(path)))
    rows, error = None, None
    if c.truncated:
        error = "truncated"
    else:
        try:
            rows = json.loads(sandbox.extract_block(c.text, sandbox.JSONBLOCK))
            if not isinstance(rows, list):
                rows, error = None, "not a list"
        except (ValueError, TypeError) as e:
            error = "unparsed: %s" % str(e)[:200]
    rec = {"model": model, "order": portal.order,
           "page": os.path.basename(path), "rows": rows, "error": error,
           "usd": c.usd, "usage": c.usage.to_dict(), "host": c.host,
           "text": c.text, "registered": args.registered}
    os.makedirs(os.path.dirname(done), exist_ok=True)
    fileio.atomic_write(done, json.dumps(rec, indent=1))
    return rec


# ---------------------------------------------------------- comparison
def compare(portal, page, rows):
    """A checker's reading of one page against its reference."""
    ref = {H.norm(r["native_id"]): r for r in portal.refs[page]}
    got = {}
    for r in rows or []:
        if isinstance(r, dict) and H.norm(r.get("native_id")):
            got.setdefault(H.norm(r.get("native_id")), r)
    fields = [f for f in portal.target.roles if f != "native_id"]
    per = {f: [0, 0] for f in fields}
    diffs = []
    for k in sorted(set(ref) & set(got)):
        for f in fields:
            a, b = H.norm(ref[k].get(f)), H.norm(got[k].get(f))
            if a is None and b is None:
                continue
            per[f][1] += 1
            if a == b:
                per[f][0] += 1
            else:
                diffs.append({"order": portal.order, "page": page, "id": k,
                              "field": f, "reference": a, "checker": b})
    return {"ref": len(ref), "read": len(got), "matched": len(set(ref) & set(got)),
            "missed": sorted(set(ref) - set(got)),
            "extra": sorted(set(got) - set(ref)), "fields": per,
            "diffs": diffs}


def summarize(model, portals):
    """Per portal: records matched and each field's agreement."""
    out = {}
    for p in portals:
        if not reads(model, p):
            continue
        res = []
        for q in p.corpus:
            path = out_path(model, q)
            if not os.path.exists(path):
                continue
            rec = fileio.read_json(path)
            res.append(dict(compare(p, os.path.basename(q), rec["rows"]),
                            error=rec["error"], usd=rec["usd"]))
        if res:
            out[p.order] = res
    return out


def report(portals):
    by = {p.order: p for p in portals}
    summary = {}
    for model in CHECKERS:
        s = summarize(model, portals)
        if not s:
            continue
        summary[model] = s
        print("\n%s" % model)
        print("  %-6s %-22s %-7s %5s %5s %5s %5s  %-44s %s"
              % ("portal", "place", "key", "ref", "read", "miss", "extra",
                 "field agreement", "errors"))
        tot = collections.Counter()
        groups = collections.defaultdict(list)
        for order, res in sorted(s.items()):
            p = by[order]
            agree = collections.Counter()
            seen = collections.Counter()
            for r in res:
                for f, (a, n) in r["fields"].items():
                    agree[f] += a
                    seen[f] += n
                for d in r["diffs"]:
                    groups[(order, d["field"])].append(d)
            kind = "export" if p.source.startswith("export") else "parser"
            tot[kind + "_agree"] += sum(agree.values())
            tot[kind + "_seen"] += sum(seen.values())
            tot[kind + "_missed"] += sum(len(r["missed"]) for r in res)
            tot[kind + "_ref"] += sum(r["ref"] for r in res)
            print("  %-6s %-22s %-7s %5d %5d %5d %5d  %-44s %s"
                  % (p.key, p.place[:22], kind, sum(r["ref"] for r in res),
                     sum(r["read"] for r in res),
                     sum(len(r["missed"]) for r in res),
                     sum(len(r["extra"]) for r in res),
                     " ".join("%s %d/%d" % (f[:6], agree[f], seen[f])
                              for f in sorted(seen)),
                     ",".join(sorted({r["error"] for r in res if r["error"]}))
                     or "-"))
        for kind in ("export", "parser"):
            if tot[kind + "_seen"]:
                wrong = tot[kind + "_seen"] - tot[kind + "_agree"]
                print("  %s portals: %d of %d values disagree (%.2f%%), %d of "
                      "%d records not read"
                      % (kind, wrong, tot[kind + "_seen"],
                         100.0 * wrong / tot[kind + "_seen"],
                         tot[kind + "_missed"], tot[kind + "_ref"]))
        print("  disagreements by portal and field (up to %d examples):"
              % EXAMPLES)
        for (order, f), ds in sorted(groups.items(), key=lambda x: -len(x[1])):
            print("    %-6s %-12s %3d  %s" % (by[order].key, f, len(ds), "; ".join(
                "%s: ref %r, checker %r" % (d["id"], d["reference"], d["checker"])
                for d in ds[:EXAMPLES])))
    fileio.atomic_write(os.path.join(OUT, "summary.json"),
                        json.dumps(summary, indent=1))
    print("\nspent: %s" % ", ".join(
        "%s $%.4f" % (infer.short_model(m), sum(r["usd"] for res in s.values()
                                                 for r in res))
        for m, s in summary.items()))


# ---------------------------------------------------------------- main
def plan(portals):
    total = collections.Counter()
    for model in CHECKERS:
        pages = recs = tin = 0
        for p in portals:
            if not reads(model, p):
                continue
            for q, n in zip(p.corpus, p.counts(), strict=True):
                if os.path.exists(out_path(model, q)):
                    continue
                pages += 1
                recs += n
                tin += infer.tokens(SYSTEM) + infer.tokens(user_text(q))
        est = infer.estimate(model, tin, recs * TOKENS_PER_RECORD
                             + pages * REASONING_PER_PAGE)
        total[infer.spec(model).provider] += est
        print("  %-20s %3d pages to read, %5d records, %7d input tokens, "
              "about $%.2f at list" % (model, pages, recs, tin, est))
    print("  about $%.2f at list against the $%.2f limit"
          % (sum(total.values()), LIMIT))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--registered", default=None)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--models", default=",".join(CHECKERS))
    ap.add_argument("--max-spend", type=float, default=LIMIT)
    args = ap.parse_args(argv)
    if args.run and not args.registered:
        ap.error("--run spends on the test portals: give --registered, the "
                 "pre-registration's OSF link")
    models = [m.strip() for m in args.models.split(",")]
    if set(models) - set(CHECKERS):
        ap.error("--models takes %s" % ", ".join(CHECKERS))
    portals = load_portals()
    if args.report:
        report(portals)
        return 0
    plan(portals)
    if not args.run:
        print("\ndry run: nothing sent. Add --run to spend.")
        return 0
    spent = sum(fileio.read_json(os.path.join(dp, f))["usd"]
                for dp, _, fs in os.walk(OUT) for f in fs
                if f.endswith(".json") and f != "summary.json")
    client = infer.Client(ROOT, max(0.0, args.max_spend - spent))
    for m in models:
        if not client.key_for(m):
            raise SystemExit("no key for %s. Nothing has been sent." % m)
    for m in models:
        for p in portals:
            if not reads(m, p):
                continue
            for q in p.corpus:
                try:
                    rec = read_page(client, args, m, p, q)
                except infer.Refused as e:
                    print("  STOPPED at the limit: %s" % e)
                    report(portals)
                    return 1
                print("  %-12s %-6s %-18s %3s rows  $%.4f  %s"
                      % (infer.short_model(m), p.key, rec["page"],
                         len(rec["rows"]) if rec["rows"] is not None else "-",
                         rec["usd"], rec["error"] or ""))
    report(portals)
    print("spent $%.4f this session" % client.budget.spent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
