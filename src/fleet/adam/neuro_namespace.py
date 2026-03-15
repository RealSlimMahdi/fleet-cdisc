"""
ADaM Neuroscience namespace extension (admiralneuro-inspired).

Accessed via ``df.adam.neuro`` on any Polars DataFrame.

Key derivations ported from pharmaverse/admiralneuro and clinical neuroscience:
  - ``centiloid``       — amyloid PET SUVR → Centiloid scale (Navitsky et al.)
  - ``mmse_category``   — MMSE total score → severity category
  - ``cdrsob_total``    — CDR-SoB total from 6 domain box scores
  - ``moca_category``   — MoCA total score → category (Normal / MCI / Impaired)
  - ``panss_total``     — PANSS total = positive + negative + general subscales

Usage
-----
    import fleet  # triggers registration

    adapet = (
        pet_df.adam.neuro
        .source("USUBJID")
        .centiloid("CLV", suvr_col="SUVR", slope=183.07, intercept=-177.26)
        .to_frame()
    )

    adcog = (
        cog_df.adam.neuro
        .mmse_category("MMSECG", score_col="AVAL")
        .to_frame()
    )
"""

from __future__ import annotations

from typing import Any

import polars as pl

# Centiloid calibration table (tracer + pipeline + ref_region → slope, intercept)
# Source: Navitsky et al. (2018), Sims et al. (2024), Royse et al. (2021)
_CENTILOID_CALIBRATIONS: dict[tuple[str, str, str], tuple[float, float]] = {
    ("18F-Florbetapir",  "AVID FBP SUVR PIPELINE",     "Whole Cerebellum"): (183.07, -177.26),
    ("18F-Florbetaben",  "AVID FBB SUVR PIPELINE",     "Whole Cerebellum"): (156.06, -148.13),
    ("18F-Florbetapir",  "BERKELEY FBP SUVR PIPELINE",  "Whole Cerebellum"): (188.22, -189.16),
    ("18F-Florbetaben",  "BERKELEY FBB SUVR PIPELINE",  "Whole Cerebellum"): (157.15, -151.87),
}


