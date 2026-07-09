"""
Pharma-style HTML table and listing renderer.

Produces submission-quality HTML tables from ``TableModel`` and
``ListingModel`` instances.  Supports optional HTML injection via
the ``html_wrapper`` parameter.

Usage::

    from fleet.tlg.render import ard_to_table_model, render_html, RenderMetadata

    meta = RenderMetadata(title="Table 14.3.1.1", subtitle="AE Summary")
    model = ard_to_table_model(ard, meta)
    html = render_html(model)

    # With injection into a wrapper template
    html = render_html(model, html_wrapper='<div class="report">{table}</div>')
"""

from __future__ import annotations

from ._models import ListingModel, TableModel, paginate, paginate_listing

# ------------------------------------------------------------------ #
# CSS — pharma submission style                                        #
# ------------------------------------------------------------------ #

_SUMMARY_CSS = """\
<style>
.fleet-table-container {
  font-family: "Courier New", Courier, monospace;
  font-size: 9pt;
  max-width: 100%;
  overflow-x: auto;
}
.fleet-table-title {
  font-weight: bold;
  font-size: 10pt;
  margin-bottom: 2px;
}
.fleet-table-subtitle {
  font-size: 9pt;
  margin-bottom: 6px;
}
.fleet-table-footnotes {
  font-size: 8pt;
  margin-top: 4px;
  color: #333;
}
.fleet-table-footnotes p {
  margin: 1px 0;
}
table.fleet-summary {
  border-collapse: collapse;
  width: 100%;
  font-family: "Courier New", Courier, monospace;
  font-size: 9pt;
}
table.fleet-summary thead th {
  border-top: 2px solid #000;
  border-bottom: 1px solid #000;
  padding: 4px 8px;
  text-align: center;
  vertical-align: bottom;
  white-space: pre-line;
  font-weight: bold;
}
table.fleet-summary thead th.stub-header {
  text-align: left;
}
table.fleet-summary tbody td {
  padding: 2px 8px;
  vertical-align: top;
}
table.fleet-summary tbody td.stub {
  text-align: left;
}
table.fleet-summary tbody td.stat-cell {
  text-align: center;
}
table.fleet-summary tbody tr.header-row td {
  padding-top: 4px;
}
table.fleet-summary tbody tr.header-row td.stub {
  font-weight: normal;
}
table.fleet-summary tbody tr.group-row td.stub,
table.fleet-summary tbody tr.section-row td.stub {
  font-weight: bold;
  padding-top: 6px;
}
table.fleet-summary tbody td.stub.indent-1 {
  padding-left: 24px;
}
table.fleet-summary tbody td.stub.indent-2 {
  padding-left: 48px;
}
table.fleet-summary tbody tr:last-child td {
  border-bottom: 2px solid #000;
}
table.fleet-summary tbody tr.separator-row td {
  border-top: 1px solid #000;
  padding: 0;
  height: 0;
  line-height: 0;
}
.fleet-page-footer {
  font-size: 8pt;
  text-align: right;
  margin-top: 4px;
}
/* Print-friendly */
@media print {
  .fleet-table-container { max-width: none; overflow: visible; }
  table.fleet-summary { page-break-inside: auto; }
  table.fleet-summary tr { page-break-inside: avoid; }
  .fleet-page { page-break-after: always; }
  .fleet-page:last-child { page-break-after: auto; }
}
</style>"""

