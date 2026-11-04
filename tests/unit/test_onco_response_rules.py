"""Oncology response rules: confirmation (c1-406), SD minimum (c1-407), post-PD BOR (c1-408)."""

import polars as pl
import pytest

from fleet.core.exceptions import DerivationError

OVR = """\
┌─────────┬───────┬────────────┐
│ USUBJID ┆ AVALC ┆ ADT        │
│ ---     ┆ ---   ┆ ---        │
│ str     ┆ str   ┆ date       │
╞═════════╪═══════╪════════════╡
│ C13     ┆ PR    ┆ 2020-02-12 │
│ C13     ┆ PD    ┆ 2020-02-26 │
│ C13     ┆ PR    ┆ 2020-03-25 │
│ C07     ┆ PR    ┆ 2020-02-12 │
│ C07     ┆ SD    ┆ 2020-02-26 │
│ C07     ┆ PR    ┆ 2020-03-11 │
│ C09     ┆ PR    ┆ 2020-01-01 │
│ C09     ┆ NE    ┆ 2020-01-15 │
│ C09     ┆ NE    ┆ 2020-01-29 │
│ C09     ┆ PR    ┆ 2020-02-12 │
│ C10     ┆ PR    ┆ 2020-01-01 │
│ C10     ┆ NE    ┆ 2020-01-15 │
│ C10     ┆ PR    ┆ 2020-02-12 │
│ C11     ┆ CR    ┆ 2020-01-01 │
│ C11     ┆ PR    ┆ 2020-02-12 │
│ C12     ┆ CR    ┆ 2020-01-01 │
│ C12     ┆ CR    ┆ 2020-02-12 │
│ C14     ┆ PR    ┆ 2020-01-01 │
│ C14     ┆ CR    ┆ 2020-02-12 │
│ C15     ┆ PR    ┆ 2020-01-01 │
│ C15     ┆ PR    ┆ 2020-01-20 │
│ C16     ┆ PR    ┆ 2020-01-01 │
│ C16     ┆ CR    ┆ 2020-01-15 │
│ C16     ┆ PR    ┆ 2020-02-12 │
│ C17     ┆ CR    ┆ 2020-01-01 │
│ C17     ┆ NE    ┆ 2020-01-15 │
│ C17     ┆ CR    ┆ 2020-02-12 │
└─────────┴───────┴────────────┘
"""

# admiralonco 1.4.1: derive_extreme_event with crsp_y_cr and crsp_y_pr on the
# records up to the first PD; accept_sd from derive_param_confirmed_resp.
ADMIRALONCO_Y = {"C10", "C12", "C14", "C17"}
ADMIRALONCO_Y_ACCEPT_SD = ADMIRALONCO_Y | {"C07"}


def _confirmed(df: pl.DataFrame, **kwargs) -> set[str]:
    out = df.adam.onco.confirmed_response_flag(
        "CRSPFL", source="AVALC", date_col="ADT", by=["USUBJID"], **kwargs
    ).to_frame()
    return set(out.filter(pl.col("CRSPFL") == "Y")["USUBJID"])


def test_confirmation_defaults_match_admiralonco() -> None:
    with pytest.warns(UserWarning, match="CR followed by a PR or SD"):
        assert _confirmed(pl.from_repr(OVR)) == ADMIRALONCO_Y


def test_one_sd_between_pr_matches_accept_sd() -> None:
    with pytest.warns(UserWarning):
        assert _confirmed(pl.from_repr(OVR), max_nr_sd=1) == ADMIRALONCO_Y_ACCEPT_SD


def test_no_limits_confirm_c07_and_c09() -> None:
    with pytest.warns(UserWarning):
        got = _confirmed(pl.from_repr(OVR), max_nr_sd=None, max_nr_ne=None)
    assert {"C07", "C09"} <= got
    assert "C13" not in got


def test_only_the_confirmed_record_is_flagged() -> None:
    rs = pl.from_repr(OVR).filter(pl.col("USUBJID") == "C12")
    out = rs.adam.onco.confirmed_response_flag(
        "CRSPFL", source="AVALC", date_col="ADT", by=["USUBJID"]
    ).to_frame()
    assert out["CRSPFL"].to_list() == ["Y", None]


def test_text_dates_are_accepted() -> None:
    rs = pl.from_repr(OVR).filter(pl.col("USUBJID") == "C12")
    rs = rs.with_columns(pl.col("ADT").cast(pl.String))
    assert _confirmed(rs) == {"C12"}


def test_response_outside_cr_pr_raises() -> None:
    with pytest.raises(DerivationError, match="Only CR and PR"):
        _confirmed(pl.from_repr(OVR), responses=["iCR", "iPR"])


def test_cr_subset_confirms_cr_only() -> None:
    with pytest.warns(UserWarning):
        assert _confirmed(pl.from_repr(OVR), responses=["CR"]) == {"C12", "C17"}


def test_null_response_warns_and_does_not_confirm() -> None:
    rs = pl.from_repr("""\
┌─────────┬───────┬────────────┐
│ USUBJID ┆ AVALC ┆ ADT        │
│ ---     ┆ ---   ┆ ---        │
│ str     ┆ str   ┆ date       │
╞═════════╪═══════╪════════════╡
│ N01     ┆ PR    ┆ 2020-01-01 │
│ N01     ┆ null  ┆ 2020-01-15 │
│ N01     ┆ PR    ┆ 2020-02-12 │
└─────────┴───────┴────────────┘
""")
    with pytest.warns(UserWarning, match="null response"):
        assert _confirmed(rs) == set()


