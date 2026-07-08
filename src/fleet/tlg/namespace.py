"""
TLG root namespace — registered as ``df.tlg``.

Provides sub-namespace properties for domain-specific TLG methods:
  - ``df.tlg.ae``  — AE tables and listings
  - ``df.tlg.vs``  — vital-signs summary tables
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from .ae_namespace import AETLGNamespace
    from .cm_namespace import CMTLGNamespace
    from .dm_namespace import DMTLGNamespace
    from .ds_namespace import DSTLGNamespace
    from .eg_namespace import EGTLGNamespace
    from .ex_namespace import EXTLGNamespace
    from .lb_namespace import LBTLGNamespace
    from .mh_namespace import MHTLGNamespace
    from .vs_namespace import VSTLGNamespace


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
        from .ae_namespace import AETLGNamespace

        return AETLGNamespace(self._df)

    @property
    def vs(self) -> VSTLGNamespace:
        """Vital-signs summary tables."""
        from .vs_namespace import VSTLGNamespace

        return VSTLGNamespace(self._df)

    @property
    def cm(self) -> CMTLGNamespace:
        """Concomitant-medication tables."""
        from .cm_namespace import CMTLGNamespace

        return CMTLGNamespace(self._df)

    @property
    def ex(self) -> EXTLGNamespace:
        """Exposure tables."""
        from .ex_namespace import EXTLGNamespace

        return EXTLGNamespace(self._df)

    @property
    def dm(self) -> DMTLGNamespace:
        """Demographic tables."""
        from .dm_namespace import DMTLGNamespace

        return DMTLGNamespace(self._df)

    @property
    def ds(self) -> DSTLGNamespace:
        """Disposition, deaths, enrollment, and deviation tables."""
        from .ds_namespace import DSTLGNamespace

        return DSTLGNamespace(self._df)

    @property
    def eg(self) -> EGTLGNamespace:
        """ECG summary tables."""
        from .eg_namespace import EGTLGNamespace

        return EGTLGNamespace(self._df)

    @property
    def lb(self) -> LBTLGNamespace:
        """Laboratory tables and listings."""
        from .lb_namespace import LBTLGNamespace

        return LBTLGNamespace(self._df)

    @property
    def mh(self) -> MHTLGNamespace:
        """Medical-history tables."""
        from .mh_namespace import MHTLGNamespace

        return MHTLGNamespace(self._df)

    def check(self) -> list[str]:
        """Run pre-validation diagnostics across all sub-namespaces.

        Returns:
            list[str]: Diagnostic messages from all sub-namespace specs.
        """
        from .ae_namespace import AETLGNamespace

        diagnostics: list[str] = []
        ae_ns = AETLGNamespace(self._df)
        diagnostics.extend(ae_ns.check())
        return diagnostics
