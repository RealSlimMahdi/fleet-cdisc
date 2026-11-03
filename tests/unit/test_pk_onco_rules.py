"""Alpha audit package E: BLQ text in PCSTRESC (c1-394) and confirmed response by group (c1-405)."""

from __future__ import annotations

import polars as pl
import pytest

import fleet  # noqa: F401
from fleet.core.exceptions import DerivationError

PC = """\
┌─────┬──────────┬──────────┬────────┐
│ ROW ┆ PCSTRESC ┆ PCSTRESN ┆ PCLLOQ │
│ --- ┆ ---      ┆ ---      ┆ ---    │
│ str ┆ str      ┆ f64      ┆ f64    │
╞═════╪══════════╪══════════╪════════╡
│ LT  ┆ <0.1     ┆ null     ┆ 0.1    │
│ BLQ ┆ BLQ      ┆ null     ┆ 0.1    │
│ LTB ┆ <BLQ     ┆ null     ┆ 0.1    │
│ BQL ┆ bql      ┆ null     ┆ 0.1    │
│ NUM ┆ 0.05     ┆ 0.05     ┆ 0.1    │
│ OK  ┆ 2.5      ┆ 2.5      ┆ 0.1    │
│ ND  ┆ null     ┆ null     ┆ 0.1    │
│ GT  ┆ >1000    ┆ null     ┆ 0.1    │
│ ALQ ┆ ALQ      ┆ null     ┆ 0.1    │
│ NOL ┆ BLQ      ┆ null     ┆ null   │
│ NQ  ┆ NQ       ┆ null     ┆ 0.1    │
└─────┴──────────┴──────────┴────────┘
"""

#        LT    BLQ   LTB   BQL   NUM   OK    ND    GT       ALQ    NOL   NQ
BLQFL = ["Y", "Y", "Y", "Y", "Y", None, None, None, None, "Y", None]
BLQFN = [1, 1, 1, 1, 1, 0, 0, 0, 0, 1, 0]
HALF = [0.05, 0.05, 0.05, 0.05, 0.05, 2.5, None, None, None, None, None]
ZERO = [0.0, 0.0, 0.0, 0.0, 0.0, 2.5, None, None, None, 0.0, None]
LLOQ = [0.1, 0.1, 0.1, 0.1, 0.1, 2.5, None, None, None, None, None]
CAT = ["BLQ", "BLQ", "BLQ", "BLQ", "BLQ", "2.5", None, ">1000", "ALQ", "BLQ", "NQ"]


def _pk():
    return pl.from_repr(PC).adam.pk


def test_blq_flag_reads_the_text() -> None:
    out = _pk().blq_flag("BLQFL", conc_col="PCSTRESN", lloq_col="PCLLOQ").to_frame()
    assert out["BLQFL"].to_list() == BLQFL


def test_blqfn_reads_the_text() -> None:
    out = _pk().blqfn("BLQFN", conc_col="PCSTRESN", lloq_col="PCLLOQ").to_frame()
    assert out["BLQFN"].to_list() == BLQFN


@pytest.mark.parametrize(
    ("method", "expected"), [("half_lloq", HALF), ("zero", ZERO), ("lloq", LLOQ)]
)
def test_blq_impute_reads_the_text(method: str, expected: list) -> None:
    out = _pk().blq_impute("AVAL", conc_col="PCSTRESN", lloq_col="PCLLOQ", method=method).to_frame()
    assert out["AVAL"].to_list() == expected


def test_avalcat_keeps_the_text_of_a_record_that_is_not_blq() -> None:
    out = _pk().avalcat("AVALCAT1", conc_col="PCSTRESN", lloq_col="PCLLOQ").to_frame()
    assert out["AVALCAT1"].to_list() == CAT


def test_numeric_below_lloq_false_lets_only_the_text_decide() -> None:
    out = (
        _pk()
        .blq_flag("BLQFL", conc_col="PCSTRESN", lloq_col="PCLLOQ", numeric_below_lloq=False)
        .blq_impute("AVAL", conc_col="PCSTRESN", lloq_col="PCLLOQ", numeric_below_lloq=False)
        .avalcat("AVALCAT1", conc_col="PCSTRESN", lloq_col="PCLLOQ", numeric_below_lloq=False)
        .to_frame()
        .filter(pl.col("ROW") == "NUM")
    )
    assert (out["BLQFL"][0], out["AVAL"][0], out["AVALCAT1"][0]) == (None, 0.05, "0.05")


