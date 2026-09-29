# -*- coding: utf-8 -*-
"""The per-cell roll-up of every model measurement: one long table of
observations, and the aggregates derived from it.

`scripts/model_stats.py` writes these to `data/infer/model_stats.csv` and
`model_stats.json`; `scripts/export_results.py` builds the results page's
data from the same functions, so the stats table, the report and the page
cannot disagree. Everything here is pure: callers read the artifacts and pass
them in.

A row is `experiment, target, model, condition, unit, unit_id, metric,
value`, so a new metric is a new row rather than a new column.
"""
import collections

from permits import infer
from permits.cells import draws_of
from permits.stats import failure_mode, pctile, wilson

__all__ = ["FIELDS", "aggregate", "cell_name", "condition", "draws_of",
           "failure_mode", "label", "pick", "purchases", "rows_from_drift",
           "rows_from_ledger", "rows_from_variance", "short", "unclaimed"]

FIELDS = ["experiment", "target", "model", "condition", "unit", "unit_id",
          "metric", "value"]


def short(model):
    """`claude-haiku-4-5-20251001` -> `haiku-4-5`, `qwen/qwen3-coder` ->
    `qwen3-coder`. Delegated so the two tables that name models agree; this
    file had its own copy, which predated the second provider and rendered a
    vendor-prefixed id at full width straight through the column.

    An id with no registry entry prints as itself. This only reads records
    already on disk, and a report that refuses to print a row is worse than
    one that prints it wide. An effort cell's `model@effort` keeps its
    effort."""
    base, sep, effort = model.partition("@")
    try:
        return infer.short_model(base) + sep + effort
    except infer.Refused:
        return model


def condition(cell):
    """The experimental condition a variance cell was run under: `baseline`,
    or the parts that set it apart, `hint` and the protocol, joined with `|`
    in the order `CellSpec.key` uses.

    Cells written before `--synth-hint` existed carry no flag and were all
    run on the baseline prompt; cells with no `protocol` ran under v1."""
    parts = ["hint"] if cell.get("synth_hint") else []
    if cell.get("protocol", "v1") != "v1":
        parts.append(cell["protocol"])
    return "|".join(parts) or "baseline"


def label(cell):
    """The model as the cell names it, `model@effort` on an effort cell."""
    return ("%s@%s" % (cell["model"], cell["effort"]) if cell.get("effort")
            else cell["model"])


def purchases(v, ledger):
    """The ledger row that bought each scored draw, keyed (cell key, draw).

    A draw record says what this run paid, which is zero for a draw replayed
    from the response cache. The cost of a cell is what its draws cost to
    buy, whenever that was, so each draw is joined to the ledger row that
    produced the response it was scored on.

    The join is on (model, target, draw index, output tokens) over successful
    variance synthesis calls. The ledger does not record which prompt a call
    used, so the output token count is what separates a hinted draw from the
    baseline draw with the same index, and a draw bought under an earlier
    output ceiling from the one scored now. Each ledger row is claimed at
    most once. When two rows match - the same draw bought twice by two
    concurrent runs, with identical token counts - the later one is taken,
    because the cache keeps the last response written.

    Ledger rows no draw claims are not a cell's cost: they are superseded or
    duplicate purchases, reported separately by `unclaimed`. A draw with no
    matching row maps to None and the cell's spend is then unknown rather
    than understated.
    """
    index = collections.defaultdict(list)
    for i, r in enumerate(ledger):
        if _is_variance_purchase(r):
            index[(r.model, r.tag.split("/")[0], r.draw,
                   r.output_tokens)].append(i)
    claimed, out = set(), {}
    for key, cell in sorted(v["cells"].items()):
        for d in draws_of(cell):
            if not d.scored():
                continue
            hits = [i for i in index.get((cell["model"], cell["target"],
                                          d.draw, d.output_tokens), [])
                    if i not in claimed]
            if hits:
                claimed.add(hits[-1])
                out[(key, d.draw)] = hits[-1]
            else:
                out[(key, d.draw)] = None
            # A re-drawn draw was bought twice: the cut-off attempt is part
            # of its cost, keyed apart so the scored attempt's row is still
            # the one latency is read from.
            if d.truncated_output_tokens is not None:
                cut = [i for i in index.get((cell["model"], cell["target"],
                                             d.draw,
                                             d.truncated_output_tokens), [])
                       if i not in claimed]
                if cut:
                    claimed.add(cut[-1])
                out[(key, d.draw, "cut")] = cut[-1] if cut else None
    return out


def _is_variance_purchase(r):
    return (r.call_class == "synthesis" and r.tag.endswith("/var")
            and r.ok)


def unclaimed(v, ledger):
    """Variance synthesis rows that no scored draw was bought by."""
    used = {i for i in purchases(v, ledger).values() if i is not None}
    return [i for i, r in enumerate(ledger)
            if _is_variance_purchase(r) and i not in used]


