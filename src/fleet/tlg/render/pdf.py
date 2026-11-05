"""
HTML → PDF renderer via WeasyPrint.

WeasyPrint is an **optional** dependency.  Install it with::

    uv add weasyprint
    # or: pip install fleet-cdisc[tlg-pdf]

When WeasyPrint is absent, ``render_pdf`` raises a clear ``ImportError``
with an install hint.  When its system libraries (Pango) are missing, the
``ImportError`` names them.

The PDF loads no external resource: a ``file:``, ``http:`` or ``data:``
URL in an ``html_wrapper`` (a logo, a style sheet, an attachment) is
refused, and each refused resource gives a ``UserWarning``.
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path
from typing import Any

from ._models import ListingModel, TableModel
from .html import render_html, render_listing_html

#: Print CSS of every PDF: landscape pages numbered "Page X of Y" by the
#: page counter, so a model page that overflows a physical page still
#: carries its number.  The model page footer would repeat it.
_PDF_CSS = (
    "@page { size: landscape; margin: 1cm 1cm 1.5cm 1cm;"
    " @bottom-right { content: 'Page ' counter(page) ' of ' counter(pages);"
    " font-family: 'Courier New', Courier, monospace; font-size: 8pt; } }"
    "body { font-family: 'Courier New', Courier, monospace; font-size: 9pt; }"
    ".fleet-page-footer { display: none; }"
)


def _weasyprint() -> Any:
    """Import WeasyPrint, with a hint for a missing package or library."""
    try:
        import weasyprint  # type: ignore[import-untyped]
    except ImportError:
        raise ImportError(
            "WeasyPrint is required for PDF export.\n"
            "Install it with:  uv add weasyprint\n"
            "Or:  pip install fleet-cdisc[tlg-pdf]"
        ) from None
    except OSError as exc:
        raise ImportError(
            "WeasyPrint is installed but its system libraries (Pango) are "
            "missing: see the WeasyPrint install page, "
            "https://doc.courtbouillon.org/weasyprint/stable/first_steps.html. "
            f"({exc})"
        ) from None
    return weasyprint


def _html_document(fragment: str) -> str:
    """Wrap an HTML fragment in the PDF document with the print CSS."""
    return (
        "<!DOCTYPE html>\n"
        '<html><head><meta charset="utf-8">'
        f"<style>{_PDF_CSS}</style></head><body>\n"
        f"{fragment}\n"
        "</body></html>"
    )


class _WarnHandler(logging.Handler):
    """Turn a WeasyPrint ERROR log record into a ``UserWarning``."""

    def emit(self, record: logging.LogRecord) -> None:
        warnings.warn(f"PDF export: {record.getMessage()}", UserWarning, stacklevel=2)


def _write_pdf(fragment: str, path: str | Path) -> Path:
    """Write *fragment* to a PDF that loads no external resource.

    A ``URLFetcher`` with no allowed protocol refuses every URL; each
    refused resource logs an error, which becomes a ``UserWarning``.
    """
    weasyprint = _weasyprint()
    from weasyprint.urls import URLFetcher  # type: ignore[import-untyped]

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("weasyprint")
    handler = _WarnHandler(level=logging.ERROR)
    log.addHandler(handler)
    try:
        weasyprint.HTML(
            string=_html_document(fragment), url_fetcher=URLFetcher(allowed_protocols=())
        ).write_pdf(str(p))
    finally:
        log.removeHandler(handler)
    return p


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
    pages with repeated title, column headers, and footnotes.  Every
    physical page carries ``Page X of Y`` from the PDF page counter.  A
    page that starts inside a block repeats its parent rows with
    ``(continued)``.  The PDF loads no external resource (see the module
    docstring).

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
        ImportError: If WeasyPrint or its system libraries are not
            installed.

    References:
        ADR-0040 (40 rows per page by default, continued parent rows).

    Examples:
        Render an AE summary to PDF::

            spec = AESummarySpec(adsl_group_col="TRT01A")
            ard = adae.tlg.ae.t_summary(spec=spec, adsl=adsl)
            model = ard_to_table_model(ard, RenderMetadata(title="Table 14.3.1.1"))
            render_pdf(model, "ae_summary.pdf")
    """
    _weasyprint()
    html = render_html(
        model, html_wrapper=html_wrapper, rows_per_page=rows_per_page, page_by=page_by
    )
    return _write_pdf(html, path)


def render_listing_pdf(
    model: ListingModel,
    path: str | Path,
    *,
    html_wrapper: str | None = None,
    rows_per_page: int | None = None,
) -> Path:
    """Render a ``ListingModel`` to a PDF file via WeasyPrint.

    Every physical page carries ``Page X of Y`` from the PDF page
    counter.  The PDF loads no external resource.

    Args:
        model: The display-ready listing model.
        path: Output PDF file path.
        html_wrapper: Optional HTML template with ``{table}`` placeholder.
        rows_per_page: Maximum data rows per page; ``None`` renders one
            continuous listing.

    Returns:
        Path: The written PDF path.

    Raises:
        ImportError: If WeasyPrint or its system libraries are not
            installed.

    Examples:
        Render an AE listing to PDF::

            listing = adae.tlg.ae.template("ael01").to_listing()
            model = listing_to_model(listing, RenderMetadata(title="Listing 16.2.7"))
            render_listing_pdf(model, "ae_listing.pdf")
    """
    _weasyprint()
    html = render_listing_html(model, html_wrapper=html_wrapper, rows_per_page=rows_per_page)
    return _write_pdf(html, path)
