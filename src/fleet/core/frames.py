"""
Typed frame entry points — zero-cost casts for the Fleet namespaces.

Polars namespace registration (``df.sdtm`` / ``df.adam`` / ``df.tlg``) is
invisible to static type checkers (pola-rs/polars#27795).  ``fleet.frame()``
bridges the gap: at runtime it returns its argument unchanged, but type
checkers see :class:`DataFrame` / :class:`LazyFrame` — ``pl.DataFrame`` /
``pl.LazyFrame`` subclasses that declare the registered namespaces.

At runtime ``fleet.DataFrame`` *is* ``pl.DataFrame`` and ``fleet.LazyFrame``
*is* ``pl.LazyFrame`` — plain aliases, no wrapper class, no overhead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NoReturn, overload

import polars as pl

if TYPE_CHECKING:
    from fleet.adam.adsl_namespace import ADSLNamespace
    from fleet.adam.namespace import AdamNamespace
    from fleet.adam.occds_namespace import OCCDSNamespace
    from fleet.sdtm.namespace import SDTMNamespace
    from fleet.tlg.namespace import TLGNamespace

    # Declaration-only subclasses (properties mirror how @pl.api registration
    # exposes the namespaces at runtime); never instantiated.
    class DataFrame(pl.DataFrame):
        """``pl.DataFrame`` with the Fleet namespaces declared for type checkers."""

        @property
        def sdtm(self) -> SDTMNamespace: ...
        @property
        def adam(self) -> AdamNamespace: ...
        @property
        def tlg(self) -> TLGNamespace: ...

    class LazyFrame(pl.LazyFrame):
        """``pl.LazyFrame`` with the Fleet namespaces declared for type checkers."""

        @property
        def sdtm(self) -> SDTMNamespace: ...
        @property
        def adam(self) -> AdamNamespace: ...
        @property
        def adsl(self) -> ADSLNamespace: ...
        @property
        def occds(self) -> OCCDSNamespace: ...
else:
    DataFrame = pl.DataFrame
    LazyFrame = pl.LazyFrame


@overload
def frame(df: pl.DataFrame) -> DataFrame: ...


@overload
def frame(df: pl.LazyFrame) -> LazyFrame: ...


# pl.from_repr returns `DataFrame | Series`; accepting (and rejecting) Series
# lets `fleet.frame(pl.from_repr(...))` type-check without a cast.
@overload
def frame(df: pl.Series) -> NoReturn: ...


def frame(df: pl.DataFrame | pl.LazyFrame | pl.Series) -> Any:
    """Return *df* unchanged, typed with the Fleet namespaces.

    Zero-cost cast for the entry-point cliff: registered namespaces
    (``.sdtm`` / ``.adam`` / ``.tlg``) are invisible to type checkers on a
    bare Polars frame, so wrap the IO-boundary load once and every chained
    verb autocompletes from there.  Verbs returning frames (``to_frame()``,
    ``write_parquet()``) keep the typed view downstream.

    Args:
        df: The ``pl.DataFrame`` or ``pl.LazyFrame`` to type as a Fleet
            frame.  Returned as-is — no copy, no wrapper.

    Returns:
        DataFrame | LazyFrame: The same object, typed as
            :class:`fleet.DataFrame` / :class:`fleet.LazyFrame` so the
            ``sdtm`` / ``adam`` / ``tlg`` namespaces type-check.

    Raises:
        TypeError: When *df* is not a ``pl.DataFrame`` or ``pl.LazyFrame``
            (e.g. a ``pl.Series`` from ``pl.from_repr``).

    Examples:
        Wrap the raw load; the rest of the pipeline is fully typed::

            import fleet
            import polars as pl

            raw = fleet.frame(pl.read_csv("dm_raw.csv"))
            dm = (
                raw.sdtm
                .assign("DOMAIN", value="DM")
                .assign("USUBJID", source="patient_number")
                .to_frame()
            )
    """
    if not isinstance(df, (pl.DataFrame, pl.LazyFrame)):
        raise TypeError(
            f"fleet.frame() expects a pl.DataFrame or pl.LazyFrame, got {type(df).__name__}."
        )
    return df
