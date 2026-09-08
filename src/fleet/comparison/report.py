"""The comparison report: what a compare found, and how it prints.

The report is a frozen dataclass in the style of
:class:`fleet.validation.ValidationResult`.  It holds the four summaries a
SAS programmer expects from PROC COMPARE (data sets, variables,
observations, values), the long value listing as a Polars frame, the set
of named flags that replaces SAS's SYSINFO integer, the settings the
comparison ran with, and the Fleet version.  Rendering lives in
:mod:`fleet.comparison.text`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, NamedTuple

import polars as pl

from fleet.core import log as fleet_log
from fleet.core.exceptions import ComparisonError, VerbUsageError

#: Comparison reports emit through this logger (INFO level, stdout by
#: default — see :mod:`fleet.core.log` to route or silence them).
_logger = fleet_log.get_logger("fleet.comparison")

#: Every flag a comparison can raise.  ``is_equal`` is true only when none is.
#: Dtype differences are information and never raise a flag.
FLAGS: tuple[str, ...] = (
    "base_only_variables",
    "candidate_only_variables",
    "type_conflicts",
    "base_only_observations",
    "candidate_only_observations",
    "values_differ",
    "duplicate_keys",
    "base_only_groups",
    "candidate_only_groups",
)

#: Columns of the value listing after the keys, in order.  A key may not
#: reuse one of these names.
LISTING_COLUMNS: tuple[str, ...] = (
    "group",
    "variable",
    "base",
    "candidate",
    "difference",
    "percent_difference",
)

#: Default print limits of the text renderer: differences per variable, and overall.
DEFAULT_MAX_PRINT = 50
DEFAULT_MAX_PRINT_TOTAL = 500

#: What ``max_print`` accepts: a per-variable limit, a ``(per_variable, total)``
#: pair, or ``None`` to print everything.
MaxPrint = int | tuple[int, int] | None


class PrintLimits(NamedTuple):
    """Resolved print limits; ``None`` means no limit."""

    per_variable: int | None
    total: int | None


def _normalise_max_print(max_print: MaxPrint) -> PrintLimits:
    """Resolve a ``max_print`` argument into explicit limits, validating its shape.

    ``None`` lifts both limits.  An integer sets the per-variable limit; the
    overall limit is then :data:`DEFAULT_MAX_PRINT_TOTAL` or the per-variable
    limit, whichever is larger.  A pair sets both explicitly.
    """
    if max_print is None:
        return PrintLimits(None, None)
    if isinstance(max_print, bool):
        raise VerbUsageError("max_print must be an int, a (per_variable, total) pair or None")
    if isinstance(max_print, int):
        if max_print < 0:
            raise ComparisonError("max_print must not be negative")
        return PrintLimits(max_print, max(max_print, DEFAULT_MAX_PRINT_TOTAL))
    if (
        isinstance(max_print, tuple)
        and len(max_print) == 2
        and all(isinstance(n, int) and not isinstance(n, bool) for n in max_print)
    ):
        per_variable, total = max_print
        if per_variable < 0 or total < 0:
            raise ComparisonError("max_print limits must not be negative")
        return PrintLimits(per_variable, total)
    raise VerbUsageError("max_print must be an int, a (per_variable, total) pair or None")


def _key_label(keys: Iterable[str], values: Iterable[Any]) -> str:
    """Render one observation's key values as ``K1=v1, K2=v2``."""
    return ", ".join(f"{k}={'null' if v is None else v}" for k, v in zip(keys, values))


@dataclass(frozen=True)
class SideSummary:
    """One side of the data set summary."""

    name: str | None
    rows: int
    variables: int


@dataclass(frozen=True)
class DatasetSummary:
    """Name, rows and variables of the base and the candidate."""

    base: SideSummary
    candidate: SideSummary


@dataclass(frozen=True)
class VariableDtypes:
    """A common variable with its dtype on each side."""

    variable: str
    base_dtype: pl.DataType
    candidate_dtype: pl.DataType


@dataclass(frozen=True)
class VariablesSummary:
    """Which variables were common, one-sided, conflicting or merely differently typed.

    Keys are never counted here; they identify observations rather than
    being compared.
    """

    common: tuple[str, ...]
    base_only: tuple[str, ...]
    candidate_only: tuple[str, ...]
    #: Same name, different kind (numeric against string, ...): listed, not compared.
    type_conflicts: tuple[VariableDtypes, ...]
    #: Same kind, different dtype: compared after casting to a common supertype.
    dtype_differences: tuple[VariableDtypes, ...]

    @property
    def compared(self) -> tuple[str, ...]:
        """The common variables whose values were actually compared."""
        conflicts = {c.variable for c in self.type_conflicts}
        return tuple(v for v in self.common if v not in conflicts)


@dataclass(frozen=True, eq=False)
class ObservationSummary:
    """How observations paired on the keys, with the key values of the unpaired ones."""

    matched: int
    base_only: int
    candidate_only: int
    #: Key values of the observations found only in the base, sorted by keys.
    base_only_keys: pl.DataFrame
    #: Key values of the observations found only in the candidate, sorted by keys.
    candidate_only_keys: pl.DataFrame


