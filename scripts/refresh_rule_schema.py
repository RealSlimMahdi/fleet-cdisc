"""Refresh the bundled CDISC rule schema from an installed CORE engine.

The engine ships its rule schema as several files
(``resources/schema/rule/CORE-base.json``, ``Operator.json``,
``Rule_Type.json``, ...).  Fleet bundles them as one file,
``src/fleet/validation/schemas/cdisc_rule_schema.json``: each other file
becomes an entry of ``$defs`` and each file reference becomes a local one.

Usage::

    uv run python scripts/refresh_rule_schema.py            # print the difference
    uv run python scripts/refresh_rule_schema.py --write    # also write the bundle
    uv run python scripts/refresh_rule_schema.py --engine-dir /path/to/core
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from fleet.validation.engine import engine_path, engine_version

BUNDLE = Path(__file__).parent.parent / "src/fleet/validation/schemas/cdisc_rule_schema.json"
_DROPPED = ("$id", "$schema", "title", "description", "$comment")
_REF = re.compile(r"^(?P<file>[A-Za-z_-]+)\.json(?:#(?P<path>.*))?$")


def _local(ref: str, owner: str | None) -> str:
    """One ``$ref`` of the engine files, as a reference inside the bundle."""
    match = _REF.match(ref)
    if match:
        name, path = match["file"], match["path"] or ""
        if name == "CORE-base":
            return f"#{path}"
        return f"#/$defs/{name}{path}"
    if ref.startswith("#") and owner is not None:
        return f"#/$defs/{owner}{ref[1:]}"
    return ref


def _rewrite(node: Any, owner: str | None) -> Any:
    if isinstance(node, dict):
        return {
            k: _local(v, owner) if k == "$ref" and isinstance(v, str) else _rewrite(v, owner)
            for k, v in node.items()
        }
    if isinstance(node, list):
        return [_rewrite(v, owner) for v in node]
    return node


def build_bundle(rule_dir: Path, version: str) -> dict[str, Any]:
    """The one-file schema built from the engine's rule schema files."""

    def load(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8-sig"))

    bundle = _rewrite(load(rule_dir / "CORE-base.json"), None)
    bundle["$id"] = "https://cdisc.org/CORE-base-bundled.json"
    bundle["$comment"] = f"Bundled by scripts/refresh_rule_schema.py from CORE {version}."
    for path in sorted(rule_dir.glob("*.json")):
        if path.stem == "CORE-base":
            continue
        part = {k: v for k, v in load(path).items() if k not in _DROPPED}
        bundle["$defs"][path.stem] = _rewrite(part, path.stem)
    return bundle


def _names(schema: dict[str, Any], key: str) -> set[str]:
    """The ``const`` values of one ``$defs`` entry (the rule types, the operators)."""
    text = json.dumps(schema["$defs"].get(key, {}))
    return set(re.findall(r'"const": "([^"]+)"', text))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--engine-dir", type=Path, default=engine_path().parent)
    parser.add_argument("--write", action="store_true", help="Write the refreshed bundle.")
    args = parser.parse_args()

    rule_dir = args.engine_dir / "resources" / "schema" / "rule"
    if not rule_dir.is_dir():
        print(f"No rule schema at {rule_dir}. Run `fleet install-engine` first.", file=sys.stderr)
        return 1
    executable = args.engine_dir / engine_path().name
    version = engine_version(executable) if executable.is_file() else "unknown"
    new = build_bundle(rule_dir, version)
    old = json.loads(BUNDLE.read_text(encoding="utf-8"))

    for key in ("Rule_Type", "Operator"):
        added, removed = _names(new, key) - _names(old, key), _names(old, key) - _names(new, key)
        print(f"{key}: {len(added)} added, {len(removed)} removed")
        for name in sorted(added):
            print(f"  + {name}")
        for name in sorted(removed):
            print(f"  - {name}")
    if args.write:
        BUNDLE.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Wrote {BUNDLE} (CORE {version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
