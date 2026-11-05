"""
Pharma-style RTF renderer — the de facto submission/QC format.

Pure stdlib (no dependencies).  Conventions model r2rtf: Courier New
9pt on landscape US Letter, a horizontal rule above and below the
column-header row and below the last body row, and column headers
repeated on every page.  By default the title goes in the Word page
header and the footnotes in the page footer (the SAS ODS RTF default);
``body_title=True`` writes them in the body at each page break (ODS RTF
BODYTITLE).  The footer always holds ``Page X of Y`` as Word PAGE and
NUMPAGES fields, so each physical page carries its own number.

Pagination comes from the model layer
(:func:`~fleet.tlg.render.paginate`), with a page budget measured in
points: title, header lines, footnotes and wrapped rows all count, and
``rows_per_page`` stays as a cap.  See ADR-0040.

Usage::

    from fleet.tlg.render import ard_to_table_model, render_rtf, RenderMetadata

    meta = RenderMetadata(title="Table 14.3.1.1", subtitle="AE Summary")
    model = ard_to_table_model(ard, meta)
    rtf = render_rtf(model, "ae_summary.rtf")
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from ._models import (
    ListingModel,
    RenderMetadata,
    TableModel,
    TableRow,
    _paginate,
    _paginate_listing,
)

# ── Page geometry (landscape US Letter, 1in margins, twips) ─────────── #

_PAGE_W = 15840
_PAGE_H = 12240
_MARGIN = 1440
_USABLE_W = _PAGE_W - 2 * _MARGIN

#: Distance of the Word page header and footer from the page edge (twips).
_HEADER_Y = 720

#: Default body rows per page at 9pt on landscape letter (a cap; the
#: point budget can give fewer).
_DEFAULT_ROWS_PER_PAGE = 40

#: Font sizes in half-points (RTF convention): 9pt body, 10pt title, 8pt notes.
_FS_BODY = 18
_FS_TITLE = 20
_FS_NOTE = 16

#: Line heights in points (1.2 x font size, on the safe side of Word's
#: Courier New line of 1.13 x font size).
_LINE_BODY = 10.8
_LINE_TITLE = 12.0
_LINE_NOTE = 9.6

#: Space before or after a spacer paragraph (``\sa120`` / ``\sb120``), points.
_SPACE = 6.0

#: Points kept free for table borders and the page-break paragraph.
_SAFETY = 4.0

#: Courier New advance width (0.6 em) in twips at 9pt, 10pt and 8pt.
_CHAR_BODY = 108
_CHAR_TITLE = 120
_CHAR_NOTE = 96

#: Horizontal cell padding in twips (``\trgaph108`` on each side).
_CELL_PAD = 216

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
    rf"\headery{_HEADER_Y}\footery{_HEADER_Y}"
    rf"\f0\fs{_FS_BODY}"
)

#: Usable body height in points between the top and bottom margins.
_BODY_H = (_PAGE_H - 2 * _MARGIN) / 20

#: Room in points for the page header or footer before it pushes the body.
_MARGIN_ROOM = (_MARGIN - _HEADER_Y) / 20

_PAGE_COUNTER = (
    r"Page {\field{\*\fldinst PAGE}{\fldrslt 1}} of {\field{\*\fldinst NUMPAGES}{\fldrslt 1}}"
)

_PAGE_BREAK = r"{\pard\fs2\page\par}"
_DOC_END = r"{\pard\fs2\par}"


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


def _lines(text: str, width_twips: int, char_twips: int) -> int:
    """Lines a paragraph takes when Word wraps *text* at *width_twips*."""
    chars = max(width_twips // char_twips, 1)
    return sum(max(len(textwrap.wrap(seg, chars)), 1) for seg in text.split("\n"))


def _row_height(cells: list[str], widths: list[int], indent: int = 0) -> float:
    """Height in points of one table row, with wrapped cell text."""
    lines = 1
    for idx, (text, width) in enumerate(zip(cells, widths)):
        usable = width - _CELL_PAD - (indent * _INDENT_TWIPS if idx == 0 else 0)
        lines = max(lines, _lines(text, usable, _CHAR_BODY))
    return lines * _LINE_BODY


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


def _title_height(title: str, subtitle: str) -> float:
    """Height in points of :func:`_title_block`."""
    if not (title or subtitle):
        return 0.0
    height = _LINE_BODY + _SPACE
    if title:
        height += _lines(title, _USABLE_W, _CHAR_TITLE) * _LINE_TITLE
    if subtitle:
        height += _lines(subtitle, _USABLE_W, _CHAR_BODY) * _LINE_BODY
    return height


def _footnote_block(footnotes: list[str], *, spacer: bool) -> list[str]:
    """Footnote paragraphs, after a spacer paragraph when *spacer* is set."""
    parts: list[str] = [r"\pard\sb120\par"] if footnotes and spacer else []
    for fn in footnotes:
        parts.append(rf"\pard\ql\fs{_FS_NOTE} {_esc(fn)}\fs{_FS_BODY}\par")
    return parts


def _footnote_height(footnotes: list[str], *, spacer: bool) -> float:
    """Height in points of :func:`_footnote_block`."""
    height = _LINE_BODY + _SPACE if footnotes and spacer else 0.0
    return height + sum(_lines(fn, _USABLE_W, _CHAR_NOTE) * _LINE_NOTE for fn in footnotes)


def _margin_groups(meta: RenderMetadata, *, body_title: bool) -> tuple[list[str], float]:
    """The Word page header and footer groups, and the body points they push away.

    The footer always holds the page counter as PAGE and NUMPAGES
    fields.  Without *body_title*, the header holds the title and the
    footer the footnotes too.  A header or footer taller than the room
    between the page edge and the margin pushes the body.
    """
    counter = rf"\pard\qr\fs{_FS_NOTE} {_PAGE_COUNTER}\fs{_FS_BODY}\par"
    if body_title:
        header: list[str] = []
        footer = [counter]
        header_h, footer_h = 0.0, _LINE_NOTE
    else:
        header = _title_block(meta.title, meta.subtitle)
        footer = [*_footnote_block(meta.footnotes, spacer=False), counter]
        header_h = _title_height(meta.title, meta.subtitle)
        footer_h = _footnote_height(meta.footnotes, spacer=False) + _LINE_NOTE
    groups = [r"{\header " + "".join(header) + "}"] if header else []
    groups.append(r"{\footer " + "".join(footer) + "}")
    pushed = max(0.0, header_h - _MARGIN_ROOM) + max(0.0, footer_h - _MARGIN_ROOM)
    return groups, pushed


def _page_budget(
    meta: RenderMetadata, header_cells: list[str], widths: list[int], *, body_title: bool
) -> tuple[list[str], float]:
    """The margin groups, and the points left for body rows on one page."""
    groups, pushed = _margin_groups(meta, body_title=body_title)
    fixed = pushed + _row_height(header_cells, widths) + _SAFETY
    if body_title:
        fixed += _title_height(meta.title, meta.subtitle)
        fixed += _footnote_height(meta.footnotes, spacer=True)
    return groups, _BODY_H - fixed


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
    body_title: bool = False,
) -> str:
    """Render a ``TableModel`` as a pharma-style RTF table.

    Every physical page carries the title, the column-header row (also
    flagged ``\\trhdr``), the footnotes, and ``Page X of Y`` from Word
    PAGE and NUMPAGES fields.  By default the title is in the Word page
    header and the footnotes in the page footer.  With *body_title*,
    they are body paragraphs, written again at each page break.  A page
    holds the rows that fit its height in points (title, header lines,
    footnotes and wrapped rows count), at most *rows_per_page*.  A page
    that starts inside a block repeats its parent rows with
    ``(continued)``.

    Args:
        model: The display-ready table model from ``ard_to_table_model()``.
        path: Optional output file path; the RTF is written when given.
        rows_per_page: Maximum body rows per page (default 40).  ``None``
            keeps only the height budget.
        page_by: ARD variable to page-break on (e.g. ``"PARAMCD"``).
            Defaults to ``model.metadata.page_by``.
        body_title: Write the title and footnotes in the document body
            (SAS ODS RTF BODYTITLE) instead of the page header and footer.
            A text check of the body then sees them, but the page header
            is empty.

    Returns:
        str: The complete RTF document.

    References:
        ADR-0040 (title placement, page fields, page budget).  SAS ODS
        RTF: titles and footnotes in the page header and footer unless
        BODYTITLE.  r2rtf ``rtf_page(nrow=)`` counts title, header and
        footnote lines in the page budget.

    Examples:
        Inline AE summary to a submission RTF::

            spec = AESummarySpec(adsl_group_col="TRT01A")
            ard = adae.tlg.ae.t_summary(spec=spec, adsl=adsl)
            model = ard_to_table_model(ard, RenderMetadata(title="Table 14.3.1.1"))
            render_rtf(model, "outputs/t_ae_summary.rtf")

        Title and footnotes in the body, as ODS RTF BODYTITLE::

            render_rtf(model, "outputs/t_ae_summary.rtf", body_title=True)
    """
    meta = model.metadata
    stub_w = int(_USABLE_W * 0.34)
    arm_w = (_USABLE_W - stub_w) // max(len(model.columns), 1)
    widths = [stub_w] + [arm_w] * len(model.columns)
    positions = _cell_positions(widths)
    aligns = [r"\ql"] + [r"\qc"] * len(model.columns)
    header_cells = [model.stub_label] + [col.display for col in model.columns]

    def row_cells(row: TableRow) -> list[str]:
        return [row.label] + [row.cells.get(col.label, "") for col in model.columns]

    groups, budget = _page_budget(meta, header_cells, widths, body_title=body_title)
    pages = _paginate(
        model,
        rows_per_page=rows_per_page,
        page_by=page_by,
        row_cost=lambda row: _row_height(row_cells(row), widths, row.indent),
        budget=budget,
    )

    parts: list[str] = [_DOC_HEADER, *groups]
    for idx, page in enumerate(pages, start=1):
        if idx > 1:
            parts.append(_PAGE_BREAK)
        if body_title:
            parts += _title_block(meta.title, meta.subtitle)

        # Column headers: heavy rule above, light rule below.
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
            parts.append(
                _row_rtf(
                    row_cells(row),
                    positions,
                    aligns,
                    bold=row.bold,
                    indent=row.indent,
                    border_bottom=_BDR_HEAVY if r_idx == len(page.rows) - 1 else None,
                )
            )

        if body_title:
            parts += _footnote_block(meta.footnotes, spacer=True)

    parts += [_DOC_END, "}"]
    return _write("\n".join(parts), path)


# ------------------------------------------------------------------ #
# Listing renderer                                                     #
# ------------------------------------------------------------------ #


def render_listing_rtf(
    model: ListingModel,
    path: str | Path | None = None,
    *,
    rows_per_page: int | None = _DEFAULT_ROWS_PER_PAGE,
    body_title: bool = False,
) -> str:
    """Render a ``ListingModel`` as a pharma-style RTF listing.

    The page layout follows :func:`render_rtf`: title and footnotes in
    the page header and footer (or in the body with *body_title*),
    ``Page X of Y`` from Word fields, and a page budget in points that
    counts wrapped rows.

    Args:
        model: The display-ready listing model from ``listing_to_model()``.
        path: Optional output file path; the RTF is written when given.
        rows_per_page: Maximum data rows per page (default 40).  ``None``
            keeps only the height budget.
        body_title: Write the title and footnotes in the document body
            instead of the page header and footer.

    Returns:
        str: The complete RTF document.

    References:
        ADR-0040 (title placement, page fields, page budget).

    Examples:
        Lab abnormalities listing to RTF::

            listing = adlb.tlg.lb.l_listing()
            model = listing_to_model(listing, RenderMetadata(title="Listing 16.2.8.1"))
            render_listing_rtf(model, "outputs/l_lb_abnormal.rtf")
    """
    meta = model.metadata
    n_cols = max(len(model.column_labels), 1)
    widths = [_USABLE_W // n_cols] * n_cols
    positions = _cell_positions(widths)
    aligns = [r"\ql"] * n_cols
    header_cells = list(model.column_labels)

    def row_cells(row_data: dict[str, str]) -> list[str]:
        return [row_data.get(label, "") for label in model.column_labels]

    groups, budget = _page_budget(meta, header_cells, widths, body_title=body_title)
    pages = _paginate_listing(
        model,
        rows_per_page=rows_per_page,
        row_cost=lambda row_data: _row_height(row_cells(row_data), widths),
        budget=budget,
    )

    parts: list[str] = [_DOC_HEADER, *groups]
    for idx, page in enumerate(pages, start=1):
        if idx > 1:
            parts.append(_PAGE_BREAK)
        if body_title:
            parts += _title_block(meta.title, meta.subtitle)

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

        for r_idx, row_data in enumerate(page.data):
            parts.append(
                _row_rtf(
                    row_cells(row_data),
                    positions,
                    aligns,
                    border_bottom=_BDR_HEAVY if r_idx == len(page.data) - 1 else None,
                )
            )

        if body_title:
            parts += _footnote_block(meta.footnotes, spacer=True)

    parts += [_DOC_END, "}"]
    return _write("\n".join(parts), path)
