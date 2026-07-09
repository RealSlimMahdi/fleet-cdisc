"""Submission-readiness tests: renderer C1 fix, ARD honesty (C8, strict
validation, non-numeric stats), value/label columns, decimal control,
percent display consistency (E5), pagination, and the RTF renderer.

Golden HTML files pin the continuous-template rendering (vst01/lbt01);
regenerate with ``uv run python scripts/regen_tlg_goldens.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import polars as pl
import pytest

import fleet  # noqa: F401 — registers df.tlg
from fleet.core.exceptions import SchemaError
from fleet.tlg import Row, Statistic, VSSummarySpec
from fleet.tlg._ard import ard_row, rows_to_ard, summarize_ard, validate_ard
from fleet.tlg.lb_namespace import LBSummarySpec
from fleet.tlg.render import (
    ListingModel,
    RenderMetadata,
    ard_to_table_model,
    listing_to_model,
    paginate,
    paginate_listing,
    render_html,
    render_listing_rtf,
    render_rtf,
)
from fleet.tlg.render._models import ColumnHeader, TableModel, TableRow, _merge_n_pct

sys.path.insert(0, str(Path(__file__).parent.parent))
from fixtures.study import ADSL, FRAMES  # noqa: E402

GOLDEN_DIR = Path(__file__).parent.parent / "fixtures" / "goldens" / "tlg"

#: Three subjects in one arm → 1/3 percentages exercise unrounded storage.
ADSL3 = pl.from_repr("""\
┌─────────┬─────────┐
│ USUBJID ┆ TRTA    │
│ ---     ┆ ---     │
│ str     ┆ str     │
╞═════════╪═════════╡
│ S01     ┆ Placebo │
│ S02     ┆ Placebo │
│ S03     ┆ Placebo │
└─────────┴─────────┘
""")

ADVS = pl.from_repr("""\
┌─────────┬─────────┬─────────┬────────────────────────────────┬──────┬─────┐
│ USUBJID ┆ TRTA    ┆ PARAMCD ┆ PARAM                          ┆ AVAL ┆ CHG │
│ ---     ┆ ---     ┆ ---     ┆ ---                            ┆ ---  ┆ --- │
│ str     ┆ str     ┆ str     ┆ str                            ┆ f64  ┆ f64 │
╞═════════╪═════════╪═════════╪════════════════════════════════╪══════╪═════╡
│ S01     ┆ Placebo ┆ SYSBP   ┆ Systolic Blood Pressure (mmHg) ┆ 120  ┆ 2   │
│ S02     ┆ Placebo ┆ SYSBP   ┆ Systolic Blood Pressure (mmHg) ┆ 130  ┆ 6   │
└─────────┴─────────┴─────────┴────────────────────────────────┴──────┴─────┘
""")


# ================================================================== #
# C1 — continuous statistics reach the rendered table                  #
# ================================================================== #


class TestContinuousRendering:
    """A VS/LB ARD with n/mean/sd/median/min/max renders every statistic."""

    @pytest.mark.parametrize("template_id", ["vst01", "lbt01"])
    def test_to_html_matches_golden(self, template_id: str) -> None:
        from fleet.tlg import TEMPLATES

        meta = TEMPLATES[template_id]
        frame = FRAMES[meta.domains[-1]]
        ns = getattr(frame.tlg, meta.namespace)
        html = ns.population(ADSL).by("TRTA").template(template_id).to_html()
        golden = (GOLDEN_DIR / f"{template_id}.html").read_text(encoding="utf-8")
        assert html == golden, f"{template_id}: rendered HTML drifted from golden"

    def test_every_statistic_gets_a_display_row(self) -> None:
        ard = ADVS.tlg.vs.t_summary(groupby="TRTA", adsl=ADSL3)
        model = ard_to_table_model(ard)
        stat_rows = [r for r in model.rows if r.row_type == "stat"]
        labels = [r.label for r in stat_rows]
        assert labels == ["n", "Mean", "SD", "Median", "Min", "Max"]
        by_label = {r.label: r for r in stat_rows}
        assert by_label["Mean"].cells["Placebo"] == "125.0"
        assert by_label["SD"].cells["Placebo"] == "7.07"
        assert by_label["Min"].cells["Placebo"] == "120.0"

    def test_stat_rows_sit_under_level_stub(self) -> None:
        ard = ADVS.tlg.vs.t_summary(groupby="TRTA", adsl=ADSL3)
        model = ard_to_table_model(ard)
        stub = next(r for r in model.rows if r.label == "SYSBP")
        assert all(v == "" for v in stub.cells.values())
        stat_rows = [r for r in model.rows if r.row_type == "stat"]
        assert all(r.indent == stub.indent + 1 for r in stat_rows)

    def test_row_label_becomes_section_or_stub_label(self) -> None:
        # Flat continuous block: the Row.label heads the stub column via
        # a section row ("Parameter" — VSSummarySpec's default label).
        ard = ADVS.tlg.vs.t_summary(groupby="TRTA", adsl=ADSL3)
        model = ard_to_table_model(ard)
        sections = [r for r in model.rows if r.row_type == "section"]
        assert [s.label for s in sections] == ["Parameter"]
        # Nested hierarchy: the parent Row.label becomes the stub header.
        adlb = FRAMES["ADLB"]
        lb_model = ard_to_table_model(adlb.tlg.lb.t_summary(groupby="TRTA", adsl=ADSL))
        assert lb_model.stub_label == "Parameter"

    def test_dm_categorical_blocks_get_section_headings(self) -> None:
        adsl = ADSL
        model = ard_to_table_model(adsl.tlg.dm.t_summary(groupby="TRTA", adsl=adsl))
        sections = [r.label for r in model.rows if r.row_type == "section"]
        assert sections[:2] == ["Sex", "Age Group (yr)"]
        # Categorical level rows carry real cells (not blanked as fake
        # hierarchy groups — the pre-fix behaviour).
        sex_level = next(r for r in model.rows if r.label in ("F", "M"))
        assert any("%" in v for v in sex_level.cells.values())

    def test_synthetic_parent_stub_for_lbt04(self) -> None:
        # t_abnormal emits children with group2=PARAMCD but no explicit
        # parent rows — the renderer synthesises the parameter stub.
        adlb = FRAMES["ADLB"]
        ard = adlb.tlg.lb.t_abnormal(groupby="TRTA", adsl=ADSL)
        model = ard_to_table_model(ard)
        groups = [r for r in model.rows if r.row_type == "group"]
        assert [g.label for g in groups] == ["ALT"]


# ================================================================== #
# C8 — percentages stored unrounded; display rounding in fmt_fn        #
# ================================================================== #


class TestUnroundedPercentages:
    ADAE3 = pl.from_repr("""\
