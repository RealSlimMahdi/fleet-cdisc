"""Checks shared by the verbs that join a second frame into the pipeline.

``merge``, ``merge_adsl``, ``join_adsl``, ``first_date``, ``last_date``,
``count_events``, ``study_day`` and ``baseline_flag`` all join a frame on
key columns.  The checks here make each of them stop, as admiral
``derive_vars_merged`` does, instead of adding an ``X_right`` column or
multiplying records with no message (ADR-0032).
"""

from __future__ import annotations

import difflib
import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

from fleet.core.exceptions import DerivationError

if TYPE_CHECKING:
    from collections.abc import Sequence

#: How many repeated key values a message lists.
_MAX_SHOWN = 5

#: Polars ``validate=`` values: which side must hold each key once.
_UNIQUE_SIDES = {"m:1": ("right",), "1:m": ("left",), "1:1": ("left", "right"), "m:m": ()}


def name_hints(missing: Sequence[str], available: Sequence[str]) -> str:
    """Quote each missing name, with a did-you-mean from *available* when one is close."""
    hints = []
    for col in missing:
        close = difflib.get_close_matches(col, list(available), n=1)
        hints.append(f"'{col}'" + (f" (did you mean '{close[0]}'?)" if close else ""))
    return ", ".join(hints)


def require_columns(
    verb: str, wanted: Sequence[str], available: Sequence[str], *, where: str
) -> None:
    """Raise ``DerivationError`` naming each name of *wanted* absent from *available*."""
    missing = [c for c in wanted if c not in available]
    if missing:
        raise DerivationError(
            f"{verb}: column(s) {name_hints(missing, available)} not found in {where}. "
            f"Available columns: {list(available)}"
        )


def refuse_shared_columns(
    verb: str,
    left: Sequence[str],
    right: Sequence[str],
    keys: Sequence[str],
    *,
    hint: str,
) -> None:
    """Raise ``DerivationError`` when a non-key column of *right* is also on the left."""
    shared = [c for c in right if c in left and c not in keys]
    if shared:
        names = ", ".join(shared)
        raise DerivationError(
            f"{verb}: {names} {'is' if len(shared) == 1 else 'are'} on both sides of the join "
            f"and not a key. {hint}"
        )


def _key_label(keys: Sequence[str], row: tuple) -> str:
    return ", ".join(f"{k}={v}" for k, v in zip(keys, row, strict=True))


def repeated_keys(frame: pl.DataFrame | pl.LazyFrame, keys: Sequence[str]) -> list[str]:
    """Labels of the key values that occur on more than one row of *frame*."""
    rows = (
        frame.lazy()
        .group_by(list(keys))
        .agg(pl.len().alias("__n__"))
        .filter(pl.col("__n__") > 1)
        .select(list(keys))
        .sort(list(keys), nulls_last=True)
        .collect()
    )
    return [_key_label(keys, row) for row in rows.iter_rows()]


def _shown(labels: list[str]) -> str:
    more = f"; ... {len(labels) - _MAX_SHOWN} more" if len(labels) > _MAX_SHOWN else ""
    return "; ".join(labels[:_MAX_SHOWN]) + more


def refuse_repeated_keys(
    verb: str, frame: pl.DataFrame, keys: Sequence[str], *, source: str
) -> pl.DataFrame:
    """Return the distinct rows of *frame*; raise when a key still has two rows.

    Identical rows are one row, so a frame cut to the key and the requested
    columns passes when the repeats agree on those columns.
    """
    distinct = frame.unique(maintain_order=True)
    labels = repeated_keys(distinct, keys)
    if labels:
        raise DerivationError(
            f"{verb}: {source} has more than one row for {len(labels)} value(s) of "
            f"{', '.join(keys)} ({_shown(labels)}). {source} must hold one row per "
            f"{', '.join(keys)}."
        )
    return distinct


@dataclass(frozen=True)
class JoinCheck:
    """A ``merge`` join whose key check waits for the next ``to_frame()``."""

    verb: str
    keys: tuple[str, ...]
    left: pl.LazyFrame
    right: pl.LazyFrame
    validate: str | None

    def explain_validation(self) -> str | None:
        """The repeated keys that broke ``validate=``, or ``None`` when this join did not."""
        if self.validate is None:
            return None
        sides = {"left": self.left, "right": self.right}
        for side in _UNIQUE_SIDES.get(self.validate, ()):
            labels = repeated_keys(sides[side].select(self.keys), self.keys)
            if labels:
                return (
                    f"{self.verb}(validate={self.validate!r}): the {side} frame has more than "
                    f"one row for {len(labels)} value(s) of {', '.join(self.keys)} "
                    f"({_shown(labels)})."
                )
        return None

    def warn_many_to_many(self) -> None:
        """Warn when a key value repeats on both sides, so the join multiplies records."""
        if self.validate is not None:
            return
        left = self.left.select(self.keys)
        right = self.right.select(self.keys)
        on_left = left.group_by(self.keys).agg(pl.len().alias("__n__")).filter(pl.col("__n__") > 1)
        on_right = (
            right.group_by(self.keys).agg(pl.len().alias("__n__")).filter(pl.col("__n__") > 1)
        )
        both = (
            on_left.select(self.keys)
            .join(on_right.select(self.keys), on=list(self.keys), nulls_equal=True)
            .sort(list(self.keys), nulls_last=True)
            .collect()
        )
        labels = [_key_label(self.keys, row) for row in both.iter_rows()]
        if labels:
            warnings.warn(
                f"{self.verb}(): {len(labels)} value(s) of {', '.join(self.keys)} repeat on "
                f"both sides ({_shown(labels)}), so the join gives every pair of their rows "
                "(many-to-many). Pass validate='m:1' to stop instead, or make the keys unique.",
                stacklevel=4,
            )
