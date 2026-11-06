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
          algorithm: assign
          value: "TESTRUN"
      - name: USUBJID
        type: text
        derivation:
          algorithm: assign
          source: patient_number
      - name: AGE
        type: integer
        derivation:
          algorithm: assign
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
          algorithm: assign
          source: USUBJID
      - name: AGE
        type: integer
        derivation:
          algorithm: assign
          source: AGE
      - name: TRT01A
        type: text
        derivation:
          algorithm: assign
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
          algorithm: assign
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
          algorithm: assign
          source: USUBJID
      - name: AVAL
        type: float
        derivation:
          algorithm: assign
          source: vsstresn
      - name: TRT01A
        type: text
      - name: AGE
        type: integer
        derivation:
          algorithm: assign
          value: 99
      - name: AGEGR1
        type: text
        derivation:
          algorithm: merge
          dataset: ADSL
          "on": USUBJID
          keep: [AGEGR1]
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
          algorithm: assign
          source: patient_number
      - name: AETERM
        type: text
        derivation:
          algorithm: assign
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


class TestRawPaths:
    """c1-288: a raw input with ``path:`` is read from the study root, by the DAG and the run."""

    def test_one_define_drives_the_dag_and_the_run(self, ctx: StudyContext) -> None:
        from fleet.core.dag import build_dag

        raw = ctx.study_root / "data" / "raw"
        raw.mkdir(parents=True)
        DM_RAW.write_csv(raw / "dm_raw.csv")

        dag = build_dag(
            ctx.metadata_sdtm_dir / "define.yaml", ctx.metadata_adam_dir / "define.yaml"
        )
        built = list(run_study(plan_study(ctx)))

        assert dag.impacted_by("dm_raw") == ["dm_raw", "DM", "ADSL"]
        assert dag.nodes["dm_raw"].path == "data/raw/dm_raw.csv"
        assert built[0].inputs["dm_raw"].path == raw / "dm_raw.csv"
        assert built[-1].frame["USUBJID"].to_list() == ["P1", "P2"]

    def test_raw_and_dataset_inputs_keep_the_raw_records(self, tmp_path: Path) -> None:
        ae = _AE_WITH_MERGE.replace(
            "      - name: ae_raw\n        type: raw\n",
            "      - name: ae_raw\n        type: raw\n        path: data/raw/ae_raw.csv\n",
        )
        ctx = _write_study(tmp_path, sdtm=_DM + ae, adam=None)
        raw = tmp_path / "data" / "raw"
        raw.mkdir(parents=True)
        DM_RAW.write_csv(raw / "dm_raw.csv")
        pl.from_repr("""\
┌────────────────┬──────────┐
│ patient_number ┆ term     │
│ ---            ┆ ---      │
│ str            ┆ str      │
╞════════════════╪══════════╡
│ P1             ┆ HEADACHE │
│ P1             ┆ NAUSEA   │
│ P1             ┆ RASH     │
└────────────────┴──────────┘
""").write_csv(raw / "ae_raw.csv")

        ae_built = list(run_study(plan_study(ctx)))[-1]

        assert ae_built.frame["AETERM"].to_list() == ["HEADACHE", "NAUSEA", "RASH"]
        assert ae_built.frame["AGE"].to_list() == [45, 45, 45]


class TestSuppFromTheSpec:
    """c1-105 step A: a qualifier variable goes to SUPP<domain>, not to the parent."""

    def test_qualifier_moves_to_supp_and_later_steps_still_read_it(self, tmp_path: Path) -> None:
        dm = _DM + (
            "      - name: SAFETY\n"
            "        label: Safety Population Flag\n"
            "        type: text\n"
            "        role: qualifier\n"
            "        derivation:\n"
            "          algorithm: assign\n"
            "          source: saf\n"
        )
        adsl = _ADSL + (
            "      - name: SAFFL\n"
            "        type: text\n"
            "        derivation:\n"
            "          algorithm: assign\n"
            "          source: SAFETY\n"
        )
        ctx = _write_study(tmp_path, sdtm=dm, adam=adsl)
        raw = pl.from_repr("""\
┌────────────────┬─────┬─────┐
│ patient_number ┆ age ┆ saf │
│ ---            ┆ --- ┆ --- │
│ str            ┆ i64 ┆ str │
╞════════════════╪═════╪═════╡
│ P1             ┆ 45  ┆ Y   │
│ P2             ┆ 60  ┆ N   │
└────────────────┴─────┴─────┘
""")
        dm_built, adsl_built = run_study(plan_study(ctx), inputs={"dm_raw": raw})

        assert "SAFETY" not in dm_built.frame.columns
        assert dm_built.supp is not None
        assert dm_built.supp.select("RDOMAIN", "USUBJID", "IDVAR", "QNAM", "QVAL").rows() == [
            ("DM", "P1", None, "SAFETY", "Y"),
            ("DM", "P2", None, "SAFETY", "N"),
        ]
        assert dm_built.supp["QLABEL"].unique().to_list() == ["Safety Population Flag"]
        assert adsl_built.frame["SAFFL"].to_list() == ["Y", "N"]
        assert adsl_built.supp is None


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


