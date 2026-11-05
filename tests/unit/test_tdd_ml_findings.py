"""Regression tests for the medium and low trial design audit findings (package ml-sdtm)."""

from __future__ import annotations

import datetime
import enum

import polars as pl
import pytest
from pydantic import ValidationError

import fleet  # noqa: F401
from fleet.adam.neuro_namespace import NeuroNamespace  # noqa: F401
from fleet.core.exceptions import CTError, DerivationError
from fleet.sdtm._tdd_mixin import TrialDesignMixin
from fleet.sdtm.design import StudyDesign
from fleet.sdtm.tdd import (
    Epoch,
    TrialArm,
    TrialCriteria,
    TrialCriterion,
    TrialElement,
    TrialElements,
    TrialVisit,
    TrialVisits,
)
from fleet.sdtm.tdd_audit import audit

_TV = pl.from_repr("""\
┌──────────┬───────────┬─────────┐
│ VISITNUM ┆ VISIT     ┆ VISITDY │
│ ---      ┆ ---       ┆ ---     │
│ i64      ┆ str       ┆ i64     │
╞══════════╪═══════════╪═════════╡
│ 1        ┆ SCREENING ┆ -7      │
│ 2        ┆ WEEK 1    ┆ 8       │
│ 3        ┆ WEEK 2    ┆ 15      │
└──────────┴───────────┴─────────┘
""")

_TE_ROWS = TrialElements(
    elements=[TrialElement(etcd="SCRN", element="Screening", testrl="CONSENT", epoch="SCREENING")]
)


# ── c1-224 visit_map with no tolerance warns ───────────────────────────── #


def test_c1_224_no_tolerance_warns_with_the_largest_distance() -> None:
    sv = pl.from_repr("""\
┌─────────┬────────┬────────────┬────────────┐
│ USUBJID ┆ DOMAIN ┆ SVSTDTC    ┆ RFSTDTC    │
│ ---     ┆ ---    ┆ ---        ┆ ---        │
│ str     ┆ str    ┆ str        ┆ str        │
╞═════════╪════════╪════════════╪════════════╡
│ S1      ┆ SV     ┆ 2014-08-01 ┆ 2014-01-10 │
└─────────┴────────┴────────────┴────────────┘
""")
    with pytest.warns(UserWarning, match="largest distance is 189 study days"):
        out = sv.sdtm.visit_map(
            "VISITNUM", "VISIT", date_col="SVSTDTC", planned_visits=_TV, ref_date="RFSTDTC"
        ).to_frame()
    assert out.select("VISITNUM", "VISIT").row(0) == (3, "WEEK 2")


# ── c2-953 c1-116 epoch_assign ─────────────────────────────────────────── #


def test_c2_953_se_with_no_epoch_names_the_fix() -> None:
    se = pl.from_repr("""\
┌─────────┬──────┬────────────┬────────────┐
│ USUBJID ┆ ETCD ┆ SESTDTC    ┆ SEENDTC    │
│ ---     ┆ ---  ┆ ---        ┆ ---        │
│ str     ┆ str  ┆ str        ┆ str        │
╞═════════╪══════╪════════════╪════════════╡
│ S1      ┆ SCRN ┆ 2014-01-01 ┆ 2014-01-15 │
│ S1      ┆ TRT  ┆ 2014-01-15 ┆ 2014-04-15 │
└─────────┴──────┴────────────┴────────────┘
""")
    ae = pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ AESTDTC    │
│ ---     ┆ ---        │
│ str     ┆ str        │
╞═════════╪════════════╡
│ S1      ┆ 2014-01-20 │
└─────────┴────────────┘
""")
    with pytest.raises(DerivationError, match="SE has no EPOCH"):
        ae.sdtm.epoch_assign("EPOCH", date_col="AESTDTC", se=se)


def test_c1_116_epoch_ranges_accept_a_date_column() -> None:
    vs = pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ VSDTC      │
│ ---     ┆ ---        │
│ str     ┆ date       │
╞═════════╪════════════╡
│ 1       ┆ 2024-01-01 │
└─────────┴────────────┘
""")
    ranges = [{"start": "2023-12-01", "end": "2024-01-10", "epoch": "SCREENING"}]
    out = vs.sdtm.epoch_assign("EPOCH", date_col="VSDTC", epoch_ranges=ranges).to_frame()
    assert out["EPOCH"].to_list() == ["SCREENING"]


