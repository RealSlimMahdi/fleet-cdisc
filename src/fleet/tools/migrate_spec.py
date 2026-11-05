"""Rewrite a define.yaml from the pre-alpha spec vocabulary to the verb vocabulary (ADR-0008).

Before ADR-0008 a ``derivation:`` block named a spec algorithm
(``assign_ct``, ``hardcode_no_ct``, ``if_then_else``) whose keys were
renamed verb keywords (``ct_codelist``, ``else_value``).  Since ADR-0008 the
``algorithm:`` value is the verb name and the keys are its keyword
arguments.  The old names no longer load; this module rewrites a spec in
one go, and the tables below are the frozen record of the old vocabulary,
independent of the registry.

Usage (standalone)::

    python -m fleet.tools.migrate_spec specs/define.yaml            # print diff
    python -m fleet.tools.migrate_spec specs/ --write               # rewrite in place

Programmatic API (used by the ``fleet migrate --spec`` CLI subcommand)::

    from fleet.tools.migrate_spec import migrate_spec_text

    new_text, changes = migrate_spec_text(old_text)

The rewriter works line by line, so comments and layout survive.  It
handles block-style ``derivation:`` mappings and the simplified
single-dataset format; a flow-style block (``derivation: {algorithm: ...}``)
is left as is and reported.

What gets rewritten
-------------------
* ``algorithm:`` values: the spec names become the verb names
  (:data:`ALGORITHM_RENAMES`).
* Keys of a block, per old algorithm (:data:`KEY_RENAMES`): ``ct_codelist``
  to ``ct``, ``ct_mapping`` to ``ct_map``, ``else_value`` to ``else``,
  ``groups`` to ``by``, the ``study_day`` dates to ``start`` and ``end``, and
  the legacy keys the registry used to accept (``join_on``, ``flag_where``),
  and the sort key of ``pick`` (``order``, also in each event) and of
  ``nodup`` (``sort_by``) to ``order_by``.
* ``ct:`` equal to the variable's ``codelist:`` is dropped: the id is written
  once and ``from_spec`` fills it in.
* Keys Fleet no longer reads are removed (:data:`REMOVED_KEYS`):
  ``depends_on`` did nothing, because every verb checks its own columns.
* ``fleet_spec_version`` becomes 2, inserted when absent.
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

#: The dialect this module writes.
SPEC_VERSION = 2

#: Old ``algorithm:`` value → verb name.
ALGORITHM_RENAMES: dict[str, str] = {
    "assign_no_ct": "assign",
    "assign_ct": "assign",
    "hardcode_ct": "assign",
    "hardcode_no_ct": "assign",
    "dataset_level": "assign",
    "source": "assign",
    "assigned": "assign",
    "rename": "assign",
    "assign_dtc": "date",
    "if_then_else": "case_when",
    "condderivation": "case_when",
    "lookup": "merge",
    "study_day": "duration",
    "callable": "derivation",
    "transform": "derivation",
    "count": "count_events",
    "mean_arterial_pressure": "map",
}

_GROUPS_TO_BY = {"groups": "by"}
_ADAM_DURATION_KEYS = {
    "analysis_date": "start",
    "reference_date": "end",
    "start_date": "start",
    "end_date": "end",
}

#: Old ``algorithm:`` value → {old key: new key}.  A key is renamed only
#: when the block does not already hold the new key.
KEY_RENAMES: dict[str, dict[str, str]] = {
    "assign_ct": {"ct_codelist": "ct", "ct_mapping": "ct_map"},
    "hardcode_ct": {"ct_codelist": "ct"},
    "date": {"input_format": "format"},
    "assign_dtc": {"input_format": "format"},
    "if_then_else": {"else_value": "else"},
    "condderivation": {"conditions": "when", "else_value": "else"},
    "merge": {"target_cols": "keep", "join_on": "on"},
    "lookup": {"target_cols": "keep", "join_on": "on"},
    "group_by": {"group_cols": "by"},
    "seq": dict(_GROUPS_TO_BY),
    "baseline": dict(_GROUPS_TO_BY),
    "flag": {
        **_GROUPS_TO_BY,
        "flag_order_by": "order_by",
        "flag_value_col": "value_col",
        "flag_where": "where",
    },
    "first_date": dict(_GROUPS_TO_BY),
    "last_date": dict(_GROUPS_TO_BY),
    "count_events": dict(_GROUPS_TO_BY),
    "count": dict(_GROUPS_TO_BY),
    "study_day": {"analysis_date": "end", "reference_date": "start"},
    "duration": {"source": "start", **_ADAM_DURATION_KEYS},
    "nrind": {"aval": "value"},
    "on_treatment": {"analysis_date": "adt", "reference_date": "trtsdt"},
    "ae_aerel": {"aerel_source": "source"},
    "callable": {"callable_ref": "callable"},
    # c1-136: one name for the sort key across verbs.
    "pick": {"order": "order_by"},
    "nodup": {"sort_by": "order_by"},
}

#: Old ``algorithm:`` value → {old key: new key} for the keys of each item of
#: its ``events:`` list (``pick``).
EVENT_KEY_RENAMES: dict[str, dict[str, str]] = {"pick": {"order": "order_by"}}


#: Keys of a ``derivation:`` block that Fleet no longer reads; the rewrite drops them.
REMOVED_KEYS: frozenset[str] = frozenset({"depends_on"})


def migrate_block(
    block: Mapping[str, Any], *, codelist: str | None = None
) -> tuple[dict[str, Any], list[str]]:
    """Rewrite one ``derivation:`` block to the verb vocabulary.

    Args:
        block: The block, with its ``algorithm`` (or a bare ``callable``).
        codelist: The ``codelist:`` of the variable; a ``ct`` equal to it
            is dropped.

    Returns:
        tuple: ``(new_block, changes)``; *changes* is empty when the block
            is already in the verb vocabulary.

    Examples:
        The DM.SEX block of ADR-0008::

            new, changes = migrate_block(
                {"algorithm": "assign_ct", "source": "sex", "ct_codelist": "C66731"},
                codelist="C66731",
            )
            assert new == {"algorithm": "assign", "source": "sex"}
    """
    old = block.get("algorithm")
    changes: list[str] = []
    renames = KEY_RENAMES.get(str(old), {}) if old is not None else {}
    new: dict[str, Any] = {}
    for key, value in block.items():
        if key in REMOVED_KEYS:
            changes.append(f"{key}: removed (Fleet no longer reads it)")
            continue
        target = renames.get(key, key)
        if target != key and target not in block:
            changes.append(f"{key}: -> {target}:")
            key = target
        new[key] = value
    event_renames = EVENT_KEY_RENAMES.get(str(old), {})
    if event_renames and isinstance(new.get("events"), list):
        events = []
        for event in new["events"]:
            if isinstance(event, Mapping):
                event = {
                    (
                        event_renames[k]
                        if k in event_renames and event_renames[k] not in event
                        else k
                    ): v
                    for k, v in event.items()
                }
            events.append(event)
        if events != new["events"]:
            changes.append("events: order: -> order_by:")
        new["events"] = events
    for key, target in renames.items():
        if key in block and target in block:
            changes.append(f"{key}: kept, {target}: is also given — resolve by hand")
    if old in ALGORITHM_RENAMES:
        new["algorithm"] = ALGORITHM_RENAMES[str(old)]
        changes.append(f"algorithm: {old} -> {new['algorithm']}")
    if codelist and new.get("ct") == codelist:
        del new["ct"]
        changes.append(f"ct: {codelist} dropped (the variable's codelist:)")
    return new, changes


#: The sentence a load error ends with when the spec uses the old vocabulary.
MIGRATE_HINT = (
    " This spec uses pre-ADR-0008 keys; rewrite the file with "
    "`fleet migrate --spec <define.yaml> --write`."
)


def _old_block(block: Any) -> bool:
    if not isinstance(block, Mapping):
        return False
    try:
        return bool(migrate_block(block)[1])
    except Exception:
        return False


def migrate_hint(spec: Any) -> str:
    """Return :data:`MIGRATE_HINT` when *spec* is in the pre-ADR-0008 vocabulary.

    Args:
        spec: A parsed define.yaml (full or simplified format) or one
            ``derivation:`` block.

    Returns:
        str: :data:`MIGRATE_HINT` when ``fleet_spec_version`` is 1 or a
            block would change under ``fleet migrate --spec``, else ``""``.

    Examples:
        An old key under an unchanged algorithm name::

            hint = migrate_hint({"algorithm": "seq", "groups": ["USUBJID"]})
            assert "fleet migrate --spec" in hint
    """
    if not isinstance(spec, Mapping):
        return ""
    if "algorithm" in spec or "callable" in spec:
        return MIGRATE_HINT if _old_block(spec) else ""
    if spec.get("fleet_spec_version") == 1:
        return MIGRATE_HINT
    blocks: list[Any] = list(spec.get("variables") or [])
    for dataset in spec.get("datasets") or []:
        if isinstance(dataset, Mapping):
            for var in dataset.get("variables") or []:
                if isinstance(var, Mapping):
                    blocks.append(var.get("derivation"))
    return MIGRATE_HINT if any(_old_block(b) for b in blocks) else ""


# --------------------------------------------------------------------- #
# Text rewriting                                                          #
# --------------------------------------------------------------------- #

_KEY_LINE = re.compile(r"^(\s*)(- )?([A-Za-z_][\w]*):(.*)$")
_ALGO_LINE = re.compile(r"""^(\s*)(- )?algorithm:\s*["']?([\w.]+)["']?(\s*#.*)?\s*$""")
_VERSION_LINE = re.compile(r"^fleet_spec_version:\s*\d+(\s*#.*)?\s*$")
_SCALAR = re.compile(r"""^\s*(?:"([^"]*)"|'([^']*)'|([^\s#]+))""")


def _key_of(line: str) -> tuple[int, str, str] | None:
    """``(effective indent, key, rest)`` of a mapping line, else ``None``."""
    m = _KEY_LINE.match(line.rstrip("\n"))
    if m is None:
        return None
    indent = len(m.group(1)) + (2 if m.group(2) else 0)
    return indent, m.group(3), m.group(4)


def _is_blank(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _scalar(rest: str) -> str | None:
    m = _SCALAR.match(rest)
    if m is None:
        return None
    return next(g for g in m.groups() if g is not None)


def _block_bounds(lines: list[str], at: int, indent: int) -> tuple[int, int]:
    """Lines ``[start, end)`` of the mapping that holds the key line *at*."""
    start = at
    while start > 0:
        prev = lines[start - 1]
        if _is_blank(prev):
            start -= 1
            continue
        key = _key_of(prev)
        eff = key[0] if key else _indent(prev)
        if eff < indent:
            break
        start -= 1
        if key and eff == indent and prev.lstrip().startswith("- "):
            break  # the `- key:` line opens this list item: the block starts here
    end = at + 1
    while end < len(lines):
        line = lines[end]
        if _is_blank(line):
            end += 1
            continue
        key = _key_of(line)
        eff = key[0] if key else _indent(line)
        if eff < indent or (key and key[0] == indent and line.lstrip().startswith("- ")):
            break
        end += 1
    return start, end


def _variable_codelist(lines: list[str], start: int, indent: int) -> str | None:
    """The ``codelist:`` of the variable entry that holds a block starting at *start*."""
    i = start - 1
    while i >= 0:
        line = lines[i]
        if not _is_blank(line):
            key = _key_of(line)
            if key is None:
                return None
            eff, name, rest = key
            if eff < indent - 2:
                return None
            if eff == indent - 2 and name == "codelist":
                return _scalar(rest)
            if line.lstrip().startswith("- ") and eff <= indent - 2:
                return None
        i -= 1
    return None


def migrate_spec_text(text: str, *, set_version: bool = True) -> tuple[str, list[str]]:
    """Rewrite a define.yaml document to the verb vocabulary.

    Args:
        text: The YAML text.
        set_version: Also write ``fleet_spec_version: 2`` (off for a
            fragment, such as a YAML block in the docs).

    Returns:
        tuple: ``(new_text, changes)``; one change per rewritten line, with
            its 1-based line number.
    """
    lines = text.splitlines(keepends=True)
    changes: list[str] = []
    out = list(lines)
    i = 0
    while i < len(lines):
        m = _ALGO_LINE.match(lines[i].rstrip("\n"))
        if m is None:
            i += 1
            continue
        indent = len(m.group(1)) + (2 if m.group(2) else 0)
        old = m.group(3)
        start, end = _block_bounds(lines, i, indent)
        renames = KEY_RENAMES.get(old, {})
        present = {
            _key_of(lines[j])[1]  # type: ignore[index]
            for j in range(start, end)
            if _key_of(lines[j]) and _key_of(lines[j])[0] == indent  # type: ignore[index]
        }
        codelist = _variable_codelist(lines, start, indent)
        event_renames = EVENT_KEY_RENAMES.get(old, {})
        for j in range(start, end):
            key = _key_of(lines[j])
            if key is not None and key[0] > indent and key[1] in event_renames:
                new_key = event_renames[key[1]]
                out[j] = re.sub(rf"\b{key[1]}:", f"{new_key}:", lines[j], count=1)
                changes.append(f"line {j + 1}: events {key[1]}: -> {new_key}:")
                continue
            if key is None or key[0] != indent:
                continue
            eff, name, rest = key
            if name in REMOVED_KEYS:
                out[j] = ""
                k = j + 1
                while k < end and lines[k].strip().startswith("-") and _indent(lines[k]) > indent:
                    out[k] = ""  # a block-style list under the removed key
                    k += 1
                changes.append(f"line {j + 1}: {name}: removed (Fleet no longer reads it)")
                continue
            if j == i and old in ALGORITHM_RENAMES:
                out[j] = re.sub(rf"\b{re.escape(old)}\b", ALGORITHM_RENAMES[old], lines[j], count=1)
                changes.append(f"line {j + 1}: algorithm: {old} -> {ALGORITHM_RENAMES[old]}")
                continue
            new_name = renames.get(name)
            if new_name and new_name in present:
                changes.append(
                    f"line {j + 1}: {name}: kept, {new_name}: is also given — resolve by hand"
                )
            elif new_name:
                out[j] = re.sub(rf"\b{name}:", f"{new_name}:", lines[j], count=1)
                changes.append(f"line {j + 1}: {name}: -> {new_name}:")
                name = new_name
            if name == "ct" and codelist and _scalar(rest) == codelist:
                out[j] = ""
                changes.append(f"line {j + 1}: ct: {codelist} dropped (the variable's codelist:)")
        i = end
    text_out = "".join(out)
    if set_version:
        text_out, version_change = _set_version(text_out)
        if version_change:
            changes.append(version_change)
    return text_out, changes


def _set_version(text: str) -> tuple[str, str | None]:
    """Write ``fleet_spec_version: 2``, inserted before the first top-level key when absent."""
    lines = text.splitlines(keepends=True)
    for j, line in enumerate(lines):
        if _VERSION_LINE.match(line.rstrip("\n")):
            if re.match(rf"^fleet_spec_version:\s*{SPEC_VERSION}\b", line):
                return text, None
            lines[j] = re.sub(r"\d+", str(SPEC_VERSION), line, count=1)
            return "".join(lines), f"line {j + 1}: fleet_spec_version -> {SPEC_VERSION}"
    top_keys = {_key_of(line)[1] for line in lines if _key_of(line) and _key_of(line)[0] == 0}  # type: ignore[index]
    if not top_keys & {"datasets", "variables"}:
        return text, None
    for j, line in enumerate(lines):
        if not _is_blank(line) and _key_of(line) and _key_of(line)[0] == 0:  # type: ignore[index]
            lines.insert(j, f"fleet_spec_version: {SPEC_VERSION}\n")
            return "".join(lines), f"line {j + 1}: fleet_spec_version: {SPEC_VERSION} added"
    return text, None


# --------------------------------------------------------------------- #
# Files and CLI                                                           #
# --------------------------------------------------------------------- #


def migrate_spec_file(path: str | Path, *, write: bool = False) -> list[str]:
    """Migrate one file; print a diff, or rewrite it in place with *write*."""
    p = Path(path)
    original = p.read_text(encoding="utf-8")
    new_text, changes = migrate_spec_text(original)
    if changes and write:
        p.write_text(new_text, encoding="utf-8")
    return changes


def _iter_yaml_files(paths: Sequence[str]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            files.extend(sorted(q for q in p.rglob("*.y*ml") if q.is_file()))
        else:
            files.append(p)
    return files


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point: migrate define.yaml files, printing a diff or writing in place.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``): one or more
            file/directory paths and ``--write``.

    Returns:
        int: ``0`` on success, ``1`` when a file cannot be read.
    """
    parser = argparse.ArgumentParser(
        prog="python -m fleet.tools.migrate_spec",
        description="Rewrite a define.yaml to the verb vocabulary of ADR-0008.",
    )
    parser.add_argument("files", nargs="+", help="define.yaml files or directories.")
    parser.add_argument(
        "--write", action="store_true", help="Rewrite files in place (default: print a diff)."
    )
    args = parser.parse_args(argv)

    exit_code = 0
    total = 0
    for path in _iter_yaml_files(args.files):
        try:
            original = path.read_text(encoding="utf-8")
        except OSError as err:
            print(f"{path}: {err}", file=sys.stderr)
            exit_code = 1
            continue
        new_text, changes = migrate_spec_text(original)
        if not changes:
            continue
        total += len(changes)
        if args.write:
            path.write_text(new_text, encoding="utf-8")
            print(f"{path}: {len(changes)} change(s) written")
        else:
            sys.stdout.writelines(
                difflib.unified_diff(
                    original.splitlines(keepends=True),
                    new_text.splitlines(keepends=True),
                    fromfile=str(path),
                    tofile=f"{path} (migrated)",
                )
            )
        for change in changes:
            print(f"  {change}", file=sys.stderr)
    if total == 0:
        print("Nothing to migrate.", file=sys.stderr)
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
