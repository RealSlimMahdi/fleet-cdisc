"""Validation result models for CDISC conformance checking."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Severity(Enum):
    """Validation issue severity levels."""

    ERROR = "Error"
    WARNING = "Warning"
    INFO = "Info"


@dataclass
class ValidationIssue:
    """A single validation issue."""

    severity: Severity
    rule_id: str
    message: str
    variable: str | None = None
    rows_affected: int | None = None
    suggested_fix: str | None = None

    def __str__(self) -> str:
        parts = [f"[{self.severity.value}] {self.rule_id}: {self.message}"]
        if self.variable:
            parts.append(f"Variable: {self.variable}")
        if self.rows_affected:
            parts.append(f"Rows: {self.rows_affected}")
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

    def print_report(self, show_warnings: bool = True, show_info: bool = False) -> None:
        print("\n" + "=" * 70)
        print(f"CDISC Validation Report: {self.dataset_name}")
        print("=" * 70)
        print(f"Dataset Type: {self.dataset_type} {self.model_version}")
        print(f"Status: {'PASS' if self.is_valid else 'FAIL'}")
        print(f"Total Issues: {self.total_issues}")
        print("-" * 70)

        if self.errors:
            print(f"\nERRORS ({len(self.errors)}):")
            for i, issue in enumerate(self.errors, 1):
                print(f"\n{i}. {issue}")

        if show_warnings and self.warnings:
            print(f"\nWARNINGS ({len(self.warnings)}):")
            for i, issue in enumerate(self.warnings, 1):
                print(f"\n{i}. {issue}")

        if show_info and self.infos:
            print(f"\nINFO ({len(self.infos)}):")
            for i, issue in enumerate(self.infos, 1):
                print(f"\n{i}. {issue}")

        print("\n" + "=" * 70)

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
                if issue.suggested_fix:
                    extra += f"<div class='suggested-fix'><strong>Suggested Fix:</strong> {issue.suggested_fix}</div>\n"
                cards.append(
                    f"<div class='issue-card {css_class}'>"
                    f"<div class='issue-header'>{i}. {issue.message}</div>"
                    f"<div class='issue-detail'><strong>Rule ID:</strong> <span class='rule-id'>{issue.rule_id}</span></div>"
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
<strong>Dataset:</strong> {self.dataset_name}<br>
<strong>Type:</strong> {self.dataset_type} {self.model_version}<br>
<strong>Status:</strong> <span class="status">{status_text}</span><br>
<strong>Errors:</strong> {len(self.errors)} | <strong>Warnings:</strong> {len(self.warnings)} | <strong>Info:</strong> {len(self.infos)}
</div>
{errors_html}
{warnings_html}
</div>
</body>
</html>"""
