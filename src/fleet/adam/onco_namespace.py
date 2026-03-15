"""
ADaM Oncology Polars namespace extension (admiralonco-inspired).

Registers ``df.onco`` on every Polars DataFrame.

Key derivations ported from pharmaverse/admiralonco:
  - ``aval_resp``             — RECIST response text → numeric code
  - ``tumor_response_flag``   — flag responders ("CR"/"PR") as "Y"
  - ``best_overall_response`` — best (most favourable) response per group
  - ``confirmed_response_flag``— confirm response sustained ≥ N days
  - ``filter_pd``             — keep only records up to first PD per group

Usage
-----
    import fleet  # triggers registration

    adrs = (
        rs_sdtm.onco
        .source("USUBJID")
        .aval_resp("AVAL", source="OVRLRESP")
        .best_overall_response("BOR", source="OVRLRESP", groups=["USUBJID"])
        .tumor_response_flag("RSPFL", source="OVRLRESP")
        .to_frame()
    )
"""

from __future__ import annotations

from typing import Any

import polars as pl

# RECIST / RECIST-like response order (lower = more favourable)
_RESP_TO_NUM: dict[str, int] = {
    "CR": 1,
    "PR": 2,
    "SD": 3,
    "NON-CR/NON-PD": 4,
    "PD": 5,
    "NE": 6,
    "MISSING": 7,
}

_NUM_TO_RESP: dict[int, str] = {v: k for k, v in _RESP_TO_NUM.items()}


def _resp_num_expr(source: str) -> pl.Expr:
    """Return an expression mapping *source* to its RECIST numeric rank."""
    chain = (
        pl.when(pl.col(source) == "CR").then(1)
        .when(pl.col(source) == "PR").then(2)
        .when(pl.col(source) == "SD").then(3)
        .when(pl.col(source) == "NON-CR/NON-PD").then(4)
        .when(pl.col(source) == "PD").then(5)
        .when(pl.col(source) == "NE").then(6)
        .when(pl.col(source) == "MISSING").then(7)
        .otherwise(None)
    )
    return chain


def _num_resp_expr(num_expr: pl.Expr) -> pl.Expr:
    """Return an expression mapping a numeric RECIST rank back to text."""
    return (
        pl.when(num_expr == 1).then(pl.lit("CR"))
        .when(num_expr == 2).then(pl.lit("PR"))
        .when(num_expr == 3).then(pl.lit("SD"))
        .when(num_expr == 4).then(pl.lit("NON-CR/NON-PD"))
        .when(num_expr == 5).then(pl.lit("PD"))
        .when(num_expr == 6).then(pl.lit("NE"))
        .when(num_expr == 7).then(pl.lit("MISSING"))
        .otherwise(pl.lit(None))
    )


