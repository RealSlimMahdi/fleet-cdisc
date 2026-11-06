"""
ADaM Oncology namespace extension (admiralonco-inspired).

Accessed via ``df.adam.onco`` on any Polars DataFrame.

Key derivations, inspired by pharmaverse/admiralonco (not ports; values can differ):
  - ``aval_resp``             — RECIST response text → numeric code
  - ``tumor_response_flag``   — flag responders ("CR"/"PR") as "Y"
  - ``best_overall_response`` — best (most favourable) response per group,
                                with a protocol minimum for SD
  - ``confirmed_response_flag``— flag a CR or PR that a later assessment confirms
  - ``filter_pd``             — keep only records up to first PD per group

``best_overall_response`` reads every record. Run ``filter_pd`` first, on a
copy, so that a response after the first PD does not set BOR.

Usage
-----
    import fleet  # triggers registration

    bor = (
        adrs.adam.onco
        .filter_pd(response_col="OVRLRESP", date_col="ADT", by=["USUBJID"])
        .best_overall_response("BOR", source="OVRLRESP", date_col="ADT",
                               reference_date="RANDDT", min_sd_days=42,
                               by=["USUBJID"])
        .to_frame()
        .select("USUBJID", "BOR")
        .unique()
    )
    adrs = (
        adrs.join(bor, on="USUBJID", how="left")
        .adam.onco
        .aval_resp("AVAL", source="OVRLRESP")
        .tumor_response_flag("RSPFL", source="OVRLRESP")
        .to_frame()
    )
"""

from __future__ import annotations

import warnings
from typing import Self

import polars as pl

from fleet.adam._mixins import SharedADaMVerbsMixin
from fleet.core.exceptions import DerivationError

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


