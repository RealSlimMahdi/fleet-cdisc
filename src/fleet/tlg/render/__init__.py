"""
TLG render sub-module — ARD in, artifact out.

Provides shaping utilities to convert long-format ARD DataFrames into
display-ready table/listing models, model-layer pagination shared by
every output format, and renderers that produce HTML, PDF, RTF, and
editable PPTX slide deck artifacts.

Usage::

    from fleet.tlg.render import RenderMetadata, ard_to_table_model, render_html

    meta = RenderMetadata(title="Table 14.3.1.1", subtitle="AE Summary — Safety Population")
    model = ard_to_table_model(ard, meta)
    html = render_html(model)
"""

from ._models import (
    ListingModel,
    RenderMetadata,
    TableModel,
    ard_to_table_model,
    listing_to_model,
    paginate,
    paginate_listing,
)
from .html import render_html, render_listing_html
from .pdf import render_listing_pdf, render_pdf
from .rtf import render_listing_rtf, render_rtf
from .slides import render_listing_pptx, render_pptx

__all__ = [
    "RenderMetadata",
    "TableModel",
    "ListingModel",
    "ard_to_table_model",
    "listing_to_model",
    "paginate",
    "paginate_listing",
    "render_html",
    "render_listing_html",
    "render_pdf",
    "render_listing_pdf",
    "render_pptx",
    "render_listing_pptx",
    "render_rtf",
    "render_listing_rtf",
]