def test_two_assessments_on_one_date_warn() -> None:
    rs = pl.from_repr("""\
┌─────────┬───────┬────────────┐
│ USUBJID ┆ AVALC ┆ ADT        │
│ ---     ┆ ---   ┆ ---        │
│ str     ┆ str   ┆ date       │
╞═════════╪═══════╪════════════╡
│ D01     ┆ PR    ┆ 2020-01-01 │
│ D01     ┆ PR    ┆ 2020-02-12 │
│ D01     ┆ SD    ┆ 2020-02-12 │
└─────────┴───────┴────────────┘
""")
    with pytest.warns(UserWarning, match="two assessments on one date"):
        _confirmed(rs)


# ── best_overall_response: SD minimum (c1-407) ────────────────────────────

BOR_ADRS = """\
┌─────────┬───────────────┬────────────┬────────────┐
│ USUBJID ┆ AVALC         ┆ ADT        ┆ RANDDT     │
│ ---     ┆ ---           ┆ ---        ┆ ---        │
│ str     ┆ str           ┆ date       ┆ date       │
╞═════════╪═══════════════╪════════════╪════════════╡
│ B04     ┆ SD            ┆ 2020-01-15 ┆ 2020-01-01 │
│ B05     ┆ SD            ┆ 2020-01-15 ┆ 2020-01-01 │
│ B05     ┆ PD            ┆ 2020-02-26 ┆ 2020-01-01 │
│ B07     ┆ NON-CR/NON-PD ┆ 2020-01-15 ┆ 2020-01-01 │
│ B21     ┆ SD            ┆ 2020-02-11 ┆ 2020-01-01 │
│ B22     ┆ SD            ┆ 2020-02-12 ┆ 2020-01-01 │
│ B23     ┆ SD            ┆ null       ┆ 2020-01-01 │
│ B24     ┆ PR            ┆ 2020-01-15 ┆ 2020-01-01 │
└─────────┴───────────────┴────────────┴────────────┘
"""


def _bor(df: pl.DataFrame, min_sd_days: int) -> dict[str, str]:
    out = df.adam.onco.best_overall_response(
        "BOR",
        source="AVALC",
        date_col="ADT",
        reference_date="RANDDT",
        min_sd_days=min_sd_days,
        by=["USUBJID"],
    ).to_frame()
    return dict(out.select("USUBJID", "BOR").unique().rows())


def test_sd_before_the_minimum_counts_as_ne() -> None:
    assert _bor(pl.from_repr(BOR_ADRS), 42) == {
        "B04": "NE",
        "B05": "PD",
        "B07": "NE",
        "B21": "NE",  # day 41
        "B22": "SD",  # day 42
        "B23": "NE",  # null date
        "B24": "PR",  # CR and PR have no minimum
    }


def test_min_sd_days_zero_switches_the_rule_off() -> None:
    bor = _bor(pl.from_repr(BOR_ADRS), 0)
    assert bor["B04"] == "SD"
    assert bor["B07"] == "NON-CR/NON-PD"


def test_sd_minimum_is_required() -> None:
    with pytest.raises(TypeError):
        pl.from_repr(BOR_ADRS).adam.onco.best_overall_response(  # type: ignore[call-arg]
            "BOR", source="AVALC", by=["USUBJID"]
        )


def test_negative_min_sd_days_raises() -> None:
    with pytest.raises(DerivationError, match="min_sd_days"):
        _bor(pl.from_repr(BOR_ADRS), -1)


# ── best_overall_response after PD (c1-408) ───────────────────────────────

POST_PD = """\
┌─────────┬──────────┬────────────┬────────────┐
│ USUBJID ┆ OVRLRESP ┆ ADT        ┆ RANDDT     │
│ ---     ┆ ---      ┆ ---        ┆ ---        │
│ str     ┆ str      ┆ date       ┆ date       │
╞═════════╪══════════╪════════════╪════════════╡
│ B10     ┆ PD       ┆ 2020-01-29 ┆ 2020-01-01 │
│ B10     ┆ PR       ┆ 2020-02-26 ┆ 2020-01-01 │
│ B11     ┆ SD       ┆ 2020-01-29 ┆ 2020-01-01 │
│ B11     ┆ PD       ┆ 2020-02-26 ┆ 2020-01-01 │
│ B11     ┆ CR       ┆ 2020-03-25 ┆ 2020-01-01 │
└─────────┴──────────┴────────────┴────────────┘
"""


def test_bor_reads_every_record_without_filter_pd() -> None:
    out = (
        pl.from_repr(POST_PD)
        .adam.onco.best_overall_response(
            "BOR",
            source="OVRLRESP",
            date_col="ADT",
            reference_date="RANDDT",
            min_sd_days=0,
            by=["USUBJID"],
        )
        .to_frame()
    )
    assert dict(out.select("USUBJID", "BOR").unique().rows()) == {"B10": "PR", "B11": "CR"}


def test_documented_chain_cuts_at_first_pd() -> None:
    adrs = pl.from_repr(POST_PD)
    bor = (
        adrs.adam.onco.filter_pd(response_col="OVRLRESP", date_col="ADT", by=["USUBJID"])
        .best_overall_response(
            "BOR",
            source="OVRLRESP",
            date_col="ADT",
            reference_date="RANDDT",
            min_sd_days=0,
            by=["USUBJID"],
        )
        .to_frame()
        .select("USUBJID", "BOR")
        .unique()
    )
    out = adrs.join(bor, on="USUBJID", how="left")
    assert out.height == adrs.height
    assert dict(out.select("USUBJID", "BOR").unique().rows()) == {"B10": "PD", "B11": "SD"}
