"""Fleet language server for ``define.yaml`` files (``fleet lsp --stdio``).

Requires the ``lsp`` extra (``pygls``).  Everything the server knows is
discovered from the installed Fleet package — the generated JSON schema
(``fleet.define_xml.schemas``), the spec-algorithm registry
(``fleet.core.spec_registry``), and verb docstrings
(``fleet.core.algorithm_resolver``) — never hardcoded, so new algorithms
appear in completions the moment they are registered.

Capabilities:

* **Diagnostics** (debounced on open/change): YAML syntax errors, JSON
  schema violations mapped to the offending line (best effort via YAML
  node marks), and did-you-mean hints for unknown ``algorithm:`` values.
* **Completions**: ``algorithm:`` values per standard, per-algorithm
  parameter keys (required first), and codelist OIDs from the file's own
  ``codelists:`` section.
* **Hover**: algorithm summary + parameter table (from the dispatched
  verb's docstring) and inline-codelist term previews.

The semantic helpers (:func:`compute_diagnostics`,
:func:`compute_completions`, :func:`compute_hover`) are pure functions
over ``(text, position)`` returning plain data, so they are unit-testable
without a running server.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

import yaml

#: Seconds to wait after the last keystroke before re-validating.
_DEBOUNCE_S = 0.3

#: Diagnostics scan both standards when neither the file nor its path
#: pins one down.
_STANDARDS = ("sdtm", "adam")


# ────────────────────────────────────────────────────────────────────── #
# Pure helpers (no pygls dependency)                                      #
# ────────────────────────────────────────────────────────────────────── #


@lru_cache(maxsize=1)
def _schema() -> dict[str, Any]:
    """Load the generated define-spec JSON schema shipped with Fleet."""
    from fleet.define_xml.schema_builder import SCHEMA_PATH

    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _safe_load(text: str) -> dict[str, Any]:
    """Parse YAML, returning ``{}`` on any error or non-mapping document."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _line_index(text: str) -> dict[tuple[Any, ...], int]:
    """Map document paths (e.g. ``("datasets", 0, "name")``) to 0-based lines."""
    try:
        root = yaml.compose(text)
    except yaml.YAMLError:
        return {}
    if root is None:
        return {}
    index: dict[tuple[Any, ...], int] = {}

    def walk(node: yaml.Node, path: tuple[Any, ...]) -> None:
        index.setdefault(path, node.start_mark.line)
        if isinstance(node, yaml.MappingNode):
            for key, value in node.value:
                key_path = (*path, getattr(key, "value", "?"))
                index.setdefault(key_path, key.start_mark.line)
                walk(value, key_path)
        elif isinstance(node, yaml.SequenceNode):
            for i, item in enumerate(node.value):
                walk(item, (*path, i))

    walk(root, ())
    return index


def _locate(index: dict[tuple[Any, ...], int], path: tuple[Any, ...]) -> int:
    """Return the line of *path*, falling back to its nearest ancestor."""
    while path:
        if path in index:
            return index[path]
        path = path[:-1]
    return 0


def infer_standards(data: dict[str, Any], path: str = "") -> tuple[str, ...]:
    """Infer which standard(s) a define file targets.

    Resolution order: the file's own ``study.standard`` value, then the
    file path (``/sdtm/`` vs ``/adam/``), then both.

    Args:
        data: Parsed define.yaml mapping (may be empty).
        path: File path, used as a fallback hint.

    Returns:
        tuple[str, ...]: ``("sdtm",)``, ``("adam",)``, or both.
    """
    study = data.get("study")
    declared = str(study.get("standard", "")).upper() if isinstance(study, dict) else ""
    if "SDTM" in declared or "SEND" in declared:
        return ("sdtm",)
    if "ADAM" in declared:
        return ("adam",)
    lowered = path.lower()
    if "/sdtm/" in lowered or "\\sdtm\\" in lowered:
        return ("sdtm",)
    if "/adam/" in lowered or "\\adam\\" in lowered:
        return ("adam",)
    return _STANDARDS