@dataclass(frozen=True, eq=False)
class ValuesSummary:
    """Differences per compared variable over the matched observations."""

    #: One row per compared variable: ``variable`` (str), ``differences`` (int).
    per_variable: pl.DataFrame
    observations_with_differences: int

    @property
    def variables_with_differences(self) -> int:
        """How many compared variables differ on at least one observation."""
        return self.per_variable.filter(pl.col("differences") > 0).height

    @property
    def total_differences(self) -> int:
        """How many values differ in all, summed over the compared variables."""
        return int(self.per_variable["differences"].sum())


@dataclass(frozen=True)
class ComparisonSettings:
    """The settings a comparison ran with, so a run can be reproduced."""

    keys: tuple[str, ...]
    max_print: MaxPrint
    base_name: str | None
    candidate_name: str | None


class _Unset:
    """Sentinel: use the ``max_print`` recorded in the report settings."""

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return "<use report settings>"


_USE_SETTINGS = _Unset()


@dataclass(frozen=True, eq=False)
class ComparisonReport:
    """Outcome of :func:`fleet.compare`.

    Attributes:
        datasets: Name, rows and variables per side.
        variables: Common, one-sided, conflicting and differently typed variables.
        observations: Matched and one-sided observation counts, with the
            key values of the one-sided observations.
        values: Differences per compared variable.
        listing: Long frame of every differing value, sorted by keys: the key
            columns, then ``group`` (reserved for BY groups, null until they
            land), ``variable``, ``base`` and ``candidate`` as strings,
            ``difference`` and ``percent_difference`` for numeric variables
            (null otherwise; percent is null when the base is zero or null).
            Never truncated; ``max_print`` only governs the text renderer.
        flags: The subset of :data:`FLAGS` this comparison raised.
        settings: The settings the comparison ran with.
        version: The Fleet version that produced the report.
    """

    datasets: DatasetSummary
    variables: VariablesSummary
    observations: ObservationSummary
    values: ValuesSummary
    listing: pl.DataFrame
    flags: frozenset[str]
    settings: ComparisonSettings
    version: str

    @property
    def is_equal(self) -> bool:
        """True only when no flag was raised."""
        return not self.flags

    @property
    def raised_flags(self) -> tuple[str, ...]:
        """The raised flags in their documented order."""
        return tuple(f for f in FLAGS if f in self.flags)

    @property
    def base_label(self) -> str:
        """The base's name as given, or ``"base"``."""
        return self.settings.base_name or "base"

    @property
    def candidate_label(self) -> str:
        """The candidate's name as given, or ``"candidate"``."""
        return self.settings.candidate_name or "candidate"

    @property
    def summary(self) -> str:
        """One line: verdict, sides, matched observations, compared variables, flags."""
        verdict = "EQUAL" if self.is_equal else "NOT EQUAL"
        line = (
            f"{verdict} - {self.base_label} vs {self.candidate_label}: "
            f"{self.observations.matched} matched observations, "
            f"{len(self.variables.compared)} variables compared"
        )
        if self.flags:
            line += f"; flags: {', '.join(self.raised_flags)}"
        return line

    def to_text(self, max_print: MaxPrint | _Unset = _USE_SETTINGS) -> str:
        """Render the report as plain text in PROC COMPARE section order.

        Sections: data set summary, variables summary, observation summary,
        values summary, value listing grouped per observation, verdict.
        The print limits cap the value listing (per variable first, then
        overall) and the one-sided observation lists; the report's own
        ``listing`` frame is never truncated.

        Args:
            max_print: Differences to print per variable, a
                ``(per_variable, total)`` pair, or ``None`` for everything.
                Defaults to the ``max_print`` the comparison ran with.

        Returns:
            str: The rendered report, one section per block.

        Examples:
            Keep the full text of a comparison next to a build::

                report = fleet.compare(adsl_prod, adsl_qc, keys=["USUBJID"])
                Path("adsl_compare.txt").write_text(report.to_text(max_print=None))
        """
        from .text import _render_text

        limit = self.settings.max_print if isinstance(max_print, _Unset) else max_print
        return _render_text(self, _normalise_max_print(limit))

    def print_report(self, max_print: MaxPrint | _Unset = _USE_SETTINGS) -> None:
        """Emit :meth:`to_text` through the ``fleet.comparison`` logger.

        By default the report reaches stdout (INFO level); use the standard
        :mod:`logging` API or :func:`fleet.core.log.disable_console` to route
        or silence it.

        Args:
            max_print: As for :meth:`to_text`.

        Examples:
            Print a QC comparison and gate a script on it::

                report = fleet.compare(adsl_prod, adsl_qc, keys=["USUBJID"])
                report.print_report()
                assert report.is_equal, report.raised_flags
        """
        fleet_log.ensure_default_handler()
        _logger.info(self.to_text(max_print))

    def __str__(self) -> str:
        """The text report with the settings' print limits, so ``print(report)`` reads."""
        return self.to_text()
