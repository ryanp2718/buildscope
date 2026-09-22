# -*- coding: utf-8 -*-
"""The step-1 source registry: one entry per publisher dataset.

Identity is D3's `(state_fips, bps_id)` throughout - never a name, never a FIPS
place. `Mecklenburg County NC` is the office that files for Charlotte, and the
dataset is published by the City of Charlotte; the office is what the record
belongs to, and conflating the two is claim 3c.

**Every field name here is verified against the live schema before any pull.**
`data/spike_b/schema.json` is not authoritative: it holds the schema of the
*first* Seattle dataset tried (`76t5-zqzr`, which has no date field at all),
not the corrected one, and nothing in the file says so. A stale schema
artifact that looks current is worse than no artifact, so `step1_run.py`
re-probes and refuses to pull a source whose declared fields do not exist.
"""
from .adapters.opendata import Source

SOURCES = [
    Source(
        key="austin", state_fips="48", bps_id="033000", label="Austin TX",
        platform="socrata",
        base="https://data.austintexas.gov/resource/3syk-w9eu.json",
        id_field="permit_number", issued_field="issue_date",
        applied_field="applieddate", units_field="housing_units",
        structure_fields=("permit_class", "permit_class_mapped"),
        work_fields=("work_class",),
        kind_fields=("permittype",),
        # No default_kind, deliberately. Austin's single dataset carries
        # Building, Electrical, Mechanical and Plumbing permits together and
        # every one of them has a populated housing_units value. This is the
        # source of the 726% error; it must classify per record.
        default_kind=None,
        desc_fields=("permit_type_desc", "permit_class"),
        address_field="original_address1",
        note="sub-permits present; permittype must be classified per record"),

    Source(
        key="seattle", state_fips="53", bps_id="475000", label="Seattle WA",
        platform="socrata",
        base="https://data.seattle.gov/resource/8tqq-u7ib.json",
        id_field="permitnum", issued_field="issueddate",
        applied_field="applieddate", units_field="housingunits",
        structure_fields=("permitclass", "permitclassmapped"),
        work_fields=("permittypedesc",),
        kind_fields=("permittypedesc",),
        # Seattle publishes housingunits, housingunitsadded and
        # housingunitsremoved. BPS counts units *authorized*, which is what
        # "added" names; Spike B used "housingunits" without knowing the other
        # two existed. Both are carried so the reconciler can score each and
        # the choice is settled by measurement rather than by assumption.
        alt_units_field="housingunitsadded",
        default_kind="BUILDING",
        desc_fields=("description", "permitclass"),
        address_field="originaladdress1",
        note="corrected dataset 8tqq-u7ib; schema.json holds the stale one"),

    Source(
        key="charlotte", state_fips="37", bps_id="379000",
        label="Mecklenburg County NC", platform="arcgis",
        base="https://meckgis.mecklenburgcountync.gov/server/rest/services/"
             "BuildingPermits/FeatureServer/0",
        id_field="permitnum", issued_field="issuedate",
        applied_field=None, units_field="numunits",
        # typeofbldg is a field Spike B never used. permittype only offers
        # "One/Two Family" vs "Commercial", and apartment buildings are filed
        # under Commercial - so permittype alone cannot see multifamily at all.
        structure_fields=("typeofbldg", "permittype"),
        work_fields=("worktype",),
        kind_fields=("permittype",),
        default_kind="BUILDING",
        desc_fields=("permitdesc", "workdesc"),
        address_field=None,
        note="worktype blank in all Q1 2026 records - the drift alarm case"),

    Source(
        key="columbus", state_fips="39", bps_id="135700", label="Columbus OH",
        platform="arcgis",
        base="https://services1.arcgis.com/9yy6msODkIBzkUXU/arcgis/rest/"
             "services/Building_Permits/FeatureServer/0",
        id_field="B1_ALT_ID", issued_field="ISSUED_DT",
        applied_field=None, units_field="UNITS",
        structure_fields=("GENERAL_TYPE", "B1_PER_TYPE", "B1_PER_SUB_TYPE"),
        work_fields=("GENERAL_TYPE",),
        kind_fields=("B1_PER_TYPE",),
        default_kind="BUILDING",
        desc_fields=("GENERAL_TYPE", "VALUE_DESC"),
        address_field="SITE_ADDRESS",
        note="'1,2,3 Family' spans BPS 101-104 and cannot be itemized"),

    Source(
        key="nashville", state_fips="47", bps_id="605000",
        label="Nashville-Davidson TN", platform="arcgis",
        base="https://services2.arcgis.com/HdTo6HJqh92wn4D8/arcgis/rest/"
             "services/Building_Permits_Issued_2/FeatureServer/0",
        id_field="Permit__", issued_field="Date_Issued",
        applied_field="Date_Entered", units_field=None,
        structure_fields=("Permit_Subtype_Description",
                          "Permit_Type_Description"),
        work_fields=("Permit_Type_Description",),
        kind_fields=("Permit_Type_Description",),
        default_kind="BUILDING",
        desc_fields=("Permit_Subtype_Description", "Purpose"),
        address_field="Address",
        note="no unit field; units only in free text, ranges are refused"),
]

BY_KEY = {s.key: s for s in SOURCES}
