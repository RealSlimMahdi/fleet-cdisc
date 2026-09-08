"""Self-contained HTML renderer for the comparison report.

One page a reviewer without Python opens and sees where two datasets differ.
Structural findings (one-sided variables and observations, type conflicts,
and any other raised flag) are chips at the top.  Below, only the mismatched
observations are listed, base and candidate side by side with both cells
highlighted, one collapsible block per differing variable.  Sections appear
per group as soon as the listing's ``group`` column is populated.  The page
carries every difference (it is never truncated) and embeds its own style;
it fetches no script, stylesheet, font or image.
"""

from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING, Any

import polars as pl

from .report import VariableDtypes, _key_label

if TYPE_CHECKING:
    from .report import ComparisonReport

#: Variable blocks start open when a section has at most this many; beyond
#: it they start closed, so a report over fifty variables stays navigable.
_OPEN_BLOCKS_UP_TO = 5

#: What each raised flag is called on its chip.
_FLAG_LABELS: dict[str, str] = {
    "base_only_variables": "Variables in base only",
    "candidate_only_variables": "Variables in candidate only",
    "type_conflicts": "Type conflicts",
    "base_only_observations": "Observations in base only",
    "candidate_only_observations": "Observations in candidate only",
    "values_differ": "Values differ",
    "duplicate_keys": "Duplicate keys",
    "base_only_groups": "Groups in base only",
    "candidate_only_groups": "Groups in candidate only",
}

#: A one-sided observation chip names up to this many observations by their
#: key values; the complete list follows further down the page.
_CHIP_OBSERVATIONS = 5

_STYLE = """\
:root { color-scheme: light; }
body { margin: 0; padding: 24px 32px; background: #f6f7f9; color: #1f2328;
  font: 14px/1.45 -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; }
main { max-width: 1200px; margin: 0 auto; }
h1 { font-size: 22px; margin: 0 0 8px; }
h2 { font-size: 17px; margin: 28px 0 10px; padding-bottom: 4px; border-bottom: 1px solid #d0d7de; }
h3 { font-size: 15px; margin: 20px 0 8px; }
h3 .count { margin-left: 8px; color: #57606a; font-weight: 400; }
.verdict { display: inline-block; padding: 4px 12px; border-radius: 4px; color: #fff; font-weight: 700; }
.verdict.equal { background: #1a7f37; }
.verdict.unequal { background: #cf222e; }
.summary-line { margin: 10px 0 16px; color: #57606a; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
.chip { padding: 4px 12px; border: 1px solid #d0d7de; border-radius: 16px; background: #fff; }
.chip.flag { border-color: #cf222e; background: #ffebe9; }
.chip.info { border-color: #0969da; background: #ddf4ff; }
.chip strong { margin-right: 6px; }
.scroll { max-height: 320px; overflow: auto; }
table { border-collapse: collapse; background: #fff; }
th, td { border: 1px solid #d0d7de; padding: 4px 10px; text-align: left; vertical-align: top;
  font-variant-numeric: tabular-nums; }
th { background: #f0f2f5; font-weight: 600; }
td.number { text-align: right; }
td.null { color: #8c959f; font-style: italic; }
td.base.changed { background: #ffebe9; }
td.candidate.changed { background: #dafbe1; }
details { margin: 10px 0; background: #fff; border: 1px solid #d0d7de; border-radius: 6px; }
summary { padding: 8px 12px; cursor: pointer; font-weight: 600; }
summary .count { margin-left: 8px; color: #57606a; font-weight: 400; }
details > div { padding: 0 12px 12px; overflow-x: auto; }
footer { margin-top: 32px; color: #8c959f; font-size: 12px; }
"""


def _render_html(report: ComparisonReport) -> str:
    """Render *report* as one self-contained page; nothing in it is truncated."""
    title = f"Comparison report: {report.base_label} vs {report.candidate_label}"
    body = [
        f"<h1>{escape(title)}</h1>",
        *_verdict(report),
        *_chips(report),
        *_summary_section(report),
        *_one_sided_observations(report),
        *_listing_sections(report),
        f"<footer>Produced by Fleet {escape(report.version)}</footer>",
    ]
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{escape(title)}</title>\n<style>\n{_STYLE}</style>\n</head>\n<body>\n<main>\n"
        + "\n".join(body)
        + "\n</main>\n</body>\n</html>\n"
    )


