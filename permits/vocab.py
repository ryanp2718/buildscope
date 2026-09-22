# -*- coding: utf-8 -*-
"""Native strings to controlled vocabulary. D6's mapping layer.

D6 amortizes vocabulary mapping per `(platform, jurisdiction, native_string)`
rather than per record, so this module is a pure function of a string plus a
tally of what it could not map. Adapters call it; a synthesized extractor at
step 4 calls the same thing. There is one normalization path, not two.

**The central rule: prefer the embedded BPS structure code over a keyword.**

Austin publishes `permit_class` as "R- 101 Single Family Houses", "C- 105 Five
or More Family Bldgs", "R- 103 Two Family Bldgs". Those numbers are not
Austin's taxonomy, they are the Census structure codes - 101/102/103/104/105 -
because Austin files a BPS return and reuses the codes internally. Many
jurisdictions do. Matching the code is therefore both more precise and more
portable than matching English, and it is self-excluding: 329, 434, 435, 438,
645 and the 3xx/4xx/6xx families are not dwellings and simply do not match.

Two errors this module exists to prevent, both found by reading the
vocabularies Spike B pulled:

  **1. Prefix-listing the structure codes drops records.** Spike B's Austin
  rule enumerated ("R- 101", "R- 102", "R- 103", "R- 104", "C- 105", "R- 105").
  Austin's vocabulary also contains **"C- 101 Single Family Houses" (8,279
  records)** and **"C- 104 Three & Four Family Bldgs" (5,949)**. Both were
  silently excluded. The residential/commercial prefix is not a reliable guide
  to what the structure is; the code is. Matching `\\b10[1-5]\\b` regardless of
  prefix fixes this and cannot drift the same way again.

  **2. Filtering on a "residential" permit type drops multifamily.** Charlotte
  splits `permittype` into "One/Two Family" and "Commercial" and files
  apartment buildings under Commercial. Nashville has "Building Residential -
  New" (11,016) and "Building Commercial - New" (868) and the apartments are in
  the second. A rule that selects the residential-looking value loses exactly
  the structure class Spike B reported as unusable - which means part of that
  multifamily error is a classification bug, not the timing effect it was
  attributed to. **Never use a residential keyword as the unit-bearing test.**
  Use a positive unit count, which is what a dwelling actually is.

Every classifier returns `(value, rule_name)`. The rule name is recorded so a
number can be traced to the line of reasoning that produced it, and so an
unmapped string is visible rather than silently becoming UNKNOWN.
"""
import collections
import re

from . import emit

# What one row of a source-published classification code table says.
#
# Some jurisdictions publish their own code legend - St. Johns County FL
# renders all 69 of its Property Use codes as the options of the search form's
# own dropdown, with labels. That is strictly better evidence than any keyword
# match on a type string, because it is the jurisdiction stating what its own
# codes mean rather than this project guessing. It is also per-source: two
# jurisdictions using the same integer rarely mean the same thing by it.
#
# `units` is the count the code definitionally implies, or None where it names
# no number. `exclude` marks a code whose records are real permits but must not
# reach a BPS comparison - see the constant below.
CodeSpec = collections.namedtuple(
    "CodeSpec", "structure work kind units exclude label")


def spec(label, structure=None, work="UNKNOWN", kind="OTHER", units=None,
         exclude=None):
    return CodeSpec(structure, work, kind, units, exclude, label)

# A BPS structure code standing as its own token. "C-1000" and "C-1001" do not
# match because the digits continue; "R- 435" and "R- 329" do not match because
# they are not in the range.
BPS_CODE = re.compile(r"(?<!\d)(10[1-5])(?!\d)")

STRUCTURE_KEYWORDS = (
    # (pattern, structure_type, rule). Ordered most specific first: "two
    # family" must beat "family", and "five or more" must beat "more".
    (r"five or more|5\+ *(unit|famil)|multi[- ]?family|apartment|apt\b",
     emit.FIVE_PLUS, "kw:multifamily"),
    (r"three *(&|and) *four|3 *(&|and|-) *4 *famil|triplex|fourplex|quadplex",
     emit.THREE_FOUR, "kw:three-four"),
    (r"two *famil|duplex|2 *famil", emit.TWO_FAMILY, "kw:two-family"),
    (r"secondary apartment|accessory dwelling|\badu\b|townhou?se|row ?house",
     emit.SF_ATTACHED, "kw:attached"),
    (r"single ?famil|one ?famil|\bsfr\b|\bsfd\b|detached dwelling",
     emit.SF_DETACHED, "kw:single-family"),
)

