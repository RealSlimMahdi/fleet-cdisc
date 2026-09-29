"""Validation result models for CDISC conformance checking."""

from dataclasses import dataclass, field
from enum import Enum
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from fleet.core import log as fleet_log

if TYPE_CHECKING:
    from fleet.validation.run_setup import RunSetup

#: Validation reports emit through this logger (INFO level, stdout by
#: default — see :mod:`fleet.core.log` to route or silence them).
_logger = fleet_log.get_logger("fleet.validation")

#: Which engine run a finding came from: the CDISC rules, or the study's custom rules.
RuleSource = Literal["official", "custom"]


class Severity(Enum):
    """Validation issue severity levels."""

    ERROR = "Error"
    WARNING = "Warning"
    INFO = "Info"


@dataclass
class ValidationIssue:
    """A single validation issue.

    The optional ``producing_verb`` / ``verb_method`` / ``spec_ref`` fields
    are populated by :func:`fleet.validation.lineage_join.enrich_with_lineage`
    when variable-level lineage (see :class:`fleet.core.dag.VariableNode`)
    is available.  They turn a bare "variable failed rule" message into a
    direct cross-link back to the exact Python verb that produced the
    column.
    """

    severity: Severity
    rule_id: str
    message: str
    variable: str | None = None
    rows_affected: int | None = None
    suggested_fix: str | None = None
    producing_verb: str | None = None
    verb_method: str | None = None
    spec_ref: str | None = None
    source: RuleSource = "official"

    def __str__(self) -> str:
        parts = [f"[{self.severity.value}] {self.rule_id} ({self.source}): {self.message}"]
        if self.variable:
            parts.append(f"Variable: {self.variable}")
        if self.rows_affected:
            parts.append(f"Rows: {self.rows_affected}")
        if self.producing_verb:
            parts.append(f"Producing verb: {self.producing_verb} ({self.verb_method})")
        if self.spec_ref:
            parts.append(f"Spec reference: {self.spec_ref}")
        if self.suggested_fix:
            parts.append(f"Suggested fix: {self.suggested_fix}")
        return "\n   ".join(parts)


