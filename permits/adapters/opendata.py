# -*- coding: utf-8 -*-
"""Adapter for bucket-1 sources: Socrata and ArcGIS FeatureServer.

This is the first code in the project that materializes a permit **record**.
Spike B never did - it asked Socrata and ArcGIS to `COUNT` and `SUM` server
side and compared the totals. That was the right call for a half-day
feasibility spike and it is why the spike cost 57 requests, but it means every
Spike B number came out of a `where` clause that nothing downstream could
inspect. A wrong clause produced a wrong total with no trace, which is exactly
how Austin's 726% error happened and stayed invisible until the permit-type
breakdown was pulled by hand.

Records change that: the classification decision is attached to each row, the
rule that fired is recorded, and the reconciliation is a fold over rows rather
than a server-side aggregate taken on trust.

**The adapter locates native strings. It does not interpret them.** Every
classification goes through `permits.vocab`, and every record is constructed
through `permits.emit`. That is section 9's obligation 1 - a synthesized
extractor at step 4 emits the same dict into the same interface, and there is
no second normalization path to keep in sync.

The fetcher is injected rather than imported so this module stays independent
of the capture layer; the runner wires in `permits.capture`, which is the
working D1 implementation (a page may not exist on disk without a manifest row
written in the same operation).
"""
import json
import urllib.parse

from .. import emit, vocab

ADAPTER_VERSION = "opendata/1.0"

# Socrata pages at 50k but politeness and memory both argue for smaller; ArcGIS
# services commonly cap `maxRecordCount` near 1000-2000 and silently truncate
# above it, which is a failure mode that looks exactly like a quiet month.
PAGE_SIZE = {"socrata": 5000, "arcgis": 1000}


class Source(object):
    """One publisher dataset, with the native field names stated explicitly.

    Field names are not guessed. Every one here was read out of the dataset's
    own schema endpoint during Spike B (`data/spike_b/schema.json`) or out of
    the vocabulary dump. Guessing a field name is how this project previously
    fabricated three `bps_id` values and a `classification.csv`.
    """

    def __init__(self, key, state_fips, bps_id, label, platform, base,
                 id_field, issued_field, units_field, structure_fields,
                 work_fields, kind_fields, applied_field=None,
                 default_kind=None, desc_fields=(), address_field=None,
                 alt_units_field=None, note=None):
        self.key = key
        self.source_id = "%s|%s|%s" % (state_fips, bps_id, key)
        self.state_fips = state_fips
        self.bps_id = bps_id
        self.label = label
        self.platform = platform
        self.base = base
        self.id_field = id_field
        self.issued_field = issued_field
        self.applied_field = applied_field
        self.units_field = units_field
        self.alt_units_field = alt_units_field
        self.structure_fields = structure_fields
        self.work_fields = work_fields
        self.kind_fields = kind_fields
        self.default_kind = default_kind
        self.desc_fields = desc_fields
        self.address_field = address_field
        self.note = note


def _url(src, lo, hi, offset, limit):
    """A date-bounded page of records. Half-open [lo, hi) in both dialects."""
    if src.platform == "socrata":
        w = "%s >= '%sT00:00:00' AND %s < '%sT00:00:00'" % (
            src.issued_field, lo, src.issued_field, hi)
        return src.base + "?" + urllib.parse.urlencode(
            {"$where": w, "$limit": limit, "$offset": offset,
             "$order": src.id_field})
    w = ("%s >= TIMESTAMP '%s 00:00:00' AND %s < TIMESTAMP '%s 00:00:00'"
         % (src.issued_field, lo, src.issued_field, hi))
    return src.base + "/query?" + urllib.parse.urlencode(
        {"where": w, "outFields": "*", "f": "json", "returnGeometry": "false",
         "resultOffset": offset, "resultRecordCount": limit,
         "orderByFields": src.id_field})


def _rows(body, platform):
    """Parse a page, and say whether the server truncated it.

    ArcGIS sets `exceededTransferLimit` when it returns fewer rows than asked
    for because of a server-side cap. Ignoring that flag is how a paginated
    pull silently returns a third of a month and reports success.
    """
    d = json.loads(body)
    if platform == "socrata":
        return d, False
    if "error" in d:
        raise RuntimeError("ArcGIS error: %s" % json.dumps(d["error"])[:300])
    return ([f.get("attributes", {}) for f in d.get("features", [])],
            bool(d.get("exceededTransferLimit")))