WORK_KEYWORDS = (
    (r"\bdemoli|\bdemo\b|\braze\b", "DEMOLITION", "kw:demolition"),
    (r"\bnew\b|new structure|new construction", "NEW", "kw:new"),
    (r"\baddition\b|\baddn\b", "ADDITION", "kw:addition"),
    (r"remodel|renovat|alterat|rehab|repair|replace|upfit|finish ?out|"
     r"tenant|change ?out|upgrade", "ALTERATION", "kw:alteration"),
    # Columbus files 260k records as "1,2,3 Family - Other". That is a real
    # work class, not a failure to classify, and leaving it UNKNOWN made the
    # coverage figure read 4.2% when the mapper was working correctly.
    (r"\bother\b|unspecified", "OTHER", "kw:other"),
)

KIND_KEYWORDS = (
    # Order matters: Austin's permittype codes are two letters, and the words
    # are checked first so "Electrical Permit" does not fall through to OTHER.
    (r"electric", "ELECTRICAL", "kw:electrical"),
    (r"mechanical|\bhvac\b", "MECHANICAL", "kw:mechanical"),
    (r"plumb", "PLUMBING", "kw:plumbing"),
    (r"\bbuilding\b|\bbldg\b|\bbp\b", "BUILDING", "kw:building"),
    (r"\bsign\b|graphics|tree removal|driveway|sidewalk|irrigation|fence|"
     r"tent|festival|\bpool\b|roofing|siding", "OTHER", "kw:not-a-building"),
)

# Austin-style two-letter permittype codes. These are exact matches on a short
# token, never a substring search, because "BP" appears inside plenty of words.
KIND_CODES = {"BP": "BUILDING", "EP": "ELECTRICAL", "MP": "MECHANICAL",
              "PP": "PLUMBING"}


def _first(patterns, text):
    low = text.lower()
    for pat, val, rule in patterns:
        if re.search(pat, low):
            return val, rule
    return None, None


