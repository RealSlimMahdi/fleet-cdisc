"""ADTTE rows carry STUDYID from ADSL (c1-354)."""

from contextlib import nullcontext

import polars as pl
import pytest

from fleet.adam.tte import AE_EVENT, DEATH_EVENT, LASTALIVE_CENSOR
from fleet.core.exceptions import DerivationError

ADSL = """\
┌─────────┬─────────┬────────┬────────────┬───────┬────────────┬────────────┐
│ STUDYID ┆ USUBJID ┆ TRT01P ┆ TRTSDT     ┆ DTHFL ┆ DTHDT      ┆ LSTALVDT   │
│ ---     ┆ ---     ┆ ---    ┆ ---        ┆ ---   ┆ ---        ┆ ---        │
│ str     ┆ str     ┆ str    ┆ date       ┆ str   ┆ date       ┆ date       │
╞═════════╪═════════╪════════╪════════════╪═══════╪════════════╪════════════╡
│ S1      ┆ 01      ┆ A      ┆ 2023-01-01 ┆ Y     ┆ 2023-03-01 ┆ 2023-03-01 │
│ S1      ┆ 02      ┆ B      ┆ 2023-01-02 ┆ null  ┆ null       ┆ 2023-06-30 │
│ S1      ┆ 03      ┆ A      ┆ 2023-01-03 ┆ null  ┆ null       ┆ null       │
└─────────┴─────────┴────────┴────────────┴───────┴────────────┴────────────┘
"""

ADAE = """\
┌─────────┬─────────┬────────────┬───────┐
│ USUBJID ┆ TRTEMFL ┆ ASTDT      ┆ AESEQ │
│ ---     ┆ ---     ┆ ---        ┆ ---   │
│ str     ┆ str     ┆ date       ┆ i64   │
╞═════════╪═════════╪════════════╪═══════╡
│ 01      ┆ Y       ┆ 2023-01-10 ┆ 1     │
│ 02      ┆ Y       ┆ 2023-02-05 ┆ 1     │
└─────────┴─────────┴────────────┴───────┘
"""


def _chain(adsl: pl.DataFrame, adae: pl.DataFrame | None = None, **kwargs):
    return (
        adsl.adam.tte.pin("ADSL", adsl)
        .pin("ADAE", pl.from_repr(ADAE) if adae is None else adae)
        .param(
            "OS",
            "Overall Survival",
            start_date="TRTSDT",
            events=[DEATH_EVENT],
            censors=[LASTALIVE_CENSOR],
            **kwargs,
        )
        .param(
            "TTAE",
            "Time to First AE",
            start_date="TRTSDT",
            events=[AE_EVENT],
            censors=[LASTALIVE_CENSOR],
            **kwargs,
        )
    )


@pytest.mark.parametrize("retain", ["drop", "censor_at_start"])
def test_every_adtte_row_has_studyid(retain: str) -> None:
    with pytest.warns(UserWarning) if retain == "drop" else nullcontext():
        out = _chain(pl.from_repr(ADSL), retain=retain).to_frame()
    assert out.columns[0] == "STUDYID"
    assert out["STUDYID"].null_count() == 0
    assert set(out["PARAMCD"]) == {"OS", "TTAE"}


def test_subject_keys_with_studyid_gives_one_column() -> None:
    out = _chain(
        pl.from_repr(ADSL),
        pl.from_repr(ADAE).with_columns(pl.lit("S1").alias("STUDYID")),
        subject_keys=["STUDYID", "USUBJID"],
        retain="censor_at_start",
    ).to_frame()
    assert [c for c in out.columns if c.startswith("STUDYID")] == ["STUDYID"]
    assert out["STUDYID"].null_count() == 0


def test_set_values_to_studyid_overrides_without_right_column() -> None:
    out = _chain(
        pl.from_repr(ADSL), set_values_to={"STUDYID": "S9"}, retain="censor_at_start"
    ).to_frame()
    assert [c for c in out.columns if c.startswith("STUDYID")] == ["STUDYID"]
    assert set(out["STUDYID"]) == {"S9"}


def test_adsl_without_studyid_adds_no_column() -> None:
    out = _chain(pl.from_repr(ADSL).drop("STUDYID"), retain="censor_at_start").to_frame()
    assert "STUDYID" not in out.columns


def test_two_studyid_values_for_one_subject_raise() -> None:
    adsl = pl.concat(
        [pl.from_repr(ADSL), pl.from_repr(ADSL).head(1).with_columns(pl.lit("S2").alias("STUDYID"))]
    )
    with pytest.raises(DerivationError, match='subject_keys=\\["STUDYID", "USUBJID"\\]'):
        _chain(adsl, retain="censor_at_start")


def test_join_adsl_after_param_adds_treatment() -> None:
    out = _chain(pl.from_repr(ADSL), retain="censor_at_start").join_adsl("TRT01P").to_frame()
    assert out["TRT01P"].null_count() == 0


def test_join_adsl_of_a_column_on_the_frame_raises() -> None:
    ns = _chain(pl.from_repr(ADSL), retain="censor_at_start")
    with pytest.raises(DerivationError, match="on both sides of the join"):
        ns.join_adsl("STUDYID")