def _iter_algorithms(data: dict[str, Any]):
    """Yield ``(derivation_path, algorithm)`` for every derivation block."""
    datasets = data.get("datasets")
    if not isinstance(datasets, list):
        return
    for di, ds in enumerate(datasets):
        variables = ds.get("variables") if isinstance(ds, dict) else None
        if not isinstance(variables, list):
            continue
        for vi, var in enumerate(variables):
            derivation = var.get("derivation") if isinstance(var, dict) else None
            if isinstance(derivation, dict) and isinstance(derivation.get("algorithm"), str):
                yield (("datasets", di, "variables", vi, "derivation"), derivation["algorithm"])


def compute_diagnostics(text: str, path: str = "") -> list[dict[str, Any]]:
    """Validate define.yaml *text*, returning plain diagnostic dicts.

    Three passes: YAML syntax, unknown ``algorithm:`` values (with
    registry-driven did-you-mean suggestions, suppressing the JSON
    schema's unhelpful anyOf message for the same block), then JSON
    schema validation with errors mapped to the offending line.

    Args:
        text: Full document text.
        path: File path (standard-inference hint).

    Returns:
        list[dict]: ``{"line": int, "message": str, "severity":
            "error" | "warning"}`` entries, 0-based lines.

    Examples:
        Lint a spec string before shipping it to a pipeline::

            from fleet.lsp_server import compute_diagnostics

            problems = compute_diagnostics(Path("define.yaml").read_text())
            assert not problems
    """
    import jsonschema
    from jsonschema.exceptions import best_match

    from fleet.core.spec_registry import get_algorithm, suggest_algorithm

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        problem = getattr(exc, "problem", None) or str(exc)
        return [
            {
                "line": mark.line if mark else 0,
                "message": f"YAML syntax error: {problem}",
                "severity": "error",
            }
        ]
    if data is None:
        return []
    if not isinstance(data, dict):
        return [
            {
                "line": 0,
                "message": f"A define.yaml must be a YAML mapping, got {type(data).__name__}.",
                "severity": "error",
            }
        ]

    index = _line_index(text)
    standards = infer_standards(data, path)
    diagnostics: list[dict[str, Any]] = []

    # Pass 1 — unknown algorithms via the registry (clearer than anyOf).
    flagged: set[tuple[Any, ...]] = set()
    for derivation_path, algo in _iter_algorithms(data):
        if any(get_algorithm(std, algo) for std in standards):
            continue
        flagged.add(derivation_path)
        line = _locate(index, (*derivation_path, "algorithm"))
        other = next(
            (std for std in _STANDARDS if std not in standards and get_algorithm(std, algo)),
            None,
        )
        if other is not None:
            message = (
                f"'{algo}' is a {other} algorithm, but this file targets "
                f"{'/'.join(standards)}."
            )
        else:
            suggestion = next(
                (s for s in (suggest_algorithm(std, algo) for std in standards) if s),
                None,
            )
            hint = f" Did you mean '{suggestion}'?" if suggestion else ""
            message = f"Unknown algorithm '{algo}'.{hint}"
        diagnostics.append({"line": line, "message": message, "severity": "error"})

    # Pass 2 — generated JSON schema (whole document).
    validator = jsonschema.Draft202012Validator(_schema())
    for error in validator.iter_errors(data):
        best = best_match([error]) or error
        error_path = tuple(best.absolute_path)
        if any(error_path[: len(f)] == f for f in flagged):
            continue  # already reported with a better message
        diagnostics.append(
            {
                "line": _locate(index, error_path),
                "message": best.message.splitlines()[0][:300],
                "severity": "error",
            }
        )
    return diagnostics


_KEY_PREFIX_RE = re.compile(r"^\s*[\w-]*$")
_WORD_RE = re.compile(r"[A-Za-z0-9_.\-]+")


def _enclosing_algorithm(lines: list[str], line: int) -> str | None:
    """Best-effort: the ``algorithm:`` value governing *line*'s block.

    Scans upward until a new variable entry (``- name:``) is crossed.
    """
    for i in range(line - 1, max(-1, line - 40), -1):
        stripped = lines[i].strip()
        match = re.match(r"^algorithm:\s*([\w-]+)", stripped)
        if match:
            return match.group(1)
        if stripped.startswith("- name:"):
            return None
    return None


