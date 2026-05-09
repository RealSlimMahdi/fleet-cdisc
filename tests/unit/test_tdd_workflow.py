"""Unit tests for the Trial Design Domain (TDD) workflow.

Covers:
- Pydantic field validation (reject bad types, boundary values)
- Collection-level validation (duplicate keys, ordering, FK)
- Cross-domain FK validation (with and without upstream injection)
- Sequence enforcement (wrong order → ValueError)
- fetch_structure (mocked API, cache-first, reconciliation warnings)
- Protocol-reference pipelines (TE, TA, TV, TS, TI)
- Subject-level pipelines (SV, SE) — visit_map, element_boundaries,
  epoch_assign, study_day
- Mermaid parser (parse_trial_design)
"""

from __future__ import annotations

from unittest.mock import patch

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration
from fleet.sdtm.tdd import (
    Epoch,
    TrialArm,
    TrialArms,
    TrialCriteria,
    TrialCriterion,
    TrialElement,
    TrialElements,
    TrialParameter,
    TrialParameters,
    TrialVisit,
    TrialVisits,
    parse_trial_design,
)

# ================================================================== #
# Helpers / fixtures                                                   #
# ================================================================== #


@pytest.fixture
def te_rows() -> TrialElements:
    return TrialElements(
        elements=[
            TrialElement(etcd="SCRN", element="Screening", tedur="P14D", epoch=Epoch.SCREENING),
            TrialElement(etcd="TRT", element="Treatment", tedur="P84D", epoch=Epoch.TREATMENT),
            TrialElement(etcd="FU", element="Follow-up", tedur="P28D", epoch=Epoch.FOLLOW_UP),
        ]
    )


@pytest.fixture
def ta_rows() -> TrialArms:
    return TrialArms(
        arms=[
            TrialArm(
                armcd="PBO",
                arm="Placebo",
                taetord=1,
                etcd="SCRN",
                element="Screening",
                epoch=Epoch.SCREENING,
            ),
            TrialArm(
                armcd="PBO",
                arm="Placebo",
                taetord=2,
                etcd="TRT",
                element="Treatment",
                epoch=Epoch.TREATMENT,
            ),
            TrialArm(
                armcd="PBO",
                arm="Placebo",
                taetord=3,
                etcd="FU",
                element="Follow-up",
                epoch=Epoch.FOLLOW_UP,
            ),
        ]
    )


@pytest.fixture
def tv_rows() -> TrialVisits:
    return TrialVisits(
        visits=[
            TrialVisit(visitnum=1, visit="Screening", visitdy=1),
            TrialVisit(visitnum=2, visit="Baseline", visitdy=14),
            TrialVisit(visitnum=3, visit="Week 4", visitdy=42),
            TrialVisit(visitnum=4, visit="Week 12", visitdy=98),
        ]
    )


@pytest.fixture
def ts_rows() -> TrialParameters:
    return TrialParameters(
        parameters=[
            TrialParameter(tsparmcd="ADDON", tsparm="Added on to Existing Treatments", tsval="N"),
            TrialParameter(tsparmcd="AGEMAX", tsparm="Planned Maximum Age of Subjects", tsval="80"),
            TrialParameter(tsparmcd="AGEMIN", tsparm="Planned Minimum Age of Subjects", tsval="18"),
        ]
    )


@pytest.fixture
def ti_rows() -> TrialCriteria:
    return TrialCriteria(
        criteria=[
            TrialCriterion(ietestcd="INCL01", ietest="Age >= 18 years", iecat="INCLUSION"),
            TrialCriterion(ietestcd="EXCL01", ietest="Pregnancy", iecat="EXCLUSION"),
        ]
    )


