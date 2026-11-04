"""Regression tests for the TLG output findings (pagination, RTF, CLI, YAML)."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

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
    spec = _adae().tlg.ae.population(_adsl()).by("TRTA").template("aet02").uncoded(None).to_spec()
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


# c1-302: fleet tlg export --population passes the filter to adsl_filter.


def _export(argv: list[str]) -> int:
    from fleet import cli

    try:
        cli.main(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def test_tlg_export_population_filters_the_big_n(tmp_path: Path) -> None:
    adsl = pl.from_repr("""
┌─────────┬──────┬───────┐
│ USUBJID ┆ TRTA ┆ SAFFL │
│ ---     ┆ ---  ┆ ---   │
│ str     ┆ str  ┆ str   │
╞═════════╪══════╪═══════╡
│ S1      ┆ A    ┆ Y     │
│ S2      ┆ A    ┆ Y     │
│ S3      ┆ A    ┆ N     │
└─────────┴──────┴───────┘
""")
    adae = _adae().filter(pl.col("AEBODSYS").is_not_null())
    adsl_path, adae_path = tmp_path / "adsl.csv", tmp_path / "adae.csv"
    adsl.write_csv(adsl_path)
    adae.write_csv(adae_path)
    base = ["tlg", "export", "--domain", "ae", "--data", str(adae_path), "--adsl", str(adsl_path)]

    all_out, saf_out = tmp_path / "all.html", tmp_path / "saf.html"
    assert _export([*base, "-o", str(all_out)]) == 0
    population = 'pl.col("SAFFL") == "Y"'
    assert _export([*base, "--population", population, "-o", str(saf_out)]) == 0

    assert "N=3" in all_out.read_text(encoding="utf-8")
    saf = saf_out.read_text(encoding="utf-8")
    assert "N=2" in saf
    assert "N=3" not in saf
    assert "Population:" in saf


def test_tlg_export_rejects_an_invalid_population(tmp_path: Path, capsys) -> None:
    adsl_path, adae_path = tmp_path / "adsl.csv", tmp_path / "adae.csv"
    _adsl().write_csv(adsl_path)
    _adae().write_csv(adae_path)
    code = _export(
        [
            "tlg",
            "export",
            "--domain",
            "ae",
            "--data",
            str(adae_path),
            "--adsl",
            str(adsl_path),
            "--population",
            "__import__('os')",
            "-o",
            str(tmp_path / "x.html"),
        ]
    )
    assert code == 1
    assert "--population" in capsys.readouterr().err


# c1-813: a wide listing PDF keeps every column on the page.

_AE_LISTING_ROW = {
    "USUBJID": "01-701-1015",
    "TRTA": "Xanomeline High Dose",
    "AEBODSYS": "GENERAL DISORDERS AND ADMINISTRATION SITE CONDITIONS",
    "AEDECOD": "APPLICATION SITE ERYTHEMA",
    "AETERM": "REDNESS AT APPLICATION SITE",
    "AESEV": "MODERATE",
    "AESER": "N",
    "AEREL": "PROBABLE",
    "AEACN": "DOSE NOT CHANGED",
    "AEOUT": "NOT RECOVERED/NOT RESOLVED",
    "ASTDT": "2014-01-03",
    "AENDT": "2014-01-20",
    "ASTDY": "2",
    "AENDY": "19",
    "TRTEMFL": "Y",
}


def test_wide_listing_pdf_keeps_every_column_on_the_page(tmp_path: Path, monkeypatch) -> None:
    weasyprint = pytest.importorskip("weasyprint")
    from fleet.tlg.render import RenderMetadata, listing_to_model, render_listing_pdf

    # Programmatic frame: one 15-column AE row, repeated.
    listing = pl.DataFrame([_AE_LISTING_ROW] * 3)
    model = listing_to_model(listing, RenderMetadata(title="Listing 16.2.7"))

    rendered = {}

    def keep_layout(self, target=None, **kwargs):
        rendered["doc"] = self.render()
        return rendered["doc"].write_pdf(target)

    monkeypatch.setattr(weasyprint.HTML, "write_pdf", keep_layout)
    render_listing_pdf(model, tmp_path / "ael01.pdf")

    def boxes(box):
        yield box
        for child in getattr(box, "children", None) or []:
            yield from boxes(child)

    page = rendered["doc"].pages[0]
    right_limit = page.width - 96 / 2.54  # 1 cm page margin, in CSS px
    text_right = max(
        b.position_x + b.width for b in boxes(page._page_box) if type(b).__name__ == "TextBox"
    )
    assert text_right <= right_limit + 0.5


# c1-470: the explorer default variant is the batch output, checked at load.

_AET01_INTERACTIVE = """\
template: aet01
adsl_filter: 'pl.col("SAFFL") == "Y"'
statistics: [n_subjects, n_pct]
interactive:
  groupby: {choices: [TRTA, TRT01A], default: TRTA}
  population:
    - {label: Safety, filter: 'pl.col("SAFFL")=="Y"', default: true}
    - {label: ITT, filter: 'pl.col("ITTFL") == "Y"'}
  dataset_filter:
    - {label: All AEs, filter: null, default: true}
    - {label: Serious only, filter: 'pl.col("AESER") == "Y"'}
  stats:
    - {label: "n (%)", statistics: [n_subjects, n_pct], default: true}
    - {label: "+ events", statistics: [n_subjects, n_pct, n_events]}
