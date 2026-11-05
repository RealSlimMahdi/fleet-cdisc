"""Tests for the ``fleet lsp`` semantic helpers (``fleet.lsp_server``).

The helpers are pure functions over ``(text, position)`` so no running
server is needed: diagnostics on bad specs (YAML errors, schema
violations, unknown-algorithm did-you-mean), completions (algorithm ids
from the registry, per-algorithm params, codelist OIDs), and hover
(algorithm docs, inline-codelist previews).
"""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
from pathlib import Path

import pytest

pytest.importorskip("pygls", reason="lsp extra (pygls) not installed")

from fleet.core.spec_registry import algorithm_names, get_algorithm  # noqa: E402
from fleet.lsp_server import (  # noqa: E402
    compute_completions,
    compute_diagnostics,
    compute_hover,
    infer_standards,
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
          algorithm: asign
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
          algorithm: assign
          source: sex
          ct: C66731
"""

#: Simplified single-dataset shape: two entries, only the first derived.
FLAT_SPEC = """\
study:
  standard: SDTMIG
variables:
  - target: DUR
    algorithm: duration
    start: a
  - target: SEX
"""

#: The same block with ``algorithm`` opening the list entry.
INLINE_ALGO_SPEC = """\
study:
  standard: SDTMIG
variables:
  - algorithm: duration
    start: a
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
        algo = [d for d in diags if "asign" in d["message"]]
        assert len(algo) == 1
        assert "Did you mean 'assign'?" in algo[0]["message"]
        assert algo[0]["line"] == 7  # the `algorithm:` line, 0-based

    def test_schema_violations_reported(self):
        # study is missing required keys (name, description, ...)
        diags = compute_diagnostics(BAD_ALGO_SPEC)
        assert any("required property" in d["message"] for d in diags)

    def test_wrong_standard_algorithm_named(self):
        text = BAD_ALGO_SPEC.replace("asign", "chg")  # chg is ADaM-only
        diags = compute_diagnostics(text)
        assert any("'chg' is a adam algorithm" in d["message"] for d in diags)

    def test_simplified_format_is_clean(self):
        """The single-dataset shape from_spec() accepts is a valid spec, not an error."""
        text = "domain: DM\nvariables:\n  - target: USUBJID\n    algorithm: assign\n    source: subject_id\n"
        assert compute_diagnostics(text) == []

    def test_simplified_format_still_catches_unknown_algorithm(self):
        text = "domain: DM\nvariables:\n  - target: USUBJID\n    algorithm: asign\n    source: subject_id\n"
        diags = compute_diagnostics(text)
        assert any("Did you mean 'assign'?" in d["message"] for d in diags)
        assert diags[0]["line"] == 3  # the `algorithm:` line, 0-based


class TestCompletions:
    def _algo_items(self, text: str) -> list[str]:
        lines = text.splitlines()
        line = next(i for i, ln in enumerate(lines) if "algorithm:" in ln)
        return [i["label"] for i in compute_completions(text, line, len(lines[line]))]

    def test_algorithm_completions_match_registry(self):
        labels = self._algo_items(BAD_ALGO_SPEC)
        assert set(algorithm_names("sdtm")) == set(labels)  # SDTMIG file → sdtm only
        assert "assign" in labels
        assert "chg" not in labels

    def test_algorithm_completions_both_standards_when_unknown(self):
        text = BAD_ALGO_SPEC.replace("  standard: SDTMIG\n", "")
        labels = self._algo_items(text)
        assert "assign" in labels and "chg" in labels

    def test_param_completions_required_first(self):
        text = BAD_ALGO_SPEC.replace("asign", "duration") + "          "
        lines = text.splitlines()
        items = compute_completions(text, len(lines) - 1, 10)
        labels = [i["label"] for i in items]
        assert set(labels) == {p.name for p in get_algorithm("sdtm", "duration").params}
        ordered = sorted(items, key=lambda i: i["sort_text"])
        assert [i["label"] for i in ordered][:2] == ["start", "end"]  # required first

    def test_codelist_oid_completions_from_inline_section(self):
        lines = CODELIST_SPEC.splitlines()
        line = next(i for i, ln in enumerate(lines) if "ct:" in ln)
        char = lines[line].index(":") + 2
        items = compute_completions(CODELIST_SPEC, line, char)
        assert items == [{"label": "C66731", "detail": "Sex"}]

    def test_param_completions_when_algorithm_opens_the_list_entry(self):
        text = INLINE_ALGO_SPEC + "    "
        lines = text.splitlines()
        labels = [i["label"] for i in compute_completions(text, len(lines) - 1, 4)]
        # c1-611: the block already holds start, so it is not offered again
        assert set(labels) == {p.name for p in get_algorithm("sdtm", "duration").params} - {"start"}

    def test_param_completions_stop_at_the_next_variable_entry(self):
        """A fresh entry has no algorithm yet, so the previous one's params must not leak."""
        text = FLAT_SPEC + "    "
        lines = text.splitlines()
        assert compute_completions(text, len(lines) - 1, 4) == []


class TestHover:
    def test_algorithm_hover_has_docstring_and_params(self):
        text = CODELIST_SPEC
        lines = text.splitlines()
        line = next(i for i, ln in enumerate(lines) if "algorithm: assign" in ln)
        md = compute_hover(text, line, lines[line].index("assign") + 1)
        assert md is not None
        assert "assign" in md
        assert "controlled terminology" in md  # registry description
        assert "Verb: `fleet." in md  # summary source: introspect.algorithm_doc()
        assert "`ct`" in md  # param table

    def test_codelist_hover_shows_name_and_terms(self):
        lines = CODELIST_SPEC.splitlines()
        line = next(i for i, ln in enumerate(lines) if "ct:" in ln)
        md = compute_hover(CODELIST_SPEC, line, lines[line].index("C66731") + 1)
        assert md is not None
        assert "Sex" in md
        assert "M" in md and "F" in md

    def test_algorithm_hover_when_algorithm_opens_the_list_entry(self):
        lines = INLINE_ALGO_SPEC.splitlines()
        line = next(i for i, ln in enumerate(lines) if "algorithm:" in ln)
        md = compute_hover(INLINE_ALGO_SPEC, line, lines[line].index("duration") + 1)
        assert md is not None
        assert "duration" in md
        assert "`start`" in md  # param table

    def test_hover_on_plain_text_is_none(self):
        assert compute_hover(CODELIST_SPEC, 0, 1) is None

    def test_codelist_hover_without_items_has_no_terms_line(self):
        """c1-780: an empty codelist shows its name, not an empty "Terms:" line."""
        text = CODELIST_SPEC.replace(
            '    items:\n      - coded_value: "M"\n        decode: MALE\n'
            '      - coded_value: "F"\n        decode: FEMALE\n',
            "",
        )
        lines = text.splitlines()
        line = next(i for i, ln in enumerate(lines) if "ct:" in ln)

        md = compute_hover(text, line, lines[line].index("C66731") + 1)

        assert md == "**Sex** (`C66731`)"

    def test_adam_hover_names_the_adam_verb(self):
        """c1-780: ``seq`` in an ADaM spec runs the ADaM verb; the hover names it."""
        text = "study:\n  standard: ADaMIG\nvariables:\n  - target: ASEQ\n    algorithm: seq\n"
        lines = text.splitlines()
        line = next(i for i, ln in enumerate(lines) if "algorithm:" in ln)

        md = compute_hover(text, line, lines[line].index("seq") + 1)

        assert md is not None
        assert "Verb: `fleet.adam.namespace.AdamNamespace.seq`" in md


class TestStandardInference:
    @pytest.mark.parametrize(
        ("declared", "expected"),
        [("SDTMIG", ("sdtm",)), ("SENDIG", ("sdtm",)), ("ADaMIG", ("adam",))],
    )
    def test_declared_standard_wins(self, declared, expected):
        assert infer_standards({"study": {"standard": declared}}) == expected

    @pytest.mark.parametrize(
        "path",
        ["/study/metadata/adam/define.yaml", "C:\\study\\metadata\\adam\\define.yaml"],
        ids=["posix", "windows"],
    )
    def test_path_is_the_fallback_hint(self, path):
        assert infer_standards({}, path) == ("adam",)

    def test_declared_standard_beats_the_path(self):
        spec = {"study": {"standard": "SDTMIG"}}
        assert infer_standards(spec, "/study/metadata/adam/define.yaml") == ("sdtm",)

    def test_both_standards_when_nothing_says(self):
        assert infer_standards({}) == ("sdtm", "adam")

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("/work/sdtm/S01/metadata/adam/define.yaml", ("adam",)),
            ("/work/sdtm/S01/metadata/adam", ("adam",)),
            ("/adam/x/sdtm", ("sdtm",)),
        ],
    )
    def test_the_nearest_folder_decides(self, path, expected):
        """c1-614: the folder nearest the file wins, not the first substring."""
        assert infer_standards({}, path) == expected


