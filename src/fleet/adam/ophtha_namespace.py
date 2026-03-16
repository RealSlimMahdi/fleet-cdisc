"""
ADaM Ophthalmology namespace extension (admiralophtha-inspired).

Accessed via ``df.adam.ophtha`` on any Polars DataFrame.

Key derivations ported from pharmaverse/admiralophtha:
  - ``etdrs_to_logmar``   — ETDRS score → LogMAR (Beck et al. formula)
  - ``logmar_to_etdrs``   — LogMAR → ETDRS (inverse)
  - ``study_eye``         — SC FOCID code (OS/OD/OU) → LEFT/RIGHT/BILATERAL
  - ``affected_eye``      — derive AFEYE from laterality and study eye
  - ``bcva_criterion``    — flag records meeting a BCVA threshold criterion

Usage
-----
    import fleet  # triggers registration

    adbcva = (
        bcva_df.adam.ophtha
        .etdrs_to_logmar("LOGMAR", source="ETDRS")
        .study_eye("STUDYEYE", source="SCSTRESC")
        .bcva_criterion("BCVACR1FL", value_col="ETDRS", threshold=70,
                        direction="ge")
        .to_frame()
    )
"""

from __future__ import annotations

from typing import Any, Self

import polars as pl

from ._mixins import SharedADaMVerbsMixin


