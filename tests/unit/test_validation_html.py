"""The validation HTML page (#119): every cell escaped, ``rows_affected=0`` shown.

``ValidationResult.save_html_report`` and ``fleet validate --report`` write the
page of :func:`fleet.validation.models.write_html_report`; the CLI side is
covered in ``test_cli_validate.py``.
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


def test_every_value_is_escaped(tmp_path: Path) -> None:
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
    refused = SweepDataset(Path("data/sdtm/ae.parquet"), None, HOSTILE)

    page = Path(
        write_html_report([result], tmp_path / "report.html", could_not_run=[refused])
    ).read_text(encoding="utf-8")

    for raw in ("<b>", " & ", '"q"', "'a'"):
        assert raw not in page
    # status: dataset, type, version; finding: dataset, rule, variable, message,
    # fix, verb, method, spec; could not run: reason
    assert page.count(ESCAPED) == 12


def test_rows_affected_zero_is_shown(tmp_path: Path) -> None:
    issue = ValidationIssue(Severity.ERROR, "CORE-000001", "bad", rows_affected=0)
    result = ValidationResult("AE", "sdtmig", "3-4", total_issues=1, errors=[issue])

    page = Path(result.save_html_report(tmp_path / "report.html")).read_text(encoding="utf-8")

    assert "<td>CORE-000001</td><td>official</td><td></td><td>0</td><td>bad</td>" in page
    assert "Rows: 0" in str(issue)
