"""Fleet language server for ``define.yaml`` files (``fleet lsp --stdio``).

Requires the ``lsp`` extra (``pygls``).  Everything the server knows is
discovered from the installed Fleet package through :mod:`fleet.introspect`
— the generated JSON schema, the spec-algorithm registry, and verb
docstrings — never hardcoded, so new algorithms appear in completions the
moment they are registered.

This module is a **protocol adapter**: it translates LSP into calls on
that surface and holds no clinical knowledge of its own.  Reaching past
:mod:`fleet.introspect` into Fleet's internals is a test failure
(ADR-0001), because the shipped VS Code client versions against the
surface alone.

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

import re
from fnmatch import fnmatch
from pathlib import PurePath
from typing import Any, get_args

import yaml

from fleet.introspect import Standard, load_spec_yaml, standard_of

#: Seconds to wait after the last keystroke before re-validating.
_DEBOUNCE_S = 0.3

#: Diagnostics scan both standards when neither the file nor its path
#: pins one down.
_STANDARDS = get_args(Standard)

#: Line ends the LSP knows (3.17: \n, \r\n, \r).  ``str.splitlines`` and
#: PyYAML also break on the characters below, which would shift every line.
_LINE_END = re.compile(r"\r\n|\r|\n")
_NOT_A_LINE_END = str.maketrans({"\u2028": " ", "\u2029": " ", "\x85": " "})

#: The key ``from_spec()`` needs on a dataset or a variable entry; every
#: other required key (and every key of ``study:``) only ``fleet define-xml``
#: needs.
_RUNTIME_REQUIRED = frozenset({"name"})


# ────────────────────────────────────────────────────────────────────── #
# Pure helpers (no pygls dependency)                                      #
# ────────────────────────────────────────────────────────────────────── #


def _client_text(text: str) -> str:
    """*text* with U+2028, U+2029 and U+0085 as spaces, so lines count as the client counts them."""
    return text.translate(_NOT_A_LINE_END)


def _lines(text: str) -> list[str]:
    """The lines of *text*, split only where the LSP ends a line."""
    return _LINE_END.split(text)


def is_define_yaml(path: str) -> bool:
    """Return True when *path* names a spec file (``define*.yaml`` or ``.yml``).

    Many LSP clients attach by file type, not by name, so the server gives
    every other YAML file (``study_config.yaml``) an empty diagnostic list.
    """
    name = PurePath(path).name
    return fnmatch(name, "define*.yaml") or fnmatch(name, "define*.yml")


def _safe_load(text: str) -> dict[str, Any]:
    """Parse YAML, returning ``{}`` on any error or non-mapping document."""
    try:
        data = load_spec_yaml(text)
    except (yaml.YAMLError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


def _line_index(text: str) -> dict[tuple[Any, ...], int]:
    """Map document paths (e.g. ``("datasets", 0, "name")``) to 0-based lines."""
    try:
        root = yaml.compose(text)
    except (yaml.YAMLError, RecursionError):
        return {}
    if root is None:
        return {}
    index: dict[tuple[Any, ...], int] = {}
    seen: set[int] = set()

    def walk(node: yaml.Node, path: tuple[Any, ...]) -> None:
        index.setdefault(path, node.start_mark.line)
        if id(node) in seen:  # an alias: its lines are the anchor's, walked once
            return
        seen.add(id(node))
        if isinstance(node, yaml.MappingNode):
            for key, value in node.value:
                key_path = (*path, getattr(key, "value", "?"))
                index.setdefault(key_path, key.start_mark.line)
                walk(value, key_path)
        elif isinstance(node, yaml.SequenceNode):
            for i, item in enumerate(node.value):
                walk(item, (*path, i))

    try:
        walk(root, ())
    except RecursionError:
        return index
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
    nearest folder named ``sdtm`` or ``adam`` in the file path, then both.

    Args:
        data: Parsed define.yaml mapping (may be empty).
        path: File path, used as a fallback hint.

    Returns:
        tuple[str, ...]: ``("sdtm",)``, ``("adam",)``, or both.
    """
    study = data.get("study")
    declared = study.get("standard") if isinstance(study, dict) else None
    standard = standard_of(declared, path)
    return (standard,) if standard else _STANDARDS


