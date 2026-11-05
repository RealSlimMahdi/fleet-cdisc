"""
EG TLG sub-namespace — ECG summary tables.

Accessed via ``df.tlg.eg`` on any Polars DataFrame containing ADaM ADEG data.
"""

from __future__ import annotations

from typing import ClassVar, Literal

import polars as pl
from pydantic import Field, model_validator

from ._ard import (
    default_fmt_fn,
    format_ard,
    prepare_frame,
    restrict_to_population,
    summarize_ard,
    summarize_spec,
    validate_ard,
)
from ._builder import BuilderVerbsMixin
from ._specs import (
    Row,
    SchemaError,
    Statistic,
    SummarySpecBase,
    change_from_baseline_prefilter,
)


class EGSummarySpec(SummarySpecBase):
    """Spec for an ECG summary table (t_eg_summary).

    Defaults provide zero-config convenience for a standard ADEG
    per-PARAM × AVISIT continuous-stats table.  Every field is also
    settable inline through [`TLGBuilder`][fleet.tlg.TLGBuilder].
    """

    context: ClassVar[str] = "t_eg_summary"
    nested: ClassVar[bool] = True

    rows: list[Row] = Field(
        default_factory=lambda: [
            Row(field="PARAMCD", label="Parameter"),
            Row(field="AVISIT", label="Visit"),
        ],
        description=(
            "Hierarchy of row groupings.  Set inline via "
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
            "Statistics computed per row.  Set inline via "
            "[`TLGBuilder.stats()`][fleet.tlg.TLGBuilder.stats]."
        ),
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "PARAMCD", "AVAL", "AVISIT", "TRTA"],
        description="Columns required in the analysis dataset for this spec.",
    )


class EGChgSpec(EGSummarySpec):
    """Spec for ECG change from baseline (egt03): CHG stats per PARAM × visit.

    Prefilter rule: the baseline record (``ABLFL`` = Y) and records
    with no change value are dropped before summarising, so ``ABLFL``
    is a required column.  Unless set, the prefilter follows
    ``value_col``; ``prefilter=None`` switches the rule off.
    """

    context: ClassVar[str] = "t_eg_chg"

    value_col: str = Field(
        default="CHG",
        description="Analysis-value column summarized (change from baseline).",
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "PARAMCD", "AVISIT", "CHG"],
    )

    @model_validator(mode="after")
    def _default_prefilter_follows_value_col(self) -> EGChgSpec:
        if "prefilter" not in self.model_fields_set:
            self.prefilter = change_from_baseline_prefilter(self.value_col)
        return self


class EGQtcatSpec(SummarySpecBase):
    """Spec for QTc category counts (egt05_qtcat): n / % per PARAM × visit × category.

    The row hierarchy is fixed: one block per parameter and visit, with
    the AVALCAT1 categories inside it.  ``percent_base`` selects the
    percentage denominator.
    """

    context: ClassVar[str] = "t_eg_qtcat"
    nested: ClassVar[bool] = True

    _unconsumed_spec_fields: ClassVar[frozenset[str]] = frozenset(
        {"rows", "header_rows", "value_col", "label_col", "missing"}
    )

    percent_base: Literal["visit", "adsl"] = Field(
        default="visit",
        description=(
            "Percentage denominator.  ``visit``: subjects with a non-missing "
            "AVALCAT1 in the arm, parameter and visit (the block's n row).  "
            "``adsl``: the arm's big N from ADSL."
        ),
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "PARAMCD", "AVISIT", "AVALCAT1"],
    )


_QTC_BLOCK = "__QTC_BLOCK"
_QTC_GROUP2 = "PARAMCD / AVISIT"
_QTCAT_STATS = frozenset({Statistic.N_SUBJECTS, Statistic.N_PCT})


