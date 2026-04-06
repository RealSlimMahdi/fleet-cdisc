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
from ._specs import (
    AEListingSpec,
    AESummarySpec,
    Column,
    GroupPool,
    Row,
    Statistic,
    TLGSpec,
    VSSummarySpec,
)
from .ae_namespace import AETLGNamespace
from .namespace import TLGNamespace

__all__ = [
    # Namespace
    "TLGNamespace",
    "AETLGNamespace",
    # Specs
    "TLGSpec",
    "AESummarySpec",
    "AEListingSpec",
    "VSSummarySpec",
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
]
