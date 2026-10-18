"""Tests for the study run (``fleet.run``).

Seams: ``plan_study`` and ``run_study``, the module's public interface.
Each test writes a study to ``tmp_path`` and seeds frames where a file
would add nothing. Terms: ``CONTEXT.md``, section "Running a study".
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from fleet.core.exceptions import StudyRunError
from fleet.core.study_context import StudyContext, load_study_context
from fleet.run import plan_study, run_study

_CONFIG = """\
study_id: TESTRUN
company: Test Co
sdtm:
  ig_version: "3-4"
  domains: [DM]
"""

_SDTM_HEADER = """\
study:
  id: TESTRUN
  name: TESTRUN
  description: Test study for the run suite
  protocol_name: TESTRUN
  originator: Test Co
  standard: SDTMIG
  standard_version: "3.4"
"""

_ADAM_HEADER = _SDTM_HEADER.replace("SDTMIG", "ADaMIG").replace('"3.4"', '"1.3"')

_DM = """\
  - name: DM
    label: Demographics
    inputs:
      - name: dm_raw
        type: raw
        path: data/raw/dm_raw.csv
    variables:
      - name: STUDYID
        type: text
        derivation:
          algorithm: hardcode_no_ct
          value: "TESTRUN"
      - name: USUBJID
        type: text
        derivation:
          algorithm: assign_no_ct
          source: patient_number
      - name: AGE
        type: integer
        derivation:
          algorithm: assign_no_ct
          source: age
"""

_ADSL = """\
  - name: ADSL
    label: Subject-Level Analysis Dataset
    inputs:
      - name: DM
        type: dataset
    variables:
      - name: USUBJID
        type: text
        derivation:
          algorithm: source
          source: USUBJID
      - name: AGE
        type: integer
        derivation:
          algorithm: source
          source: AGE
      - name: TRT01A
        type: text
        derivation:
          algorithm: assigned
          value: "Placebo"
