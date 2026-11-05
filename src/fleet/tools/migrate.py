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
  ``assign_no_ct``/``assign_ct``/``hardcode_no_ct``/``hardcode_ct`` →
  ``assign``; ``dataset_level(value=)``/``assigned(value=)``,
  ``rename(source=)`` and ``source(from_col=)`` → ``assign``;
  ``if_then_else``/``condderivation`` → ``case_when``;
  ``lookup(dataset=)`` → ``merge``; ``assign_dtc(input_format=)`` →
  ``date(format=)``.
* Deprecated kwargs on kept verbs: ``groups=``/``by_vars=``/
  ``group_cols=``/``group_by=`` → ``by=``; ``target_cols=``/``keep_cols=``
  → ``keep=``.
* A leading positional argument on ``merge(dataset=)``/``lookup(dataset=)``
  (the legacy ``target_cols`` position) → ``keep=``, in place.

Renames are keyed on the *method name* of the call, and a name that other
libraries also use (``rename``, ``lookup``, ``merge``) needs the Fleet
keyword, so unrelated calls (Polars' ``df.rename({...})``,
``codecs.lookup(...)``, ``heapq.merge(...)``) are left untouched.  A call
that has no automatic rewrite (``remove_dup``) and an old verb name used
as a value (``fn = df.sdtm.assign_no_ct``) are reported, not rewritten.
"""

from __future__ import annotations

import argparse
import difflib
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

_INSTALL_HINT = (
    "fleet.tools.migrate requires libcst, which is not installed. "
    "Install it with the 'migrate' extra: uv add 'fleet-cdisc[migrate]'."
)

#: Deprecated verb → canonical verb (plain method rename).
VERB_RENAMES: dict[str, str] = {
    "assign_no_ct": "assign",
    "assign_ct": "assign",
    "hardcode_no_ct": "assign",
    "hardcode_ct": "assign",
    "if_then_else": "case_when",
    "condderivation": "case_when",
    "assign_dtc": "date",
}

#: Deprecated verbs renamed only when a signature-identifying kwarg is
#: present (guards against unrelated methods of the same name, e.g.
#: Polars' ``DataFrame.rename``).
GUARDED_VERB_RENAMES: dict[str, tuple[str, str]] = {
    # old verb -> (guard kwarg that must be present, canonical verb)
    "rename": ("source", "assign"),
    "source": ("from_col", "assign"),
    "lookup": ("dataset", "merge"),
    "assigned": ("value", "assign"),
    "dataset_level": ("value", "assign"),
}

#: Per-verb kwarg renames applied together with the verb rename.
VERB_KWARG_RENAMES: dict[str, dict[str, str]] = {
    "assign_ct": {"ct_codelist": "ct", "ct_mapping": "ct_map"},
    "hardcode_ct": {"ct_codelist": "ct"},
    "if_then_else": {"else_value": "else_"},
    "condderivation": {"conditions": "when", "else_value": "else_"},
    "lookup": {"target_cols": "keep"},
    "source": {"from_col": "source"},
    "assign_dtc": {"input_format": "format"},
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

#: Verbs whose legacy *leading positional* argument becomes keep= (with dataset= given).
POSITIONAL_LIST_TO_KEEP: frozenset[str] = frozenset({"merge", "lookup"})

#: Removed verbs with no automatic rewrite → the note printed for a call.
MANUAL_REWRITES: dict[str, str] = {
    "remove_dup": "use .nodup(subset=..., sort_by=..., keep=...) and choose the kept row",
}

#: Old verb names that only Fleet used: reported when used as a value, not called.
FLEET_ONLY_NAMES: frozenset[str] = frozenset(
    {
        "assign_no_ct",
        "assign_ct",
        "hardcode_no_ct",
        "hardcode_ct",
        "if_then_else",
        "condderivation",
        "assign_dtc",
        "dataset_level",
        "remove_dup",
    }
)

#: ``--write`` help of both migrate tools.
WRITE_HELP = (
    "Rewrite files in place (default: print a unified diff). No backup file is kept: "
    "commit the files to git first."
)

#: Folders that `fleet migrate` never walks into: caches, installed packages, tool state.
_SKIP_DIRS = frozenset({"__pycache__", "site-packages", "node_modules"})


def iter_source_files(paths: Sequence[str], suffixes: tuple[str, ...]) -> list[Path]:
    """The files under *paths* with one of *suffixes*; a named file is always kept.

    A directory walk skips hidden folders (``.venv``, ``.git``), caches,
    ``site-packages`` and each folder that holds a ``pyvenv.cfg``.
    """
    files: list[Path] = []
    for raw in paths:
        root = Path(raw)
        if not root.is_dir():
            files.append(root)
            continue
        found: list[Path] = []
        for folder, dirs, names in os.walk(root):
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".")
                and d not in _SKIP_DIRS
                and not (Path(folder) / d / "pyvenv.cfg").is_file()
            ]
            found.extend(Path(folder) / n for n in names if n.endswith(suffixes))
        files.extend(sorted(found))
    return files


def _require_libcst():
    try:
        import libcst
    except ImportError as err:  # pragma: no cover — depends on environment
        raise ImportError(_INSTALL_HINT) from err
    return libcst


def _build_transformer(cst, changes: list[str], notes: list[str]):
    """Create the libcst transformer class bound to a change log and a note log."""
    from libcst.metadata import PositionProvider

    class _FleetMigrator(cst.CSTTransformer):
        METADATA_DEPENDENCIES = (PositionProvider,)

        def __init__(self) -> None:
            super().__init__()
            self._called: set[int] = set()

        def _line(self, node) -> int:
            return self.get_metadata(PositionProvider, node).start.line

        def visit_Call(self, node) -> bool:
            self._called.add(id(node.func))
            return True

        def leave_Attribute(self, original_node, updated_node):
            name = original_node.attr.value
            if name in FLEET_ONLY_NAMES and id(original_node) not in self._called:
                notes.append(f"line {self._line(original_node)}: .{name} is used as a value")
            return updated_node

        def leave_Call(self, original_node, updated_node):
            func = updated_node.func
            if not isinstance(func, cst.Attribute):
                return updated_node
            name = func.attr.value
            keywords = {a.keyword.value for a in updated_node.args if a.keyword is not None}

            if name in MANUAL_REWRITES:
                notes.append(
                    f"line {self._line(original_node)}: .{name}(): {MANUAL_REWRITES[name]}"
                )
                return updated_node

            new_verb: str | None = None
            kwarg_map: dict[str, str] = {}

            if name in VERB_RENAMES:
                new_verb = VERB_RENAMES[name]
                kwarg_map = dict(VERB_KWARG_RENAMES.get(name, {}))
            elif name in GUARDED_VERB_RENAMES:
                guard, target = GUARDED_VERB_RENAMES[name]
                if guard in keywords:
                    new_verb = target
                    kwarg_map = dict(VERB_KWARG_RENAMES.get(name, {}))
            elif name in KWARG_RENAMES:
                kwarg_map = dict(KWARG_RENAMES[name])

            if new_verb is None and not kwarg_map:
                return updated_node

            args = list(updated_node.args)
            changed = False

            # Legacy leading positional column list on merge/lookup -> keep=, in place,
            # so its comma and comment stay.  Only a Fleet call (dataset= given) with
            # no other positional argument: a keyword may not precede a positional one.
            if (
                name in POSITIONAL_LIST_TO_KEEP
                and args
                and "dataset" in keywords
                and not keywords & {"keep", "target_cols"}
                and args[0].keyword is None
                and not args[0].star
                and not any(a.keyword is None and a.star != "**" for a in args[1:])
            ):
                args[0] = args[0].with_changes(
                    keyword=cst.Name("keep"),
                    equal=cst.AssignEqual(
                        whitespace_before=cst.SimpleWhitespace(""),
                        whitespace_after=cst.SimpleWhitespace(""),
                    ),
                )
                changed = True
                changes.append(f".{name}() leading positional column list -> keep=")

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
            return updated_node.with_changes(func=new_func, args=args)

    return _FleetMigrator()


def migrate_source(code: str, *, notes: list[str] | None = None) -> tuple[str, list[str]]:
    """Rewrite deprecated Fleet spellings in *code* to canonical ones.

    Args:
        code: Python source text.
        notes: When given, receives one line per old spelling that has no
            automatic rewrite (``remove_dup``, an old verb name used as a
            value).  The code at those places is left as is.

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

            notes = []
            new_code, changes = migrate_source(open("dm.py").read(), notes=notes)
            for change in changes + notes:
                print(change)
    """
    cst = _require_libcst()
    changes: list[str] = []
    found: list[str] = []
    wrapper = cst.metadata.MetadataWrapper(cst.parse_module(code))
    new_module = wrapper.visit(_build_transformer(cst, changes, found))
    if notes is not None:
        notes.extend(found)
    return new_module.code, changes


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point: migrate files, printing a diff or writing in place.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).  Recognised
            arguments: one or more file/directory paths and ``--write``.

    Returns:
        int: Process exit code: ``0`` on success (including "nothing to
            do"); ``1`` when libcst is missing, a file cannot be read,
            parsed or written, or a place needs a rewrite by hand.  The
            other files are still migrated.
    """
    parser = argparse.ArgumentParser(
        prog="python -m fleet.tools.migrate",
        description="Rewrite deprecated Fleet verb/kwarg spellings to canonical ones.",
    )
    parser.add_argument("files", nargs="+", help="Python files or directories to migrate.")
    parser.add_argument(
        "--write",
        action="store_true",
        help=WRITE_HELP,
    )
    args = parser.parse_args(argv)

    try:
        _require_libcst()
    except ImportError as err:
        print(str(err), file=sys.stderr)
        return 1

    exit_code = 0
    total_changes = 0
    for path in iter_source_files(args.files, (".py",)):
        try:
            with open(path, encoding="utf-8", newline="") as fh:
                original = fh.read()
        except (OSError, UnicodeError) as err:
            print(f"{path}: cannot read: {err}", file=sys.stderr)
            exit_code = 1
            continue
        notes: list[str] = []
        try:
            new_code, changes = migrate_source(original, notes=notes)
        except ImportError:
            raise
        except Exception as err:  # parse errors etc. — report and continue
            print(f"{path}: failed to migrate: {err}", file=sys.stderr)
            exit_code = 1
            continue
        for note in notes:
            print(f"{path}: left as is, rewrite by hand: {note}", file=sys.stderr)
            exit_code = 1
        if not changes:
            continue
        if args.write:
            try:
                with open(path, "w", encoding="utf-8", newline="") as fh:
                    fh.write(new_code)
            except OSError as err:
                print(f"{path}: cannot write: {err}", file=sys.stderr)
                exit_code = 1
                continue
            print(f"{path}: {len(changes)} change(s) written")
        else:
            diff = difflib.unified_diff(
                original.splitlines(keepends=True),
                new_code.splitlines(keepends=True),
                fromfile=str(path),
                tofile=f"{path} (migrated)",
            )
            sys.stdout.writelines(diff)
        total_changes += len(changes)
        for change in changes:
            print(f"  {change}", file=sys.stderr)
    if total_changes == 0 and exit_code == 0:
        print("Nothing to migrate.", file=sys.stderr)
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
