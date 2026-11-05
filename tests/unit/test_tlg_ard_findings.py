"""Regression tests for the high TLG/ARD audit findings (package tlg-ard).

Each test names its finding ID.  The data are the rows of the finding.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from pydantic import ValidationError

import fleet.tlg as tlg
from fleet import cli
from fleet.core.exceptions import SchemaError
from fleet.tlg import (
    AEListingSpec,
    AEOverviewSpec,
    AESeveritySpec,
    AESocPtSpec,
    CMSummarySpec,
    Column,
    DMSummarySpec,
    GroupPool,
    LBAbnormalSpec,
    MissingLevel,
    Row,
    Statistic,
    VSSummarySpec,
    ard_to_table_model,
    render_html,
)
from fleet.tlg._ard import apply_fmt_fn, compute_big_n


def _stat(ard: pl.DataFrame, *, arm: str, level: str, stat: str = "n", **eq: str) -> float:
    cond = (
        (pl.col("group1_level") == arm)
        & (pl.col("variable_level") == level)
        & (pl.col("stat_name") == stat)
    )
    for col, value in eq.items():
        cond = cond & (pl.col(col) == value)
    return ard.filter(cond)["stat"].item()


def _row(model: tlg.TableModel, label: str, after: str | None = None) -> tlg.render.TableRow:
    rows = model.rows
    if after is not None:
        rows = rows[[r.label for r in rows].index(after) + 1 :]
    return next(r for r in rows if r.label == label)


# ── c1-428: a printed tie rounds half away from zero ────────────────────


@pytest.mark.parametrize(
    ("value", "fmt", "expected"),
    [
        (6.25, "xx.x", "6.3"),
        (31.25, "xx.x", "31.3"),
        (12.25, "xx.x", "12.3"),
        (0.25, "xx.x", "0.3"),
        (2.5, "xx", "3"),
        (12.5, "xx", "13"),
        (0.125, "xx.xx", "0.13"),
        (1.005, "xx.xx", "1.01"),
        (0.285, "xx.xx", "0.29"),
        (1.15, "xx.x", "1.2"),
        (-2.25, "xx.x", "-2.3"),
        (-0.04, "xx.x", "0.0"),
        (124.44999999999999, "xx.x", "124.5"),
        (28.749999999999996, "xx.x", "28.8"),
        (31.25, "xx.x%", "31.3%"),
        (float("inf"), "xx.x", "inf"),
    ],
)
def test_c1_428_a_tie_rounds_half_away_from_zero(value: float, fmt: str, expected: str) -> None:
    assert apply_fmt_fn(value, fmt) == expected


def test_c1_428_a_huge_value_does_not_raise() -> None:
    assert apply_fmt_fn(1e30, "xx.x").startswith("1000000000000000019884624838656")


def test_c1_428_arm_of_16_prints_sas_percentages() -> None:
    adsl = pl.DataFrame({"USUBJID": [f"S{i:02d}" for i in range(16)], "TRTA": ["Drug A"] * 16})
    adae = pl.from_repr("""
┌─────────┬────────┬──────────┬──────────┐
│ USUBJID ┆ TRTA   ┆ AEBODSYS ┆ AEDECOD  │
│ ---     ┆ ---    ┆ ---      ┆ ---      │
│ str     ┆ str    ┆ str      ┆ str      │
╞═════════╪════════╪══════════╪══════════╡
│ S00     ┆ Drug A ┆ NERV     ┆ HEADACHE │
│ S01     ┆ Drug A ┆ GI       ┆ NAUSEA   │
│ S02     ┆ Drug A ┆ GI       ┆ NAUSEA   │
│ S03     ┆ Drug A ┆ GI       ┆ NAUSEA   │
│ S04     ┆ Drug A ┆ GI       ┆ NAUSEA   │
│ S05     ┆ Drug A ┆ GI       ┆ NAUSEA   │
└─────────┴────────┴──────────┴──────────┘
""")
    ard = adae.tlg.ae.t_soc_pt(groupby="TRTA", adsl=adsl)
    pct = ard.filter((pl.col("stat_name") == "pct") & (pl.col("variable") == "AEDECOD"))
    fmt = dict(zip(pct["variable_level"], pct["stat_fmt"]))
    assert fmt == {"HEADACHE": "6.3", "NAUSEA": "31.3"}


# ── c1-430 / c1-431: a null arm is in no column ─────────────────────────


ADSL_NULL_ARM = pl.from_repr("""
┌─────────┬─────────┬───────┬─────┬─────┐
│ USUBJID ┆ TRT01A  ┆ SAFFL ┆ AGE ┆ SEX │
│ ---     ┆ ---     ┆ ---   ┆ --- ┆ --- │
│ str     ┆ str     ┆ str   ┆ i64 ┆ str │
╞═════════╪═════════╪═══════╪═════╪═════╡
│ P1      ┆ Placebo ┆ Y     ┆ 60  ┆ F   │
│ P2      ┆ Placebo ┆ Y     ┆ 62  ┆ M   │
│ D1      ┆ Drug    ┆ Y     ┆ 70  ┆ F   │
│ SF1     ┆ null    ┆ N     ┆ 55  ┆ M   │
└─────────┴─────────┴───────┴─────┴─────┘
""")


def test_c1_430_null_arm_is_left_out_with_a_warning() -> None:
    with pytest.warns(UserWarning, match=r"TRT01A is null for 1 subject\(s\).*SF1"):
        ard = ADSL_NULL_ARM.tlg.dm.t_summary(groupby="TRT01A")
    big_n = ard.filter(pl.col("stat_name") == "N")
    assert dict(zip(big_n["group1_level"], big_n["stat"])) == {"Drug": 1.0, "Placebo": 2.0}


def test_c1_430_a_population_filter_removes_the_warning() -> None:
    spec = DMSummarySpec(adsl_filter='pl.col("SAFFL") == "Y"')
    ard = ADSL_NULL_ARM.tlg.dm.t_summary(groupby="TRT01A", spec=spec)
    assert ard.filter(pl.col("stat_name") == "N").height == 2


def test_c1_431_total_pool_leaves_out_records_without_an_arm() -> None:
    adsl = pl.from_repr("""
