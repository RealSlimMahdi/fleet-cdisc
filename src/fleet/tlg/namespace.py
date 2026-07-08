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

    def catalog(self) -> pl.DataFrame:
        """Return the TLG template catalog (built-ins + user templates).

        Passthrough to [`fleet.tlg.catalog()`][fleet.tlg.catalog] so the
        catalog is discoverable from any DataFrame.

        Returns:
            pl.DataFrame: One row per registered template — ``id``,
                ``title``, ``cdisc_class``, ``namespace``, ``method``,
                ``output_type``, ``domains``, ``source_ref``, ``status``.

        Examples:
            ``adae.tlg.catalog().filter(pl.col("namespace") == "ae")``
        """
        from ._registry import catalog as _catalog

        return _catalog()

    def check(self) -> list[str]:
        """Run pre-validation diagnostics on every applicable sub-namespace.

        A sub-namespace is *applicable* when its default summary spec's
        required columns are all present in the DataFrame — e.g. a frame
        with ``AEBODSYS``/``AEDECOD`` triggers the AE checks, one with
        ``PARAMCD``/``AVAL`` the findings checks.  Namespaces whose
        required columns are absent are skipped (they would only report
        that this isn't their dataset).

        Returns:
            list[str]: Diagnostic messages prefixed with the namespace
                name, or a single message when no sub-namespace applies.

        Examples:
            ``report = adae.tlg.check()``
        """
        from ._runner import NAMESPACE_CLASSES

        available = set(self._df.columns)
        diagnostics: list[str] = []
        applicable = 0
        for name, ns_cls in NAMESPACE_CLASSES.items():
            spec_cls = getattr(ns_cls, "_builder_specs", {}).get("t_summary")
            if spec_cls is None:
                continue
            spec = spec_cls()
            if not set(spec.required_columns) <= available:
                continue
            applicable += 1
            diagnostics.extend(f"[{name}] {msg}" for msg in ns_cls(self._df).check())
        if applicable == 0:
            diagnostics.append(
                "NO APPLICABLE NAMESPACE: no sub-namespace's required columns "
                f"are all present (available: {sorted(available)}). Run "
                "df.tlg.<ns>.check() directly for a specific diagnosis."
            )
        return diagnostics