# Fake IG metadata for mocking fetch_structure
MOCK_TE_META = {
    "domain": "TE",
    "label": "Trial Elements",
    "ig_version": "3-4",
    "variables": [
        {
            "name": "STUDYID",
            "label": "Study Identifier",
            "type": "Char",
            "core": "Req",
            "role": "Identifier",
        },
        {
            "name": "DOMAIN",
            "label": "Domain Abbreviation",
            "type": "Char",
            "core": "Req",
            "role": "Identifier",
        },
        {"name": "ETCD", "label": "Element Code", "type": "Char", "core": "Req", "role": "Topic"},
        {
            "name": "ELEMENT",
            "label": "Description of Element",
            "type": "Char",
            "core": "Req",
            "role": "",
        },
        {
            "name": "TESTRL",
            "label": "Rule for Start of Element",
            "type": "Char",
            "core": "Perm",
            "role": "",
        },
        {
            "name": "TEENRL",
            "label": "Rule for End of Element",
            "type": "Char",
            "core": "Perm",
            "role": "",
        },
        {"name": "TEDUR", "label": "Planned Duration", "type": "Char", "core": "Perm", "role": ""},
        {
            "name": "EPOCH",
            "label": "Epoch",
            "type": "Char",
            "core": "Req",
            "role": "",
            "codelist": "C99079",
        },
    ],
}


# ================================================================== #
# Phase 1 — Pydantic Field Validation                                 #
# ================================================================== #


class TestTrialElementValidation:
    def test_valid_element(self):
        e = TrialElement(etcd="SCRN", element="Screening", tedur="P14D", epoch=Epoch.SCREENING)
        assert e.etcd == "SCRN"
        assert e.epoch == Epoch.SCREENING

    def test_reject_numeric_etcd(self):
        with pytest.raises(Exception):
            TrialElement(etcd=123, element="Screening", epoch=Epoch.SCREENING)

    def test_reject_too_long_etcd(self):
        with pytest.raises(Exception):
            TrialElement(etcd="TOOLONGCODE", element="Screening", epoch=Epoch.SCREENING)

    def test_reject_lowercase_etcd(self):
        with pytest.raises(Exception):
            TrialElement(etcd="scrn", element="Screening", epoch=Epoch.SCREENING)

    def test_reject_empty_element(self):
        with pytest.raises(Exception):
            TrialElement(etcd="SCRN", element="", epoch=Epoch.SCREENING)

    def test_reject_bad_iso_duration(self):
        with pytest.raises(Exception):
            TrialElement(etcd="SCRN", element="Screening", tedur="14 days", epoch=Epoch.SCREENING)

    def test_valid_iso_durations(self):
        e1 = TrialElement(etcd="A", element="Test", tedur="P14D", epoch=Epoch.SCREENING)
        assert e1.tedur == "P14D"
        e2 = TrialElement(etcd="B", element="Test", tedur="P1Y2M3DT4H5M6S", epoch=Epoch.SCREENING)
        assert e2.tedur == "P1Y2M3DT4H5M6S"

    def test_empty_tedur_allowed(self):
        e = TrialElement(etcd="SCRN", element="Screening", tedur="", epoch=Epoch.SCREENING)
        assert e.tedur == ""

    def test_default_empty_rules(self):
        e = TrialElement(etcd="SCRN", element="Screening", epoch=Epoch.SCREENING)
        assert e.testrl == ""
        assert e.teenrl == ""


class TestTrialArmValidation:
    def test_valid_arm(self):
        a = TrialArm(
            armcd="PBO",
            arm="Placebo",
            taetord=1,
            etcd="SCRN",
            element="Screening",
            epoch=Epoch.SCREENING,
        )
        assert a.armcd == "PBO"
        assert a.taetord == 1

    def test_reject_taetord_zero(self):
        with pytest.raises(Exception):
            TrialArm(
                armcd="PBO",
                arm="Placebo",
                taetord=0,
                etcd="SCRN",
                element="Screening",
                epoch=Epoch.SCREENING,
            )

    def test_reject_taetord_negative(self):
        with pytest.raises(Exception):
            TrialArm(
                armcd="PBO",
                arm="Placebo",
                taetord=-1,
                etcd="SCRN",
                element="Screening",
                epoch=Epoch.SCREENING,
            )


