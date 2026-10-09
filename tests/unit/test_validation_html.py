"""The validation HTML page (#119): every value escaped, one renderer for every surface.

``ValidationResult.save_html_report`` and ``fleet validate --report`` both
write the page of :func:`fleet.validation.models.write_html_report`; the CLI
side is covered in ``test_cli_validate.py``.
"""

from __future__ import annotations

from pathlib import Path

from fleet.validation import SweepDataset
from fleet.validation.models import (
    Severity,
    ValidationIssue,
    ValidationResult,
    write_html_report,
)

#: A tag, an ampersand and both quote characters, as a data value or custom rule text may hold.
HOSTILE = "<b>x</b> & \"q\" 'a'"
ESCAPED = "&lt;b&gt;x&lt;/b&gt; &amp; &quot;q&quot; &#x27;a&#x27;"


def _result(*issues: ValidationIssue, name: str = "AE") -> ValidationResult:
    return ValidationResult(
        dataset_name=name,
        dataset_type="sdtmig",
        model_version="3-4",
        total_issues=len(issues),
        errors=[i for i in issues if i.severity == Severity.ERROR],
        warnings=[i for i in issues if i.severity == Severity.WARNING],
        infos=[i for i in issues if i.severity == Severity.INFO],
    )


def _page(result: ValidationResult, tmp_path: Path) -> str:
    return Path(result.save_html_report(tmp_path / "report.html")).read_text(encoding="utf-8")


class TestEscaping:
    def test_every_interpolated_value_is_escaped(self, tmp_path: Path) -> None:
        issue = ValidationIssue(
            Severity.ERROR,
            rule_id=HOSTILE,
            message=HOSTILE,
            variable=HOSTILE,
            suggested_fix=HOSTILE,
            producing_verb=HOSTILE,
            verb_method=HOSTILE,
            spec_ref=HOSTILE,
        )
        result = ValidationResult(HOSTILE, HOSTILE, HOSTILE, total_issues=1, errors=[issue])

        page = _page(result, tmp_path)

        for raw in ("<b>", " & ", '"q"', "'a'"):
            assert raw not in page
        assert f"<title>CDISC Validation Report - {ESCAPED}</title>" in page
        # the attribute value stays inside its quotes
        assert f"<a href='#{ESCAPED}' class='verb-link'>{ESCAPED}</a> &middot; {ESCAPED}" in page
        # title, dataset, type, version, message, rule, variable, verb, method twice, spec, fix
        assert page.count(ESCAPED) == 12

    def test_a_could_not_run_reason_is_escaped(self, tmp_path: Path) -> None:
        dataset = SweepDataset(Path("data/sdtm/ae.parquet"), None, f"Could not run: {HOSTILE}")

        write_html_report([], tmp_path / "report.html", could_not_run=[dataset])

        page = (tmp_path / "report.html").read_text(encoding="utf-8")
        assert "<b>" not in page
        assert f"<strong>Reason:</strong> Could not run: {ESCAPED}" in page


class TestContent:
    def test_rows_affected_zero_is_shown(self, tmp_path: Path) -> None:
        issue = ValidationIssue(Severity.ERROR, "CORE-000001", "bad", rows_affected=0)

        assert "<strong>Rows Affected:</strong> 0</div>" in _page(_result(issue), tmp_path)
        assert "Rows: 0" in str(issue)

    def test_errors_warnings_and_info_each_get_a_section_of_cards(self, tmp_path: Path) -> None:
        page = _page(
            _result(
                ValidationIssue(Severity.ERROR, "R1", "an error"),
                ValidationIssue(Severity.WARNING, "R2", "a warning"),
                ValidationIssue(Severity.INFO, "R3", "an info"),
            ),
            tmp_path,
        )

        assert "<div class='section-title'>Errors (1)</div>" in page
        assert "<div class='section-title'>Warnings (1)</div>" in page
        assert "<div class='section-title'>Info (1)</div>" in page
        assert "<div class='issue-card info'>" in page

    def test_the_method_writes_the_shared_page(self, tmp_path: Path) -> None:
        result = _result(ValidationIssue(Severity.ERROR, "R1", "an error", variable="AESEV"))

        result.save_html_report(tmp_path / "method.html")
        write_html_report([result], tmp_path / "shared.html")

        method = (tmp_path / "method.html").read_text(encoding="utf-8")
        assert method == (tmp_path / "shared.html").read_text(encoding="utf-8")

    def test_one_page_holds_every_dataset_and_every_could_not_run(self, tmp_path: Path) -> None:
        failed = _result(ValidationIssue(Severity.ERROR, "R1", "an error"), name="AE")
        passed = _result(name="DM")
        refused = SweepDataset(Path("data/sdtm/adsl.parquet"), None, "Could not run: unclear")

        write_html_report([failed, passed], tmp_path / "r.html", could_not_run=[refused])

        page = (tmp_path / "r.html").read_text(encoding="utf-8")
        assert "<title>CDISC Validation Report - 3 datasets</title>" in page
        assert "<h1 class='fail'>" in page
        for name, status in (("AE", "fail"), ("DM", "pass"), ("ADSL", "could-not-run")):
            assert f"<div class='summary {status}'>\n<strong>Dataset:</strong> {name}<br>" in page