"""


def _overview_spec(text: str):
    import yaml

    from fleet.tlg.ae_namespace import AEOverviewSpec

    return AEOverviewSpec.model_validate(yaml.safe_load(text))


def test_axis_defaults_equal_to_the_spec_load() -> None:
    # The population default differs in white space only: same expression.
    assert _overview_spec(_AET01_INTERACTIVE).interactive is not None


@pytest.mark.parametrize(
    ("old", "new", "axis"),
    [
        (
            'adsl_filter: \'pl.col("SAFFL") == "Y"\'',
            'adsl_filter: \'pl.col("ITTFL") == "Y"\'',
            "population",
        ),
        ("statistics: [n_subjects, n_pct]\n", "statistics: [n_subjects]\n", "stats"),
        ("default: TRTA}", "default: TRT01A}", "groupby"),
        (
            "statistics: [n_subjects, n_pct]\n",
            'statistics: [n_subjects, n_pct]\ndataset_filter: \'pl.col("AESER") == "Y"\'\n',
            "dataset_filter",
        ),
    ],
)
def test_axis_default_that_differs_from_the_spec_raises(old: str, new: str, axis: str) -> None:
    from pydantic import ValidationError

    text = _AET01_INTERACTIVE.replace(old, new, 1)
    assert text != _AET01_INTERACTIVE
    with pytest.raises(ValidationError, match=f"interactive.{axis} default"):
        _overview_spec(text)


def test_a_saved_variant_loads_and_its_default_is_that_variant() -> None:
    from fleet.tlg import enumerate_variants, run_spec

    adsl = pl.from_repr("""
┌─────────┬──────┬────────┬───────┬───────┐
│ USUBJID ┆ TRTA ┆ TRT01A ┆ SAFFL ┆ ITTFL │
│ ---     ┆ ---  ┆ ---    ┆ ---   ┆ ---   │
│ str     ┆ str  ┆ str    ┆ str   ┆ str   │
╞═════════╪══════╪════════╪═══════╪═══════╡
│ S1      ┆ A    ┆ A      ┆ Y     ┆ Y     │
│ S2      ┆ A    ┆ A      ┆ Y     ┆ Y     │
│ S3      ┆ A    ┆ A      ┆ Y     ┆ Y     │
│ S4      ┆ A    ┆ A      ┆ N     ┆ Y     │
└─────────┴──────┴────────┴───────┴───────┘
""")
    adae = pl.from_repr("""
┌─────────┬──────┬────────┬───────┬──────────────────┬────────┐
│ USUBJID ┆ TRTA ┆ TRT01A ┆ AESER ┆ AEACN            ┆ AESDTH │
│ ---     ┆ ---  ┆ ---    ┆ ---   ┆ ---              ┆ ---    │
│ str     ┆ str  ┆ str    ┆ str   ┆ str              ┆ str    │
╞═════════╪══════╪════════╪═══════╪══════════════════╪════════╡
│ S1      ┆ A    ┆ A      ┆ Y     ┆ DOSE NOT CHANGED ┆ N      │
│ S2      ┆ A    ┆ A      ┆ N     ┆ DOSE NOT CHANGED ┆ N      │
└─────────┴──────┴────────┴───────┴──────────────────┴────────┘
""")
    base = _overview_spec(_AET01_INTERACTIVE)
    chosen = next(
        v
        for v in enumerate_variants(base)
        if v.axis_labels["dataset_filter"] == "Serious only"
        and v.axis_labels["population"] == "ITT"
        and v.axis_labels["stats"] == "n (%)"
        and v.axis_labels["groupby"] == "TRTA"
    )
    promoted = type(base).from_yaml(chosen.spec.to_yaml())
    v0 = enumerate_variants(promoted)[0]
    assert v0.is_default
    assert v0.axis_labels == chosen.axis_labels
    batch = run_spec(promoted, adae, adsl=adsl)
    assert batch.equals(run_spec(v0.spec, adae, adsl=adsl))
    assert batch.equals(run_spec(chosen.spec, adae, adsl=adsl))