def rows_from_variance(v, ledger=()):
    """One row per draw per metric. Draws that were never attempted are
    emitted as `attempted=0` rather than dropped: a cell that stopped on
    budget has a different denominator from one that ran out of successes,
    and dropping the row loses that distinction.

    An infrastructure error is emitted as `attempted=0, infra_error=1`: it
    is reported beside the pass rate, not as a failure in it.

    `usd` is what the run that wrote the record paid; `usd_purchase`,
    `seconds`, `ttft_s` and `tokens_per_s` come from the ledger row that
    bought the response (see `purchases`). A draw with no such row gets
    `purchase_unknown=1` instead. Tokens per second is output tokens over
    the time after the first token, so queueing and thinking that the host
    does not stream are not counted as slow generation.
    """
    bought = purchases(v, ledger)
    out = []
    for key, cell in v["cells"].items():
        target, model, cond = cell["target"], label(cell), condition(cell)
        for d in draws_of(cell):
            mode = failure_mode(d)
            uid = "d%02d" % d.draw
            if mode == "not_attempted":
                metrics = [("attempted", 0)]
            elif mode == "infra_error":
                metrics = [("attempted", 0), ("infra_error", 1)]
            else:
                metrics = [
                    ("attempted", 1),
                    ("perfect", 1 if mode == "perfect" else 0),
                    ("silent_failure", 1 if mode.startswith("silent") else 0),
                    ("loud_failure", 1 if mode == "loud" else 0),
                    ("usd", d.spend()),
                    ("output_tokens", d.output_tokens),
                    ("source_bytes", d.bytes),
                    ("truncated", 1 if d.truncated else 0),
                    ("redrawn", 1 if d.redraw_max_tokens else 0),
                    ("reasoning_tokens", d.reasoning_tokens),
                ]
                i = bought.get((key, d.draw))
                redrawn = d.truncated_output_tokens is not None
                cut = bought.get((key, d.draw, "cut"))
                if i is None or (redrawn and cut is None):
                    metrics.append(("purchase_unknown", 1))
                else:
                    row = ledger[i]
                    metrics.append(("usd_purchase", row.usd
                                    + (ledger[cut].usd if redrawn else 0.0)))
                    metrics.append(("seconds", row.seconds))
                    if row.ttft_s is not None:
                        metrics.append(("ttft_s", row.ttft_s))
                        gen = row.seconds - row.ttft_s
                        if gen > 0:
                            metrics.append(("tokens_per_s",
                                            round(row.output_tokens / gen, 1)))
            for metric, value in metrics:
                out.append({"experiment": "variance", "target": target,
                            "model": model, "condition": cond,
                            "unit": "draw", "unit_id": uid,
                            "metric": metric, "value": value})
    return out


def rows_from_drift(dr):
    """One row per candidate per mutation. The `clean` column is excluded
    from survival: an extractor that was already broken before any mutation
    was applied has not been shown to be brittle, it has been shown to be
    broken, and folding the two together is how the published Haiku Accela
    extractor's 0/8 nearly became a drift finding."""
    out = []
    for target, t in dr["targets"].items():
        for mutation, results in t["mutations"].items():
            if mutation == "clean":
                continue
            for candidate, r in results.items():
                out.append(
                    {"experiment": "drift", "target": target,
                     "model": candidate, "condition": "",
                     "unit": "extractor_mutation",
                     "unit_id": "%s|%s" % (candidate, mutation),
                     "metric": "survived",
                     "value": 1 if r.get("survived") else 0})
    return out


def rows_from_ledger(ledger):
    """One row per API call. `ok` is absent on rows written before
    2026-09-22 and reads as a success, which is what it was - the client of
    the day could not record anything else (`LedgerRow.from_dict`)."""
    out = []
    for i, r in enumerate(ledger):
        target = r.tag.split("/")[0]
        for metric, value in (("usd", r.usd), ("seconds", r.seconds),
                              ("input_tokens", r.input_tokens),
                              ("output_tokens", r.output_tokens),
                              ("cache_read_input_tokens",
                               r.cache_read_input_tokens)):
            out.append({"experiment": "ledger", "target": target,
                        "model": r.model, "condition": "",
                        "unit": "call", "unit_id": "c%04d" % i,
                        "metric": metric, "value": value})
        out.append({"experiment": "ledger", "target": target,
                    "model": r.model, "condition": "",
                    "unit": "call", "unit_id": "c%04d" % i, "metric": "ok",
                    "value": 1 if r.ok else 0})
    return out


def pick(rows, experiment, metric, target=None, model=None, cond=None):
    return [r["value"] for r in rows
            if r["experiment"] == experiment and r["metric"] == metric
            and (target is None or r["target"] == target)
            and (model is None or r["model"] == model)
            and (cond is None or r["condition"] == cond)]


def cell_name(target, model, cond):
    """The key `scripts/conformance.py` files the cell under in
    variance.json, so a figure here can be traced to its draws."""
    base = "%s|%s" % (target, model)
    return base if cond == "baseline" else "%s|%s" % (base, cond)


