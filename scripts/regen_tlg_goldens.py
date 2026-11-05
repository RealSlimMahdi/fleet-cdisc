"""Regenerate the TLG golden ARDs (Parquet) from the frozen fixture study.

Usage::

    uv run python scripts/regen_tlg_goldens.py

Each DONE table template runs on tests/fixtures/study.py with the
default configuration (the template's default arm: TRTA, or TRT01A for
the ADSL templates; adsl=ADSL) and its ARD is written
to tests/fixtures/goldens/tlg/<id>.parquet.  Parquet preserves dtypes
and the null vs "" distinction that CSV flattens — both are semantically
load-bearing in an ARD.  The continuous templates vst01/lbt01 also get a
rendered HTML golden (<id>.html) through the inline builder's
``to_html()``.  Before it writes a Parquet golden, the script prints each
changed cell (template, row keys, column, old value, new value) and each
added or removed row, because git shows only "Binary files differ".  Read
that list before committing: every changed cell is a changed published
number.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "tests"))

import polars as pl  # noqa: E402
from fixtures.study import ADSL, FRAMES  # noqa: E402

import fleet  # noqa: F401, E402 — registers df.tlg
from fleet.tlg import TEMPLATES  # noqa: E402
from fleet.tlg._registry import OutputType  # noqa: E402

GOLDEN_DIR = ROOT / "tests" / "fixtures" / "goldens" / "tlg"

#: ARD columns that identify a row; every other shared column is a value.
KEY_COLUMNS = (
    "group1",
    "group1_level",
    "group2",
    "group2_level",
    "variable",
    "variable_level",
    "stat_name",
)

#: Continuous templates whose rendered HTML is also pinned (C1 regression).
HTML_GOLDEN_IDS = ("vst01", "lbt01")


def changed_cells(template_id: str, old: pl.DataFrame, new: pl.DataFrame) -> list[str]:
    """One line per changed cell, added row and removed row between two ARDs."""
    lines = [
        f"{template_id}: column {c} {'added' if c in new.columns else 'removed'}"
        for c in sorted(set(old.columns) ^ set(new.columns))
    ]
    keys = [c for c in KEY_COLUMNS if c in old.columns and c in new.columns]
    values = [c for c in new.columns if c in old.columns and c not in keys]
    # A repeated key pairs by position within its key group.
    on = [*keys, "_n"]

    def keyed(df: pl.DataFrame, side: str) -> pl.DataFrame:
        return df.select(*keys, *values).with_columns(
            pl.int_range(pl.len()).over(keys).alias("_n"), pl.lit(True).alias(side)
        )

    joined = keyed(old, "_old").join(
        keyed(new, "_new"), on=on, how="full", nulls_equal=True, coalesce=True, suffix="_new"
    )
    for row in joined.iter_rows(named=True):
        where = " ".join(f"{k}={row[k]}" for k in keys if row[k] not in (None, ""))
        if row["_new"] is None:
            lines.append(f"{template_id}: row removed: {where}")
        elif row["_old"] is None:
            lines.append(f"{template_id}: row added: {where}")
        else:
            lines.extend(
                f"{template_id}: {where}: {c}: {row[c]!r} -> {row[f'{c}_new']!r}"
                for c in values
                if row[c] != row[f"{c}_new"]
            )
    return lines


def main() -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for meta in TEMPLATES.values():
        if meta.output_type is not OutputType.TABLE:
            continue
        frame = FRAMES[meta.domains[-1]]
        ns = getattr(frame.tlg, meta.namespace)
        ard = getattr(ns, meta.method)(adsl=ADSL)
        path = GOLDEN_DIR / f"{meta.id}.parquet"
        changes = changed_cells(meta.id, pl.read_parquet(path), ard) if path.is_file() else []
        for line in changes:
            print(f"    {line}")
        ard.write_parquet(path)
        status = f"{len(changes)} change(s)" if path.is_file() else "new"
        print(f"  {meta.id:8s} {ard.height:4d} rows, {status} -> {path.relative_to(ROOT)}")

    for template_id in HTML_GOLDEN_IDS:
        meta = TEMPLATES[template_id]
        frame = FRAMES[meta.domains[-1]]
        ns = getattr(frame.tlg, meta.namespace)
        html = ns.population(ADSL).by("TRTA").template(template_id).to_html()
        path = GOLDEN_DIR / f"{template_id}.html"
        path.write_text(html, encoding="utf-8")
        print(f"  {template_id:8s} html      -> {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
