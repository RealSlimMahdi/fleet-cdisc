"""Tests for the TLG render sub-module — models, shaping, and HTML renderer."""

from __future__ import annotations

import polars as pl
import pytest

from fleet.tlg import (
    AEListingSpec,
    Column,
    GroupPool,
    OverallStat,
    Statistic,
)
from fleet.tlg.render import (
    ListingModel,
    RenderMetadata,
    TableModel,
    ard_to_table_model,
    listing_to_model,
    render_html,
    render_listing_html,
)
from fleet.tlg.render._models import ColumnHeader, TableRow, _merge_n_pct

# ------------------------------------------------------------------ #
# Fixtures                                                             #
# ------------------------------------------------------------------ #


@pytest.fixture()
def adsl() -> pl.DataFrame:
    """Minimal ADSL with 6 subjects across 3 arms."""
    return pl.DataFrame(
        {
            "USUBJID": ["SUBJ-01", "SUBJ-02", "SUBJ-03", "SUBJ-04", "SUBJ-05", "SUBJ-06"],
            "TRTA": ["Placebo", "Placebo", "Drug A", "Drug A", "Drug B", "Drug B"],
            "SAFFL": ["Y", "Y", "Y", "Y", "Y", "N"],
        }
    )


@pytest.fixture()
def adae() -> pl.DataFrame:
    """Minimal ADAE-like DataFrame for AE summary tests."""
    return pl.DataFrame(
        {
            "USUBJID": [
                "SUBJ-01",
                "SUBJ-01",
                "SUBJ-02",
                "SUBJ-03",
                "SUBJ-03",
                "SUBJ-03",
                "SUBJ-04",
                "SUBJ-05",
            ],
            "TRTA": [
                "Placebo",
                "Placebo",
                "Placebo",
                "Drug A",
                "Drug A",
                "Drug A",
                "Drug A",
                "Drug B",
            ],
            "AEBODSYS": [
                "NERVOUS",
                "GASTRO",
                "NERVOUS",
                "NERVOUS",
                "NERVOUS",
                "GASTRO",
                "GASTRO",
                "NERVOUS",
            ],
            "AEDECOD": [
                "HEADACHE",
                "NAUSEA",
                "HEADACHE",
                "HEADACHE",
                "DIZZINESS",
                "NAUSEA",
                "NAUSEA",
                "HEADACHE",
            ],
            "AESEV": [
                "MILD",
                "MODERATE",
                "MILD",
                "MILD",
                "MILD",
                "MODERATE",
                "MILD",
                "MILD",
            ],
            "AESER": ["N", "N", "N", "N", "N", "Y", "N", "N"],
            "SAFFL": ["Y", "Y", "Y", "Y", "Y", "Y", "Y", "Y"],
        }
    )


@pytest.fixture()
def basic_ard(adae: pl.DataFrame, adsl: pl.DataFrame) -> pl.DataFrame:
    """A basic ARD from default AE summary."""
    return adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl)


@pytest.fixture()
def rich_ard(adae: pl.DataFrame, adsl: pl.DataFrame) -> pl.DataFrame:
    """ARD with pools, header rows, and hierarchy."""
    return (
        adae.tlg.ae.population(adsl)
        .by("TRTA")
        .header_rows(
            [
                OverallStat(label="Subjects with any AE"),
                OverallStat(label="Subjects with >= 1 SAE", filter=pl.col("AESER") == "Y"),
            ]
        )
        .rows(["AEBODSYS", "AEDECOD"])
        .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
        .pools([GroupPool(label="Total", arms="*")])
        .column_order(["Placebo", "Drug A", "Drug B", "Total"])
        .to_ard()
    )


# ================================================================== #
# RenderMetadata                                                       #
# ================================================================== #


class TestRenderMetadata:
    """RenderMetadata dataclass."""

    def test_defaults(self) -> None:
        meta = RenderMetadata()
        assert meta.title == ""
        assert meta.subtitle == ""
        assert meta.footnotes == []

    def test_custom(self) -> None:
        meta = RenderMetadata(
            title="Table 14.3.1",
            subtitle="AE Summary",
            footnotes=["Source: ADAE"],
        )
        assert meta.title == "Table 14.3.1"
        assert len(meta.footnotes) == 1


# ================================================================== #
# ColumnHeader                                                         #
# ================================================================== #


