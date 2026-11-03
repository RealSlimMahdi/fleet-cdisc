"""Statistics read back from the RTF, PPTX and PDF renderers (alpha audit c1-860).

The golden tests compare the ARD and two HTML pages.  These tests render one
AE table to the other formats and read each statistic back from the file,
so "compared cell by cell" holds for every format Fleet writes.
"""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl
import pytest

from fleet.tlg import OverallStat, Statistic
from fleet.tlg.render import RenderMetadata, ard_to_table_model, render_rtf

_ADSL = pl.from_repr("""
    ┌─────────┬─────────┬───────┐
    │ USUBJID ┆ TRTA    ┆ SAFFL │
    │ ---     ┆ ---     ┆ ---   │
    │ str     ┆ str     ┆ str   │
    ╞═════════╪═════════╪═══════╡
    │ SUBJ-01 ┆ Placebo ┆ Y     │
    │ SUBJ-02 ┆ Placebo ┆ Y     │
    │ SUBJ-03 ┆ Drug A  ┆ Y     │
    │ SUBJ-04 ┆ Drug A  ┆ Y     │
    └─────────┴─────────┴───────┘
    """)

_ADAE = pl.from_repr("""
    ┌─────────┬─────────┬──────────┬──────────┬───────┐
    │ USUBJID ┆ TRTA    ┆ AEBODSYS ┆ AEDECOD  ┆ AESER │
    │ ---     ┆ ---     ┆ ---      ┆ ---      ┆ ---   │
    │ str     ┆ str     ┆ str      ┆ str      ┆ str   │
    ╞═════════╪═════════╪══════════╪══════════╪═══════╡
    │ SUBJ-01 ┆ Placebo ┆ NERVOUS  ┆ HEADACHE ┆ N     │
    │ SUBJ-03 ┆ Drug A  ┆ NERVOUS  ┆ HEADACHE ┆ N     │
    │ SUBJ-03 ┆ Drug A  ┆ GASTRO   ┆ NAUSEA   ┆ Y     │
    │ SUBJ-04 ┆ Drug A  ┆ GASTRO   ┆ NAUSEA   ┆ N     │
    └─────────┴─────────┴──────────┴──────────┴───────┘
    """)

#: Counted by hand from the frames above: N is 2 per arm.
_EXPECTED = {
    "Subjects with any AE": {"Placebo": "1 (50.0%)", "Drug A": "2 (100.0%)"},
    "Subjects with >= 1 SAE": {"Placebo": "0", "Drug A": "1 (50.0%)"},
    "NAUSEA": {"Placebo": "0", "Drug A": "2 (100.0%)"},
}


@pytest.fixture(scope="module")
def model():
    ard = (
        _ADAE.tlg.ae.population(_ADSL)
        .by("TRTA")
        .header_rows(
            [
                OverallStat(label="Subjects with any AE"),
                OverallStat(label="Subjects with >= 1 SAE", filter=pl.col("AESER") == "Y"),
            ]
        )
        .rows(["AEBODSYS", "AEDECOD"])
        .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
        .to_ard()
    )
    model = ard_to_table_model(ard, RenderMetadata(title="Table 14.3.1"))
    by_label = {row.label.strip(): row.cells for row in model.rows}
    for label, cells in _EXPECTED.items():
        for arm, value in cells.items():
            assert by_label[label][arm] == value, (label, arm)
    return model


def _in_order(text: str, *needles: str) -> bool:
    """True when each needle occurs in *text* after the one before it."""
    position = 0
    for needle in needles:
        position = text.find(needle, position)
        if position < 0:
            return False
        position += len(needle)
    return True


def _assert_every_statistic(text: str, arms: list[str]) -> None:
    text = re.sub(r"\s+", " ", text)
    for label, cells in _EXPECTED.items():
        assert _in_order(text, label, *(cells[arm] for arm in arms)), label


def test_rtf_holds_every_statistic(model, tmp_path: Path) -> None:
    rtf = render_rtf(model, tmp_path / "t.rtf")
    text = re.sub(r"\\[a-z]+-?\d* ?|[{}]", " ", Path(tmp_path / "t.rtf").read_text("utf-8"))

    assert rtf
    _assert_every_statistic(text, [c.label for c in model.columns])


def test_pptx_holds_every_statistic(model, tmp_path: Path) -> None:
    pptx = pytest.importorskip("pptx")
    from fleet.tlg.render.slides import render_pptx

    deck = pptx.Presentation(str(render_pptx(model, tmp_path / "t.pptx")))
    cells = [
        cell.text
        for slide in deck.slides
        for shape in slide.shapes
        if shape.has_table
        for row in shape.table.rows
        for cell in row.cells
    ]

    _assert_every_statistic(" | ".join(cells), [c.label for c in model.columns])


def test_pdf_holds_every_statistic(model, tmp_path: Path) -> None:
    pytest.importorskip("weasyprint")
    pypdf = pytest.importorskip("pypdf")
    from fleet.tlg.render.pdf import render_pdf

    pdf = pypdf.PdfReader(str(render_pdf(model, tmp_path / "t.pdf")))
    text = " ".join(page.extract_text() for page in pdf.pages)

    _assert_every_statistic(text, [c.label for c in model.columns])
