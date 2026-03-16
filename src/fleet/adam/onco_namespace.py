"""
ADaM Oncology namespace extension (admiralonco-inspired).

Accessed via ``df.adam.onco`` on any Polars DataFrame.

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
        rs_sdtm.adam.onco
        .source("USUBJID")
        .aval_resp("AVAL", source="OVRLRESP")
        .best_overall_response("BOR", source="OVRLRESP", groups=["USUBJID"])
        .tumor_response_flag("RSPFL", source="OVRLRESP")
        .to_frame()
    )
"""

from __future__ import annotations

from typing import Any, Self

import polars as pl

from ._mixins import SharedADaMVerbsMixin

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
    return pl.col(source).replace_strict(_RESP_TO_NUM, default=None)


def _num_resp_expr(num_expr: pl.Expr) -> pl.Expr:
    """Return an expression mapping a numeric RECIST rank back to text."""
    return num_expr.replace_strict(_NUM_TO_RESP, default=None)


class OncoNamespace(SharedADaMVerbsMixin):
    """
    Immutable pipeline builder for ADaM oncology derivations.

    Inherits shared verbs from ``SharedADaMVerbsMixin``.
    Each verb returns a new ``OncoNamespace`` instance;
    ``to_frame()`` materialises the result.
    """

    # ------------------------------------------------------------------ #
    # 1. aval_resp — RECIST text → numeric                                #
    # ------------------------------------------------------------------ #

    def aval_resp(self, target: str, *, source: str) -> Self:
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
    ) -> Self:
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
    ) -> Self:
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
    ) -> Self:
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
    ) -> Self:
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