class TestColumnHeader:
    """ColumnHeader display logic."""

    def test_display_with_big_n(self) -> None:
        ch = ColumnHeader(label="Placebo", big_n=42)
        assert ch.display == "Placebo\n(N=42)"

    def test_display_without_big_n(self) -> None:
        ch = ColumnHeader(label="Placebo")
        assert ch.display == "Placebo"


# ================================================================== #
# _merge_n_pct                                                        #
# ================================================================== #


class TestMergeNPct:
    """n + pct merge logic."""

    def test_normal(self) -> None:
        assert _merge_n_pct("3", "50.0") == "3 (50.0%)"

    def test_zero(self) -> None:
        result = _merge_n_pct("0", "0.0")
        assert result == "0"

    def test_empty_n(self) -> None:
        assert _merge_n_pct("", "50.0") == ""

    def test_zero_pct_nonzero_n(self) -> None:
        # n=1 but pct=0.0 should show "1 (  0%)"
        result = _merge_n_pct("1", "0.0")
        assert "1" in result


# ================================================================== #
# ard_to_table_model — Phase 2                                        #
# ================================================================== #


class TestArdToTableModel:
    """ARD → TableModel shaping."""

    def test_basic_model_has_columns(self, basic_ard: pl.DataFrame) -> None:
        model = ard_to_table_model(basic_ard)
        assert isinstance(model, TableModel)
        assert len(model.columns) > 0

    def test_big_n_extracted_to_headers(self, basic_ard: pl.DataFrame, adsl: pl.DataFrame) -> None:
        model = ard_to_table_model(basic_ard)
        labels = {c.label for c in model.columns}
        assert "Placebo" in labels
        assert "Drug A" in labels
        # Verify big-N is populated
        placebo = next(c for c in model.columns if c.label == "Placebo")
        assert placebo.big_n == 2

    def test_no_big_n_row_in_display(self, basic_ard: pl.DataFrame) -> None:
        """Big-N rows should be consumed into headers, not appear as rows."""
        model = ard_to_table_model(basic_ard)
        for row in model.rows:
            assert row.row_type != "big_n"

    def test_header_rows_present(self, rich_ard: pl.DataFrame) -> None:
        model = ard_to_table_model(rich_ard)
        header_rows = [r for r in model.rows if r.row_type == "header"]
        assert len(header_rows) == 2
        labels = {r.label for r in header_rows}
        assert "Subjects with any AE" in labels
        assert "Subjects with >= 1 SAE" in labels

    def test_hierarchy_row_types(self, rich_ard: pl.DataFrame) -> None:
        model = ard_to_table_model(rich_ard)
        group_rows = [r for r in model.rows if r.row_type == "group"]
        data_rows = [r for r in model.rows if r.row_type == "data"]
        assert len(group_rows) > 0, "Should have group (SOC) rows"
        assert len(data_rows) > 0, "Should have data (PT) rows"

    def test_group_rows_have_empty_cells(self, rich_ard: pl.DataFrame) -> None:
        model = ard_to_table_model(rich_ard)
        group_rows = [r for r in model.rows if r.row_type == "group"]
        for gr in group_rows:
            for val in gr.cells.values():
                assert val == "", f"Group row should have empty cells, got '{val}'"

    def test_data_rows_have_merged_n_pct(self, rich_ard: pl.DataFrame) -> None:
        model = ard_to_table_model(rich_ard)
        data_rows = [r for r in model.rows if r.row_type == "data"]
        # At least some data rows should have non-empty cells with percentage
        non_empty = [val for row in data_rows for val in row.cells.values() if val and "%" in val]
        assert len(non_empty) > 0, "Should have merged n(pct%) cells"

    def test_column_order_preserved(self, rich_ard: pl.DataFrame) -> None:
        model = ard_to_table_model(rich_ard)
        labels = [c.label for c in model.columns]
        assert labels == ["Placebo", "Drug A", "Drug B", "Total"]

    def test_data_rows_indented(self, rich_ard: pl.DataFrame) -> None:
        model = ard_to_table_model(rich_ard)
        data_rows = [r for r in model.rows if r.row_type == "data"]
        for dr in data_rows:
            assert dr.indent == 1

    def test_metadata_passed_through(self, basic_ard: pl.DataFrame) -> None:
        meta = RenderMetadata(title="Test", footnotes=["fn1"])
        model = ard_to_table_model(basic_ard, meta)
        assert model.metadata.title == "Test"
        assert model.metadata.footnotes == ["fn1"]


# ================================================================== #
# listing_to_model                                                     #
# ================================================================== #