class OphthaNamespace(SharedADaMVerbsMixin):
    """
    Immutable pipeline builder for ADaM ophthalmology derivations.

    Inherits shared verbs from ``SharedADaMVerbsMixin``.
    """

    # ------------------------------------------------------------------ #
    # 1. etdrs_to_logmar — ETDRS score → LogMAR                          #
    # ------------------------------------------------------------------ #

    def etdrs_to_logmar(
        self,
        target: str,
        *,
        source: str,
        round_digits: int | None = 4,
    ) -> Self:
        """
        Convert an ETDRS letter score in *source* to LogMAR units.

        Formula (Beck et al., Am J Ophthalmol 2003):

            logMAR = -0.02 × ETDRS + 1.7

        Example::

            .etdrs_to_logmar("LOGMAR", source="ETDRS")
        """
        expr = (-0.02 * pl.col(source) + 1.7)
        if round_digits is not None:
            expr = expr.round(round_digits)
        return self._chain(expr.alias(target))

    # ------------------------------------------------------------------ #
    # 2. logmar_to_etdrs — LogMAR → ETDRS                                #
    # ------------------------------------------------------------------ #

    def logmar_to_etdrs(
        self,
        target: str,
        *,
        source: str,
        round_digits: int | None = 1,
    ) -> Self:
        """
        Convert a LogMAR value in *source* back to ETDRS letter score.

        Inverse of the Beck formula:

            ETDRS = (1.7 - logMAR) / 0.02

        Example::

            .logmar_to_etdrs("ETDRS", source="LOGMAR")
        """
        expr = (1.7 - pl.col(source)) / 0.02
        if round_digits is not None:
            expr = expr.round(round_digits)
        return self._chain(expr.alias(target))

    # ------------------------------------------------------------------ #
    # 3. study_eye — derive STUDYEYE from SC FOCID                       #
    # ------------------------------------------------------------------ #

    def study_eye(
        self,
        target: str,
        *,
        source: str,
    ) -> Self:
        """
        Map SC FOCID laterality codes to plain-text study eye labels.

        ========  ===========
        FOCID     STUDYEYE
        ========  ===========
        OS        LEFT
        OD        RIGHT
        OU        BILATERAL
        (other)   null
        ========  ===========

        Mirrors ``admiralophtha::derive_var_studyeye``.

        Example::

            .study_eye("STUDYEYE", source="SCSTRESC")
        """
        return self._chain(
            pl.when(pl.col(source).str.to_uppercase() == "OS")
            .then(pl.lit("LEFT"))
            .when(pl.col(source).str.to_uppercase() == "OD")
            .then(pl.lit("RIGHT"))
            .when(pl.col(source).str.to_uppercase() == "OU")
            .then(pl.lit("BILATERAL"))
            .otherwise(pl.lit(None))
            .alias(target)
        )

    # ------------------------------------------------------------------ #
    # 4. affected_eye — derive AFEYE from laterality and study eye        #
    # ------------------------------------------------------------------ #

    def affected_eye(
        self,
        target: str,
        *,
        loc_col: str,
        lat_col: str,
        study_eye_col: str = "STUDYEYE",
        loc_values: list[str] | None = None,
    ) -> Self:
        """
        Derive Affected Eye (``AFEYE``) from the laterality and study eye columns.

        Logic (mirrors ``admiralophtha::derive_var_afeye``):

        - Laterality == ``"BILATERAL"`` and location in *loc_values* → ``"Both Eyes"``
        - Study Eye == ``"BILATERAL"`` and laterality in valid list → ``"Study Eye"``
        - Laterality matches Study Eye → ``"Study Eye"``
        - Laterality differs from Study Eye → ``"Fellow Eye"``
        - Otherwise → null

        *loc_values*: valid location values (default: ``["EYE"]``).

        Example::

            .affected_eye("AFEYE", loc_col="AELOC", lat_col="AELAT")
        """
        locs = [v.upper() for v in (loc_values or ["EYE"])]
        valid_lat = ["LEFT", "RIGHT", "BILATERAL"]

        seye_up = pl.col(study_eye_col).str.to_uppercase()
        lat_up = pl.col(lat_col).str.to_uppercase()
        loc_up = pl.col(loc_col).str.to_uppercase()

        return self._chain(
            pl.when(
                seye_up.is_in(["LEFT", "RIGHT", "BILATERAL"])
                & lat_up.eq(pl.lit("BILATERAL"))
                & loc_up.is_in(locs)
            )
            .then(pl.lit("Both Eyes"))
            .when(
                seye_up.eq(pl.lit("BILATERAL"))
                & lat_up.is_in(valid_lat)
                & loc_up.is_in(locs)
            )
            .then(pl.lit("Study Eye"))
            .when(
                lat_up.eq(seye_up)
                & seye_up.is_in(["LEFT", "RIGHT", "BILATERAL"])
                & lat_up.is_in(valid_lat)
                & loc_up.is_in(locs)
            )
            .then(pl.lit("Study Eye"))
            .when(
                lat_up.ne(seye_up)
                & seye_up.is_in(["LEFT", "RIGHT", "BILATERAL"])
                & lat_up.is_in(valid_lat)
                & loc_up.is_in(locs)
            )
            .then(pl.lit("Fellow Eye"))
            .otherwise(pl.lit(None))
            .alias(target)
        )

    # ------------------------------------------------------------------ #
    # 5. bcva_criterion — flag records meeting a BCVA threshold           #
    # ------------------------------------------------------------------ #

    def bcva_criterion(
        self,
        target: str,
        *,
        value_col: str,
        threshold: float,
        direction: str = "ge",
        flag_value: str = "Y",
    ) -> Self:
        """
        Flag records where *value_col* meets a BCVA criterion threshold.

        *direction*: ``"ge"`` (≥), ``"gt"`` (>), ``"le"`` (≤), ``"lt"`` (<).

        Equivalent to the ``CRITx``/``CRITxFL`` pair in admiralophtha.

        Example::

            .bcva_criterion("BCVACR1FL", value_col="ETDRS",
                            threshold=70, direction="ge")
        """
        direction = direction.lower()
        col = pl.col(value_col)
        if direction == "ge":
            cond = col >= threshold
        elif direction == "gt":
            cond = col > threshold
        elif direction == "le":
            cond = col <= threshold
        elif direction == "lt":
            cond = col < threshold
        else:
            raise ValueError(f"direction must be one of ge/gt/le/lt, got '{direction}'.")

        return self._chain(
            pl.when(cond)
            .then(pl.lit(flag_value))
            .otherwise(pl.lit(None))
            .alias(target)
        )