class NeuroNamespace:
    """
    Immutable pipeline builder for ADaM neuroscience derivations.

    Follows the same immutable-builder pattern as ``AdamNamespace``.
    """

    def __init__(self, df: pl.DataFrame) -> None:
        self._lazy = df.lazy()

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _chain(self, *exprs: pl.Expr) -> "NeuroNamespace":
        new = object.__new__(NeuroNamespace)
        new._lazy = self._lazy.with_columns(list(exprs))
        return new

    def _materialise_then(self, df: pl.DataFrame) -> "NeuroNamespace":
        new = object.__new__(NeuroNamespace)
        new._lazy = df.lazy()
        return new

    # ------------------------------------------------------------------ #
    # Base verbs                                                           #
    # ------------------------------------------------------------------ #

    def source(self, target: str, *, from_col: str | None = None) -> "NeuroNamespace":
        """Copy *from_col* (or *target* itself) to *target*."""
        src = from_col if from_col is not None else target
        return self._chain(pl.col(src).alias(target))

    def assigned(self, target: str, *, value: Any) -> "NeuroNamespace":
        """Set *target* to a constant *value* for every record."""
        return self._chain(pl.lit(value).alias(target))

    def derivation(
        self, target: str, *, expression: str | pl.Expr
    ) -> "NeuroNamespace":
        """Arbitrary Polars expression derivation."""
        from ..sdtm.utils import parse_expression
        expr = (
            expression
            if isinstance(expression, pl.Expr)
            else parse_expression(str(expression))
        )
        return self._chain(expr.alias(target))

    def whereclauses(self, *, where: str | pl.Expr) -> "NeuroNamespace":
        """Filter the dataset to records matching *where*."""
        from ..sdtm.utils import parse_expression
        df = self.to_frame()
        fexpr = where if isinstance(where, pl.Expr) else parse_expression(str(where))
        return self._materialise_then(df.filter(fexpr))

    # ------------------------------------------------------------------ #
    # 1. centiloid — amyloid PET SUVR → Centiloid scale                  #
    # ------------------------------------------------------------------ #

    def centiloid(
        self,
        target: str,
        *,
        suvr_col: str,
        slope: float | None = None,
        intercept: float | None = None,
        tracer: str | None = None,
        pipeline: str | None = None,
        ref_region: str = "Whole Cerebellum",
        round_digits: int | None = 2,
    ) -> "NeuroNamespace":
        """
        Convert amyloid PET SUVR to the Centiloid scale.

        Formula (Centiloid Working Group):

            Centiloid = slope × SUVR + intercept

        Provide either:

        - *slope* and *intercept* directly (custom calibration), or
        - *tracer* + *pipeline* to look up pre-defined parameters from the
          built-in calibration table (see table below).

        Supported tracer × pipeline combinations
        (reference region always "Whole Cerebellum"):

        ==================  ==============================  =======  =========
        Tracer              Pipeline                        Slope    Intercept
        ==================  ==============================  =======  =========
        18F-Florbetapir     AVID FBP SUVR PIPELINE         183.07   -177.26
        18F-Florbetaben     AVID FBB SUVR PIPELINE         156.06   -148.13
        18F-Florbetapir     BERKELEY FBP SUVR PIPELINE     188.22   -189.16
        18F-Florbetaben     BERKELEY FBB SUVR PIPELINE     157.15   -151.87
        ==================  ==============================  =======  =========

        Example::

            # Custom parameters
            .centiloid("CLV", suvr_col="SUVR", slope=183.07, intercept=-177.26)

            # Pre-defined lookup
            .centiloid("CLV", suvr_col="SUVR",
                       tracer="18F-Florbetapir",
                       pipeline="AVID FBP SUVR PIPELINE")
        """
        if slope is not None and intercept is not None:
            s, i = slope, intercept
        elif tracer and pipeline:
            key = (tracer, pipeline, ref_region)
            if key not in _CENTILOID_CALIBRATIONS:
                valid = list(_CENTILOID_CALIBRATIONS.keys())
                raise ValueError(
                    f"No calibration found for tracer={tracer!r}, "
                    f"pipeline={pipeline!r}, ref_region={ref_region!r}. "
                    f"Valid combinations: {valid}"
                )
            s, i = _CENTILOID_CALIBRATIONS[key]
        else:
            raise ValueError(
                "Provide either (slope, intercept) or (tracer, pipeline)."
            )

        expr = pl.lit(s) * pl.col(suvr_col) + pl.lit(i)
        if round_digits is not None:
            expr = expr.round(round_digits)
        return self._chain(expr.alias(target))

    # ------------------------------------------------------------------ #
    # 2. mmse_category — MMSE severity categories                        #
    # ------------------------------------------------------------------ #

    def mmse_category(
        self,
        target: str,
        *,
        score_col: str,
    ) -> "NeuroNamespace":
        """
        Categorise MMSE total score into severity levels.

        Thresholds (Folstein / O'Bryant 2008):

        ==========  ============
        MMSE score  Category
        ==========  ============
        27 – 30     Normal
        18 – 26     Mild
        10 – 17     Moderate
        0 –  9      Severe
        ==========  ============

        Example::

            .mmse_category("MMSECG", score_col="AVAL")
        """
        score = pl.col(score_col)
        return self._chain(
            pl.when(score >= 27).then(pl.lit("Normal"))
            .when(score >= 18).then(pl.lit("Mild"))
            .when(score >= 10).then(pl.lit("Moderate"))
            .when(score >= 0).then(pl.lit("Severe"))
            .otherwise(pl.lit(None))
            .alias(target)
        )

    # ------------------------------------------------------------------ #
    # 3. cdrsob_total — CDR Sum of Boxes total                           #
    # ------------------------------------------------------------------ #

    def cdrsob_total(
        self,
        target: str,
        *,
        domain_cols: list[str],
        round_digits: int | None = 1,
    ) -> "NeuroNamespace":
        """
        Compute the CDR Sum of Boxes (CDR-SoB) as the sum of *domain_cols*.

        Standard domains: Memory, Orientation, Judgment, Community Affairs,
        Home & Hobbies, Personal Care (6 boxes, each scored 0–3).

        Null handling: records where one or more domain columns are null yield a
        null total.

        Example::

            .cdrsob_total("CDRSOB", domain_cols=[
                "CDRMEM", "CDRORNT", "CDRJDGM",
                "CDRCOMM", "CDRHOME", "CDRPERS",
            ])
        """
        total = sum(pl.col(c) for c in domain_cols)  # type: ignore[arg-type]
        if round_digits is not None:
            total = total.round(round_digits)
        return self._chain(total.alias(target))

    # ------------------------------------------------------------------ #
    # 4. moca_category — MoCA severity categories                        #
    # ------------------------------------------------------------------ #

    def moca_category(
        self,
        target: str,
        *,
        score_col: str,
        normal_threshold: int = 26,
        mci_threshold: int = 18,
    ) -> "NeuroNamespace":
        """
        Categorise MoCA total score (0–30) into three bands.

        =================  ==========
        MoCA score         Category
        =================  ==========
        ≥ normal_threshold Normal
        ≥ mci_threshold    MCI
        < mci_threshold    Impaired
        =================  ==========

        Defaults: Normal ≥ 26, MCI 18–25, Impaired < 18.

        Example::

            .moca_category("MOACG", score_col="AVAL")
        """
        score = pl.col(score_col)
        return self._chain(
            pl.when(score >= normal_threshold).then(pl.lit("Normal"))
            .when(score >= mci_threshold).then(pl.lit("MCI"))
            .when(score >= 0).then(pl.lit("Impaired"))
            .otherwise(pl.lit(None))
            .alias(target)
        )

    # ------------------------------------------------------------------ #
    # 5. panss_total — PANSS composite total                             #
    # ------------------------------------------------------------------ #

    def panss_total(
        self,
        target: str,
        *,
        positive_col: str,
        negative_col: str,
        general_col: str,
    ) -> "NeuroNamespace":
        """
        Compute PANSS total score = positive + negative + general subscale totals.

        Each subscale column should already be the subscale summary.

        Example::

            .panss_total("PANSSTOT",
                         positive_col="PANSSPOS",
                         negative_col="PANSSNEG",
                         general_col="PANSSGEN")
        """
        return self._chain(
            (pl.col(positive_col) + pl.col(negative_col) + pl.col(general_col))
            .alias(target)
        )

    # ------------------------------------------------------------------ #
    # Materialise                                                          #
    # ------------------------------------------------------------------ #

    def to_frame(self) -> pl.DataFrame:
        """Materialise the pipeline and return a ``pl.DataFrame``."""
        return self._lazy.collect()
