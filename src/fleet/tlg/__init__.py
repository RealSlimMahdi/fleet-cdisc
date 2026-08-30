"""
TLG (Tables, Listings, Graphs) Polars namespace extension.

Registers ``df.tlg`` on every Polars DataFrame. Sub-structures are
accessed via properties:
  - ``df.tlg.ae``  — AE summary tables and listings
  - ``df.tlg.vs``  — Vital-signs summary tables

Usage
-----
    import fleet

    ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl)
"""

from ._ard import (
    ARD_COLUMN_ORDER,
    ARD_COLUMNS,
    ARD_GROUP_COLUMNS,
    ARD_REQUIRED_COLUMNS,
    ARD_SCHEMA,
    apply_fmt_fn,
    build_ard_row,
    default_fmt_fn,
    format_ard,
    validate_ard,
)
from ._builder import TLGBuilder
from ._registry import (
    TEMPLATES,
    CDISCClass,
    OutputType,
    Status,
    TemplateMeta,
    catalog,
    register_template,
    unregister_template,
)
from ._runner import (
    GROUPBY_CANDIDATES,
    NAMESPACE_CLASSES,
    detect_groupby,
    load_spec,
    run_spec,
    spec_schema,
)
from ._specs import (
    AEListingSpec,
    AESummarySpec,
    ChoiceOption,
    Column,
    GroupbyChoice,
    GroupPool,
    InteractiveBlock,
    OverallStat,
    Row,
    Statistic,
    SummarySpecBase,
    TLGSpec,
    VSSummarySpec,
    resolve_filter,
)
from ._variants import Variant, enumerate_variants
from .ae_namespace import (
    AEGradeSpec,
    AEOverviewSpec,
    AERelationshipSpec,
    AESeveritySpec,
    AESocPtSpec,
    AETLGNamespace,
)
from .cm_namespace import CMByPTSpec, CMSummarySpec, CMTLGNamespace
from .dm_namespace import DMSummarySpec, DMTLGNamespace
from .ds_namespace import (
    DSDeathsSpec,
    DSDeviationsSpec,
    DSDispositionSpec,
    DSEnrollmentSpec,
    DSTLGNamespace,
)
from .eg_namespace import EGChgSpec, EGQtcatSpec, EGSummarySpec, EGTLGNamespace
from .ex_namespace import EXSummarySpec, EXTLGNamespace
from .lb_namespace import (
    LBAbnormalSpec,
    LBChgSpec,
    LBListingSpec,
    LBShiftSpec,
    LBSummarySpec,
    LBTLGNamespace,
)
from .mh_namespace import MHSummarySpec, MHTLGNamespace
from .namespace import TLGNamespace
from .render import (
    ExplorerEntry,
    ListingModel,
    RenderMetadata,
    TableModel,
    ard_to_table_model,
    listing_to_model,
    paginate,
    paginate_listing,
    render_explorer,
    render_html,
    render_listing_html,
    render_listing_pdf,
    render_listing_pptx,
    render_listing_rtf,
    render_pdf,
    render_pptx,
    render_rtf,
)
from .vs_namespace import VSTLGNamespace

__all__ = [
    # Namespace
    "TLGNamespace",
    "AETLGNamespace",
    "VSTLGNamespace",
    "CMTLGNamespace",
    "EXTLGNamespace",
    "DMTLGNamespace",
    "DSTLGNamespace",
    "EGTLGNamespace",
    "LBTLGNamespace",
    "MHTLGNamespace",
    "TLGBuilder",
    # Specs
    "TLGSpec",
    "SummarySpecBase",
    "AESummarySpec",
    "AEOverviewSpec",
    "AESocPtSpec",
    "AESeveritySpec",
    "AEGradeSpec",
    "AERelationshipSpec",
    "AEListingSpec",
    "VSSummarySpec",
    "CMSummarySpec",
    "CMByPTSpec",
    "DMSummarySpec",
    "DSDispositionSpec",
    "DSDeathsSpec",
    "DSEnrollmentSpec",
    "DSDeviationsSpec",
    "EGSummarySpec",
    "EGChgSpec",
    "EGQtcatSpec",
    "EXSummarySpec",
    "LBSummarySpec",
    "LBChgSpec",
    "LBShiftSpec",
    "LBAbnormalSpec",
    "LBListingSpec",
    "MHSummarySpec",
    "OverallStat",
    "resolve_filter",
    # Interactive explorer
    "ChoiceOption",
    "GroupbyChoice",
    "InteractiveBlock",
    "Variant",
    "enumerate_variants",
    "ExplorerEntry",
    "render_explorer",
    # Registry
    "TEMPLATES",
    "TemplateMeta",
    "CDISCClass",
    "OutputType",
    "Status",
    "catalog",
    "register_template",
    "unregister_template",
    # YAML workflow
    "NAMESPACE_CLASSES",
    "GROUPBY_CANDIDATES",
    "detect_groupby",
    "load_spec",
    "run_spec",
    "spec_schema",
    # Building blocks
    "Row",
    "Column",
    "Statistic",
    "GroupPool",
    # ARD
    "ARD_SCHEMA",
    "ARD_COLUMNS",
    "ARD_COLUMN_ORDER",
    "ARD_REQUIRED_COLUMNS",
    "ARD_GROUP_COLUMNS",
    "build_ard_row",
    "validate_ard",
    "format_ard",
    "apply_fmt_fn",
    "default_fmt_fn",
    # Render
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
