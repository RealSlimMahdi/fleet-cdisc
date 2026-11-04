"""StudyDesign aggregate, TDD audit, and TS-seeding tests."""

from __future__ import annotations

import polars as pl
import pytest

import fleet  # noqa: F401 — registers the .sdtm namespace
from fleet.sdtm.design import StudyDesign
from fleet.sdtm.tdd import TrialVisits, _ctgov_to_parameters
from fleet.sdtm.tdd_audit import audit


@pytest.fixture
def design() -> StudyDesign:
    return StudyDesign(
        study_id="CDISCPILOT01",
        elements=[
            {
                "etcd": "SCRN",
                "element": "Screening",
                "tedur": "P14D",
                "epoch": "SCREENING",
                "testrl": "INFORMED CONSENT",
                "teenrl": "RANDOMIZATION - 1",
            },
            {
                "etcd": "PBO",
                "element": "Placebo Treatment",
                "tedur": "P84D",
                "epoch": "TREATMENT",
                "testrl": "RANDOMIZATION",
            },
            {
                "etcd": "XANLO",
                "element": "Xanomeline Low Dose",
                "tedur": "P84D",
                "epoch": "TREATMENT",
                "testrl": "RANDOMIZATION",
            },
            {
                "etcd": "FU",
                "element": "Follow-up",
                "tedur": "P28D",
                "epoch": "FOLLOW-UP",
                "testrl": "END OF TREATMENT + 1",
            },
        ],
        arms={"PBO": ["SCRN", "PBO", "FU"], "XAN_LO": ["SCRN", "XANLO", "FU"]},
        arm_names={"PBO": "Placebo", "XAN_LO": "Xanomeline Low Dose"},
        visits=[
            {"visitnum": 1, "visit": "Screening", "visitdy": -14},
            {"visitnum": 2, "visit": "Baseline", "visitdy": 1},
        ],
        parameters=[{"tsparmcd": "TITLE", "tsparm": "Trial Title", "tsval": "Demo"}],
    )


class TestStudyDesignValidation:
    def test_arm_referencing_unknown_element_rejected(self):
        with pytest.raises(ValueError, match="undefined elements"):
            StudyDesign(
                study_id="S1",
                elements=[{"etcd": "SCRN", "element": "Screening", "epoch": "SCREENING"}],
                arms={"PBO": ["SCRN", "NOPE"]},
            )

    def test_empty_arm_path_rejected(self):
        with pytest.raises(ValueError, match="empty element path"):
            StudyDesign(study_id="S1", elements=[], arms={"PBO": []})

    def test_visit_referencing_unknown_arm_rejected(self):
        with pytest.raises(ValueError, match="undefined arm"):
            StudyDesign(
                study_id="S1",
                elements=[{"etcd": "SCRN", "element": "Screening", "epoch": "SCREENING"}],
                arms={"PBO": ["SCRN"]},
                visits=[{"visitnum": 1, "visit": "V1", "armcd": "GHOST"}],
            )


class TestStudyDesignDerivation:
    def test_ta_derives_order_element_epoch(self, design):
        ta = design.to_ta()
        pbo = ta.filter(pl.col("ARMCD") == "PBO")
        assert pbo["TAETORD"].to_list() == [1, 2, 3]
        assert pbo["ELEMENT"].to_list() == ["Screening", "Placebo Treatment", "Follow-up"]
        assert pbo["EPOCH"].to_list() == ["SCREENING", "TREATMENT", "FOLLOW-UP"]

    def test_tabranch_rendered_at_branch_point(self, design):
        ta = design.to_ta()
        branch = ta.filter(pl.col("TABRANCH") != "")
        assert branch["ETCD"].to_list() == ["SCRN", "SCRN"]
        assert "Randomized to Placebo" in branch["TABRANCH"].to_list()

    def test_no_tabranch_when_paths_identical(self, design):
        same = StudyDesign(
            study_id="S1",
            elements=[e.model_dump() for e in design.elements],
            arms={"A": ["SCRN", "FU"], "B": ["SCRN", "FU"]},
        )
        assert (same.to_ta()["TABRANCH"] == "").all()

    def test_te_has_no_epoch_column(self, design):
        assert "EPOCH" not in design.to_te().columns

    def test_domains_skips_empty_sections(self, design):
        frames = design.domains()
        assert set(frames) == {"TE", "TA", "TV", "TS"}
        assert frames["TE"].columns[:2] == ["STUDYID", "DOMAIN"]

    def test_mermaid_round_trip(self, design):
        text = design.to_mermaid()
        parsed = StudyDesign.from_mermaid(text, study_id=design.study_id)
        assert parsed.arms == design.arms
        assert {e.etcd for e in parsed.elements} == {e.etcd for e in design.elements}

    def test_yaml_round_trip(self, design, tmp_path):
        path = tmp_path / "trial_design.yaml"
        design.to_yaml(path)
        loaded = StudyDesign.from_yaml(path)
        assert loaded == design


