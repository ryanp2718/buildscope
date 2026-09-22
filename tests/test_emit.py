# -*- coding: utf-8 -*-
"""The emit contract: the rules that stand between a pull and a wrong number.

Every assertion here is descended from a specific measured failure:

  `countable_units`     Austin issues Electrical, Mechanical and Plumbing
                        sub-permits alongside each Building permit and **every
                        one carries a populated `housing_units` value**.
                        Summing naively counted dwellings up to four times:
                        **726% error** against BPS.
  `unit_count_source`   Nashville publishes no unit field at all. "0 units" and
                        "this source has no unit field" collapsing into the same
                        integer zeroes out a jurisdiction silently.
  `implied_by_...`      104 is "three OR four" and 105 is "five or more".
                        Neither names a number. Picking one is the free-text
                        guess that manufactured the false Nashville figure.
  `MissingIdentifier`   the only EmitError an adapter may count and continue
                        past, because it is a property of the source data
                        rather than a bug in the adapter.
  `bps_id` as TEXT      Clark County NV is `021000`. As an integer it is 21000
                        and it is a different county.
"""
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from permits import emit                                # noqa: E402


def rec(**kw):
    kw.setdefault("source_id", "test")
    kw.setdefault("state_fips", "12")
    kw.setdefault("bps_id", "803000")
    kw.setdefault("native_id", "B26-0001")
    kw.setdefault("platform", "test")
    kw.setdefault("extractor_version", "test/1.0")
    return emit.PermitRecord(**kw)


class TestIdentity(unittest.TestCase):

    def test_missing_native_id_is_its_own_error(self):
        """Distinguishable by type, not by message text - a synthesized
        extractor at step 4 has to satisfy the same interface."""
        for bad in (None, "", "   "):
            with self.subTest(native_id=bad):
                with self.assertRaises(emit.MissingIdentifier):
                    rec(native_id=bad)
        self.assertTrue(issubclass(emit.MissingIdentifier, emit.EmitError))

    def test_office_identity_is_required(self):
        with self.assertRaises(emit.EmitError):
            rec(state_fips=None)
        with self.assertRaises(emit.EmitError):
            rec(bps_id=None)

    def test_bps_id_stays_text(self):
        """The leading zero is load-bearing. `021000` is Clark County NV."""
        r = rec(state_fips="32", bps_id="021000")
        self.assertEqual(r.bps_id, "021000")
        self.assertIsInstance(r.bps_id, str)
        self.assertEqual(r.as_dict()["bps_id"], "021000")

    def test_state_fips_zero_padded(self):
        self.assertEqual(rec(state_fips="1").state_fips, "01")
        self.assertEqual(rec(state_fips=1).state_fips, "01")

    def test_observation_key_is_deterministic(self):
        """D5: computed at fetch time from (source_id, native_id), never
        inferred and never content-derived in step 1."""
        a, b = rec(), rec()
        self.assertEqual(a.observation_key, b.observation_key)
        self.assertEqual(a.observation_key, "test|B26-0001")
        self.assertNotEqual(rec(native_id="X").observation_key,
                            a.observation_key)


class TestUnits(unittest.TestCase):

    def test_austin_subpermit_trap(self):
        """The 726% error, expressed as code rather than as a filter someone
        has to remember to apply."""
        for kind in ("ELECTRICAL", "MECHANICAL", "PLUMBING", "OTHER",
                     "UNKNOWN"):
            with self.subTest(kind=kind):
                r = rec()
                r.permit_kind = kind
                r.work_class = "NEW"
                r.units(4, "field")
                self.assertEqual(r.countable_units, 0)
        r = rec()
        r.permit_kind = "BUILDING"
        r.work_class = "NEW"
        r.units(4, "field")
        self.assertEqual(r.countable_units, 4)

    def test_only_new_construction_counts(self):
        """BPS counts units *authorized* by new construction. An alteration
        that reports units is not a BPS unit."""
        for wc in ("ADDITION", "ALTERATION", "DEMOLITION", "OTHER", "UNKNOWN"):
            with self.subTest(work_class=wc):
                r = rec()
                r.permit_kind, r.work_class = "BUILDING", wc
                r.units(9, "field")
                self.assertEqual(r.countable_units, 0)

    def test_absent_is_not_zero(self):
        r = rec()
        r.units(None, "absent")
        self.assertIsNone(r.unit_count)
        self.assertEqual(r.unit_count_source, "absent")

        z = rec()
        z.units(0, "field")
        self.assertEqual(z.unit_count, 0)
        self.assertEqual(z.unit_count_source, "field")
        # The two must be distinguishable downstream, which is the whole point.
        self.assertNotEqual(r.unit_count_source, z.unit_count_source)

    def test_absent_with_a_count_is_rejected(self):
        r = rec()
        r.unit_count_source, r.unit_count = "absent", 3
        with self.assertRaises(emit.EmitError):
            r.validate()

    def test_unit_source_is_not_optional_or_inferable(self):
        with self.assertRaises(emit.EmitError):
            rec().units(1, "guessed")