# ── c1-225 c1-229 c1-230 TDD builder chain ─────────────────────────────── #


def test_c1_225_header_columns_come_first() -> None:
    te = (
        pl.DataFrame()
        .sdtm.fetch_structure("TE")
        .study_header("S", "TE")
        .add_elements(_TE_ROWS)
        .to_frame()
    )
    assert te.columns == ["STUDYID", "DOMAIN", "ETCD", "ELEMENT", "TESTRL", "TEENRL", "TEDUR"]


def test_c1_229_header_and_add_verb_must_match_the_fetched_domain() -> None:
    fetched = pl.DataFrame().sdtm.fetch_structure("TE")
    with pytest.raises(ValueError, match=r"study_header\('TA'\) does not match"):
        fetched.study_header("S", "TA")
    with pytest.raises(ValueError, match="study_id must be a non-empty string"):
        fetched.study_header(None, "TE")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=r"add_criteria\(\) does not build TE"):
        fetched.study_header("S", "TE").add_criteria(
            TrialCriteria(
                criteria=[TrialCriterion(ietestcd="IN01", ietest="Age", iecat="INCLUSION")]
            )
        )


def test_c1_230_cache_for_another_domain_raises(tmp_path) -> None:
    cache = tmp_path / "te.yaml"
    pl.DataFrame().sdtm.fetch_structure("TE", save_to=cache)
    with pytest.raises(ValueError, match="holds domain TE, not TA"):
        pl.DataFrame().sdtm.fetch_structure("TA", save_to=cache)


def test_c1_230_missing_define_path_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        pl.DataFrame().sdtm.fetch_structure("TE", define_path=tmp_path / "nope.yaml")


def test_c1_230_the_library_error_is_in_the_message(monkeypatch) -> None:
    def no_key(domain: str, ig_version: str) -> dict:
        raise CTError("CDISC API key is required")

    monkeypatch.setattr(TrialDesignMixin, "_fetch_ig_domain", staticmethod(no_key))
    with pytest.raises(CTError, match="CDISC API key is required"):
        pl.DataFrame().sdtm.fetch_structure("AE")


# ── TDD models ─────────────────────────────────────────────────────────── #


def test_c2_958_a_real_tv_builds() -> None:
    tv = TrialVisits(
        visits=[
            TrialVisit(visitnum=1, visit="SCREENING", visitdy=-7),
            TrialVisit(visitnum=3.5, visit="WEEK 1", visitdy=7),
            TrialVisit(visitnum=13, visit="WEEK 26", visitdy=182),
            TrialVisit(visitnum=201, visit="RETRIEVAL", visitdy=168),
        ]
    )
    assert tv.to_polars()["VISITNUM"].to_list() == [1.0, 3.5, 13.0, 201.0]


def test_c1_248_same_visitnum_in_two_arms_and_criteria_versions() -> None:
    tv = TrialVisits(
        visits=[
            TrialVisit(visitnum=2, visit="V2", armcd="A"),
            TrialVisit(visitnum=2, visit="V2", armcd="B"),
        ]
    )
    assert tv.to_polars().height == 2
    with pytest.raises(ValidationError, match="blank-ARMCD row and an arm row"):
        TrialVisits(
            visits=[
                TrialVisit(visitnum=2, visit="V2"),
                TrialVisit(visitnum=2, visit="V2", armcd="A"),
            ]
        )
    ti = TrialCriteria(
        criteria=[
            TrialCriterion(ietestcd="INCL01", ietest="Age", iecat="INCLUSION", tivers="1"),
            TrialCriterion(ietestcd="INCL01", ietest="Age 18", iecat="INCLUSION", tivers="2"),
        ]
    )
    assert ti.to_polars().height == 2


