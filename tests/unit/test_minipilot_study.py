"""The shipped MINIPILOT study runs end to end with ``fleet run`` and ``build_dag`` (c1-347).

Seams: the ``fleet run`` command and ``build_dag``, on a copy of
``examples/minipilot``.  The raw CSV files are the study's own inputs.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from fleet import cli
from fleet.core.dag import build_dag
from fleet.core.define_spec import load_define_spec

_STUDY = Path(__file__).parents[2] / "examples" / "minipilot"
_DATASETS = ["DM", "AE", "VS", "EX", "ADSL", "ADVS", "ADAE", "ADEX"]

pytestmark = pytest.mark.skipif(not _STUDY.exists(), reason="examples/ is not shipped here")


@pytest.fixture(scope="module")
def out(tmp_path_factory: pytest.TempPathFactory) -> Path:
    study = tmp_path_factory.mktemp("run") / "minipilot"
    shutil.copytree(_STUDY, study)
    try:
        cli.main(["run", "--config", str(study / "study_config.yaml"), "--out", str(study / "out")])
    except SystemExit as exc:
        assert not exc.code
    return study / "out"


def test_fleet_run_writes_every_declared_variable_of_every_dataset(out: Path) -> None:
    for standard in ("sdtm", "adam"):
        for entry in load_define_spec(_STUDY / standard / "define.yaml").datasets or []:
            frame = pl.read_parquet(out / f"{entry.name.lower()}.parquet")
            assert frame.columns == [v.name for v in entry.variables], entry.name


def test_the_dag_of_the_same_defines_orders_and_impacts_every_dataset() -> None:
    dag = build_dag(_STUDY / "sdtm" / "define.yaml", _STUDY / "adam" / "define.yaml")

    order = [n for n in dag.execution_order() if n in _DATASETS]
    assert order.index("ADSL") < min(order.index(d) for d in ("ADVS", "ADAE", "ADEX"))
    assert set(dag.impacted_by("dm_raw")) >= {"DM", "ADSL", "ADVS", "ADAE", "ADEX"}


def test_saffl_is_n_for_the_subject_with_no_dose(out: Path) -> None:
    adsl = pl.read_parquet(out / "adsl.parquet")

    assert adsl.select("USUBJID", "SAFFL").rows() == [
        ("MINIPILOT-001", "Y"),
        ("MINIPILOT-002", "Y"),
        ("MINIPILOT-003", "N"),
    ]


def test_baseline_and_change_follow_the_study_rules(out: Path) -> None:
    """Baseline: the last non-missing AVAL on or before TRTSDT. CHG and PCHG: after TRTSDT only.

    Subject 002 has no DAY 1 value, so its baseline is the screening value.
    """
    advs = pl.read_parquet(out / "advs.parquet").select(
        "USUBJID", "VISIT", "AVAL", "ABLFL", "BASE", "CHG", "PCHG"
    )

    expected = pl.from_repr("""\
┌───────────────┬───────────┬───────┬───────┬───────┬──────┬───────────┐
│ USUBJID       ┆ VISIT     ┆ AVAL  ┆ ABLFL ┆ BASE  ┆ CHG  ┆ PCHG      │
│ ---           ┆ ---       ┆ ---   ┆ ---   ┆ ---   ┆ ---  ┆ ---       │
│ str           ┆ str       ┆ f64   ┆ str   ┆ f64   ┆ f64  ┆ f64       │
╞═══════════════╪═══════════╪═══════╪═══════╪═══════╪══════╪═══════════╡
│ MINIPILOT-001 ┆ SCREENING ┆ 120.0 ┆ null  ┆ 118.0 ┆ null ┆ null      │
│ MINIPILOT-001 ┆ DAY 1     ┆ 118.0 ┆ Y     ┆ 118.0 ┆ null ┆ null      │
│ MINIPILOT-001 ┆ WEEK 2    ┆ 125.0 ┆ null  ┆ 118.0 ┆ 7.0  ┆ 5.932203  │
│ MINIPILOT-002 ┆ SCREENING ┆ 130.0 ┆ Y     ┆ 130.0 ┆ null ┆ null      │
│ MINIPILOT-002 ┆ DAY 1     ┆ null  ┆ null  ┆ 130.0 ┆ null ┆ null      │
│ MINIPILOT-002 ┆ WEEK 2    ┆ 128.0 ┆ null  ┆ 130.0 ┆ -2.0 ┆ -1.538462 │
│ MINIPILOT-003 ┆ SCREENING ┆ 140.0 ┆ null  ┆ null  ┆ null ┆ null      │
└───────────────┴───────────┴───────┴───────┴───────┴──────┴───────────┘
""")
    assert_frame_equal(advs, expected, abs_tol=1e-6)