EX = pl.from_repr("""\
┌─────────┬───────┬────────────┐
│ USUBJID ┆ EXTRT ┆ EXSTDTC    │
│ ---     ┆ ---   ┆ ---        │
│ str     ┆ str   ┆ str        │
╞═════════╪═══════╪════════════╡
│ P1      ┆ A     ┆ 2024-01-02 │
│ P1      ┆ A     ┆ 2024-01-09 │
│ P2      ┆ B     ┆ 2024-02-01 │
└─────────┴───────┴────────────┘
""")

_ADSL_DM_EX = _ADSL.replace(
    "      - name: DM\n        type: dataset\n",
    "      - name: DM\n        type: dataset\n      - name: EX\n        type: dataset\n",
)


class TestCarryJoin:
    """c1-290: a carried column from a many-row input must not repeat ADSL records."""

    def test_a_carried_column_from_an_input_with_repeats_stops_and_names_the_subject(
        self, tmp_path: Path
    ) -> None:
        adsl = _ADSL_DM_EX + "      - name: EXTRT\n        type: text\n"
        ctx = _write_study(tmp_path, adam=adsl)

        with pytest.raises(
            StudyRunError, match=r"ADSL: input EX has 2 records for USUBJID P1.*many-row input"
        ):
            list(run_study(plan_study(ctx), inputs={"dm_raw": DM_RAW, "EX": EX}))

    def test_an_input_with_repeats_and_nothing_to_carry_keeps_one_record_per_subject(
        self, tmp_path: Path
    ) -> None:
        ctx = _write_study(tmp_path, adam=_ADSL_DM_EX)

        adsl = list(run_study(plan_study(ctx), inputs={"dm_raw": DM_RAW, "EX": EX}))[-1].frame

        assert adsl["USUBJID"].to_list() == ["P1", "P2"]


class TestUndeclaredSource:
    """c1-292: the message names the inputs: block, not a Python .pin() call."""

    def test_a_variable_reading_an_undeclared_dataset_names_the_inputs_block(
        self, tmp_path: Path
    ) -> None:
        adsl = _ADSL + (
            "      - name: TRTSDT\n        type: date\n        derivation:\n"
            "          algorithm: first_date\n          from_dataset: EX\n"
            "          date_col: EXSTDTC\n"
        )
        ctx = _write_study(tmp_path, adam=adsl)

        with pytest.raises(
            StudyRunError,
            match=r"dataset ADSL, variable TRTSDT reads EX: add EX to the inputs: block of ADSL",
        ):
            list(run_study(plan_study(ctx), inputs={"dm_raw": DM_RAW, "EX": EX}))