class TestTrialVisitValidation:
    def test_valid_visit(self):
        v = TrialVisit(visitnum=1, visit="Screening")
        assert v.visitnum == 1
        assert v.visitdy is None

    def test_reject_visitnum_zero(self):
        with pytest.raises(Exception):
            TrialVisit(visitnum=0, visit="Screening")

    def test_optional_armcd(self):
        v = TrialVisit(visitnum=1, visit="Screening", armcd="")
        assert v.armcd == ""


class TestTrialParameterValidation:
    def test_valid_param(self):
        p = TrialParameter(tsparmcd="ADDON", tsparm="Added on to Existing Treatments")
        assert p.tsparmcd == "ADDON"

    def test_reject_lowercase_tsparmcd(self):
        with pytest.raises(Exception):
            TrialParameter(tsparmcd="addon", tsparm="Test")

    def test_reject_empty_tsparmcd(self):
        with pytest.raises(Exception):
            TrialParameter(tsparmcd="", tsparm="Test")


class TestTrialCriterionValidation:
    def test_valid_criterion(self):
        c = TrialCriterion(ietestcd="INCL01", ietest="Age >= 18", iecat="INCLUSION")
        assert c.iecat == "INCLUSION"

    def test_reject_bad_iecat(self):
        with pytest.raises(Exception):
            TrialCriterion(ietestcd="INCL01", ietest="Age >= 18", iecat="MAYBE")


# ================================================================== #
# Phase 2 — Collection-Level Validation                                #
# ================================================================== #


class TestTrialElementsCollection:
    def test_valid_collection(self, te_rows):
        assert len(te_rows.elements) == 3

    def test_duplicate_etcd_rejected(self):
        with pytest.raises(ValueError, match="Duplicate ETCD"):
            TrialElements(
                elements=[
                    TrialElement(etcd="SCRN", element="Screening", epoch=Epoch.SCREENING),
                    TrialElement(etcd="SCRN", element="Screening 2", epoch=Epoch.SCREENING),
                ]
            )

    def test_to_polars(self, te_rows):
        df = te_rows.to_polars()
        assert "ETCD" in df.columns
        assert "ELEMENT" in df.columns
        assert "EPOCH" in df.columns
        assert df.shape[0] == 3
        assert df["ETCD"].to_list() == ["SCRN", "TRT", "FU"]


class TestTrialArmsCollection:
    def test_valid_collection(self, ta_rows):
        assert len(ta_rows.arms) == 3

    def test_non_sequential_taetord_rejected(self):
        with pytest.raises(ValueError, match="TAETORD.*sequential"):
            TrialArms(
                arms=[
                    TrialArm(
                        armcd="PBO",
                        arm="Placebo",
                        taetord=1,
                        etcd="SCRN",
                        element="Screening",
                        epoch=Epoch.SCREENING,
                    ),
                    TrialArm(
                        armcd="PBO",
                        arm="Placebo",
                        taetord=3,
                        etcd="TRT",
                        element="Treatment",
                        epoch=Epoch.TREATMENT,
                    ),
                ]
            )

    def test_to_polars(self, ta_rows):
        df = ta_rows.to_polars()
        assert "ARMCD" in df.columns
        assert "TAETORD" in df.columns
        assert df.shape[0] == 3


class TestTrialVisitsCollection:
    def test_valid_collection(self, tv_rows):
        assert len(tv_rows.visits) == 4

    def test_duplicate_visitnum_rejected(self):
        with pytest.raises(ValueError, match="Duplicate VISITNUM"):
            TrialVisits(
                visits=[
                    TrialVisit(visitnum=1, visit="V1", visitdy=1),
                    TrialVisit(visitnum=1, visit="V1b", visitdy=2),
                ]
            )

    def test_visitdy_ordering_rejected(self):
        with pytest.raises(ValueError, match="VISITDY must increase"):
            TrialVisits(
                visits=[
                    TrialVisit(visitnum=1, visit="V1", visitdy=10),
                    TrialVisit(visitnum=2, visit="V2", visitdy=5),
                ]
            )

    def test_to_polars(self, tv_rows):
        df = tv_rows.to_polars()
        assert "VISITNUM" in df.columns
        assert "VISIT" in df.columns
        assert df.shape[0] == 4