# ── Medium and low audit findings ─────────────────────────────────────────────


def _example_with(line_after: str, new_line: str) -> tuple[str, int]:
    """The pilot SDTM spec with *new_line* inserted after the DM.SEX line holding *line_after*."""
    lines = EXAMPLE_SPEC.read_text(encoding="utf-8").splitlines()
    sex = next(i for i, ln in enumerate(lines) if ln.strip() == "- name: SEX")
    at = next(i for i in range(sex, len(lines)) if lines[i].strip().startswith(line_after)) + 1
    lines.insert(at, new_line)
    return "\n".join(lines) + "\n", at


class TestAuditDiagnostics:
    def test_c1_608_an_unexpected_variable_key_is_on_its_own_line(self):
        text, line = _example_with("- name: SEX", "        orgin: Collected")
        assert compute_diagnostics(text, str(EXAMPLE_SPEC)) == [
            {
                "line": line,
                "message": "Additional properties are not allowed ('orgin' was unexpected)",
                "severity": "error",
            }
        ]

    def test_c1_608_a_derivation_key_is_explained_like_from_spec(self):
        text, line = _example_with("algorithm: assign", "          sorce: sex")
        assert compute_diagnostics(text, str(EXAMPLE_SPEC)) == [
            {"line": line, "message": "sorce: Extra inputs are not permitted", "severity": "error"}
        ]

    def test_c1_610_keys_only_define_xml_needs_are_warnings(self):
        text = (
            "output_format: parquet\n"
            "datasets:\n"
            "  - name: ADSL\n"
            "    variables:\n"
            "      - name: USUBJID\n"
        )
        diags = compute_diagnostics(text)
        assert diags and all(d["severity"] == "warning" for d in diags)
        assert {
            "line": 2,
            "message": "'label' is a required property (needed by fleet define-xml)",
            "severity": "warning",
        } in diags
        assert not any("any of the given schemas" in d["message"] for d in diags)

    def test_c1_610_a_spec_with_no_shape_is_still_an_error(self):
        assert compute_diagnostics("output_format: parquet\n") == [
            {
                "line": 0,
                "message": "A spec needs datasets: with study:, or variables:",
                "severity": "error",
            }
        ]

    def test_c1_612_a_unicode_line_separator_does_not_shift_lines(self):
        text = 'study:\n  standard: SDTMIG\n  name: "a\u2028b"\ndatasets: 5\n'
        assert [d["line"] for d in compute_diagnostics(text) if "array" in d["message"]] == [3]

    def test_c1_615_an_upper_case_name_gets_a_hint(self):
        text = BAD_ALGO_SPEC.replace("standard: SDTMIG", "standard: ADaMIG").replace("asign", "CHG")
        assert any("Did you mean 'chg'?" in d["message"] for d in compute_diagnostics(text))

    def test_c1_615_an_old_name_points_to_fleet_migrate(self):
        text = BAD_ALGO_SPEC.replace("asign", "hardcode_no_ct")
        algo = [d for d in compute_diagnostics(text) if "hardcode_no_ct" in d["message"]]
        assert len(algo) == 1
        assert "'assign'" in algo[0]["message"] and "fleet migrate --spec" in algo[0]["message"]

    def test_c1_615_spec_version_1_points_to_fleet_migrate(self):
        text = "fleet_spec_version: 1\n" + FLAT_SPEC
        assert any("fleet migrate --spec" in d["message"] for d in compute_diagnostics(text))

    @pytest.mark.parametrize(
        "text", ["a: &x\n  - *x\n", "[" * 3000 + "]" * 3000], ids=["recursive-anchor", "deep"]
    )
    def test_c1_616_a_hostile_file_gives_one_diagnostic(self, text):
        diags = compute_diagnostics(text)
        assert len(diags) == 1
        assert "nests too deep or expands too much" in diags[0]["message"]
        assert compute_hover(text, 0, 1) is None
        assert compute_completions(text, 0, 1) == []