┌─────────┬─────────┬──────────┬──────────┐
│ USUBJID ┆ TRTA    ┆ AEBODSYS ┆ AEDECOD  │
│ ---     ┆ ---     ┆ ---      ┆ ---      │
│ str     ┆ str     ┆ str      ┆ str      │
╞═════════╪═════════╪══════════╪══════════╡
│ S01     ┆ Placebo ┆ NERVOUS  ┆ HEADACHE │
└─────────┴─────────┴──────────┴──────────┘
""")

    def test_stat_holds_full_precision(self) -> None:
        ard = self.ADAE3.tlg.ae.t_summary(groupby="TRTA", adsl=ADSL3)
        pct = ard.filter((pl.col("variable") == "AEDECOD") & (pl.col("stat_name") == "pct"))[
            "stat"
        ].to_list()
        assert pct == [pytest.approx(100 / 3)]  # not 33.3

    def test_stat_fmt_still_one_decimal(self) -> None:
        ard = self.ADAE3.tlg.ae.t_summary(groupby="TRTA", adsl=ADSL3)
        pct_fmt = ard.filter((pl.col("variable") == "AEDECOD") & (pl.col("stat_name") == "pct"))[
            "stat_fmt"
        ].to_list()
        assert pct_fmt == ["33.3"]

    def test_rendered_cell_unchanged(self) -> None:
        ard = self.ADAE3.tlg.ae.t_summary(groupby="TRTA", adsl=ADSL3)
        model = ard_to_table_model(ard)
        headache = next(r for r in model.rows if r.label == "HEADACHE")
        assert headache.cells["Placebo"] == "1 (33.3%)"

    def test_abnormal_pct_unrounded(self) -> None:
        adlb = pl.from_repr("""\
