"""Pipeline Passport — attach reference domains to a pipeline instance.

``PinMixin`` adds ``.pin()`` / ``.repin()`` to any namespace that
inherits it.  Pinned DataFrames propagate via ``copy.copy()`` (the
same mechanism as ``_tdd_stage`` and ``_domain_meta`` in the TDD
mixin).  Cross-domain verbs retrieve pins with ``_require_pin()`` and
the stored join key with ``_pin_join_key()``.

Duplicate-pin guard (Option C — warn + ``.repin()`` hybrid):

* ``.pin("DM", df).pin("DM", df2)`` → emits ``UserWarning``, proceeds
* ``.repin("DM", df2)`` → silent replacement (explicit intent)

Every pin access is recorded in ``_pin_lineage`` via
``record_pin_lineage()`` so lineage / DAG integration is automatic.
"""

from __future__ import annotations

import copy
import warnings
from typing import TYPE_CHECKING, Any, ClassVar, Self

import polars as pl

from fleet.core.exceptions import DerivationError, PinError

if TYPE_CHECKING:
    pass


def _normalize_key(join_on: str | list[str]) -> list[str]:
    """Coerce *join_on* to a ``list[str]``."""
    return [join_on] if isinstance(join_on, str) else list(join_on)


class PinMixin:
    """Mixin that lets any namespace attach reference-domain DataFrames.

    Instance attributes set by this mixin (all survive ``copy.copy``):

    * ``_pinned`` — ``dict[str, tuple[pl.DataFrame, list[str]]]``
      keyed by upper-cased domain name → ``(dataframe, join_key)``.
    * ``_pin_lineage`` — ``list[PinDependency]`` accumulated cross-domain
      access records.
    * ``_fk_severity`` — default FK-check severity (``"warn"`` | ``"error"``
      | ``"off"``).
    """

    # Namespace subclasses override with domain-specific rules.
    _FK_RULES: ClassVar[dict[str, dict[str, str]]] = {}

    # ------------------------------------------------------------------ #
    # Public verbs                                                         #
    # ------------------------------------------------------------------ #

    def pin(
        self,
        domain: str,
        df: pl.DataFrame,
        *,
        join_on: str | list[str] = "USUBJID",
    ) -> Self:
        """Attach a reference domain to this pipeline.

        Args:
            domain: Logical name (e.g. ``"DM"``, ``"ADSL"``, ``"TV"``).
            df: The materialised reference DataFrame.
            join_on: Column(s) used to join this reference into the
                pipeline.  Stored and reused by all downstream verbs
                that consume this pin.

        Returns:
            Self: A shallow copy with the pin attached; call
                ``.to_frame()`` to materialise.

        Examples:
            Pin DM to an AE pipeline for study-day derivation::

                ae = (
                    ae_raw.sdtm
                    .assign("DOMAIN", value="AE")
                    .pin("DM", dm_df)
                    .study_day("AESTDY", date_col="AESTDTC")
                    .to_frame()
                )
        """
        new = copy.copy(self)
        key = domain.upper()
        pinned: dict[str, tuple[pl.DataFrame, list[str]]] = dict(getattr(self, "_pinned", {}))
        if key in pinned:
            warnings.warn(
                f"Pin '{key}' replaced. Use .repin() to suppress this warning.",
                stacklevel=2,
            )
        pinned[key] = (df, _normalize_key(join_on))
        new._pinned = pinned
        return new

    def repin(
        self,
        domain: str,
        df: pl.DataFrame,
        *,
        join_on: str | list[str] = "USUBJID",
    ) -> Self:
        """Replace an existing pin explicitly (no warning).

        Args:
            domain: Logical name to replace.
            df: The new reference DataFrame.
            join_on: Column(s) for the join key.

        Returns:
            Self: A shallow copy with the pin replaced.

        Examples:
            Replace a previously pinned DM with a filtered version::

                ae = (
                    ae_raw.sdtm
                    .pin("DM", dm_full)
                    .repin("DM", dm_filtered)
                    .study_day("AESTDY", date_col="AESTDTC")
                    .to_frame()
                )
        """
        new = copy.copy(self)
        pinned: dict[str, tuple[pl.DataFrame, list[str]]] = dict(getattr(self, "_pinned", {}))
        pinned[domain.upper()] = (df, _normalize_key(join_on))
        new._pinned = pinned
        return new

    def pins(self) -> dict[str, dict[str, Any]]:
        """Inspect currently pinned domains.

        Returns:
            dict: ``{domain: {"df": DataFrame, "join_on": [cols]}}``.

        Examples:
            Check what's pinned before study_day::

                ns = ae_raw.sdtm.pin("DM", dm_df).pin("TV", tv_df, join_on="VISITNUM")
                print(ns.pins())
                # {'DM': {'df': ..., 'join_on': ['USUBJID']},
                #  'TV': {'df': ..., 'join_on': ['VISITNUM']}}
        """
        pinned: dict[str, tuple[pl.DataFrame, list[str]]] = getattr(self, "_pinned", {})
        return {domain: {"df": df, "join_on": list(key)} for domain, (df, key) in pinned.items()}

    def fk_policy(self, severity: str) -> Self:
        """Set the default FK-check severity for this pipeline.

        Args:
            severity: One of ``"warn"`` (emit ``UserWarning``),
                ``"error"`` (raise ``ValueError``), or ``"off"``
                (disable FK checks).

        Returns:
            Self: A shallow copy with the updated policy.

        Examples:
            Enforce strict FK checking::

                ae = (
                    ae_raw.sdtm
                    .pin("DM", dm_df)
                    .fk_policy("error")
                    .assign("USUBJID", source="patient_number")
                    .to_frame()
                )
        """
        if severity not in ("warn", "error", "off"):
            raise DerivationError(
                f"fk_policy severity must be 'warn', 'error', or 'off', got '{severity}'"
            )
        new = copy.copy(self)
        new._fk_severity = severity
        return new

    # ------------------------------------------------------------------ #
    # Internal helpers (used by verbs)                                     #
    # ------------------------------------------------------------------ #

    def _require_pin(
        self,
        domain: str,
        verb: str,
        columns: list[str] | None = None,
    ) -> pl.DataFrame:
        """Retrieve a pinned DataFrame or raise an actionable error.

        Records the access in ``_pin_lineage`` automatically.

        Args:
            domain: Upper-cased domain name (e.g. ``"DM"``).
            verb: Name of the calling verb (for error messages and lineage).
            columns: If specified, return only these columns plus the
                join key — surgical extraction.

        Returns:
            pl.DataFrame: The pinned (or sliced) DataFrame.

        Raises:
            PinError: If the domain is not pinned, with an actionable
                message telling the user what to add.  Also catchable as
                ``LookupError``.
        """
        pinned: dict[str, tuple[pl.DataFrame, list[str]]] = getattr(self, "_pinned", {})
        key = domain.upper()
        if key not in pinned:
            raise PinError(
                f"{verb}() requires a pinned '{key}' domain. "
                f'Add .pin("{key}", {key.lower()}_df) before .{verb}() in your chain.'
            )
        df, join_key = pinned[key]
        if columns is not None:
            needed = list(dict.fromkeys(join_key + columns))
            df = df.select([c for c in needed if c in df.columns])
        return df

    def _pin_join_key(self, domain: str) -> list[str]:
        """Return the stored join key for a pinned domain.

        Args:
            domain: Upper-cased domain name.

        Raises:
            PinError: If *domain* is not pinned.  Also catchable as
                ``LookupError``.
        """
        pinned: dict[str, tuple[pl.DataFrame, list[str]]] = getattr(self, "_pinned", {})
        key = domain.upper()
        if key not in pinned:
            raise PinError(f"No pin found for domain '{key}'.")
        return list(pinned[key][1])

    def _check_fk(
        self,
        col: str,
        *,
        pin: str,
        ref_col: str | None = None,
        severity: str | None = None,
    ) -> set[str]:
        """Validate foreign-key integrity against a pinned domain.

        Args:
            col: Column in the current frame to validate.
            pin: Pinned domain name (e.g. ``"DM"``).
            ref_col: Column in the pinned frame to validate against.
                Defaults to *col*.
            severity: Override the pipeline-level FK severity.

        Returns:
            set[str]: The set of orphan values (empty when clean).
        """
        sev = severity or getattr(self, "_fk_severity", "warn")
        if sev == "off":
            return set()

        pinned: dict[str, tuple[pl.DataFrame, list[str]]] = getattr(self, "_pinned", {})
        if pin.upper() not in pinned:
            return set()

        ref_df, _ = pinned[pin.upper()]
        ref_column = ref_col or col
        if ref_column not in ref_df.columns:
            return set()

        # Materialise only the column we need
        current_vals = set(self._lazy.select(col).collect()[col].drop_nulls().to_list())
        ref_vals = set(ref_df[ref_column].drop_nulls().to_list())
        orphans = current_vals - ref_vals

        if orphans:
            msg = (
                f"FK check: {len(orphans)} value(s) in '{col}' not found in "
                f"pinned {pin}.{ref_column}: {sorted(orphans)[:5]}"
            )
            if sev == "error":
                raise DerivationError(msg)
            warnings.warn(msg, stacklevel=3)
        return orphans

    def _auto_fk_check(self, target: str) -> None:
        """Queue an FK check if *target* matches a rule in ``_FK_RULES``.

        The check itself is deferred to the next materialisation
        (``to_frame()`` runs all pending checks in one pass over the
        final frame) so pinning no longer forces a collect on every
        assign verb.  The severity in force *now* is captured with the
        queue entry, preserving ``fk_policy`` semantics.
        """
        rules: dict[str, dict[str, str]] = self.__class__._FK_RULES
        if target not in rules:
            return
        rule = rules[target]
        pin_domain = rule.get("pin", "")
        # Only check if the pin actually exists (no pin = no noise)
        if pin_domain.upper() not in getattr(self, "_pinned", {}):
            return
        severity = getattr(self, "_fk_severity", "warn")
        if severity == "off":
            return
        entry = (target, pin_domain, rule.get("ref_col", target), severity)
        pending: list[tuple[str, str, str, str]] = list(getattr(self, "_pending_fk_checks", []))
        if entry not in pending:
            pending.append(entry)
        self._pending_fk_checks = pending

    def _run_pending_fk_checks(self, df: pl.DataFrame) -> None:
        """Run all queued FK checks against the materialised *df*.

        Called by ``to_frame()`` after collection — one batched pass
        over the final frame instead of one collect per assign verb.
        Emits the same ``FK check`` warnings / errors as the immediate
        path.
        """
        pending: list[tuple[str, str, str, str]] = list(getattr(self, "_pending_fk_checks", []))
        if not pending:
            return
        # Clear before raising/warning so repeated to_frame() calls on the
        # same instance do not re-report (rebind, never mutate — earlier
        # chain copies keep their own queue).
        self._pending_fk_checks = []
        pinned: dict[str, tuple[pl.DataFrame, list[str]]] = getattr(self, "_pinned", {})
        for col, pin, ref_col, severity in pending:
            if severity == "off" or pin.upper() not in pinned:
                continue
            ref_df, _ = pinned[pin.upper()]
            if ref_col not in ref_df.columns or col not in df.columns:
                continue
            current_vals = set(df[col].drop_nulls().to_list())
            ref_vals = set(ref_df[ref_col].drop_nulls().to_list())
            orphans = current_vals - ref_vals
            if not orphans:
                continue
            msg = (
                f"FK check: {len(orphans)} value(s) in '{col}' not found in "
                f"pinned {pin}.{ref_col}: {sorted(orphans)[:5]}"
            )
            if severity == "error":
                raise DerivationError(msg)
            warnings.warn(msg, stacklevel=3)