def _warn_response_data(scope: pl.DataFrame, grps: list[str]) -> None:
    """Warn on null responses, same-date assessments and CR followed by PR or SD."""

    def _groups(frame: pl.DataFrame) -> str:
        rows = frame.select(grps).unique(maintain_order=True).rows()
        shown = ", ".join(str(r[0] if len(r) == 1 else r) for r in rows[:5])
        return shown + (" ..." if len(rows) > 5 else "")

    checks = [
        (scope.filter(pl.col("__v").is_null()), "have a null response; it confirms nothing"),
        (
            scope.filter(pl.len().over([*grps, "__dt"]) > 1),
            "have two assessments on one date; their order is unknown",
        ),
        (
            scope.group_by(grps)
            .agg(
                (
                    pl.col("__dt").filter(pl.col("__v") == "CR").min()
                    < pl.col("__dt").filter(pl.col("__v").is_in(["PR", "SD"])).max()
                ).alias("__bad")
            )
            .filter(pl.col("__bad")),
            "have a CR followed by a PR or SD; check the assessments",
        ),
    ]
    for frame, text in checks:
        if frame.height:
            warnings.warn(
                f"confirmed_response_flag(): {grps} {_groups(frame)} {text}.",
                UserWarning,
                stacklevel=3,
            )


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

        References:
            RECIST 1.1: Eisenhauer EA et al. New response evaluation criteria in solid
            tumours. Eur J Cancer. 2009;45(2):228-247. The numeric ranks follow
            admiralonco ``aval_resp`` (pharmaverse).
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
        date_col: str,
        reference_date: str,
        min_sd_days: int,
        by: list[str] | None = None,
    ) -> Self:
        """Derive best overall response (BOR) per group.

        The most favourable response is the one with the lowest RECIST rank
        (CR < PR < SD < NON-CR/NON-PD < PD < NE < MISSING). An SD or
        NON-CR/NON-PD assessed before *reference_date* + *min_sd_days*, or
        with a null date, counts as NE. The verb reads every record: it does
        not remove records after the first PD or after new anti-cancer
        therapy. Run ``filter_pd`` on a copy first and join BOR back.

        Args:
            target: Name of the output column.
            source: Column containing RECIST response text.
            date_col: Assessment date column (Date or ISO text).
            reference_date: Start of the SD minimum, for example RANDDT or
                TRTSDT.
            min_sd_days: Protocol minimum duration of SD, in days. ``0``
                switches the rule off; the two date columns are then not read.
            by: Partition columns (default ``["USUBJID"]``).

        Returns:
            Self: The namespace with *target* appended.

        Raises:
            DerivationError: If *min_sd_days* is negative.

        Examples:
            Derive BOR per subject up to the first PD, with a 42-day SD minimum::

                bor = (
                    adrs.adam.onco
                    .filter_pd(response_col="OVRLRESP", date_col="ADT",
                               by=["USUBJID"])
                    .best_overall_response("BOR", source="OVRLRESP",
                                           date_col="ADT",
                                           reference_date="RANDDT",
                                           min_sd_days=42, by=["USUBJID"])
                    .to_frame()
                    .select("USUBJID", "BOR")
                    .unique()
                )
                adrs = adrs.join(bor, on="USUBJID", how="left")

        References:
            RECIST 1.1 (Eisenhauer EA et al. Eur J Cancer. 2009;45(2):228-247),
            section 4.4: best overall response is the best response up to
            progression; section 4.4.3: SD must meet a protocol-specified
            minimum time from the reference date, else BOR is NE or PD. The
            ordering CR < PR < SD < NON-CR/NON-PD < PD < NE follows admiralonco
            ``derive_param_bor`` (``ADT >= reference + minimum``). This verb does
            not apply the confirmation requirement; see
            ``confirmed_response_flag``. ADR-0031.
        """
        if min_sd_days < 0:
            raise DerivationError(
                f"best_overall_response(): min_sd_days={min_sd_days}. Give 0 or more days."
            )
        grps = by or ["USUBJID"]
        resp = pl.col(source)
        if min_sd_days:
            early = (
                pl.col(date_col).cast(pl.Date)
                < pl.col(reference_date).cast(pl.Date) + pl.duration(days=min_sd_days)
            ).fill_null(True)
            resp = (
                pl.when(resp.is_in(["SD", "NON-CR/NON-PD"]) & early)
                .then(pl.lit("NE"))
                .otherwise(resp)
            )
        best_num = resp.replace_strict(_RESP_TO_NUM, default=None).min().over(grps)
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
        max_nr_ne: int | None = 1,
        max_nr_sd: int | None = 0,
    ) -> Self:
        """Flag each CR or PR record that a later assessment confirms.

        A CR is confirmed by a CR at least *confirmation_days* later. A PR is
        confirmed by a CR or PR at least *confirmation_days* later. All
        assessments after the record, up to and including the first
        confirming one, must be CR or NE for a CR, and CR, PR, NE or SD for a
        PR, with at most *max_nr_ne* NE and at most *max_nr_sd* SD. For a PR,
        no PR may follow a CR in that window. Assessments after the first PD
        of a group are not read, so a ``filter_pd`` before the verb changes
        nothing. Only the confirmed record is flagged.

        The verb warns, with the group values, when a CR is followed by a PR
        or SD, when two assessments of a group have the same date, and when
        *source* is null.

        Args:
            target: Name of the output flag column.
            source: Column containing response text.
            date_col: Assessment date column (Date or ISO text).
            confirmation_days: Minimum gap in days (default ``28``).
            responses: Responses to confirm: ``["CR", "PR"]`` (default) or a
                subset of it.
            by: Partition columns (default ``["USUBJID"]``).
            flag_value: Value to assign (default ``"Y"``).
            max_nr_ne: Maximum number of NE assessments in the window
                (default ``1``). ``None`` gives no limit.
            max_nr_sd: Maximum number of SD assessments in the window of a
                PR (default ``0``). ``None`` gives no limit. SD never
                confirms a CR.

        Returns:
            Self: A fresh namespace wrapping the updated frame.

        Raises:
            DerivationError: If *responses* holds a value other than CR or PR.

        Examples:
            Flag confirmed CR/PR responses::

                adrs = (
                    rs_raw.adam.onco
                    .confirmed_response_flag(
                        "CRSPFL", source="OVRLRESP", date_col="ADT",
                        confirmation_days=28, by=["USUBJID"])
                    .to_frame()
                )

        References:
            RECIST 1.1 (Eisenhauer EA et al. Eur J Cancer. 2009;45(2):228-247),
            section 4.4.3 Table 3, section 4.4.4 and the Appendix FAQ: a CR or PR
            is confirmed by a repeat assessment no less than 4 weeks later. The
            rules for NE and SD between the two follow the admiralonco
            ``crsp_y_cr`` and ``crsp_y_pr`` events (pharmaverse); SD between
            two PR is the ``accept_sd`` option of the deprecated
            ``derive_param_confirmed_resp``. RECIST does not fix them: check the
            SAP. ADR-0030.
        """
        rsp = responses if responses is not None else ["CR", "PR"]
        unknown = sorted(set(rsp) - {"CR", "PR"})
        if unknown or not rsp:
            raise DerivationError(
                f"confirmed_response_flag(): responses={rsp!r}. Only CR and PR can be "
                "confirmed; give ['CR', 'PR'] or a subset."
            )
        grps = by or ["USUBJID"]
        df = self.to_frame().with_row_index("__row")
        work = df.select(
            "__row",
            *grps,
            pl.col(date_col).cast(pl.Date).alias("__dt"),
            pl.col(source).alias("__v"),
        )
        first_pd = (
            work.filter(pl.col("__v") == "PD")
            .group_by(grps)
            .agg(pl.col("__dt").min().alias("__pd"))
        )
        scope = (
            work.join(first_pd, on=grps, how="left", nulls_equal=True)
            .filter(pl.col("__pd").is_null() | (pl.col("__dt") <= pl.col("__pd")))
            .filter(pl.col("__dt").is_not_null())
            .drop("__pd")
        )
        _warn_response_data(scope, grps)

        anchors = scope.filter(pl.col("__v").is_in(rsp))
        later = scope.select(*grps, pl.col("__dt").alias("__dt_j"), pl.col("__v").alias("__v_j"))
        pairs = anchors.join(later, on=grps, how="inner", nulls_equal=True).filter(
            pl.col("__dt_j") > pl.col("__dt")
        )
        is_cr = pl.col("__v") == "CR"
        far = pl.col("__dt_j") >= pl.col("__dt") + pl.duration(days=confirmation_days)
        confirms = far & pl.when(is_cr).then(pl.col("__v_j") == "CR").otherwise(
            pl.col("__v_j").is_in(["CR", "PR"])
        )
        upper = pairs.filter(confirms).group_by("__row").agg(pl.col("__dt_j").min().alias("__up"))
        window = pairs.join(upper, on="__row").filter(pl.col("__dt_j") <= pl.col("__up"))

        v_j = pl.col("__v_j")
        n_ne = (v_j == "NE").sum()
        n_sd = (v_j == "SD").sum()
        allowed_pr = ["CR", "PR", "NE"] + (["SD"] if max_nr_sd != 0 else [])
        cr_ok = v_j.is_in(["CR", "NE"]).fill_null(False).all()
        pr_ok = v_j.is_in(allowed_pr).fill_null(False).all()
        no_pr_after_cr = (
            pl.col("__dt_j").filter(v_j == "CR").min() > pl.col("__dt_j").filter(v_j == "PR").max()
        ).fill_null(True)
        rule = pl.when(pl.col("__v").first() == "CR").then(cr_ok).otherwise(pr_ok & no_pr_after_cr)
        if max_nr_ne is not None:
            rule = rule & (n_ne <= max_nr_ne)
        if max_nr_sd is not None:
            rule = rule & (n_sd <= max_nr_sd)
        confirmed = (
            window.group_by("__row")
            .agg(rule.alias("__ok"))
            .filter(pl.col("__ok"))
            .select("__row", pl.lit(flag_value).alias(target))
        )
        out = df.drop(target, strict=False).join(confirmed, on="__row", how="left")
        return self._materialise_then(out.sort("__row").drop("__row"))

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

        References:
            admiralonco ``filter_pd`` (pharmaverse): records up to and including the
            first progressive disease, as RECIST 1.1 uses for response endpoints.
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

        joined = df.join(pd_dates, on=grps, how="left", nulls_equal=True)
        filtered = joined.filter(
            pl.col("_first_pd").is_null() | (pl.col(date_col).cast(pl.Date) <= pl.col("_first_pd"))
        ).drop("_first_pd")

        from fleet.core.lineage import record_row_step

        return record_row_step(self._materialise_then(filtered), "filter_pd", {})