@dataclass
class ValidationResult:
    """Collected results of a CDISC validation run."""

    dataset_name: str
    dataset_type: str
    model_version: str
    total_issues: int = 0
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)
    infos: list[ValidationIssue] = field(default_factory=list)
    #: The inputs this result was validated with, when the surface used a run setup.
    setup: "RunSetup | None" = None

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    @property
    def summary(self) -> str:
        status = "PASS" if self.is_valid else "FAIL"
        return (
            f"{status} - {self.dataset_name} ({self.dataset_type} {self.model_version})\n"
            f"  Errors: {len(self.errors)}, Warnings: {len(self.warnings)}, Info: {len(self.infos)}"
        )

    def print_report(self, report_type: str = "smart") -> None:
        """Emit a formatted validation report through the ``fleet.validation`` logger.

        By default the report reaches stdout (INFO level); use the
        standard :mod:`logging` API or :func:`fleet.core.log.disable_console`
        to route or silence it.

        Args:
            report_type: ``"smart"`` (default) for a deduplicated view that
                groups identical findings and shows compact row ranges,
                ``"summary"`` for a compact one-line-per-issue view,
                ``"full"`` for expanded details including variable names,
                affected rows, producing verbs, and suggested fixes.
        """
        fleet_log.ensure_default_handler()
        _logger.info("\n" + "=" * 70)
        _logger.info(f"CDISC Validation Report: {self.dataset_name}")
        _logger.info("=" * 70)
        for line in self.setup.header_lines() if self.setup is not None else ():
            _logger.info(line)
        _logger.info(f"Dataset Type: {self.dataset_type} {self.model_version}")
        _logger.info(f"Status: {'PASS' if self.is_valid else 'FAIL'}")
        _logger.info(f"Total Issues: {self.total_issues}")
        _logger.info(
            f"  Errors: {len(self.errors)}, Warnings: {len(self.warnings)}, Info: {len(self.infos)}"
        )
        _logger.info("-" * 70)

        if report_type == "full":
            self._print_full()
        elif report_type == "smart":
            self._print_smart()
        else:
            self._print_summary()

        _logger.info("\n" + "=" * 70)

    def _print_summary(self) -> None:
        """Compact view: one line per issue."""
        if self.errors:
            _logger.info(f"\nERRORS ({len(self.errors)}):")
            for issue in self.errors:
                label = f"  [{issue.rule_id}] ({issue.source})"
                if issue.variable:
                    label += f" {issue.variable}:"
                _logger.info(f"{label} {issue.message}")
        if self.warnings:
            _logger.info(f"\nWARNINGS ({len(self.warnings)}):")
            for issue in self.warnings:
                label = f"  [{issue.rule_id}] ({issue.source})"
                if issue.variable:
                    label += f" {issue.variable}:"
                _logger.info(f"{label} {issue.message}")
        if not self.errors and not self.warnings:
            _logger.info("\n  No errors or warnings.")

    def _print_full(self) -> None:
        """Expanded view: all fields per issue, including info."""
        if self.errors:
            _logger.info(f"\nERRORS ({len(self.errors)}):")
            for i, issue in enumerate(self.errors, 1):
                _logger.info(f"\n{i}. {issue}")

        if self.warnings:
            _logger.info(f"\nWARNINGS ({len(self.warnings)}):")
            for i, issue in enumerate(self.warnings, 1):
                _logger.info(f"\n{i}. {issue}")

        if self.infos:
            _logger.info(f"\nINFO ({len(self.infos)}):")
            for i, issue in enumerate(self.infos, 1):
                _logger.info(f"\n{i}. {issue}")

        if not self.errors and not self.warnings and not self.infos:
            _logger.info("\n  No issues found.")

    def _print_smart(self) -> None:
        """Deduplicated view: groups identical findings and shows row ranges."""

        def _group_issues(issues: list[ValidationIssue]) -> list[dict]:
            """Group issues by (rule_id, message, variable) and consolidate rows."""
            groups: dict[tuple, dict] = {}
            for issue in issues:
                key = (issue.rule_id, issue.message, issue.variable or "", issue.source)
                if key not in groups:
                    groups[key] = {
                        "issue": issue,
                        "rows": [],
                        "count": 0,
                    }
                groups[key]["count"] += 1
                if issue.rows_affected is not None:
                    groups[key]["rows"].append(issue.rows_affected)
            return list(groups.values())

        def _format_rows(rows: list[int]) -> str:
            """Format row numbers into compact ranges (e.g. '1-5, 8, 10-12')."""
            if not rows:
                return ""
            sorted_rows = sorted(set(rows))
            ranges: list[str] = []
            start = prev = sorted_rows[0]
            for r in sorted_rows[1:]:
                if r == prev + 1:
                    prev = r
                else:
                    ranges.append(f"{start}" if start == prev else f"{start}-{prev}")
                    start = prev = r
            ranges.append(f"{start}" if start == prev else f"{start}-{prev}")
            return ", ".join(ranges)

        def _print_grouped(label: str, issues: list[ValidationIssue]) -> None:
            if not issues:
                return
            grouped = _group_issues(issues)
            unique_count = len(grouped)
            total_count = len(issues)
            _logger.info(f"\n{label} ({unique_count} unique, {total_count} total):")
            for i, grp in enumerate(grouped, 1):
                issue = grp["issue"]
                count = grp["count"]
                rows = grp["rows"]
                _logger.info(f"\n{i}. [{issue.rule_id}] ({issue.source}) {issue.message}")
                if issue.variable:
                    _logger.info(f"   Variable: {issue.variable}")
                if rows:
                    _logger.info(f"   Rows affected: {_format_rows(rows)} ({count} occurrences)")
                elif count > 1:
                    _logger.info(f"   Occurrences: {count}")
                if issue.producing_verb:
                    _logger.info(f"   Producing verb: {issue.producing_verb} ({issue.verb_method})")
                if issue.suggested_fix:
                    _logger.info(f"   Suggested fix: {issue.suggested_fix}")

        _print_grouped("ERRORS", self.errors)
        _print_grouped("WARNINGS", self.warnings)
        _print_grouped("INFO", self.infos)

        if not self.errors and not self.warnings and not self.infos:
            _logger.info("\n  No issues found.")

    def save_html_report(self, output_path: str | Path) -> str:
        """Save validation report as HTML file."""
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        html = self._build_html()
        output_file.write_text(html, encoding="utf-8")
        return str(output_file.absolute())

    def _build_html(self) -> str:
        status_color = "#28a745" if self.is_valid else "#dc3545"
        status_text = "PASS" if self.is_valid else "FAIL"

        def issue_cards(issues: list[ValidationIssue], css_class: str = "") -> str:
            cards = []
            for i, issue in enumerate(issues, 1):
                extra = ""
                if issue.variable:
                    extra += f"<div class='issue-detail'><strong>Variable:</strong> {issue.variable}</div>\n"
                if issue.rows_affected:
                    extra += f"<div class='issue-detail'><strong>Rows Affected:</strong> {issue.rows_affected}</div>\n"
                if issue.producing_verb:
                    verb_html = (
                        f"<a href='#{issue.verb_method}' class='verb-link'>"
                        f"{issue.producing_verb}</a>"
                        if issue.verb_method
                        else issue.producing_verb
                    )
                    extra += (
                        f"<div class='issue-detail'><strong>Producing verb:</strong> "
                        f"{verb_html}"
                        f"{(' &middot; ' + issue.verb_method) if issue.verb_method else ''}"
                        f"</div>\n"
                    )
                if issue.spec_ref:
                    extra += f"<div class='issue-detail'><strong>Spec reference:</strong> {issue.spec_ref}</div>\n"
                if issue.suggested_fix:
                    extra += f"<div class='suggested-fix'><strong>Suggested Fix:</strong> {issue.suggested_fix}</div>\n"
                cards.append(
                    f"<div class='issue-card {css_class}'>"
                    f"<div class='issue-header'>{i}. {issue.message}</div>"
                    f"<div class='issue-detail'><strong>Rule ID:</strong> <span class='rule-id'>{issue.rule_id}</span></div>"
                    f"<div class='issue-detail'><strong>Source:</strong> {issue.source}</div>"
                    f"{extra}</div>"
                )
            return "\n".join(cards)

        errors_html = (
            f"<div class='section'><div class='section-title'>Errors ({len(self.errors)})</div>"
            f"{issue_cards(self.errors)}</div>"
            if self.errors
            else ""
        )
        warnings_html = (
            f"<div class='section'><div class='section-title'>Warnings ({len(self.warnings)})</div>"
            f"{issue_cards(self.warnings, 'warning')}</div>"
            if self.warnings
            else ""
        )
        setup_html = "".join(
            f"{escape(line)}<br>\n" for line in (self.setup.header_lines() if self.setup else ())
        )

        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>CDISC Validation Report - {self.dataset_name}</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
