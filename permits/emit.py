# -*- coding: utf-8 -*-
"""The shared emit interface. Every extractor, hand-written or synthesized,
produces records through this module and nothing else.

Section 9, obligation 1: *"D8's shared emit interface is binding from the first
adapter, not aspirational. The step-1 adapter must emit through the same
interface a synthesized extractor will, or the schema silently takes the shape
of whatever that one platform exposes and the generic path fights it forever."*

The contract that makes that true:

    **An adapter returns native strings. This module owns all normalization.**

An adapter's job is to locate values on a page or in an API response and hand
back `{field: native_string}`. It never decides what `"NEW SFR"` means. That
keeps the vendor-specific part of every adapter small, and it means a
synthesized extractor at step 4 is drop-in the moment it emits the same dict -
no schema negotiation, no second normalization path to keep in sync, and the
D6 vocabulary mapping is shared rather than reimplemented per platform.

Three fields exist here only because Spike B found the failures they represent,
and each one would otherwise be a silent wrong number rather than a loud error:

  `permit_kind`       Austin issues Electrical, Mechanical and Plumbing
                      sub-permits alongside each Building Permit and **every
                      one carries a populated `housing_units` value**. Summing
                      naively counted dwellings up to four times: 726% error
                      against BPS. Unit counts are credited only from
                      `permit_kind == BUILDING`, and an adapter that cannot
                      determine the kind must say UNKNOWN rather than guess -
                      UNKNOWN is excluded from unit totals and counted loudly.

  `unit_count_source` Nashville-Davidson publishes no unit field at all; units
                      exist only inside free text. "0 units" and "no unit field
                      exists" are different facts and must not collapse into
                      the same integer. ABSENT records are excluded from unit
                      reconciliation rather than treated as zero.

  `structure_type`    Reconciliation joins to BPS on structure type, not on a
                      total. Spike B's whole result was that error is ~2-6% for
                      low-density and unusable for 5+, which is invisible
                      without this split.

No bitemporality at this layer - step 1 is explicitly "no bitemporality". D7
still holds: valid time (`reported_date`) and transaction time (`observed_at`)
are both recorded and neither overwrites the other. What step 1 omits is
interval closing (`observed_from`/`observed_to`), not the second timestamp.
"""
import hashlib
import io
import json
import os
import re
import time

# ---- controlled vocabularies ----------------------------------------------

# BPS structure classes. The reconciliation join lives here and nowhere else.
# BPS place files split units into four columns; these are the codes that map
# onto them. Austin publishes its permit_class as literally "R- 101", "C- 105"
# etc., which is to say some jurisdictions already speak this vocabulary.
SF_DETACHED = "101"
SF_ATTACHED = "102"
TWO_FAMILY = "103"
THREE_FOUR = "104"
FIVE_PLUS = "105"
# Some jurisdictions publish a class that spans several BPS codes and cannot be
# split - Columbus's "1,2,3 Family" is 101 through 104 in one bucket. Inventing
# a column for it would be a fabrication, and dropping it would delete most of
# Columbus. It gets its own marker and is comparable ONLY at the low-density
# aggregate, never per column.
LOW_BUNDLE = "1-4"
STRUCTURE_TYPES = (SF_DETACHED, SF_ATTACHED, TWO_FAMILY, THREE_FOUR, FIVE_PLUS,
                   LOW_BUNDLE)

# Which BPS unit column each structure class is counted in.
BPS_COLUMN = {SF_DETACHED: "u1", SF_ATTACHED: "u1", TWO_FAMILY: "u2",
              THREE_FOUR: "u34", FIVE_PLUS: "u5p", LOW_BUNDLE: "low_bundle"}
# The low-density / multifamily split Spike B's result is stated in.
LOW_DENSITY = ("u1", "u2", "u34", "low_bundle")

WORK_CLASSES = ("NEW", "ADDITION", "ALTERATION", "DEMOLITION", "OTHER",
                "UNKNOWN")

# Only BUILDING contributes units. See the Austin note above.
PERMIT_KINDS = ("BUILDING", "ELECTRICAL", "MECHANICAL", "PLUMBING", "OTHER",
                "UNKNOWN")