def compute_completions(
    text: str, line: int, character: int, path: str = ""
) -> list[dict[str, Any]]:
    """Return completion candidates for a define.yaml cursor position.

    Completes ``algorithm:`` values (registry ids per inferred standard),
    parameter keys of the enclosing algorithm (required first), and
    codelist OIDs from the file's own ``codelists:`` section.

    Args:
        text: Full document text.
        line: 0-based cursor line.
        character: 0-based cursor column.
        path: File path (standard-inference hint).

    Returns:
        list[dict]: ``{"label", "detail", "sort_text",
            "documentation"}`` entries (all but ``label`` optional).

    Examples:
        Offer algorithm ids at an ``algorithm:`` key::

            from fleet.lsp_server import compute_completions

            items = compute_completions("derivation:\\n  algorithm: ", 1, 13)
            assert any(i["label"] == "assign_ct" for i in items)
    """
    from fleet.core import spec_registry

    lines = text.splitlines()
    if line >= len(lines):
        return []
    prefix = lines[line][:character]
    stripped = prefix.strip()
    data = _safe_load(text)

    if re.match(r"^(-\s+)?algorithm:", stripped):
        seen: dict[str, dict[str, Any]] = {}
        for std in infer_standards(data, path):
            for algo in spec_registry.algorithms(std):
                seen.setdefault(
                    algo.name,
                    {
                        "label": algo.name,
                        "detail": std,
                        "documentation": algo.description,
                    },
                )
        return sorted(seen.values(), key=lambda i: i["label"])

    if re.match(r"^(-\s+)?(ct_codelist|codelist):", stripped):
        codelists = data.get("codelists")
        return [
            {"label": str(cl["oid"]), "detail": str(cl.get("name", ""))}
            for cl in (codelists if isinstance(codelists, list) else [])
            if isinstance(cl, dict) and cl.get("oid")
        ]

    if _KEY_PREFIX_RE.match(prefix):
        algo_name = _enclosing_algorithm(lines, line)
        if algo_name:
            for std in infer_standards(data, path):
                algo = spec_registry.get_algorithm(std, algo_name)
                if algo is None:
                    continue
                return [
                    {
                        "label": p.name,
                        "detail": ("required — " if p.required else "") + (p.description or ""),
                        "sort_text": f"{int(not p.required)}{i:02d}",
                    }
                    for i, p in enumerate(algo.params)
                ]
    return []


def _word_at(line_text: str, character: int) -> str | None:
    """Return the ``[A-Za-z0-9_.-]+`` token spanning *character*, if any."""
    for match in _WORD_RE.finditer(line_text):
        if match.start() <= character <= match.end():
            return match.group()
    return None


def compute_hover(text: str, line: int, character: int, path: str = "") -> str | None:
    """Return Markdown hover content for a define.yaml cursor position.

    Hovers on an ``algorithm:`` value show the registry description, the
    first sentence of the dispatched verb's docstring with its dotted
    path, and the parameter table.  Hovers on a codelist OID declared in
    the file's ``codelists:`` section show its name and first terms.

    Args:
        text: Full document text.
        line: 0-based cursor line.
        character: 0-based cursor column.
        path: File path (standard-inference hint).

    Returns:
        str | None: Markdown content, or ``None`` when there is nothing
            to say about the position.

    Examples:
        Explain an algorithm without leaving the editor::

            from fleet.lsp_server import compute_hover

            md = compute_hover("derivation:\\n  algorithm: assign_ct", 1, 15)
            assert "assign_ct" in md
    """
    from fleet.core import spec_registry
    from fleet.core.algorithm_resolver import resolve_algorithm_docstring

    lines = text.splitlines()
    if line >= len(lines):
        return None
    word = _word_at(lines[line], character)
    if not word:
        return None
    data = _safe_load(text)

    if lines[line].strip().startswith("algorithm:"):
        for std in infer_standards(data, path):
            algo = spec_registry.get_algorithm(std, word)
            if algo is None:
                continue
            summary, dotted = resolve_algorithm_docstring(algo.name)
            parts = [f"**{algo.name}** ({std}) — {algo.description or summary or ''}".rstrip(" —")]
            if summary and summary != algo.description:
                parts.append(summary)
            if dotted:
                parts.append(f"Verb: `{dotted}`")
            if algo.params:
                rows = "\n".join(
                    f"- `{p.name}`{' *(required)*' if p.required else ''}"
                    + (f" — {p.description}" if p.description else "")
                    for p in algo.params
                )
                parts.append(f"Parameters:\n{rows}")
            return "\n\n".join(parts)
        return None

    codelists = data.get("codelists")
    for cl in codelists if isinstance(codelists, list) else []:
        if isinstance(cl, dict) and str(cl.get("oid")) == word:
            items = [i for i in (cl.get("items") or []) if isinstance(i, dict)]
            terms = ", ".join(str(i.get("coded_value")) for i in items[:8])
            suffix = ", …" if len(items) > 8 else ""
            return f"**{cl.get('name', word)}** (`{word}`)\n\nTerms: {terms}{suffix}"
    return None


