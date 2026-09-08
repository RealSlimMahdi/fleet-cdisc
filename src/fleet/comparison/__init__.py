"""Comparison: pair two datasets on keys and report where they differ.

Fleet's PROC COMPARE analogue, in pure Polars.  The package is named after
the noun so that it does not shadow :func:`fleet.compare`, the function it
provides::

    import fleet

    report = fleet.compare(base, candidate, keys=["USUBJID", "AESEQ"])
    report.print_report()
    assert report.is_equal, report.flags

Vocabulary (``CONTEXT.md``): the **base** is the reference, the
**candidate** is measured against it, the **keys** identify one
observation on each side, and the outcome is a **comparison report**.
Decision record: ``docs/adr/0002-own-comparison-engine-in-pure-polars.md``.
"""

from fleet.core.exceptions import ComparisonError

from .engine import compare
from .report import (
    DEFAULT_MAX_PRINT,
    DEFAULT_MAX_PRINT_TOTAL,
    FLAGS,
    LISTING_COLUMNS,
    ComparisonReport,
    ComparisonSettings,
    DatasetSummary,
    ObservationSummary,
    SideSummary,
    ValuesSummary,
    VariableDtypes,
    VariablesSummary,
)

__all__ = [
    "compare",
    "ComparisonError",
    "ComparisonReport",
    "ComparisonSettings",
    "DatasetSummary",
    "SideSummary",
    "VariablesSummary",
    "VariableDtypes",
    "ObservationSummary",
    "ValuesSummary",
    "FLAGS",
    "LISTING_COLUMNS",
    "DEFAULT_MAX_PRINT",
    "DEFAULT_MAX_PRINT_TOTAL",
]
