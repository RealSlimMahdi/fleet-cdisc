"""
TableModel / ListingModel → PPTX slide deck renderer.

``python-pptx`` is an **optional** dependency.  Install it with::

    uv add python-pptx
    # or: pip install fleet-cdisc[tlg-pptx]

When ``python-pptx`` is absent, ``render_pptx`` raises a clear ``ImportError``
with an install hint.

The generated slides are fully editable — text, tables, fonts, colours, and
layout can be modified after export using PowerPoint, LibreOffice Impress,
or any OOXML-compatible editor.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._models import ListingModel, TableModel, paginate, paginate_listing

#: Body rows that fit one 16:9 slide at the default 8pt body font.
_MAX_ROWS_PER_SLIDE = 15

# ── Default theme ─────────────────────────────────────────────────── #

_DEFAULT_THEME: dict[str, Any] = {
    "font_name": "Courier New",
    "font_size_title": 14,
    "font_size_subtitle": 10,
    "font_size_body": 8,
    "font_size_footnote": 7,
    "header_bg": "4472C4",  # Blue
    "header_fg": "FFFFFF",  # White
    "group_bg": "D9E2F3",  # Light blue
    "alt_row_bg": "F2F2F2",  # Light grey
}


def _resolve_theme(overrides: dict[str, Any] | None) -> dict[str, Any]:
    """Merge user overrides into the default theme."""
    theme = dict(_DEFAULT_THEME)
    if overrides:
        theme.update(overrides)
    return theme


def _add_title_block(slide: Any, metadata: Any, th: dict[str, Any]) -> Any:
    """Add the title and subtitle text boxes; return the top of the table."""
    from pptx.util import Inches, Pt  # type: ignore[import-untyped]

    top = Inches(0.3)
    for text, size, bold, height in (
        (metadata.title, th["font_size_title"], True, 0.45),
        (metadata.subtitle, th["font_size_subtitle"], False, 0.4),
    ):
        if not text:
            continue
        txbox = slide.shapes.add_textbox(Inches(0.5), top, Inches(12), Inches(height))
        tf = txbox.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = text
        p.font.size = Pt(size)
        p.font.bold = bold
        p.font.name = th["font_name"]
        top += Inches(height)
    return top + Inches(0.1)


def _add_footnotes(slide: Any, footnotes: list[str], top: Any, th: dict[str, Any]) -> None:
    """Add the footnote text box below the table."""
    if not footnotes:
        return
    from pptx.dml.color import RGBColor  # type: ignore[import-untyped]
    from pptx.util import Inches, Pt  # type: ignore[import-untyped]

    txbox = slide.shapes.add_textbox(Inches(0.5), top + Inches(0.15), Inches(12), Inches(0.8))
    tf = txbox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = "\n".join(footnotes)
    p.font.size = Pt(th["font_size_footnote"])
    p.font.name = th["font_name"]
    p.font.color.rgb = RGBColor.from_string("666666")


# ── Summary table slide ──────────────────────────────────────────── #


def render_pptx(
    model: TableModel,
    path: str | Path,
    *,
    theme: dict[str, Any] | None = None,
    rows_per_page: int | None = None,
) -> Path:
    """Render a ``TableModel`` to a PPTX slide deck.

    Each slide contains a fully editable PowerPoint table with:
    - Title and subtitle from ``RenderMetadata``
    - Column headers with optional (N=xx) display
    - Row hierarchy with indentation and bold formatting
    - Footnotes rendered below the table

    Long tables are chunked across slides via the model-layer paginator
    (title, headers, and footnotes repeat per slide), so a 300-row table
    never lands on one unreadable slide.

    The output is editable: users can modify fonts, colours, text, and
    layout in PowerPoint or LibreOffice Impress after export.

    Args:
        model: The display-ready table model from ``ard_to_table_model()``.
        path: Output ``.pptx`` file path.
        theme: Optional dict of style overrides.  Keys include
            ``font_name``, ``font_size_body``, ``header_bg``, etc.
            See ``_DEFAULT_THEME`` for all available keys.
        rows_per_page: Body rows per slide (default 15 — what fits a
            16:9 slide at the default body font).

    Returns:
        Path: The written ``.pptx`` path.

    Raises:
        ImportError: If ``python-pptx`` is not installed.

    Examples:
        Render an AE summary ARD to editable slides::

            from fleet.tlg import ard_to_table_model, RenderMetadata
            from fleet.tlg.render.slides import render_pptx

            meta = RenderMetadata(title="Table 14.3.1.1", subtitle="AE Summary")
            model = ard_to_table_model(ard, meta)
            render_pptx(model, "ae_summary.pptx")
    """
    try:
        from pptx import Presentation  # type: ignore[import-untyped]
        from pptx.util import Emu, Inches, Pt  # type: ignore[import-untyped]
    except ImportError:
        raise ImportError(
            "python-pptx is required for PPTX slide export.\n"
            "Install it with:  uv add python-pptx\n"
            "Or:  pip install fleet-cdisc[tlg-pptx]"
        ) from None

    from pptx.dml.color import RGBColor  # type: ignore[import-untyped]
    from pptx.enum.text import PP_ALIGN  # type: ignore[import-untyped]

    th = _resolve_theme(theme)
    pages = paginate(model, rows_per_page=rows_per_page or _MAX_ROWS_PER_SLIDE)

    prs = Presentation()
    # Landscape 16:9
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    for page in pages:
        slide_layout = prs.slide_layouts[6]  # Blank layout
        slide = prs.slides.add_slide(slide_layout)
        top = _add_title_block(slide, page.metadata, th)

        # ── Table dimensions ──
        n_cols = 1 + len(page.columns)  # stub + arms
        n_rows = 1 + len(page.rows)  # header + data rows

        table_width = Inches(12.3)
        table_height = min(Inches(0.3) * n_rows, Inches(5.5))
        table_left = Inches(0.5)

        tbl_shape = slide.shapes.add_table(
            n_rows, n_cols, table_left, top, table_width, table_height
        )
        table = tbl_shape.table

        # Distribute column widths: stub gets 30%, rest evenly split
        stub_width = int(table_width * 0.30)
        arm_width = int((table_width - stub_width) / max(len(page.columns), 1))
        table.columns[0].width = Emu(stub_width)
        for ci in range(1, n_cols):
            table.columns[ci].width = Emu(arm_width)

        # ── Helper: set cell text + style ──
        def _set_cell(
            row_idx: int,
            col_idx: int,
            text: str,
            *,
            bold: bool = False,
            font_size: int | None = None,
            bg: str | None = None,
            fg: str | None = None,
            align: Any = PP_ALIGN.LEFT,
            table: Any = table,
        ) -> None:
            cell = table.cell(row_idx, col_idx)
            cell.text = ""
            p = cell.text_frame.paragraphs[0]
            p.text = text
            p.font.name = th["font_name"]
            p.font.size = Pt(font_size or th["font_size_body"])
            p.font.bold = bold
            p.alignment = align
            if fg:
                p.font.color.rgb = RGBColor.from_string(fg)
            if bg:
                cell.fill.solid()
                cell.fill.fore_color.rgb = RGBColor.from_string(bg)

        # ── Column headers ──
        _set_cell(0, 0, page.stub_label, bold=True, bg=th["header_bg"], fg=th["header_fg"])
        for ci, col in enumerate(page.columns, start=1):
            _set_cell(
                0,
                ci,
                col.display,
                bold=True,
                bg=th["header_bg"],
                fg=th["header_fg"],
                align=PP_ALIGN.CENTER,
            )

        # ── Data rows ──
        for ri, row in enumerate(page.rows, start=1):
            # Row background
            if row.row_type in ("group", "section"):
                bg = th["group_bg"]
            elif ri % 2 == 0:
                bg = th["alt_row_bg"]
            else:
                bg = None

            # Stub cell; the row model alone decides bold, as in HTML and RTF.
            indent_spaces = "  " * row.indent
            _set_cell(ri, 0, f"{indent_spaces}{row.label}", bold=row.bold, bg=bg)

            # Value cells
            for ci, col in enumerate(page.columns, start=1):
                val = row.cells.get(col.label, "")
                _set_cell(ri, ci, val, bold=row.bold, bg=bg, align=PP_ALIGN.CENTER)

        _add_footnotes(slide, page.metadata.footnotes, top + table_height, th)

    # ── Write ──
    p_out = Path(path)
    p_out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(p_out))
    return p_out


# ── Listing slide ─────────────────────────────────────────────────── #


def render_listing_pptx(
    model: ListingModel,
    path: str | Path,
    *,
    theme: dict[str, Any] | None = None,
    rows_per_page: int | None = None,
) -> Path:
    """Render a ``ListingModel`` to a PPTX slide deck.

    Each slide contains a flat data listing as an editable PowerPoint
    table.  Long listings are chunked across slides (title, headers,
    and footnotes repeat per slide).  The listing can be modified after
    export.

    Args:
        model: The display-ready listing model from ``listing_to_model()``.
        path: Output ``.pptx`` file path.
        theme: Optional dict of style overrides.
        rows_per_page: Data rows per slide (default 15).

    Returns:
        Path: The written ``.pptx`` path.

    Raises:
        ImportError: If ``python-pptx`` is not installed.

    Examples:
        Render an AE listing to editable slides::

            from fleet.tlg import listing_to_model, RenderMetadata
            from fleet.tlg.render.slides import render_listing_pptx

            meta = RenderMetadata(title="Listing 16.2.7.1", subtitle="AE Listing")
            model = listing_to_model(listing_df, meta)
            render_listing_pptx(model, "ae_listing.pptx")
    """
    try:
        from pptx import Presentation  # type: ignore[import-untyped]
        from pptx.util import Emu, Inches, Pt  # type: ignore[import-untyped]
    except ImportError:
        raise ImportError(
            "python-pptx is required for PPTX slide export.\n"
            "Install it with:  uv add python-pptx\n"
            "Or:  pip install fleet-cdisc[tlg-pptx]"
        ) from None

    from pptx.dml.color import RGBColor  # type: ignore[import-untyped]
    from pptx.enum.text import PP_ALIGN  # type: ignore[import-untyped]

    th = _resolve_theme(theme)
    pages = paginate_listing(model, rows_per_page=rows_per_page or _MAX_ROWS_PER_SLIDE)

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    for page in pages:
        slide_layout = prs.slide_layouts[6]  # Blank
        slide = prs.slides.add_slide(slide_layout)
        top = _add_title_block(slide, page.metadata, th)

        # ── Table ──
        n_cols = len(page.column_labels)
        n_rows = 1 + len(page.data)  # header + data

        table_width = Inches(12.3)
        table_height = min(Inches(0.3) * n_rows, Inches(5.5))
        table_left = Inches(0.5)

        tbl_shape = slide.shapes.add_table(
            n_rows, n_cols, table_left, top, table_width, table_height
        )
        table = tbl_shape.table

        col_width = int(table_width / max(n_cols, 1))
        for ci in range(n_cols):
            table.columns[ci].width = Emu(col_width)

        # Headers
        for ci, lbl in enumerate(page.column_labels):
            cell = table.cell(0, ci)
            cell.text = ""
            p = cell.text_frame.paragraphs[0]
            p.text = lbl
            p.font.name = th["font_name"]
            p.font.size = Pt(th["font_size_body"])
            p.font.bold = True
            p.alignment = PP_ALIGN.LEFT
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor.from_string(th["header_bg"])
            p.font.color.rgb = RGBColor.from_string(th["header_fg"])

        # Data rows
        for ri, row_data in enumerate(page.data, start=1):
            bg = th["alt_row_bg"] if ri % 2 == 0 else None
            for ci, lbl in enumerate(page.column_labels):
                cell = table.cell(ri, ci)
                cell.text = ""
                p = cell.text_frame.paragraphs[0]
                p.text = row_data.get(lbl, "")
                p.font.name = th["font_name"]
                p.font.size = Pt(th["font_size_body"])
                p.alignment = PP_ALIGN.LEFT
                if bg:
                    cell.fill.solid()
                    cell.fill.fore_color.rgb = RGBColor.from_string(bg)

        _add_footnotes(slide, page.metadata.footnotes, top + table_height, th)

    # ── Write ──
    p_out = Path(path)
    p_out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(p_out))
    return p_out
