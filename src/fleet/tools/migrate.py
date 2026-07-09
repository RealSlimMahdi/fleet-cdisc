"""Rewrite old Fleet verb/kwarg spellings to their canonical forms.

The old spellings no longer exist at runtime — they were removed outright
(pre-alpha rename, no deprecation window).  This codemod remains so that
external scripts written against the old names can be rewritten in one go.

Usage (standalone)::

    python -m fleet.tools.migrate path/to/pipeline.py            # print diff
    python -m fleet.tools.migrate src/study01/ --write           # rewrite in place

Programmatic API (used by the ``fleet migrate`` CLI subcommand)::

    from fleet.tools.migrate import migrate_source

    new_code, changes = migrate_source(old_code)

The rewriter is libcst-based (lossless: comments and formatting are
preserved).  libcst ships behind the ``migrate`` extra::

    uv pip install 'fleet-cdisc[migrate]'

What gets rewritten
-------------------
* Deprecated verbs → canonical verbs, including their kwargs:
  ``assign_no_ct``/``assign_ct``/``hardcode_no_ct``/``hardcode_ct``/
  ``dataset_level``/``assigned`` → ``assign``; ``rename(source=)`` and
  ``source(from_col=)`` → ``assign``; ``if_then_else``/``condderivation``
  → ``case_when``; ``lookup`` → ``merge``.
* Deprecated kwargs on kept verbs: ``groups=``/``by_vars=``/
  ``group_cols=``/``group_by=`` → ``by=``; ``target_cols=``/``keep_cols=``
  → ``keep=``.
* A leading positional list on ``merge``/``lookup`` (the legacy
  ``target_cols`` position) → a trailing ``keep=[...]`` keyword.

Renames are keyed on the *method name* of the call, so unrelated calls
(e.g. Polars' own ``df.rename({...})``, which has no ``source=`` kwarg)
are left untouched.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

_INSTALL_HINT = (
    "fleet.tools.migrate requires libcst, which is not installed. "
    "Install it with the 'migrate' extra: uv pip install 'fleet-cdisc[migrate]' "
    "(or: uv sync --extra migrate)."
)

#: Deprecated verb → canonical verb (plain method rename).
VERB_RENAMES: dict[str, str] = {
    "assign_no_ct": "assign",
    "assign_ct": "assign",
    "hardcode_no_ct": "assign",
    "hardcode_ct": "assign",
    "dataset_level": "assign",
    "assigned": "assign",
    "if_then_else": "case_when",
    "condderivation": "case_when",
    "lookup": "merge",
}

#: Deprecated verbs renamed only when a signature-identifying kwarg is
#: present (guards against unrelated methods of the same name, e.g.
#: Polars' ``DataFrame.rename``).
GUARDED_VERB_RENAMES: dict[str, tuple[str, str]] = {
    # old verb -> (guard kwarg that must be present, canonical verb)
    "rename": ("source", "assign"),
    "source": ("from_col", "assign"),
}

#: Per-verb kwarg renames applied together with the verb rename.
VERB_KWARG_RENAMES: dict[str, dict[str, str]] = {
    "assign_ct": {"ct_codelist": "ct", "ct_mapping": "ct_map"},
    "hardcode_ct": {"ct_codelist": "ct"},
    "if_then_else": {"else_value": "else_"},
    "condderivation": {"conditions": "when", "else_value": "else_"},
    "lookup": {"target_cols": "keep"},
    "source": {"from_col": "source"},
}

#: Kwarg-only renames on verbs that keep their name.
KWARG_RENAMES: dict[str, dict[str, str]] = {
    "flag": {"groups": "by"},
    "seq": {"groups": "by"},
    "baseline": {"groups": "by"},
    "first_date": {"groups": "by"},
    "last_date": {"groups": "by"},
    "count_events": {"groups": "by"},
    "best_overall_response": {"groups": "by"},
    "confirmed_response_flag": {"groups": "by"},
    "filter_pd": {"groups": "by"},
    "event_flag": {"groups": "by"},
    "derive_summary_records": {"by_vars": "by"},
    "derive_locf_records": {"by_vars": "by"},
    "derive_param": {"by_vars": "by"},
    "group_by": {"group_cols": "by"},
    "baseline_flag": {"group_by": "by"},
    "merge_adsl": {"keep_cols": "keep"},
    "merge": {"target_cols": "keep"},
}

#: Verbs whose legacy *leading positional list* argument becomes keep=.
POSITIONAL_LIST_TO_KEEP: frozenset[str] = frozenset({"merge", "lookup"})


def _require_libcst():
    try:
        import libcst
    except ImportError as err:  # pragma: no cover — depends on environment
        raise ImportError(_INSTALL_HINT) from err
    return libcst


def _build_transformer(cst, changes: list[str]):
    """Create the libcst transformer class bound to a change log."""

    class _FleetMigrator(cst.CSTTransformer):
        METADATA_DEPENDENCIES = ()

        def leave_Call(self, original_node, updated_node):
            func = updated_node.func
            if not isinstance(func, cst.Attribute):
                return updated_node
            name = func.attr.value

            new_verb: str | None = None
            kwarg_map: dict[str, str] = {}

            if name in VERB_RENAMES:
                new_verb = VERB_RENAMES[name]
                kwarg_map = dict(VERB_KWARG_RENAMES.get(name, {}))
            elif name in GUARDED_VERB_RENAMES:
                guard, target = GUARDED_VERB_RENAMES[name]
                if any(
                    a.keyword is not None and a.keyword.value == guard for a in updated_node.args
                ):
                    new_verb = target
                    kwarg_map = dict(VERB_KWARG_RENAMES.get(name, {}))
            elif name in KWARG_RENAMES:
                kwarg_map = dict(KWARG_RENAMES[name])

            if new_verb is None and not kwarg_map:
                return updated_node

            args = list(updated_node.args)
            changed = False
            moved_positional = False

            # Legacy leading positional list on merge/lookup → keep=
            if name in POSITIONAL_LIST_TO_KEEP and args:
                first = args[0]
                if first.keyword is None and isinstance(first.value, cst.List):
                    keep_arg = first.with_changes(
                        keyword=cst.Name("keep"),
                        equal=cst.AssignEqual(
                            whitespace_before=cst.SimpleWhitespace(""),
                            whitespace_after=cst.SimpleWhitespace(""),
                        ),
                    )
                    args = args[1:] + [keep_arg]
                    changed = moved_positional = True
                    changes.append(f".{name}([...]) positional column list -> keep=[...]")

            # Kwarg renames
            for i, arg in enumerate(args):
                if arg.keyword is None:
                    continue
                old_kw = arg.keyword.value
                if old_kw in kwarg_map:
                    args[i] = arg.with_changes(keyword=cst.Name(kwarg_map[old_kw]))
                    changed = True
                    changes.append(f".{name}({old_kw}=) -> {kwarg_map[old_kw]}=")

            new_func = func
            if new_verb is not None and new_verb != name:
                new_func = func.with_changes(attr=cst.Name(new_verb))
                changed = True
                changes.append(f".{name}() -> .{new_verb}()")

            if not changed:
                return updated_node
            if moved_positional and args:
                # Repair comma placement after moving keep= to the end.
                fixed_args = []
                for i, arg in enumerate(args):
                    if i < len(args) - 1 and not isinstance(arg.comma, cst.Comma):
                        arg = arg.with_changes(
                            comma=cst.Comma(whitespace_after=cst.SimpleWhitespace(" "))
                        )
                    elif i == len(args) - 1:
                        arg = arg.with_changes(comma=cst.MaybeSentinel.DEFAULT)
                    fixed_args.append(arg)
                args = fixed_args
            return updated_node.with_changes(func=new_func, args=args)

    return _FleetMigrator()


def migrate_source(code: str) -> tuple[str, list[str]]:
    """Rewrite deprecated Fleet spellings in *code* to canonical ones.

    Args:
        code: Python source text.

    Returns:
        tuple: ``(new_code, changes)`` where *changes* is one
            human-readable description per rewrite (empty when nothing
            changed — in that case ``new_code == code``).

    Raises:
        ImportError: When libcst is not installed (install the
            ``migrate`` extra).

    Examples:
        Rewrite a study script in memory::

            from fleet.tools.migrate import migrate_source

            new_code, changes = migrate_source(open("dm.py").read())
            for change in changes:
                print(change)
    """
    cst = _require_libcst()
    changes: list[str] = []
    module = cst.parse_module(code)
    new_module = module.visit(_build_transformer(cst, changes))
    return new_module.code, changes


def migrate_file(path: str | Path, *, write: bool = False) -> list[str]:
    """Migrate one file; optionally write the result back in place.

    Args:
        path: Path to a Python source file.
        write: When ``True``, overwrite the file with the migrated code;
            otherwise the file is left untouched.

    Returns:
        list[str]: The change descriptions (empty when nothing changed).
    """
    p = Path(path)
    original = p.read_text(encoding="utf-8")
    new_code, changes = migrate_source(original)
    if changes and write:
        p.write_text(new_code, encoding="utf-8")
    return changes


def _iter_python_files(paths: Sequence[str]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            files.extend(sorted(p.rglob("*.py")))
        else:
            files.append(p)
    return files


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point: migrate files, printing a diff or writing in place.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).  Recognised
            arguments: one or more file/directory paths and ``--write``.

    Returns:
        int: Process exit code — ``0`` on success (including "nothing to
            do"), ``1`` when libcst is missing or a file cannot be parsed.
    """
    parser = argparse.ArgumentParser(
        prog="python -m fleet.tools.migrate",
        description="Rewrite deprecated Fleet verb/kwarg spellings to canonical ones.",
    )
    parser.add_argument("files", nargs="+", help="Python files or directories to migrate.")
    parser.add_argument(
        "--write",
        action="store_true",
        help="Rewrite files in place (default: print a unified diff).",
    )
    args = parser.parse_args(argv)

    try:
        _require_libcst()
    except ImportError as err:
        print(str(err), file=sys.stderr)
        return 1

    exit_code = 0
    total_changes = 0
    for path in _iter_python_files(args.files):
        try:
            original = path.read_text(encoding="utf-8")
            new_code, changes = migrate_source(original)
        except ImportError:
            raise
        except Exception as err:  # parse errors etc. — report and continue
            print(f"{path}: failed to migrate: {err}", file=sys.stderr)
            exit_code = 1
            continue
        if not changes:
            continue
        total_changes += len(changes)
        if args.write:
            path.write_text(new_code, encoding="utf-8")
            print(f"{path}: {len(changes)} change(s) written")
        else:
            diff = difflib.unified_diff(
                original.splitlines(keepends=True),
                new_code.splitlines(keepends=True),
                fromfile=str(path),
                tofile=f"{path} (migrated)",
            )
            sys.stdout.writelines(diff)
        for change in changes:
            print(f"  {change}", file=sys.stderr)
    if total_changes == 0:
        print("Nothing to migrate.", file=sys.stderr)
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
