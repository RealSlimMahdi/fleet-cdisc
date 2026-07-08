"""Registry-driven TLG backbone tests (review round, points 7–8).

The template registry is the manifest: every entry must resolve to a
working namespace method, run on the frozen fixture study in default-by,
custom-by (TRT01P) and pooled-Total configurations, and — for tables —
match its checked-in golden ARD (regenerate with
``uv run python scripts/regen_tlg_goldens.py`` after an intentional
change, and review the CSV diff like a statistician).
"""

from __future__ import annotations

import sys
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

import fleet  # noqa: F401 — registers df.tlg
from fleet.tlg import TEMPLATES, GroupPool, catalog
from fleet.tlg._ard import ARD_SCHEMA, validate_ard
from fleet.tlg._registry import OutputType, Status

sys.path.insert(0, str(Path(__file__).parent.parent))
from fixtures.study import ADSL, FRAMES  # noqa: E402

GOLDEN_DIR = Path(__file__).parent.parent / "fixtures" / "goldens" / "tlg"

#: t_abnormal computes per-cell denominators domain-side and refuses
#: pools until the engine grows per-cell denominator support.
NO_POOLS = {"lbt04"}


def _frame_for(meta) -> pl.DataFrame:
    return FRAMES[meta.domains[-1]]


def _normalize(ard: pl.DataFrame) -> pl.DataFrame:
    """CSV round-trips cannot distinguish null from empty strings."""
    return ard.with_columns(
        pl.col(c).fill_null("") for c, dt in ard.schema.items() if dt == pl.Utf8
    )


@pytest.mark.parametrize("meta", TEMPLATES.values(), ids=lambda m: m.id)
def test_done_template_resolves_and_runs(meta) -> None:
    """Every DONE entry maps to a real method producing a valid output."""
    assert meta.status is Status.DONE
    ns = getattr(_frame_for(meta).tlg, meta.namespace)
    method = getattr(ns, meta.method)

    if meta.output_type is OutputType.LISTING:
        out = method()
        assert isinstance(out, pl.DataFrame)
        return

    for by in ("TRTA", "TRT01P"):
        ard = method(groupby=by, adsl=ADSL)
        assert validate_ard(ard) == [], f"{meta.id} invalid with by={by}"
        n_rows = ard.filter(pl.col("stat_name") == "N")
        assert set(n_rows["group1_level"].to_list()) == {"Placebo", "Drug A", "Drug B"}


@pytest.mark.parametrize(
    "meta",
    [m for m in TEMPLATES.values() if m.output_type is OutputType.TABLE],
    ids=lambda m: m.id,
)
def test_table_supports_pooled_total(meta) -> None:
    ns = getattr(_frame_for(meta).tlg, meta.namespace)
    spec_cls = type(ns)._builder_specs.get(meta.method)
    assert spec_cls is not None, f"{meta.id}: method not registered for the builder"
    if meta.id in NO_POOLS:
        return
    spec = spec_cls(pools=[GroupPool(label="Total", arms="*")])
    ard = getattr(ns, meta.method)(groupby="TRTA", adsl=ADSL, spec=spec)
    assert validate_ard(ard) == []
    assert "Total" in ard["group1_level"].to_list()


@pytest.mark.parametrize(
    "meta",
    [m for m in TEMPLATES.values() if m.output_type is OutputType.TABLE],
    ids=lambda m: m.id,
)
def test_table_matches_golden(meta) -> None:
    """The default-by ARD equals the checked-in golden, cell for cell."""
    golden_path = GOLDEN_DIR / f"{meta.id}.csv"
    assert golden_path.exists(), (
        f"No golden for {meta.id} — run scripts/regen_tlg_goldens.py and review the new file."
    )
    ns = getattr(_frame_for(meta).tlg, meta.namespace)
    ard = getattr(ns, meta.method)(groupby="TRTA", adsl=ADSL)
    golden = pl.read_csv(
        golden_path, schema_overrides=ARD_SCHEMA, missing_utf8_is_empty_string=True
    )
    assert_frame_equal(_normalize(ard), _normalize(golden), check_exact=False, rel_tol=1e-9)


def test_catalog_is_complete() -> None:
    df = catalog()
    assert df.height == len(TEMPLATES)
    assert set(df["status"].to_list()) == {"done"}
    assert set(df.columns) >= {"id", "title", "namespace", "method", "status"}
