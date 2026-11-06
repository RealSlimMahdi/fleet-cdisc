"""
LB TLG sub-namespace — laboratory summary tables and abnormality listings.

Accessed via ``df.tlg.lb`` on any Polars DataFrame containing ADaM ADLB data.
Ports the ``{tlg.templates}`` LBT01 (continuous lab statistics per
PARAM/AVISIT) and LBL01 (laboratory abnormalities listing) templates.
"""

from __future__ import annotations

from typing import Any, ClassVar

import polars as pl
from pydantic import Field, field_validator, model_validator

from ._ard import (
    ard_row,
    check_text_arm,
    enum_arms,
    listing_frame,
    prepare_frame,
    resolve_arms,
    restrict_to_population,
    rows_to_ard,
    summarize_ard,
    summarize_spec,
    validate_ard,
    worst_case,
)
from ._builder import BuilderVerbsMixin
from ._specs import (
    Column,
    Row,
    SchemaError,
    Statistic,
    SummarySpecBase,
    TLGSpec,
    _check_filter_field,
    change_from_baseline_prefilter,
    resolve_filter,
)

#: Default post-baseline rule of the shift and abnormality tables: an
#: on-treatment record that is not the baseline record.  ADaM codes both
#: flags as Y / null, so the ABLFL test is null-safe.
POST_BASELINE_PREFILTER = '(pl.col("ONTRTFL") == "Y") & pl.col("ABLFL").ne_missing("Y")'

#: Default rule of the abnormalities listing: a range indicator that is
#: not normal (``NORMAL``, ``N`` or blank, in any case).
ABNORMAL_PREFILTER = (
    'pl.col("ANRIND").is_not_null() & '
    '~pl.col("ANRIND").str.to_uppercase().str.strip_chars().is_in(["NORMAL", "N", ""])'
)

_POST_BASELINE_HINT = (
    " The table counts post-baseline records only. When the dataset has no "
    "ONTRTFL or ABLFL, state the SAP's post-baseline rule as the prefilter, "
    "for example prefilter='pl.col(\"ADY\") > 1'."
)

_PREFILTER_DESCRIPTION = (
    "The post-baseline rule.  The default keeps on-treatment records "
    "(``ONTRTFL`` = Y) that are not the baseline record (``ABLFL`` = Y), "
    "so both columns are required.  State another SAP rule as an "
    "expression, e.g. ``'pl.col(\"ADY\") > 1'``; ``null`` switches the "
    "rule off (the dataset must then hold post-baseline records only)."
)


class LBSummarySpec(SummarySpecBase):
    """Spec for a laboratory summary table (LBT01).

    Defaults provide zero-config continuous statistics for each
    parameter (``PARAMCD``) at each analysis visit (``AVISIT``),
    mirroring the GDSR ``LBT01`` baseline/change layout.
    """

    context: ClassVar[str] = "t_lb_summary"
    nested: ClassVar[bool] = True

    rows: list[Row] = Field(
        default_factory=lambda: [
            Row(field="PARAMCD", label="Parameter"),
            Row(field="AVISIT", label="Analysis Visit"),
        ],
        description=(
            "Hierarchy of row groupings (PARAM \u2192 AVISIT).  Set inline via "
            "[`TLGBuilder.rows()`][fleet.tlg.TLGBuilder.rows]."
        ),
    )
    statistics: list[Statistic] = Field(
        default_factory=lambda: [
            Statistic.N_SUBJECTS,
            Statistic.MEAN,
            Statistic.SD,
            Statistic.MEDIAN,
            Statistic.MIN,
            Statistic.MAX,
        ],
        description=(
            "Continuous statistics computed per row.  Set inline via "
            "[`TLGBuilder.stats()`][fleet.tlg.TLGBuilder.stats]."
        ),
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "PARAMCD", "AVAL", "AVISIT"],
        description="Columns required in the analysis dataset for this spec.",
    )