class Vocabulary(object):
    """Per-source mapping with an unmapped-string tally.

    The tally is the point. A classifier that returns UNKNOWN for 40% of a
    jurisdiction's records has not classified that jurisdiction, and the only
    way to know is to keep the strings it failed on and count them.
    """

    def __init__(self, source_id, platform, default_kind=None,
                 code_table=None):
        """`default_kind` is a source-level declaration, and it is the right
        place for this fact rather than a per-record classification.

        Charlotte, Columbus, Nashville and Seattle each publish a dataset that
        contains building permits and nothing else; there is no per-record
        string to classify because the whole file is one kind. Austin is the
        opposite - one dataset carrying BP/EP/MP/PP together - and that is
        exactly why it produced a 4x overcount. So: declare the scope once per
        source when it is known, fall back to per-record classification when it
        is not. This is D6's amortization applied to permit kind.
        """
        self.source_id = source_id
        self.platform = platform
        self.default_kind = default_kind
        self.code_table = code_table or {}
        self.unmapped = {}
        self.rules_fired = {}

    # -- a source's own published code table -----------------------------
    def by_code(self, code):
        """(CodeSpec, rule) for a code this source publishes a legend for.

        Returns (None, None) for an unrecognized code and tallies it, which is
        the point: a jurisdiction that adds a code mid-year shows up as a
        rising unmapped count rather than as records quietly classified
        UNKNOWN. Codes are matched exactly and case-insensitively, never as a
        prefix - St. Johns has both 329 (swimming pool) and 329E (pool
        enclosure), and 435 (residential roof) and 435C (commercial roof), so
        a prefix match would silently merge a code with its own variants.
        """
        if not code:
            return None, None
        k = str(code).strip().upper()
        s = self.code_table.get(k)
        if s is None:
            self._miss("code", k)
            return None, None
        rule = "code:%s" % k
        self._hit(rule)
        return s, rule

    def _miss(self, axis, text):
        k = "%s: %s" % (axis, (text or "")[:70])
        self.unmapped[k] = self.unmapped.get(k, 0) + 1

    def _hit(self, rule):
        self.rules_fired[rule] = self.rules_fired.get(rule, 0) + 1

    # -- structure -------------------------------------------------------
    def structure(self, *natives):
        """Structure class from any of several native strings.

        Several because jurisdictions split the signal: Columbus carries it in
        `GENERAL_TYPE`, Austin in `permit_class`, Nashville in a subtype
        description. The first string that yields a code wins.
        """
        text = " | ".join(n for n in natives if n)
        if not text:
            return None, None
        m = BPS_CODE.search(text)
        if m:
            self._hit("bps-code")
            return m.group(1), "bps-code"
        # Columbus's "1,2,3 Family" spans 101-104 and cannot be split further.
        # Returning SF_DETACHED would be a fabrication; the honest answer is a
        # low-density marker the reconciler can group but not itemize.
        # Combined classes that span several BPS codes. Seattle's
        # "Single Family/Duplex" is 101 and 103 together; Columbus's
        # "1,2,3 Family" is 101 through 104; Charlotte's "One/Two Family" is
        # 101 and 103. A keyword match picks whichever word appears first and
        # is wrong for the rest, so these are marked as a bundle and refined
        # by unit count below rather than guessed at here.
        if re.search(r"1 *, *2 *, *3 *famil|one.?two.?three famil|"
                     r"one/two famil|single ?family ?/ ?duplex|"
                     r"sf ?/ ?duplex", text.lower()):
            self._hit("kw:low-density-bundle")
            return emit.LOW_BUNDLE, "kw:low-density-bundle"
        v, rule = _first(STRUCTURE_KEYWORDS, text)
        if v:
            self._hit(rule)
            return v, rule
        self._miss("structure", text)
        return None, None

    # -- work class ------------------------------------------------------
    def work(self, *natives):
        text = " | ".join(n for n in natives if n)
        if not text:
            return "UNKNOWN", None
        v, rule = _first(WORK_KEYWORDS, text)
        if v:
            self._hit(rule)
            return v, rule
        self._miss("work", text)
        return "UNKNOWN", None

    # -- permit kind -----------------------------------------------------
    def kind(self, *natives):
        """Which trade this permit is, which decides whether it carries units.

        Returns UNKNOWN rather than assuming BUILDING. UNKNOWN contributes zero
        units (see `emit.countable_units`), so the failure mode is an
        undercount that shows up in reconciliation, not the silent 4x overcount
        Austin produced.
        """
        if self.default_kind and not any(
                n and str(n).strip().upper() in KIND_CODES for n in natives):
            self._hit("source-declared:%s" % self.default_kind)
            return self.default_kind, "source-declared"
        for n in natives:
            if n and str(n).strip().upper() in KIND_CODES:
                v = KIND_CODES[str(n).strip().upper()]
                self._hit("code:%s" % str(n).strip().upper())
                return v, "code"
        text = " | ".join(n for n in natives if n)
        if not text:
            return "UNKNOWN", None
        v, rule = _first(KIND_KEYWORDS, text)
        if v:
            self._hit(rule)
            return v, rule
        self._miss("kind", text)
        return "UNKNOWN", None

    # -- refinement by unit count ----------------------------------------
    def refine(self, structure_type, units, work_class):
        """Sharpen a structure class using the record's own unit count.

        The BPS structure classes *are* unit-count bands - 1 unit, 2 units,
        3-4, 5 or more - so for a new building with a definite count the count
        is better evidence than any string. This turns Seattle's combined
        "Single Family/Duplex" class into the right column per record instead
        of assigning all 294 of them to two-family on a keyword.

        Deliberately narrow, because one permit can cover several buildings: a
        single permit for ten detached houses carries ten units but is ten
        1-unit structures, not one 10-unit structure. So refinement only ever
        runs **within** a family the text already established - it sharpens a
        low-density bundle and it splits 3-4 out of a multifamily class, and it
        never promotes a low-density record into 5+ on unit count alone.
        """
        if work_class != "NEW" or units is None or units <= 0:
            return structure_type, None
        if structure_type == emit.LOW_BUNDLE:
            if units == 1:
                v = emit.SF_DETACHED
            elif units == 2:
                v = emit.TWO_FAMILY
            elif units <= 4:
                v = emit.THREE_FOUR
            else:
                # More units than the bundle's own class allows. Trust the
                # count only as far as saying it is not a single dwelling;
                # 3-4 is the highest band the bundle can justify.
                v = emit.THREE_FOUR
            self._hit("refine:bundle-by-units")
            return v, "refine:bundle-by-units"
        if structure_type == emit.FIVE_PLUS and units <= 4:
            self._hit("refine:multifamily-down-to-3-4")
            return (emit.THREE_FOUR if units >= 3 else
                    (emit.TWO_FAMILY if units == 2 else emit.SF_DETACHED),
                    "refine:multifamily-down")
        return structure_type, None

    # -- units implied by the structure class ----------------------------
    # Rules whose output is trustworthy enough to imply a count. The test is
    # not "did we get a structure type" but "did we get it from a statement
    # about what kind of building this is". `bps-code` and the single-family,
    # attached and two-family keyword rules all are. Everything else is not:
    #   kw:three-four        3 or 4 - names no number
    #   kw:multifamily       5 or more - names no number
    #   kw:low-density-bundle spans 101-104 - names no number
    #   refine:*             derived FROM a unit count; implying one back
    #                        would be circular
    IMPLY_RULES = frozenset(("bps-code", "kw:single-family", "kw:attached",
                             "kw:two-family"))

    def imply_units(self, structure_type, work_class, structure_rule,
                    controlled):
        """(units, rule) when the structure class definitionally names a count.

        `controlled` is the caller's declaration that the string the class came
        from is a controlled vocabulary field - a type column, a BPS class code
        column - and not operator free text. It is not optional and not
        inferable here, because the one time free text reached these
        classifiers it produced 43 Clark County records typed as 101 from
        `bps-code` matching a lot number: "LOT 101" is not single-family
        detached. A rule name alone cannot tell those apart; only the caller
        knows which field it read.

        Returns (None, reason) rather than raising, so a refusal is recorded
        in the same tally as a miss instead of disappearing.
        """
        if not controlled:
            return None, "refused:uncontrolled-field"
        if work_class != "NEW":
            # An alteration to a single-family house is not one new dwelling.
            return None, "refused:not-new"
        if structure_rule not in self.IMPLY_RULES:
            return None, "refused:rule-not-determinate"
        n = emit.IMPLIED_UNITS.get(structure_type)
        if n is None:
            return None, "refused:class-not-determinate"
        rule = "imply:%s-from-%s" % (n, structure_type)
        self._hit(rule)
        return n, rule

    # -- units from free text --------------------------------------------
    UNIT_TEXT = (
        (r"(\d+)\s*(?:or more)?\s*unit", 1),
        (r">\s*(\d+)\s*unit", 1),
    )

    def units_from_text(self, text):
        """Recover a unit count from a description, or None.

        Nashville's only unit signal is a string like "Multifamily, Apt /
        Twnhome > 5 Unit Bldg". That parses to "at least 5", which is **not** a
        unit count and must not be returned as one - "> 5" summed as 5 would
        understate a 200-unit building by 40x. So this returns a count only
        when the string states an exact number, and refuses on open-ended
        ranges. Refusing is the correct behaviour: it keeps the record's
        `unit_count_source` at `absent`, which excludes it from the
        reconciliation instead of poisoning it.
        """
        if not text:
            return None, None
        low = text.lower()
        if re.search(r">\s*\d+\s*unit|\d+\s*\+\s*unit|or more", low):
            self._miss("units:open-ended-range", text)
            return None, "refused:open-ended"
        m = re.search(r"(\d+)\s*unit", low)
        if m:
            self._hit("units:exact-from-text")
            return int(m.group(1)), "units:exact-from-text"
        return None, None

    def report(self):
        return {"source_id": self.source_id, "platform": self.platform,
                "rules_fired": dict(sorted(self.rules_fired.items(),
                                           key=lambda kv: -kv[1])),
                "unmapped": dict(sorted(self.unmapped.items(),
                                        key=lambda kv: -kv[1])[:40]),
                "unmapped_total": sum(self.unmapped.values())}