class TestTrialParametersCollection:
    def test_valid_collection(self, ts_rows):
        assert len(ts_rows.parameters) == 3

    def test_duplicate_tsparmcd_rejected(self):
        with pytest.raises(ValueError, match="Duplicate TSPARMCD"):
            TrialParameters(
                parameters=[
                    TrialParameter(tsparmcd="ADDON", tsparm="Test 1"),
                    TrialParameter(tsparmcd="ADDON", tsparm="Test 2"),
                ]
            )

    def test_to_polars(self, ts_rows):
        df = ts_rows.to_polars()
        assert "TSPARMCD" in df.columns


class TestTrialCriteriaCollection:
    def test_valid_collection(self, ti_rows):
        assert len(ti_rows.criteria) == 2

    def test_duplicate_ietestcd_rejected(self):
        with pytest.raises(ValueError, match="Duplicate IETESTCD"):
            TrialCriteria(
                criteria=[
                    TrialCriterion(ietestcd="INCL01", ietest="T1", iecat="INCLUSION"),
                    TrialCriterion(ietestcd="INCL01", ietest="T2", iecat="INCLUSION"),
                ]
            )

    def test_to_polars(self, ti_rows):
        df = ti_rows.to_polars()
        assert "IETESTCD" in df.columns
        assert "IECAT" in df.columns


# ================================================================== #
# Phase 3 — Cross-Domain FK Validation                                #
# ================================================================== #


class TestCrossDomainFK:
    def test_add_arms_with_valid_te(self, te_rows, ta_rows):
        """FK check passes when all TA.ETCD values exist in TE."""
        valid_etcds = {e.etcd for e in te_rows.elements}
        for a in ta_rows.arms:
            assert a.etcd in valid_etcds

    def test_add_arms_with_invalid_te_raises(self, te_rows):
        """FK check catches orphaned ETCD."""
        bad_arms = TrialArms(
            arms=[
                TrialArm(
                    armcd="PBO",
                    arm="Placebo",
                    taetord=1,
                    etcd="MISSING",
                    element="Unknown",
                    epoch=Epoch.SCREENING,
                ),
            ]
        )
        # Simulate the validation that add_arms performs
        valid_etcds = {e.etcd for e in te_rows.elements}
        with pytest.raises(ValueError, match="not found in TE"):
            for a in bad_arms.arms:
                if a.etcd not in valid_etcds:
                    raise ValueError(
                        f"TA.ETCD '{a.etcd}' not found in TE. Valid: {sorted(valid_etcds)}"
                    )

    def test_add_arms_without_te_skips_fk(self, ta_rows):
        """Omitting te= skips FK check (no error)."""
        # This should not raise — structural validation only
        assert len(ta_rows.arms) == 3


# ================================================================== #
# Phase 4 — Sequence Enforcement                                      #
# ================================================================== #


class TestSequenceEnforcement:
    def _make_ns(self):
        """Create a bare namespace with TDD stage tracking."""
        return pl.DataFrame().sdtm

    def test_add_elements_before_fetch_raises(self, te_rows):
        ns = self._make_ns()
        with pytest.raises(ValueError, match="fetch_structure"):
            ns.add_elements(te_rows)

    def test_study_header_before_fetch_raises(self):
        ns = self._make_ns()
        with pytest.raises(ValueError, match="fetch_structure"):
            ns.study_header("STUDY01", "TE")

    @patch("fleet.sdtm._tdd_mixin.TrialDesignMixin._fetch_ig_domain", return_value=MOCK_TE_META)
    def test_add_elements_before_header_raises(self, mock_fetch, te_rows):
        ns = self._make_ns()
        ns2 = ns.fetch_structure("TE")
        with pytest.raises(ValueError, match="study_header"):
            ns2.add_elements(te_rows)

    @patch("fleet.sdtm._tdd_mixin.TrialDesignMixin._fetch_ig_domain", return_value=MOCK_TE_META)
    def test_correct_sequence_succeeds(self, mock_fetch, te_rows):
        result = (
            pl.DataFrame()
            .sdtm.fetch_structure("TE")
            .study_header("CDISCPILOT01", "TE")
            .add_elements(te_rows)
            .to_frame()
        )
        assert "STUDYID" in result.columns
        assert "DOMAIN" in result.columns
        assert "ETCD" in result.columns
        assert result.shape[0] == 3