class TestRunOrder:
    """c1-291: a dataset runs after the planned datasets it reads."""

    def test_advs_listed_before_adsl_reads_the_adsl_of_this_run(self, tmp_path: Path) -> None:
        advs = _ADVS.replace(
            "      - name: AGEGR1\n        type: text\n        derivation:\n"
            "          algorithm: merge\n          dataset: ADSL\n"
            '          "on": USUBJID\n'
            "          keep: [AGEGR1]\n",
            "",
        )
        ctx = _write_study(tmp_path, adam=advs + _ADSL)
        ctx.adam_data_dir.mkdir(parents=True)
        pl.from_repr("""\
┌─────────┬─────┬────────┐
│ USUBJID ┆ AGE ┆ TRT01A │
│ ---     ┆ --- ┆ ---    │
│ str     ┆ i64 ┆ str    │
╞═════════╪═════╪════════╡
│ P1      ┆ 45  ┆ OLD    │
│ P2      ┆ 60  ┆ OLD    │
└─────────┴─────┴────────┘
""").write_parquet(ctx.adam_data_dir / "adsl.parquet")

        plan = plan_study(ctx)
        built = list(run_study(plan, inputs={"dm_raw": DM_RAW, "VS": VS}))

        assert [s.dataset for s in plan.steps] == ["DM", "ADSL", "ADVS"]
        assert built[-1].frame["TRT01A"].to_list() == ["Placebo", "Placebo"]
        assert built[-1].inputs["ADSL"].source == "built"

    def test_two_datasets_that_read_each_other_stop_with_both_names(self, tmp_path: Path) -> None:
        adsl = _ADSL.replace(
            "      - name: DM\n        type: dataset\n",
            "      - name: DM\n        type: dataset\n      - name: ADVS\n        type: dataset\n",
        )
        ctx = _write_study(tmp_path, adam=adsl + _ADVS)

        with pytest.raises(StudyRunError, match=r"ADSL, ADVS read each other"):
            plan_study(ctx)


class TestInputSearch:
    """c1-286: a type: dataset input never reads the raw directory."""

    _RAW_DM = pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ AGE │
│ ---     ┆ --- │
│ str     ┆ i64 │
╞═════════╪═════╡
│ S1      ┆ 999 │
│ S2      ┆ 999 │
└─────────┴─────┘
""")
    _SDTM_DM = pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ AGE │
│ ---     ┆ --- │
│ str     ┆ i64 │
╞═════════╪═════╡
│ S1      ┆ 45  │
│ S2      ┆ 60  │
└─────────┴─────┘
""")

    def _study(self, tmp_path: Path) -> StudyContext:
        ctx = _write_study(tmp_path)
        ctx.raw_data_dir.mkdir(parents=True)
        ctx.sdtm_data_dir.mkdir(parents=True)
        self._RAW_DM.write_csv(ctx.raw_data_dir / "dm.csv")
        return ctx

    def test_a_partial_adsl_run_reads_the_sdtm_dm_not_the_raw_file(self, tmp_path: Path) -> None:
        ctx = self._study(tmp_path)
        self._SDTM_DM.write_parquet(ctx.sdtm_data_dir / "dm.parquet")

        adsl = next(run_study(plan_study(ctx, datasets=["ADSL"])))

        assert adsl.frame["AGE"].to_list() == [45, 60]
        assert adsl.inputs["DM"].path == ctx.sdtm_data_dir / "dm.parquet"

    def test_a_declared_sdtm_input_with_only_a_raw_file_is_not_found(self, tmp_path: Path) -> None:
        ctx = self._study(tmp_path)

        with pytest.raises(StudyRunError, match=r"'DM' not found \(type: dataset\)"):
            next(run_study(plan_study(ctx, datasets=["ADSL"])))

    def test_two_files_for_one_dataset_in_one_folder_stop_and_name_both(
        self, tmp_path: Path
    ) -> None:
        ctx = self._study(tmp_path)
        self._SDTM_DM.write_parquet(ctx.sdtm_data_dir / "dm.parquet")
        self._SDTM_DM.write_csv(ctx.sdtm_data_dir / "dm.csv")

        with pytest.raises(StudyRunError, match=r"dm\.csv, dm\.parquet in .* hold dataset DM"):
            next(run_study(plan_study(ctx, datasets=["ADSL"])))

    def test_a_dataset_json_input_is_read(self, tmp_path: Path) -> None:
        from fleet.io import save_dataset_json

        ctx = self._study(tmp_path)
        save_dataset_json(self._SDTM_DM, ctx.sdtm_data_dir / "dm.json", domain="DM")

        adsl = next(run_study(plan_study(ctx, datasets=["ADSL"])))

        assert adsl.frame["AGE"].to_list() == [45, 60]

    def test_an_adam_only_study_reads_the_vendor_sdtm_not_the_raw_file(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "metadata" / "adam").mkdir(parents=True)
        (tmp_path / "metadata" / "adam" / "define.yaml").write_text(
            _ADAM_HEADER + "datasets:\n" + _ADSL, encoding="utf-8"
        )
        (tmp_path / "study_config.yaml").write_text(_CONFIG, encoding="utf-8")
        ctx = load_study_context(tmp_path / "study_config.yaml")
        ctx.raw_data_dir.mkdir(parents=True)
        ctx.sdtm_data_dir.mkdir(parents=True)
        self._RAW_DM.write_csv(ctx.raw_data_dir / "dm.csv")
        self._SDTM_DM.write_parquet(ctx.sdtm_data_dir / "dm.parquet")

        adsl = next(run_study(plan_study(ctx)))

        assert adsl.frame["AGE"].to_list() == [45, 60]


