"""Regression tests for the TLG output findings (pagination, RTF, CLI, YAML)."""

from __future__ import annotations

from pathlib import Path

import polars as pl

import fleet  # noqa: F401
from fleet.tlg.ae_namespace import AESocPtSpec

_SRC = Path(__file__).resolve().parents[2] / "src" / "fleet"


def _adsl() -> pl.DataFrame:
    return pl.from_repr("""
┌─────────┬──────┬───────┐
│ USUBJID ┆ TRTA ┆ SAFFL │
│ ---     ┆ ---  ┆ ---   │
│ str     ┆ str  ┆ str   │
╞═════════╪══════╪═══════╡
│ S1      ┆ A    ┆ Y     │
│ S2      ┆ A    ┆ Y     │
└─────────┴──────┴───────┘
""")


def _adae() -> pl.DataFrame:
    return pl.from_repr("""
┌─────────┬──────┬──────────┬──────────┐
│ USUBJID ┆ TRTA ┆ AEBODSYS ┆ AEDECOD  │
│ ---     ┆ ---  ┆ ---      ┆ ---      │
│ str     ┆ str  ┆ str      ┆ str      │
╞═════════╪══════╪══════════╪══════════╡
│ S1      ┆ A    ┆ NERV     ┆ HEADACHE │
│ S2      ┆ A    ┆ null     ┆ null     │
└─────────┴──────┴──────────┴──────────┘
""")


# c1-464: an explicit uncoded=None survives the YAML round trip.


def test_uncoded_none_survives_the_yaml_round_trip() -> None:
    spec = AESocPtSpec(template="aet02", uncoded=None)
    text = spec.to_yaml()
    assert "uncoded: null" in text
    reloaded = AESocPtSpec.from_yaml(text)
    assert reloaded.uncoded is None
    adae, adsl = _adae(), _adsl()
    before = adae.tlg.ae.t_soc_pt(groupby="TRTA", adsl=adsl, spec=spec)
    after = adae.tlg.ae.t_soc_pt(groupby="TRTA", adsl=adsl, spec=reloaded)
    assert before.equals(after)


def test_builder_uncoded_none_writes_uncoded_null() -> None:
    spec = (
        _adae().tlg.ae.population(_adsl()).by("TRTA").template("aet02").uncoded(None).to_spec()
    )
    assert "uncoded: null" in spec.to_yaml()


def test_default_uncoded_rule_is_not_written_as_null() -> None:
    assert "uncoded: null" not in AESocPtSpec(template="aet02").to_yaml()


# c1-447: the ARD is not called "{cards}-compatible" (names differ).


def test_no_source_docstring_calls_the_ard_cards_compatible() -> None:
    hits = [
        str(p.relative_to(_SRC))
        for p in _SRC.rglob("*.py")
        if "{cards}-compatible" in p.read_text(encoding="utf-8")
    ]
    assert hits == []
