"""
TLG root namespace — registered as ``df.tlg``.

Provides sub-namespace properties for domain-specific TLG methods:
  - ``df.tlg.ae``  — AE tables and listings
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from fleet.tlg.ae_namespace import AETLGNamespace


@pl.api.register_dataframe_namespace("tlg")
class TLGNamespace:
    """Root TLG namespace, accessed as ``df.tlg``.

    This namespace acts as a router to domain-specific sub-namespaces.
    It holds a reference to the underlying DataFrame and passes it to
    sub-namespaces on property access.
    """

    def __init__(self, df: pl.DataFrame) -> None:
        self._df = df

    @property
    def ae(self) -> AETLGNamespace:
        """AE (adverse event) tables and listings."""
        from fleet.tlg.ae_namespace import AETLGNamespace

        return AETLGNamespace(self._df)

    def check(self) -> list[str]:
        """Run pre-validation diagnostics across all sub-namespaces.

        Returns:
            list[str]: Diagnostic messages from all sub-namespace specs.
        """
        from fleet.tlg.ae_namespace import AETLGNamespace

        diagnostics: list[str] = []
        ae_ns = AETLGNamespace(self._df)
        diagnostics.extend(ae_ns.check())
        return diagnostics
