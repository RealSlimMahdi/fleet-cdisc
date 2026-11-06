"""Regression tests for the TLG output findings (pagination, RTF, CLI, YAML)."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

import fleet  # noqa: F401
from fleet.tlg.ae_namespace import AESocPtSpec
from fleet.tlg.render import RenderMetadata

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


# The t_summary example runs on an ADSL that holds the arm as TRT01A only.


def test_the_t_summary_docstring_example_runs_on_an_adsl_with_trt01a() -> None:
    import textwrap

    from fleet.tlg import AESummarySpec
    from fleet.tlg.ae_namespace import AETLGNamespace

    doc = AETLGNamespace.t_summary.__doc__ or ""
    block = doc.split("ADSL arm in TRT01A::\n\n")[1].split("\n\n")[0]
    adsl = _adsl().rename({"TRTA": "TRT01A"})
    scope = {"adae": _adae(), "adsl": adsl, "AESummarySpec": AESummarySpec}

    exec(textwrap.dedent(block), scope)

    assert scope["ard"].height > 0


def test_no_tlg_docstring_groups_by_trta_on_the_adsl() -> None:
    hits = [
        str(p.relative_to(_SRC))
        for p in (_SRC / "tlg").rglob("*.py")
        if 'groupby="TRTA", adsl=adsl' in p.read_text(encoding="utf-8")
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


# c1-456: a page that starts inside a block repeats its parents.


def _lbt01_model():
    """Programmatic LBT01 layout: parameter, visit, six statistic rows."""
    from fleet.tlg.render._models import ColumnHeader, TableModel, TableRow

    stats = ["n", "Mean", "SD", "Median", "Min", "Max"]
    rows = []
    for param in ["ALT", "AST"]:
        rows.append(TableRow(param, "group", 0, {"A": ""}, True, "PARAMCD"))
        for visit in ["Baseline", "Week 2", "Week 4", "Week 8"]:
            rows.append(TableRow(visit, "data", 1, {"A": ""}, False, "AVISIT"))
            rows += [TableRow(s, "stat", 2, {"A": "1.0"}, False, "AVISIT") for s in stats]
    return TableModel(
        metadata=RenderMetadata(title="Table 14.3.4.1"),
        columns=[ColumnHeader(label="A", big_n=4)],
        rows=rows,
    )


def _aet02_model(n_soc: int = 3, n_pt: int = 23, label: str = "PT"):
    """Programmatic AET02 layout: SOC rows and PT rows, all with counts."""
    from fleet.tlg.render._models import ColumnHeader, TableModel, TableRow

    rows = []
    for s in range(n_soc):
        rows.append(TableRow(f"SOC {s}", "group", 0, {"Placebo": "5 (50.0%)"}, True, "AEBODSYS"))
        rows += [
            TableRow(f"{label} {s}-{p}", "data", 1, {"Placebo": "1 (10.0%)"}, False, "AEDECOD")
            for p in range(n_pt)
        ]
    return TableModel(
        metadata=RenderMetadata(
            title="Table 14.3.1.2",
            subtitle="Safety population",
            footnotes=["MedDRA 26.0.", "Subjects counted once per SOC and PT."],
        ),
        columns=[ColumnHeader(label="Placebo", big_n=84)],
        rows=rows,
    )


def _real_rows(page):
    return [r for r in page.rows if not r.label.endswith(" (continued)")]


def _assert_parents_on_page(pages) -> None:
    for page in pages:
        seen: list = []
        for row in page.rows:
            if row.indent > 0:
                parents = [r for r in seen if r.indent < row.indent]
                assert parents, f"{row.label!r} has no parent on its page"
                assert parents[-1].indent == row.indent - 1
            seen.append(row)


def test_lbt01_pages_repeat_parameter_and_visit() -> None:
    from fleet.tlg.render import paginate

    model = _lbt01_model()
    pages = paginate(model, rows_per_page=12)
    _assert_parents_on_page(pages)
    assert not pages[0].rows[0].label.endswith("(continued)")
    assert pages[1].rows[0].label == "ALT (continued)"
    assert pages[1].rows[0].cells == {"A": ""}
    # Each statistic block stays whole on one page.
    for page in pages:
        assert sum(r.row_type == "stat" for r in page.rows) % 6 == 0
    # No row is lost or duplicated.
    assert [r for p in pages for r in _real_rows(p)] == model.rows


def test_aet02_pages_repeat_the_soc_with_empty_cells() -> None:
    from fleet.tlg.render import paginate

    pages = paginate(_aet02_model(), rows_per_page=40)
    _assert_parents_on_page(pages)
    first = pages[1].rows[0]
    assert first.label == "SOC 1 (continued)"
    assert first.cells == {"Placebo": ""}


def test_no_continued_row_on_the_first_page_of_a_page_by_block() -> None:
    from fleet.tlg.render import paginate

    pages = paginate(_lbt01_model(), rows_per_page=40, page_by="PARAMCD")
    assert [p.rows[0].label for p in pages] == ["ALT", "AST"]


def test_a_stat_block_larger_than_the_page_is_split() -> None:
    from fleet.tlg.render import paginate

    model = _lbt01_model()
    pages = paginate(model, rows_per_page=4)
    assert [r for p in pages for r in _real_rows(p)] == model.rows
    _assert_parents_on_page(pages)


def test_render_pdf_paginates_by_default() -> None:
    import inspect

    from fleet.tlg.render import render_pdf, render_rtf

    pdf_default = inspect.signature(render_pdf).parameters["rows_per_page"].default
    assert pdf_default == inspect.signature(render_rtf).parameters["rows_per_page"].default == 40


# c1-820: the RTF page counter is a field, and the page budget is in points.


def _groups(rtf: str) -> tuple[str, str, str]:
    """(header group, footer group, body) of a Fleet RTF document."""
    head_start = rtf.find(r"{\header ")
    foot_start = rtf.find(r"{\footer ")
    foot_end = rtf.index("}\n", rtf.index(r"\fldinst NUMPAGES}")) + 1
    header = rtf[head_start:foot_start] if head_start >= 0 else ""
    return header, rtf[foot_start:foot_end], rtf[foot_end:]


def test_rtf_default_puts_title_in_header_and_footnotes_in_footer() -> None:
    from fleet.tlg.render import render_rtf

    rtf = render_rtf(_aet02_model())
    header, footer, body = _groups(rtf)
    assert "Table 14.3.1.2" in header and "Safety population" in header
    assert "MedDRA 26.0." in footer
    assert r"{\field{\*\fldinst PAGE}" in footer
    assert r"{\field{\*\fldinst NUMPAGES}" in footer
    assert "Table 14.3.1.2" not in body and "MedDRA" not in body
    assert "Page 1 of" not in rtf


def test_rtf_body_title_repeats_title_and_footnotes_per_page() -> None:
    from fleet.tlg.render import render_rtf

    rtf = render_rtf(_aet02_model(), body_title=True)
    header, footer, body = _groups(rtf)
    n_pages = rtf.count(r"\trhdr")
    assert header == ""
    assert r"\fldinst PAGE}" in footer and "MedDRA" not in footer
    assert body.count("Table 14.3.1.2") == n_pages
    assert body.count("MedDRA 26.0.") == n_pages


def test_rtf_page_budget_counts_title_footnotes_and_wrapped_rows() -> None:
    from fleet.tlg.render import render_rtf

    # 72 single-line rows: 40-row cap with title and footnotes in the margins.
    assert render_rtf(_aet02_model()).count(r"\trhdr") == 2
    # Title and footnotes in the body leave room for fewer rows.
    assert render_rtf(_aet02_model(), body_title=True).count(r"\trhdr") == 3
    # A long term wraps to several lines, so fewer rows fit on a page.
    long = "Aspartate aminotransferase increased " * 3
    wrapped = render_rtf(_aet02_model(n_soc=1, n_pt=40, label=long))
    assert wrapped.count(r"\trhdr") >= 4


def test_rtf_listing_has_footer_fields_and_a_budget() -> None:
    from fleet.tlg.render import RenderMetadata, listing_to_model, render_listing_rtf

    listing = pl.DataFrame([_AE_LISTING_ROW] * 40)
    model = listing_to_model(listing, RenderMetadata(title="Listing 16.2.7"))
    rtf = render_listing_rtf(model)
    _, footer, body = _groups(rtf)
    assert r"\fldinst NUMPAGES}" in footer
    # Each AE row wraps to many lines in 15 columns: 40 rows need several pages.
    assert rtf.count(r"\trhdr") > 2
    assert "Listing 16.2.7" not in body