class TestAuditCompletions:
    def test_c1_609_a_value_after_a_bare_colon_gets_a_space(self):
        text = "study:\n  standard: SDTMIG\nderivation:\n  algorithm:"
        items = compute_completions(text, 3, len("  algorithm:"))
        assert items and all(i["insert_text"] == f" {i['label']}" for i in items)
        after_space = compute_completions(text + " ", 3, len("  algorithm: "))
        assert all("insert_text" not in i for i in after_space)

    def test_c1_611_a_quoted_algorithm_offers_its_keys_less_the_held_ones(self):
        text = (
            "study:\n  standard: ADaMIG\nvariables:\n"
            '  - target: ADY\n    algorithm: "duration"\n    start: TRTSDT\n    \n'
        )
        labels = {i["label"] for i in compute_completions(text, 6, 4)}
        assert labels == {p.name for p in get_algorithm("adam", "duration").params} - {"start"}

    def test_c1_611_a_key_inside_a_nested_mapping_offers_nothing(self):
        text = CODELIST_SPEC.replace("ct: C66731", "ct_map:\n            Male: M\n            ")
        lines = text.splitlines()
        assert compute_completions(text, len(lines) - 1, 12) == []


def test_c1_616_load_spec_yaml_refuses_a_recursive_anchor():
    import yaml

    from fleet.introspect import load_spec_yaml

    with pytest.raises(yaml.YAMLError, match="nests too deep"):
        load_spec_yaml("a: &x\n  - *x\n")