"""


def _write_study(root: Path, *, sdtm: str = _DM, adam: str | None = _ADSL) -> StudyContext:
    (root / "study_config.yaml").write_text(_CONFIG, encoding="utf-8")
    sdtm_dir = root / "metadata" / "sdtm"
    sdtm_dir.mkdir(parents=True)
    (sdtm_dir / "define.yaml").write_text(_SDTM_HEADER + "datasets:\n" + sdtm, encoding="utf-8")
    if adam is not None:
        adam_dir = root / "metadata" / "adam"
        adam_dir.mkdir(parents=True)
        (adam_dir / "define.yaml").write_text(_ADAM_HEADER + "datasets:\n" + adam, encoding="utf-8")
    return load_study_context(root / "study_config.yaml")


@pytest.fixture
def ctx(tmp_path: Path) -> StudyContext:
    return _write_study(tmp_path)


DM_RAW = pl.from_repr("""\
┌────────────────┬─────┐
│ patient_number ┆ age │
│ ---            ┆ --- │
│ str            ┆ i64 │
╞════════════════╪═════╡
│ P1             ┆ 45  │
│ P2             ┆ 60  │
└────────────────┴─────┘
""")


class TestPlanStudy:
    def test_sdtm_steps_come_before_adam_steps_in_file_order(self, ctx: StudyContext) -> None:
        plan = plan_study(ctx)

        assert [(s.standard, s.dataset) for s in plan.steps] == [("sdtm", "DM"), ("adam", "ADSL")]
        assert plan.steps[0].define == ctx.metadata_sdtm_dir / "define.yaml"

    def test_datasets_keeps_only_the_named_steps_case_insensitively(
        self, ctx: StudyContext
    ) -> None:
        plan = plan_study(ctx, datasets=["adsl"])

        assert [s.dataset for s in plan.steps] == ["ADSL"]

    def test_unknown_dataset_is_refused_with_the_known_names(self, ctx: StudyContext) -> None:
        with pytest.raises(StudyRunError, match=r"unknown dataset.*NOSUCH.*ADSL, DM"):
            plan_study(ctx, datasets=["nosuch"])

    def test_a_study_without_define_files_cannot_be_planned(self, tmp_path: Path) -> None:
        (tmp_path / "study_config.yaml").write_text(_CONFIG, encoding="utf-8")
        ctx = load_study_context(tmp_path / "study_config.yaml")

        with pytest.raises(StudyRunError, match="no define.yaml found"):
            plan_study(ctx)


class TestRunStudy:
    def test_a_seed_feeds_the_first_step_and_a_built_dataset_feeds_the_next(
        self, ctx: StudyContext
    ) -> None:
        built = list(run_study(plan_study(ctx), inputs={"dm_raw": DM_RAW}))

        assert [b.step.dataset for b in built] == ["DM", "ADSL"]
        dm, adsl = built
        assert dm.frame.columns == ["STUDYID", "USUBJID", "AGE"]
        assert dm.frame["USUBJID"].to_list() == ["P1", "P2"]
        assert dm.inputs["dm_raw"].source == "seed"
        assert adsl.frame["TRT01A"].to_list() == ["Placebo", "Placebo"]
        assert adsl.inputs["DM"].source == "built"

    def test_a_declared_path_is_read_from_the_study_root(self, ctx: StudyContext) -> None:
        raw = ctx.study_root / "data" / "raw"
        raw.mkdir(parents=True)
        DM_RAW.write_csv(raw / "dm_raw.csv")

        dm = next(run_study(plan_study(ctx, datasets=["DM"])))

        assert dm.frame["AGE"].to_list() == [45, 60]
        assert dm.inputs["dm_raw"].source == "declared path"
        assert dm.inputs["dm_raw"].path == raw / "dm_raw.csv"

    def test_an_input_without_a_path_is_found_by_name_in_the_data_directories(
        self, tmp_path: Path
    ) -> None:
        by_name = _DM.replace("        path: data/raw/dm_raw.csv\n", "")
        ctx = _write_study(tmp_path, sdtm=by_name, adam=None)
        ctx.raw_data_dir.mkdir(parents=True)
        DM_RAW.write_csv(ctx.raw_data_dir / "dm_raw.csv")

        dm = next(run_study(plan_study(ctx)))

        assert dm.frame["USUBJID"].to_list() == ["P1", "P2"]
        assert dm.inputs["dm_raw"].source == "raw directory"
        assert dm.inputs["dm_raw"].path == ctx.raw_data_dir / "dm_raw.csv"

    def test_a_missing_input_names_the_directories_searched(self, tmp_path: Path) -> None:
        by_name = _DM.replace("        path: data/raw/dm_raw.csv\n", "")
        ctx = _write_study(tmp_path, sdtm=by_name, adam=None)

        with pytest.raises(StudyRunError, match=r"'dm_raw' not found.*data/raw"):
            next(run_study(plan_study(ctx)))

    def test_a_seed_wins_over_a_file_at_the_declared_path(self, ctx: StudyContext) -> None:
        raw = ctx.study_root / "data" / "raw"
        raw.mkdir(parents=True)
        DM_RAW.with_columns(pl.lit(1).alias("age")).write_csv(raw / "dm_raw.csv")

        dm = next(run_study(plan_study(ctx, datasets=["DM"]), inputs={"dm_raw": DM_RAW}))

        assert dm.frame["AGE"].to_list() == [45, 60]
        assert dm.inputs["dm_raw"].source == "seed"

    def test_a_declared_path_that_does_not_exist_is_refused(self, ctx: StudyContext) -> None:
        with pytest.raises(
            StudyRunError, match=r"declared path data/raw/dm_raw.csv does not exist"
        ):
            next(run_study(plan_study(ctx, datasets=["DM"])))

    def test_a_seed_that_is_also_a_step_is_refused_before_anything_builds(
        self, ctx: StudyContext
    ) -> None:
        adsl = pl.from_repr("""\
┌─────────┬─────┬────────┐
│ USUBJID ┆ AGE ┆ TRT01A │
│ ---     ┆ --- ┆ ---    │
│ str     ┆ i64 ┆ str    │
╞═════════╪═════╪════════╡
│ P1      ┆ 45  ┆ Fixed  │
└─────────┴─────┴────────┘
""")

        with pytest.raises(StudyRunError, match=r"ADSL.*both a seeded input and a step"):
            next(run_study(plan_study(ctx), inputs={"dm_raw": DM_RAW, "adsl": adsl}))


_ADSL_WITH_AGEGR1 = (
    _ADSL
    + """\
      - name: AGEGR1
        type: text
        derivation:
          algorithm: assigned
          value: "<65"
"""
)

_ADVS = """\
  - name: ADVS
    label: Vital Signs Analysis Dataset
    inputs:
      - name: VS
        type: dataset
      - name: ADSL
        type: dataset
    variables:
      - name: USUBJID
        type: text
        derivation:
          algorithm: source
          source: USUBJID
      - name: AVAL
        type: float
        derivation:
          algorithm: source
          source: vsstresn
      - name: TRT01A
        type: text
      - name: AGE
        type: integer
        derivation:
          algorithm: assigned
          value: 99
      - name: AGEGR1
        type: text
        derivation:
          algorithm: lookup
          dataset: ADSL
          "on": USUBJID
