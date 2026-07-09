"""Tests for the ``fleet lsp`` semantic helpers (``fleet.lsp_server``).

The helpers are pure functions over ``(text, position)`` so no running
server is needed: diagnostics on bad specs (YAML errors, schema
violations, unknown-algorithm did-you-mean), completions (algorithm ids
from the registry, per-algorithm params, codelist OIDs), and hover
(algorithm docs, inline-codelist previews).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pygls", reason="lsp extra (pygls) not installed")

from fleet.core.spec_registry import algorithm_names, get_algorithm  # noqa: E402
from fleet.lsp_server import (  # noqa: E402
    compute_completions,
    compute_diagnostics,
    compute_hover,
)

EXAMPLE_SPEC = (
    Path(__file__).parent.parent.parent / "examples" / "cdiscpilot01" / "sdtm" / "define.yaml"
)

#: Minimal schema-valid-ish SDTM spec with one deliberate typo.
BAD_ALGO_SPEC = """\
study:
  standard: SDTMIG
datasets:
  - name: DM
    variables:
      - name: SEX
        derivation:
          algorithm: asign_ct
          source: sex
"""

CODELIST_SPEC = """\
study:
  standard: SDTMIG
codelists:
  - oid: C66731
    name: Sex
    type: text
    items:
      - coded_value: "M"
        decode: MALE
      - coded_value: "F"
        decode: FEMALE
datasets:
  - name: DM
    variables:
      - name: SEX
        derivation:
          algorithm: assign_ct
          source: sex
          ct_codelist: C66731
"""


class TestDiagnostics:
    def test_valid_example_spec_is_clean(self):
        text = EXAMPLE_SPEC.read_text(encoding="utf-8")
        assert compute_diagnostics(text, str(EXAMPLE_SPEC)) == []

    def test_yaml_syntax_error_reported_with_line(self):
        diags = compute_diagnostics("study:\n  id: [unclosed\n")
        assert len(diags) == 1
        assert "YAML syntax error" in diags[0]["message"]

    def test_unknown_algorithm_gets_did_you_mean(self):
        diags = compute_diagnostics(BAD_ALGO_SPEC)
        algo = [d for d in diags if "asign_ct" in d["message"]]
        assert len(algo) == 1
        assert "Did you mean 'assign_ct'?" in algo[0]["message"]
        assert algo[0]["line"] == 7  # the `algorithm:` line, 0-based

    def test_schema_violations_reported(self):
        # study is missing required keys (name, description, ...)
        diags = compute_diagnostics(BAD_ALGO_SPEC)
        assert any("required property" in d["message"] for d in diags)

    def test_wrong_standard_algorithm_named(self):
        text = BAD_ALGO_SPEC.replace("asign_ct", "chg")  # chg is ADaM-only
        diags = compute_diagnostics(text)
        assert any("'chg' is a adam algorithm" in d["message"] for d in diags)


class TestCompletions:
    def _algo_items(self, text: str) -> list[str]:
        lines = text.splitlines()
        line = next(i for i, ln in enumerate(lines) if "algorithm:" in ln)
        return [i["label"] for i in compute_completions(text, line, len(lines[line]))]

    def test_algorithm_completions_match_registry(self):
        labels = self._algo_items(BAD_ALGO_SPEC)
        assert set(algorithm_names("sdtm")) == set(labels)  # SDTMIG file → sdtm only
        assert "assign_ct" in labels
        assert "chg" not in labels

    def test_algorithm_completions_both_standards_when_unknown(self):
        text = BAD_ALGO_SPEC.replace("  standard: SDTMIG\n", "")
        labels = self._algo_items(text)
        assert "assign_ct" in labels and "chg" in labels

    def test_param_completions_required_first(self):
        text = BAD_ALGO_SPEC.replace("asign_ct", "duration") + "          "
        lines = text.splitlines()
        items = compute_completions(text, len(lines) - 1, 10)
        labels = [i["label"] for i in items]
        assert set(labels) == {p.name for p in get_algorithm("sdtm", "duration").params}
        ordered = sorted(items, key=lambda i: i["sort_text"])
        assert [i["label"] for i in ordered][:2] == ["start", "end"]  # required first

    def test_codelist_oid_completions_from_inline_section(self):
        lines = CODELIST_SPEC.splitlines()
        line = next(i for i, ln in enumerate(lines) if "ct_codelist:" in ln)
        char = lines[line].index(":") + 2
        items = compute_completions(CODELIST_SPEC, line, char)
        assert items == [{"label": "C66731", "detail": "Sex"}]


class TestHover:
    def test_algorithm_hover_has_docstring_and_params(self):
        text = CODELIST_SPEC
        lines = text.splitlines()
        line = next(i for i, ln in enumerate(lines) if "algorithm: assign_ct" in ln)
        md = compute_hover(text, line, lines[line].index("assign_ct") + 1)
        assert md is not None
        assert "assign_ct" in md
        assert "controlled-terminology" in md  # registry description
        assert "ct_codelist" in md  # param table

    def test_codelist_hover_shows_name_and_terms(self):
        lines = CODELIST_SPEC.splitlines()
        line = next(i for i, ln in enumerate(lines) if "ct_codelist:" in ln)
        md = compute_hover(CODELIST_SPEC, line, lines[line].index("C66731") + 1)
        assert md is not None
        assert "Sex" in md
        assert "M" in md and "F" in md

    def test_hover_on_plain_text_is_none(self):
        assert compute_hover(CODELIST_SPEC, 0, 1) is None