class LBListingSpec(TLGSpec):
    """Spec for a laboratory abnormalities listing (LBL01).

    The ``prefilter`` keeps results with a non-normal range indicator
    (``ANRIND``); it applies after ``dataset_filter``, and ``None``
    lists every record.  The default columns present subject,
    parameter, value, and toxicity grade, sorted for review.  When the
    dataset has no ``PARAM``, the default parameter column and sort key
    is ``PARAMCD``.
    """

    _unconsumed_spec_fields: ClassVar[frozenset[str]] = frozenset({"adsl_filter", "header_rows"})

    output_type: str = "listing"
    prefilter: Any | None = Field(
        default=ABNORMAL_PREFILTER,
        description=(
            "The record rule of the listing, applied after "
            "``dataset_filter``.  The default keeps a non-normal "
            "``ANRIND``; ``null`` lists every record."
        ),
    )

    _validate_prefilter = field_validator("prefilter")(_check_filter_field)
    columns: list[Column] = Field(
        default_factory=lambda: [
            Column(field="USUBJID", label="Subject"),
            Column(field="TRTA", label="Treatment"),
            Column(field="PARAM", label="Parameter"),
            Column(field="AVISIT", label="Analysis Visit"),
            Column(field="AVAL", label="Result"),
            Column(field="AVALU", label="Unit"),
            Column(field="ANRIND", label="Range Indicator"),
            Column(field="ATOXGR", label="Toxicity Grade"),
        ],
        description="Ordered list of columns to include in the listing.",
    )
    sort_by: list[str] = Field(
        default_factory=lambda: ["USUBJID", "PARAM", "AVISIT"],
        description="Sort order applied before rendering.",
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "PARAMCD", "AVAL", "ANRIND"],
        description="Columns required in the analysis dataset for this spec.",
    )


class LBChgSpec(LBSummarySpec):
    """Spec for lab change from baseline (lbt02): CHG stats per PARAM × visit.

    Prefilter rule: the baseline record (``ABLFL`` = Y) and records
    with no change value are dropped before summarising, so ``ABLFL``
    and the ``value_col`` column are required.  Unless set, the
    prefilter follows ``value_col``; ``prefilter=None`` switches the
    rule off.
    """

    context: ClassVar[str] = "t_lb_chg"

    value_col: str = Field(
        default="CHG",
        description="Analysis-value column summarized (change from baseline).",
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "PARAMCD", "AVISIT"],
    )

    @model_validator(mode="after")
    def _default_prefilter_follows_value_col(self) -> LBChgSpec:
        if "prefilter" not in self.model_fields_set:
            self.prefilter = change_from_baseline_prefilter(self.value_col)
        return self


class LBShiftSpec(SummarySpecBase):
    """Spec for the lab shift table (lbt03).

    The row hierarchy is fixed (PARAMCD → baseline-to-worst shift cell);
    the spec drives validation, pooling, ordering, the worst-case
    rank (``anrind_order``) and the post-baseline rule (``prefilter``).
    """

    context: ClassVar[str] = "t_lb_shift"
    nested: ClassVar[bool] = True
    prefilter_hint: ClassVar[str] = _POST_BASELINE_HINT

    _unconsumed_spec_fields: ClassVar[frozenset[str]] = frozenset(
        {"rows", "header_rows", "value_col", "missing"}
    )

    prefilter: Any | None = Field(
        default=POST_BASELINE_PREFILTER, description=_PREFILTER_DESCRIPTION
    )
    statistics: list[Statistic] = Field(
        default_factory=lambda: [Statistic.N_SUBJECTS],
    )
    anrind_order: list[str] = Field(
        default_factory=lambda: ["NORMAL", "LOW", "HIGH", "LOW LOW", "HIGH HIGH"],
        description="Range indicators from least to most abnormal (worst-case rank).",
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "PARAMCD", "BNRIND", "ANRIND"],
    )