_LISTING_CSS = """\
<style>
.fleet-listing-container {
  font-family: "Courier New", Courier, monospace;
  font-size: 9pt;
  max-width: 100%;
  overflow-x: auto;
}
.fleet-listing-title {
  font-weight: bold;
  font-size: 10pt;
  margin-bottom: 2px;
}
.fleet-listing-subtitle {
  font-size: 9pt;
  margin-bottom: 6px;
}
.fleet-listing-footnotes {
  font-size: 8pt;
  margin-top: 4px;
  color: #333;
}
.fleet-listing-footnotes p {
  margin: 1px 0;
}
table.fleet-listing {
  border-collapse: collapse;
  width: 100%;
  font-family: "Courier New", Courier, monospace;
  font-size: 9pt;
}
table.fleet-listing thead th {
  border-top: 2px solid #000;
  border-bottom: 1px solid #000;
  padding: 4px 8px;
  text-align: left;
  font-weight: bold;
}
table.fleet-listing tbody td {
  padding: 2px 8px;
  text-align: left;
  vertical-align: top;
}
table.fleet-listing tbody tr:last-child td {
  border-bottom: 2px solid #000;
}
.fleet-page-footer {
  font-size: 8pt;
  text-align: right;
  margin-top: 4px;
}
@media print {
  .fleet-listing-container { max-width: none; overflow: visible; }
  table.fleet-listing { page-break-inside: auto; }
  table.fleet-listing tr { page-break-inside: avoid; }
  .fleet-page { page-break-after: always; }
  .fleet-page:last-child { page-break-after: auto; }
}
</style>"""


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #


def _esc(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


# ------------------------------------------------------------------ #
# Summary table renderer                                               #
# ------------------------------------------------------------------ #


def _table_page_parts(model: TableModel, page_footer: str | None = None) -> list[str]:
    """HTML fragments for one page: title, table, footnotes, page footer."""
    parts: list[str] = []

    if model.metadata.title:
        parts.append(f'<div class="fleet-table-title">{_esc(model.metadata.title)}</div>')
    if model.metadata.subtitle:
        parts.append(f'<div class="fleet-table-subtitle">{_esc(model.metadata.subtitle)}</div>')

    # ── Table header ──
    parts.append('<table class="fleet-summary">')
    parts.append("<thead>")
    parts.append("<tr>")
    parts.append(f'<th class="stub-header">{_esc(model.stub_label)}</th>')
    for col in model.columns:
        parts.append(f"<th>{_esc(col.display)}</th>")
    parts.append("</tr>")
    parts.append("</thead>")

    # ── Table body ──
    parts.append("<tbody>")

    # Track whether we've seen header rows to insert a separator
    seen_header = False
    separator_inserted = False

    for row in model.rows:
        # Insert separator between header rows and hierarchy rows
        if row.row_type != "header" and seen_header and not separator_inserted:
            parts.append('<tr class="separator-row">')
            parts.append(f'<td colspan="{1 + len(model.columns)}"></td>')
            parts.append("</tr>")
            separator_inserted = True

        if row.row_type == "header":
            seen_header = True

        css_class = f"{row.row_type}-row"
        parts.append(f'<tr class="{css_class}">')

        # Stub cell (indent expressed as a CSS class)
        stub_class = "stub" if row.indent == 0 else f"stub indent-{row.indent}"
        parts.append(f'<td class="{stub_class}">{_esc(row.label)}</td>')

        # Stat cells
        for col in model.columns:
            val = _esc(row.cells.get(col.label, ""))
            parts.append(f'<td class="stat-cell">{val}</td>')

        parts.append("</tr>")

    parts.append("</tbody>")
    parts.append("</table>")

    # ── Footnotes ──
    if model.metadata.footnotes:
        parts.append('<div class="fleet-table-footnotes">')
        for fn in model.metadata.footnotes:
            parts.append(f"<p>{_esc(fn)}</p>")
        parts.append("</div>")

    if page_footer:
        parts.append(f'<div class="fleet-page-footer">{_esc(page_footer)}</div>')

    return parts


def render_html(
    model: TableModel,
    *,
    html_wrapper: str | None = None,
    rows_per_page: int | None = None,
    page_by: str | None = None,
) -> str:
    """Render a ``TableModel`` as a pharma-style HTML table.

    Pagination happens in the model layer (:func:`~fleet.tlg.render.paginate`):
    each page repeats title, column headers, and footnotes, carries a
    ``Page X of Y`` footer, and breaks on a real page in print/PDF media.

    Args:
        model: The display-ready table model from ``ard_to_table_model()``.
        html_wrapper: Optional HTML template string.  If given, the
            generated ``<table>`` block replaces the ``{table}`` placeholder,
            enabling embedding in sponsor portals, Quarto documents, or
            interactive dashboards.
        rows_per_page: Maximum body rows per page; ``None`` disables
            row-count splitting.
        page_by: ARD variable to page-break on (e.g. ``"PARAMCD"``).
            Defaults to ``model.metadata.page_by``.

    Returns:
        str: Complete HTML string (with ``<style>`` block) or injected
            into *html_wrapper*.

    Examples:
        Render an AE summary to HTML::

            ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl)
            model = ard_to_table_model(ard, RenderMetadata(title="Table 14.3.1.1"))
            html = render_html(model)
    """
    pages = paginate(model, rows_per_page=rows_per_page, page_by=page_by)

    parts: list[str] = ['<div class="fleet-table-container">', _SUMMARY_CSS]
    if len(pages) == 1:
        parts += _table_page_parts(pages[0])
    else:
        for idx, page in enumerate(pages, start=1):
            parts.append('<div class="fleet-page">')
            parts += _table_page_parts(page, page_footer=f"Page {idx} of {len(pages)}")
            parts.append("</div>")
    parts.append("</div>")

    html = "\n".join(parts)

    if html_wrapper is not None:
        return html_wrapper.replace("{table}", html)

    return html


# ------------------------------------------------------------------ #
# Listing renderer                                                     #
# ------------------------------------------------------------------ #


def _listing_page_parts(model: ListingModel, page_footer: str | None = None) -> list[str]:
    """HTML fragments for one listing page."""
    parts: list[str] = []

    if model.metadata.title:
        parts.append(f'<div class="fleet-listing-title">{_esc(model.metadata.title)}</div>')
    if model.metadata.subtitle:
        parts.append(f'<div class="fleet-listing-subtitle">{_esc(model.metadata.subtitle)}</div>')

    parts.append('<table class="fleet-listing">')

    # ── Header ──
    parts.append("<thead>")
    parts.append("<tr>")
    for label in model.column_labels:
        parts.append(f"<th>{_esc(label)}</th>")
    parts.append("</tr>")
    parts.append("</thead>")

    # ── Body ──
    parts.append("<tbody>")
    for row_data in model.data:
        parts.append("<tr>")
        for label in model.column_labels:
            val = _esc(row_data.get(label, ""))
            parts.append(f"<td>{val}</td>")
        parts.append("</tr>")
    parts.append("</tbody>")

    parts.append("</table>")

    if model.metadata.footnotes:
        parts.append('<div class="fleet-listing-footnotes">')
        for fn in model.metadata.footnotes:
            parts.append(f"<p>{_esc(fn)}</p>")
        parts.append("</div>")

    if page_footer:
        parts.append(f'<div class="fleet-page-footer">{_esc(page_footer)}</div>')

    return parts


def render_listing_html(
    model: ListingModel,
    *,
    html_wrapper: str | None = None,
    rows_per_page: int | None = None,
) -> str:
    """Render a ``ListingModel`` as a pharma-style HTML listing.

    Args:
        model: The display-ready listing model from ``listing_to_model()``.
        html_wrapper: Optional HTML template string with ``{table}``
            placeholder.
        rows_per_page: Maximum data rows per page; each page repeats
            title, column headers, and footnotes with a ``Page X of Y``
            footer.  ``None`` renders one continuous listing.

    Returns:
        str: Complete HTML string (with ``<style>`` block).

    Examples:
        Render an AE listing to HTML::

            listing = adae.tlg.ae.template("ael01").to_listing()
            model = listing_to_model(listing, RenderMetadata(title="Listing 16.2.7"))
            html = render_listing_html(model)
    """
    pages = paginate_listing(model, rows_per_page=rows_per_page)

    parts: list[str] = ['<div class="fleet-listing-container">', _LISTING_CSS]
    if len(pages) == 1:
        parts += _listing_page_parts(pages[0])
    else:
        for idx, page in enumerate(pages, start=1):
            parts.append('<div class="fleet-page">')
            parts += _listing_page_parts(page, page_footer=f"Page {idx} of {len(pages)}")
            parts.append("</div>")
    parts.append("</div>")

    html = "\n".join(parts)

    if html_wrapper is not None:
        return html_wrapper.replace("{table}", html)

    return html
