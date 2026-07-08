"""
Pharma-style RTF renderer — the de facto submission/QC format.

Pure stdlib (no dependencies).  Conventions model r2rtf: Courier New
9pt on landscape US Letter, a horizontal rule above and below the
column-header row and below the last body row, repeated title block and
column headers on every page, footnote block, and a right-aligned
``Page X of Y`` footer.  Pagination comes from the model layer
(:func:`~fleet.tlg.render.paginate`) so RTF pages match the HTML/PDF
page composition exactly.

Usage::

    from fleet.tlg.render import ard_to_table_model, render_rtf, RenderMetadata

    meta = RenderMetadata(title="Table 14.3.1.1", subtitle="AE Summary")
    model = ard_to_table_model(ard, meta)
    rtf = render_rtf(model, "ae_summary.rtf")
"""

from __future__ import annotations

from pathlib import Path

from ._models import ListingModel, TableModel, paginate, paginate_listing

# ── Page geometry (landscape US Letter, 1in margins, twips) ─────────── #

_PAGE_W = 15840
_PAGE_H = 12240
_MARGIN = 1440
_USABLE_W = _PAGE_W - 2 * _MARGIN

#: Default body rows per page at 9pt on landscape letter.
_DEFAULT_ROWS_PER_PAGE = 40

#: Font sizes in half-points (RTF convention): 9pt body, 10pt title, 8pt notes.
_FS_BODY = 18
_FS_TITLE = 20
_FS_NOTE = 16

#: Border widths in twips: heavy outer rule, light header rule.
_BDR_HEAVY = 30
_BDR_LIGHT = 15

#: Twips of stub indentation per indent level.
_INDENT_TWIPS = 240

_DOC_HEADER = (
    r"{\rtf1\ansi\deff0"
    r"{\fonttbl{\f0\fmodern\fcharset0 Courier New;}}"
    rf"\paperw{_PAGE_W}\paperh{_PAGE_H}\landscape"
    rf"\margl{_MARGIN}\margr{_MARGIN}\margt{_MARGIN}\margb{_MARGIN}"
    rf"\f0\fs{_FS_BODY}"
)


def _esc(text: str) -> str:
    """Escape RTF control characters and encode non-ASCII as ``\\uN?``."""
    out: list[str] = []
    for ch in text:
        if ch in "\\{}":
            out.append("\\" + ch)
        elif ch == "\n":
            out.append(r"\line ")
        elif ord(ch) > 127:
            code = ord(ch)
            if code > 32767:  # RTF \u takes a signed 16-bit value
                code -= 65536
            out.append(rf"\u{code}?")
        else:
            out.append(ch)
    return "".join(out)


def _cell_positions(widths: list[int]) -> list[int]:
    """Cumulative right-edge positions (``\\cellx``) from cell widths."""
    positions: list[int] = []
    edge = 0
    for w in widths:
        edge += w
        positions.append(edge)
    return positions


def _row_rtf(
    cells: list[str],
    positions: list[int],
    aligns: list[str],
    *,
    header: bool = False,
    bold: bool = False,
    indent: int = 0,
    border_top: int | None = None,
    border_bottom: int | None = None,
) -> str:
    """One RTF table row: cell definitions, then cell contents.

    The first cell is the stub (left-aligned, indented); *aligns* holds
    one paragraph-alignment control word per cell (``\\ql``/``\\qc``).
    """
    parts: list[str] = [r"\trowd\trgaph108\trleft0"]
    if header:
        parts.append(r"\trhdr")
    for pos in positions:
        borders = ""
        if border_top is not None:
            borders += rf"\clbrdrt\brdrs\brdrw{border_top}"
        if border_bottom is not None:
            borders += rf"\clbrdrb\brdrs\brdrw{border_bottom}"
        parts.append(rf"{borders}\cellx{pos}")
    parts.append("\n")
    for idx, (text, align) in enumerate(zip(cells, aligns)):
        li = rf"\li{indent * _INDENT_TWIPS}" if idx == 0 and indent else ""
        content = _esc(text)
        if bold or header:
            content = rf"\b {content}\b0"
        parts.append(rf"\pard\intbl{align}{li} {content}\cell")
    parts.append(r"\row")
    return "".join(parts)


def _title_block(title: str, subtitle: str) -> list[str]:
    """Centered title/subtitle paragraphs (r2rtf convention)."""
    parts: list[str] = []
    if title:
        parts.append(rf"\pard\qc\b\fs{_FS_TITLE} {_esc(title)}\b0\fs{_FS_BODY}\par")
    if subtitle:
        parts.append(rf"\pard\qc {_esc(subtitle)}\par")
    if title or subtitle:
        parts.append(r"\pard\sa120\par")
    return parts


def _footer_block(footnotes: list[str], page_footer: str) -> list[str]:
    """Footnote paragraphs and the right-aligned page counter."""
    parts: list[str] = []
    if footnotes:
        parts.append(r"\pard\sb120\par")
        for fn in footnotes:
            parts.append(rf"\pard\ql\fs{_FS_NOTE} {_esc(fn)}\fs{_FS_BODY}\par")
    parts.append(rf"\pard\qr\fs{_FS_NOTE} {_esc(page_footer)}\fs{_FS_BODY}\par")
    return parts