@pl.api.register_dataframe_namespace("onco")
class OncoNamespace:
    """
    Immutable pipeline builder for ADaM oncology derivations.

    Mirrors the API style of ``AdamNamespace`` — each verb returns a new
    ``OncoNamespace`` instance; ``to_frame()`` materialises the result.
    """

    def __init__(self, df: pl.DataFrame) -> None:
        self._df = df
        self._pipeline: list[pl.Expr] = []

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _chain(self, *exprs: pl.Expr) -> "OncoNamespace":
        new = object.__new__(OncoNamespace)
        new._df = self._df
        new._pipeline = self._pipeline + list(exprs)
        return new

    def _materialise_then(self, df: pl.DataFrame) -> "OncoNamespace":
        new = object.__new__(OncoNamespace)
        new._df = df
        new._pipeline = []
        return new

    # ------------------------------------------------------------------ #
    # Base verbs (mirror core ADaM verbs for convenience)                 #
    # ------------------------------------------------------------------ #

    def source(self, target: str, *, from_col: str | None = None) -> "OncoNamespace":
        """Copy *from_col* (or *target* itself) to *target*."""
        src = from_col if from_col is not None else target
        return self._chain(pl.col(src).alias(target))

    def assigned(self, target: str, *, value: Any) -> "OncoNamespace":
        """Set *target* to a constant *value* for every record."""
        return self._chain(pl.lit(value).alias(target))

    def derivation(
        self, target: str, *, expression: str | pl.Expr
    ) -> "OncoNamespace":
        """Arbitrary Polars expression derivation."""
        from ..sdtm.utils import parse_expression
        expr = (
            expression
            if isinstance(expression, pl.Expr)
            else parse_expression(str(expression))
        )
        return self._chain(expr.alias(target))

    def whereclauses(self, *, where: str | pl.Expr) -> "OncoNamespace":
        """Filter the dataset to records matching *where*."""
        from ..sdtm.utils import parse_expression
        df = self.to_frame()
        fexpr = where if isinstance(where, pl.Expr) else parse_expression(str(where))
        return self._materialise_then(df.filter(fexpr))

    # ------------------------------------------------------------------ #
    # 1. aval_resp — RECIST text → numeric                                #
    # ------------------------------------------------------------------ #

    def aval_resp(self, target: str, *, source: str) -> "OncoNamespace":
        """
        Map RECIST / oncology response text values in *source* to numeric codes.

        Mapping (from admiralonco ``aval_resp``):

        ===============   ====
        Response          Code
        ===============   ====
        CR                   1
        PR                   2
        SD                   3
        NON-CR/NON-PD        4
        PD                   5
        NE                   6
        MISSING              7
        (other / null)    null
        ===============   ====

        Example::

            .aval_resp("AVAL", source="OVRLRESP")
        """
        return self._chain(_resp_num_expr(source).cast(pl.Float64).alias(target))

    # ------------------------------------------------------------------ #
    # 2. tumor_response_flag — flag responders                            #
    # ------------------------------------------------------------------ #

    def tumor_response_flag(
        self,
        target: str,
        *,
        source: str,
        responses: list[str] | None = None,
        flag_value: str = "Y",
    ) -> "OncoNamespace":
        """
        Flag records where *source* is in *responses* (default: ``["CR", "PR"]``).

        Returns *flag_value* (default ``"Y"``), null otherwise.

        Example::

            .tumor_response_flag("RSPFL", source="OVRLRESP")                 # CR or PR
            .tumor_response_flag("CBFL",  source="OVRLRESP",
                                 responses=["CR", "PR", "SD"])                # clinical benefit
        """
        rsp = responses if responses is not None else ["CR", "PR"]
        return self._chain(
            pl.when(pl.col(source).is_in(rsp))
            .then(pl.lit(flag_value))
            .otherwise(pl.lit(None))
            .alias(target)
        )

    # ------------------------------------------------------------------ #
    # 3. best_overall_response — most favourable response per group       #
    # ------------------------------------------------------------------ #

    def best_overall_response(
        self,
        target: str,
        *,
        source: str,
        groups: list[str] | None = None,
    ) -> "OncoNamespace":
        """
        Derive the best overall response (BOR) within each *groups* partition.

        The most favourable response is the one with the lowest RECIST numeric
        rank (CR=1 < PR=2 < SD=3 < NON-CR/NON-PD=4 < PD=5 < NE=6 < MISSING=7).

        All records within the group receive the same BOR text value.

        Example::

            .best_overall_response("BOR", source="OVRLRESP",
                                    groups=["USUBJID"])
        """
        grps = groups or ["USUBJID"]
        num_expr = _resp_num_expr(source)
        best_num = num_expr.min().over(grps)
        return self._chain(_num_resp_expr(best_num).alias(target))

    # ------------------------------------------------------------------ #
    # 4. confirmed_response_flag — confirm response sustained N days      #
    # ------------------------------------------------------------------ #

    def confirmed_response_flag(
        self,
        target: str,
        *,
        source: str,
        date_col: str,
        confirmation_days: int = 28,
        responses: list[str] | None = None,
        groups: list[str] | None = None,
        flag_value: str = "Y",
    ) -> "OncoNamespace":
        """
        Flag a confirmed response: the subject must have a response record in
        *responses* followed by another response record at least *confirmation_days*
        later within the same *groups* partition.

        Materialises the pipeline then returns a fresh namespace.

        Example::

            .confirmed_response_flag(
                "CRSPFL",
                source="OVRLRESP",
                date_col="ADT",
                confirmation_days=28,
                groups=["USUBJID"],
            )
        """
        rsp = responses if responses is not None else ["CR", "PR"]
        grps = groups or ["USUBJID"]

        df = self.to_frame()

        # Candidate responder records
        resp_df = df.filter(pl.col(source).is_in(rsp))

        # For each group, check whether there exist two response dates ≥ N days apart
        confirmed_subjs = (
            resp_df
            .with_columns(pl.col(date_col).cast(pl.Date))
            .group_by(grps)
            .agg([
                pl.col(date_col).min().alias("_first_resp"),
                pl.col(date_col).max().alias("_last_resp"),
            ])
            .with_columns(
                (pl.col("_last_resp") - pl.col("_first_resp"))
                .dt.total_days()
                .alias("_gap")
            )
            .filter(pl.col("_gap") >= confirmation_days)
            .select(grps)
        )

        joined = df.join(confirmed_subjs, on=grps, how="left")
        # Mark as confirmed if subject has confirmed response AND current row is a response
        in_confirmed = joined.with_columns(
            pl.when(
                pl.col(source).is_in(rsp)
                & pl.col(grps[0]).is_in(confirmed_subjs[grps[0]])
            )
            .then(pl.lit(flag_value))
            .otherwise(pl.lit(None))
            .alias(target)
        ).select(df.columns + [target])

        return self._materialise_then(in_confirmed)

    # ------------------------------------------------------------------ #
    # 5. filter_pd — keep records up to first PD per group               #
    # ------------------------------------------------------------------ #

    def filter_pd(
        self,
        *,
        response_col: str,
        date_col: str,
        groups: list[str] | None = None,
    ) -> "OncoNamespace":
        """
        Filter the dataset to keep only records up to and including the first
        progressive disease (PD) observation per *groups* partition.

        Records for groups without any PD observation are fully retained.
        Materialises the current pipeline before filtering.

        Example::

            .filter_pd(response_col="OVRLRESP", date_col="ADT",
                       groups=["USUBJID"])
        """
        grps = groups or ["USUBJID"]
        df = self.to_frame()

        # First PD date per group
        pd_dates = (
            df.filter(pl.col(response_col) == "PD")
            .with_columns(pl.col(date_col).cast(pl.Date))
            .group_by(grps)
            .agg(pl.col(date_col).min().alias("_first_pd"))
        )

        joined = df.join(pd_dates, on=grps, how="left")
        filtered = joined.filter(
            pl.col("_first_pd").is_null()
            | (pl.col(date_col).cast(pl.Date) <= pl.col("_first_pd"))
        ).drop("_first_pd")

        return self._materialise_then(filtered)

    # ------------------------------------------------------------------ #
    # Materialise                                                          #
    # ------------------------------------------------------------------ #

    def to_frame(self) -> pl.DataFrame:
        """Materialise the pipeline and return a ``pl.DataFrame``."""
        if not self._pipeline:
            return self._df
        return self._df.with_columns(self._pipeline)
