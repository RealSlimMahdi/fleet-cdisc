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
``to_html()``.  Review the diff before committing — every changed cell
is a changed published number.
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

#: Continuous templates whose rendered HTML is also pinned (C1 regression).
HTML_GOLDEN_IDS = ("vst01", "lbt01")


def main() -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for meta in TEMPLATES.values():
        if meta.output_type is not OutputType.TABLE:
            continue
        frame = FRAMES[meta.domains[-1]]
        ns = getattr(frame.tlg, meta.namespace)
        ard = getattr(ns, meta.method)(adsl=ADSL)
        path = GOLDEN_DIR / f"{meta.id}.parquet"
        ard.write_parquet(path)
        print(f"  {meta.id:8s} {ard.height:4d} rows -> {path.relative_to(ROOT)}")

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
