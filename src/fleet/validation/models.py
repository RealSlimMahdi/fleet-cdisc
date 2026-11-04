"""Validation result models for CDISC conformance checking."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from fleet.core import log as fleet_log

if TYPE_CHECKING:
    from fleet.validation.run_setup import RunSetup, SweepDataset

#: Validation reports emit through this logger (INFO level, stdout by
#: default — see :mod:`fleet.core.log` to route or silence them).
_logger = fleet_log.get_logger("fleet.validation")

#: Which engine run a finding came from: the CDISC rules, or the study's custom rules.
RuleSource = Literal["official", "custom"]


class Severity(Enum):
    """Where a finding stands.

    CORE gives no severity (ADR-0017).  ``ERROR`` is a finding that blocks,
    ``WARNING`` a finding the study config accepts with a reason, and
    ``INFO`` a note that cannot block (a study-level rule in a
    single-dataset run).
    """

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
    #: The reason from ``validation.accepted`` when the study accepts this finding.
    accepted: str | None = None

    def __str__(self) -> str:
        parts = [f"[{self.severity.value}] {self.rule_id} ({self.source}): {self.message}"]
        if self.accepted:
            parts.append(f"Accepted: {self.accepted}")
        if self.variable:
            parts.append(f"Variable: {self.variable}")
        if self.rows_affected is not None:
            parts.append(f"Rows: {self.rows_affected}")
        if self.producing_verb:
            parts.append(f"Producing verb: {self.producing_verb} ({self.verb_method})")
        if self.spec_ref:
            parts.append(f"Spec reference: {self.spec_ref}")
        if self.suggested_fix:
            parts.append(f"Suggested fix: {self.suggested_fix}")
        return "\n   ".join(parts)


@dataclass
class RuleRun:
    """What one engine run did with its rules, read from the CORE ``Rules_Report``.

    The counts belong to the engine run, not to one dataset: CORE does not
    say which dataset a rule ran on.  A rule that could not run or was not
    loaded is a rule problem, not a data finding, so it never blocks.
    """

    source: RuleSource = "official"
    #: Rules with status ``SUCCESS`` or ``ISSUE_REPORTED``.
    executed: int = 0
    #: Rules with status ``SKIPPED``: no dataset in scope, or a variable absent.
    skipped: int = 0
    #: Rule ID to the engine's reason, for each rule with status ``EXECUTION_ERROR``.
    could_not_run: dict[str, str] = field(default_factory=dict)
    #: Custom rule IDs, or files that do not parse, that are absent from the report.
    not_loaded: list[str] = field(default_factory=list)

    def count_line(self) -> str:
        """One line of counts, the line the verb prints."""
        line = (
            f"Rules (engine run, {self.source}): {self.executed} executed, "
            f"{self.skipped} skipped, {len(self.could_not_run)} could not run"
        )
        if self.source == "custom":
            line += f", {len(self.not_loaded)} not loaded"
        return line

    def problem_lines(self) -> list[str]:
        """The rules that could not run or were not loaded, for the CLI and HTML report."""
        lines = []
        if self.could_not_run:
            if self.source == "custom":
                named = (f"{rid} ({why})" for rid, why in self.could_not_run.items())
            else:
                named = iter(self.could_not_run)
            lines.append(f"Could not run ({self.source}): {', '.join(named)}")
        if self.not_loaded:
            lines.append(f"Not loaded ({self.source}): {', '.join(self.not_loaded)}")
        return lines


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
    #: Rules the engine executed (``SUCCESS`` or ``ISSUE_REPORTED`` in its
    #: ``Rules_Report``); ``None`` when the report does not say.
    rules_executed: int | None = None
    #: Why the engine could not run (crash, timeout, no report), or ``None``.
    could_not_run: str | None = None
    #: One entry per engine run (official, custom) that gave a ``Rules_Report``.
    rule_runs: list[RuleRun] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """``True`` when the engine ran and no finding blocks."""
        return self.could_not_run is None and not self.errors

    @property
    def status(self) -> str:
        """The status word of the report (ADR-0017).

        ``COULD NOT RUN`` when the engine did not finish, ``FAIL`` when a
        finding blocks, ``NOT ASSESSED`` when no rule executed,
        ``FINDINGS (n)`` when every finding is accepted, else ``PASS``.
        """
        if self.could_not_run is not None:
            return "COULD NOT RUN"
        if self.errors:
            return "FAIL"
        if self.rules_executed == 0:
            return "NOT ASSESSED"
        if self.warnings:
            return f"FINDINGS ({len(self.warnings)})"
        return "PASS"

    def apply_setup(self, setup: "RunSetup") -> None:
        """Record *setup* and move the findings it accepts out of the blocking ones.

        A finding is accepted when ``validation.accepted`` lists its rule
        and this dataset; it keeps its message and gains the reason.

        Args:
            setup: The run setup this result was validated with.

        Examples:
            ``result.apply_setup(build_run_setup(name="DM"))``
        """
        self.setup = setup
        reasons = {(a.rule.upper(), a.dataset.upper()): a.reason for a in setup.accepted}
        blocking: list[ValidationIssue] = []
        for issue in self.errors:
            reason = reasons.get((issue.rule_id.upper(), self.dataset_name.upper()))
            if reason is None:
                blocking.append(issue)
            else:
                issue.severity, issue.accepted = Severity.WARNING, reason
                self.warnings.append(issue)
        self.errors = blocking

    @property
    def summary(self) -> str:
        return (
            f"{self.status} - {self.dataset_name} ({self.dataset_type} {self.model_version})\n"
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
        _logger.info(f"Status: {self.status}")
        if self.could_not_run is not None:
            _logger.info(f"Could not run: {self.could_not_run}")
        for run in self.rule_runs:
            _logger.info(run.count_line())
        if self.rules_executed is not None and not self.rule_runs:
            _logger.info(f"Rules executed: {self.rules_executed}")
        _logger.info(f"Total Issues: {self.total_issues}")
        _logger.info(
            f"  Errors: {len(self.errors)}, Warnings (accepted): {len(self.warnings)}, "
            f"Info: {len(self.infos)}"
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
            _logger.info(f"\nACCEPTED FINDINGS ({len(self.warnings)}):")
            for issue in self.warnings:
                label = f"  [{issue.rule_id}] ({issue.source})"
                if issue.variable:
                    label += f" {issue.variable}:"
                _logger.info(f"{label} {issue.message} Accepted: {issue.accepted}")
        if not self.errors and not self.warnings:
            _logger.info(self._nothing_found("No errors or warnings."))

    def _print_full(self) -> None:
        """Expanded view: all fields per issue, including info."""
        if self.errors:
            _logger.info(f"\nERRORS ({len(self.errors)}):")
            for i, issue in enumerate(self.errors, 1):
                _logger.info(f"\n{i}. {issue}")

        if self.warnings:
            _logger.info(f"\nACCEPTED FINDINGS ({len(self.warnings)}):")
            for i, issue in enumerate(self.warnings, 1):
                _logger.info(f"\n{i}. {issue}")

        if self.infos:
            _logger.info(f"\nINFO ({len(self.infos)}):")
            for i, issue in enumerate(self.infos, 1):
                _logger.info(f"\n{i}. {issue}")

        if not self.errors and not self.warnings and not self.infos:
            _logger.info(self._nothing_found("No issues found."))

    def _nothing_found(self, text: str) -> str:
        """The closing line of a report with no finding; NOT ASSESSED is not clean."""
        if self.status == "NOT ASSESSED":
            return "\n  No rule executed, so nothing was assessed."
        return f"\n  {text}"

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
                if issue.accepted:
                    _logger.info(f"   Accepted: {issue.accepted}")
                if issue.suggested_fix:
                    _logger.info(f"   Suggested fix: {issue.suggested_fix}")

        _print_grouped("ERRORS", self.errors)
        _print_grouped("ACCEPTED FINDINGS", self.warnings)
        _print_grouped("INFO", self.infos)

        if not self.errors and not self.warnings and not self.infos:
            _logger.info(self._nothing_found("No issues found."))

    def save_html_report(self, output_path: str | Path) -> str:
        """Write this result as a self-contained HTML page and return its absolute path.

        The page is the one ``fleet validate --report`` writes for a sweep
        (see :func:`write_html_report`), with this dataset only.

        Args:
            output_path: Destination ``.html`` file; parent directories are
                created.

        Returns:
            str: The absolute path of the written file.

        Examples:
            Archive the findings of one dataset::

                result = ValidationService().validate_sdtm(dm, domain="DM", version="3.4")
                result.save_html_report("outputs/dm_validation.html")
        """
        return write_html_report([self], output_path)


def write_html_report(
    results: Sequence[ValidationResult],
    output_path: str | Path,
    *,
    could_not_run: "Sequence[SweepDataset]" = (),
) -> str:
    """Write validation results as one self-contained HTML page; return its absolute path.

    A status row per dataset, then one row per error, warning and info
    finding, and per dataset that could not run.  Every cell is escaped:
    messages carry data values and the text of custom rules.
    Both ``fleet validate --report`` and
    :meth:`ValidationResult.save_html_report` write this page.

    Args:
        results: The validation results, one per dataset.
        output_path: Destination ``.html`` file; parent directories are
            created.
        could_not_run: The datasets of a sweep whose run setup was refused.

    Returns:
        str: The absolute path of the written file.

    Examples:
        One page for every dataset of one engine run::

            results = ValidationService().validate_datasets(
                {"DM": dm, "AE": ae}, standard="sdtm", version="3.4"
            )
            write_html_report(list(results.values()), "outputs/validation.html")
    """
    status = [
        _row(
            r.dataset_name,
            f"{r.dataset_type} {r.model_version}",
            r.status,
            len(r.errors),
            len(r.warnings),
            len(r.infos),
        )
        for r in results
    ]
    findings = [
        _row(
            r.dataset_name,
            i.severity.value,
            i.rule_id,
            i.source,
            i.variable or "",
            "" if i.rows_affected is None else i.rows_affected,
            i.message,
            f"Accepted: {i.accepted}" if i.accepted else (i.suggested_fix or ""),
            f"{i.producing_verb} ({i.verb_method})" if i.producing_verb else "",
            i.spec_ref or "",
        )
        for r in results
        for i in (*r.errors, *r.warnings, *r.infos)
    ]
    findings += [
        _row(d.name, "Could not run", "", "", "", "", d.reason or "", "", "", "")
        for d in could_not_run
    ] + [
        _row(r.dataset_name, "Could not run", "", "", "", "", r.could_not_run, "", "", "")
        for r in results
        if r.could_not_run is not None
    ]
    setups = dict.fromkeys(
        "\n".join(r.setup.header_lines()) for r in results if r.setup is not None
    )
    runs = {id(run): run for r in results for run in r.rule_runs}.values()
    rule_lines = [line for run in runs for line in (run.count_line(), *run.problem_lines())]
    if rule_lines:
        rule_lines.append("Rule problems are not data findings: they do not change the status.")
        setups["\n".join(rule_lines)] = None
    names = [r.dataset_name for r in results] + [d.name for d in could_not_run]
    title = names[0] if len(names) == 1 else f"{len(names)} datasets"
    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>CDISC Validation Report - {escape(title)}</title>"
        "<style>body{font-family:sans-serif}table{border-collapse:collapse;margin:1em 0}"
        "td,th{border:1px solid #999;padding:4px 8px;font-size:13px;text-align:left}</style>"
        "</head><body><h1>CDISC Validation Report</h1>"
        + "".join(f"<pre>{escape(s)}</pre>" for s in setups)
        + "<table>"
        + _row("Dataset", "Standard", "Status", "Errors", "Warnings", "Info", tag="th")
        + "".join(status)
        + "</table><table>"
        + _row(
            "Dataset",
            "Severity",
            "Rule",
            "Source",
            "Variable",
            "Rows",
            "Message",
            "Suggested fix",
            "Producing verb",
            "Spec reference",
            tag="th",
        )
        + ("".join(findings) or "<tr><td colspan=10>No findings.</td></tr>")
        + "</table></body></html>"
    )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return str(path.absolute())


def _row(*cells: object, tag: str = "td") -> str:
    """One table row; every cell is escaped here and nowhere else."""
    return "<tr>" + "".join(f"<{tag}>{escape(str(c))}</{tag}>" for c in cells) + "</tr>"
