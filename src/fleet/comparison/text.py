"""Plain-text renderer for the comparison report, in PROC COMPARE section order.

Sections: data set summary, variables summary, observation summary, values
summary, summary statistics, value listing, verdict.  The listing is grouped
per observation so one subject's differences read together, and truncated to
the print limits (per variable within a group first, then overall).  The
listing frame on the report is never truncated; only what is printed is.  A
comparison with BY variables reports the observation and values summaries per
group as well and sections the listing per group.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any

import polars as pl

from .report import (
    _MEASURE_LABELS,
    _SIDE_LABELS,
    PrintLimits,
    VariableDtypes,
    _cap,
    _has_measures,
    _key_label,
    _plural,
    _truncate_listing,
)

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
        *(f"WARNING: {warning}" for warning in report.warnings),
        *([""] if report.warnings else []),
    ]
    lines += _datasets_section(report)
    lines += _variables_section(report)
    lines += _observations_section(report, limits.per_variable)
    lines += _values_section(report)
    lines += _statistics_section(report)
    lines += _listing_section(report, limits)
    lines += _verdict_section(report)
    return "\n".join(lines)


def _table(
    headings: Sequence[str], rows: Iterable[Sequence[object]], indent: str = "  "
) -> list[str]:
    """A small table as fixed-width columns: the label left, everything after it right."""
    cells = [[str(value) for value in row] for row in rows]
    widths = [max([len(h), *(len(r[i]) for r in cells)]) for i, h in enumerate(headings)]

    def line(row: Sequence[str]) -> str:
        rest = "  ".join(f"{c:>{w}}" for c, w in zip(row[1:], widths[1:]))
        return f"{indent}{row[0]:<{widths[0]}}  {rest}".rstrip()

    return [line(headings), *(line(row) for row in cells)]


def _datasets_section(report: ComparisonReport) -> list[str]:
    d, s = report.datasets, report.settings
    return [
        "Data set summary",
        _RULE,
        f"  Base:      {report.base_label}  "
        f"({d.base.rows} observations, {d.base.variables} variables)",
        f"  Candidate: {report.candidate_label}  "
        f"({d.candidate.rows} observations, {d.candidate.variables} variables)",
        f"  Keys:      {', '.join(s.keys)}",
        *([f"  Pairs:     {s.pair_labels}  (base = candidate)"] if s.pairs else []),
        *([f"  Variables: {', '.join(s.variables)}  (restricted)"] if s.variables else []),
        f"  Settings:  {s.equality}",
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
    lines = [
        "Observation summary",
        _RULE,
        _line("Matched observations", o.matched),
        _line("Observations in base only", o.base_only),
        *_key_rows(keys, o.base_only_keys, limit),
        _line("Observations in candidate only", o.candidate_only),
        *_key_rows(keys, o.candidate_only_keys, limit),
    ]
    if report.settings.allow_duplicates:
        lines += [
            _line("Duplicate observations in base", o.base_duplicates),
            _line("Duplicate observations in candidate", o.candidate_duplicates),
        ]
    lines += _groups_block(report)
    lines.append("")
    return lines


def _line(label: str, value: object) -> str:
    """One summary line, its value in the section's value column."""
    return f"  {label + ':':<32} {value}"


def _groups_block(report: ComparisonReport) -> list[str]:
    """The one-sided groups and the per-group observation counts; nothing without BY variables."""
    o = report.observations
    if not report.settings.by:
        return []
    lines = [
        _line(label, "; ".join(groups))
        for label, groups in (
            ("Groups in base only", o.base_only_groups),
            ("Groups in candidate only", o.candidate_only_groups),
        )
        if groups
    ]
    return [
        *lines,
        "",
        *_table(["Group", "Matched", "Base only", "Candidate only"], o.per_group.iter_rows()),
    ]


def _key_rows(keys: tuple[str, ...], frame: pl.DataFrame, limit: int | None) -> list[str]:
    shown = _cap(frame, limit)
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
        if report.settings.by:
            lines += [
                "",
                *_table(
                    ["Group", "Variables", "Observations", "Unequal"],
                    values.per_group.iter_rows(),
                ),
            ]
    lines.append("")
    return lines


def _statistics_section(report: ComparisonReport) -> list[str]:
    """One block per differing variable: its count, and its measures when it is numeric."""
    statistics = report.statistics
    lines = ["Summary statistics", _RULE]
    if statistics.height == 0:
        return [*lines, "  No unequal values.", ""]
    lines.append("  Over the matched observations where both sides are non-null.")
    for row in statistics.iter_rows(named=True):
        count = _plural(row["differences"], "unequal value")
        if not _has_measures(row):
            lines += ["", f"  {row['variable']}  ({count}; not numeric, no statistics)"]
            continue
        lines += [
            "",
            f"  {row['variable']}  ({count})",
            *_table(
                ["Statistic", *_MEASURE_LABELS.values()],
                (
                    [label, *(_number(row[f"{side}_{m}"]) for m in _MEASURE_LABELS)]
                    for side, label in _SIDE_LABELS.items()
                ),
                indent="    ",
            ),
        ]
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
    by = report.settings.by
    # Inside a group section the BY values are already on its heading, so an
    # observation is named by what is left of the keys.
    detail_keys = keys[len(by) :] or keys
    rows = shown.to_dicts()
    width = max([_MIN_VARIABLE_WIDTH, *(len(r["variable"]) for r in rows)])
    base_width = max([4, *(len(_cell(r["base"])) for r in rows)])
    candidate_width = max([9, *(len(_cell(r["candidate"])) for r in rows)])
    numeric = any(r["difference"] is not None for r in rows)
    header = f"    {'Variable':<{width}}  {'Base':<{base_width}}  {'Candidate':<{candidate_width}}"
    if numeric:
        header += "  Difference  % Difference"
    lines.append(header)

    group: str | None = None
    current: tuple[Any, ...] | None = None
    for row in rows:
        if by and row["group"] != group:
            lines += ([""] if group is not None else []) + [f"  Group {row['group']}"]
            group, current = row["group"], None
        key = tuple(row[k] for k in detail_keys)
        if key != current:
            lines.append(f"  {_key_label(detail_keys, key)}")
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