# ────────────────────────────────────────────────────────────────────── #
# pygls server wiring                                                     #
# ────────────────────────────────────────────────────────────────────── #


def create_server():
    """Build the pygls ``LanguageServer`` with all Fleet features registered.

    Returns:
        pygls.lsp.server.LanguageServer: Server ready for ``.start_io()``.
    """
    import asyncio

    from lsprotocol import types
    from pygls.lsp.server import LanguageServer

    from fleet._version import __version__

    server = LanguageServer("fleet-lsp", __version__)

    def _to_lsp(text: str, diags: list[dict[str, Any]]) -> list[Any]:
        lines = text.splitlines()
        out = []
        for d in diags:
            ln = min(d["line"], max(len(lines) - 1, 0))
            width = len(lines[ln]) if lines else 1
            out.append(
                types.Diagnostic(
                    range=types.Range(
                        start=types.Position(line=ln, character=0),
                        end=types.Position(line=ln, character=max(width, 1)),
                    ),
                    message=d["message"],
                    severity=(
                        types.DiagnosticSeverity.Error
                        if d["severity"] == "error"
                        else types.DiagnosticSeverity.Warning
                    ),
                    source="fleet",
                )
            )
        return out

    async def _validate(ls: LanguageServer, uri: str) -> None:
        doc = ls.workspace.get_text_document(uri)
        version = doc.version
        await asyncio.sleep(_DEBOUNCE_S)
        doc = ls.workspace.get_text_document(uri)
        if doc.version != version:
            return  # superseded by a newer edit
        ls.text_document_publish_diagnostics(
            types.PublishDiagnosticsParams(
                uri=uri,
                version=doc.version,
                diagnostics=_to_lsp(doc.source, compute_diagnostics(doc.source, doc.path)),
            )
        )

    @server.feature(types.TEXT_DOCUMENT_DID_OPEN)
    async def did_open(ls: LanguageServer, params: types.DidOpenTextDocumentParams) -> None:
        await _validate(ls, params.text_document.uri)

    @server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
    async def did_change(ls: LanguageServer, params: types.DidChangeTextDocumentParams) -> None:
        await _validate(ls, params.text_document.uri)

    @server.feature(
        types.TEXT_DOCUMENT_COMPLETION,
        types.CompletionOptions(trigger_characters=[":", " "]),
    )
    def completion(ls: LanguageServer, params: types.CompletionParams):
        doc = ls.workspace.get_text_document(params.text_document.uri)
        items = compute_completions(
            doc.source, params.position.line, params.position.character, doc.path
        )
        return [
            types.CompletionItem(
                label=item["label"],
                detail=item.get("detail"),
                sort_text=item.get("sort_text"),
                documentation=item.get("documentation"),
                kind=types.CompletionItemKind.Value,
            )
            for item in items
        ]

    @server.feature(types.TEXT_DOCUMENT_HOVER)
    def hover(ls: LanguageServer, params: types.HoverParams):
        doc = ls.workspace.get_text_document(params.text_document.uri)
        markdown = compute_hover(
            doc.source, params.position.line, params.position.character, doc.path
        )
        if markdown is None:
            return None
        return types.Hover(
            contents=types.MarkupContent(kind=types.MarkupKind.Markdown, value=markdown)
        )

    return server


def main() -> None:
    """Run the Fleet language server over stdio (entry point for ``fleet lsp``)."""
    create_server().start_io()


if __name__ == "__main__":
    main()