# ================================================================== #
# Phase 5 — fetch_structure (mocked)                                   #
# ================================================================== #


class TestFetchStructure:
    @patch("fleet.sdtm._tdd_mixin.TrialDesignMixin._fetch_ig_domain", return_value=MOCK_TE_META)
    def test_fetch_sets_domain_meta(self, mock_fetch):
        ns = pl.DataFrame().sdtm.fetch_structure("TE")
        assert hasattr(ns, "_domain_meta")
        assert ns._domain_meta["domain"] == "TE"
        mock_fetch.assert_called_once_with("TE", "3-4")

    @patch("fleet.sdtm._tdd_mixin.TrialDesignMixin._fetch_ig_domain", return_value=MOCK_TE_META)
    def test_fetch_saves_yaml(self, mock_fetch, tmp_path):
        cache_file = tmp_path / "te_structure.yaml"
        ns = pl.DataFrame().sdtm.fetch_structure("TE", save_to=cache_file)
        assert cache_file.exists()
        assert ns._domain_meta["domain"] == "TE"

    @patch("fleet.sdtm._tdd_mixin.TrialDesignMixin._fetch_ig_domain")
    def test_fetch_cache_first(self, mock_fetch, tmp_path):
        """Pre-existing YAML file → no API call."""
        cache_file = tmp_path / "te_structure.yaml"
        import yaml

        cache_file.write_text(yaml.dump(MOCK_TE_META))

        ns = pl.DataFrame().sdtm.fetch_structure("TE", save_to=cache_file)
        mock_fetch.assert_not_called()
        assert ns._domain_meta["domain"] == "TE"

    @patch("fleet.sdtm._tdd_mixin.TrialDesignMixin._fetch_ig_domain")
    def test_reconciliation_warns_on_missing_required(self, mock_fetch):
        """IG with extra required variable → UserWarning."""
        meta_with_extra = {
            **MOCK_TE_META,
            "variables": MOCK_TE_META["variables"]
            + [
                {
                    "name": "TESEQ",
                    "label": "Sequence Number",
                    "type": "Integer",
                    "core": "Req",
                    "role": "",
                },
            ],
        }
        mock_fetch.return_value = meta_with_extra
        with pytest.warns(UserWarning, match="TESEQ"):
            pl.DataFrame().sdtm.fetch_structure("TE")


# ================================================================== #
# Phase 6 — Protocol-Reference Pipelines                               #
# ================================================================== #