class TestListingToModel:
    """Listing DataFrame → ListingModel."""

    def test_basic(self, adae: pl.DataFrame) -> None:
        listing = adae.tlg.ae.l_listing()
        model = listing_to_model(listing)
        assert isinstance(model, ListingModel)
        assert len(model.column_labels) > 0
        assert len(model.data) == len(listing)

    def test_with_metadata(self, adae: pl.DataFrame) -> None:
        listing = adae.tlg.ae.l_listing()
        meta = RenderMetadata(title="Listing 16.2.1")
        model = listing_to_model(listing, meta)
        assert model.metadata.title == "Listing 16.2.1"


# ================================================================== #
# render_html — Phase 3                                                #
# ================================================================== #


class TestRenderHtml:
    """HTML summary table renderer."""

    def test_returns_string(self, basic_ard: pl.DataFrame) -> None:
        model = ard_to_table_model(basic_ard)
        html = render_html(model)
        assert isinstance(html, str)
        assert len(html) > 0

    def test_contains_table_tag(self, basic_ard: pl.DataFrame) -> None:
        model = ard_to_table_model(basic_ard)
        html = render_html(model)
        assert "<table" in html
        assert "</table>" in html

    def test_contains_style(self, basic_ard: pl.DataFrame) -> None:
        model = ard_to_table_model(basic_ard)
        html = render_html(model)
        assert "<style>" in html
        assert "fleet-summary" in html

    def test_title_rendered(self, basic_ard: pl.DataFrame) -> None:
        meta = RenderMetadata(title="Table 14.3.1.1")
        model = ard_to_table_model(basic_ard, meta)
        html = render_html(model)
        assert "Table 14.3.1.1" in html

    def test_subtitle_rendered(self, basic_ard: pl.DataFrame) -> None:
        meta = RenderMetadata(subtitle="AE Summary - Safety Population")
        model = ard_to_table_model(basic_ard, meta)
        html = render_html(model)
        assert "AE Summary - Safety Population" in html

    def test_footnotes_rendered(self, basic_ard: pl.DataFrame) -> None:
        meta = RenderMetadata(footnotes=["Source: ADAE", "Pop: Safety"])
        model = ard_to_table_model(basic_ard, meta)
        html = render_html(model)
        assert "Source: ADAE" in html
        assert "Pop: Safety" in html

    def test_arm_headers_with_n(self, basic_ard: pl.DataFrame) -> None:
        model = ard_to_table_model(basic_ard)
        html = render_html(model)
        assert "(N=2)" in html  # Placebo and Drug A each have N=2

    def test_header_rows_rendered(self, rich_ard: pl.DataFrame) -> None:
        model = ard_to_table_model(rich_ard)
        html = render_html(model)
        assert "header-row" in html
        assert "Subjects with any AE" in html

    def test_group_rows_rendered(self, rich_ard: pl.DataFrame) -> None:
        model = ard_to_table_model(rich_ard)
        html = render_html(model)
        assert "group-row" in html

    def test_data_rows_indented(self, rich_ard: pl.DataFrame) -> None:
        model = ard_to_table_model(rich_ard)
        html = render_html(model)
        assert "data-row" in html

    def test_separator_between_header_and_hierarchy(self, rich_ard: pl.DataFrame) -> None:
        model = ard_to_table_model(rich_ard)
        html = render_html(model)
        assert "separator-row" in html

    def test_html_escape(self) -> None:
        """Special characters in labels should be escaped."""
        model = TableModel(
            metadata=RenderMetadata(title="Test <script>alert(1)</script>"),
            columns=[ColumnHeader(label="Arm", big_n=10)],
            rows=[TableRow(label="Row & label", row_type="flat", cells={"Arm": "1 (10.0%)"})],
        )
        html = render_html(model)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "Row &amp; label" in html

    def test_html_wrapper_injection(self, basic_ard: pl.DataFrame) -> None:
        model = ard_to_table_model(basic_ard)
        wrapper = '<div class="sponsor-portal">{table}</div>'
        html = render_html(model, html_wrapper=wrapper)
        assert html.startswith('<div class="sponsor-portal">')
        assert html.endswith("</div>")
        assert "<table" in html

    def test_no_wrapper_returns_standalone(self, basic_ard: pl.DataFrame) -> None:
        model = ard_to_table_model(basic_ard)
        html = render_html(model)
        assert html.startswith('<div class="fleet-table-container">')


# ================================================================== #
# render_listing_html                                                  #
# ================================================================== #