UNIT_SOURCES = ("field",            # a dedicated numeric unit column
                "parsed_from_text",  # recovered from a description string
                "implied_by_structure_code",  # definitional; see below
                "absent")            # no unit information exists at all

# `implied_by_structure_code` exists because some sources publish a structure
# class and no unit count, and for three of the BPS classes the unit count is
# not a guess - it is what the class *means*. A 101 is one dwelling unit by
# definition; that is the definition BPS itself counts by.
#
# It is a separate source value rather than being folded into "field" because
# it must stay separately reportable. A jurisdiction whose entire unit total
# is implied has not been measured against BPS, it has been derived from the
# same taxonomy BPS uses, and an error figure computed that way is close to
# circular. The Emitter below tracks implied units in their own column set so
# every reconciliation can be stated with and without them, and trips the
# alarm when a source's units are wholly implied.
#
# Only three classes are determinate. 104 is "three OR four", 105 is "five or
# more", and LOW_BUNDLE spans 101-104: none of them names a number, and
# picking one would be exactly the free-text guess that manufactured the false
# Nashville figure.
IMPLIED_UNITS = {SF_DETACHED: 1, SF_ATTACHED: 1, TWO_FAMILY: 2}

# The known overcount/undercount risk, recorded here because it is a property
# of the rule and not of any one adapter: one permit can cover several
# buildings. A single permit for ten detached houses is ten units and ten
# 101 structures, and implying 1 undercounts it by 10x. Undercounting is the
# safer direction - it surfaces as a reconciliation gap rather than as a
# confident wrong number - but it is not free, and a source where implied
# units dominate needs this checked against a known total before its error
# figure means anything.

MILESTONES = ("applied", "issued", "finaled", "terminated")

SCHEMA_VERSION = "step1.1"


class EmitError(ValueError):
    """Raised instead of emitting a record that cannot be trusted."""


class MissingIdentifier(EmitError):
    """A row that carries no native identifier.

    Its own type because it is the ONLY EmitError that is a property of the
    source data rather than a bug in an adapter. An adapter may legitimately
    count these and continue; it may not do that with any other EmitError.
    Distinguishing them by message text was tried and is too fragile for an
    interface a step-4 synthesized extractor also has to satisfy.
    """


# ---- normalization ---------------------------------------------------------

_INT = re.compile(r"-?\d[\d,]*")
_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d", "%d-%b-%Y", "%m-%d-%Y",
                 "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%b %d, %Y")