class TestAudit:
    def test_clean_design_audits_clean_except_ts_profile(self, design):
        findings = design.audit()
        # Only the TS FDA-profile gaps should fire on a structurally sound design.
        assert set(findings["domain"].to_list()) == {"TS"}

    def test_taetord_not_unique_within_arm(self):
        ta = pl.from_repr("""
┌───────┬─────────┬─────────┬──────┬───────────┐
│ ARMCD ┆ ARM     ┆ TAETORD ┆ ETCD ┆ ELEMENT   │
│ ---   ┆ ---     ┆ ---     ┆ ---  ┆ ---       │
│ str   ┆ str     ┆ i64     ┆ str  ┆ str       │
╞═══════╪═════════╪═════════╪══════╪═══════════╡
│ PBO   ┆ Placebo ┆ 1       ┆ SCRN ┆ Screening │
│ PBO   ┆ Placebo ┆ 1       ┆ TRT  ┆ Treatment │
└───────┴─────────┴─────────┴──────┴───────────┘
""")
        findings = audit(ta=ta)
        assert "SD1052" in findings["rule_id"].to_list()

    def test_ta_element_mismatch_against_te(self):
        te = pl.from_repr("""
┌──────┬───────────┬────────┬────────┬───────┐
│ ETCD ┆ ELEMENT   ┆ TESTRL ┆ TEENRL ┆ TEDUR │
│ ---  ┆ ---       ┆ ---    ┆ ---    ┆ ---   │
│ str  ┆ str       ┆ str    ┆ str    ┆ str   │
╞══════╪═══════════╪════════╪════════╪═══════╡
│ SCRN ┆ Screening ┆ IC     ┆ RAND   ┆ P14D  │
└──────┴───────────┴────────┴────────┴───────┘
""")
        ta = pl.from_repr("""
┌───────┬─────────┬─────────┬──────┬─────────────┐
│ ARMCD ┆ ARM     ┆ TAETORD ┆ ETCD ┆ ELEMENT     │
│ ---   ┆ ---     ┆ ---     ┆ ---  ┆ ---         │
│ str   ┆ str     ┆ i64     ┆ str  ┆ str         │
╞═══════╪═════════╪═════════╪══════╪═════════════╡
│ PBO   ┆ Placebo ┆ 1       ┆ SCRN ┆ Different!  │
└───────┴─────────┴─────────┴──────┴─────────────┘
""")
        rule_ids = audit(te=te, ta=ta)["rule_id"].to_list()
        assert "SD0067" in rule_ids

    def test_reserved_armcd_flagged(self):
        ta = pl.from_repr("""
┌──────────┬──────────────┬─────────┬──────┬───────────┐
│ ARMCD    ┆ ARM          ┆ TAETORD ┆ ETCD ┆ ELEMENT   │
│ ---      ┆ ---          ┆ ---     ┆ ---  ┆ ---       │
│ str      ┆ str          ┆ i64     ┆ str  ┆ str       │
╞══════════╪══════════════╪═════════╪══════╪═══════════╡
│ SCRNFAIL ┆ Screen Fail  ┆ 1       ┆ SCRN ┆ Screening │
└──────────┴──────────────┴─────────┴──────┴───────────┘
""")
        assert "SD1053" in audit(ta=ta)["rule_id"].to_list()

    def test_element_without_end_rule_or_duration(self):
        te = pl.from_repr("""
┌──────┬───────────┬────────┬────────┬───────┐
│ ETCD ┆ ELEMENT   ┆ TESTRL ┆ TEENRL ┆ TEDUR │
│ ---  ┆ ---       ┆ ---    ┆ ---    ┆ ---   │
│ str  ┆ str       ┆ str    ┆ str    ┆ str   │
╞══════╪═══════════╪════════╪════════╪═══════╡
│ SCRN ┆ Screening ┆ IC     ┆        ┆       │
└──────┴───────────┴────────┴────────┴───────┘
""")
        assert "SD0089" in audit(te=te)["rule_id"].to_list()

    def test_ts_conditional_rules(self):
        ts = pl.from_repr("""
┌───────┬──────────┬────────────┬────────────────┐
│ TSSEQ ┆ TSPARMCD ┆ TSPARM     ┆ TSVAL          │
│ ---   ┆ ---      ┆ ---        ┆ ---            │
│ i64   ┆ str      ┆ str        ┆ str            │
╞═══════╪══════════╪════════════╪════════════════╡
│ 1     ┆ STYPE    ┆ Study Type ┆ INTERVENTIONAL │
│ 1     ┆ ADDON    ┆ Added on   ┆ Y              │
└───────┴──────────┴────────────┴────────────────┘
""")
        rule_ids = audit(ts=ts)["rule_id"].to_list()
        assert {"SD1310", "SD1311", "SD1312", "SD2216"}.issubset(rule_ids)
        assert "SD2232" in rule_ids  # SSTDTC missing → rejection-level

    def test_dm_cross_check(self, design):
        dm = pl.from_repr("""
┌─────────────┬──────────┐
│ USUBJID     ┆ ARMCD    │
│ ---         ┆ ---      │
│ str         ┆ str      │
╞═════════════╪══════════╡
│ 01-701-1015 ┆ PBO      │
│ 01-701-1023 ┆ GHOST    │
│ 01-701-1028 ┆ SCRNFAIL │
└─────────────┴──────────┘
""")
        findings = design.audit(dm=dm)
        rule_ids = findings["rule_id"].to_list()
        assert "FLEETTD02" in rule_ids  # GHOST not defined in TA
        assert "SD1354" in rule_ids  # XAN_LO has no subjects