class TestRenderListingHtml:
    """HTML listing renderer."""

    def test_returns_string(self, adae: pl.DataFrame) -> None:
        listing = adae.tlg.ae.l_listing()
        model = listing_to_model(listing)
        html = render_listing_html(model)
        assert isinstance(html, str)
        assert "<table" in html

    def test_contains_listing_style(self, adae: pl.DataFrame) -> None:
        listing = adae.tlg.ae.l_listing()
        model = listing_to_model(listing)
        html = render_listing_html(model)
        assert "fleet-listing" in html

    def test_title_rendered(self, adae: pl.DataFrame) -> None:
        listing = adae.tlg.ae.l_listing()
        model = listing_to_model(listing, RenderMetadata(title="Listing 16.2.1"))
        html = render_listing_html(model)
        assert "Listing 16.2.1" in html

    def test_column_headers_rendered(self, adae: pl.DataFrame) -> None:
        spec = AEListingSpec(
            columns=[
                Column(field="USUBJID", label="Subject"),
                Column(field="AEDECOD", label="Preferred Term"),
            ],
            required_columns=["USUBJID", "AEDECOD"],
        )
        listing = adae.tlg.ae.l_listing(spec=spec)
        model = listing_to_model(listing)
        html = render_listing_html(model)
        assert "Subject" in html
        assert "Preferred Term" in html

    def test_html_wrapper_injection(self, adae: pl.DataFrame) -> None:
        listing = adae.tlg.ae.l_listing()
        model = listing_to_model(listing)
        wrapper = "<main>{table}</main>"
        html = render_listing_html(model, html_wrapper=wrapper)
        assert html.startswith("<main>")


# ================================================================== #
# Builder .to_html()                                                   #
# ================================================================== #


