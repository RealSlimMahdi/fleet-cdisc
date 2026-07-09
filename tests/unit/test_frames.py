"""Runtime tests for the typed entry points (``fleet.frame`` / aliases).

The typing behaviour is checker-only; at runtime ``frame()`` must be a
zero-cost identity and the aliases must *be* the Polars classes.
"""

import polars as pl

import fleet


def _df() -> pl.DataFrame:
    return pl.from_repr("""\
┌────────────┐
│ subject_id │
│ ---        │
│ str        │
╞════════════╡
│ S001       │
└────────────┘
""")


def test_frame_returns_dataframe_unchanged() -> None:
    df = _df()
    assert fleet.frame(df) is df


def test_frame_returns_lazyframe_unchanged() -> None:
    lf = _df().lazy()
    assert fleet.frame(lf) is lf


def test_aliases_are_the_polars_classes() -> None:
    assert fleet.DataFrame is pl.DataFrame
    assert fleet.LazyFrame is pl.LazyFrame


def test_frame_result_chains_into_namespace() -> None:
    dm = fleet.frame(_df()).sdtm.assign("DOMAIN", value="DM").to_frame()
    assert isinstance(dm, pl.DataFrame)
    assert dm["DOMAIN"].to_list() == ["DM"]