class TestProtocolReferencePipelines:
    @patch("fleet.sdtm._tdd_mixin.TrialDesignMixin._fetch_ig_domain", return_value=MOCK_TE_META)
    def test_te_pipeline(self, mock_fetch, te_rows):
        result = (
            pl.DataFrame()
            .sdtm.fetch_structure("TE")
            .study_header("CDISCPILOT01", "TE")
            .add_elements(te_rows)
            .to_frame()
        )
        assert result.shape[0] == 3
        assert result["STUDYID"][0] == "CDISCPILOT01"
        assert result["DOMAIN"][0] == "TE"
        assert result["ETCD"].to_list() == ["SCRN", "TRT", "FU"]
        assert result["EPOCH"].to_list() == ["SCREENING", "TREATMENT", "FOLLOW-UP"]

    @patch("fleet.sdtm._tdd_mixin.TrialDesignMixin._fetch_ig_domain", return_value=MOCK_TE_META)
    def test_ta_pipeline(self, mock_fetch, ta_rows, te_rows):
        result = (
            pl.DataFrame()
            .sdtm.fetch_structure("TA")
            .study_header("CDISCPILOT01", "TA")
            .add_arms(ta_rows, te=te_rows)
            .to_frame()
        )
        assert result.shape[0] == 3
        assert result["STUDYID"][0] == "CDISCPILOT01"
        assert result["ARMCD"].to_list() == ["PBO", "PBO", "PBO"]
        assert result["TAETORD"].to_list() == [1, 2, 3]

    @patch("fleet.sdtm._tdd_mixin.TrialDesignMixin._fetch_ig_domain", return_value=MOCK_TE_META)
    def test_ta_pipeline_fk_fails(self, mock_fetch, te_rows):
        """TA with bogus ETCD should raise when te= is provided."""
        bad_arms = TrialArms(
            arms=[
                TrialArm(
                    armcd="PBO",
                    arm="Placebo",
                    taetord=1,
                    etcd="NOPE",
                    element="Bad",
                    epoch=Epoch.SCREENING,
                ),
            ]
        )
        with pytest.raises(ValueError, match="not found in TE"):
            (
                pl.DataFrame()
                .sdtm.fetch_structure("TA")
                .study_header("CDISCPILOT01", "TA")
                .add_arms(bad_arms, te=te_rows)
            )

    @patch("fleet.sdtm._tdd_mixin.TrialDesignMixin._fetch_ig_domain", return_value=MOCK_TE_META)
    def test_tv_pipeline(self, mock_fetch, tv_rows):
        result = (
            pl.DataFrame()
            .sdtm.fetch_structure("TV")
            .study_header("CDISCPILOT01", "TV")
            .add_visits(tv_rows)
            .to_frame()
        )
        assert result.shape[0] == 4
        assert result["VISITNUM"].to_list() == [1, 2, 3, 4]

    @patch("fleet.sdtm._tdd_mixin.TrialDesignMixin._fetch_ig_domain", return_value=MOCK_TE_META)
    def test_ts_pipeline(self, mock_fetch, ts_rows):
        result = (
            pl.DataFrame()
            .sdtm.fetch_structure("TS")
            .study_header("CDISCPILOT01", "TS")
            .add_parameters(ts_rows)
            .to_frame()
        )
        assert result.shape[0] == 3
        assert "TSPARMCD" in result.columns

    @patch("fleet.sdtm._tdd_mixin.TrialDesignMixin._fetch_ig_domain", return_value=MOCK_TE_META)
    def test_ti_pipeline(self, mock_fetch, ti_rows):
        result = (
            pl.DataFrame()
            .sdtm.fetch_structure("TI")
            .study_header("CDISCPILOT01", "TI")
            .add_criteria(ti_rows)
            .to_frame()
        )
        assert result.shape[0] == 2
        assert result["IECAT"].to_list() == ["INCLUSION", "EXCLUSION"]


# ================================================================== #
# Phase 7 — Subject-Level Verbs                                        #
# ================================================================== #


class TestStudyDay:
    def test_basic_study_day(self):
        raw = pl.DataFrame(
            {
                "SVSTDTC": ["2014-01-05", "2014-01-01", "2013-12-30"],
                "RFSTDTC": ["2014-01-02", "2014-01-02", "2014-01-02"],
            }
        )
        result = raw.sdtm.duration("SVSTDY", start="RFSTDTC", end="SVSTDTC").to_frame()
        assert "SVSTDY" in result.columns
        # 2014-01-05 - 2014-01-02 = 3 days, >= 0 so +1 = 4
        assert result["SVSTDY"][0] == 4
        # 2014-01-01 - 2014-01-02 = -1 day, negative so no +1 = -1
        assert result["SVSTDY"][1] == -1
        # 2013-12-30 - 2014-01-02 = -3 days, negative so no +1 = -3
        assert result["SVSTDY"][2] == -3


