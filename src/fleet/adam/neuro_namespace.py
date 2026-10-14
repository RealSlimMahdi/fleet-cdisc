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

from typing import Self

import polars as pl

from fleet.adam._mixins import SharedADaMVerbsMixin
from fleet.core.exceptions import DerivationError

# Centiloid calibration table (tracer + pipeline + ref_region → slope, intercept)
# Source: Navitsky et al. (2018), Sims et al. (2024), Royse et al. (2021)
_CENTILOID_CALIBRATIONS: dict[tuple[str, str, str], tuple[float, float]] = {
    ("18F-Florbetapir", "AVID FBP SUVR PIPELINE", "Whole Cerebellum"): (183.07, -177.26),
    ("18F-Florbetaben", "AVID FBB SUVR PIPELINE", "Whole Cerebellum"): (156.06, -148.13),
    ("18F-Florbetapir", "BERKELEY FBP SUVR PIPELINE", "Whole Cerebellum"): (188.22, -189.16),
    ("18F-Florbetaben", "BERKELEY FBB SUVR PIPELINE", "Whole Cerebellum"): (157.15, -151.87),
}


class NeuroNamespace(SharedADaMVerbsMixin):
    """
    Immutable pipeline builder for ADaM neuroscience derivations.

    Inherits shared verbs from ``SharedADaMVerbsMixin``.
    """

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
    ) -> Self:
        """Convert amyloid PET SUVR to the Centiloid scale.

        ``Centiloid = slope * SUVR + intercept``.  Provide either *slope* and
        *intercept* directly or *tracer* + *pipeline* for a built-in lookup.

        Args:
            target: Name of the output column.
            suvr_col: Column containing the SUVR value.
            slope: Calibration slope (provide with *intercept*).
            intercept: Calibration intercept.
            tracer: Tracer name for built-in lookup.
            pipeline: Pipeline name for built-in lookup.
            ref_region: Reference region (default ``"Whole Cerebellum"``).
            round_digits: Decimal places to round to (default ``2``).

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Convert SUVR to Centiloid with custom parameters::

                adapet = (
                    pet_raw.adam.neuro
                    .centiloid("CLV", suvr_col="SUVR",
                               slope=183.07, intercept=-177.26)
                    .to_frame()
                )

        References:
            Klunk WE et al. The Centiloid Project: standardizing quantitative amyloid
            plaque estimation by PET. Alzheimers Dement. 2015;11(1):1-15. The built-in
            tracer and pipeline calibrations follow admiralneuro
            ``derive_param_centiloid`` (pharmaverse).
        """
        if slope is not None and intercept is not None:
            s, i = slope, intercept
        elif tracer and pipeline:
            key = (tracer, pipeline, ref_region)
            if key not in _CENTILOID_CALIBRATIONS:
                valid = list(_CENTILOID_CALIBRATIONS.keys())
                raise DerivationError(
                    f"No calibration found for tracer={tracer!r}, "
                    f"pipeline={pipeline!r}, ref_region={ref_region!r}. "
                    f"Valid combinations: {valid}"
                )
            s, i = _CENTILOID_CALIBRATIONS[key]
        else:
            raise DerivationError("Provide either (slope, intercept) or (tracer, pipeline).")

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
    ) -> Self:
        """Categorise MMSE total score into severity levels.

        27–30 = Normal, 18–26 = Mild, 10–17 = Moderate, 0–9 = Severe.

        Args:
            target: Name of the output column.
            score_col: Column containing the MMSE total score.

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Derive MMSE category::

                adcog = (
                    cog_raw.adam.neuro
                    .mmse_category("MMSECG", score_col="AVAL")
                    .to_frame()
                )

        References:
            Folstein MF, Folstein SE, McHugh PR. Mini-mental state. J Psychiatr Res.
            1975;12:189-198 (the instrument). No single standard fixes the severity
            bands: NICE TA217 (2011) uses 21-26 mild, 10-20 moderate and below 10
            severe. Check the SAP before relying on the bands above.
        """
        score = pl.col(score_col)
        return self._chain(
            pl.when(score >= 27)
            .then(pl.lit("Normal"))
            .when(score >= 18)
            .then(pl.lit("Mild"))
            .when(score >= 10)
            .then(pl.lit("Moderate"))
            .when(score >= 0)
            .then(pl.lit("Severe"))
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
    ) -> Self:
        """Compute CDR Sum of Boxes (CDR-SoB) from domain box scores.

        Standard domains: Memory, Orientation, Judgment, Community Affairs,
        Home & Hobbies, Personal Care (6 boxes, each 0–3).

        Args:
            target: Name of the output column.
            domain_cols: List of CDR domain score columns.
            round_digits: Decimal places to round to (default ``1``).

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Derive CDR-SoB total from 6 domains::

                adcog = (
                    cog_raw.adam.neuro
                    .cdrsob_total("CDRSOB", domain_cols=[
                        "CDRMEM", "CDRORNT", "CDRJDGM",
                        "CDRCOMM", "CDRHOME", "CDRPERS"])
                    .to_frame()
                )
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
    ) -> Self:
        """Categorise MoCA total score into Normal / MCI / Impaired.

        Defaults: Normal ≥ 26, MCI 18–25, Impaired < 18.

        Args:
            target: Name of the output column.
            score_col: Column containing the MoCA total score.
            normal_threshold: Lower bound for Normal (default ``26``).
            mci_threshold: Lower bound for MCI (default ``18``).

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Derive MoCA category::

                adcog = (
                    cog_raw.adam.neuro
                    .moca_category("MOACG", score_col="AVAL")
                    .to_frame()
                )

        References:
            Nasreddine ZS et al. The Montreal Cognitive Assessment, MoCA. J Am Geriatr
            Soc. 2005;53:695-699: a total of 26 or more is normal. The MCI lower
            bound of 18 is not fixed by the instrument; check the SAP.
        """
        score = pl.col(score_col)
        return self._chain(
            pl.when(score >= normal_threshold)
            .then(pl.lit("Normal"))
            .when(score >= mci_threshold)
            .then(pl.lit("MCI"))
            .when(score >= 0)
            .then(pl.lit("Impaired"))
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
    ) -> Self:
        """Compute PANSS total = positive + negative + general subscales.

        Args:
            target: Name of the output column.
            positive_col: Column containing the positive subscale total.
            negative_col: Column containing the negative subscale total.
            general_col: Column containing the general subscale total.

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Derive PANSS total score::

                adnpi = (
                    npi_raw.adam.neuro
                    .panss_total("PANSSTOT", positive_col="PANSSPOS",
                                 negative_col="PANSSNEG",
                                 general_col="PANSSGEN")
                    .to_frame()
                )
        """
        return self._chain(
            (pl.col(positive_col) + pl.col(negative_col) + pl.col(general_col)).alias(target)
        )
