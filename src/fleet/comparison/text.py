"""Plain-text renderer for the comparison report, in PROC COMPARE section order.

Sections: data set summary, variables summary, observation summary, values
summary, value listing, verdict.  The listing is grouped per observation so
one subject's differences read together, and truncated to the print limits
(per variable within a group first, then overall).  The listing frame on
the report is never truncated; only what is printed is.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import polars as pl

from .report import PrintLimits, VariableDtypes, _key_label

if TYPE_CHECKING:
    from .report import ComparisonReport

_RULE = "-" * 70
_HEADER_RULE = "=" * 70
_MIN_VARIABLE_WIDTH = 8


def _render_text(report: ComparisonReport, limits: PrintLimits) -> str:
    """Render *report* as text, capping the listing and the one-sided key lists to *limits*."""
    lines: list[str] = [
        f"Comparison report: {report.base_label} vs {report.candidate_label}",
        _HEADER_RULE,
        "",
    ]
    lines += _datasets_section(report)
    lines += _variables_section(report)
    lines += _observations_section(report, limits.per_variable)
    lines += _values_section(report)
    lines += _listing_section(report, limits)
    lines += _verdict_section(report)
    return "\n".join(lines)


def _datasets_section(report: ComparisonReport) -> list[str]:
    d = report.datasets
    return [
        "Data set summary",
        _RULE,
        f"  Base:      {report.base_label}  "
        f"({d.base.rows} observations, {d.base.variables} variables)",
        f"  Candidate: {report.candidate_label}  "
        f"({d.candidate.rows} observations, {d.candidate.variables} variables)",
        f"  Keys:      {', '.join(report.settings.keys)}",
        "",
    ]


def _variables_section(report: ComparisonReport) -> list[str]:
    v = report.variables
    names = [t.variable for t in (*v.type_conflicts, *v.dtype_differences)]
    width = max([_MIN_VARIABLE_WIDTH, *map(len, names)])
    return [
        "Variables summary",
        _RULE,
        f"  Variables in common:           {len(v.common)}  (compared: {len(v.compared)})",
        f"  Variables in base only:        {len(v.base_only)}{_names(v.base_only)}",
        f"  Variables in candidate only:   {len(v.candidate_only)}{_names(v.candidate_only)}",
        f"  Type conflicts (not compared): {len(v.type_conflicts)}",
        *_dtype_lines(v.type_conflicts, width),
        f"  Dtype differences (compared after casting): {len(v.dtype_differences)}",
        *_dtype_lines(v.dtype_differences, width),
        "",
    ]


def _names(variables: tuple[str, ...]) -> str:
    return f"  {', '.join(variables)}" if variables else ""


def _dtype_lines(entries: tuple[VariableDtypes, ...], width: int) -> list[str]:
    return [
        f"    {t.variable:<{width}}  base {t.base_dtype} / candidate {t.candidate_dtype}"
        for t in entries
    ]


def _observations_section(report: ComparisonReport, limit: int | None) -> list[str]:
    o = report.observations
    keys = report.settings.keys
    return [
        "Observation summary",
        _RULE,
        f"  Matched observations:            {o.matched}",
        f"  Observations in base only:       {o.base_only}",
        *_key_rows(keys, o.base_only_keys, limit),
        f"  Observations in candidate only:  {o.candidate_only}",
        *_key_rows(keys, o.candidate_only_keys, limit),
        "",
    ]


def _key_rows(keys: tuple[str, ...], frame: pl.DataFrame, limit: int | None) -> list[str]:
    shown = frame if limit is None else frame.head(limit)
    lines = [f"    {_key_label(keys, row)}" for row in shown.iter_rows()]
    if shown.height < frame.height:
        lines.append(f"    ... and {frame.height - shown.height} more")
    return lines


def _values_section(report: ComparisonReport) -> list[str]:
    values = report.values
    lines = ["Values summary", _RULE]
    if not report.variables.compared:
        lines.append("  No variables compared.")
    elif values.total_differences == 0:
        lines.append("  All compared values are equal.")
    else:
        unequal = values.per_variable.filter(pl.col("differences") > 0)
        width = max([_MIN_VARIABLE_WIDTH, *map(len, unequal["variable"].to_list())])
        lines += [
            f"  Variables with unequal values:    {values.variables_with_differences}",
            f"  Observations with unequal values: {values.observations_with_differences}",
            f"  Total unequal values:             {values.total_differences}",
            "",
            f"  {'Variable':<{width}}  Unequal",
        ]
        lines += [f"  {variable:<{width}}  {n}" for variable, n in unequal.iter_rows()]
    lines.append("")
    return lines


def _listing_section(report: ComparisonReport, limits: PrintLimits) -> list[str]:
    listing = report.listing
    lines = ["Value listing", _RULE]
    if listing.height == 0:
        lines += ["  No unequal values.", ""]
        return lines

    shown = _truncate_listing(listing, limits)
    if shown.height < listing.height:
        lines.append(
            f"  (showing {shown.height} of {listing.height} unequal values; "
            f"limits: {_limit(limits.per_variable)} per variable, "
            f"{_limit(limits.total)} overall; max_print=None prints all)"
        )
    else:
        lines.append(f"  (showing all {listing.height} unequal values)")

    keys = report.settings.keys
    rows = shown.to_dicts()
    width = max([_MIN_VARIABLE_WIDTH, *(len(r["variable"]) for r in rows)])
    base_width = max([4, *(len(_cell(r["base"])) for r in rows)])
    candidate_width = max([9, *(len(_cell(r["candidate"])) for r in rows)])
    numeric = any(r["difference"] is not None for r in rows)
    header = f"    {'Variable':<{width}}  {'Base':<{base_width}}  {'Candidate':<{candidate_width}}"
    if numeric:
        header += "  Difference  % Difference"
    lines.append(header)

    current: tuple[Any, ...] | None = None
    for row in rows:
        key = tuple(row[k] for k in keys)
        if key != current:
            lines.append(f"  {_key_label(keys, key)}")
            current = key
        line = (
            f"    {row['variable']:<{width}}  {_cell(row['base']):<{base_width}}"
            f"  {_cell(row['candidate']):<{candidate_width}}"
        )
        if row["difference"] is not None:
            line += f"  {_number(row['difference']):<10}  {_number(row['percent_difference'])}"
        lines.append(line.rstrip())
    lines.append("")
    return lines


def _truncate_listing(listing: pl.DataFrame, limits: PrintLimits) -> pl.DataFrame:
    """Keep the first ``per_variable`` differences of each variable within its group, then the first ``total``."""
    shown = listing
    if limits.per_variable is not None:
        rank = pl.int_range(pl.len()).over("group", "variable")
        shown = shown.filter(rank < limits.per_variable)
    if limits.total is not None:
        shown = shown.head(limits.total)
    return shown


def _verdict_section(report: ComparisonReport) -> list[str]:
    lines = ["Verdict", _RULE]
    if report.is_equal:
        lines.append("  EQUAL: no differences found.")
    else:
        lines.append(f"  NOT EQUAL: {', '.join(report.raised_flags)}")
    return lines


def _cell(value: str | None) -> str:
    return "null" if value is None else value


def _number(value: float | None) -> str:
    return "" if value is None else f"{value:g}"


def _limit(value: int | None) -> str:
    return "none" if value is None else str(value)
