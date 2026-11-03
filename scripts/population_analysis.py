"""Score the portal population run as its pre-registration says: P1-P3,
the check's delivery and wrong-but-accepted rates, cost per trusted
extractor per product and in the two population views, and the agent
against the scripted loop.

Reads the runner's records (`data/population/eval/episodes.json`, run id
`eval-pop-1` by default), the sample (`sample.csv`, `usability.csv`,
`open_data.csv`, `draw.csv`) and each test portal's reference header. Makes
no model calls. Writes `data/population/eval/analysis.json` and prints the
tables.

**An attempt** is one try at an extractor for one portal. Its spend and
its chance of a trusted extractor (one the check accepts that is perfect on
every page) are:
- a one-shot cell: best-of-k with the check over its stored draws, k all
  of them (`arms.best_of_k`), as the runner's report has it;
- a loop or agent cell: an episode's mean spend and its trusted rate (the
  submitted module); a cell with no room (stage-2 pass@1 of 1) takes its
  one-shot result, as the pre-registration says.
The loop pooled over the cheap models is each portal's mean over the five.
A product's result is the mean over its tested portals, and a view's cost
per trusted extractor is a ratio of totals: the product weights times
spend, over the product weights times the trusted chance.

**Weights.** A portal row in the located range (offices 1-150 and the
take-all stratum, size rank 50 or better) has design weight 1 if take-all,
950/141 if drawn. Its usable chance is 1 or 0 where onboarding settled it,
and otherwise its product's onboarded rate from `usability.csv` (an
analysis choice: capped portals were never onboarded, and Accela's rate is
12 of 15). The layout view counts every such row; the pipeline view only
rows the crawler fetches whose office has no qualifying open data. Only
products with a tested portal are estimated (no imputation).

**Intervals** are the pre-registration's stratified bootstrap: drawn
offices resampled (take-all fixed), which moves the product weights; tested
portals resampled within each product (a product with one tested portal
kept as it is); draws and episodes resampled within each cell. 95%
percentile intervals.

**Matched spend (P3)** reads best-of-k at the loop's mean list-priced spend
per episode, interpolating linearly between whole k (k = 0 spends nothing),
and holding at all stored draws when the loop spends more.
"""
import argparse
import csv
import itertools
import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from permits import arms, fileio                              # noqa: E402
from permits.cells import Outcome                             # noqa: E402
from permits.population import EVAL, POP, REFS                # noqa: E402

CHEAP = ("openai/gpt-oss-120b", "google/gemini-3.5-flash-lite",
         "deepseek/deepseek-v4-flash", "openai/gpt-6-luna",
         "xiaomi/mimo-v2.6-flash")
STRONG = ("claude-opus-5-5", "google/gemini-3.8-flash")
SCORED = (Outcome.PERFECT, Outcome.IMPERFECT, Outcome.RAISED,
          Outcome.EXEC_ERROR, Outcome.REFUSED, Outcome.NO_CODE)
CHECK_MISSES = (104, 319)
TAKE_ALL_RANK = 50
DRAWN_W = 950.0 / 141
LOCATED = 150
P2_LIMIT = 0.05
PRICES = ("list_usd", "usd")


# ------------------------------------------------------------ loading
def load_records(run_id):
    eps = fileio.read_json(os.path.join(EVAL, "episodes.json"))["episodes"]
    return [r for r in eps.values()
            if r["run_id"] == run_id and r["outcome"] in SCORED]


def load_portals():
    """Each test portal's header: {order: {product, place, access}}."""
    out = {}
    for f in sorted(os.listdir(REFS)):
        if f.startswith("ref_") and f.endswith(".json"):
            d = fileio.read_json(os.path.join(REFS, f))
            out[int(d["order"])] = {"product": d["product"],
                                    "place": d["place"],
                                    "access": d.get("access", "crawler")}
    return out