┌─────────┬─────────┬─────────┬───────┬────────┬────────┐
│ USUBJID ┆ TRTA    ┆ PARAMCD ┆ ABLFL ┆ BNRIND ┆ ANRIND │
│ ---     ┆ ---     ┆ ---     ┆ ---   ┆ ---    ┆ ---    │
│ str     ┆ str     ┆ str     ┆ null  ┆ str    ┆ str    │
╞═════════╪═════════╪═════════╪═══════╪════════╪════════╡
│ S01     ┆ Placebo ┆ ALT     ┆ null  ┆ NORMAL ┆ HIGH   │
│ S02     ┆ Placebo ┆ ALT     ┆ null  ┆ NORMAL ┆ NORMAL │
│ S03     ┆ Placebo ┆ ALT     ┆ null  ┆ NORMAL ┆ NORMAL │
└─────────┴─────────┴─────────┴───────┴────────┴────────┘
""")
        ard = adlb.tlg.lb.t_abnormal(groupby="TRTA", adsl=ADSL3)
        high = ard.filter((pl.col("variable_level") == "High") & (pl.col("stat_name") == "pct"))
        assert high["stat"].to_list() == [pytest.approx(100 / 3)]
        assert high["stat_fmt"].to_list() == ["33.3"]


# ================================================================== #
# ARD honesty — rows_to_ard raises, validate_ard strict mode           #
# ================================================================== #


class TestArdHonesty:
    def test_non_numeric_stat_raises(self) -> None:
        rows = [ard_row("TRTA", "Placebo", "X", "Y", "n", "n", "not-a-number", "ctx")]
        with pytest.raises(SchemaError, match="Non-numeric stat"):
            rows_to_ard(rows)

    def test_numeric_string_still_coerces(self) -> None:
        rows = [ard_row("TRTA", "Placebo", "X", "Y", "n", "n", "3", "ctx")]
        ard = rows_to_ard(rows)
        assert ard["stat"].to_list() == [3.0]

    def test_validate_ard_strict_rejects_extras(self) -> None:
        ard = rows_to_ard([ard_row("TRTA", "Placebo", "X", "Y", "n", "n", 1, "ctx")])
        annotated = ard.with_columns(pl.lit("keep").alias("my_note"))
        assert any("Unexpected columns" in i for i in validate_ard(annotated))

    def test_validate_ard_relaxed_accepts_extras(self) -> None:
        ard = rows_to_ard([ard_row("TRTA", "Placebo", "X", "Y", "n", "n", 1, "ctx")])
        annotated = ard.with_columns(pl.lit("keep").alias("my_note"))
        assert validate_ard(annotated, strict=False) == []

    def test_validate_ard_relaxed_still_checks_required(self) -> None:
        bad = pl.from_repr("""\