class LBAbnormalSpec(SummarySpecBase):
    """Spec for laboratory abnormalities not present at baseline (lbt04).

    The ``prefilter`` is the post-baseline rule; the baseline lookup
    reads the records before it.
    """

    context: ClassVar[str] = "t_lb_abnormal"
    prefilter_hint: ClassVar[str] = _POST_BASELINE_HINT

    _unconsumed_spec_fields: ClassVar[frozenset[str]] = frozenset(
        {"rows", "statistics", "header_rows", "pools", "value_col", "label_col", "missing"}
    )

    prefilter: Any | None = Field(
        default=POST_BASELINE_PREFILTER, description=_PREFILTER_DESCRIPTION
    )
    low_values: list[str] = Field(
        default_factory=lambda: ["LOW", "LOW LOW"],
        description="ANRIND values counted as the Low direction (any case).",
    )
    high_values: list[str] = Field(
        default_factory=lambda: ["HIGH", "HIGH HIGH"],
        description="ANRIND values counted as the High direction (any case).",
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "PARAMCD", "BNRIND", "ANRIND"],
    )


#: ANRIND values that mean "in range" or "not graded".
_NORMAL_CODES = frozenset({"", "NORMAL", "N"})


def _check_anrind_codes(post: pl.DataFrame, spec: LBAbnormalSpec) -> None:
    """Raise when ANRIND has abnormal codes that no direction names."""
    present = set(post["__anrind"].drop_nulls().str.strip_chars().unique().to_list())
    present -= _NORMAL_CODES
    levels = {v.upper() for v in [*spec.low_values, *spec.high_values]}
    if present and not present & levels:
        raise SchemaError(
            f"ANRIND has codes {sorted(present)} and none is in low_values "
            f"{spec.low_values} or high_values {spec.high_values}. Set them in the "
            "spec: LBAbnormalSpec(low_values=['L'], high_values=['H']), or the "
            "low_values and high_values keys of the YAML spec."
        )