def test_c1_248_audit_keys_tv_on_armcd_and_visitnum() -> None:
    tv = pl.from_repr("""
┌───────┬──────────┬───────┬─────────┐
│ ARMCD ┆ VISITNUM ┆ VISIT ┆ VISITDY │
│ ---   ┆ ---      ┆ ---   ┆ ---     │
│ str   ┆ i64      ┆ str   ┆ i64     │
╞═══════╪══════════╪═══════╪═════════╡
│ A     ┆ 1        ┆ V1    ┆ 1       │
│ B     ┆ 1        ┆ V1    ┆ 1       │
└───────┴──────────┴───────┴─────────┘
""")
    rules = audit(tv=tv)["rule_id"].to_list()
    assert "FLEETTD06" not in rules
    assert "SD1064" not in rules


def test_c1_252_arm_codes_with_hyphens_build() -> None:
    arm = TrialArm(
        armcd="P-5-10", arm="Placebo", taetord=1, etcd="TRT-1", element="T", epoch="TREATMENT"
    )
    assert arm.armcd == "P-5-10"


def test_c1_253_empty_sections_and_null_visitdy_keep_their_types() -> None:
    tv = TrialVisits(visits=[TrialVisit(visitnum=1, visit="V1")]).to_polars()
    assert tv.schema["VISITDY"] == pl.Int64
    empty = StudyDesign(study_id="S").to_tv()
    assert empty.height == 0
    assert empty.columns[:4] == ["STUDYID", "DOMAIN", "VISITNUM", "VISIT"]
    assert StudyDesign(study_id="S").to_te().height == 0


def test_c1_256_c1_260_epoch_has_13_members() -> None:
    assert len(Epoch) == 13
    assert Epoch._concept_id == "C99079"
    with pytest.raises(ValueError):
        Epoch("C99079")
    assert not isinstance(Epoch.__dict__.get("_concept_id"), enum.Enum)


def test_c1_256_to_spec_yaml_with_ct_epoch_writes_the_concept_id() -> None:
    raw = pl.DataFrame({"ep": ["SCREENING"]})
    text = raw.sdtm.assign("EPOCH", source="ep", ct=Epoch).to_spec_yaml("SE")
    assert "C99079" in text


def test_c1_260_cdrsob_total_with_no_columns_raises() -> None:
    df = pl.DataFrame({"X": [1.0]})
    with pytest.raises(DerivationError, match="give the 6 CDR boxes, got 0"):
        df.adam.neuro.cdrsob_total("CDRSOB", domain_cols=[])


@pytest.mark.parametrize("bad", ["P", "PT", "P1DT", "P1Y2W"])
def test_c1_257_an_iso_duration_needs_a_component(bad: str) -> None:
    with pytest.raises(ValidationError):
        TrialElement(etcd="X", element="X", tedur=bad, epoch="TREATMENT")


@pytest.mark.parametrize("good", ["P14D", "P1Y2M3DT4H5M6S", "P2W", "PT12H"])
def test_c1_257_valid_iso_durations_stay_valid(good: str) -> None:
    assert TrialElement(etcd="X", element="X", tedur=good, epoch="TREATMENT").tedur == good


def test_c1_259_ietestcd_rules_in_model_and_audit() -> None:
    with pytest.raises(ValidationError):
        TrialCriterion(ietestcd="1TEST", ietest="T", iecat="INCLUSION")
    ti = pl.from_repr("""\
┌──────────┐
│ IETESTCD │
│ ---      │
│ str      │
╞══════════╡
│ IN-1     │
│ incl1    │
│ IN CL    │
│ 1TEST    │
│ INCL01   │
└──────────┘
""")
    found = audit(ti=ti).filter(pl.col("rule_id") == "SD0018")["message"].to_list()
    assert len(found) == 4
    assert not any("INCL01" in m for m in found)


# ── tdd_audit ──────────────────────────────────────────────────────────── #


