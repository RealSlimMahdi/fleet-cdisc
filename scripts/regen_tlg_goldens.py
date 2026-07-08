"""Regenerate the TLG golden ARD CSVs from the frozen fixture study.

Usage::

    uv run python scripts/regen_tlg_goldens.py

Each DONE table template runs on tests/fixtures/study.py with the
default configuration (groupby="TRTA", adsl=ADSL) and its ARD is written
to tests/fixtures/goldens/tlg/<id>.csv.  Review the diff before
committing — every changed cell is a changed published number.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from fixtures.study import ADSL, FRAMES  # noqa: E402

import fleet  # noqa: F401, E402 — registers df.tlg
from fleet.tlg import TEMPLATES  # noqa: E402
from fleet.tlg._registry import OutputType  # noqa: E402

GOLDEN_DIR = ROOT / "tests" / "fixtures" / "goldens" / "tlg"


def main() -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for meta in TEMPLATES.values():
        if meta.output_type is not OutputType.TABLE:
            continue
        frame = FRAMES[meta.domains[-1]]
        ns = getattr(frame.tlg, meta.namespace)
        ard = getattr(ns, meta.method)(groupby="TRTA", adsl=ADSL)
        path = GOLDEN_DIR / f"{meta.id}.csv"
        ard.write_csv(path)
        print(f"  {meta.id:8s} {ard.height:4d} rows -> {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