def _verdict(report: ComparisonReport) -> list[str]:
    css_class, text = ("equal", "EQUAL") if report.is_equal else ("unequal", "NOT EQUAL")
    return [
        f'<p><span class="verdict {css_class}">{text}</span></p>',
        f'<p class="summary-line">{escape(report.summary)}</p>',
    ]


def _chips(report: ComparisonReport) -> list[str]:
    """One chip per raised flag, then an information chip for dtype differences."""
    chips = [
        _chip("flag", flag, _FLAG_LABELS[flag], _flag_detail(report, flag))
        for flag in report.raised_flags
    ]
    if report.variables.dtype_differences:
        chips.append(
            _chip(
                "info",
                "dtype_differences",
                "Dtype differences (information, compared after casting)",
                _dtype_detail(report.variables.dtype_differences),
            )
        )
    return [f'<div class="chips">{"".join(chips)}</div>'] if chips else []


def _chip(css_class: str, name: str, label: str, detail: str) -> str:
    text = f"<strong>{escape(label)}</strong>{escape(detail)}"
    return f'<span class="chip {css_class}" title="{escape(name)}">{text}</span>'


def _flag_detail(report: ComparisonReport, flag: str) -> str:
    """What a chip says after its label; flags without detail today say nothing."""
    v, o, values = report.variables, report.observations, report.values
    keys = report.settings.keys
    details = {
        "base_only_variables": lambda: ", ".join(v.base_only),
        "candidate_only_variables": lambda: ", ".join(v.candidate_only),
        "type_conflicts": lambda: _dtype_detail(v.type_conflicts),
        "base_only_observations": lambda: _observation_detail(keys, o.base_only_keys),
        "candidate_only_observations": lambda: _observation_detail(keys, o.candidate_only_keys),
        "values_differ": lambda: (
            f"{_plural(values.total_differences, 'value')} in "
            f"{_plural(values.observations_with_differences, 'observation')}, "
            f"{_plural(values.variables_with_differences, 'variable')}"
        ),
    }
    return details.get(flag, lambda: "")()


def _observation_detail(keys: tuple[str, ...], frame: pl.DataFrame) -> str:
    """``N observations: K=v; K=v ...``, naming the first few by their key values."""
    shown = frame.head(_CHIP_OBSERVATIONS)
    labels = "; ".join(_key_label(keys, row) for row in shown.iter_rows())
    text = f"{_plural(frame.height, 'observation')}: {labels}"
    if shown.height < frame.height:
        text += f" ... and {frame.height - shown.height} more"
    return text


def _dtype_detail(entries: tuple[VariableDtypes, ...]) -> str:
    return "; ".join(
        f"{t.variable} (base {t.base_dtype} / candidate {t.candidate_dtype})" for t in entries
    )


def _summary_section(report: ComparisonReport) -> list[str]:
    d, v, o = report.datasets, report.variables, report.observations
    return [
        "<h2>Summary</h2>",
        "<table>",
        "<tr><th>Side</th><th>Name</th><th>Observations</th><th>Variables</th></tr>",
        f"<tr><td>Base</td>{_td(d.base.name)}{_td(d.base.rows, 'number')}"
        f"{_td(d.base.variables, 'number')}</tr>",
        f"<tr><td>Candidate</td>{_td(d.candidate.name)}{_td(d.candidate.rows, 'number')}"
        f"{_td(d.candidate.variables, 'number')}</tr>",
        "</table>",
        f"<p>Keys: {escape(', '.join(report.settings.keys))}. "
        f"Variables in common: {len(v.common)} (compared: {len(v.compared)}). "
        f"Matched observations: {o.matched}.</p>",
    ]


def _one_sided_observations(report: ComparisonReport) -> list[str]:
    """The key values of the observations found on one side only; complete, scrollable."""
    o = report.observations
    lines: list[str] = []
    for label, frame in (
        ("Observations in base only", o.base_only_keys),
        ("Observations in candidate only", o.candidate_only_keys),
    ):
        if frame.height == 0:
            continue
        lines += [f"<h3>{label} ({frame.height})</h3>", '<div class="scroll">', *_key_table(frame)]
        lines.append("</div>")
    return ["<h2>Observations on one side only</h2>", *lines] if lines else []