def aggregate(rows):
    """Per-cell summary, derived from the long table only.

    A cell is (target, model, condition). Grouping on (target, model) alone
    pooled hinted draws into the baseline rate, so the key carries the
    condition and matches the variance.json key it came from."""
    cells = sorted({(r["target"], r["model"], r["condition"]) for r in rows
                    if r["experiment"] == "variance"})
    out = {}
    for target, model, cond in cells:
        def var(metric, target=target, model=model, cond=cond):
            return pick(rows, "variance", metric, target, model, cond)
        att = var("attempted")
        perf = var("perfect")
        silent = var("silent_failure")
        n, k = len(perf), sum(perf)
        fails = n - k
        n_silent = sum(silent)
        infra = sum(var("infra_error"))
        # A draw cut off at the cap is a harness failure and a v2 draw is
        # re-drawn once at the catalogue limit, so `redrawn` counts those and
        # `truncated` the scored attempts still cut off: after a re-draw, or
        # on a v1 cell, which is not re-drawn.
        truncated = sum(var("truncated"))
        redrawn = sum(var("redrawn"))
        lat = var("seconds")
        # Call errors are a property of the provider, not the prompt, and a
        # failed call has no draw to join to, so this one figure is pooled
        # over every call for the model on the target.
        errs = pick(rows, "ledger", "ok", target, model)
        # What failed calls were billed, pooled the same way. Zero until a
        # host closed streams early with the charge reported (step 6
        # pre-registration, deviation 2); outside `usd_total`, which is what
        # the scored draws cost, so a host's failures are not read as the
        # model's price.
        calls = collections.defaultdict(dict)
        for r in rows:
            if (r["experiment"] == "ledger" and r["target"] == target
                    and r["model"] == model):
                calls[r["unit_id"]][r["metric"]] = r["value"]
        usd_failed = sum(c.get("usd", 0.0) for c in calls.values()
                         if not c.get("ok", 1))
        # What the run that wrote the record paid, and what the cell's draws
        # cost to buy. The second is the denominator: a draw replayed from
        # the cache is free to repeat but was not free to buy.
        usd_run = sum(var("usd"))
        usd = sum(var("usd_purchase"))
        unknown = sum(var("purchase_unknown"))
        # Survival is pooled over the draws of this model on this target.
        # Candidate names in drift.json carry the tier, not the model id.
        tag = short(model)
        surv = [r["value"] for r in rows
                if r["experiment"] == "drift" and r["target"] == target
                and r["model"].startswith("draw %s " % tag)]
        lo, hi = wilson(k, n)
        e = {
            "target": target, "model": model, "condition": cond,
            "draws_attempted": sum(att), "draws_scored": n,
            "perfect": k,
            "success_rate": (float(k) / n) if n else None,
            "success_ci95": [round(lo, 4), round(hi, 4)],
            "failures": fails, "silent_failures": n_silent,
            "usd_total": round(usd, 6),
            "usd_this_run": round(usd_run, 6),
            "draws_unpriced": unknown,
            # Cost per extractor that actually worked. The headline cost of a
            # cheap model is per call; the cost that matters is per success,
            # and on a 5% cell those differ by twentyfold.
            # None means "cannot be stated": either no successes, since
            # dividing a bill by zero is how a broken cell gets quoted as
            # free, or a draw whose purchase is missing from the ledger, since
            # a partial bill understates the cost.
            "usd_per_success": (round(usd / k, 6)
                                if k and usd and not unknown else None),
            # True when some of the draws were scored from the cache, so the
            # spend above was paid by earlier runs rather than this one.
            "usd_is_replayed": bool(usd and usd_run < usd),
            "latency_p50_s": pctile(lat, 0.50),
            "latency_p95_s": pctile(lat, 0.95),
            # Draws the host failed twice, as a share of draws sent. Beside
            # the success rate, never inside it.
            "draws_truncated": truncated,
            "draws_redrawn": redrawn,
            "reasoning_tokens_p50": pctile(var("reasoning_tokens"), 0.50),
            "draws_infra_error": infra,
            "infra_error_rate": (float(infra) / (n + infra)
                                 if n + infra else None),
            # None on draws bought before the ledger recorded first token.
            "ttft_p50_s": pctile(var("ttft_s"), 0.50),
            "tokens_per_s_p50": pctile(var("tokens_per_s"), 0.50),
            "api_calls": len(errs),
            "usd_failed_calls": round(usd_failed, 6),
            "api_error_rate": (1.0 - float(sum(errs)) / len(errs)
                               if errs else None),
        }
        if fails:
            slo, shi = wilson(n_silent, fails)
            e["silent_share_of_failures"] = round(float(n_silent) / fails, 4)
            e["silent_ci95"] = [round(slo, 4), round(shi, 4)]
        # Drift candidates are baseline extractors; drift.json does not
        # record a condition, so survival is attached to the baseline only.
        if surv and cond == "baseline":
            dlo, dhi = wilson(sum(surv), len(surv))
            e["drift_survival"] = round(float(sum(surv)) / len(surv), 4)
            e["drift_n"] = len(surv)
            e["drift_ci95"] = [round(dlo, 4), round(dhi, 4)]
        out[cell_name(target, model, cond)] = e
    return out