┌────────┬──────┐
│ group1 ┆ stat │
│ ---    ┆ ---  │
│ str    ┆ f64  │
╞════════╪══════╡
│ TRTA   ┆ 1    │
└────────┴──────┘
""")
        assert any("Missing required" in i for i in validate_ard(bad, strict=False))


# ================================================================== #
# value_col / label_col                                                #
# ================================================================== #


class TestValueAndLabelColumns:
    def test_value_col_summarizes_chg(self) -> None:
        spec = VSSummarySpec(
            value_col="CHG",
            required_columns=["USUBJID", "TRTA", "PARAMCD", "CHG"],
        )
        ard = ADVS.tlg.vs.t_summary(groupby="TRTA", adsl=ADSL3, spec=spec)
        mean = ard.filter(pl.col("stat_name") == "mean")["stat"].drop_nulls().to_list()
        assert mean == [4.0]  # (2 + 6) / 2 — CHG, not AVAL (125.0)

    def test_missing_value_col_raises(self) -> None:
        with pytest.raises(SchemaError, match="value.*col|CHG2"):
            summarize_ard(
                ADVS,
                rows=["PARAMCD"],
                stats=[Statistic.MEAN],
                context="t",
                group_col="TRTA",
                value_col="CHG2",
            )

    def test_label_col_maps_stub_levels(self) -> None:
        spec = VSSummarySpec(label_col="PARAM")
        ard = ADVS.tlg.vs.t_summary(groupby="TRTA", adsl=ADSL3, spec=spec)
        levels = set(ard.filter(pl.col("variable") == "PARAMCD")["variable_level"].to_list())
        assert levels == {"Systolic Blood Pressure (mmHg)"}

    def test_label_col_maps_group2_parent(self) -> None:
        adlb = FRAMES["ADLB"].with_columns(pl.lit("Alanine Aminotransferase (U/L)").alias("PARAM"))
        spec = LBSummarySpec(label_col="PARAM")
        ard = adlb.tlg.lb.t_summary(groupby="TRTA", adsl=ADSL, spec=spec)
        parents = set(
            ard.filter(pl.col("group2") == "PARAMCD")["group2_level"].drop_nulls().to_list()
        )
        assert parents == {"Alanine Aminotransferase (U/L)"}

    def test_missing_label_col_raises(self) -> None:
        spec = VSSummarySpec(label_col="NOPE")
        with pytest.raises(SchemaError, match="NOPE"):
            ADVS.tlg.vs.t_summary(groupby="TRTA", adsl=ADSL3, spec=spec)


# ================================================================== #
# Decimal control                                                      #
# ================================================================== #


class TestDecimals:
    def test_spec_level_decimals_override_defaults(self) -> None:
        spec = VSSummarySpec(decimals={"mean": "xx.xxx", "sd": "xx.x"})
        ard = ADVS.tlg.vs.t_summary(groupby="TRTA", adsl=ADSL3, spec=spec)
        mean = ard.filter(pl.col("stat_name") == "mean")
        assert set(mean["fmt_fn"].to_list()) == {"xx.xxx"}
        assert "125.000" in mean["stat_fmt"].to_list()
        sd = ard.filter(pl.col("stat_name") == "sd")
        assert set(sd["fmt_fn"].to_list()) == {"xx.x"}

    def test_row_decimals_override_spec(self) -> None:
        spec = VSSummarySpec(
            rows=[Row(field="PARAMCD", decimals={"mean": "xx.xx"})],
            decimals={"mean": "xx"},
        )
        ard = ADVS.tlg.vs.t_summary(groupby="TRTA", adsl=ADSL3, spec=spec)
        mean = ard.filter(pl.col("stat_name") == "mean")
        assert set(mean["fmt_fn"].to_list()) == {"xx.xx"}

    def test_unmentioned_stats_keep_defaults(self) -> None:
        spec = VSSummarySpec(decimals={"mean": "xx.xx"})
        ard = ADVS.tlg.vs.t_summary(groupby="TRTA", adsl=ADSL3, spec=spec)
        median = ard.filter(pl.col("stat_name") == "median")
        assert set(median["fmt_fn"].to_list()) == {"xx.x"}

    def test_decimals_survive_yaml_roundtrip(self) -> None:
        spec = VSSummarySpec(decimals={"mean": "xx.xx"})
        restored = VSSummarySpec.from_yaml(spec.to_yaml())
        assert restored.decimals == {"mean": "xx.xx"}


# ================================================================== #
# E5 — percent display consistency                                     #
# ================================================================== #


class TestPercentDisplay:
    def test_sub_threshold_merged(self) -> None:
        assert _merge_n_pct("1", "0.0") == "1 (<0.1%)"

    def test_sub_threshold_two_decimals(self) -> None:
        assert _merge_n_pct("1", "0.00") == "1 (<0.01%)"

    def test_true_zero_cell(self) -> None:
        assert _merge_n_pct("0", "0.0") == "0"

    def test_missing_pct_shows_count_only(self) -> None:
        # No denominator → no parenthetical, never "(  0%)".
        assert _merge_n_pct("3", "") == "3"

    def test_no_double_space_artifact(self) -> None:
        for n, pct in (("1", "0.0"), ("3", ""), ("2", "50.0")):
            assert "  " not in _merge_n_pct(n, pct)

    def test_standalone_pct_carries_percent_sign(self) -> None:
        adae = pl.from_repr("""\
┌─────────┬─────────┬──────────┬──────────┐
│ USUBJID ┆ TRTA    ┆ AEBODSYS ┆ AEDECOD  │
│ ---     ┆ ---     ┆ ---      ┆ ---      │
│ str     ┆ str     ┆ str      ┆ str      │
╞═════════╪═════════╪══════════╪══════════╡
│ S01     ┆ Placebo ┆ NERVOUS  ┆ HEADACHE │
└─────────┴─────────┴──────────┴──────────┘
""")
        from fleet.tlg import AESummarySpec

        spec = AESummarySpec(statistics=[Statistic.N_PCT])
        ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=ADSL3, spec=spec)
        model = ard_to_table_model(ard)
        headache = next(r for r in model.rows if r.label == "HEADACHE")
        assert headache.cells["Placebo"] == "33.3%"

    def test_merged_sub_threshold_from_real_ard(self) -> None:
        # 1 of 3000 subjects = 0.0333% → displays "0.0" at 1dp → "<0.1".
        big_adsl = pl.DataFrame(
            {
                "USUBJID": [f"S{i:04d}" for i in range(3000)],
                "TRTA": ["Placebo"] * 3000,
            }
        )
        adae = pl.from_repr("""\