def _pick(row, fields):
    return tuple(row.get(f) for f in fields)


def build(src, row, vb, content_hash):
    """One native row to one PermitRecord. All interpretation via vocab."""
    rec = emit.PermitRecord(
        source_id=src.source_id, state_fips=src.state_fips,
        bps_id=src.bps_id, native_id=row.get(src.id_field),
        platform=src.platform, extractor_version=ADAPTER_VERSION,
        content_hash=content_hash, native=None)

    rec.permit_kind, _ = vb.kind(*_pick(row, src.kind_fields))
    rec.work_class, _ = vb.work(*_pick(row, src.work_fields))
    structure, structure_rule = vb.structure(*_pick(row, src.structure_fields))

    desc = " | ".join(str(row.get(f)) for f in src.desc_fields
                      if row.get(f) not in (None, ""))
    rec.description = emit.norm_text(desc)
    if src.address_field:
        rec.address = emit.norm_text(row.get(src.address_field))

    # Units. A dedicated numeric field is the only trustworthy source; free
    # text is a documented fallback that refuses open-ended ranges rather than
    # guessing at them (see vocab.units_from_text).
    if src.units_field and row.get(src.units_field) not in (None, ""):
        rec.units(row.get(src.units_field), "field")
    else:
        u, _ = vb.units_from_text(rec.description)
        if u is not None:
            rec.units(u, "parsed_from_text")
        else:
            rec.units(None, "absent")

    # A competing unit field, carried rather than chosen. Seattle publishes
    # housingunits and housingunitsadded and they are not the same quantity;
    # which one reconciles against BPS is a measurement, not a preference.
    if src.alt_units_field:
        rec.native = {"alt_units": emit.norm_int(row.get(src.alt_units_field)),
                      "alt_units_field": src.alt_units_field}

    # Structure is set last, because refining it needs the unit count.
    structure, refine_rule = vb.refine(structure, rec.unit_count,
                                       rec.work_class)
    rec.structure_type = structure
    rec.native = dict(rec.native or {},
                      structure_rule=refine_rule or structure_rule)

    rec.milestone("issued", row.get(src.issued_field),
                  native_string=str(row.get(src.issued_field)))
    if src.applied_field:
        rec.milestone("applied", row.get(src.applied_field))
    return rec


def pull(src, lo, hi, fetch, emitter, vb, max_pages=12):
    """Fetch every record issued in [lo, hi) and emit it. Returns a summary.

    `fetch(url, name, page_type) -> (body, row)` is injected; `row` is the
    provenance record the capture layer wrote, and its sha256 becomes the
    record's `content_hash` so every emitted permit points back at the exact
    bytes it came from.
    """
    n_rows = n_emitted = n_rejected = 0
    truncated = False
    size = PAGE_SIZE[src.platform]
    offset = 0
    for page in range(max_pages):
        url = _url(src, lo, hi, offset, size)
        body, prov = fetch(url, "%s_%s_%d" % (src.key, lo[:7], page),
                           "API-DATA")
        if body is None:
            break
        rows, over = _rows(body, src.platform)
        truncated = truncated or over
        h = (prov or {}).get("sha256")
        for r in rows:
            n_rows += 1
            try:
                emitter.emit(build(src, r, vb, h))
                n_emitted += 1
            except emit.MissingIdentifier:
                # A record with no native identifier cannot be given one
                # without D5's content-derived key, which step 1 does not
                # build. Count it; do not invent an id for it. Narrowed from
                # a bare EmitError: the broad catch let an adapter bug be
                # counted as a data property for 351 Clark County rows.
                n_rejected += 1
        if len(rows) < size:
            break
        offset += size
    return {"rows_seen": n_rows, "emitted": n_emitted,
            "rejected_no_id": n_rejected, "server_truncated": truncated,
            "pages": page + 1}


def vocabulary_for(src):
    return vocab.Vocabulary(src.source_id, src.platform,
                            default_kind=src.default_kind)
