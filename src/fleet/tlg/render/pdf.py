"""
HTML → PDF renderer via WeasyPrint.

WeasyPrint is an **optional** dependency.  Install it with::

    uv add weasyprint
    # or: pip install fleet-cdisc[tlg-pdf]

When WeasyPrint is absent, ``render_pdf`` raises a clear ``ImportError``
with an install hint.
"""

from __future__ import annotations

from pathlib import Path

from ._models import ListingModel, TableModel
from .html import render_html, render_listing_html


def render_pdf(
    model: TableModel,
    path: str | Path,
    *,
    html_wrapper: str | None = None,
    rows_per_page: int | None = 40,
    page_by: str | None = None,
) -> Path:
    """Render a ``TableModel`` to a PDF file via WeasyPrint.

    Pagination comes from the model layer: pages break on real PDF
    pages with repeated title, column headers, and footnotes, plus a
    ``Page X of Y`` footer.  A page that starts inside a block repeats
    its parent rows with ``(continued)``.

    Args:
        model: The display-ready table model.
        path: Output PDF file path.
        html_wrapper: Optional HTML template with ``{table}`` placeholder.
        rows_per_page: Maximum body rows per page (default 40, as
            ``render_rtf``); ``None`` disables row-count splitting.
        page_by: ARD variable to page-break on (e.g. ``"PARAMCD"``).
            Defaults to ``model.metadata.page_by``.

    Returns:
        Path: The written PDF path.

    Raises:
        ImportError: If WeasyPrint is not installed.

    References:
        ADR-0041 (40 rows per page by default, continued parent rows).

    Examples:
        Render an AE summary to PDF::

            ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl)
            model = ard_to_table_model(ard, RenderMetadata(title="Table 14.3.1.1"))
            render_pdf(model, "ae_summary.pdf")
    """
    try:
        import weasyprint  # type: ignore[import-untyped]
    except ImportError:
        raise ImportError(
            "WeasyPrint is required for PDF export.\n"
            "Install it with:  uv add weasyprint\n"
            "Or:  pip install fleet-cdisc[tlg-pdf]"
        ) from None

    html = render_html(
        model, html_wrapper=html_wrapper, rows_per_page=rows_per_page, page_by=page_by
    )
    # Wrap in a minimal HTML document for WeasyPrint
    doc = (
        "<!DOCTYPE html>\n"
        '<html><head><meta charset="utf-8">'
        "<style>"
        "@page { size: landscape; margin: 1cm; }"
        "body { font-family: 'Courier New', Courier, monospace; font-size: 9pt; }"
        "</style></head><body>\n"
        f"{html}\n"
        "</body></html>"
    )
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    weasyprint.HTML(string=doc).write_pdf(str(p))
    return p


def render_listing_pdf(
    model: ListingModel,
    path: str | Path,
    *,
    html_wrapper: str | None = None,
    rows_per_page: int | None = None,
) -> Path:
    """Render a ``ListingModel`` to a PDF file via WeasyPrint.

    Args:
        model: The display-ready listing model.
        path: Output PDF file path.
        html_wrapper: Optional HTML template with ``{table}`` placeholder.
        rows_per_page: Maximum data rows per page; ``None`` renders one
            continuous listing.

    Returns:
        Path: The written PDF path.

    Raises:
        ImportError: If WeasyPrint is not installed.

    Examples:
        Render an AE listing to PDF::

            listing = adae.tlg.ae.template("ael01").to_listing()
            model = listing_to_model(listing, RenderMetadata(title="Listing 16.2.7"))
            render_listing_pdf(model, "ae_listing.pdf")
    """
    try:
        import weasyprint  # type: ignore[import-untyped]
    except ImportError:
        raise ImportError(
            "WeasyPrint is required for PDF export.\n"
            "Install it with:  uv add weasyprint\n"
            "Or:  pip install fleet-cdisc[tlg-pdf]"
        ) from None

    html = render_listing_html(model, html_wrapper=html_wrapper, rows_per_page=rows_per_page)
    doc = (
        "<!DOCTYPE html>\n"
        '<html><head><meta charset="utf-8">'
        "<style>"
        "@page { size: landscape; margin: 1cm; }"
        "body { font-family: 'Courier New', Courier, monospace; font-size: 9pt; }"
        "</style></head><body>\n"
        f"{html}\n"
        "</body></html>"
    )
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    weasyprint.HTML(string=doc).write_pdf(str(p))
    return p
