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
        .best_overall_response("BOR", source="OVRLRESP", by=["USUBJID"])
        .tumor_response_flag("RSPFL", source="OVRLRESP")
        .to_frame()
    )
"""

from __future__ import annotations

from typing import Self

import polars as pl

from fleet.adam._mixins import SharedADaMVerbsMixin

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
        """Map RECIST response text to numeric codes.

        Mapping: CR=1, PR=2, SD=3, NON-CR/NON-PD=4, PD=5, NE=6,
        MISSING=7.  Other/null values produce null.

        Args:
            target: Name of the output numeric column.
            source: Column containing RECIST response text.

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Map overall response to a numeric code::

                adrs = (
                    rs_raw.adam.onco
                    .aval_resp("AVAL", source="OVRLRESP")
                    .to_frame()
                )
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
        """Flag records where *source* matches a target response.

        Args:
            target: Name of the output flag column.
            source: Column containing response text.
            responses: Values to flag (default ``["CR", "PR"]``).
            flag_value: Value to assign for matching records (default ``"Y"``).

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Flag objective responders (CR or PR)::

                adrs = (
                    rs_raw.adam.onco
                    .tumor_response_flag("RSPFL", source="OVRLRESP")
                    .to_frame()
                )
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
        by: list[str] | None = None,
    ) -> Self:
        """Derive best overall response (BOR) per group.

        The most favourable response is the one with the lowest RECIST rank
        (CR < PR < SD < NON-CR/NON-PD < PD < NE < MISSING).

        Args:
            target: Name of the output column.
            source: Column containing RECIST response text.
            by: Partition columns (default ``["USUBJID"]``).

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Derive BOR per subject::

                adrs = (
                    rs_raw.adam.onco
                    .best_overall_response("BOR", source="OVRLRESP",
                                           by=["USUBJID"])
                    .to_frame()
                )
        """
        grps = by or ["USUBJID"]
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
        by: list[str] | None = None,
        flag_value: str = "Y",
    ) -> Self:
        """Flag a confirmed response sustained for at least *confirmation_days*.

        A response is confirmed when two response records in *responses*
        exist at least *confirmation_days* apart within the same group.

        Args:
            target: Name of the output flag column.
            source: Column containing response text.
            date_col: Assessment date column.
            confirmation_days: Minimum gap in days (default ``28``).
            responses: Values to consider (default ``["CR", "PR"]``).
            by: Partition columns (default ``["USUBJID"]``).
            flag_value: Value to assign (default ``"Y"``).

        Returns:
            Self: A fresh namespace wrapping the updated frame.

        Examples:
            Flag confirmed CR/PR responses::

                adrs = (
                    rs_raw.adam.onco
                    .confirmed_response_flag(
                        "CRSPFL", source="OVRLRESP", date_col="ADT",
                        confirmation_days=28, by=["USUBJID"])
                    .to_frame()
                )
        """
        rsp = responses if responses is not None else ["CR", "PR"]
        grps = by or ["USUBJID"]

        df = self.to_frame()

        # Candidate responder records
        resp_df = df.filter(pl.col(source).is_in(rsp))

        # For each group, check whether there exist two response dates ≥ N days apart
        confirmed_subjs = (
            resp_df.with_columns(pl.col(date_col).cast(pl.Date))
            .group_by(grps)
            .agg(
                [
                    pl.col(date_col).min().alias("_first_resp"),
                    pl.col(date_col).max().alias("_last_resp"),
                ]
            )
            .with_columns(
                (pl.col("_last_resp") - pl.col("_first_resp")).dt.total_days().alias("_gap")
            )
            .filter(pl.col("_gap") >= confirmation_days)
            .select(grps)
        )

        joined = df.join(confirmed_subjs, on=grps, how="left")
        # Mark as confirmed if subject has confirmed response AND current row is a response
        in_confirmed = joined.with_columns(
            pl.when(pl.col(source).is_in(rsp) & pl.col(grps[0]).is_in(confirmed_subjs[grps[0]]))
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
        by: list[str] | None = None,
    ) -> Self:
        """Keep records up to and including the first PD per group.

        Groups without any PD observation are fully retained.
        Materialises the pipeline before filtering.

        Args:
            response_col: Column containing response text.
            date_col: Assessment date column.
            by: Partition columns (default ``["USUBJID"]``).

        Returns:
            Self: A fresh namespace wrapping the filtered frame.

        Examples:
            Filter to records up to first progressive disease::

                adrs = (
                    rs_raw.adam.onco
                    .filter_pd(response_col="OVRLRESP", date_col="ADT",
                               by=["USUBJID"])
                    .to_frame()
                )
        """
        grps = by or ["USUBJID"]
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
            pl.col("_first_pd").is_null() | (pl.col(date_col).cast(pl.Date) <= pl.col("_first_pd"))
        ).drop("_first_pd")

        return self._materialise_then(filtered)