def norm_int(s):
    """First integer in a string, or None. Never raises on junk."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return int(s)
    m = _INT.search(str(s))
    return int(m.group(0).replace(",", "")) if m else None


def norm_date(s):
    """Return an ISO date string, or None. Epoch millis are accepted because
    ArcGIS returns them and a silent drop there would empty a whole month."""
    if s is None or s == "":
        return None
    if isinstance(s, (int, float)) or (isinstance(s, str) and s.isdigit()
                                       and len(s) >= 12):
        # ArcGIS esriFieldTypeDate is epoch milliseconds, UTC.
        try:
            return time.strftime("%Y-%m-%d", time.gmtime(float(s) / 1000.0))
        except (ValueError, OSError):
            return None
    s = str(s).strip()
    # The date part alone, then the fixed-width head. St. Johns renders
    # "3/2/2026 11:06:49 PM": single-digit month and day, with a time. The
    # width-based slice below takes the first 10 characters for "%m/%d/%Y"
    # and hands strptime "3/2/2026 1", which fails - so every date from that
    # county came back None while the adapter looked like it was working.
    # strptime itself is happy with unpadded numbers; only the slice was not.
    heads = [s.split()[0] if s.split() else s, s[:19]]
    for head in heads:
        for f in _DATE_FORMATS:
            try:
                return time.strftime("%Y-%m-%d", time.strptime(
                    head[:len(time.strftime(f, time.gmtime(0)))], f))
            except ValueError:
                continue
        try:
            return time.strftime("%Y-%m-%d", time.strptime(head, "%m/%d/%Y"))
        except ValueError:
            pass
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    return m.group(0) if m else None


def norm_text(s):
    return re.sub(r"\s+", " ", str(s)).strip() if s not in (None, "") else None


# ---- the record ------------------------------------------------------------

class PermitRecord(object):
    """One permit as emitted by any extractor.

    `observation_key` is D5's deterministic half: `(source_id,
    source_native_id_raw)`, computed at fetch time and never inferred. No
    `permit_id` is assigned here - entity resolution is a derived view (D5),
    and writing a surrogate into the log would mean un-merging requires
    rewriting history.
    """

    __slots__ = (
        "address",
        "bps_id",
        "content_hash",
        "description",
        "extractor_version",
        "milestones",
        "native",
        "native_id",
        "observed_at",
        "permit_kind",
        "platform",
        "source_id",
        "state_fips",
        "structure_type",
        "unit_count",
        "unit_count_source",
        "valuation",
        "work_class",
    )

    def __init__(self, source_id, state_fips, bps_id, native_id, platform,
                 extractor_version, content_hash=None, native=None):
        if not native_id or not str(native_id).strip():
            # D5: "no native ID" is a real case, but it needs a content-derived
            # key and a low-confidence flag, which step 1 does not build. Fail
            # loudly rather than emit a record with no identity.
            raise MissingIdentifier("no native identifier; D5 content-derived "
                                    "keys are out of scope for step 1")
        if not (state_fips and bps_id):
            raise EmitError("D3: office identity is (state_fips, bps_id), "
                            "never a name and never a FIPS place")
        self.source_id = source_id
        self.state_fips = str(state_fips).zfill(2)
        self.bps_id = str(bps_id)
        self.native_id = str(native_id).strip()
        self.platform = platform
        self.extractor_version = extractor_version
        self.content_hash = content_hash
        self.native = native or {}

        self.permit_kind = "UNKNOWN"
        self.work_class = "UNKNOWN"
        self.structure_type = None
        self.unit_count = None
        self.unit_count_source = "absent"
        self.valuation = None
        self.address = None
        self.description = None
        self.milestones = []
        self.observed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # -- D5 -------------------------------------------------------------
    @property
    def observation_key(self):
        return "%s|%s" % (self.source_id, self.native_id)

    # -- D6: milestones are rows, not booleans --------------------------
    def milestone(self, name, reported_date, native_string=None):
        """Record that a milestone was observed with a reported date.

        Absence of a row means *not observed*, which is not the same as *did
        not happen* - that distinction is the whole reason these are rows.
        """
        if name not in MILESTONES:
            raise EmitError("unknown milestone %r" % name)
        d = norm_date(reported_date)
        if d is None:
            return self
        self.milestones.append({"milestone": name, "reported_date": d,
                                "native_string": norm_text(native_string)})
        return self

    def reported(self, name):
        for m in self.milestones:
            if m["milestone"] == name:
                return m["reported_date"]
        return None

    # -- units ----------------------------------------------------------
    def units(self, value, source):
        """Set the unit count and say where it came from.

        `source` is not optional and not inferable. "0 units" and "this
        jurisdiction publishes no unit field" are different facts; collapsing
        them silently zeroes out a jurisdiction in the reconciliation.
        """
        if source not in UNIT_SOURCES:
            raise EmitError("unit_count_source must be one of %r" %
                            (UNIT_SOURCES,))
        self.unit_count_source = source
        self.unit_count = None if source == "absent" else norm_int(value)
        return self

    @property
    def countable_units(self):
        """Units this record contributes to a BPS-comparable total.

        Everything that is not a building permit contributes zero, whatever its
        unit field says. This is the Austin sub-permit trap expressed as code
        rather than as a filter someone has to remember to apply.
        """
        if self.permit_kind != "BUILDING":
            return 0
        if self.unit_count_source == "absent" or self.unit_count is None:
            return 0
        if self.work_class != "NEW":
            return 0
        return self.unit_count

    @property
    def units_implied(self):
        return self.unit_count_source == "implied_by_structure_code"

    @property
    def countable_units_measured(self):
        """Countable units the source actually stated.

        The complement of the implied ones. Carried on the record so a
        reconciliation can be reported both ways without re-deriving the rule,
        and so "we measured this" and "we inferred this from the same taxonomy
        we are checking against" never silently become one number.
        """
        return 0 if self.units_implied else self.countable_units

    @property
    def bps_column(self):
        return BPS_COLUMN.get(self.structure_type)

    def validate(self):
        if self.permit_kind not in PERMIT_KINDS:
            raise EmitError("permit_kind %r" % self.permit_kind)
        if self.work_class not in WORK_CLASSES:
            raise EmitError("work_class %r" % self.work_class)
        if self.structure_type is not None \
                and self.structure_type not in STRUCTURE_TYPES:
            raise EmitError("structure_type %r" % self.structure_type)
        if self.unit_count_source == "absent" and self.unit_count is not None:
            raise EmitError("unit_count set while source is 'absent'")
        if self.units_implied:
            # An implied count that does not match what the class implies means
            # the two were set from different reasoning, and the record no
            # longer says where its number came from. That is the one property
            # this source value has to guarantee.
            want = IMPLIED_UNITS.get(self.structure_type)
            if want is None:
                raise EmitError(
                    "unit_count_source is implied_by_structure_code but "
                    "structure_type %r implies no determinate count"
                    % (self.structure_type,))
            if self.unit_count != want:
                raise EmitError(
                    "structure_type %s implies %d unit(s), record carries %r"
                    % (self.structure_type, want, self.unit_count))
        return self

    def as_dict(self):
        return {
            "observation_key": self.observation_key,
            "source_id": self.source_id,
            "state_fips": self.state_fips,
            "bps_id": self.bps_id,
            "native_id": self.native_id,
            "platform": self.platform,
            "permit_kind": self.permit_kind,
            "work_class": self.work_class,
            "structure_type": self.structure_type,
            "bps_column": self.bps_column,
            "unit_count": self.unit_count,
            "unit_count_source": self.unit_count_source,
            "countable_units": self.countable_units,
            "countable_units_measured": self.countable_units_measured,
            "valuation": self.valuation,
            "address": self.address,
            "description": self.description,
            "milestones": self.milestones,
            "date_applied": self.reported("applied"),
            "date_issued": self.reported("issued"),
            "observed_at": self.observed_at,
            "native": self.native or None,
            "content_hash": self.content_hash,
            "extractor_version": self.extractor_version,
            "schema_version": SCHEMA_VERSION,
        }


# ---- the sink, with the drift alarm built in -------------------------------

class Emitter(object):
    """Writes records as JSONL and counts what it could not fill in.

    The per-field null rate is section 5's drift alarm. It is here rather than
    in a later analysis step because Spike B watched Mecklenburg County abandon
    `worktype` mid-dataset - populated 123,262 times historically, blank in
    every one of the 500 records issued in Q1 2026 - with no signal of any
    kind. An alarm that runs only when someone remembers to look is not an
    alarm. This one runs on every record that is ever emitted.
    """

    ALARM_FIELDS = ("permit_kind", "work_class", "structure_type",
                    "unit_count", "date_issued")

    def __init__(self, path, source_id):
        self.path = path
        self.source_id = source_id
        self.n = 0
        self.rejected = 0
        self.null = dict.fromkeys(self.ALARM_FIELDS, 0)
        self.unknown_kind = 0
        self.by_column = {}
        self.by_column_implied = {}
        d = os.path.dirname(path)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        self._fh = io.open(path, "a", encoding="utf-8", newline="\n")

    def emit(self, rec):
        try:
            rec.validate()
        except EmitError:
            self.rejected += 1
            raise
        d = rec.as_dict()
        self._fh.write(json.dumps(d, sort_keys=True) + "\n")
        self.n += 1
        for f in self.ALARM_FIELDS:
            v = d.get(f)
            if v is None or v == "UNKNOWN":
                self.null[f] += 1
        if rec.permit_kind == "UNKNOWN":
            self.unknown_kind += 1
        c = rec.bps_column
        if c and rec.countable_units:
            self.by_column[c] = self.by_column.get(c, 0) + rec.countable_units
            if rec.units_implied:
                self.by_column_implied[c] = (
                    self.by_column_implied.get(c, 0) + rec.countable_units)
        return self

    def alarm(self):
        """Per-field null rates, and whether any of them should stop the run."""
        if not self.n:
            return {"n": 0, "rates": {}, "tripped": []}
        rates = dict((f, round(self.null[f] / float(self.n), 4))
                     for f in self.ALARM_FIELDS)
        tripped = []
        # A classification field that is null for most records means the
        # jurisdiction cannot be classified at all, which is Mecklenburg.
        for f in ("permit_kind", "work_class"):
            if rates[f] >= 0.90:
                tripped.append("%s null in %.0f%% of records - the field this "
                               "classification depends on is not populated"
                               % (f, 100 * rates[f]))
        if rates["structure_type"] >= 0.99:
            tripped.append("structure_type never determined - no BPS join is "
                           "possible for this source")
        # A source with almost no unit data must not produce an error figure.
        # Nashville publishes no unit field; a free-text fallback recovered a
        # handful of exact counts and refused every open-ended range, which is
        # the correct per-record behaviour but adds up to a systematic
        # undercount - it scored 87-105% "error" against BPS, a number that
        # describes the fallback rather than Nashville. Spike B declined to
        # score Nashville at all and that was right. Recovering 1% of units is
        # not partial coverage, it is a different measurement wearing the same
        # units, and reporting it would be worse than reporting nothing.
        if rates["unit_count"] >= 0.95:
            tripped.append("unit_count absent in %.0f%% of records - no usable "
                           "unit field; this source yields permit counts only "
                           "and must not be scored against BPS units"
                           % (100 * rates["unit_count"]))
        # `implied_by_structure_code` fills unit_count in, so a source whose
        # units are entirely derived from its structure class would sail past
        # the check above looking measured. It is not measured. Deriving units
        # from the same taxonomy the reconciliation joins on and then calling
        # the agreement an error figure is close to circular, and the whole
        # reason that source value is tracked separately is so this can fire.
        # Implied units qualify a figure; they do not block one. The two are
        # different findings and collapsing them was wrong.
        #
        # `tripped` means the source cannot be scored at all: the field the
        # number would come from is not populated, so any figure would describe
        # the extractor rather than the jurisdiction. `qualified` means the
        # number is real but may not be quoted bare.
        #
        # St. Johns County is why the distinction is needed. Every one of its
        # units is implied from its published structure class, so the sentence
        # below is true - but the comparison is still between two independent
        # observations. Ours is a count of the 101/102 permits the county's
        # public portal shows; BPS is what that county mailed to the Census
        # Bureau. They share a taxonomy, not a measurement, and they can
        # disagree through unreported permits, month-boundary lag, coverage, or
        # a permit covering more than one house. Suppressing that comparison
        # would discard the one test available of the implication rule itself.
        #
        # This does not weaken the blocking cases, which is the check that it
        # is a principled change rather than a convenient one: Clark County has
        # no unit field on 96% of records and is still stopped by the coverage
        # alarm above, whatever this one says.
        total = sum(self.by_column.values())
        implied = sum(self.by_column_implied.values())
        qualified = []
        if total and implied == total:
            qualified.append(
                "every countable unit is implied_by_structure_code - this "
                "source states no unit counts, so the total is derived from "
                "the BPS taxonomy and the comparison tests the implication "
                "rule itself; it may not be quoted as a measured figure")
        elif total and implied >= 0.5 * total:
            qualified.append("%.0f%% of countable units are "
                             "implied_by_structure_code - report the measured "
                             "and implied totals separately"
                             % (100.0 * implied / total))
        return {"n": self.n, "rates": rates, "tripped": tripped,
                "qualified": qualified,
                "by_bps_column": self.by_column,
                "by_bps_column_implied": self.by_column_implied,
                "units_total": total, "units_implied": implied,
                "unknown_permit_kind": self.unknown_kind}

    def close(self):
        self._fh.close()
        return self.alarm()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


def content_hash(b):
    if isinstance(b, str):
        b = b.encode("utf-8", "replace")
    return hashlib.sha256(b).hexdigest()