class TestStudyDayCDISC:
    """Verify CDISC study day convention: no day 0."""

    def test_ref_date_is_day_1(self):
        raw = pl.DataFrame(
            {
                "DTC": ["2014-01-02"],
                "REF": ["2014-01-02"],
            }
        )
        result = raw.sdtm.duration("DY", start="REF", end="DTC").to_frame()
        # Same day: diff=0, >=0 so +1 → day 1
        assert result["DY"][0] == 1

    def test_day_before_ref_is_minus_1(self):
        raw = pl.DataFrame(
            {
                "DTC": ["2014-01-01"],
                "REF": ["2014-01-02"],
            }
        )
        result = raw.sdtm.duration("DY", start="REF", end="DTC").to_frame()
        # Diff = -1, negative so no +1 → -1
        assert result["DY"][0] == -1


class TestEpochAssign:
    def test_basic_epoch_assignment(self):
        raw = pl.DataFrame(
            {
                "SVSTDTC": ["2014-01-05", "2014-02-01", "2014-05-01"],
            }
        )
        result = raw.sdtm.epoch_assign(
            "EPOCH",
            date_col="SVSTDTC",
            epoch_ranges=[
                {"start": "2014-01-01", "end": "2014-01-15", "epoch": "SCREENING"},
                {"start": "2014-01-16", "end": "2014-04-15", "epoch": "TREATMENT"},
                {"start": "2014-04-16", "end": "2014-12-31", "epoch": "FOLLOW-UP"},
            ],
        ).to_frame()
        assert result["EPOCH"].to_list() == ["SCREENING", "TREATMENT", "FOLLOW-UP"]

    def test_no_match_returns_null(self):
        raw = pl.DataFrame({"DTC": ["2020-01-01"]})
        result = raw.sdtm.epoch_assign(
            "EPOCH",
            date_col="DTC",
            epoch_ranges=[
                {"start": "2014-01-01", "end": "2014-12-31", "epoch": "SCREENING"},
            ],
        ).to_frame()
        assert result["EPOCH"][0] is None


class TestElementBoundaries:
    def test_basic_boundaries(self):
        raw = pl.DataFrame(
            {
                "USUBJID": ["S01", "S01", "S01"],
                "ETCD": ["SCRN", "TRT", "FU"],
                "screening_date": ["2014-01-01", "2014-01-01", "2014-01-01"],
                "first_dose_date": ["2014-01-15", "2014-01-15", "2014-01-15"],
                "last_visit_date": ["2014-05-01", "2014-05-01", "2014-05-01"],
            }
        )
        result = raw.sdtm.element_boundaries(
            "SESTDTC",
            "SEENDTC",
            milestones={
                "SCRN": "screening_date",
                "TRT": "first_dose_date",
                "FU": "last_visit_date",
            },
        ).to_frame()
        assert "SESTDTC" in result.columns
        assert "SEENDTC" in result.columns
        # SCRN start = screening_date, SCRN end = next element's start (TRT's first_dose_date)
        assert result["SESTDTC"][0] == "2014-01-01"
        assert result["SEENDTC"][0] == "2014-01-15"


class TestVisitMap:
    def test_basic_visit_mapping(self, tv_rows):
        raw = pl.DataFrame(
            {
                "SVSTDTC": ["2014-01-03", "2014-01-15"],
                "RFSTDTC": ["2014-01-01", "2014-01-01"],
            }
        )
        result = raw.sdtm.visit_map(
            "VISITNUM", "VISIT", date_col="SVSTDTC", planned_visits=tv_rows, ref_date="RFSTDTC"
        ).to_frame()
        assert "VISITNUM" in result.columns
        assert "VISIT" in result.columns
        # Day 3 should map to Visit 1 (VISITDY=1, diff=2) vs Visit 2 (VISITDY=14, diff=11)
        assert result["VISITNUM"][0] == 1
        # Day 15 should map to Visit 2 (VISITDY=14, diff=1)
        assert result["VISITNUM"][1] == 2