┌─────────┬─────────┬──────────┬──────────┐
│ USUBJID ┆ TRTA    ┆ AEBODSYS ┆ AEDECOD  │
│ ---     ┆ ---     ┆ ---      ┆ ---      │
│ str     ┆ str     ┆ str      ┆ str      │
╞═════════╪═════════╪══════════╪══════════╡
│ S0001   ┆ Placebo ┆ NERVOUS  ┆ HEADACHE │
└─────────┴─────────┴──────────┴──────────┘
""")
        ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=big_adsl)
        model = ard_to_table_model(ard)
        headache = next(r for r in model.rows if r.label == "HEADACHE")
        assert headache.cells["Placebo"] == "1 (<0.1%)"


# ================================================================== #
# Pagination — model layer                                             #
# ================================================================== #


def _wide_model(n_groups: int = 4, levels_per_group: int = 5) -> TableModel:
    """Synthetic hierarchy model: n_groups PARAMCD stubs × level rows."""
    rows = []
    for g in range(n_groups):
        rows.append(
            TableRow(
                label=f"PARAM{g}",
                row_type="group",
                cells={"Placebo": ""},
                bold=True,
                variable="PARAMCD",
            )
        )
        for i in range(levels_per_group):
            rows.append(
                TableRow(
                    label=f"V{g}.{i}",
                    row_type="data",
                    indent=1,
                    cells={"Placebo": str(i)},
                    variable="AVISIT",
                )
            )
    return TableModel(
        metadata=RenderMetadata(title="T", footnotes=["fn"], page_by=None),
        columns=[ColumnHeader(label="Placebo", big_n=10)],
        rows=rows,
    )


class TestPagination:
    def test_no_params_returns_single_page(self) -> None:
        model = _wide_model()
        assert paginate(model) == [model]

    def test_page_by_splits_per_group(self) -> None:
        model = _wide_model(n_groups=3)
        pages = paginate(model, page_by="PARAMCD")
        assert len(pages) == 3
        assert all(p.rows[0].row_type == "group" for p in pages)
        assert all(p.metadata.title == "T" for p in pages)

    def test_metadata_page_by_honoured(self) -> None:
        model = _wide_model(n_groups=2)
        model.metadata.page_by = "PARAMCD"
        assert len(paginate(model)) == 2

    def test_rows_per_page_never_orphans_a_stub(self) -> None:
        model = _wide_model(n_groups=4, levels_per_group=5)
        pages = paginate(model, rows_per_page=6)
        for page in pages:
            last = page.rows[-1]
            assert not (
                last.row_type in ("group", "section") and all(v == "" for v in last.cells.values())
            ), "stub row orphaned at page end"

    def test_html_pages_repeat_headers_and_number_pages(self) -> None:
        model = _wide_model(n_groups=3)
        html = render_html(model, page_by="PARAMCD")
        assert html.count('<div class="fleet-page">') == 3
        assert html.count("<thead>") == 3
        assert "Page 1 of 3" in html and "Page 3 of 3" in html
        assert html.count("fn</p>") == 3

    def test_html_single_page_output_has_no_page_wrappers(self) -> None:
        model = _wide_model(n_groups=2)
        html = render_html(model)
        assert '<div class="fleet-page">' not in html
        assert "Page 1 of" not in html

    def test_listing_pagination(self) -> None:
        listing = pl.DataFrame({"A": [str(i) for i in range(25)], "B": ["x"] * 25})
        model = listing_to_model(listing, RenderMetadata(title="L"))
        pages = paginate_listing(model, rows_per_page=10)
        assert [len(p.data) for p in pages] == [10, 10, 5]
        assert all(isinstance(p, ListingModel) for p in pages)


# ================================================================== #
# RTF renderer                                                         #
# ================================================================== #


class TestRenderRtf:
    def _model(self):
        ard = ADVS.tlg.vs.t_summary(groupby="TRTA", adsl=ADSL3)
        meta = RenderMetadata(
            title="Table 14.2.1", subtitle="Vital Signs", footnotes=["Source: ADVS"]
        )
        return ard_to_table_model(ard, meta)

    def test_document_skeleton(self) -> None:
        rtf = render_rtf(self._model())
        assert rtf.startswith(r"{\rtf1\ansi")
        assert rtf.rstrip().endswith("}")
        assert "Courier New" in rtf
        assert r"\fs18" in rtf  # 9pt body
        assert r"\landscape" in rtf

    def test_title_footnote_page_blocks(self) -> None:
        rtf = render_rtf(self._model())
        assert "Table 14.2.1" in rtf
        assert "Vital Signs" in rtf
        assert "Source: ADVS" in rtf
        assert "Page 1 of 1" in rtf

    def test_headers_flagged_for_repetition_with_borders(self) -> None:
        rtf = render_rtf(self._model())
        assert r"\trhdr" in rtf
        assert r"\clbrdrt" in rtf and r"\clbrdrb" in rtf

    def test_pagination_repeats_headers(self) -> None:
        model = _wide_model(n_groups=3)
        rtf = render_rtf(model, rows_per_page=8, page_by="PARAMCD")
        assert rtf.count(r"\page") == 2  # 3 pages → 2 breaks
        assert rtf.count(r"\trhdr") == 3
        assert "Page 2 of 3" in rtf

    def test_escapes_control_characters(self) -> None:
        meta = RenderMetadata(title=r"50% {of} \subjects — ±2")
        model = ard_to_table_model(ADVS.tlg.vs.t_summary(groupby="TRTA", adsl=ADSL3), meta)
        rtf = render_rtf(model)
        assert r"\{of\}" in rtf
        assert r"\\subjects" in rtf
        assert "\\u8212?" in rtf  # em dash escaped as \uN?
        assert "\\u177?" in rtf  # ± escaped
        assert rtf.isascii()

    def test_writes_file(self, tmp_path: Path) -> None:
        out = tmp_path / "t_vs.rtf"
        rtf = render_rtf(self._model(), out)
        assert out.read_text(encoding="ascii") == rtf

    def test_listing_rtf(self, tmp_path: Path) -> None:
        listing = pl.from_repr("""\