class LBTLGNamespace(BuilderVerbsMixin):
    """Laboratory tables, listings, and diagnostics.

    Accessed as ``df.tlg.lb``.  Provides the LBT01 continuous lab
    statistics table and the LBL01 abnormalities listing.

    Args:
        df: A Polars DataFrame containing ADaM ADLB-level data.
    """

    _builder_specs = {
        "t_summary": LBSummarySpec,
        "t_chg": LBChgSpec,
        "t_shift": LBShiftSpec,
        "t_abnormal": LBAbnormalSpec,
        "l_listing": LBListingSpec,
    }

    def __init__(self, df: pl.DataFrame) -> None:
        self._df = df

    # ------------------------------------------------------------------ #
    # Summary table (LBT01)                                                #
    # ------------------------------------------------------------------ #

    def t_summary(
        self,
        *,
        groupby: str | None = None,
        adsl: pl.DataFrame | None = None,
        spec: LBSummarySpec | None = None,
    ) -> pl.DataFrame:
        """Produce a laboratory summary ARD (Analysis Results Dataset).

        Computes big-N from *adsl*, then continuous statistics for each
        parameter at each analysis visit (or custom row hierarchy),
        cards-aligned for downstream rendering.

        Args:
            groupby: Treatment arm column name.  Overrides
                ``spec.columns[0]`` when given.
            adsl: ADSL DataFrame for big-N denominators.
            spec: Optional ``LBSummarySpec`` override.  If ``None``, the
                default spec is used.

        Returns:
            pl.DataFrame: ARD in the {cards} long layout, with columns
                ``group1``, ``group1_level``, ``group2``, ``group2_level``,
                ``variable``, ``variable_level``, ``stat_name``,
                ``stat_label``, ``stat``, ``fmt_fn``, ``stat_fmt``,
                ``warning``, ``error``, ``context``.

        Examples:
            lab summary, ADSL arm in TRT01A::

                spec = LBSummarySpec(adsl_group_col="TRT01A")
                ard = adlb.tlg.lb.t_summary(spec=spec, adsl=adsl)

            Custom spec with pooled arms::

                from fleet.tlg import GroupPool

                from fleet.tlg.lb_namespace import LBSummarySpec

                spec = LBSummarySpec(
                    pools=[GroupPool(label="Total", arms="*")],
                    adsl_group_col="TRT01A",
                )
                ard = adlb.tlg.lb.t_summary(spec=spec, adsl=adsl)
        """
        return summarize_spec(self._df, spec or LBSummarySpec(), groupby=groupby, adsl=adsl)

    # ------------------------------------------------------------------ #
    # Change from baseline (LBT02/LBT03)                                   #
    # ------------------------------------------------------------------ #

    def t_chg(
        self,
        *,
        groupby: str | None = None,
        adsl: pl.DataFrame | None = None,
        spec: LBChgSpec | None = None,
    ) -> pl.DataFrame:
        """Mean change-from-baseline ARD per parameter and visit (LBT02).

        Summarizes ``spec.value_col`` (``CHG`` by default, not raw
        ``AVAL``) for post-baseline records, nested per parameter ×
        visit.  The paired n counts only subjects with a non-missing
        change value at the visit; baseline records are excluded
        null-safely (ADaM codes ``ABLFL`` as Y / null).  Both rules are
        the spec's prefilter, so ``ABLFL`` is a required column.

        Args:
            groupby: Treatment-arm column.
            adsl: ADSL DataFrame for big-N denominators.
            spec: Optional ``LBChgSpec`` override.

        Returns:
            pl.DataFrame: ARD in the {cards} long layout.

        Examples:
            ADSL arm in TRT01A::

                spec = LBChgSpec(adsl_group_col="TRT01A")
                ard = adlb.tlg.lb.t_chg(spec=spec, adsl=adsl)
        """
        return summarize_spec(self._df, spec or LBChgSpec(), groupby=groupby, adsl=adsl)

    # ------------------------------------------------------------------ #
    # Shift counts (LBT03)                                                 #
    # ------------------------------------------------------------------ #

    def t_shift(
        self,
        *,
        groupby: str | None = None,
        adsl: pl.DataFrame | None = None,
        spec: LBShiftSpec | None = None,
    ) -> pl.DataFrame:
        """Baseline → worst post-baseline shift table per parameter (LBT03).

        A true cross-tabulation: per parameter, each subject contributes
        one ``"<BNRIND> to <ANRIND>"`` shift cell, where ANRIND is their
        worst post-baseline range indicator (NORMAL < LOW < HIGH <
        LOW LOW < HIGH HIGH — deterministic clinical rank, HIGH breaking
        the LOW/HIGH tie).  Only post-baseline records count: the
        spec's ``prefilter`` states the rule (default ``ONTRTFL`` = Y
        and not the ``ABLFL`` record); subjects without a baseline
        indicator are excluded.

        Percentages are intentionally not emitted: the correct
        denominator is subjects with both a baseline and a post-baseline
        result per parameter, which needs per-cell denominator support
        in the engine (next round) — a percentage against the arm big-N
        would be wrong, so a statistic other than n raises.

        Args:
            groupby: Treatment-arm column.
            adsl: ADSL DataFrame for the arm universe and big-N rows.
            spec: Optional ``LBShiftSpec`` override.

        Returns:
            pl.DataFrame: ARD in the {cards} long layout (subject counts).

        Raises:
            SchemaError: If the spec carries ``rows`` or ``header_rows``
                — the shift hierarchy is fixed and would silently ignore
                them —, a statistic other than ``n_subjects``, or if a
                column of the post-baseline rule is missing.

        Examples:
            ADSL arm in TRT01A::

                spec = LBShiftSpec(adsl_group_col="TRT01A")
                ard = adlb.tlg.lb.t_shift(spec=spec, adsl=adsl)
        """
        spec = spec or LBShiftSpec()
        if spec.rows or spec.header_rows:
            raise SchemaError(
                "t_shift's row hierarchy is fixed (PARAMCD → baseline-to-worst "
                "shift cell) and it emits no header rows — 'rows' and "
                "'header_rows' in the spec would be silently ignored, so they "
                "are rejected. Use t_summary for a custom hierarchy."
            )
        other = [s.value for s in spec.statistics if s != Statistic.N_SUBJECTS]
        if other:
            raise SchemaError(
                f"t_shift emits subject counts only; remove {other}. A "
                "percentage of the arm big N would be wrong: the denominator "
                "is the subjects with a baseline and a post-baseline result."
            )
        group_col = groupby or (spec.columns[0] if spec.columns else "TRTA")
        spec.validate_dataframe(self._df, group_col=group_col)
        # The dataset filter must bite before the worst-case reduction:
        # a filtered-out record must not decide a subject's worst level.
        post = prepare_frame(self._df, spec).filter(pl.col("ANRIND").is_not_null())
        worst = worst_case(
            post,
            by=["USUBJID", group_col, "PARAMCD"],
            order_col="ANRIND",
            order=spec.anrind_order,
            order_field="anrind_order",
        )
        shift = worst.filter(pl.col("BNRIND").is_not_null()).with_columns(
            (pl.col("BNRIND").cast(pl.Utf8) + " to " + pl.col("ANRIND").cast(pl.Utf8)).alias(
                "SHIFT"
            )
        )
        return summarize_ard(
            shift,
            rows=["PARAMCD", "SHIFT"],
            stats=spec.statistics,
            context=spec.context,
            group_col=group_col,
            pools=spec.pools,
            column_order=spec.column_order,
            adsl=adsl,
            adsl_filter=spec.adsl_filter,
            nested=spec.nested,
            label_col=spec.label_col,
            decimals=spec.decimals,
            adsl_group_col=spec.adsl_group_col,
        )

    # ------------------------------------------------------------------ #
    # Abnormal counts (LBT04)                                              #
    # ------------------------------------------------------------------ #

    def t_abnormal(
        self,
        *,
        groupby: str | None = None,
        adsl: pl.DataFrame | None = None,
        spec: LBAbnormalSpec | None = None,
    ) -> pl.DataFrame:
        """Laboratory abnormalities not present at baseline (LBT04).

        Per parameter and direction (Low = LOW / LOW LOW, High = HIGH /
        HIGH HIGH), following ``crane::ard_tabulate_abnormal``:

        - denominator ``N`` = subjects with ≥1 post-baseline assessment
          whose baseline is **not** abnormal in that direction;
        - numerator ``n`` = those with any post-baseline value in the
          direction;
        - ``pct`` = n / N (null when N = 0 — never fabricated).

        Post-baseline means the spec's ``prefilter`` (default
        ``ONTRTFL`` = Y and not the ``ABLFL`` record).  The baseline
        lookup reads the records before the prefilter, so ``BNRIND`` is
        a required column.  To apply no baseline exclusion, add a null
        ``BNRIND`` column.

        The directions read ``spec.low_values`` and ``spec.high_values``
        (default ``LOW``/``LOW LOW`` and ``HIGH``/``HIGH HIGH``), in any
        case.  When ANRIND holds other codes, such as ``H`` and ``L``,
        set them in the spec; the table stops when no code of the data
        is in either list.  An arm with no analysis record keeps its
        column with N=0, as in ``t_summary``.

        Args:
            groupby: Treatment-arm column.
            adsl: ADSL DataFrame for the arm universe and big-N rows.
            spec: Optional ``LBAbnormalSpec`` override.

        Returns:
            pl.DataFrame: ARD in the {cards} long layout.

        Raises:
            SchemaError: If ANRIND holds abnormal codes and none of them
                is in ``low_values`` or ``high_values``.

        Examples:
            ADSL arm in TRT01A::

                spec = LBAbnormalSpec(adsl_group_col="TRT01A")
                ard = adlb.tlg.lb.t_abnormal(spec=spec, adsl=adsl)

            Sponsor low and high flags::

                spec = LBAbnormalSpec(
                    low_values=["L"], high_values=["H"], adsl_group_col="TRT01A"
                )
                ard = adlb.tlg.lb.t_abnormal(spec=spec, adsl=adsl)
        """
        spec = spec or LBAbnormalSpec()
        group_col = groupby or (spec.columns[0] if spec.columns else "TRTA")
        spec.validate_dataframe(self._df, group_col=group_col)
        if spec.pools or spec.header_rows:
            raise SchemaError(
                "t_abnormal does not support pools or header_rows yet — "
                "its per-cell denominators need dedicated engine support."
            )
        source = self._df
        if group_col not in source.columns:
            raise SchemaError(
                f"Group column '{group_col}' not found in the analysis dataset. "
                f"Available: {sorted(source.columns)}"
            )
        check_text_arm(source, group_col, "the analysis dataset")
        adsl_col = spec.adsl_group_col or group_col
        if adsl is not None and adsl_col in adsl.columns:
            check_text_arm(adsl, adsl_col, "adsl")
        categories = enum_arms(adsl, adsl_col) or enum_arms(source, group_col)
        source = source.with_columns(pl.col(group_col).cast(pl.Utf8))
        known_arms = set(source[group_col].drop_nulls().unique().to_list())
        # The baseline lookup needs the records the post-baseline rule drops.
        source = prepare_frame(source, spec.model_copy(update={"prefilter": None}))
        if adsl is not None:
            if "USUBJID" not in adsl.columns:
                raise SchemaError("adsl has no USUBJID column.")
            source = restrict_to_population(source, adsl, spec.adsl_filter)
        elif spec.adsl_filter is not None:
            raise SchemaError("adsl_filter is set but no adsl was given: pass adsl=... .")
        post_rule = resolve_filter(spec.prefilter)
        post = source.filter(post_rule) if post_rule is not None else source
        post = post.filter(pl.col("ANRIND").is_not_null())
        post = post.with_columns(pl.col("ANRIND").str.to_uppercase().alias("__anrind"))
        _check_anrind_codes(post, spec)

        context = spec.context
        arms, big_n = resolve_arms(
            set(post[group_col].drop_nulls().unique().to_list()),
            group_col,
            adsl=adsl,
            adsl_group_col=spec.adsl_group_col,
            adsl_filter=spec.adsl_filter,
            pools=[],
            column_order=spec.column_order,
            known_arms=known_arms,
            categories=categories,
        )

        fmt = spec.decimals or {}
        rows_out: list[dict[str, object]] = []
        if adsl is not None:
            rows_out += [
                ard_row(
                    group_col, arm, "", "", "N", "N", big_n.get(arm), context, fmt_fn=fmt.get("N")
                )
                for arm in arms
            ]

        directions = {
            "Low": [v.upper() for v in spec.low_values],
            "High": [v.upper() for v in spec.high_values],
        }
        baseline = source.with_columns(
            pl.col("BNRIND").cast(pl.Utf8).str.to_uppercase().alias("__bnrind")
        )
        for param in sorted(post["PARAMCD"].drop_nulls().unique().to_list()):
            p_post = post.filter(pl.col("PARAMCD") == param)
            for direction, levels in directions.items():
                base_abnormal = set(
                    baseline.filter(
                        (pl.col("PARAMCD") == param) & pl.col("__bnrind").is_in(levels)
                    )["USUBJID"].to_list()
                )
                for arm in arms:
                    a_post = p_post.filter(pl.col(group_col) == arm)
                    eligible = set(a_post["USUBJID"].to_list()) - base_abnormal
                    abnormal = set(
                        a_post.filter(pl.col("__anrind").is_in(levels))["USUBJID"].to_list()
                    )
                    n = len(abnormal & eligible)
                    denom = len(eligible)
                    # Unrounded — display precision belongs to fmt_fn.
                    pct = n / denom * 100 if denom > 0 else None
                    lineage = {"group2": "PARAMCD", "group2_level": str(param)}
                    rows_out += [
                        ard_row(
                            group_col,
                            arm,
                            "ABNORMAL",
                            direction,
                            "n",
                            "n",
                            n,
                            context,
                            fmt_fn=fmt.get("n"),
                            **lineage,
                        ),
                        ard_row(
                            group_col,
                            arm,
                            "ABNORMAL",
                            direction,
                            "N",
                            "N assessed",
                            denom,
                            context,
                            fmt_fn=fmt.get("N"),
                            **lineage,
                        ),
                        ard_row(
                            group_col,
                            arm,
                            "ABNORMAL",
                            direction,
                            "pct",
                            "n / N (%)",
                            pct,
                            context,
                            fmt_fn=fmt.get("pct"),
                            **lineage,
                        ),
                    ]

        ard = rows_to_ard(rows_out)
        issues = validate_ard(ard)
        if issues:
            raise SchemaError("ARD output failed schema validation:\n  " + "\n  ".join(issues))
        return ard

    # ------------------------------------------------------------------ #
    # Listing (LBL01)                                                      #
    # ------------------------------------------------------------------ #

    def l_listing(
        self,
        *,
        spec: LBListingSpec | None = None,
    ) -> pl.DataFrame:
        """Produce a laboratory abnormalities listing DataFrame.

        Applies ``dataset_filter``, then the spec's ``prefilter`` (by
        default a non-normal range indicator, ``ANRIND``), sorts by
        ``sort_by`` (a key need not be a displayed column), formats
        each column with its ``Column.format`` and keeps the requested
        columns.

        Args:
            spec: Optional ``LBListingSpec`` override.  If ``None``, the
                default spec is used.

        Returns:
            pl.DataFrame: A plain DataFrame with the requested columns,
                sorted per spec.

        Raises:
            SchemaError: If a listing column or a sort key that the user
                set is not in the dataset, or a format cannot print a
                value.

        Examples:
            Default lab listing::

                listing = adlb.tlg.lb.l_listing()

            Custom listing with explicit columns::

                from fleet.tlg import Column

                from fleet.tlg.lb_namespace import LBListingSpec

                spec = LBListingSpec(
                    columns=[
                        Column(field="USUBJID", label="Subject"),
                        Column(field="PARAM", label="Parameter"),
                        Column(field="AVAL", label="Result"),
                    ],
                    sort_by=["USUBJID"],
                )
                listing = adlb.tlg.lb.l_listing(spec=spec)
        """
        spec = spec or LBListingSpec()
        spec.validate_dataframe(self._df)

        df = self._df
        dataset_filter = resolve_filter(spec.dataset_filter)
        if dataset_filter is not None:
            df = df.filter(dataset_filter)
        prefilter = resolve_filter(spec.prefilter)
        if prefilter is not None:
            df = df.filter(prefilter)
        return listing_frame(df, spec, fallback={"PARAM": "PARAMCD"})

    # ------------------------------------------------------------------ #
    # Pre-validation diagnostic                                            #
    # ------------------------------------------------------------------ #

    def check(
        self,
        *,
        spec: LBSummarySpec | None = None,
    ) -> list[str]:
        """Run pre-validation diagnostics without computing.

        Args:
            spec: Optional spec to check against.  If ``None``, the
                default ``LBSummarySpec`` is used.

        Returns:
            list[str]: Diagnostic messages (empty if all checks pass).

        Examples:
            Check data readiness::

                report = adlb.tlg.lb.check()
        """
        spec = spec or LBSummarySpec()
        return spec.check(self._df)