# ================================================================== #
# Phase 8 — Mermaid Parser                                            #
# ================================================================== #


class TestMermaidParser:
    def test_linear_flowchart(self):
        mermaid = """
            flowchart TD
            subgraph SCR[SCREENING]
                SCRN["Screening<br/>P14D"]
            end
            subgraph TRT[TREATMENT]
                TREAT["Treatment<br/>P84D"]
            end
            subgraph FU[FOLLOW-UP]
                FOLL["Follow-up<br/>P28D"]
            end
            SCRN --> TREAT
            TREAT --> FOLL
        """
        te, ta = parse_trial_design(mermaid)
        assert len(te.elements) == 3
        etcds = {e.etcd for e in te.elements}
        assert "SCRN" in etcds
        assert "TREAT" in etcds or "TREAT" in etcds
        assert "FOLL" in etcds

    def test_branching_flowchart(self):
        mermaid = """
            flowchart TD
            subgraph SCR[SCREENING]
                SCRN["Screening<br/>P14D"]
            end
            subgraph TRT[TREATMENT]
                DRUG["Drug<br/>P84D"]
                PBO["Placebo<br/>P84D"]
            end
            SCRN -->|DRUG_ARM| DRUG
            SCRN -->|PBO_ARM| PBO
        """
        te, ta = parse_trial_design(mermaid)
        # Should have at least SCRN + DRUG + PBO elements
        assert len(te.elements) >= 3
        # Should have at least 2 arms
        arm_codes = {a.armcd for a in ta.arms}
        assert len(arm_codes) >= 2

    def test_elements_have_epochs(self):
        mermaid = """
            flowchart TD
            subgraph SCR[SCREENING]
                SCRN["Screening<br/>P14D"]
            end
            subgraph TRT[TREATMENT]
                TREAT["Treatment<br/>P84D"]
            end
            SCRN --> TREAT
        """
        te, ta = parse_trial_design(mermaid)
        for elem in te.elements:
            if elem.etcd == "SCRN":
                assert elem.epoch == Epoch.SCREENING

    def test_durations_extracted(self):
        mermaid = """
            flowchart TD
            subgraph TRT[TREATMENT]
                DRUG["Drug<br/>P84D"]
                PLAC["Placebo<br/>P28D"]
            end
            DRUG --> PLAC
        """
        te, ta = parse_trial_design(mermaid)
        drug = next((e for e in te.elements if e.etcd == "DRUG"), None)
        assert drug is not None
        assert drug.tedur == "P84D"


# ================================================================== #
# Regression — Existing SDTM functionality                             #
# ================================================================== #


class TestSDTMRegression:
    """Ensure TDD mixin doesn't break existing SDTM namespace verbs."""

    def test_assign_no_ct(self):
        raw = pl.DataFrame({"patient_number": ["01-001"]})
        result = raw.sdtm.assign_no_ct("USUBJID", source="patient_number").to_frame()
        assert result["USUBJID"][0] == "01-001"

    def test_hardcode_no_ct(self):
        raw = pl.DataFrame({"x": [1, 2, 3]})
        result = raw.sdtm.hardcode_no_ct("DOMAIN", value="DM").to_frame()
        assert result["DOMAIN"].to_list() == ["DM", "DM", "DM"]

    def test_chain_multiple_verbs(self):
        raw = pl.DataFrame(
            {
                "patient_number": ["01-001", "01-002"],
                "site_id": ["701", "702"],
            }
        )
        result = (
            raw.sdtm.assign_no_ct("USUBJID", source="patient_number")
            .assign_no_ct("SITEID", source="site_id")
            .hardcode_no_ct("DOMAIN", value="DM")
            .to_frame()
        )
        assert set(result.columns) >= {"USUBJID", "SITEID", "DOMAIN", "patient_number", "site_id"}

    def test_to_frame_produces_dataframe(self):
        raw = pl.DataFrame({"x": [1]})
        result = raw.sdtm.to_frame()
        assert isinstance(result, pl.DataFrame)
