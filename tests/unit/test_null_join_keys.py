"""A null key joins a null key, as SAS MERGE BY matches missing to missing.

Once a SAS blank reads as null (package F), a blank ATPT or AVISIT is a
null join key.  Polars drops such rows from a join by default; SAS and
dplyr do not.  Each verb that joins on keys the user names follows SAS.
"""

from __future__ import annotations

import datetime as dt

import polars as pl

import fleet  # noqa: F401  (registers the namespaces)

ADVS = pl.from_repr("""
┌─────────┬──────────┬───────┬───────┐
│ USUBJID ┆ ATPT     ┆ PARAM ┆ AVAL  │
│ ---     ┆ ---      ┆ ---   ┆ ---   │
│ str     ┆ str      ┆ str   ┆ f64   │
╞═════════╪══════════╪═══════╪═══════╡
│ S1      ┆ PRE-DOSE ┆ SYSBP ┆ 120.0 │
│ S1      ┆ null     ┆ SYSBP ┆ 130.0 │
└─────────┴──────────┴───────┴───────┘
""")


def test_merge_pairs_a_null_key_with_a_null_key() -> None:
    refs = pl.from_repr("""
┌─────────┬──────────┬──────┐
│ USUBJID ┆ ATPT     ┆ REFV │
│ ---     ┆ ---      ┆ ---  │
│ str     ┆ str      ┆ i64  │
╞═════════╪══════════╪══════╡
│ S1      ┆ PRE-DOSE ┆ 1    │
│ S1      ┆ null     ┆ 2    │
└─────────┴──────────┴──────┘
""")

    out = ADVS.adam.merge(refs, on=["USUBJID", "ATPT"]).to_frame()

    assert out["REFV"].to_list() == [1, 2]


def test_first_date_by_a_null_key() -> None:
    ex = pl.DataFrame(
        {
            "USUBJID": ["S1", "S1"],
            "ATPT": ["PRE-DOSE", None],
            "EXSTDT": [dt.date(2024, 1, 15), dt.date(2024, 1, 16)],
        }
    )

    out = ADVS.adam.first_date(
        "FDOSEDT", from_dataset=ex, date_col="EXSTDT", by=["USUBJID", "ATPT"]
    )

    assert out.to_frame()["FDOSEDT"].to_list() == [dt.date(2024, 1, 15), dt.date(2024, 1, 16)]


def test_count_events_by_a_null_key() -> None:
    out = ADVS.adam.count_events("NREC", from_dataset=ADVS, by=["USUBJID", "ATPT"]).to_frame()

    assert out["NREC"].to_list() == [1, 1]


def test_flag_exists_matches_a_null_key() -> None:
    source = ADVS.filter(pl.col("ATPT").is_null()).select("USUBJID", "ATPT")

    multi = ADVS.adam.flag(
        "INSRC", criteria="exists", from_dataset=source, on=["USUBJID", "ATPT"]
    ).to_frame()
    single = ADVS.adam.flag(
        "INSRC", criteria="exists", from_dataset=source.select("ATPT"), on=["ATPT"]
    ).to_frame()

    assert multi["INSRC"].to_list() == [None, "Y"]
    assert single["INSRC"].to_list() == [None, "Y"]


def test_derive_param_keeps_a_group_with_a_null_key() -> None:
    """c1-319: admiral and SAS BY give one MAP record per ATPT, the missing one too."""
    advs = pl.from_repr("""
┌─────────┬──────────┬─────────┬───────┐
│ USUBJID ┆ ATPT     ┆ PARAMCD ┆ AVAL  │
│ ---     ┆ ---      ┆ ---     ┆ ---   │
│ str     ┆ str      ┆ str     ┆ f64   │
╞═════════╪══════════╪═════════╪═══════╡
│ S1      ┆ PRE-DOSE ┆ SYSBP   ┆ 120.0 │
│ S1      ┆ PRE-DOSE ┆ DIABP   ┆ 80.0  │
│ S1      ┆ null     ┆ SYSBP   ┆ 150.0 │
│ S1      ┆ null     ┆ DIABP   ┆ 90.0  │
└─────────┴──────────┴─────────┴───────┘
""")

    out = advs.adam.derive_param(
        by=["USUBJID", "ATPT"],
        set_values_to={"PARAMCD": "MAP"},
        parameter_filter={"SYSBP": "SYSBP", "DIABP": "DIABP"},
        analysis_value=(pl.col("SYSBP") + 2 * pl.col("DIABP")) / 3,
    ).to_frame()

    map_rows = out.filter(pl.col("PARAMCD") == "MAP").sort("ATPT", nulls_last=True)
    assert map_rows["AVAL"].round(4).to_list() == [93.3333, 110.0]