def _csv(name):
    with open(os.path.join(POP, name), encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def usable_rates():
    """Each product's onboarded usable rate."""
    n, yes = {}, {}
    for r in _csv("usability.csv"):
        p = r["product"]
        n[p] = n.get(p, 0) + 1
        yes[p] = yes.get(p, 0) + (r["usable"] == "yes")
    return {p: yes[p] / float(n[p]) for p in n}


def population_rows():
    """The located range's portal rows, with what the weights need."""
    rank = {int(r["order"]): int(r["size_rank"]) for r in _csv("draw.csv")}
    open_data = {int(r["order"]) for r in _csv("open_data.csv")
                 if not r["note"].strip()}
    rates = usable_rates()
    settled = {int(r["order"]): r["usable"] == "yes"
               for r in _csv("usability.csv")}
    rows = []
    for r in _csv("sample.csv"):
        o = int(r["order"])
        take_all = rank[o] <= TAKE_ALL_RANK
        if o > LOCATED and not take_all:
            continue
        if o in settled:
            usable = 1.0 if settled[o] else 0.0
        elif r["role"] in ("tested", "skipped"):
            usable = 1.0
        elif r["role"] == "not usable":
            usable = 0.0
        else:
            usable = rates.get(r["product"])
        rows.append({"order": o, "product": r["product"], "role": r["role"],
                     "take_all": take_all,
                     "fetchable": r["access"] == "crawler",
                     "open_data": o in open_data, "usable": usable})
    return rows


def weights(rows, counts=None):
    """Product weights in the layout and pipeline views. `counts` gives a
    drawn office's multiplicity in a bootstrap replicate."""
    lay, pipe = {}, {}
    for r in rows:
        if r["usable"] is None:
            continue
        c = (1 if r["take_all"] or counts is None
             else counts.get(r["order"], 0))
        w = (1.0 if r["take_all"] else DRAWN_W) * c * r["usable"]
        lay[r["product"]] = lay.get(r["product"], 0.0) + w
        if r["fetchable"] and not r["open_data"]:
            pipe[r["product"]] = pipe.get(r["product"], 0.0) + w
    return {"layout": lay, "pipeline": pipe}


# -------------------------------------------------------------- cells
def cells(recs):
    """{(order, model, arm): [record]}, one-shot draws and episodes."""
    out = {}
    for r in recs:
        out.setdefault((r["order"], r["model"], r["arm"]), []).append(r)
    for v in out.values():
        v.sort(key=lambda r: r["episode"])
    return out


def stored(rs):
    return [arms.Stored(r["episode"], r["list_usd"], r["usd"],
                        r["accepted"], r["outcome"] == Outcome.PERFECT,
                        bool(r.get("field_perfect"))) for r in rs]


def oneshot_attempt(rs, price):
    b = arms.best_of_k(stored(rs), len(rs))
    return b[price], b["success"]


def episode_attempt(rs, price):
    n = float(len(rs))
    return (sum(r[price] for r in rs) / n,
            sum(1 for r in rs if r["trusted"]) / n)


def room(rs):
    return sum(1 for r in rs if r["outcome"] == Outcome.PERFECT) < len(rs)


def attempt(cs, order, model, arm, price):
    """(spend, trusted chance) of one approach on one portal, or None."""
    one = cs.get((order, model, "oneshot"))
    if arm == "oneshot":
        return oneshot_attempt(one, price) if one else None
    eps = cs.get((order, model, arm))
    if eps:
        return episode_attempt(eps, price)
    if one and not room(one):
        return oneshot_attempt(one, price)
    return None


def pooled(cs, order, models, arm, price):
    xs = [attempt(cs, order, m, arm, price) for m in models]
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    return (sum(x[0] for x in xs) / len(xs), sum(x[1] for x in xs) / len(xs))


def bok_at(draws, spend):
    """Best-of-k's trusted chance at a list-priced spend, interpolated."""
    pts = [(0.0, 0.0)] + [(b["list_usd"], b["success"]) for b in
                          (arms.best_of_k(draws, k)
                           for k in range(1, len(draws) + 1))]
    for (s0, p0), (s1, p1) in itertools.pairwise(pts):
        if spend <= s1:
            return p0 if s1 == s0 else p0 + (p1 - p0) * (spend - s0) / (s1 - s0)
    return pts[-1][1]


# ---------------------------------------------------------- estimates
APPROACHES = ([("oneshot", (m,)) for m in CHEAP + STRONG]
              + [("scripted", (m,)) for m in CHEAP]
              + [("agent", (m,)) for m in CHEAP]
              + [("scripted", CHEAP), ("agent", CHEAP)])


def name(arm, models):
    if len(models) > 1:
        return "%s, cheap pooled" % arm
    return "%s %s" % (arm, models[0].split("/")[-1])


def product_results(cs, portals, plist, arm, models, price):
    """{product: (spend, trusted chance)}: the mean over its portals."""
    by = {}
    for o in plist:
        x = pooled(cs, o, models, arm, price)
        if x is not None:
            by.setdefault(portals[o]["product"], []).append(x)
    return {p: (sum(x[0] for x in xs) / len(xs), sum(x[1] for x in xs) / len(xs))
            for p, xs in by.items()}


def view_cost(prod, w):
    num = sum(w.get(p, 0.0) * s for p, (s, _) in prod.items())
    den = sum(w.get(p, 0.0) * t for p, (_, t) in prod.items())
    return num / den if den else None


def p2(cs, plist):
    """Accepted extractors that fail the reference: (wrong, accepted)."""
    wrong = acc = 0
    for (o, _m, arm), rs in cs.items():
        if o not in plist:
            continue
        for r in rs:
            if r["accepted"] and (arm == "oneshot" or r.get("submitted")):
                acc += 1
                wrong += r["outcome"] != Outcome.PERFECT
    return wrong, acc


def p3(cs, plist):
    """Mean over portals of the loop's trusted rate minus best-of-k's at
    the loop's spend, each portal the mean over its cells with room."""
    diffs = []
    for o in plist:
        ds = []
        for m in CHEAP:
            eps, one = cs.get((o, m, "scripted")), cs.get((o, m, "oneshot"))
            if not eps or not one:
                continue
            spend, rate = episode_attempt(eps, "list_usd")
            ds.append(rate - bok_at(stored(one), spend))
        if ds:
            diffs.append(sum(ds) / len(ds))
    return sum(diffs) / len(diffs) if diffs else None


def agent_vs(cs, plist):
    """Agent minus loop, and agent minus best-of-5 at B5, trusted rates,
    mean over portals of each portal's mean over its cells."""
    out = {}
    for label, other in (("loop", "scripted"), ("best-of-5", None)):
        diffs = []
        for o in plist:
            ds = []
            for m in CHEAP:
                ag = cs.get((o, m, "agent"))
                if not ag:
                    continue
                a = episode_attempt(ag, "list_usd")[1]
                if other:
                    ot = cs.get((o, m, other))
                    if not ot:
                        continue
                    b = episode_attempt(ot, "list_usd")[1]
                else:
                    b = arms.best_of_k(stored(cs[(o, m, "oneshot")]),
                                       arms.PRIMARY_K)["success"]
                ds.append(a - b)
            if ds:
                diffs.append(sum(ds) / len(ds))
        out[label] = sum(diffs) / len(diffs) if diffs else None
    return out


def delivery(cs, plist, arm, models):
    """Per attempt: delivered (accepted, and submitted for an episode),
    wrong among delivered, trusted, attempts."""
    n = dl = wr = tr = 0
    for (o, m, a), rs in cs.items():
        if o not in plist or a != arm or m not in models:
            continue
        for r in rs:
            n += 1
            d = r["accepted"] and (arm == "oneshot" or r.get("submitted"))
            dl += d
            wr += d and r["outcome"] != Outcome.PERFECT
            tr += r["trusted"]
    return {"attempts": n, "delivered": dl / float(n) if n else None,
            "wrong_of_delivered": wr / float(dl) if dl else None,
            "trusted": tr / float(n) if n else None}


def estimate(cs, portals, rows, counts=None):
    """Every pre-registered figure from one set of cells."""
    plist = sorted(portals)
    pipe_list = [o for o in plist if portals[o]["access"] != "by hand"]
    w = weights(rows, counts)
    wrong, acc = p2(cs, plist)
    out = {"p2": wrong / float(acc) if acc else None,
           "p2_counts": [wrong, acc], "p3": p3(cs, plist),
           "agent": agent_vs(cs, plist), "costs": {}}
    for price in PRICES:
        for arm, models in APPROACHES:
            k = "%s|%s" % (name(arm, models), price)
            prod_all = product_results(cs, portals, plist, arm, models, price)
            prod_pipe = product_results(cs, portals, pipe_list, arm, models,
                                        price)
            out["costs"][k] = {
                "per_product": {p: (s / t if t else None)
                                for p, (s, t) in prod_all.items()},
                "layout": view_cost(prod_all, w["layout"]),
                "pipeline": view_cost(prod_pipe, w["pipeline"])}
    for price in PRICES:
        loop = out["costs"]["scripted, cheap pooled|%s" % price]["pipeline"]
        for m in STRONG:
            s = out["costs"]["oneshot %s|%s" % (m.split("/")[-1], price)][
                "pipeline"]
            out["p1|%s|%s" % (m, price)] = (loop / s if loop and s else None)
    return out


# ---------------------------------------------------------- bootstrap
def drawn_offices():
    """Offices 1-150 outside the take-all stratum: the drawn ones."""
    return sorted(int(r["order"]) for r in _csv("draw.csv")
                  if int(r["order"]) <= LOCATED
                  and int(r["size_rank"]) > TAKE_ALL_RANK)


def resample(cs, portals, drawn, rng):
    """One replicate: drawn offices, portals within products, draws within
    cells. Returns (cells, portals, counts), each portal copy renamed."""
    counts = {}
    for _ in drawn:
        o = rng.choice(drawn)
        counts[o] = counts.get(o, 0) + 1
    by_portal = {}
    for (o, m, a), rs in cs.items():
        by_portal.setdefault(o, []).append((m, a, rs))
    by = {}
    for o, p in portals.items():
        by.setdefault(p["product"], []).append(o)
    new_cs, new_portals, i = {}, {}, 0
    for _prod, os_ in sorted(by.items()):
        pick = os_ if len(os_) == 1 else [rng.choice(os_) for _ in os_]
        for o in pick:
            i += 1
            key = 100000 + i
            new_portals[key] = portals[o]
            for m, a, rs in by_portal.get(o, []):
                new_cs[(key, m, a)] = [rng.choice(rs) for _ in rs]
    return new_cs, new_portals, counts


def interval(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    lo, hi = xs[int(0.025 * (len(xs) - 1))], xs[int(0.975 * (len(xs) - 1))]
    return [lo, hi]


def walk(est, path=()):
    """Every numeric leaf of an estimate, keyed by its path."""
    if isinstance(est, dict):
        for k, v in est.items():
            yield from walk(v, (*path, str(k)))
    elif isinstance(est, (int, float)) and not isinstance(est, bool):
        yield path, est


def get(est, path):
    for k in path:
        est = est.get(k) if isinstance(est, dict) else None
        if est is None:
            return None
    return est


# --------------------------------------------------------------- main
def verdict_p2(est, ci):
    if est >= P2_LIMIT:
        return "refuted"
    return "confirmed" if ci and ci[1] < P2_LIMIT else "consistent"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run-id", default="eval-pop-1")
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20261003)
    args = ap.parse_args(argv)
    portals = load_portals()
    rows = population_rows()
    cs = cells(load_records(args.run_id))
    point = estimate(cs, portals, rows)
    rng = random.Random(args.seed)
    drawn = drawn_offices()
    reps = []
    for i in range(args.boot):
        bc, bp, counts = resample(cs, portals, drawn, rng)
        reps.append(estimate(bc, bp, rows, counts))
        if (i + 1) % 200 == 0:
            print("  bootstrap %d of %d" % (i + 1, args.boot), file=sys.stderr)
    cis = {"/".join(p): interval([get(r, p) for r in reps])
           for p, _ in walk(point)}
    no_miss = {o: p for o, p in portals.items() if o not in CHECK_MISSES}
    out = {"run_id": args.run_id, "boot": args.boot, "seed": args.seed,
           "point": point, "intervals": cis,
           "without_check_misses": estimate(cs, no_miss, rows),
           "weights": weights(rows),
           "delivery": {name(a, ms): {"all": delivery(cs, sorted(portals), a,
                                                      ms),
                                      "without_misses": delivery(
                                          cs, sorted(no_miss), a, ms)}
                        for a, ms in APPROACHES}}
    out["p2_verdict"] = verdict_p2(point["p2"], cis.get("p2"))
    fileio.atomic_write(os.path.join(EVAL, "analysis.json"),
                        json.dumps(out, indent=1, sort_keys=True))
    report(out)
    return 0


def _ci(out, key):
    c = out["intervals"].get(key)
    return "[%.3f, %.3f]" % tuple(c) if c else "[-]"


def report(out):
    pt = out["point"]
    w, a = pt["p2_counts"]
    print("\nP2 (primary): %d of %d accepted extractors fail the reference: "
          "%.2f%% %s -> %s" % (w, a, 100 * pt["p2"], _ci(out, "p2"),
                               out["p2_verdict"]))
    for m in STRONG:
        for price in PRICES:
            k = "p1|%s|%s" % (m, price)
            print("P1 loop / %s one-shot, pipeline view, %s: %.3f %s"
                  % (m.split("/")[-1], price, pt[k], _ci(out, k)))
    print("P3 loop minus best-of-k at the loop's spend: %+.3f %s"
          % (pt["p3"], _ci(out, "p3")))
    for k, v in pt["agent"].items():
        print("agent minus %s: %+.3f %s" % (k, v, _ci(out, "agent/" + k)))
    print("\n%-34s %10s %10s   %s" % ("cost per trusted (list)", "pipeline",
                                      "layout", "per product"))
    for arm, models in APPROACHES:
        c = pt["costs"]["%s|list_usd" % name(arm, models)]
        print("%-34s %10s %10s   %s" % (
            name(arm, models),
            "%.4f" % c["pipeline"] if c["pipeline"] else "-",
            "%.4f" % c["layout"] if c["layout"] else "-",
            ", ".join("%s %.4f" % (p[:8], v) for p, v in
                      sorted(c["per_product"].items()) if v)))
    print("\n%-34s %8s %10s %10s %8s" % ("delivery (all 17)", "attempts",
                                         "delivered", "wrong/del", "trusted"))
    for k, v in out["delivery"].items():
        d = v["all"]
        if d["attempts"]:
            print("%-34s %8d %10.3f %10s %8.3f" % (
                k, d["attempts"], d["delivered"],
                "%.3f" % d["wrong_of_delivered"]
                if d["wrong_of_delivered"] is not None else "-", d["trusted"]))
    print("\nweights:", json.dumps(out["weights"], indent=None))


if __name__ == "__main__":
    sys.exit(main())