def _write(rtf: str, path: str | Path | None) -> str:
    """Write *rtf* to *path* when given; always return the string."""
    if path is not None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(rtf, encoding="ascii")
    return rtf


# ------------------------------------------------------------------ #
# Summary table renderer                                               #
# ------------------------------------------------------------------ #


def render_rtf(
    model: TableModel,
    path: str | Path | None = None,
    *,
    rows_per_page: int | None = _DEFAULT_ROWS_PER_PAGE,
    page_by: str | None = None,
) -> str:
    """Render a ``TableModel`` as a pharma-style RTF table.

    Every page carries the title block, the column-header row (also
    flagged ``\\trhdr`` so word processors repeat it on overflow), the
    footnote block, and a ``Page X of Y`` footer.

    Args:
        model: The display-ready table model from ``ard_to_table_model()``.
        path: Optional output file path; the RTF is written when given.
        rows_per_page: Maximum body rows per page (default 40, sized for
            9pt landscape letter).  ``None`` disables row-count splitting.
        page_by: ARD variable to page-break on (e.g. ``"PARAMCD"``).
            Defaults to ``model.metadata.page_by``.

    Returns:
        str: The complete RTF document.

    Examples:
        Inline AE summary to a submission RTF::

            ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl)
            model = ard_to_table_model(ard, RenderMetadata(title="Table 14.3.1.1"))
            render_rtf(model, "outputs/t_ae_summary.rtf")
    """
    pages = paginate(model, rows_per_page=rows_per_page, page_by=page_by)

    stub_w = int(_USABLE_W * 0.34)
    arm_w = (_USABLE_W - stub_w) // max(len(model.columns), 1)
    positions = _cell_positions([stub_w] + [arm_w] * len(model.columns))
    aligns = [r"\ql"] + [r"\qc"] * len(model.columns)

    parts: list[str] = [_DOC_HEADER]
    for idx, page in enumerate(pages, start=1):
        if idx > 1:
            parts.append(r"\page")
        parts += _title_block(page.metadata.title, page.metadata.subtitle)

        # Column headers: heavy rule above, light rule below.
        header_cells = [page.stub_label] + [col.display for col in page.columns]
        parts.append(
            _row_rtf(
                header_cells,
                positions,
                aligns,
                header=True,
                border_top=_BDR_HEAVY,
                border_bottom=_BDR_LIGHT,
            )
        )

        for r_idx, row in enumerate(page.rows):
            cells = [row.label] + [row.cells.get(col.label, "") for col in page.columns]
            parts.append(
                _row_rtf(
                    cells,
                    positions,
                    aligns,
                    bold=row.bold,
                    indent=row.indent,
                    border_bottom=_BDR_HEAVY if r_idx == len(page.rows) - 1 else None,
                )
            )

        parts += _footer_block(page.metadata.footnotes, f"Page {idx} of {len(pages)}")

    parts.append("}")
    return _write("\n".join(parts), path)


# ------------------------------------------------------------------ #
# Listing renderer                                                     #
# ------------------------------------------------------------------ #


def render_listing_rtf(
    model: ListingModel,
    path: str | Path | None = None,
    *,
    rows_per_page: int | None = _DEFAULT_ROWS_PER_PAGE,
) -> str:
    """Render a ``ListingModel`` as a pharma-style RTF listing.

    Args:
        model: The display-ready listing model from ``listing_to_model()``.
        path: Optional output file path; the RTF is written when given.
        rows_per_page: Maximum data rows per page (default 40).  ``None``
            renders one continuous listing.

    Returns:
        str: The complete RTF document.

    Examples:
        Lab abnormalities listing to RTF::

            listing = adlb.tlg.lb.l_listing()
            model = listing_to_model(listing, RenderMetadata(title="Listing 16.2.8.1"))
            render_listing_rtf(model, "outputs/l_lb_abnormal.rtf")
    """
    pages = paginate_listing(model, rows_per_page=rows_per_page)

    n_cols = max(len(model.column_labels), 1)
    col_w = _USABLE_W // n_cols
    positions = _cell_positions([col_w] * n_cols)
    aligns = [r"\ql"] * n_cols

    parts: list[str] = [_DOC_HEADER]
    for idx, page in enumerate(pages, start=1):
        if idx > 1:
            parts.append(r"\page")
        parts += _title_block(page.metadata.title, page.metadata.subtitle)

        parts.append(
            _row_rtf(
                list(page.column_labels),
                positions,
                aligns,
                header=True,
                border_top=_BDR_HEAVY,
                border_bottom=_BDR_LIGHT,
            )
        )

        for r_idx, row_data in enumerate(page.data):
            cells = [row_data.get(label, "") for label in page.column_labels]
            parts.append(
                _row_rtf(
                    cells,
                    positions,
                    aligns,
                    border_bottom=_BDR_HEAVY if r_idx == len(page.data) - 1 else None,
                )
            )

        parts += _footer_block(page.metadata.footnotes, f"Page {idx} of {len(pages)}")

    parts.append("}")
    return _write("\n".join(parts), path)