class EGTLGNamespace(BuilderVerbsMixin):
    """ECG tables and diagnostics.

    Accessed as ``df.tlg.eg``.  Supports both spec-driven
    (``t_summary(spec=...)``) and inline builder (``df.tlg.eg.by(...)``)
    workflows.

    Args:
        df: A Polars DataFrame containing ADaM ADEG-level data.
    """

    _builder_specs = {"t_summary": EGSummarySpec, "t_chg": EGChgSpec, "t_qtcat": EGQtcatSpec}

    def __init__(self, df: pl.DataFrame) -> None:
        self._df = df

    # ------------------------------------------------------------------ #
    # Summary table                                                        #
    # ------------------------------------------------------------------ #

    def t_summary(
        self,
        *,
        groupby: str | None = None,
        adsl: pl.DataFrame | None = None,
        spec: EGSummarySpec | None = None,
    ) -> pl.DataFrame:
        """Produce an ECG summary ARD (Analysis Results Dataset).

        Computes big-N from *adsl*, then continuous statistics for each
        parameter × visit (or custom row hierarchy).

        Args:
            groupby: Treatment arm column name.  Overrides
                ``spec.columns[0]`` when given.
            adsl: ADSL DataFrame for big-N denominators.
            spec: Optional ``EGSummarySpec`` override.  If ``None``, the
                default spec is used.

        Returns:
            pl.DataFrame: ARD in the {cards} long layout.

        Examples:
            EG summary, ADSL arm in TRT01A::

                spec = EGSummarySpec(adsl_group_col="TRT01A")
                ard = adeg.tlg.eg.t_summary(spec=spec, adsl=adsl)

            Custom spec with pooled arms::

                from fleet.tlg import EGSummarySpec, GroupPool

                spec = EGSummarySpec(
                    pools=[GroupPool(label="Total", arms="*")],
                    adsl_group_col="TRT01A",
                )
                ard = adeg.tlg.eg.t_summary(spec=spec, adsl=adsl)
        """
        return summarize_spec(self._df, spec or EGSummarySpec(), groupby=groupby, adsl=adsl)

    # ------------------------------------------------------------------ #
    # Change-from-baseline (egt03) — continuous                            #
    # ------------------------------------------------------------------ #

    def t_chg(
        self,
        *,
        groupby: str | None = None,
        adsl: pl.DataFrame | None = None,
        spec: EGChgSpec | None = None,
    ) -> pl.DataFrame:
        """ECG change-from-baseline ARD (continuous, egt03).

        Summarizes ``spec.value_col`` (``CHG`` by default) with
        mean/SD/median/min/max per PARAMCD × AVISIT for post-baseline
        records with a non-missing change value (the spec's prefilter;
        ``ABLFL`` is required).

        Args:
            groupby: Treatment-arm column; overrides ``spec.columns[0]``.
            adsl: ADSL for big-N denominators.
            spec: Optional ``EGChgSpec`` override.

        Returns:
            pl.DataFrame: ARD in the {cards} long layout.

        Examples:
            ADSL arm in TRT01A::

                spec = EGChgSpec(adsl_group_col="TRT01A")
                ard = adeg.tlg.eg.t_chg(spec=spec, adsl=adsl)
        """
        return summarize_spec(self._df, spec or EGChgSpec(), groupby=groupby, adsl=adsl)

    # ------------------------------------------------------------------ #
    # QTc category counts (egt05_qtcat) — categorical                      #
    # ------------------------------------------------------------------ #

    def t_qtcat(
        self,
        *,
        groupby: str | None = None,
        adsl: pl.DataFrame | None = None,
        spec: EGQtcatSpec | None = None,
    ) -> pl.DataFrame:
        """QTc category-count ARD (n / %, egt05_qtcat).

        One block per parameter and visit (``group2`` is
        ``"PARAMCD / AVISIT"``).  Each block starts with an ``n`` row:
        the subjects with a non-missing AVALCAT1 in the arm, parameter
        and visit.  The category rows follow, in ``AVALCAT1N`` order when
        that column exists.  With ``percent_base="visit"`` (default) the
        percentage uses the block's n; with ``"adsl"`` it uses the arm's
        big N.  A null or blank AVALCAT1 is not counted.  Visits follow
        ``AVISITN`` when that column exists.

        Args:
            groupby: Treatment-arm column; overrides ``spec.columns[0]``.
            adsl: ADSL for big-N denominators.
            spec: Optional ``EGQtcatSpec`` override.

        Returns:
            pl.DataFrame: ARD in the {cards} long layout.

        Raises:
            SchemaError: If one subject has two records in one parameter
                and visit (the analysis records must be selected first,
                e.g. with ``ANL01FL``), if ``percent_base="adsl"`` has no
                *adsl*, or if the spec sets ``rows``, ``header_rows`` or
                statistics other than n and n (%).

        Examples:
            ADSL arm in TRT01A::

                spec = EGQtcatSpec(adsl_group_col="TRT01A")
                ard = adeg.tlg.eg.t_qtcat(spec=spec, adsl=adsl)
        """
        spec = spec or EGQtcatSpec()
        if spec.rows or spec.header_rows:
            raise SchemaError(
                "t_qtcat's row hierarchy is fixed (PARAMCD / AVISIT → AVALCAT1) and "
                "it emits no header rows: 'rows' and 'header_rows' are rejected."
            )
        extra = [s.value for s in spec.statistics if s not in _QTCAT_STATS]
        if extra:
            raise SchemaError(f"t_qtcat computes n and n (%) only; remove {extra}.")
        if spec.percent_base == "adsl" and adsl is None:
            raise SchemaError("percent_base='adsl' needs the ADSL big N: pass adsl=... .")
        group_col = groupby or (spec.columns[0] if spec.columns else "TRTA")
        spec.validate_dataframe(self._df, group_col=group_col)

        df = prepare_frame(self._df, spec)
        if adsl is not None and "USUBJID" in adsl.columns:
            df = restrict_to_population(df, adsl, spec.adsl_filter)
        df = df.with_columns(pl.col("AVALCAT1").cast(pl.Utf8)).filter(
            pl.col("AVALCAT1").str.strip_chars().fill_null("") != ""
        )
        dups = (
            df.group_by("USUBJID", "PARAMCD", "AVISIT")
            .len()
            .filter(pl.col("len") > 1)
            .sort("USUBJID", "PARAMCD", "AVISIT")
        )
        if dups.height:
            raise SchemaError(
                f"{dups.height} subject-parameter-visit cell(s) have more than one "
                f"record, e.g. {dups.head(5).drop('len').rows()}. Select one "
                "analysis record per subject, parameter and visit first (for "
                'example dataset_filter=\'pl.col("ANL01FL") == "Y"\').'
            )

        df = df.with_columns(
            (pl.col("PARAMCD").cast(pl.Utf8) + " / " + pl.col("AVISIT").cast(pl.Utf8)).alias(
                _QTC_BLOCK
            )
        )
        visit_key = ["PARAMCD", "AVISITN" if "AVISITN" in df.columns else "AVISIT"]
        block_order = (
            df.select(_QTC_BLOCK, *visit_key).drop_nulls(_QTC_BLOCK).unique().sort(visit_key)
        )[_QTC_BLOCK].unique(maintain_order=True)
        if "AVALCAT1N" in df.columns:
            cat_order = (
                df.group_by("AVALCAT1")
                .agg(pl.col("AVALCAT1N").min())
                .sort("AVALCAT1N", "AVALCAT1")["AVALCAT1"]
            )
        else:
            cat_order = df["AVALCAT1"].unique().sort()

        ard = summarize_ard(
            df,
            rows=[
                Row(field=_QTC_BLOCK, label="Parameter / Visit"),
                Row(field="AVALCAT1", label="QTc Category"),
            ],
            stats=[Statistic.N_SUBJECTS],
            context=spec.context,
            group_col=group_col,
            pools=spec.pools,
            column_order=spec.column_order,
            adsl=adsl,
            adsl_filter=spec.adsl_filter,
            nested=True,
            decimals=spec.decimals,
            adsl_group_col=spec.adsl_group_col,
        )
        big_n = ard.filter(pl.col("variable") == "")
        block_n = ard.filter(pl.col("variable") == _QTC_BLOCK).with_columns(
            group2=pl.lit(_QTC_GROUP2),
            group2_level=pl.col("variable_level"),
            variable=pl.lit("AVALCAT1"),
            variable_level=pl.lit("n"),
            variable_label=pl.lit("QTc Category"),
        )
        leaves = ard.filter(pl.col("group2") == _QTC_BLOCK).with_columns(group2=pl.lit(_QTC_GROUP2))
        if spec.percent_base == "visit":
            den = block_n.select("group1_level", "group2_level", pl.col("stat").alias("__den"))
            den_keys = ["group1_level", "group2_level"]
        else:
            den = big_n.select("group1_level", pl.col("stat").alias("__den"))
            den_keys = ["group1_level"]
        pct_fmt = (spec.decimals or {}).get("pct") or default_fmt_fn("pct")
        pct = (
            leaves.join(den, on=den_keys, how="left")
            .with_columns(
                stat_name=pl.lit("pct"),
                stat_label=pl.lit("n (%)"),
                stat=pl.when(pl.col("__den") > 0).then(pl.col("stat") / pl.col("__den") * 100),
                fmt_fn=pl.lit(pct_fmt),
            )
            .drop("__den")
        )
        parts = [block_n]
        if Statistic.N_SUBJECTS in spec.statistics:
            parts.append(leaves)
        if Statistic.N_PCT in spec.statistics:
            parts.append(pct)
        body = (
            pl.concat(parts, how="vertical_relaxed")
            .with_columns(
                pl.col("group2_level")
                .replace_strict(block_order, list(range(block_order.len())), default=None)
                .alias("__block"),
                pl.when(pl.col("variable_level") == "n")
                .then(-1)
                .otherwise(
                    pl.col("variable_level").replace_strict(
                        cat_order, list(range(cat_order.len())), default=None
                    )
                )
                .alias("__cat"),
            )
            .sort("__block", "__cat", maintain_order=True)
            .drop("__block", "__cat")
        )
        out = format_ard(pl.concat([big_n, body], how="vertical_relaxed"))
        issues = validate_ard(out)
        if issues:
            raise SchemaError("ARD output failed schema validation:\n  " + "\n  ".join(issues))
        return out

    # ------------------------------------------------------------------ #
    # Pre-validation diagnostic                                            #
    # ------------------------------------------------------------------ #

    def check(
        self,
        *,
        spec: EGSummarySpec | None = None,
    ) -> list[str]:
        """Run pre-validation diagnostics without computing.

        Args:
            spec: Optional spec to check against.

        Returns:
            list[str]: Diagnostic messages (empty if all checks pass).

        Examples:
            Check data readiness::

                report = adeg.tlg.eg.check()
        """
        spec = spec or EGSummarySpec()
        return spec.check(self._df)