class TestVisitSchedule:
    def test_from_schedule_orders_and_day_convention(self):
        tv = TrialVisits.from_schedule(
            [("Week 4", 28), ("Screening", -14), ("Baseline", 0)],
            anchor="RANDOMIZATION",
            window=3,
        )
        df = tv.to_polars()
        assert df["VISITNUM"].to_list() == [1, 2, 3]
        assert df["VISIT"].to_list() == ["Screening", "Baseline", "Week 4"]
        # CDISC no-day-zero: offset 0 → day 1, negatives unchanged
        assert df["VISITDY"].to_list() == [-14, 1, 29]
        # c1-222: the window counts study days, as visit_map does
        assert df["TVSTRL"].to_list() == [
            "14 days before RANDOMIZATION; window -3/+3 study days, no Day 0",
            "On day of RANDOMIZATION; window -3/+3 study days, no Day 0",
            "28 days after RANDOMIZATION; window -3/+3 study days, no Day 0",
        ]


class TestCtgovSeeding:
    def test_mapping_from_ctgov_record(self):
        record = {
            "protocolSection": {
                "identificationModule": {"nctId": "NCT00000000", "briefTitle": "Demo"},
                "statusModule": {
                    "overallStatus": "COMPLETED",
                    "startDateStruct": {"date": "2014-01-01"},
                    "completionDateStruct": {"date": "2015-06-30"},
                },
                "designModule": {
                    "studyType": "INTERVENTIONAL",
                    "phases": ["PHASE3"],
                    "designInfo": {
                        "interventionModel": "PARALLEL",
                        "allocation": "RANDOMIZED",
                        "maskingInfo": {"masking": "DOUBLE"},
                    },
                    "enrollmentInfo": {"count": 300},
                },
                "eligibilityModule": {
                    "minimumAge": "50 Years",
                    "maximumAge": "80 Years",
                    "sex": "ALL",
                    "healthyVolunteers": False,
                },
                "armsInterventionsModule": {"armGroups": [{}, {}]},
                "outcomesModule": {
                    "primaryOutcomes": [{"measure": "ADAS-Cog"}, {"measure": "CIBIC+"}]
                },
                "contactsLocationsModule": {
                    "locations": [{"country": "United States"}, {"country": "United States"}]
                },
                "sponsorCollaboratorsModule": {"leadSponsor": {"name": "CDISC"}},
            }
        }
        rows = _ctgov_to_parameters(record)
        by_code = {(r.tsparmcd, r.tsseq): r.tsval for r in rows}
        assert by_code[("REGID", 1)] == "NCT00000000"
        assert by_code[("TPHASE", 1)] == "PHASE III TRIAL"
        assert by_code[("RANDOM", 1)] == "Y"
        assert by_code[("TBLIND", 1)] == "DOUBLE BLIND"
        assert by_code[("AGEMIN", 1)] == "P50Y"
        assert by_code[("SEXPOP", 1)] == "BOTH"
        assert by_code[("HLTSUBJI", 1)] == "N"
        assert by_code[("SENDTC", 1)] == "2015-06-30"
        assert by_code[("NARMS", 1)] == "2"
        assert by_code[("OUTMSPRI", 2)] == "CIBIC+"
        assert by_code[("FCNTRY", 1)] == "United States"