def _iter_algorithms(data: dict[str, Any]):
    """Yield ``(derivation_path, algorithm)`` for every derivation block.

    Covers both spec shapes: the define.yaml ``datasets`` tree and the
    simplified single-dataset ``variables`` list whose entries carry
    inline algorithm fields.
    """
    datasets = data.get("datasets")
    if isinstance(datasets, list):
        for di, ds in enumerate(datasets):
            variables = ds.get("variables") if isinstance(ds, dict) else None
            if not isinstance(variables, list):
                continue
            for vi, var in enumerate(variables):
                derivation = var.get("derivation") if isinstance(var, dict) else None
                if isinstance(derivation, dict) and isinstance(derivation.get("algorithm"), str):
                    yield (
                        ("datasets", di, "variables", vi, "derivation"),
                        derivation["algorithm"],
                    )
        return

    flat = data.get("variables")
    if not isinstance(flat, list):
        return
    for vi, var in enumerate(flat):
        if isinstance(var, dict) and isinstance(var.get("algorithm"), str):
            yield (("variables", vi), var["algorithm"])


def compute_diagnostics(text: str, path: str = "") -> list[dict[str, Any]]:
    """Validate define.yaml *text*, returning plain diagnostic dicts.

    Three passes: YAML syntax, unknown ``algorithm:`` values (with
    registry-driven did-you-mean suggestions and a ``fleet migrate --spec``
    hint for a pre-ADR-0008 name, suppressing the JSON schema's unhelpful
    anyOf message for the same block), then JSON schema validation with
    errors mapped to the offending line.  An unexpected key is reported on
    its own line; a refused derivation block in the words of
    ``from_spec()``; a key only ``fleet define-xml`` needs as a warning.

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

    from fleet.introspect import (
        define_schema,
        get_algorithm,
        renamed_algorithm,
        suggest_algorithm,
    )

    text = _client_text(text)
    try:
        data = load_spec_yaml(text)
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
        renamed = renamed_algorithm(algo)
        if other is not None:
            message = (
                f"'{algo}' is a {other} algorithm, but this file targets {'/'.join(standards)}."
            )
        elif renamed is not None:
            message = f"'{algo}' is the pre-ADR-0008 spelling of '{renamed}'. {_MIGRATE_HINT}"
        else:
            suggestion = next(
                (s for s in (suggest_algorithm(std, algo) for std in standards) if s),
                None,
            )
            hint = f" Did you mean '{suggestion}'?" if suggestion else ""
            message = f"Unknown algorithm '{algo}'.{hint}"
        diagnostics.append({"line": line, "message": message, "severity": "error"})

    # Pass 2 — generated JSON schema (whole document).
    validator = jsonschema.Draft202012Validator(define_schema())
    try:
        for error in validator.iter_errors(data):
            if any(tuple(error.absolute_path)[: len(f)] == f for f in flagged):
                continue  # already reported with a better message
            diagnostics += _schema_diagnostics(error, data, index, standards)
    except RecursionError:
        diagnostics.append(
            {"line": 0, "message": "The file nests too deep to validate.", "severity": "error"}
        )
    return diagnostics


_MIGRATE_HINT = "Rewrite the file with `fleet migrate --spec <define.yaml> --write`."


def _schema_diagnostics(
    error: Any, data: dict[str, Any], index: dict[tuple[Any, ...], int], standards: tuple[str, ...]
) -> list[dict[str, Any]]:
    """One schema error as diagnostics, on the line and in the words that help most.

    An unexpected key is reported on its own line, once per key.  A
    derivation block the schema refuses is explained by the per-algorithm
    model ``from_spec()`` uses.  A key only ``fleet define-xml`` needs is a
    warning, because ``from_spec()`` runs without it.
    """
    from jsonschema.exceptions import best_match

    from fleet.introspect import check_derivation, get_algorithm

    error_path = tuple(error.absolute_path)

    def diagnostic(key_path: tuple[Any, ...], message: str, severity: str = "error") -> dict:
        return {"line": _locate(index, key_path), "message": message[:300], "severity": severity}

    if error.validator == "additionalProperties" and isinstance(error.instance, dict):
        allowed = set(error.schema.get("properties", {}))
        extra = [k for k in error.instance if k not in allowed]
        if extra:
            return [
                diagnostic(
                    (*error_path, key),
                    f"Additional properties are not allowed ('{key}' was unexpected)",
                )
                for key in extra
            ]

    if error.validator == "anyOf" and error_path == ():
        if isinstance(data.get("datasets"), list) and "study" not in data:
            return [
                diagnostic(
                    (), "'study' is a required property (needed by fleet define-xml)", "warning"
                )
            ]
        return [diagnostic((), "A spec needs datasets: with study:, or variables:")]

    if (
        error.validator == "anyOf"
        and error_path[-1:] == ("derivation",)
        and isinstance(error.instance, dict)
    ):
        variable = _at(data, error_path[:-1])
        algorithm = error.instance.get("algorithm")
        standard = next(
            (s for s in standards if isinstance(algorithm, str) and get_algorithm(s, algorithm)),
            None,
        )
        if standard is not None and isinstance(variable, dict):
            codelist = variable.get("codelist")
            problems = check_derivation(
                standard,
                error.instance,
                target=str(variable.get("name") or "VAR"),
                codelist=codelist if isinstance(codelist, str) else None,
            )
            if problems:
                return [
                    diagnostic(
                        (*error_path, p.key) if p.key in error.instance else error_path,
                        p.message,
                    )
                    for p in problems
                ]

    if error_path == ("fleet_spec_version",) and error.instance == 1:
        return [
            diagnostic(
                error_path,
                f"fleet_spec_version 1 is the pre-ADR-0008 vocabulary. {_MIGRATE_HINT}",
            )
        ]

    best = best_match([error]) or error
    best_path = tuple(best.absolute_path)
    message = best.message.splitlines()[0]
    if best.validator == "required" and _is_metadata_block(best_path):
        missing = re.match(r"'([^']+)' is a required property", message)
        if missing and (best_path == ("study",) or missing.group(1) not in _RUNTIME_REQUIRED):
            return [diagnostic(best_path, f"{message} (needed by fleet define-xml)", "warning")]
    return [diagnostic(best_path, message)]


def _at(data: Any, path: tuple[Any, ...]) -> Any:
    """The value at *path* in *data*, or ``None`` when the path does not exist."""
    for step in path:
        try:
            data = data[step]
        except (KeyError, IndexError, TypeError):
            return None
    return data


def _is_metadata_block(path: tuple[Any, ...]) -> bool:
    """True for the study block, a dataset entry or a variable entry."""
    shapes = (
        ("study",),
        ("datasets", int),
        ("datasets", int, "variables", int),
    )
    return any(
        len(path) == len(shape)
        and all(isinstance(p, s) if isinstance(s, type) else p == s for p, s in zip(path, shape))
        for shape in shapes
    )


_KEY_PREFIX_RE = re.compile(r"^\s*[\w-]*$")
_WORD_RE = re.compile(r"[A-Za-z0-9_.\-]+")

#: ``algorithm:`` as a plain key or as the opening key of a list entry
#: (``- algorithm: duration``), which both spec shapes allow; the value may
#: be quoted.
_ALGORITHM_RE = re.compile(r"^-?\s*algorithm:\s*[\"']?([\w.-]*)")

#: One block line: its indent, an optional list dash, and its key.
_BLOCK_LINE_RE = re.compile(r"^(\s*)(-\s+)?([\w-]+)\s*:")


def _enclosing_algorithm(lines: list[str], line: int, indent: int) -> tuple[str | None, set[str]]:
    """The ``algorithm:`` of the block the cursor is in, and the keys that block holds.

    The block is the run of keys at the cursor's indent, above and below
    it, bounded by a shallower line and by the list dash that opens an
    entry.  Deeper lines (the items of a ``when:`` list, the pairs of a
    ``ct_map``) belong to a key of the block and are skipped.  So a new
    entry that has not named an algorithm yet offers no parameters, rather
    than the previous entry's.
    """
    algorithm: str | None = None
    held: set[str] = set()

    def visit(i: int) -> str:
        """``"skip"``, ``"stop"``, ``"key"`` or ``"opener"`` for line *i*."""
        nonlocal algorithm
        text = lines[i]
        if not text.strip() or text.lstrip().startswith("#"):
            return "skip"
        match = _BLOCK_LINE_RE.match(text)
        if match is None:
            return "skip" if len(text) - len(text.lstrip()) > indent else "stop"
        column = len(match.group(1)) + len(match.group(2) or "")
        if column > indent:
            return "skip"
        if column < indent:
            return "stop"
        held.add(match.group(3))
        found = _ALGORITHM_RE.match(text.strip())
        if found:
            algorithm = found.group(1) or None
        return "opener" if match.group(2) else "key"

    for i in range(line - 1, -1, -1):
        kind = visit(i)
        if kind in ("stop", "opener"):
            break
    for i in range(line + 1, len(lines)):
        text = lines[i]
        match = _BLOCK_LINE_RE.match(text)
        if match and match.group(2) and len(match.group(1)) + len(match.group(2)) == indent:
            break  # the next entry of the same list
        if visit(i) == "stop":
            break
    return algorithm, held


def compute_completions(
    text: str, line: int, character: int, path: str = ""
) -> list[dict[str, Any]]:
    """Return completion candidates for a define.yaml cursor position.

    Completes ``algorithm:`` values (registry ids per inferred standard),
    parameter keys of the enclosing algorithm (required first, without the
    keys the block already holds), and codelist OIDs from the file's own
    ``codelists:`` section.  Right after a colon, an item carries an
    ``insert_text`` with a leading space, so the result is valid YAML.

    Args:
        text: Full document text.
        line: 0-based cursor line.
        character: 0-based cursor column, in characters of *text*.
        path: File path (standard-inference hint).

    Returns:
        list[dict]: ``{"label", "detail", "sort_text",
            "documentation", "insert_text"}`` entries (all but ``label``
            optional).

    Examples:
        Offer algorithm ids at an ``algorithm:`` key::

            from fleet.lsp_server import compute_completions

            items = compute_completions("derivation:\\n  algorithm: ", 1, 13)
            assert any(i["label"] == "assign" for i in items)
    """
    text = _client_text(text)
    items = _completions(text, line, character, path)
    lines = _lines(text)
    if line < len(lines) and lines[line][:character].endswith(":"):
        for item in items:
            item["insert_text"] = f" {item['label']}"
    return items


def _completions(text: str, line: int, character: int, path: str) -> list[dict[str, Any]]:
    from fleet import introspect

    lines = _lines(text)
    if line >= len(lines):
        return []
    prefix = lines[line][:character]
    stripped = prefix.strip()
    data = _safe_load(text)

    if _ALGORITHM_RE.match(stripped):
        seen: dict[str, dict[str, Any]] = {}
        for std in infer_standards(data, path):
            for algo in introspect.algorithms(std):
                seen.setdefault(
                    algo.name,
                    {
                        "label": algo.name,
                        "detail": std,
                        "documentation": algo.description,
                    },
                )
        return sorted(seen.values(), key=lambda i: i["label"])

    if re.match(r"^(-\s+)?(ct|codelist):", stripped):
        codelists = data.get("codelists")
        return [
            {"label": str(cl["oid"]), "detail": str(cl.get("name", ""))}
            for cl in (codelists if isinstance(codelists, list) else [])
            if isinstance(cl, dict) and cl.get("oid")
        ]

    if _KEY_PREFIX_RE.match(prefix):
        indent = len(prefix) - len(prefix.lstrip())
        algo_name, held = _enclosing_algorithm(lines, line, indent)
        if algo_name:
            for std in infer_standards(data, path):
                algo = introspect.get_algorithm(std, algo_name)
                if algo is None:
                    continue
                return [
                    {
                        "label": p.name,
                        "detail": ("required — " if p.required else "") + (p.description or ""),
                        "sort_text": f"{int(not p.required)}{i:02d}",
                    }
                    for i, p in enumerate(algo.params)
                    if p.name not in held
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

            md = compute_hover("derivation:\\n  algorithm: assign", 1, 15)
            assert "assign" in md
    """
    from fleet import introspect

    text = _client_text(text)
    lines = _lines(text)
    if line >= len(lines):
        return None
    word = _word_at(lines[line], character)
    if not word:
        return None
    data = _safe_load(text)

    if _ALGORITHM_RE.match(lines[line].strip()):
        for std in infer_standards(data, path):
            algo = introspect.get_algorithm(std, word)
            if algo is None:
                continue
            doc = introspect.algorithm_doc(algo.name, standard=std)
            summary = doc.summary if doc else ""
            parts = [f"**{algo.name}** ({std}) — {algo.description or summary or ''}".rstrip(" —")]
            if summary and summary != algo.description:
                parts.append(summary)
            if doc:
                parts.append(f"Verb: `{doc.verb_path}`")
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
            header = f"**{cl.get('name', word)}** (`{word}`)"
            if not items:
                return header
            terms = ", ".join(str(i.get("coded_value")) for i in items[:8])
            suffix = ", …" if len(items) > 8 else ""
            return f"{header}\n\nTerms: {terms}{suffix}"
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

    from fleet import __version__

    # Full sync: pygls splits an incremental edit on U+2028 as a line end,
    # which the client does not, and would corrupt the document.
    server = LanguageServer(
        "fleet-lsp", __version__, text_document_sync_kind=types.TextDocumentSyncKind.Full
    )

    def _to_lsp(doc: Any, diags: list[dict[str, Any]]) -> list[Any]:
        lines = _lines(_client_text(doc.source))
        out = []
        for d in diags:
            ln = min(d["line"], max(len(lines) - 1, 0))
            width = doc.position_codec.client_num_units(lines[ln]) if lines else 1
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

    def _position(doc: Any, position: Any) -> tuple[int, int]:
        """The client position as a line and a character index of the sanitised text."""
        lines = _lines(_client_text(doc.source))
        if position.line >= len(lines):
            return position.line, position.character
        server_position = doc.position_codec.position_from_client_units(lines, position)
        return server_position.line, server_position.character

    async def _validate(ls: LanguageServer, uri: str) -> None:
        doc = ls.workspace.get_text_document(uri)
        version = doc.version
        await asyncio.sleep(_DEBOUNCE_S)
        doc = ls.workspace.get_text_document(uri)
        if doc.version != version:
            return  # superseded by a newer edit, or closed
        diagnostics = (
            _to_lsp(doc, compute_diagnostics(doc.source, doc.path))
            if is_define_yaml(doc.path)
            else []
        )
        ls.text_document_publish_diagnostics(
            types.PublishDiagnosticsParams(
                uri=uri,
                version=doc.version,
                diagnostics=diagnostics,
            )
        )

    @server.feature(types.TEXT_DOCUMENT_DID_OPEN)
    async def did_open(ls: LanguageServer, params: types.DidOpenTextDocumentParams) -> None:
        await _validate(ls, params.text_document.uri)

    @server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
    async def did_change(ls: LanguageServer, params: types.DidChangeTextDocumentParams) -> None:
        await _validate(ls, params.text_document.uri)

    @server.feature(types.TEXT_DOCUMENT_DID_CLOSE)
    def did_close(ls: LanguageServer, params: types.DidCloseTextDocumentParams) -> None:
        ls.text_document_publish_diagnostics(
            types.PublishDiagnosticsParams(uri=params.text_document.uri, diagnostics=[])
        )

    @server.feature(
        types.TEXT_DOCUMENT_COMPLETION,
        types.CompletionOptions(trigger_characters=[" "]),
    )
    def completion(ls: LanguageServer, params: types.CompletionParams):
        doc = ls.workspace.get_text_document(params.text_document.uri)
        line, character = _position(doc, params.position)
        items = compute_completions(doc.source, line, character, doc.path)
        return [
            types.CompletionItem(
                label=item["label"],
                detail=item.get("detail"),
                sort_text=item.get("sort_text"),
                documentation=item.get("documentation"),
                insert_text=item.get("insert_text"),
                kind=types.CompletionItemKind.Value,
            )
            for item in items
        ]

    @server.feature(types.TEXT_DOCUMENT_HOVER)
    def hover(ls: LanguageServer, params: types.HoverParams):
        doc = ls.workspace.get_text_document(params.text_document.uri)
        line, character = _position(doc, params.position)
        markdown = compute_hover(doc.source, line, character, doc.path)
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
