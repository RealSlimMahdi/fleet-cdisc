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
) -> Path:
    """Render a ``TableModel`` to a PDF file via WeasyPrint.

    Args:
        model: The display-ready table model.
        path: Output PDF file path.
        html_wrapper: Optional HTML template with ``{table}`` placeholder.

    Returns:
        Path: The written PDF path.

    Raises:
        ImportError: If WeasyPrint is not installed.
    """
    try:
        import weasyprint  # type: ignore[import-untyped]
    except ImportError:
        raise ImportError(
            "WeasyPrint is required for PDF export.\n"
            "Install it with:  uv add weasyprint\n"
            "Or:  pip install fleet-cdisc[tlg-pdf]"
        ) from None

    html = render_html(model, html_wrapper=html_wrapper)
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
) -> Path:
    """Render a ``ListingModel`` to a PDF file via WeasyPrint.

    Args:
        model: The display-ready listing model.
        path: Output PDF file path.
        html_wrapper: Optional HTML template with ``{table}`` placeholder.

    Returns:
        Path: The written PDF path.

    Raises:
        ImportError: If WeasyPrint is not installed.
    """
    try:
        import weasyprint  # type: ignore[import-untyped]
    except ImportError:
        raise ImportError(
            "WeasyPrint is required for PDF export.\n"
            "Install it with:  uv add weasyprint\n"
            "Or:  pip install fleet-cdisc[tlg-pdf]"
        ) from None

    html = render_listing_html(model, html_wrapper=html_wrapper)
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