┌─────────┬────────┐
│ Subject ┆ Result │
│ ---     ┆ ---    │
│ str     ┆ str    │
╞═════════╪════════╡
│ S01     ┆ 120    │
│ S02     ┆ 130    │
└─────────┴────────┘
""")
        model = listing_to_model(listing, RenderMetadata(title="Listing 16.1"))
        rtf = render_listing_rtf(model, tmp_path / "l.rtf")
        assert "Listing 16.1" in rtf
        assert "S01" in rtf and "Page 1 of 1" in rtf
        assert (tmp_path / "l.rtf").exists()

    def test_listing_rtf_paginates(self) -> None:
        listing = pl.DataFrame({"A": [str(i) for i in range(90)]})
        model = listing_to_model(listing)
        rtf = render_listing_rtf(model)  # default 40 rows/page → 3 pages
        assert rtf.count(r"\page") == 2
        assert "Page 3 of 3" in rtf

    def test_builder_to_rtf(self, tmp_path: Path) -> None:
        out = tmp_path / "builder.rtf"
        rtf = (
            ADVS.tlg.vs.population(ADSL3)
            .by("TRTA")
            .to_rtf(out, metadata=RenderMetadata(title="Builder RTF"))
        )
        assert rtf.startswith(r"{\rtf1")
        assert "Builder RTF" in rtf
        assert out.read_text(encoding="ascii") == rtf


# ================================================================== #
# PDF / PPTX pagination (optional deps)                                #
# ================================================================== #


class TestOptionalRendererPagination:
    def test_pptx_chunks_rows_across_slides(self, tmp_path: Path) -> None:
        pptx = pytest.importorskip("pptx")
        from fleet.tlg.render.slides import render_pptx

        model = _wide_model(n_groups=6, levels_per_group=5)  # 36 rows
        out = tmp_path / "deck.pptx"
        render_pptx(model, out)
        prs = pptx.Presentation(str(out))
        assert len(prs.slides) > 1  # no longer one giant slide

    def test_pdf_paginates_through_html(self, tmp_path: Path) -> None:
        pytest.importorskip("weasyprint")
        from fleet.tlg.render.pdf import render_pdf

        model = _wide_model(n_groups=3)
        out = tmp_path / "t.pdf"
        result = render_pdf(model, out, page_by="PARAMCD")
        assert result.exists() and result.stat().st_size > 0