def _key_table(frame: pl.DataFrame) -> list[str]:
    lines = ["<table>", "<tr>" + "".join(f"<th>{escape(k)}</th>" for k in frame.columns) + "</tr>"]
    lines += ["<tr>" + "".join(_td(value) for value in row) + "</tr>" for row in frame.iter_rows()]
    lines.append("</table>")
    return lines


def _listing_sections(report: ComparisonReport) -> list[str]:
    """The mismatched observations: a section per group, one block per differing variable."""
    listing = report.listing
    lines = ["<h2>Unequal values</h2>"]
    if listing.height == 0:
        lines.append("<p>No unequal values.</p>")
        return lines
    groups = listing["group"].unique(maintain_order=True).to_list()
    if groups == [None]:
        lines.append(f"<p>{_counts(report, listing)}</p>")
        return lines + _variable_blocks(report, listing)
    for group in groups:
        rows = listing.filter(
            pl.col("group").is_null() if group is None else pl.col("group") == group
        )
        name = "(no group)" if group is None else str(group)
        lines.append(
            f'<h3>Group {escape(name)}<span class="count">{_counts(report, rows)}</span></h3>'
        )
        lines += _variable_blocks(report, rows)
    return lines


def _counts(report: ComparisonReport, rows: pl.DataFrame) -> str:
    """``N unequal values in M observations, K variables`` over *rows*."""
    observations = rows.select(report.settings.keys).n_unique()
    return (
        f"{_plural(rows.height, 'unequal value')} in {_plural(observations, 'observation')}, "
        f"{_plural(rows['variable'].n_unique(), 'variable')}"
    )


def _variable_blocks(report: ComparisonReport, rows: pl.DataFrame) -> list[str]:
    """One ``<details>`` block per variable present in *rows*, in compared order.

    A variable the listing carries but the values summary does not know is
    still rendered, after the known ones: the page is built from the listing.
    """
    present = rows["variable"].unique(maintain_order=True).to_list()
    compared = [v for v in report.values.per_variable["variable"].to_list() if v in present]
    variables = compared + [v for v in present if v not in compared]
    open_attribute = " open" if len(variables) <= _OPEN_BLOCKS_UP_TO else ""
    lines: list[str] = []
    for variable in variables:
        block = rows.filter(pl.col("variable") == variable)
        lines += [
            f"<details{open_attribute}>",
            f"<summary>{escape(variable)}"
            f'<span class="count">{_plural(block.height, "unequal value")}</span></summary>',
            "<div>",
            *_block_table(report, block),
            "</div>",
            "</details>",
        ]
    return lines


def _block_table(report: ComparisonReport, block: pl.DataFrame) -> list[str]:
    keys = list(report.settings.keys)
    numeric = block["difference"].is_not_null().any()
    header = [*keys, report.base_label, report.candidate_label]
    if numeric:
        header += ["Difference", "% difference"]
    lines = ["<table>", "<tr>" + "".join(f"<th>{escape(h)}</th>" for h in header) + "</tr>"]
    for row in block.to_dicts():
        cells = [_td(row[k]) for k in keys]
        cells.append(_td(row["base"], "base changed"))
        cells.append(_td(row["candidate"], "candidate changed"))
        if numeric:
            cells.append(_td(_number(row["difference"]), "number"))
            cells.append(_td(_number(row["percent_difference"]), "number"))
        lines.append("<tr>" + "".join(cells) + "</tr>")
    lines.append("</table>")
    return lines


def _td(value: Any, css_class: str = "") -> str:
    """One cell; ``None`` renders as ``null`` and is styled as such."""
    if value is None:
        classes = f"{css_class} null".strip()
        return f'<td class="{classes}">null</td>'
    attribute = f' class="{css_class}"' if css_class else ""
    return f"<td{attribute}>{escape(str(value))}</td>"


def _number(value: float | None) -> str | None:
    return None if value is None else f"{value:g}"


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")