# ── The server over stdio ─────────────────────────────────────────────────────


def _frame(message: dict) -> bytes:
    body = json.dumps(message).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def _reader(stream, inbox: queue.Queue) -> None:
    while True:
        length = None
        while True:
            header = stream.readline()
            if not header:
                return
            if header in (b"\r\n", b"\n"):
                break
            name, _, value = header.decode("ascii").partition(":")
            if name.lower() == "content-length":
                length = int(value)
        inbox.put(json.loads(stream.read(length)))


def _next(inbox: queue.Queue, method: str) -> dict:
    while True:
        message = inbox.get(timeout=30)
        if message.get("method") == method or (method == "result" and "result" in message):
            return message


def test_c1_612_c1_613_the_server_over_stdio():
    """Full sync, line numbers past U+2028, and an empty list when a file closes."""
    server = subprocess.Popen(
        [sys.executable, "-m", "fleet.lsp_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    inbox: queue.Queue = queue.Queue()
    threading.Thread(target=_reader, args=(server.stdout, inbox), daemon=True).start()
    uri = "file:///tmp/sdtm/define.yaml"
    try:

        def send(message: dict) -> None:
            server.stdin.write(_frame({"jsonrpc": "2.0", **message}))
            server.stdin.flush()

        send({"id": 1, "method": "initialize", "params": {"capabilities": {}}})
        capabilities = _next(inbox, "result")["result"]["capabilities"]
        assert capabilities["textDocumentSync"]["change"] == 1  # Full
        assert capabilities["completionProvider"]["triggerCharacters"] == [" "]
        send({"method": "initialized", "params": {}})
        text = 'study:\n  standard: SDTMIG\n  name: "a\u2028b"\ndatasets: 5\n'
        send(
            {
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {"uri": uri, "languageId": "yaml", "version": 1, "text": text}
                },
            }
        )
        published = _next(inbox, "textDocument/publishDiagnostics")["params"]
        lines = [d["range"]["start"]["line"] for d in published["diagnostics"]]
        assert 3 in lines and 4 not in lines
        send({"method": "textDocument/didClose", "params": {"textDocument": {"uri": uri}}})
        closed = _next(inbox, "textDocument/publishDiagnostics")["params"]
        assert closed == {"uri": uri, "diagnostics": []}
    finally:
        server.kill()
        server.wait(timeout=10)