class TestPilotStudy:
    """The CDISCPILOT01 define files run from the raw inputs to ADSL."""

    _PILOT = Path(__file__).parents[2] / "examples" / "cdiscpilot01" / "study_config.yaml"

    _RAW = {
        "dm_raw": pl.from_repr("""\
┌────────────────┬─────────┬─────┬─────┬───────┬────────────────────────┬──────────┬─────────────────────┬─────────────────┬────────────────┬───────────────────────┐
│ patient_number ┆ site_id ┆ age ┆ sex ┆ race  ┆ ethnic                 ┆ arm_code ┆ arm_description     ┆ first_dose_date ┆ last_dose_date ┆ informed_consent_date │
│ ---            ┆ ---     ┆ --- ┆ --- ┆ ---   ┆ ---                    ┆ ---      ┆ ---                 ┆ ---             ┆ ---            ┆ ---                   │
│ str            ┆ str     ┆ i64 ┆ str ┆ str   ┆ str                    ┆ str      ┆ str                 ┆ str             ┆ str            ┆ str                   │
╞════════════════╪═════════╪═════╪═════╪═══════╪════════════════════════╪══════════╪═════════════════════╪═════════════════╪════════════════╪═══════════════════════╡
│ 01-701-1015    ┆ 701     ┆ 63  ┆ F   ┆ WHITE ┆ NOT HISPANIC OR LATINO ┆ Pbo      ┆ Placebo             ┆ 2014-01-02      ┆ 2014-07-02     ┆ 2014-01-01            │
│ 01-701-1023    ┆ 701     ┆ 64  ┆ M   ┆ WHITE ┆ NOT HISPANIC OR LATINO ┆ Xan_Lo   ┆ Xanomeline Low Dose ┆ 2014-01-03      ┆ 2014-07-04     ┆ 2014-01-02            │
└────────────────┴─────────┴─────┴─────┴───────┴────────────────────────┴──────────┴─────────────────────┴─────────────────┴────────────────┴───────────────────────┘
"""),
        "ae_raw": pl.from_repr("""\
┌────────────────┬───────────┬─────────────────┬───────────────┬─────────────┬─────────────┬────────────┬────────────────────┬──────────────────┬──────────────────┐
│ patient_number ┆ ae_term   ┆ ae_decoded_term ┆ ae_start_date ┆ ae_end_date ┆ ae_severity ┆ ae_serious ┆ ae_outcome         ┆ ae_action        ┆ ae_relationship  │
│ ---            ┆ ---       ┆ ---             ┆ ---           ┆ ---         ┆ ---         ┆ ---        ┆ ---                ┆ ---              ┆ ---              │
│ str            ┆ str       ┆ str             ┆ str           ┆ str         ┆ str         ┆ str        ┆ str                ┆ str              ┆ str              │
╞════════════════╪═══════════╪═════════════════╪═══════════════╪═════════════╪═════════════╪════════════╪════════════════════╪══════════════════╪══════════════════╡
│ 01-701-1015    ┆ NAUSEA    ┆ Nausea          ┆ 2014-02-05    ┆ 2014-02-06  ┆ MODERATE    ┆ N          ┆ RECOVERED/RESOLVED ┆ DOSE NOT CHANGED ┆ NOT RELATED      │
│ 01-701-1015    ┆ HEADACHE  ┆ Headache        ┆ 2014-01-10    ┆ 2014-01-12  ┆ MILD        ┆ N          ┆ RECOVERED/RESOLVED ┆ DOSE NOT CHANGED ┆ POSSIBLY RELATED │
│ 01-701-1023    ┆ DIZZINESS ┆ Dizziness       ┆ 2014-01-15    ┆ 2014-01-16  ┆ MILD        ┆ N          ┆ RECOVERED/RESOLVED ┆ DOSE NOT CHANGED ┆ POSSIBLY RELATED │
└────────────────┴───────────┴─────────────────┴───────────────┴─────────────┴─────────────┴────────────┴────────────────────┴──────────────────┴──────────────────┘
"""),
        "vs_raw": pl.from_repr("""\
┌────────────────┬──────────┬─────────────────────────┬───────────┬──────────┬──────────┬──────────┬──────────┬──────────┬────────────┐
│ patient_number ┆ vstestcd ┆ vstest                  ┆ vs_result ┆ vsorresu ┆ vsstresn ┆ vsstresu ┆ visitnum ┆ visit    ┆ vs_date    │
│ ---            ┆ ---      ┆ ---                     ┆ ---       ┆ ---      ┆ ---      ┆ ---      ┆ ---      ┆ ---      ┆ ---        │
│ str            ┆ str      ┆ str                     ┆ str       ┆ str      ┆ f64      ┆ str      ┆ f64      ┆ str      ┆ str        │
╞════════════════╪══════════╪═════════════════════════╪═══════════╪══════════╪══════════╪══════════╪══════════╪══════════╪════════════╡
│ 01-701-1015    ┆ SYSBP    ┆ Systolic Blood Pressure ┆ 120       ┆ mmHg     ┆ 120.0    ┆ mmHg     ┆ 1.0      ┆ BASELINE ┆ 2014-01-01 │
│ 01-701-1023    ┆ SYSBP    ┆ Systolic Blood Pressure ┆ 130       ┆ mmHg     ┆ 130.0    ┆ mmHg     ┆ 1.0      ┆ BASELINE ┆ 2014-01-02 │
└────────────────┴──────────┴─────────────────────────┴───────────┴──────────┴──────────┴──────────┴──────────┴──────────┴────────────┘
"""),
        "ex_raw": pl.from_repr("""\
┌────────────────┬──────────────┬─────────┬───────────────┬─────────────┐
│ patient_number ┆ ex_treatment ┆ ex_dose ┆ ex_start_date ┆ ex_end_date │
│ ---            ┆ ---          ┆ ---     ┆ ---           ┆ ---         │
│ str            ┆ str          ┆ i64     ┆ str           ┆ str         │
╞════════════════╪══════════════╪═════════╪═══════════════╪═════════════╡
│ 01-701-1015    ┆ PLACEBO      ┆ 0       ┆ 2014-01-02    ┆ 2014-07-02  │
│ 01-701-1023    ┆ XANOMELINE   ┆ 54      ┆ 2014-01-03    ┆ 2014-07-04  │
└────────────────┴──────────────┴─────────┴───────────────┴─────────────┘
"""),
    }

    def test_the_pilot_runs_from_the_raw_inputs_to_adsl(self) -> None:
        plan = plan_study(
            load_study_context(self._PILOT), datasets=["DM", "AE", "VS", "EX", "ADSL"]
        )

        built = {b.step.dataset: b.frame for b in run_study(plan, inputs=self._RAW)}

        assert built["AE"].select("USUBJID", "AESEQ", "AETERM").sort("USUBJID", "AESEQ").rows() == [
            ("01-701-1015", 1, "HEADACHE"),
            ("01-701-1015", 2, "NAUSEA"),
            ("01-701-1023", 1, "DIZZINESS"),
        ]
        assert built["ADSL"]["STUDYID"].to_list() == ["CDISCPILOT01", "CDISCPILOT01"]
        assert built["ADSL"]["TRTSDT"].cast(pl.String).to_list() == ["2014-01-02", "2014-01-03"]

    @pytest.mark.skipif(not _PILOT.exists(), reason="examples/ is not shipped here")
    def test_fleet_run_reads_the_shipped_raw_files(self, tmp_path, monkeypatch) -> None:
        """c1-186: on a copy of the shipped pilot, ``fleet run --dataset DM`` builds DM."""
        import shutil

        from fleet import cli

        study = tmp_path / "cdiscpilot01"
        shutil.copytree(self._PILOT.parent, study)
        monkeypatch.chdir(study)
        try:
            cli.main(["run", "--dataset", "DM", "--out", "out"])
        except SystemExit as exc:
            assert not exc.code
        dm = pl.read_parquet(study / "out" / "dm.parquet")
        assert dm["USUBJID"].to_list()[:2] == ["01-701-1015", "01-701-1023"]
        assert dm.height == 5
