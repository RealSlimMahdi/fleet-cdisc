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
from typing import TYPE_CHECKING, Any, ClassVar, Self, overload

import polars as pl

from fleet.core.exceptions import DerivationError, PinError

if TYPE_CHECKING:
    pass


def _normalize_key(join_on: str | list[str]) -> list[str]:
    """Coerce *join_on* to a ``list[str]``."""
    return [join_on] if isinstance(join_on, str) else list(join_on)


def _pin_frame(name: str, frame: Any) -> pl.DataFrame:
    """Return *frame* as a DataFrame: a LazyFrame is collected once, here."""
    if isinstance(frame, pl.LazyFrame):
        return frame.collect()
    if not isinstance(frame, pl.DataFrame):
        raise DerivationError(
            f"pin '{name.upper()}': expected a DataFrame or LazyFrame, got {type(frame).__name__}."
        )
    return frame


#: Pipeline columns that the foreign-key check reads.  VISITNUM, VISIT,
#: EPOCH and ETCD are left out: an unscheduled visit or an unplanned
#: epoch is a valid value that the trial design does not list.
_FK_CHECKED: tuple[str, ...] = ("USUBJID",)


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

    @overload
    def pin(
        self,
        domain: str,
        df: pl.DataFrame,
        /,
        *,
        join_on: str | list[str] = "USUBJID",
        **frames: pl.DataFrame,
    ) -> Self: ...

    @overload
    def pin(
        self,
        /,
        *,
        join_on: str | list[str] = "USUBJID",
        **frames: pl.DataFrame,
    ) -> Self: ...

    def pin(
        self,
        domain: str | None = None,
        df: pl.DataFrame | None = None,
        /,
        *,
        join_on: str | list[str] = "USUBJID",
        **frames: pl.DataFrame,
    ) -> Self:
        """Attach one or more reference domains to this pipeline.

        Two equivalent forms, usable together — the keyword form declares
        every upstream dataset in one call (kwarg name = dataset name),
        mirroring the define.yaml ``inputs:`` block:

        * ``pin("DM", dm_df)`` — one pin, positional.
        * ``pin(DM=dm_df, ADSL=adsl_df)`` — several pins, one call.

        The name/frame pair is positional-only, so *every* keyword except
        ``join_on`` is a dataset pin — no dataset name is reserved.

        Args:
            domain: Logical name (e.g. ``"DM"``, ``"ADSL"``, ``"TV"``).
            df: The reference DataFrame for *domain*.  A LazyFrame is
                collected once, at pin time.
            join_on: Column(s) used to join these references into the
                pipeline.  Applies to every pin in this call; pin
                separately for per-domain join keys.
            **frames: ``NAME=frame`` pins (names are upper-cased).

        Returns:
            Self: A shallow copy with the pin(s) attached; call
                ``.to_frame()`` to materialise.

        Raises:
            DerivationError: When called with no pins, a name without its
                frame (or vice versa), or a pinned value that is not a
                DataFrame/LazyFrame.

        Examples:
            Pin DM to an AE pipeline for study-day derivation::

                ae = (
                    ae_raw.sdtm
                    .assign("DOMAIN", value="AE")
                    .pin("DM", dm_df)
                    .study_day("AESTDY", date_col="AESTDTC")
                    .to_frame()
                )

            Declare every upstream dataset of an ADaM pipeline at once::

                adae = (
                    ae_df.adam.occds("ADAE")
                    .pin(ADSL=adsl_df, EX=ex_df)
                    .join_adsl("TRTSDT", "SAFFL")
                    .to_frame()
                )
        """
        pins: dict[str, pl.DataFrame] = {}
        if domain is not None or df is not None:
            if domain is None or df is None:
                raise DerivationError(
                    "pin() requires both a domain name and a DataFrame — "
                    'pin("DM", dm_df) — or keyword pins: pin(DM=dm_df).'
                )
            pins[domain] = df
        pins.update(frames)
        if not pins:
            raise DerivationError(
                'pin() requires at least one pin: pin("DM", dm_df) or pin(DM=dm_df, ADSL=adsl_df).'
            )

        new = copy.copy(self)
        pinned: dict[str, tuple[pl.DataFrame, list[str]]] = dict(getattr(self, "_pinned", {}))
        for name, frame in pins.items():
            frame = _pin_frame(name, frame)
            key = name.upper()
            if key in pinned:
                warnings.warn(
                    f"Pin '{key}' replaced. Use .repin() to suppress this warning.",
                    stacklevel=2,
                )
            pinned[key] = (frame, _normalize_key(join_on))
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
            df: The new reference DataFrame.  A LazyFrame is collected
                once, at pin time.
            join_on: Column(s) for the join key.

        Returns:
            Self: A shallow copy with the pin replaced.

        Raises:
            DerivationError: When *df* is not a DataFrame or LazyFrame.

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
        pinned[domain.upper()] = (_pin_frame(domain, df), _normalize_key(join_on))
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
        """Set the FK-check severity for this pipeline.

        The check runs once, at the public ``to_frame()`` (and the
        terminal verbs that call it), on the final frame, with the
        severity in force at that point.  The order of ``pin``,
        ``fk_policy`` and the verbs does not matter.  It checks
        ``USUBJID`` against the pinned ``DM`` (SDTM) or ``ADSL`` (ADaM).

        Args:
            severity: One of ``"warn"`` (emit ``UserWarning``),
                ``"error"`` (raise ``DerivationError``), or ``"off"``
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

    def _run_fk_checks(self, df: pl.DataFrame) -> None:
        """Check the foreign keys of the final frame *df* against the pins.

        Called by the public ``to_frame()`` only, with the ``fk_policy`` in
        force on this namespace.  Each column of ``_FK_CHECKED`` that has
        an ``_FK_RULES`` entry and a pinned reference is checked once.  A
        warning is given once per namespace; an error raises on every call.
        """
        severity = getattr(self, "_fk_severity", "warn")
        if severity == "off":
            return
        rules: dict[str, dict[str, str]] = self.__class__._FK_RULES
        pinned: dict[str, tuple[pl.DataFrame, list[str]]] = getattr(self, "_pinned", {})
        warned: frozenset[str] = getattr(self, "_fk_warned", frozenset())
        for col in _FK_CHECKED:
            rule = rules.get(col)
            if rule is None or col not in df.columns:
                continue
            pin = rule.get("pin", "").upper()
            ref_col = rule.get("ref_col", col)
            if pin not in pinned or ref_col not in pinned[pin][0].columns:
                continue
            ref_df = pinned[pin][0]
            current_vals = set(df[col].drop_nulls().unique().to_list())
            ref_vals = set(ref_df[ref_col].drop_nulls().unique().to_list())
            orphans = current_vals - ref_vals
            if not orphans:
                continue
            msg = (
                f"FK check: {len(orphans)} value(s) in '{col}' not found in "
                f"pinned {pin}.{ref_col}: {sorted(orphans)[:5]}"
            )
            if severity == "error":
                raise DerivationError(msg)
            if msg not in warned:
                # Rebind, never mutate: earlier chain copies keep their own memo.
                warned = warned | {msg}
                self._fk_warned = warned
                warnings.warn(msg, stacklevel=3)