┌─────────┬──────┐
│ USUBJID ┆ TRTA │
│ ---     ┆ ---  │
│ str     ┆ str  │
╞═════════╪══════╡
│ S1      ┆ A    │
│ S2      ┆ A    │
│ S3      ┆ B    │
└─────────┴──────┘
""")
    adae = pl.from_repr("""
┌─────────┬──────┬──────────┬──────────┐
│ USUBJID ┆ TRTA ┆ AEBODSYS ┆ AEDECOD  │
│ ---     ┆ ---  ┆ ---      ┆ ---      │
│ str     ┆ str  ┆ str      ┆ str      │
╞═════════╪══════╪══════════╪══════════╡
│ S1      ┆ A    ┆ NERV     ┆ HEADACHE │
│ S2      ┆ null ┆ NERV     ┆ HEADACHE │
└─────────┴──────┴──────────┴──────────┘
""")
    star = AESocPtSpec(template="aet02", pools=[GroupPool(label="Total", arms="*")])
    named = AESocPtSpec(template="aet02", pools=[GroupPool(label="Total", arms=["A", "B"])])
    for spec in (star, named):
        ard = tlg.run_spec(spec, adae, adsl=adsl)
        assert _stat(ard, arm="Total", level="HEADACHE") == 1


def test_c1_431_big_n_of_a_star_pool_has_no_null_arm() -> None:
    with pytest.warns(UserWarning, match="TRT01A is null"):
        big_n = compute_big_n(ADSL_NULL_ARM, "TRT01A", [GroupPool(label="Total", arms="*")])
    assert big_n == {"Drug": 1, "Placebo": 2, "Total": 3}


# ── c1-432 / c1-463 / c1-273: the arm column of ADSL and of the spec ────


ADAE_TRTA = pl.from_repr("""
┌─────────┬──────┬───────┬──────────┬──────────┐
│ USUBJID ┆ TRTA ┆ AESER ┆ AEBODSYS ┆ AEDECOD  │
│ ---     ┆ ---  ┆ ---   ┆ ---      ┆ ---      │
│ str     ┆ str  ┆ str   ┆ str      ┆ str      │
╞═════════╪══════╪═══════╪══════════╪══════════╡
│ S1      ┆ A    ┆ N     ┆ NERV     ┆ HEADACHE │
│ S2      ┆ B    ┆ Y     ┆ NERV     ┆ HEADACHE │
└─────────┴──────┴───────┴──────────┴──────────┘
""")

ADSL_TRT01A = pl.from_repr("""
┌─────────┬────────┬───────┬─────┬─────┐
│ USUBJID ┆ TRT01A ┆ SAFFL ┆ AGE ┆ SEX │
│ ---     ┆ ---    ┆ ---   ┆ --- ┆ --- │
│ str     ┆ str    ┆ str   ┆ i64 ┆ str │
╞═════════╪════════╪═══════╪═════╪═════╡
│ S1      ┆ A      ┆ Y     ┆ 40  ┆ F   │
│ S2      ┆ B      ┆ Y     ┆ 50  ┆ M   │
└─────────┴────────┴───────┴─────┴─────┘
""")


def test_c1_432_error_names_the_adsl_arm_flag() -> None:
    with pytest.raises(SchemaError, match=r"--adsl-groupby TRT01A.*\['TRT01A'\]"):
        ADAE_TRTA.tlg.ae.t_soc_pt(groupby="TRTA", adsl=ADSL_TRT01A)


def test_c1_432_builder_names_the_adsl_arm() -> None:
    ard = (
        ADAE_TRTA.tlg.ae.population(ADSL_TRT01A, group_col="TRT01A")
        .by("TRTA")
        .template("aet02")
        .to_ard()
    )
    big_n = ard.filter((pl.col("stat_name") == "N") & (pl.col("variable") == ""))
    assert dict(zip(big_n["group1_level"], big_n["stat"])) == {"A": 1.0, "B": 1.0}
    assert _stat(ard, arm="B", level="HEADACHE", stat="pct") == 100.0


def test_c1_432_yaml_adsl_group_col_round_trips() -> None:
    spec = tlg.AESocPtSpec(template="aet02", adsl_group_col="TRT01A")
    restored = tlg.AESocPtSpec.from_yaml(spec.to_yaml())
    ard = tlg.run_spec(restored, ADAE_TRTA, adsl=ADSL_TRT01A)
    assert _stat(ard, arm="A", level="HEADACHE") == 1


def test_c1_432_cli_adsl_groupby(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    ADAE_TRTA.write_parquet(tmp_path / "adae.parquet")
    ADSL_TRT01A.write_parquet(tmp_path / "adsl.parquet")
    spec = tmp_path / "aet02.yaml"
    spec.write_text("template: aet02\n", encoding="utf-8")
    base = ["tlg", "run", str(spec), "--data", str(tmp_path / "adae.parquet")]
    base += ["--adsl", str(tmp_path / "adsl.parquet"), "-o", str(tmp_path / "out")]

    assert _run(base) == 1
    assert "--adsl-groupby" in capsys.readouterr().err
    assert _run([*base, "--adsl-groupby", "TRT01A"]) == 0
    assert "(N=1)" in (tmp_path / "out" / "aet02.html").read_text(encoding="utf-8")


def test_c1_463_builder_by_trt01a_on_a_conformant_adsl() -> None:
    by_builder = ADSL_TRT01A.tlg.dm.population(ADSL_TRT01A).by("TRT01A").to_ard()
    direct = ADSL_TRT01A.tlg.dm.t_summary(groupby="TRT01A", adsl=ADSL_TRT01A)
    assert by_builder.equals(direct)


ADSL_PLANNED = pl.from_repr("""
┌─────────┬─────────┬─────────┐
│ USUBJID ┆ TRT01P  ┆ TRTA    │
│ ---     ┆ ---     ┆ ---     │
│ str     ┆ str     ┆ str     │
╞═════════╪═════════╪═════════╡
│ S1      ┆ Drug A  ┆ Drug A  │
│ S2      ┆ Placebo ┆ Drug A  │
│ S3      ┆ Placebo ┆ Placebo │
│ S4      ┆ Drug A  ┆ Drug A  │
└─────────┴─────────┴─────────┘
""")

ADAE_PLANNED = pl.from_repr("""
┌─────────┬─────────┬─────────┬──────────┬──────────┐
│ USUBJID ┆ TRT01P  ┆ TRTA    ┆ AEBODSYS ┆ AEDECOD  │
│ ---     ┆ ---     ┆ ---     ┆ ---      ┆ ---      │
│ str     ┆ str     ┆ str     ┆ str      ┆ str      │
╞═════════╪═════════╪═════════╪══════════╪══════════╡
│ S1      ┆ Drug A  ┆ Drug A  ┆ NERV     ┆ HEADACHE │
│ S2      ┆ Placebo ┆ Drug A  ┆ NERV     ┆ HEADACHE │
│ S3      ┆ Placebo ┆ Placebo ┆ NERV     ┆ HEADACHE │
└─────────┴─────────┴─────────┴──────────┴──────────┘
""")


def _run(argv: list[str]) -> int:
    try:
        cli.main(argv)
    except SystemExit as exc:  # noqa: PERF203
        return int(exc.code or 0)
    return 0


def test_c1_273_cli_groups_by_the_spec_columns(tmp_path: Path) -> None:
    ADAE_PLANNED.write_parquet(tmp_path / "adae.parquet")
    ADSL_PLANNED.write_parquet(tmp_path / "adsl.parquet")
    spec = tmp_path / "aet02.yaml"
    spec.write_text("template: aet02\ncolumns: [TRT01P]\n", encoding="utf-8")
    argv = ["tlg", "run", str(spec), "--data", str(tmp_path / "adae.parquet")]
    argv += ["--adsl", str(tmp_path / "adsl.parquet"), "-o", str(tmp_path / "out")]
    assert _run(argv) == 0
    html = (tmp_path / "out" / "aet02.html").read_text(encoding="utf-8")
    assert "(N=2)" in html
    assert "(N=3)" not in html

    ard = tlg.run_spec(tlg.load_spec(spec), ADAE_PLANNED, adsl=ADSL_PLANNED)
    big_n = ard.filter((pl.col("stat_name") == "N") & (pl.col("variable") == ""))
    assert big_n["stat"].to_list() == [2.0, 2.0]


def test_c1_273_resolve_groupby_order() -> None:
    declared = AESocPtSpec(template="aet02", columns=["TRT01P"])
    assert tlg.resolve_groupby(declared, ADAE_PLANNED.columns) == (None, "spec")
    assert tlg.resolve_groupby(declared, ADAE_PLANNED.columns, "TRTA") == ("TRTA", "flag")
    assert tlg.resolve_groupby(AESocPtSpec(), ADAE_PLANNED.columns) == ("TRTA", "detected")


def test_c1_273_mcp_groups_by_the_spec_columns(tmp_path: Path) -> None:
    pytest.importorskip("mcp", reason="mcp extra (mcp SDK) not installed")
    from fleet.mcp_server import fleet_tlg_run

    ADAE_PLANNED.write_parquet(tmp_path / "adae.parquet")
    ADSL_PLANNED.write_parquet(tmp_path / "adsl.parquet")
    spec = tmp_path / "aet02.yaml"
    spec.write_text("template: aet02\ncolumns: [TRT01P]\n", encoding="utf-8")
    html = fleet_tlg_run(
        str(spec), str(tmp_path / "adae.parquet"), adsl_path=str(tmp_path / "adsl.parquet")
    )
    assert "(N=2)" in html
    assert "(N=3)" not in html


# ── c1-432: a subject-level table takes the ADSL arm (ADR-0046) ─────────


ADSL_ARMS = pl.from_repr("""
┌─────────┬─────────┬─────────┬──────────────┬─────────┬───────┬────────┬────────┬─────┬─────┐
│ USUBJID ┆ TRT01P  ┆ TRT01A  ┆ EOSSTT       ┆ DCSREAS ┆ DTHFL ┆ DTHCAT ┆ SITEID ┆ AGE ┆ SEX │
│ ---     ┆ ---     ┆ ---     ┆ ---          ┆ ---     ┆ ---   ┆ ---    ┆ ---    ┆ --- ┆ --- │
│ str     ┆ str     ┆ str     ┆ str          ┆ str     ┆ str   ┆ str    ┆ str    ┆ i64 ┆ str │
╞═════════╪═════════╪═════════╪══════════════╪═════════╪═══════╪════════╪════════╪═════╪═════╡
│ S1      ┆ Drug A  ┆ Drug A  ┆ COMPLETED    ┆ null    ┆ N     ┆ null   ┆ 701    ┆ 40  ┆ F   │
│ S2      ┆ Placebo ┆ Drug A  ┆ DISCONTINUED ┆ DEATH   ┆ Y     ┆ AE     ┆ 701    ┆ 50  ┆ M   │
│ S3      ┆ Placebo ┆ Placebo ┆ COMPLETED    ┆ null    ┆ N     ┆ null   ┆ 702    ┆ 60  ┆ F   │
│ S4      ┆ Drug A  ┆ Drug A  ┆ COMPLETED    ┆ null    ┆ N     ┆ null   ┆ 702    ┆ 70  ┆ M   │
└─────────┴─────────┴─────────┴──────────────┴─────────┴───────┴────────┴────────┴─────┴─────┘
""")

SUBJECT_LEVEL = ["dm.t_summary", "ds.t_summary", "ds.t_deaths", "ds.t_enrollment"]


def _big_n(ard: pl.DataFrame) -> dict[str, float]:
    rows = ard.filter((pl.col("stat_name") == "N") & (pl.col("variable") == ""))
    return dict(zip(rows["group1_level"], rows["stat"]))


@pytest.mark.parametrize("method", SUBJECT_LEVEL)
def test_c1_432_subject_level_tables_default_to_trt01a(method: str) -> None:
    ns, name = method.split(".")
    ard = getattr(getattr(ADSL_ARMS.tlg, ns), name)()
    assert set(ard["group1"].to_list()) == {"TRT01A"}
    assert _big_n(ard) == {"Drug A": 3.0, "Placebo": 1.0}


@pytest.mark.parametrize("method", SUBJECT_LEVEL)
def test_c1_432_without_trt01a_the_planned_arm_is_taken(method: str) -> None:
    adsl = ADSL_ARMS.drop("TRT01A").with_columns(pl.col("TRT01P").alias("TRTA"))
    ns, name = method.split(".")
    ard = getattr(getattr(adsl.tlg, ns), name)()
    assert set(ard["group1"].to_list()) == {"TRT01P"}
    assert _big_n(ard) == {"Drug A": 2.0, "Placebo": 2.0}


def test_c1_432_a_named_arm_never_falls_back() -> None:
    adsl = ADSL_ARMS.drop("TRT01A")
    with pytest.raises(SchemaError, match="TRT01A"):
        adsl.tlg.dm.t_summary(spec=DMSummarySpec(columns=["TRT01A"]))


def test_c1_432_dm_check_reads_the_fallback_arm() -> None:
    adsl = ADSL_ARMS.drop("TRT01A")
    assert not [m for m in adsl.tlg.dm.check() if m.startswith("MISSING COLUMNS")]
    assert any("TRT01A" in m for m in adsl.tlg.dm.check(groupby="TRT01A"))


def test_c1_432_cli_dm_table_takes_trt01a(tmp_path: Path) -> None:
    adsl = ADSL_ARMS.with_columns(pl.col("TRT01P").alias("TRTA"))
    adsl.write_parquet(tmp_path / "adsl.parquet")
    spec = tmp_path / "dmt01.yaml"
    spec.write_text("template: dmt01\n", encoding="utf-8")
    assert tlg.resolve_groupby(tlg.load_spec(spec), adsl.columns) == (None, "spec")
    argv = ["tlg", "run", str(spec), "--data", str(tmp_path / "adsl.parquet")]
    argv += ["--adsl", str(tmp_path / "adsl.parquet"), "-o", str(tmp_path / "out")]
    assert _run(argv) == 0
    html = (tmp_path / "out" / "dmt01.html").read_text(encoding="utf-8")
    assert "(N=3)" in html
    assert "(N=2)" not in html


def test_c1_432_cli_export_adsl_groupby(tmp_path: Path) -> None:
    ADAE_TRTA.write_parquet(tmp_path / "adae.parquet")
    ADSL_TRT01A.write_parquet(tmp_path / "adsl.parquet")
    out = tmp_path / "ae.html"
    argv = ["tlg", "export", "--domain", "ae", "--data", str(tmp_path / "adae.parquet")]
    argv += ["--adsl", str(tmp_path / "adsl.parquet"), "-o", str(out)]
    assert _run(argv) == 1
    assert _run([*argv, "--adsl-groupby", "TRT01A"]) == 0
    assert "(N=1)" in out.read_text(encoding="utf-8")


def test_c1_432_cli_export_dm_takes_trt01a(tmp_path: Path) -> None:
    adsl = ADSL_ARMS.with_columns(pl.col("TRT01P").alias("TRTA"))
    adsl.write_parquet(tmp_path / "adsl.parquet")
    out = tmp_path / "dm.html"
    argv = ["tlg", "export", "--domain", "dm", "--data", str(tmp_path / "adsl.parquet")]
    argv += ["--adsl", str(tmp_path / "adsl.parquet"), "-o", str(out)]
    assert _run(argv) == 0
    assert "(N=3)" in out.read_text(encoding="utf-8")


# ── c1-435: continuous statistics need a numeric value column ───────────


ADVS_TEXT = pl.from_repr("""
┌─────────┬──────┬─────────┬───────┬────────┬──────┐
│ USUBJID ┆ TRTA ┆ PARAMCD ┆ PARAM ┆ AVISIT ┆ AVAL │
│ ---     ┆ ---  ┆ ---     ┆ ---   ┆ ---    ┆ ---  │
│ str     ┆ str  ┆ str     ┆ str   ┆ str    ┆ str  │
╞═════════╪══════╪═════════╪═══════╪════════╪══════╡
│ S1      ┆ A    ┆ SYSBP   ┆ SYSBP ┆ WEEK 2 ┆ 9    │
│ S2      ┆ A    ┆ SYSBP   ┆ SYSBP ┆ WEEK 2 ┆ 10   │
│ S3      ┆ A    ┆ SYSBP   ┆ SYSBP ┆ WEEK 2 ┆ 100  │
└─────────┴──────┴─────────┴───────┴────────┴──────┘
""")

ADSL_A3 = pl.from_repr("""
┌─────────┬──────┐
│ USUBJID ┆ TRTA │
│ ---     ┆ ---  │
│ str     ┆ str  │
╞═════════╪══════╡
│ S1      ┆ A    │
│ S2      ┆ A    │
│ S3      ┆ A    │
└─────────┴──────┘
""")


def test_c1_435_text_aval_stops_the_continuous_summary() -> None:
    with pytest.raises(SchemaError, match=r"numeric AVAL; AVAL is String.*cast\(pl.Float64\)"):
        ADVS_TEXT.tlg.vs.t_summary(groupby="TRTA", adsl=ADSL_A3)


def test_c1_435_cast_aval_gives_the_numbers() -> None:
    advs = ADVS_TEXT.with_columns(pl.col("AVAL").cast(pl.Float64))
    ard = advs.tlg.vs.t_summary(groupby="TRTA", adsl=ADSL_A3)
    assert _stat(ard, arm="A", level="WEEK 2", stat="median") == 10.0
    assert _stat(ard, arm="A", level="WEEK 2", stat="min") == 9.0
    assert _stat(ard, arm="A", level="WEEK 2", stat="max") == 100.0


def test_c1_435_a_count_on_text_aval_still_runs() -> None:
    spec = VSSummarySpec(statistics=[Statistic.N_SUBJECTS])
    ard = ADVS_TEXT.tlg.vs.t_summary(groupby="TRTA", adsl=ADSL_A3, spec=spec)
    assert _stat(ard, arm="A", level="WEEK 2") == 3


def test_c1_435_text_age_stops_the_dm_table() -> None:
    adsl = ADSL_TRT01A.with_columns(pl.col("AGE").cast(pl.Utf8))
    with pytest.raises(SchemaError, match="numeric AGE"):
        adsl.tlg.dm.t_summary(groupby="TRT01A")


# ── c1-436: a row field absent from the data stops the table ────────────


ADAE_NERV = pl.from_repr("""
┌─────────┬──────┬──────────┬──────────┐
│ USUBJID ┆ TRTA ┆ AEBODSYS ┆ AEDECOD  │
│ ---     ┆ ---  ┆ ---      ┆ ---      │
│ str     ┆ str  ┆ str      ┆ str      │
╞═════════╪══════╪══════════╪══════════╡
│ S1      ┆ A    ┆ NERV     ┆ HEADACHE │
│ S2      ┆ A    ┆ NERV     ┆ MIGRAINE │
└─────────┴──────┴──────────┴──────────┘
""")


def test_c1_436_a_row_field_typo_stops_the_table() -> None:
    spec = AESocPtSpec(template="aet02", rows=[Row(field="AEBODSYS"), Row(field="AEDECODE")])
    with pytest.raises(SchemaError, match=r"Row field\(s\) \['AEDECODE'\]"):
        tlg.run_spec(spec, ADAE_NERV, adsl=ADSL_A3)


def test_c1_436_an_explicit_dm_variable_must_exist() -> None:
    with pytest.raises(SchemaError, match="SEXX"):
        ADSL_TRT01A.tlg.dm.t_summary(
            groupby="TRT01A", spec=DMSummarySpec(categorical_vars=["SEXX"])
        )
    with pytest.raises(SchemaError, match="AAGE"):
        ADSL_TRT01A.tlg.dm.t_summary(
            groupby="TRT01A", spec=DMSummarySpec(continuous_vars={"AAGE": "Age (yr)"})
        )


def test_c1_436_default_dm_rows_absent_from_adsl_are_left_out() -> None:
    ard = ADSL_TRT01A.tlg.dm.t_summary(groupby="TRT01A")
    assert set(ard["variable"].unique()) == {"", "SEX", "AGE"}


def test_c1_436_a_listing_column_typo_stops_the_listing() -> None:
    spec = AEListingSpec(columns=[Column(field="USUBJID"), Column(field="AEDECODE")])
    with pytest.raises(SchemaError, match="AEDECODE"):
        ADAE_NERV.tlg.ae.l_listing(spec=spec)


# ── c1-442: a null category gets a Missing row ──────────────────────────


ADSL_RACE = pl.from_repr("""
┌─────────┬──────┬───────┬─────┬─────┐
│ USUBJID ┆ TRTA ┆ RACE  ┆ AGE ┆ SEX │
│ ---     ┆ ---  ┆ ---   ┆ --- ┆ --- │
│ str     ┆ str  ┆ str   ┆ i64 ┆ str │
╞═════════╪══════╪═══════╪═════╪═════╡
│ S1      ┆ A    ┆ ASIAN ┆ 40  ┆ F   │
│ S2      ┆ A    ┆ WHITE ┆ 41  ┆ M   │
│ S3      ┆ A    ┆ WHITE ┆ 42  ┆ F   │
│ S4      ┆ A    ┆ null  ┆ 43  ┆ M   │
└─────────┴──────┴───────┴─────┴─────┘
""")


def test_c1_442_dm_null_race_counts_in_a_missing_row_last() -> None:
    ard = ADSL_RACE.tlg.dm.t_summary(groupby="TRTA", adsl=ADSL_RACE)
    race = ard.filter((pl.col("variable") == "RACE") & (pl.col("stat_name") == "pct"))
    assert race["variable_level"].to_list() == ["ASIAN", "WHITE", "Missing"]
    assert race["stat_fmt"].to_list() == ["25.0", "50.0", "25.0"]


def test_c1_442_blank_counts_as_null() -> None:
    adsl = ADSL_RACE.with_columns(pl.col("RACE").fill_null("  "))
    ard = adsl.tlg.dm.t_summary(groupby="TRTA", adsl=adsl)
    assert _stat(ard, arm="A", level="Missing", variable="RACE") == 1


def test_c1_442_label_none_writes_the_warning_column() -> None:
    spec = DMSummarySpec(missing=MissingLevel(columns=["RACE"], label=None))
    with pytest.warns(UserWarning, match=r"RACE is null or blank for 1 subject"):
        ard = ADSL_RACE.tlg.dm.t_summary(groupby="TRTA", adsl=ADSL_RACE, spec=spec)
    race = ard.filter(pl.col("variable") == "RACE")
    assert "Missing" not in race["variable_level"].to_list()
    assert race["warning"].null_count() == 0
    assert ard.filter(pl.col("variable") == "SEX")["warning"].null_count() > 0


def test_c1_442_missing_none_round_trips_through_yaml() -> None:
    spec = DMSummarySpec(missing=None)
    assert DMSummarySpec.from_yaml(spec.to_yaml()).missing is None


def test_c1_442_builder_missing_verb() -> None:
    ard = (
        ADSL_RACE.tlg.dm.population(ADSL_RACE)
        .by("TRTA")
        .missing(["RACE"], label="Not reported")
        .to_ard()
    )
    assert _stat(ard, arm="A", level="Not reported", variable="RACE") == 1


ADAE_SEV = pl.from_repr("""
┌─────────┬──────┬──────────┬──────────┬───────┐
│ USUBJID ┆ TRTA ┆ AEBODSYS ┆ AEDECOD  ┆ AESEV │
│ ---     ┆ ---  ┆ ---      ┆ ---      ┆ ---   │
│ str     ┆ str  ┆ str      ┆ str      ┆ str   │
╞═════════╪══════╪══════════╪══════════╪═══════╡
│ S1      ┆ A    ┆ SKIN     ┆ RASH     ┆ MILD  │
│ S1      ┆ A    ┆ SKIN     ┆ ITCH     ┆ null  │
│ S2      ┆ A    ┆ SKIN     ┆ RASH     ┆ null  │
└─────────┴──────┴──────────┴──────────┴───────┘
""")


def test_c1_442_aet03_null_intensity_partitions_the_soc() -> None:
    adsl = ADSL_RACE.select("USUBJID", "TRTA")
    ard = ADAE_SEV.tlg.ae.t_severity(groupby="TRTA", adsl=adsl)
    leaf = ard.filter((pl.col("variable") == "AESEV") & (pl.col("stat_name") == "n"))
    counts = dict(zip(leaf["variable_level"], leaf["stat"]))
    # S1 has MILD and a null: the ranked value wins.  S2 has only a null.
    assert counts == {"MILD": 1.0, "Missing": 1.0}
    assert _stat(ard, arm="A", level="SKIN") == 2


# ── c1-451 / c1-452: SOC row count and the event count ──────────────────


ADAE_EVENTS = pl.from_repr("""
┌─────────┬──────┬──────────┬──────────┐
│ USUBJID ┆ TRTA ┆ AEBODSYS ┆ AEDECOD  │
│ ---     ┆ ---  ┆ ---      ┆ ---      │
│ str     ┆ str  ┆ str      ┆ str      │
╞═════════╪══════╪══════════╪══════════╡
│ S1      ┆ A    ┆ NERV     ┆ HEADACHE │
│ S1      ┆ A    ┆ NERV     ┆ HEADACHE │
│ S1      ┆ A    ┆ NERV     ┆ MIGRAINE │
│ S2      ┆ A    ┆ NERV     ┆ HEADACHE │
└─────────┴──────┴──────────┴──────────┘
""")

ADSL_A4 = pl.from_repr("""
┌─────────┬──────┐
│ USUBJID ┆ TRTA │
│ ---     ┆ ---  │
│ str     ┆ str  │
╞═════════╪══════╡
│ S1      ┆ A    │
│ S2      ┆ A    │
│ S3      ┆ A    │
│ S4      ┆ A    │
└─────────┴──────┘
""")


def test_c1_451_soc_row_prints_its_subject_count() -> None:
    model = ard_to_table_model(ADAE_EVENTS.tlg.ae.t_soc_pt(groupby="TRTA", adsl=ADSL_A4))
    soc = _row(model, "NERV")
    assert soc.row_type == "group"
    assert soc.cells == {"A": "2 (50.0%)"}


def test_c1_451_paramcd_stub_of_continuous_rows_stays_blank() -> None:
    advs = ADVS_TEXT.with_columns(pl.col("AVAL").cast(pl.Float64))
    model = ard_to_table_model(advs.tlg.vs.t_summary(groupby="TRTA", adsl=ADSL_A3))
    stub = next(r for r in model.rows if r.row_type == "group")
    assert set(stub.cells.values()) == {""}


def test_c1_451_a_page_never_ends_on_a_soc_row() -> None:
    model = ard_to_table_model(ADAE_ASEV.tlg.ae.t_soc_pt(groupby="TRTA", adsl=ADSL_A12))
    assert [r.label for r in model.rows] == ["GI", "DIAR", "NAUS", "NERV", "HEAD"]
    pages = tlg.paginate(model, rows_per_page=4)
    assert [[r.label for r in p.rows] for p in pages] == [
        ["GI", "DIAR", "NAUS"],
        ["NERV", "HEAD"],
    ]


def test_c1_452_event_count_prints_beside_n_pct() -> None:
    spec = AESocPtSpec(statistics=["n_subjects", "n_pct", "n_events"])
    ard = ADAE_EVENTS.tlg.ae.t_soc_pt(groupby="TRTA", adsl=ADSL_A4, spec=spec)
    model = ard_to_table_model(ard)
    assert _row(model, "NERV").cells == {"A": "2 (50.0%) 4"}
    assert _row(model, "HEADACHE").cells == {"A": "2 (50.0%) 3"}
    assert _row(model, "MIGRAINE").cells == {"A": "1 (25.0%) 1"}
    assert any("E = number of events" in f for f in model.metadata.footnotes)
    assert "2 (50.0%) 3" in render_html(model)


def test_c1_452_event_count_in_the_n_only_branch() -> None:
    spec = AESocPtSpec(statistics=["n_subjects", "n_events"])
    ard = ADAE_EVENTS.tlg.ae.t_soc_pt(groupby="TRTA", adsl=ADSL_A4, spec=spec)
    assert _row(ard_to_table_model(ard), "HEADACHE").cells == {"A": "2 3"}


# ── c1-453 / c2-968: LBT04 cells and ANRIND codes ───────────────────────


ADLB_ABN = pl.from_repr("""
┌─────────┬──────┬─────────┬───────┬─────────┬────────┬────────┐
│ USUBJID ┆ TRTA ┆ PARAMCD ┆ ABLFL ┆ ONTRTFL ┆ BNRIND ┆ ANRIND │
│ ---     ┆ ---  ┆ ---     ┆ ---   ┆ ---     ┆ ---    ┆ ---    │
│ str     ┆ str  ┆ str     ┆ str   ┆ str     ┆ str    ┆ str    │
╞═════════╪══════╪═════════╪═══════╪═════════╪════════╪════════╡
│ S01     ┆ P    ┆ ALT     ┆ Y     ┆ null    ┆ NORMAL ┆ NORMAL │
│ S01     ┆ P    ┆ ALT     ┆ null  ┆ Y       ┆ NORMAL ┆ HIGH   │
│ S02     ┆ P    ┆ ALT     ┆ Y     ┆ null    ┆ HIGH   ┆ HIGH   │
│ S02     ┆ P    ┆ ALT     ┆ null  ┆ Y       ┆ HIGH   ┆ HIGH   │
│ S03     ┆ P    ┆ ALT     ┆ Y     ┆ null    ┆ NORMAL ┆ NORMAL │
│ S03     ┆ P    ┆ ALT     ┆ null  ┆ Y       ┆ NORMAL ┆ NORMAL │
│ S04     ┆ Q    ┆ ALT     ┆ Y     ┆ null    ┆ HIGH   ┆ HIGH   │
│ S04     ┆ Q    ┆ ALT     ┆ null  ┆ Y       ┆ HIGH   ┆ HIGH   │
└─────────┴──────┴─────────┴───────┴─────────┴────────┴────────┘
""")

ADSL_PQ = pl.from_repr("""
┌─────────┬──────┐
│ USUBJID ┆ TRTA │
│ ---     ┆ ---  │
│ str     ┆ str  │
╞═════════╪══════╡
│ S01     ┆ P    │
│ S02     ┆ P    │
│ S03     ┆ P    │
│ S04     ┆ Q    │
└─────────┴──────┘
""")


def test_c1_453_lbt04_cells_show_the_cell_denominator() -> None:
    model = ard_to_table_model(ADLB_ABN.tlg.lb.t_abnormal(groupby="TRTA", adsl=ADSL_PQ))
    assert _row(model, "High").cells == {"P": "1/2 (50.0%)", "Q": "0/0"}
    assert _row(model, "Low").cells == {"P": "0/3", "Q": "0/1"}


ADLB_CODES = pl.from_repr("""
┌─────────┬──────┬─────────┬───────┬─────────┬────────┬────────┐
│ USUBJID ┆ TRTA ┆ PARAMCD ┆ ABLFL ┆ ONTRTFL ┆ BNRIND ┆ ANRIND │
│ ---     ┆ ---  ┆ ---     ┆ ---   ┆ ---     ┆ ---    ┆ ---    │
│ str     ┆ str  ┆ str     ┆ str   ┆ str     ┆ str    ┆ str    │
╞═════════╪══════╪═════════╪═══════╪═════════╪════════╪════════╡
│ S1      ┆ A    ┆ ALT     ┆ Y     ┆ null    ┆ N      ┆ N      │
│ S1      ┆ A    ┆ ALT     ┆ null  ┆ Y       ┆ N      ┆ H      │
│ S2      ┆ A    ┆ ALT     ┆ Y     ┆ null    ┆ H      ┆ H      │
│ S2      ┆ A    ┆ ALT     ┆ null  ┆ Y       ┆ H      ┆ H      │
│ S3      ┆ A    ┆ ALT     ┆ Y     ┆ null    ┆ N      ┆ N      │
│ S3      ┆ A    ┆ ALT     ┆ null  ┆ Y       ┆ N      ┆ L      │
└─────────┴──────┴─────────┴───────┴─────────┴────────┴────────┘
""")


def test_c2_968_unknown_anrind_codes_stop_lbt04() -> None:
    with pytest.raises(SchemaError, match=r"ANRIND has codes \['H', 'L'\].*low_values"):
        ADLB_CODES.tlg.lb.t_abnormal(groupby="TRTA", adsl=ADSL_A3)


def test_c2_968_study_codes_give_the_tern_counts() -> None:
    spec = LBAbnormalSpec(low_values=["L"], high_values=["H"])
    ard = ADLB_CODES.tlg.lb.t_abnormal(groupby="TRTA", adsl=ADSL_A3, spec=spec)
    assert _stat(ard, arm="A", level="Low") == 1
    assert _stat(ard, arm="A", level="Low", stat="N") == 3
    assert _stat(ard, arm="A", level="High") == 1
    assert _stat(ard, arm="A", level="High", stat="N") == 2


@pytest.mark.parametrize("code", ["NORMAL", "N"])
def test_c2_968_all_normal_data_gives_zero(code: str) -> None:
    adlb = ADLB_CODES.with_columns(pl.lit(code).alias("ANRIND"), pl.lit(code).alias("BNRIND"))
    spec = LBAbnormalSpec(low_values=["L"], high_values=["H"]) if code == "N" else None
    ard = adlb.tlg.lb.t_abnormal(groupby="TRTA", adsl=ADSL_A3, spec=spec)
    assert _stat(ard, arm="A", level="High") == 0


# ── c1-798 / c1-800: the worst-case reduction follows the pools and rows ─


ADAE_CROSS = pl.from_repr("""
┌─────────┬──────┬──────────┬──────────┬────────┐
│ USUBJID ┆ TRTA ┆ AEBODSYS ┆ AEDECOD  ┆ AESEV  │
│ ---     ┆ ---  ┆ ---      ┆ ---      ┆ ---    │
│ str     ┆ str  ┆ str      ┆ str      ┆ str    │
╞═════════╪══════╪══════════╪══════════╪════════╡
│ S1      ┆ A    ┆ NERV     ┆ HEADACHE ┆ MILD   │
│ S1      ┆ B    ┆ NERV     ┆ HEADACHE ┆ SEVERE │
│ S2      ┆ A    ┆ NERV     ┆ MIGRAINE ┆ MILD   │
└─────────┴──────┴──────────┴──────────┴────────┘
""")

ADSL_CROSS = pl.from_repr("""
┌─────────┬──────┐
│ USUBJID ┆ TRTA │
│ ---     ┆ ---  │
│ str     ┆ str  │
╞═════════╪══════╡
│ S1      ┆ A    │
│ S2      ┆ A    │
│ S3      ┆ B    │
└─────────┴──────┘
""")


def test_c1_798_total_reduces_after_the_pool() -> None:
    spec = AESeveritySpec(
        pools=[GroupPool(label="Total", arms="*")],
        statistics=[Statistic.N_SUBJECTS, Statistic.N_PCT, Statistic.N_EVENTS],
    )
    ard = ADAE_CROSS.tlg.ae.t_severity(groupby="TRTA", adsl=ADSL_CROSS, spec=spec)
    assert _stat(ard, arm="Total", level="NERV") == 2
    assert _stat(ard, arm="Total", level="MILD") == 1
    assert _stat(ard, arm="Total", level="SEVERE") == 1
    # The SOC row counts every record; the reduced level has no event count.
    assert _stat(ard, arm="Total", level="NERV", stat="n_events") == 3
    assert ard.filter(
        (pl.col("variable") == "AESEV") & (pl.col("stat_name") == "n_events")
    ).is_empty()


def test_c1_798_header_rows_count_every_record() -> None:
    spec = AESeveritySpec(
        header_rows=[tlg.OverallStat(label="Any MILD", filter='pl.col("AESEV") == "MILD"')]
    )
    ard = ADAE_CROSS.tlg.ae.t_severity(groupby="TRTA", adsl=ADSL_CROSS, spec=spec)
    # S1 has a MILD record in arm A although its worst intensity in B is SEVERE.
    assert _stat(ard, arm="A", level="Any MILD") == 2


ADAE_ASEV = pl.from_repr("""
┌─────────┬──────┬──────────┬─────────┬──────────┬──────────┐
│ USUBJID ┆ TRTA ┆ AEBODSYS ┆ AEDECOD ┆ AESEV    ┆ ASEV     │
│ ---     ┆ ---  ┆ ---      ┆ ---     ┆ ---      ┆ ---      │
│ str     ┆ str  ┆ str      ┆ str     ┆ str      ┆ str      │
╞═════════╪══════╪══════════╪═════════╪══════════╪══════════╡
│ A1      ┆ A    ┆ GI       ┆ DIAR    ┆ MILD     ┆ SEVERE   │
│ A1      ┆ A    ┆ GI       ┆ NAUS    ┆ SEVERE   ┆ MILD     │
│ A1      ┆ A    ┆ NERV     ┆ HEAD    ┆ MODERATE ┆ MODERATE │
│ A2      ┆ A    ┆ NERV     ┆ HEAD    ┆ MILD     ┆ MILD     │
└─────────┴──────┴──────────┴─────────┴──────────┴──────────┘
""")

ADSL_A12 = pl.from_repr("""
┌─────────┬──────┐
│ USUBJID ┆ TRTA │
│ ---     ┆ ---  │
│ str     ┆ str  │
╞═════════╪══════╡
│ A1      ┆ A    │
│ A2      ┆ A    │
└─────────┴──────┘
""")


def test_c1_800_reduction_by_preferred_term() -> None:
    spec = AESeveritySpec(rows=[Row(field="AEDECOD"), Row(field="AESEV")])
    ard = ADAE_ASEV.tlg.ae.t_severity(groupby="TRTA", adsl=ADSL_A12, spec=spec)
    assert _stat(ard, arm="A", level="MILD", group2_level="DIAR") == 1


def test_c1_800_overall_reduction_with_one_row() -> None:
    spec = AESeveritySpec(rows=[Row(field="AESEV")])
    ard = ADAE_ASEV.tlg.ae.t_severity(groupby="TRTA", adsl=ADSL_A12, spec=spec)
    counts = ard.filter((pl.col("variable") == "AESEV") & (pl.col("stat_name") == "n"))
    assert dict(zip(counts["variable_level"], counts["stat"])) == {"MILD": 1.0, "SEVERE": 1.0}


def test_c1_800_rank_reads_the_last_row_field() -> None:
    adae = ADAE_ASEV.drop("AESEV")
    spec = AESeveritySpec(rows=[Row(field="AEBODSYS"), Row(field="ASEV")])
    ard = adae.tlg.ae.t_severity(groupby="TRTA", adsl=ADSL_A12, spec=spec)
    assert _stat(ard, arm="A", level="SEVERE", group2_level="GI") == 1
    gi = ard.filter((pl.col("group2_level") == "GI") & (pl.col("stat_name") == "n"))
    assert gi["variable_level"].to_list() == ["SEVERE"]


def test_c1_800_empty_rows_are_refused() -> None:
    with pytest.raises(ValidationError, match="rows is empty"):
        AESeveritySpec(rows=[])


def test_c1_800_unknown_relationship_words_stop_the_table() -> None:
    adae = ADAE_ASEV.with_columns(pl.lit("POSSIBLY RELATED").alias("AEREL"))
    with pytest.raises(SchemaError, match="relationship_order"):
        adae.tlg.ae.t_relationship(groupby="TRTA", adsl=ADSL_A12)


# ── c1-803: the CM table counts every record ────────────────────────────


ADCM = pl.from_repr("""
┌─────────┬─────────┬────────┬───────────┬─────────────┐
│ USUBJID ┆ TRTA    ┆ CMCLAS ┆ CMDECOD   ┆ ATIREL      │
│ ---     ┆ ---     ┆ ---    ┆ ---       ┆ ---         │
│ str     ┆ str     ┆ str    ┆ str       ┆ str         │
╞═════════╪═════════╪════════╪═══════════╪═════════════╡
│ P1      ┆ Placebo ┆ NSAID  ┆ ASPIRIN   ┆ PRIOR       │
│ P2      ┆ Placebo ┆ NSAID  ┆ IBUPROFEN ┆ CONCOMITANT │
└─────────┴─────────┴────────┴───────────┴─────────────┘
""")


def test_c1_803_cm_counts_every_record_unless_filtered() -> None:
    adsl = ADCM.select("USUBJID", "TRTA")
    all_records = ADCM.tlg.cm.t_summary(groupby="TRTA", adsl=adsl)
    assert _stat(all_records, arm="Placebo", level="NSAID") == 2
    spec = CMSummarySpec(dataset_filter='pl.col("ATIREL") == "CONCOMITANT"')
    concomitant = ADCM.tlg.cm.t_summary(groupby="TRTA", adsl=adsl, spec=spec)
    assert _stat(concomitant, arm="Placebo", level="NSAID", stat="pct") == 50.0
    assert "prior medications included" in (tlg.CMTLGNamespace.t_summary.__doc__ or "")


# ── c2-962: a header filter on an all-blank column warns ────────────────


ADAE_BLANK = pl.from_repr("""
┌─────────┬──────┬───────┬───────┬────────┐
│ USUBJID ┆ TRTA ┆ AESER ┆ AEACN ┆ AESDTH │
│ ---     ┆ ---  ┆ ---   ┆ ---   ┆ ---    │
│ str     ┆ str  ┆ str   ┆ str   ┆ str    │
╞═════════╪══════╪═══════╪═══════╪════════╡
│ S1      ┆ A    ┆ N     ┆       ┆ N      │
│ S2      ┆ A    ┆ Y     ┆       ┆ N      │
└─────────┴──────┴───────┴───────┴────────┘
""")


def test_c2_962_blank_filter_column_warns_and_marks_the_row() -> None:
    adsl = ADSL_A12.with_columns(pl.Series("USUBJID", ["S1", "S2"]))
    label = "Subjects with at least one adverse event leading to discontinuation"
    with pytest.warns(UserWarning, match=f"filter column AEACN .*row '{label}'"):
        ard = ADAE_BLANK.tlg.ae.t_overview(groupby="TRTA", adsl=adsl)
    row = ard.filter(pl.col("variable_level") == label)
    assert row.filter(pl.col("stat_name") == "n")["stat"].item() == 0
    assert row["warning"].null_count() == 0
    others = ard.filter(pl.col("variable_level") != label)
    assert others["warning"].null_count() == others.height
    assert any("AEACN" in line for line in AEOverviewSpec().check(ADAE_BLANK))