def test_blq_text_replaces_the_default_list() -> None:
    pc = pl.from_repr("""\
┌─────────────┬──────────┬────────┐
│ PCSTRESC    ┆ PCSTRESN ┆ PCLLOQ │
│ ---         ┆ ---      ┆ ---    │
│ str         ┆ f64      ┆ f64    │
╞═════════════╪══════════╪════════╡
│ BELOW LIMIT ┆ null     ┆ 0.1    │
│ BLQ         ┆ null     ┆ 0.1    │
└─────────────┴──────────┴────────┘
""")
    out = pc.adam.pk.blq_flag(
        "BLQFL", conc_col="PCSTRESN", lloq_col="PCLLOQ", blq_text=r"(?i)^below limit$"
    ).to_frame()
    assert out["BLQFL"].to_list() == ["Y", None]


def test_a_frame_with_no_text_column_stops() -> None:
    pc = pl.from_repr(PC).drop("PCSTRESC")
    with pytest.raises(DerivationError, match="text_col=None"):
        pc.adam.pk.blq_flag("BLQFL", conc_col="PCSTRESN", lloq_col="PCLLOQ")


def test_text_col_none_states_numeric_results_only() -> None:
    pc = pl.from_repr(PC).drop("PCSTRESC")
    out = pc.adam.pk.blq_flag(
        "BLQFL", conc_col="PCSTRESN", lloq_col="PCLLOQ", text_col=None
    ).to_frame()
    assert out["BLQFL"].to_list() == [None, None, None, None, "Y"] + [None] * 6


# ── confirmed_response_flag joins on every by column (c1-405) ─────────────────


def _flagged_groups(out: pl.DataFrame, by: list[str]) -> set[tuple]:
    return set(out.filter(pl.col("CNFFL") == "Y").select(by).unique().rows())


def test_confirmed_response_uses_every_by_column() -> None:
    rs = pl.from_repr("""\
┌─────────┬─────────┬──────────┬────────────┐
│ STUDYID ┆ USUBJID ┆ OVRLRESP ┆ ADT        │
│ ---     ┆ ---     ┆ ---      ┆ ---        │
│ str     ┆ str     ┆ str      ┆ date       │
╞═════════╪═════════╪══════════╪════════════╡
│ ST1     ┆ S1      ┆ PR       ┆ 2024-01-01 │
│ ST1     ┆ S1      ┆ PR       ┆ 2024-02-05 │
│ ST1     ┆ S2      ┆ PR       ┆ 2024-01-01 │
│ ST1     ┆ S2      ┆ SD       ┆ 2024-02-05 │
└─────────┴─────────┴──────────┴────────────┘
""")
    by = ["STUDYID", "USUBJID"]
    out = rs.adam.onco.confirmed_response_flag(
        "CNFFL", source="OVRLRESP", date_col="ADT", by=by
    ).to_frame()
    assert _flagged_groups(out, by) == {("ST1", "S1")}


def test_confirmed_response_keeps_assessors_apart() -> None:
    rs = pl.from_repr("""\
┌─────────┬─────────┬──────────┬────────────┐
│ USUBJID ┆ PARAMCD ┆ OVRLRESP ┆ ADT        │
│ ---     ┆ ---     ┆ ---      ┆ ---        │
│ str     ┆ str     ┆ str      ┆ date       │
╞═════════╪═════════╪══════════╪════════════╡
│ S1      ┆ INV     ┆ PR       ┆ 2024-01-01 │
│ S1      ┆ INV     ┆ PR       ┆ 2024-02-05 │
│ S1      ┆ IRC     ┆ PR       ┆ 2024-01-01 │
│ S1      ┆ IRC     ┆ PD       ┆ 2024-02-05 │
└─────────┴─────────┴──────────┴────────────┘
""")
    by = ["USUBJID", "PARAMCD"]
    out = rs.adam.onco.confirmed_response_flag(
        "CNFFL", source="OVRLRESP", date_col="ADT", by=by
    ).to_frame()
    assert _flagged_groups(out, by) == {("S1", "INV")}


def test_confirmed_response_on_a_null_by_value() -> None:
    rs = pl.from_repr("""\
┌─────────┬─────────┬──────────┬────────────┐
│ USUBJID ┆ PARQUAL ┆ OVRLRESP ┆ ADT        │
│ ---     ┆ ---     ┆ ---      ┆ ---        │
│ str     ┆ str     ┆ str      ┆ date       │
╞═════════╪═════════╪══════════╪════════════╡
│ S1      ┆ null    ┆ PR       ┆ 2024-01-01 │
│ S1      ┆ null    ┆ PR       ┆ 2024-02-01 │
└─────────┴─────────┴──────────┴────────────┘
""")
    by = ["USUBJID", "PARQUAL"]
    out = rs.adam.onco.confirmed_response_flag(
        "CNFFL", source="OVRLRESP", date_col="ADT", by=by
    ).to_frame()
    assert _flagged_groups(out, by) == {("S1", None)}
