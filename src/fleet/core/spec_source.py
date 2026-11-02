"""Static conversion between inline Fleet programs and ``define.yaml`` derivations.

Two directions, both driven by the spec registry, so a verb and its
algorithm cannot drift apart here:

* :func:`derivations_from_source` parses a program's AST and reverse-maps
  every namespace verb call to a ``derivation:`` block without running
  anything — the mapping ``to_spec_yaml()`` applies to runtime lineage,
  applied to literal arguments instead.
* :func:`program_from_spec` renders one dataset's spec as an inline pipeline
  skeleton, one chained call per derived variable.

Examples:
    Blocks from a program, without executing it::

        >>> rows = derivations_from_source('dm = raw.sdtm.assign("DOMAIN", value="DM")')
        >>> rows[0]["block"]
        {'algorithm': 'assign', 'value': 'DM'}
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from fleet.core.dag import VariableNode
from fleet.core.define_spec import load_spec_yaml
from fleet.core.lineage import UNSERIALISABLE
from fleet.core.spec_registry import (
    SPEC_UNSUPPORTED,
    derivation_from_lineage,
    get_algorithm,
    render_formal_expression,
    with_codelist,
)

_NAMESPACES = ("sdtm", "adam")
_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,7}$")
_NOT_PARAMS = ("algorithm", "depends_on")
#: Verbs whose first argument names a dataset, not a variable: pipeline plumbing.
_PLUMBING = frozenset({"pin"})


def derivations_from_source(source: str) -> list[dict[str, Any]]:
    """Reverse-map every namespace verb call in *source* to a derivation block.

    Static: the program is parsed, never run. A call counts when it hangs
    off ``.sdtm`` / ``.adam`` (through any chain, up to ``to_frame()``)
    and its first argument is a CDISC-named string literal — the target.
    Rows come back in call order.

    Args:
        source: Python source of a program (a whole file or a selection).

    Returns:
        list[dict]: One row per call with ``name``, ``verb``, ``standard``,
            ``line`` (1-based, of the verb), ``status``, ``block``,
            ``reason`` and ``meta`` (captured ``label``/``origin``).
            *status* is ``"ok"`` (``block`` usable), ``"stub"``
            (non-literal or unmatched arguments), ``"unsupported"`` (the
            verb has no spec form) or ``"unknown"`` (not a registered verb).
    """
    tree = ast.parse(source)
    imported = _imports(tree)
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    calls.sort(key=lambda call: (call.func.end_lineno or 0, call.func.end_col_offset or 0))
    rows: list[dict[str, Any]] = []
    for call in calls:
        verb = call.func.attr  # type: ignore[attr-defined]
        standard = _chain_standard(call.func.value)  # type: ignore[attr-defined]
        if standard is None or verb in _PLUMBING or not call.args:
            continue
        target = call.args[0]
        if isinstance(target, ast.Constant) and isinstance(target.value, str):
            if _NAME_RE.match(target.value):
                rows.append(_row(standard, call, target.value))
        elif verb == "derivation" and isinstance(target, ast.Name | ast.Attribute):
            rows.append(_callable_row(standard, call, target, imported, defined))
    return rows


def program_from_spec(spec_path: str | Path, dataset: str) -> str:
    """Render *dataset*'s ``define.yaml`` derivations as an inline pipeline skeleton.

    One chained call per variable carrying a ``derivation:`` block, in spec
    order, rendered by the registry (:func:`render_formal_expression`) so
    the call is the one ``from_spec`` would make. Inputs and pinned datasets
    become placeholder loads and ``.pin()`` calls to fill in.

    Args:
        spec_path: Path to the ``define.yaml``.
        dataset: Dataset name declared in it (e.g. ``"ADSL"``).

    Returns:
        str: A Python program to review, never run blind.

    Raises:
        ValueError: When *dataset* is not declared in the spec.
    """
    path = Path(spec_path)
    data = load_spec_yaml(path.read_text(encoding="utf-8")) or {}
    datasets = [ds for ds in data.get("datasets", []) if isinstance(ds, dict)]
    block = next(
        (ds for ds in datasets if str(ds.get("name", "")).upper() == dataset.upper()), None
    )
    if block is None:
        known = ", ".join(str(ds.get("name")) for ds in datasets)
        raise ValueError(f"dataset {dataset!r} not in {path}. Known: {known}")
    study = data.get("study") if isinstance(data.get("study"), dict) else {}
    standard = "adam" if "ADAM" in str(study.get("standard", "")).upper() else "sdtm"

    name = dataset.upper()
    var = name.lower()
    variables = [v for v in block.get("variables", []) if isinstance(v, dict)]
    inputs = [
        str(i["name"]) for i in block.get("inputs", []) if isinstance(i, dict) and i.get("name")
    ]
    pinned = [p for p in _pinned(standard, variables) if p not in inputs]
    frames = inputs + pinned

    module = str(data.get("derivations_module") or "")
    imports: list[str] = []
    chain: list[str] = []
    for variable in variables:
        derivation = variable.get("derivation")
        if not isinstance(derivation, dict) or "algorithm" not in derivation:
            continue
        algorithm = str(derivation["algorithm"])
        if derivation.get("callable"):
            chain.append(_callable_call(str(derivation["callable"]), module, imports))
            continue
        try:
            block = with_codelist(standard, derivation, variable.get("codelist"))
        except ValueError:
            block = dict(derivation)
        params = {k: v for k, v in block.items() if k not in _NOT_PARAMS}
        text = render_formal_expression(
            standard, algorithm, params, target=str(variable.get("name"))
        )
        if text is None:
            chain.append(
                f"    # {variable.get('name')}: algorithm {algorithm!r} is not registered"
                " — derive inline"
            )
        else:
            chain.append(f"    .{text[text.rfind('.', 0, text.index('(')) + 1 :]}")

    lines = [
        f"# {name}" + (f" — {block['label']}" if block.get("label") else ""),
        f"# Generated by Fleet from {path.name}: one call per derived variable, in spec order.",
        "# Review before use: carry-through variables and raw columns are not derived here.",
        "import fleet",
        "import polars as pl",
        *sorted(set(imports)),
        "",
        "# %%",
    ]
    for frame in frames:
        lines.append(
            f'{frame.lower()} = fleet.frame(pl.read_parquet("TODO/{frame.lower()}.parquet"))'
            "  # declared in the spec"
        )
    source = frames[0].lower() if frames else f"{var}_raw"
    if not frames:
        lines.append(
            f'{var}_raw = fleet.frame(pl.read_csv("TODO/{var}_raw.csv"))  # the raw source'
        )
    lines += ["", "# %%", f"{var} = (", f"    {source}.{standard}"]
    for pin in inputs[1:] + pinned:
        lines.append(f'    .pin("{pin}", {pin.lower()})')
    lines += [*chain, "    .to_frame()", ")", ""]
    return "\n".join(lines)


def _callable_call(ref: str, module: str, imports: list[str]) -> str:
    """``.derivation(NAME)`` for a ``callable:`` reference, imported the way ``from_spec`` resolves it."""
    package, _, name = ref.rpartition(".")
    package = package or module
    if package:
        imports.append(f"from {package} import {name}")
        return f"    .derivation({name})"
    return f"    .derivation({name})  # TODO: import {name} from the study's derivations module"


def _imports(tree: ast.AST) -> dict[str, str]:
    """Local name → dotted path, from the program's own import statements."""
    names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                names[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.partition(".")[0]
                names[alias.asname or root] = alias.name if alias.asname else root
    return names


def _callable_row(
    standard: str,
    call: ast.Call,
    target: ast.Name | ast.Attribute,
    imported: dict[str, str],
    defined: set[str],
) -> dict[str, Any]:
    """A ``Derivation`` object dispatched bare — ``.derivation(AGEGR1)`` — as a ``callable:`` block.

    The reference is the dotted path the program itself imports it from,
    or the registered short name. The stanza takes the object's name, which
    Fleet's bare ``@derivation`` form makes the target; an object named
    outside the CDISC pattern (``add_pop_flags``) may produce several
    targets, so it is reported instead of guessed.
    """
    dotted = ast.unparse(target)
    root, _, rest = dotted.partition(".")
    if root in imported:
        dotted = imported[root] + (f".{rest}" if rest else "")
    name = dotted.rpartition(".")[2]
    row: dict[str, Any] = {
        "name": name,
        "verb": "derivation",
        "standard": standard,
        "line": call.func.end_lineno,
        "status": "stub",
        "block": None,
        "reason": "",
        "meta": {},
    }
    if not _NAME_RE.match(name):
        row["reason"] = (
            "a study-specific derivation whose targets are only known at runtime; "
            "run the pipeline and freeze it with to_spec_yaml()"
        )
    elif "." not in dotted and name in defined:
        row["reason"] = (
            "a study-specific derivation defined in this file; move it to the "
            "derivations package (fleet derivation add) so the spec can reference it"
        )
    else:
        row.update(status="ok", block={"algorithm": "derivation", "callable": dotted})
    return row


def _chain_standard(node: ast.expr) -> str | None:
    """The namespace a call chain hangs off (``raw.sdtm.…`` → ``"sdtm"``), if any.

    Walks receivers inward through attributes and calls; ``to_frame()`` ends
    the namespace, so frame methods after it are not verbs.
    """
    while True:
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "to_frame":
                return None
            node = node.func
        elif isinstance(node, ast.Attribute):
            if node.attr in _NAMESPACES:
                return node.attr
            node = node.value
        else:
            return None


def _row(standard: str, call: ast.Call, target: str) -> dict[str, Any]:
    verb = call.func.attr  # type: ignore[attr-defined]
    row: dict[str, Any] = {
        "name": target,
        "verb": verb,
        "standard": standard,
        "line": call.func.end_lineno,
        "status": "stub",
        "block": None,
        "reason": "",
        "meta": {},
    }
    if len(call.args) > 1:
        row["reason"] = "positional arguments besides the target"
        return row
    params: dict[str, Any] = {"target": target}
    for keyword in call.keywords:
        if keyword.arg is None:
            row["reason"] = "**kwargs expansion"
            return row
        try:
            params[keyword.arg] = ast.literal_eval(keyword.value)
        except ValueError:
            params[keyword.arg] = UNSERIALISABLE
    node = VariableNode(name=target, verb=verb, sources=[], method="", params=params)
    status, block, meta = derivation_from_lineage(standard, node)
    row["meta"] = meta
    if status == "ok":
        row.update(status="ok", block=block)
    elif verb in SPEC_UNSUPPORTED[standard]:
        row.update(status="unsupported", reason="the verb has no spec form")
    elif get_algorithm(standard, verb) is None:
        row.update(status="unknown", reason="not a spec-executable verb")
    elif any(value is UNSERIALISABLE for value in params.values()):
        row["reason"] = "an argument is not a literal (expression, callable or variable)"
    else:
        row["reason"] = "the arguments match no spec algorithm"
    return row


def _pinned(standard: str, variables: list[dict[str, Any]]) -> list[str]:
    """Datasets the spec's derivations resolve through a pin, in first-use order."""
    pinned: list[str] = []
    for variable in variables:
        derivation = variable.get("derivation")
        if not isinstance(derivation, dict):
            continue
        algo = get_algorithm(standard, str(derivation.get("algorithm", "")))
        for param in algo.params if algo else ():
            value = derivation.get(param.name)
            if param.convert == "pin" and isinstance(value, str) and value not in pinned:
                pinned.append(value)
    return pinned
