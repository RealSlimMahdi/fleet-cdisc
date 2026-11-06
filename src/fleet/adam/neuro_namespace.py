"""
ADaM Neuroscience namespace extension (admiralneuro-inspired).

Accessed via ``df.adam.neuro`` on any Polars DataFrame.

Key derivations, inspired by pharmaverse/admiralneuro and clinical neuroscience (not ports; values can differ):
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
from fleet.adam.utils import sas_round
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
        A SUVR of zero or below gives a null value (admiralneuro
        ``compute_centiloid`` stops on it). The value is rounded half away
        from zero (SAS ``ROUND``, ADR-0025).

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

        Raises:
            DerivationError: When only one of *slope* and *intercept* is
                given, or the tracer and pipeline have no calibration.

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
        if (slope is None) != (intercept is None):
            raise DerivationError("centiloid(): slope and intercept must be given together.")
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

        suvr = pl.col(suvr_col).cast(pl.Float64).fill_nan(None)
        expr = pl.when(suvr > 0).then(pl.lit(s) * suvr + pl.lit(i))
        return self._chain(sas_round(expr, round_digits).alias(target))

    # ------------------------------------------------------------------ #
    # 2. mmse_category — MMSE severity categories                        #
    # ------------------------------------------------------------------ #

    def mmse_category(
        self,
        target: str,
        *,
        score_col: str,
        normal_threshold: int = 24,
        mild_threshold: int = 19,
        moderate_threshold: int = 10,
    ) -> Self:
        """Categorise MMSE total score into severity levels.

        Defaults: Normal 24-30, Mild 19-23, Moderate 10-18, Severe 0-9.
        Each lower bound is an argument, so a SAP that uses other bands
        passes its own cut-offs.  A score below 0 or above 30 gets null.

        Args:
            target: Name of the output column.
            score_col: Column containing the MMSE total score.
            normal_threshold: Lower bound for Normal (default ``24``).
            mild_threshold: Lower bound for Mild (default ``19``).
            moderate_threshold: Lower bound for Moderate (default ``10``).

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Derive MMSE category::

                adcog = (
                    cog_raw.adam.neuro
                    .mmse_category("MMSECG", score_col="AVAL")
                    .to_frame()
                )

            Use the bands of a SAP that puts Mild at 21-26::

                adcog = (
                    cog_raw.adam.neuro
                    .mmse_category("MMSECG", score_col="AVAL",
                                   normal_threshold=27, mild_threshold=21)
                    .to_frame()
                )

        References:
            Folstein MF, Folstein SE, McHugh PR. Mini-mental state. J Psychiatr Res.
            1975;12:189-198 (the instrument). Default bands: Tombaugh TN, McIntyre
            NJ. The Mini-Mental State Examination: a comprehensive review. J Am
            Geriatr Soc. 1992;40:922-935 (24-30 normal, 19-23 mild, 10-18 moderate,
            9 and below severe). Other schemes are in use, for example mild 21-26
            and moderate 10-20; take the cut-offs from the SAP.
        """
        score = pl.col(score_col).cast(pl.Float64).fill_nan(None)
        return self._chain(
            pl.when(score > 30)
            .then(pl.lit(None, dtype=pl.String))
            .when(score >= normal_threshold)
            .then(pl.lit("Normal"))
            .when(score >= mild_threshold)
            .then(pl.lit("Mild"))
            .when(score >= moderate_threshold)
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
        Home & Hobbies, Personal Care (6 boxes, each 0–3). A null box gives a
        null total.

        Args:
            target: Name of the output column.
            domain_cols: The 6 CDR box score columns.
            round_digits: Decimal places to round to (default ``1``), half
                away from zero (SAS ``ROUND``, ADR-0025).

        Returns:
            Self: The namespace with *target* appended.

        Raises:
            DerivationError: When *domain_cols* does not name 6 columns.

        References:
            Morris JC. The Clinical Dementia Rating (CDR). Neurology.
            1993;43:2412-2414: the Sum of Boxes adds the 6 box scores.

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
        if len(domain_cols) != 6:
            raise DerivationError(f"cdrsob_total(): give the 6 CDR boxes, got {len(domain_cols)}.")
        total = pl.col(domain_cols[0])
        for col in domain_cols[1:]:
            total = total + pl.col(col)
        return self._chain(sas_round(total, round_digits).alias(target))

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

        Defaults: Normal 26-30, MCI 18-25, Impaired 0-17.  A score below 0
        or above 30 gets null.

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
        score = pl.col(score_col).cast(pl.Float64).fill_nan(None)
        return self._chain(
            pl.when(score > 30)
            .then(pl.lit(None, dtype=pl.String))
            .when(score >= normal_threshold)
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

        Raises:
            DerivationError: When a subscale column is not numeric (for
                example String); cast it to a number first.

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
        schema = self._lazy.collect_schema()
        for col in (positive_col, negative_col, general_col):
            dtype = schema.get(col)
            if dtype is not None and not (dtype.is_numeric() or dtype == pl.Null):
                raise DerivationError(
                    f"panss_total(): column '{col}' is {dtype}; cast it to a number first."
                )
        return self._chain(
            (pl.col(positive_col) + pl.col(negative_col) + pl.col(general_col)).alias(target)
        )