class TestImpliedUnits(unittest.TestCase):

    def test_determinate_classes_only(self):
        self.assertEqual(emit.IMPLIED_UNITS,
                         {emit.SF_DETACHED: 1, emit.SF_ATTACHED: 1,
                          emit.TWO_FAMILY: 2})

    def test_indeterminate_classes_refused(self):
        """104 is "three OR four", 105 is "five or more", 1-4 spans four
        classes. None of them names a number."""
        for st in (emit.THREE_FOUR, emit.FIVE_PLUS, emit.LOW_BUNDLE):
            with self.subTest(structure=st):
                r = rec()
                r.permit_kind, r.work_class, r.structure_type = \
                    "BUILDING", "NEW", st
                r.units(3, "implied_by_structure_code")
                with self.assertRaises(emit.EmitError):
                    r.validate()

    def test_implied_count_must_match_the_class(self):
        r = rec()
        r.permit_kind, r.work_class = "BUILDING", "NEW"
        r.structure_type = emit.TWO_FAMILY
        r.units(1, "implied_by_structure_code")          # 103 implies 2
        with self.assertRaises(emit.EmitError):
            r.validate()
        r.units(2, "implied_by_structure_code")
        r.validate()

    def test_implied_units_stay_separately_reportable(self):
        """A jurisdiction whose entire unit total is implied has not been
        measured against BPS; it has been derived from the taxonomy BPS counts
        by. The error figure would be close to circular, so the split has to
        survive to the record."""
        r = rec()
        r.permit_kind, r.work_class = "BUILDING", "NEW"
        r.structure_type = emit.SF_DETACHED
        r.units(1, "implied_by_structure_code")
        r.validate()
        self.assertTrue(r.units_implied)
        self.assertEqual(r.countable_units, 1)
        self.assertEqual(r.countable_units_measured, 0)

        m = rec()
        m.permit_kind, m.work_class = "BUILDING", "NEW"
        m.structure_type = emit.SF_DETACHED
        m.units(1, "field")
        m.validate()
        self.assertFalse(m.units_implied)
        self.assertEqual(m.countable_units_measured, 1)


class TestMilestones(unittest.TestCase):

    def test_vocabulary_is_closed(self):
        self.assertEqual(emit.MILESTONES,
                         ("applied", "issued", "finaled", "terminated"))
        with self.assertRaises(emit.EmitError):
            rec().milestone("approved", "2026-03-02")

    def test_absence_is_not_falsity(self):
        """No issuance row means *not observed*, which is not *not issued*."""
        r = rec()
        self.assertIsNone(r.reported("issued"))
        self.assertEqual(r.milestones, [])

    def test_undatable_milestone_is_dropped_not_nulled(self):
        """A milestone row with no date would assert an observation we do not
        have."""
        r = rec().milestone("issued", "not a date")
        self.assertEqual(r.milestones, [])
        r.milestone("issued", "3/2/2026 11:06:49 PM")
        self.assertEqual(r.reported("issued"), "2026-03-02")

    def test_rows_not_booleans(self):
        r = rec().milestone("applied", "2026-01-05").milestone(
            "issued", "2026-03-02")
        self.assertEqual([m["milestone"] for m in r.milestones],
                         ["applied", "issued"])
        self.assertEqual(r.as_dict()["date_applied"], "2026-01-05")
        self.assertEqual(r.as_dict()["date_issued"], "2026-03-02")


class TestValidation(unittest.TestCase):

    def test_closed_vocabularies(self):
        for field, bad in (("permit_kind", "BUILDINGS"),
                           ("work_class", "NEWISH"),
                           ("structure_type", "106")):
            with self.subTest(field=field):
                r = rec()
                setattr(r, field, bad)
                with self.assertRaises(emit.EmitError):
                    r.validate()

    def test_bps_column_mapping(self):
        want = {emit.SF_DETACHED: "u1", emit.SF_ATTACHED: "u1",
                emit.TWO_FAMILY: "u2", emit.THREE_FOUR: "u34",
                emit.FIVE_PLUS: "u5p", emit.LOW_BUNDLE: "low_bundle"}
        self.assertEqual(emit.BPS_COLUMN, want)
        for st, col in want.items():
            r = rec()
            r.structure_type = st
            self.assertEqual(r.bps_column, col)

    def test_low_bundle_is_not_a_bps_column(self):
        """Columbus's "1,2,3 Family" spans 101-104 and is comparable only at
        the low-density aggregate, never per column."""
        self.assertIn("low_bundle", emit.LOW_DENSITY)
        self.assertNotIn(emit.BPS_COLUMN[emit.LOW_BUNDLE], ("u1", "u2", "u34"))

    def test_schema_version_is_emitted(self):
        self.assertEqual(rec().as_dict()["schema_version"], emit.SCHEMA_VERSION)