class TestUsdmImport:
    def test_structural_subset(self):
        usdm = {
            "study": {
                "name": "DEMO",
                "versions": [
                    {
                        "studyIdentifiers": [{"studyIdentifier": "CDISCPILOT01"}],
                        "studyDesigns": [
                            {
                                "arms": [
                                    {"id": "a1", "name": "Placebo"},
                                    {"id": "a2", "name": "Xanomeline Low"},
                                ],
                                "epochs": [
                                    {"id": "ep1", "name": "Screening"},
                                    {"id": "ep2", "name": "Treatment"},
                                ],
                                "elements": [
                                    {"id": "el1", "name": "Screening"},
                                    {
                                        "id": "el2",
                                        "name": "Placebo Dosing",
                                        "transitionStartRule": {"text": "RANDOMIZATION"},
                                    },
                                    {"id": "el3", "name": "Xano Dosing"},
                                ],
                                "studyCells": [
                                    {"armId": "a1", "epochId": "ep1", "elementIds": ["el1"]},
                                    {"armId": "a2", "epochId": "ep1", "elementIds": ["el1"]},
                                    {"armId": "a1", "epochId": "ep2", "elementIds": ["el2"]},
                                    {"armId": "a2", "epochId": "ep2", "elementIds": ["el3"]},
                                ],
                                "encounters": [{"name": "Visit 1"}, {"name": "Visit 2"}],
                                "eligibilityCriteria": [
                                    {
                                        "identifier": "INCL01",
                                        "text": "Age 50-80",
                                        "category": {"decode": "Inclusion Criteria"},
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        }
        design = StudyDesign.from_usdm(usdm)
        assert design.study_id == "CDISCPILOT01"
        assert len(design.arms) == 2
        assert all(len(path) == 2 for path in design.arms.values())
        assert design.elements[1].testrl == "RANDOMIZATION"
        assert design.elements[0].epoch == "SCREENING"
        assert [v.visit for v in design.visits] == ["Visit 1", "Visit 2"]
        assert design.criteria[0].iecat == "INCLUSION"
        # The imported design derives valid domains end to end.
        assert set(design.domains()) >= {"TE", "TA"}


class TestEpochFromSE:
    def test_epoch_stamped_from_subject_elements(self):
        se = pl.from_repr("""
┌─────────┬────────────┬────────────┬───────────┐
│ USUBJID ┆ SESTDTC    ┆ SEENDTC    ┆ EPOCH     │
│ ---     ┆ ---        ┆ ---        ┆ ---       │
│ str     ┆ str        ┆ str        ┆ str       │
╞═════════╪════════════╪════════════╪═══════════╡
│ 001     ┆ 2014-01-01 ┆ 2014-01-14 ┆ SCREENING │
│ 001     ┆ 2014-01-15 ┆ null       ┆ TREATMENT │
└─────────┴────────────┴────────────┴───────────┘
""")
        ae = pl.from_repr("""
┌─────────┬────────────┐
│ USUBJID ┆ AESTDTC    │
│ ---     ┆ ---        │
│ str     ┆ str        │
╞═════════╪════════════╡
│ 001     ┆ 2014-01-05 │
│ 001     ┆ 2014-02-01 │
│ 002     ┆ 2014-01-05 │
└─────────┴────────────┘
""")
        result = ae.sdtm.epoch_assign("EPOCH", date_col="AESTDTC", se=se).to_frame()
        assert result["EPOCH"].to_list() == ["SCREENING", "TREATMENT", None]

    def test_requires_exactly_one_source(self):
        df = pl.from_repr("""\
┌────────────┐
│ DTC        │
│ ---        │
│ str        │
╞════════════╡
│ 2014-01-01 │
└────────────┘
""")
        with pytest.raises(ValueError, match="exactly one"):
            df.sdtm.epoch_assign("EPOCH", date_col="DTC")


def test_audit_flags_ts_profile_even_without_parameters_section():
    """A design with no TS section still gets the FDA profile findings —
    a missing TS dataset is the rejection-level case, not a skip."""
    design = StudyDesign(
        study_id="S1",
        elements=[
            {
                "etcd": "SCRN",
                "element": "Screening",
                "epoch": "SCREENING",
                "teenrl": "RANDOMIZATION",
            }
        ],
        arms={"A1": ["SCRN"]},
    )
    findings = design.audit()
    rule_ids = findings["rule_id"].to_list()
    assert "SD2213" in rule_ids  # TITLE missing
    assert "SD2232" in rule_ids  # SSTDTC missing (rejection criterion 1734)