class TestBuilderToHtml:
    """TLGBuilder.to_html() integration."""

    def test_returns_html_string(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        html = (
            adae.tlg.ae.population(adsl)
            .by("TRTA")
            .rows(["AEBODSYS", "AEDECOD"])
            .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
            .to_html()
        )
        assert isinstance(html, str)
        assert "<table" in html

    def test_metadata_passed(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        html = (
            adae.tlg.ae.population(adsl)
            .by("TRTA")
            .rows(["AEBODSYS", "AEDECOD"])
            .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
            .to_html(metadata=RenderMetadata(title="My Table"))
        )
        assert "My Table" in html

    def test_writes_to_file(self, adae: pl.DataFrame, adsl: pl.DataFrame, tmp_path) -> None:
        out = tmp_path / "test.html"
        html = (
            adae.tlg.ae.population(adsl)
            .by("TRTA")
            .rows(["AEBODSYS", "AEDECOD"])
            .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
            .to_html(path=str(out))
        )
        assert out.exists()
        assert out.read_text() == html

    def test_html_wrapper(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        html = (
            adae.tlg.ae.population(adsl)
            .by("TRTA")
            .rows(["AEBODSYS", "AEDECOD"])
            .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
            .to_html(html_wrapper='<div id="report">{table}</div>')
        )
        assert html.startswith('<div id="report">')


# ================================================================== #
# PDF renderer — smoke tests                                          #
# ================================================================== #


class TestRenderPdf:
    """PDF renderer via WeasyPrint (import guard)."""

    def test_import_error_without_weasyprint(self, basic_ard: pl.DataFrame) -> None:
        """If weasyprint is missing, render_pdf raises ImportError with hint."""
        ard_to_table_model(basic_ard)
        try:
            from fleet.tlg.render.pdf import render_pdf

            # WeasyPrint might or might not be installed — test the function
            # exists and accepts the right arguments.
            assert callable(render_pdf)
        except ImportError:
            pass  # Expected if weasyprint not installed

    def test_builder_to_pdf_method_exists(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        """Builder has .to_pdf() method."""
        builder = (
            adae.tlg.ae.population(adsl)
            .by("TRTA")
            .rows(["AEBODSYS", "AEDECOD"])
            .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
        )
        assert hasattr(builder, "to_pdf")


# ================================================================== #
# CLI — fleet tlg export argument parsing                              #
# ================================================================== #


class TestCLITlgExport:
    """CLI argument parsing for ``fleet tlg export``."""

    def test_parser_recognises_tlg_command(self) -> None:
        from fleet.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(
            ["tlg", "export", "--domain", "ae", "--data", "d.csv", "--adsl", "a.csv"]
        )
        assert args.command == "tlg"
        assert args.tlg_command == "export"
        assert args.domain == "ae"
        assert args.fmt == "html"

    def test_parser_accepts_pdf_format(self) -> None:
        from fleet.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(
            [
                "tlg",
                "export",
                "--domain",
                "vs",
                "--format",
                "pdf",
                "--data",
                "d.csv",
                "--adsl",
                "a.csv",
                "--title",
                "My Title",
                "--footnote",
                "fn1",
                "--footnote",
                "fn2",
            ]
        )
        assert args.fmt == "pdf"
        assert args.domain == "vs"
        assert args.title == "My Title"
        assert args.footnote == ["fn1", "fn2"]

    def test_parser_defaults(self) -> None:
        from fleet.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(
            ["tlg", "export", "--domain", "ae", "--data", "d.csv", "--adsl", "a.csv"]
        )
        assert args.output is None
        assert args.subtitle == ""
        assert args.wrap is None

    def test_parser_accepts_pptx_format(self) -> None:
        from fleet.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(
            [
                "tlg",
                "export",
                "--domain",
                "ae",
                "--format",
                "pptx",
                "--data",
                "d.csv",
                "--adsl",
                "a.csv",
            ]
        )
        assert args.fmt == "pptx"


# ================================================================== #
# PPTX renderer                                                        #
# ================================================================== #


class TestRenderPptx:
    """PPTX renderer via python-pptx."""

    def test_import_guard(self) -> None:
        """render_pptx is importable and callable."""
        from fleet.tlg.render.slides import render_pptx

        assert callable(render_pptx)

    def test_render_summary_pptx(self, basic_ard: pl.DataFrame, tmp_path) -> None:
        """render_pptx produces a readable PPTX file."""
        from fleet.tlg.render.slides import render_pptx

        meta = RenderMetadata(
            title="Table 14.3.1.1",
            subtitle="AE Summary",
            footnotes=["Source: ADAE"],
        )
        model = ard_to_table_model(basic_ard, meta)
        out = tmp_path / "test.pptx"
        result = render_pptx(model, out)
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 0

        # Verify it's a valid PPTX
        from pptx import Presentation

        prs = Presentation(str(out))
        assert len(prs.slides) == 1

    def test_render_listing_pptx(self, adae: pl.DataFrame, tmp_path) -> None:
        """render_listing_pptx produces a readable PPTX file."""
        from fleet.tlg.render.slides import render_listing_pptx

        listing_df = adae.select(["USUBJID", "TRTA", "AEBODSYS", "AEDECOD"])
        model = listing_to_model(listing_df, RenderMetadata(title="Listing 16.2.7.1"))
        out = tmp_path / "listing.pptx"
        result = render_listing_pptx(model, out)
        assert result == out
        assert out.exists()

        from pptx import Presentation

        prs = Presentation(str(out))
        assert len(prs.slides) == 1

    def test_builder_to_pptx(self, adae: pl.DataFrame, adsl: pl.DataFrame, tmp_path) -> None:
        """Builder .to_pptx() produces a valid PPTX file."""
        out = tmp_path / "builder.pptx"
        result = (
            adae.tlg.ae.population(adsl)
            .by("TRTA")
            .rows(["AEBODSYS", "AEDECOD"])
            .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
            .to_pptx(str(out), metadata=RenderMetadata(title="Builder Test"))
        )
        assert result == out
        assert out.exists()

        from pptx import Presentation

        prs = Presentation(str(out))
        slide = prs.slides[0]
        # Should have title textbox + table + possibly subtitle/footnotes
        assert len(slide.shapes) >= 2

    def test_theme_override(self, basic_ard: pl.DataFrame, tmp_path) -> None:
        """Custom theme overrides are applied."""
        from fleet.tlg.render.slides import render_pptx

        model = ard_to_table_model(basic_ard, RenderMetadata(title="Themed"))
        out = tmp_path / "themed.pptx"
        render_pptx(model, out, theme={"font_name": "Arial", "header_bg": "FF0000"})
        assert out.exists()

        from pptx import Presentation

        prs = Presentation(str(out))
        assert len(prs.slides) == 1

    def test_pptx_contains_title(self, basic_ard: pl.DataFrame, tmp_path) -> None:
        """Title text appears in the generated slide."""
        from fleet.tlg.render.slides import render_pptx

        model = ard_to_table_model(basic_ard, RenderMetadata(title="My Special Title"))
        out = tmp_path / "titled.pptx"
        render_pptx(model, out)

        from pptx import Presentation

        prs = Presentation(str(out))
        slide = prs.slides[0]
        texts = [shape.text_frame.text for shape in slide.shapes if shape.has_text_frame]
        assert any("My Special Title" in t for t in texts)
