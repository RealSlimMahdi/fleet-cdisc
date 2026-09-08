"""JSON renderer for the comparison report: one document for agents and editors.

Field names mirror the report attributes.  The contract is additive-only
within a major version, in the spirit of ADR 0001: keys may be added, never
removed or renamed, because the editor extension builds its comparison
view on them.  The value listing inside the document is truncated to the
print limits and says so; :meth:`ComparisonReport.save_listing` writes the
complete listing as parquet.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from .report import JSON_KEYS, PrintLimits, VariableDtypes, _cap, _truncate_listing

if TYPE_CHECKING:
    from .report import ComparisonReport


def _render_json(report: ComparisonReport, limits: PrintLimits, indent: int | None) -> str:
    """Serialise :func:`_render_dict`; strict JSON, so no ``NaN`` or ``Infinity`` literals."""
    return json.dumps(
        _render_dict(report, limits), indent=indent, ensure_ascii=False, allow_nan=False
    )


def _render_dict(report: ComparisonReport, limits: PrintLimits) -> dict[str, Any]:
    """The JSON document as plain Python objects, keyed and ordered by :data:`JSON_KEYS`."""
    sections = {
        "is_equal": report.is_equal,
        "summary": report.summary,
        "flags": list(report.raised_flags),
        "warnings": list(report.warnings),
        "datasets": asdict(report.datasets),
        "variables": _variables(report),
        "observations": _observations(report, limits.per_variable),
        "values": _values(report),
        "statistics": report.statistics.to_dicts(),
        "listing": _listing(report, limits),
        "settings": asdict(report.settings),
        "version": report.version,
    }
    return {key: _json_safe(sections[key]) for key in JSON_KEYS}


def _variables(report: ComparisonReport) -> dict[str, Any]:
    v = report.variables
    return {
        "common": list(v.common),
        "compared": list(v.compared),
        "base_only": list(v.base_only),
        "candidate_only": list(v.candidate_only),
        "type_conflicts": [_dtypes(t) for t in v.type_conflicts],
        "dtype_differences": [_dtypes(t) for t in v.dtype_differences],
    }


def _dtypes(entry: VariableDtypes) -> dict[str, str]:
    return {
        "variable": entry.variable,
        "base_dtype": str(entry.base_dtype),
        "candidate_dtype": str(entry.candidate_dtype),
    }


def _observations(report: ComparisonReport, limit: int | None) -> dict[str, Any]:
    """Counts and one-sided key values, the key lists capped like the text report."""
    o = report.observations
    base_keys = _cap(o.base_only_keys, limit)
    candidate_keys = _cap(o.candidate_only_keys, limit)
    return {
        "matched": o.matched,
        "base_only": o.base_only,
        "candidate_only": o.candidate_only,
        "base_only_keys": base_keys.to_dicts(),
        "candidate_only_keys": candidate_keys.to_dicts(),
        "base_duplicates": o.base_duplicates,
        "candidate_duplicates": o.candidate_duplicates,
        "per_group": o.per_group.to_dicts(),
        "base_only_groups": list(o.base_only_groups),
        "candidate_only_groups": list(o.candidate_only_groups),
        "truncated": (
            base_keys.height < o.base_only_keys.height
            or candidate_keys.height < o.candidate_only_keys.height
        ),
    }


def _values(report: ComparisonReport) -> dict[str, Any]:
    values = report.values
    return {
        "per_variable": values.per_variable.to_dicts(),
        "variables_with_differences": values.variables_with_differences,
        "observations_with_differences": values.observations_with_differences,
        "total_differences": values.total_differences,
        "per_group": values.per_group.to_dicts(),
    }


def _listing(report: ComparisonReport, limits: PrintLimits) -> dict[str, Any]:
    """The listing rows within the print limits, with how many exist in all."""
    listing = report.listing
    shown = _truncate_listing(listing, limits)
    return {
        "columns": listing.columns,
        "rows": shown.to_dicts(),
        "shown": shown.height,
        "total": listing.height,
        "truncated": shown.height < listing.height,
    }


def _json_safe(value: Any) -> Any:
    """Reduce Polars row values to what strict JSON can carry.

    Non-finite floats become null (JSON has no NaN or Infinity), temporal
    values render in ISO 8601, decimals and durations as text.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return str(value)  # Decimal, timedelta and anything else Polars may hand back