class TestEmitterAlarm(unittest.TestCase):
    """Section 5's drift alarm. It runs on every record ever emitted, because
    Mecklenburg County abandoned `worktype` mid-dataset - populated 123,262
    times historically, blank in all 500 Q1 2026 records - with no signal."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._n = [0]

    def _good(self):
        self._n[0] += 1
        r = rec(native_id="B26-%05d" % self._n[0])
        r.permit_kind, r.work_class = "BUILDING", "NEW"
        r.structure_type = emit.SF_DETACHED
        r.units(1, "field")
        r.milestone("issued", "2026-03-02")
        return r

    def _run(self, make, n=50):
        """Emit n records and return the closed alarm.

        Uses the context manager because `Emitter` holds an append handle and
        an unclosed one can lose the tail of a run - which would leave the
        manifest claiming pages that produced no records.
        """
        path = os.path.join(self.tmp, "out-%d.jsonl" % len(os.listdir(self.tmp)))
        with emit.Emitter(path, "test") as e:
            for i in range(n):
                make(e, i)
            return e.close()

    def test_empty_emitter_does_not_trip(self):
        a = self._run(lambda e, i: None, n=0)
        self.assertEqual(a["n"], 0)
        self.assertEqual(a["tripped"], [])

    def test_clean_source_does_not_trip_or_qualify(self):
        a = self._run(lambda e, i: e.emit(self._good()))
        self.assertEqual(a["n"], 50)
        self.assertEqual(a["tripped"], [])
        self.assertEqual(a["qualified"], [])

    def test_mecklenburg_unclassifiable_work_class_trips(self):
        def mk(e, i):
            r = self._good()
            r.work_class = "UNKNOWN"
            e.emit(r)
        self.assertTrue(any("work_class" in t
                            for t in self._run(mk)["tripped"]))

    def test_nashville_no_unit_field_trips(self):
        """Recovering 1% of units is not partial coverage; it is a different
        measurement wearing the same units."""
        def mk(e, i):
            r = self._good()
            if i < 99:
                r.units(None, "absent")
            e.emit(r)
        self.assertTrue(any("unit_count" in t
                            for t in self._run(mk, n=100)["tripped"]))

    def test_no_bps_join_possible_trips(self):
        def mk(e, i):
            r = self._good()
            r.structure_type = None
            e.emit(r)
        self.assertTrue(any("structure_type" in t
                            for t in self._run(mk, n=100)["tripped"]))

    def test_wholly_implied_units_qualify_but_do_not_trip(self):
        """The St. Johns case, and the reason `qualified` exists as a separate
        verdict from `tripped`. Every one of its units is implied from a
        published structure class, so the figure may not be quoted bare - but
        the comparison is still between two independent observations and
        suppressing it would discard the only available test of the
        implication rule itself."""
        def mk(e, i):
            r = self._good()
            r.units(1, "implied_by_structure_code")
            e.emit(r)
        a = self._run(mk)
        self.assertEqual(a["tripped"], [])
        self.assertTrue(a["qualified"])
        self.assertIn("implied_by_structure_code", a["qualified"][0])
        self.assertEqual(a["units_total"], a["units_implied"])

    def test_majority_implied_units_qualify(self):
        def mk(e, i):
            r = self._good()
            if i % 2 == 0:
                r.units(1, "implied_by_structure_code")
            e.emit(r)
        a = self._run(mk, n=100)
        self.assertEqual(a["tripped"], [])
        self.assertTrue(a["qualified"])

    def test_qualifying_does_not_weaken_a_blocking_case(self):
        """The check that the tripped/qualified split was principled rather
        than convenient: Clark County has no unit field on 96% of records and
        must still be stopped by the coverage alarm, whatever the implied-units
        verdict says."""
        def mk(e, i):
            r = self._good()
            if i < 96:
                r.units(None, "absent")
            else:
                r.units(1, "implied_by_structure_code")
            e.emit(r)
        a = self._run(mk, n=100)
        self.assertTrue(any("unit_count" in t for t in a["tripped"]))

    def test_rejected_records_are_counted_and_reraised(self):
        path = os.path.join(self.tmp, "rej.jsonl")
        with emit.Emitter(path, "test") as e:
            r = self._good()
            r.permit_kind = "NONSENSE"
            with self.assertRaises(emit.EmitError):
                e.emit(r)
            self.assertEqual(e.rejected, 1)
            self.assertEqual(e.n, 0)

    def test_implied_units_tracked_separately_by_column(self):
        path = os.path.join(self.tmp, "cols.jsonl")
        with emit.Emitter(path, "test") as e:
            for i in range(10):
                r = self._good()
                r.units(1, "implied_by_structure_code")
                e.emit(r)
            for i in range(10):
                e.emit(self._good())
            self.assertEqual(e.by_column["u1"], 20)
            self.assertEqual(e.by_column_implied["u1"], 10)

    def test_records_are_on_disk_after_close(self):
        path = os.path.join(self.tmp, "disk.jsonl")
        with emit.Emitter(path, "test") as e:
            for i in range(5):
                e.emit(self._good())
        with io.open(path, encoding="utf-8") as fh:
            lines = fh.read().strip().splitlines()
        self.assertEqual(len(lines), 5)
        self.assertEqual(json.loads(lines[0])["schema_version"],
                         emit.SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