def test_c1_251_a_blank_req_variable_is_an_error() -> None:
    te = pl.from_repr("""\
┌──────┬───────────┬────────┬────────┬───────┐
│ ETCD ┆ ELEMENT   ┆ TESTRL ┆ TEENRL ┆ TEDUR │
│ ---  ┆ ---       ┆ ---    ┆ ---    ┆ ---   │
│ str  ┆ str       ┆ str    ┆ str    ┆ str   │
╞══════╪═══════════╪════════╪════════╪═══════╡
│ SCRN ┆ Screening ┆        ┆        ┆ P14D  │
└──────┴───────────┴────────┴────────┴───────┘
""")
    found = audit(te=te).filter(pl.col("rule_id") == "FLEETTD08")
    assert found["message"].to_list() == ["TE.TESTRL is Req and 1 record(s) are null or blank"]
    td = pl.DataFrame({"TDORDER": [1], "TDANCVAR": ["ANCH"]})
    td_found = audit(td=td).filter(pl.col("rule_id") == "FLEETTD08")["message"].to_list()
    assert "TD.TDSTOFF is Req and the column is absent" in td_found


def test_c1_790_null_tsval_and_missing_element_give_findings() -> None:
    ts = pl.from_repr("""\
┌──────────┬───────┬─────────┐
│ TSPARMCD ┆ TSVAL ┆ TSVALNF │
│ ---      ┆ ---   ┆ ---     │
│ str      ┆ str   ┆ str     │
╞══════════╪═══════╪═════════╡
│ ADDON    ┆ null  ┆ NI      │
└──────────┴───────┴─────────┘
""")
    assert audit(ts=ts).height > 0
    assert audit(ts=ts.drop("TSVAL")).height > 0
    te = pl.DataFrame({"ETCD": ["SCRN"], "ELEMENT": ["Screening"]})
    ta_null = pl.from_repr("""\
┌───────┬─────┬─────────┬──────┬─────────┬───────────┐
│ ARMCD ┆ ARM ┆ TAETORD ┆ ETCD ┆ ELEMENT ┆ EPOCH     │
│ ---   ┆ --- ┆ ---     ┆ ---  ┆ ---     ┆ ---       │
│ str   ┆ str ┆ i64     ┆ str  ┆ str     ┆ str       │
╞═══════╪═════╪═════════╪══════╪═════════╪═══════════╡
│ A     ┆ Arm ┆ 1       ┆ SCRN ┆ null    ┆ SCREENING │
│ A     ┆ Arm ┆ 2       ┆ XXX  ┆ null    ┆ TREATMENT │
└───────┴─────┴─────────┴──────┴─────────┴───────────┘
""")
    sd0067 = audit(te=te, ta=ta_null).filter(pl.col("rule_id") == "SD0067")["message"]
    assert sd0067.to_list() == ["ETCD 'XXX' in TA is not in TE"]
    sd0067 = audit(te=te, ta=ta_null.drop("ELEMENT")).filter(pl.col("rule_id") == "SD0067")
    assert sd0067.height == 1


def test_c1_786_an_arm_needs_a_name_and_dm_arm_is_checked() -> None:
    elements = [{"etcd": "SCRN", "element": "Screening", "epoch": "SCREENING"}]
    with pytest.raises(ValidationError, match="no name in arm_names"):
        StudyDesign(study_id="S", elements=elements, arms={"PBO": ["SCRN"]})
    dm = pl.from_repr("""\
┌─────────┬───────┬───────────────────┐
│ USUBJID ┆ ARMCD ┆ ARM               │
│ ---     ┆ ---   ┆ ---               │
│ str     ┆ str   ┆ str               │
╞═════════╪═══════╪═══════════════════╡
│ 1       ┆ A     ┆ Totally different │
└─────────┴───────┴───────────────────┘
""")
    design = StudyDesign(
        study_id="S", elements=elements, arms={"A": ["SCRN"]}, arm_names={"A": "Arm A"}
    )
    found = audit(ta=design.to_ta(), dm=dm).filter(pl.col("rule_id") == "FLEETTD07")
    assert found["severity"].to_list() == ["warning"]


# ── c1-784 c1-785 from_usdm ────────────────────────────────────────────── #