"""

VS = pl.from_repr("""\
┌─────────┬──────────┐
│ USUBJID ┆ vsstresn │
│ ---     ┆ ---      │
│ str     ┆ f64      │
╞═════════╪══════════╡
│ P1      ┆ 120.0    │
│ P2      ┆ 80.0     │
└─────────┴──────────┘
""")


class TestCarryThrough:
    """ADR 0006: the join brings only carry-through columns; every input is pinned."""

    def test_carry_through_columns_come_from_the_input_and_derived_columns_do_not(
        self, tmp_path: Path
    ) -> None:
        ctx = _write_study(tmp_path, adam=_ADSL_WITH_AGEGR1 + _ADVS)

        built = list(run_study(plan_study(ctx), inputs={"dm_raw": DM_RAW, "VS": VS}))
        advs = built[-1].frame

        assert advs.columns == ["USUBJID", "AVAL", "TRT01A", "AGE", "AGEGR1"]
        assert advs["TRT01A"].to_list() == ["Placebo", "Placebo"]  # carried from ADSL
        assert advs["AGE"].to_list() == [99, 99]  # derived, so not joined from ADSL
        assert advs["AGEGR1"].to_list() == ["<65", "<65"]  # pinned ADSL reached by lookup

    def test_usubjid_is_required_only_when_a_carry_through_column_needs_it(
        self, tmp_path: Path
    ) -> None:
        ctx = _write_study(tmp_path, adam=_ADSL_WITH_AGEGR1 + _ADVS)
        vs_without_key = VS.rename({"USUBJID": "subject"})

        with pytest.raises(StudyRunError, match=r"ADVS: cannot carry TRT01A.*USUBJID"):
            list(run_study(plan_study(ctx), inputs={"dm_raw": DM_RAW, "VS": vs_without_key}))

    def test_an_input_with_nothing_to_carry_needs_no_usubjid(self, tmp_path: Path) -> None:
        advs = _ADVS.replace("      - name: TRT01A\n        type: text\n", "")
        advs = advs.replace("source: USUBJID", "source: subject")
        ctx = _write_study(tmp_path, adam=_ADSL_WITH_AGEGR1 + advs)
        vs_without_key = VS.rename({"USUBJID": "subject"})

        built = list(run_study(plan_study(ctx), inputs={"dm_raw": DM_RAW, "VS": vs_without_key}))

        assert built[-1].frame["AGE"].to_list() == [99, 99]


_AE_WITH_MERGE = """\
  - name: AE
    label: Adverse Events
    inputs:
      - name: ae_raw
        type: raw
      - name: DM
        type: dataset
    variables:
      - name: USUBJID
        type: text
        derivation:
          algorithm: assign_no_ct
          source: patient_number
      - name: AETERM
        type: text
        derivation:
          algorithm: assign_no_ct
          source: term
      - name: AGE
        type: integer
        derivation:
          algorithm: merge
          dataset: DM
          "on": USUBJID
"""

AE_RAW = pl.from_repr("""\
┌────────────────┬──────────┐
│ patient_number ┆ term     │
│ ---            ┆ ---      │
│ str            ┆ str      │
╞════════════════╪══════════╡
│ P2             ┆ HEADACHE │
└────────────────┴──────────┘
""")


class TestPinnedInputs:
    def test_a_pinned_input_is_reached_by_the_merge_algorithm(self, tmp_path: Path) -> None:
        ctx = _write_study(tmp_path, sdtm=_DM + _AE_WITH_MERGE, adam=None)

        built = list(run_study(plan_study(ctx), inputs={"dm_raw": DM_RAW, "ae_raw": AE_RAW}))
        ae = built[-1].frame

        assert ae.columns == ["USUBJID", "AETERM", "AGE"]
        assert ae["AGE"].to_list() == [60]  # P2's age, from the DM built one step earlier


class TestPlanRefusals:
    def test_a_dataset_without_inputs_is_refused_only_when_it_is_planned(
        self, tmp_path: Path
    ) -> None:
        no_inputs = _ADSL.replace("    inputs:\n      - name: DM\n        type: dataset\n", "")
        ctx = _write_study(tmp_path, adam=no_inputs)

        assert [s.dataset for s in plan_study(ctx, datasets=["DM"]).steps] == ["DM"]
        with pytest.raises(StudyRunError, match="dataset ADSL: the define declares no `inputs:`"):
            plan_study(ctx)

    def test_a_dataset_that_declares_no_inputs_cannot_be_planned(self, tmp_path: Path) -> None:
        no_inputs = _DM.replace(
            "    inputs:\n      - name: dm_raw\n        type: raw\n        path: data/raw/dm_raw.csv\n",
            "",
        )
        ctx = _write_study(tmp_path, sdtm=no_inputs, adam=None)

        with pytest.raises(StudyRunError, match="dataset DM: the define declares no `inputs:`"):
            plan_study(ctx)