.container {{ background: white; padding: 30px; border-radius: 5px; max-width: 1200px; margin: 0 auto; }}
h1 {{ color: #2c3e50; border-bottom: 3px solid {status_color}; padding-bottom: 10px; }}
.status {{ display: inline-block; padding: 5px 15px; background: {status_color}; color: white; border-radius: 3px; font-weight: bold; }}
.summary {{ background: #f8f9fa; padding: 15px; border-left: 4px solid {status_color}; margin: 20px 0; }}
.section-title {{ font-size: 18px; font-weight: bold; margin-bottom: 15px; border-bottom: 2px solid #e0e0e0; padding-bottom: 5px; }}
.issue-card {{ border: 1px solid #ddd; border-left: 4px solid #dc3545; padding: 15px; margin-bottom: 15px; border-radius: 3px; }}
.issue-card.warning {{ border-left-color: #ffc107; }}
.issue-header {{ font-weight: bold; margin-bottom: 8px; }}
.issue-detail {{ margin: 5px 0; font-size: 14px; color: #555; }}
.rule-id {{ background: #e9ecef; padding: 2px 8px; border-radius: 3px; font-family: monospace; }}
.suggested-fix {{ background: #e7f3ff; border-left: 3px solid #0066cc; padding: 10px; margin-top: 10px; font-style: italic; }}
</style>
</head>
<body>
<div class="container">
<h1>CDISC Validation Report</h1>
<div class="summary">
{setup_html}<strong>Dataset:</strong> {self.dataset_name}<br>
<strong>Type:</strong> {self.dataset_type} {self.model_version}<br>
<strong>Status:</strong> <span class="status">{status_text}</span><br>
<strong>Errors:</strong> {len(self.errors)} | <strong>Warnings:</strong> {len(self.warnings)} | <strong>Info:</strong> {len(self.infos)}
</div>
{errors_html}
{warnings_html}
</div>
</body>
</html>"""