def _usdm(**design_extra: object) -> dict:
    design = {
        "id": "SD1",
        "epochs": [
            {"id": "E3", "name": "FOLLOW-UP", "previousId": "E2", "nextId": None},
            {"id": "E2", "name": "TREATMENT", "previousId": "E1", "nextId": "E3"},
            {"id": "E1", "name": "SCREENING", "previousId": None, "nextId": "E2"},
        ],
        "elements": [
            {"id": "EL1", "name": "Screening"},
            {"id": "EL2", "name": "Treatment"},
            {"id": "EL3", "name": "Follow-up"},
        ],
        "arms": [{"id": "A1", "name": "Placebo"}],
        "studyCells": [
            {"id": "C1", "armId": "A1", "epochId": "E1", "elementIds": ["EL1"]},
            {"id": "C2", "armId": "A1", "epochId": "E2", "elementIds": ["EL2"]},
            {"id": "C3", "armId": "A1", "epochId": "E3", "elementIds": ["EL3"]},
        ],
        "encounters": [
            {
                "id": "V3",
                "name": "Week 26",
                "previousId": "V2",
                "nextId": None,
                "transitionEndRule": {"text": "subject has ECG removed"},
            },
            {"id": "V2", "name": "Baseline", "previousId": "V1", "nextId": "V3"},
            {
                "id": "V1",
                "name": "Screening",
                "previousId": None,
                "nextId": "V2",
                "transitionStartRule": {"text": "Subject identifier"},
            },
        ],
        **design_extra,
    }
    return {
        "study": {
            "versions": [
                {
                    "studyIdentifiers": [
                        {"studyIdentifier": "NCT12345678", "scopeId": "ORG2"},
                        {"studyIdentifier": "CDISCPILOT01", "scopeId": "ORG1"},
                    ],
                    "organizations": [
                        {"id": "ORG1", "type": {"decode": "Clinical Study Sponsor"}},
                        {"id": "ORG2", "type": {"decode": "Study Registry"}},
                    ],
                    "studyDesigns": [design],
                }
            ]
        }
    }


def test_c1_784_c1_785_chain_order_sponsor_id_and_visit_rules() -> None:
    with pytest.warns(UserWarning, match=r"2 visit\(s\) have no transitionStartRule"):
        design = StudyDesign.from_usdm(_usdm())
    assert design.study_id == "CDISCPILOT01"
    assert design.to_ta()["EPOCH"].to_list() == ["SCREENING", "TREATMENT", "FOLLOW-UP"]
    tv = design.to_tv().select("VISITNUM", "VISIT", "TVSTRL", "TVENRL").rows()
    assert tv == [
        (1, "Screening", "Subject identifier", ""),
        (2, "Baseline", "", ""),
        (3, "Week 26", "", "subject has ECG removed"),
    ]


def test_c1_785_broken_references_and_designs_raise_or_warn() -> None:
    bad = _usdm(studyCells=[{"id": "C1", "armId": "A1", "epochId": "E1", "elementIds": ["X"]}])
    with pytest.raises(ValueError, match="unknown elementIds"):
        StudyDesign.from_usdm(bad)
    bad = _usdm(studyCells=[{"id": "C1", "armId": "NOPE", "epochId": "E1", "elementIds": []}])
    with pytest.raises(ValueError, match="unknown armId"):
        StudyDesign.from_usdm(bad)
    none = _usdm()
    none["study"]["versions"][0]["studyDesigns"] = []
    with pytest.raises(ValueError, match="no studyDesigns"):
        StudyDesign.from_usdm(none)
    two = _usdm()
    designs = two["study"]["versions"][0]["studyDesigns"]
    designs.append(dict(designs[0], id="SD2"))
    with pytest.warns(UserWarning, match="2 study designs"):
        StudyDesign.from_usdm(two)


def test_c1_253_audit_on_an_empty_ts_reports_each_required_parameter() -> None:
    ts = StudyDesign(study_id="S").to_ts()
    assert ts.height == 0
    assert audit(ts=ts).filter(pl.col("rule_id") == "SD2232").height == 1
    assert isinstance(datetime.date.today(), datetime.date)
