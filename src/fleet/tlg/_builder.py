"""
TLG fluent builder — inline alternative to spec-driven ``t_summary()``.

``TLGBuilder`` accumulates state that maps 1:1 to a spec Pydantic model.
The builder is returned by the first verb call on a sub-namespace and
chains through to ``.to_ard()`` which materialises by constructing the
equivalent spec and delegating to ``t_summary()``.

The verb set is a *down-product* of the ARD schema — each verb maps
directly to one or more ARD columns.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

import polars as pl

from ._specs import GroupPool, OverallStat, Statistic

if TYPE_CHECKING:
    from pathlib import Path

    from ._specs import TLGSpec
    from .render._models import RenderMetadata


class TLGBuilder:
    """Fluent builder for constructing TLG ARDs inline.

    This is a shared base class composed into every TLG sub-namespace.
    Domain-specific defaults (required columns, default statistics,
    ``context`` label) are baked into the sub-namespace rather than the
    builder.

    Args:
        df: The primary analysis DataFrame.
        context: Domain context label (e.g. ``"t_ae_summary"``).
        spec_cls: The spec Pydantic model class for this domain.
        namespace_cls: The namespace class that implements ``t_summary()``.
        defaults: Domain-specific default kwargs for spec construction.
    """

    def __init__(
        self,
        df: pl.DataFrame,
        *,
        context: str,
        spec_cls: type[TLGSpec],
        namespace_cls: type[Any],
        defaults: dict[str, Any] | None = None,
    ) -> None:
        self._df = df
        self._context = context
        self._spec_cls = spec_cls
        self._namespace_cls = namespace_cls
        self._defaults: dict[str, Any] = defaults or {}
        self._adsl: pl.DataFrame | None = None
        self._adsl_filter: pl.Expr | None = None
        self._dataset_filter: pl.Expr | None = None
        self._group_col: str | None = None
        self._group2_col: str | None = None
        self._header_rows_list: list[OverallStat] = []
        self._rows_fields: list[str] = []
        self._statistics: list[Statistic] | None = None
        self._pools: list[GroupPool] = []
        self._column_order: list[str] = []
        self._fmt_overrides: dict[str, str] = {}

    def _clone(self) -> TLGBuilder:
        return copy.copy(self)

    # ------------------------------------------------------------------ #
    # Data input verbs                                                     #
    # ------------------------------------------------------------------ #

    def population(
        self,
        adsl: pl.DataFrame,
        *,
        adsl_filter: pl.Expr | None = None,
    ) -> TLGBuilder:
        """Set the ADSL population and optional denominator filter.

        Args:
            adsl: ADSL DataFrame for big-N denominators.
            adsl_filter: Optional filter applied to ADSL only.

        Returns:
            TLGBuilder: Builder with population set.
        """
        new = self._clone()
        new._adsl = adsl
        new._adsl_filter = adsl_filter
        return new

    def filter(self, expr: pl.Expr) -> TLGBuilder:
        """Set the dataset filter (applied to the primary dataset only).

        Args:
            expr: Polars expression to filter the primary dataset.

        Returns:
            TLGBuilder: Builder with dataset filter set.
        """
        new = self._clone()
        new._dataset_filter = expr
        return new

    # ------------------------------------------------------------------ #
    # Grouping verbs                                                       #
    # ------------------------------------------------------------------ #

    def by(self, col: str) -> TLGBuilder:
        """Set the primary grouping column (treatment arm).

        Args:
            col: Column name for group1 (e.g. ``"TRTA"``).

        Returns:
            TLGBuilder: Builder with group1 set.
        """
        new = self._clone()
        new._group_col = col
        return new

    def by2(self, col: str) -> TLGBuilder:
        """Set a secondary grouping column (stratification).

        The column must already exist in the DataFrame (pre-merge from
        ADSL or another dataset before calling the namespace).

        Args:
            col: Column name for group2 (e.g. ``"AGEGR1"``).

        Returns:
            TLGBuilder: Builder with group2 set.
        """
        new = self._clone()
        new._group2_col = col
        return new

    # ------------------------------------------------------------------ #
    # Row / stat / format verbs                                            #
    # ------------------------------------------------------------------ #

    def header_rows(self, overall_stats: list[OverallStat]) -> TLGBuilder:
        """Set header rows (whole-dataset aggregate rows).

        Args:
            overall_stats: List of ``OverallStat`` definitions.

        Returns:
            TLGBuilder: Builder with header rows set.
        """
        new = self._clone()
        new._header_rows_list = list(overall_stats)
        return new

    def rows(self, fields: list[str]) -> TLGBuilder:
        """Set the row hierarchy fields.

        A single field maps to ``variable``.  Two fields drive two-level
        nesting: the first maps to ``variable``, the second to ``group2``.

        Args:
            fields: One or two field names for the row hierarchy.

        Returns:
            TLGBuilder: Builder with row fields set.
        """
        new = self._clone()
        new._rows_fields = list(fields)
        return new

    def stats(self, statistics: list[Statistic]) -> TLGBuilder:
        """Set the statistics to compute.

        Args:
            statistics: List of ``Statistic`` enum values.

        Returns:
            TLGBuilder: Builder with statistics set.
        """
        new = self._clone()
        new._statistics = list(statistics)
        return new

    def pools(self, pool_defs: list[GroupPool]) -> TLGBuilder:
        """Set pooled treatment group definitions.

        Args:
            pool_defs: List of ``GroupPool`` definitions.

        Returns:
            TLGBuilder: Builder with pools set.
        """
        new = self._clone()
        new._pools = list(pool_defs)
        return new

    def column_order(self, order: list[str]) -> TLGBuilder:
        """Set the display column order.

        Args:
            order: Ordered list of arm labels.

        Returns:
            TLGBuilder: Builder with column order set.
        """
        new = self._clone()
        new._column_order = list(order)
        return new

    def fmt(self, mapping: dict[str, str]) -> TLGBuilder:
        """Override per-stat format specifiers.

        Args:
            mapping: Dict mapping stat_name to format string
                (e.g. ``{"mean": "xx.xx"}``).

        Returns:
            TLGBuilder: Builder with format overrides set.
        """
        new = self._clone()
        new._fmt_overrides = dict(mapping)
        return new

    # ------------------------------------------------------------------ #
    # Materialisation                                                      #
    # ------------------------------------------------------------------ #

    def to_spec(self) -> TLGSpec:
        """Serialise accumulated builder state to the equivalent spec.

        Returns:
            TLGSpec: A spec instance matching the builder configuration.
        """
        from ._specs import Row

        kwargs: dict[str, Any] = dict(self._defaults)

        if self._adsl_filter is not None:
            kwargs["adsl_filter"] = self._adsl_filter
        if self._dataset_filter is not None:
            kwargs["dataset_filter"] = self._dataset_filter
        if self._header_rows_list:
            kwargs["header_rows"] = self._header_rows_list
        if self._rows_fields:
            kwargs["rows"] = [Row(field=f) for f in self._rows_fields]
        if self._statistics is not None:
            kwargs["statistics"] = self._statistics
        if self._pools:
            kwargs["pools"] = self._pools
        if self._column_order:
            kwargs["column_order"] = self._column_order

        return self._spec_cls(**kwargs)

    def to_ard(self) -> pl.DataFrame:
        """Materialise the builder to an ARD DataFrame.

        Constructs the equivalent spec and delegates to the domain
        namespace's ``t_summary()`` method.

        Returns:
            pl.DataFrame: Long-format {cards}-compatible ARD.

        Examples:
            Inline AE summary::

                ard = (
                    adae.tlg.ae
                    .population(adsl, adsl_filter=pl.col("SAFFL") == "Y")
                    .by("TRTA")
                    .rows(["AEBODSYS", "AEDECOD"])
                    .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
                    .to_ard()
                )
        """
        spec = self.to_spec()
        ns = self._namespace_cls(self._df)
        return ns.t_summary(
            groupby=self._group_col,
            adsl=self._adsl,
            spec=spec,
        )

    def to_html(
        self,
        path: str | Path | None = None,
        *,
        metadata: RenderMetadata | None = None,
        html_wrapper: str | None = None,
    ) -> str:
        """Render the builder result as a pharma-style HTML table.

        Materialises the ARD via ``.to_ard()``, shapes it into a
        ``TableModel``, and renders to HTML.

        Args:
            path: Optional file path.  If given, HTML is written to disk.
            metadata: Optional ``RenderMetadata`` for title, subtitle,
                footnotes, etc.
            html_wrapper: Optional HTML template with ``{table}``
                placeholder for injection.

        Returns:
            str: The rendered HTML string.

        Examples:
            Inline AE summary to HTML::

                html = (
                    adae.tlg.ae
                    .population(adsl)
                    .by("TRTA")
                    .rows(["AEBODSYS", "AEDECOD"])
                    .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
                    .to_html(metadata=RenderMetadata(title="Table 14.3.1"))
                )
        """
        from pathlib import Path as _Path

        from .render._models import RenderMetadata as _RM
        from .render._models import ard_to_table_model
        from .render.html import render_html

        ard = self.to_ard()
        meta = metadata or _RM()
        model = ard_to_table_model(ard, meta)
        html = render_html(model, html_wrapper=html_wrapper)

        if path is not None:
            p = _Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(html, encoding="utf-8")

        return html

    def to_pdf(
        self,
        path: str | Path,
        *,
        metadata: RenderMetadata | None = None,
    ) -> Path:
        """Render the builder result as a PDF file via WeasyPrint.

        Args:
            path: Output PDF file path.
            metadata: Optional ``RenderMetadata`` for title, subtitle,
                footnotes, etc.

        Returns:
            Path: The written PDF path.

        Raises:
            ImportError: If WeasyPrint is not installed.

        Examples:
            Inline AE summary to PDF::

                path = (
                    adae.tlg.ae
                    .population(adsl)
                    .by("TRTA")
                    .rows(["AEBODSYS", "AEDECOD"])
                    .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
                    .to_pdf("ae_summary.pdf",
                            metadata=RenderMetadata(title="Table 14.3.1"))
                )
        """

        from .render._models import RenderMetadata as _RM
        from .render._models import ard_to_table_model
        from .render.pdf import render_pdf

        ard = self.to_ard()
        meta = metadata or _RM()
        model = ard_to_table_model(ard, meta)
        return render_pdf(model, path)

    def to_pptx(
        self,
        path: str | Path,
        *,
        metadata: RenderMetadata | None = None,
        theme: dict[str, Any] | None = None,
    ) -> Path:
        """Render the builder result as an editable PPTX slide deck.

        Args:
            path: Output ``.pptx`` file path.
            metadata: Optional ``RenderMetadata`` for title, subtitle,
                footnotes, etc.
            theme: Optional dict of style overrides (font, colours, sizes).

        Returns:
            Path: The written ``.pptx`` path.

        Raises:
            ImportError: If ``python-pptx`` is not installed.

        Examples:
            Inline AE summary to editable slides::

                path = (
                    adae.tlg.ae
                    .population(adsl)
                    .by("TRTA")
                    .rows(["AEBODSYS", "AEDECOD"])
                    .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
                    .to_pptx("ae_summary.pptx",
                             metadata=RenderMetadata(title="Table 14.3.1"))
                )
        """

        from .render._models import RenderMetadata as _RM
        from .render._models import ard_to_table_model
        from .render.slides import render_pptx

        ard = self.to_ard()
        meta = metadata or _RM()
        model = ard_to_table_model(ard, meta)
        return render_pptx(model, path, theme=theme)
