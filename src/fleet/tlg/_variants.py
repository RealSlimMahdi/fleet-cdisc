"""
Variant enumeration for interactive TLG specs (DX-review §8).

``enumerate_variants`` expands a spec's declared ``interactive:`` block
into the cartesian product of its axes.  Every variant is the *same*
spec with one field updated per axis (``model_copy(update=...)``), so
each one runs through the identical engine path as the batch output —
the anti-drift core of the explorer.
"""

from __future__ import annotations

import math
import warnings
from itertools import product
from typing import Any, NamedTuple

from fleet.core.exceptions import SchemaError

from ._specs import InteractiveBlock, TLGSpec

#: Hard cap on the variant-space size — beyond this the explorer file
#: becomes unusable and a live server (future ``fleet tlg serve``) is
#: the right tool.
MAX_VARIANTS = 500

#: Soft threshold above which a size warning is emitted.
WARN_VARIANTS = 100


class Variant(NamedTuple):
    """One point of the declared variant space.

    Attributes:
        variant_id: Stable id (``v0``, ``v1``, ...) in enumeration order.
        axis_labels: Axis name → selected choice label (empty when the
            spec has no ``interactive:`` block).
        spec: The concrete spec for this variant.
        is_default: True for the all-defaults combination (always first)
            — the one the batch run renders.
    """

    variant_id: str
    axis_labels: dict[str, str]
    spec: TLGSpec
    is_default: bool


def _axis_options(
    spec: TLGSpec,
) -> list[tuple[str, list[tuple[str, dict[str, Any], bool, int]]]]:
    """Declared axes as ``(axis_name, [(label, field_update, is_default, index)])``."""
    block = spec.interactive
    assert block is not None
    axes: list[tuple[str, list[tuple[str, dict[str, Any], bool, int]]]] = []
    if block.groupby is not None:
        gb = block.groupby
        axes.append(
            (
                "groupby",
                [(c, {"columns": [c]}, c == gb.default, i) for i, c in enumerate(gb.choices)],
            )
        )
    for axis, field in (
        ("population", "adsl_filter"),
        ("dataset_filter", "dataset_filter"),
        ("stats", "statistics"),
    ):
        options = getattr(block, axis)
        if options is None:
            continue
        axes.append(
            (
                axis,
                [
                    (
                        o.label,
                        {field: o.statistics if axis == "stats" else o.filter},
                        o.default,
                        i,
                    )
                    for i, o in enumerate(options)
                ],
            )
        )
    # Default choice first per axis (stable sort) so the cartesian
    # product starts with the all-defaults combination.
    return [(name, sorted(opts, key=lambda t: not t[2])) for name, opts in axes]


def _block_with_defaults(block: InteractiveBlock, chosen: dict[str, int]) -> InteractiveBlock:
    """Copy *block* with ``default`` moved to the chosen option of each axis."""
    update: dict[str, Any] = {}
    for axis, index in chosen.items():
        if axis == "groupby":
            gb = block.groupby
            assert gb is not None
            update[axis] = gb.model_copy(update={"default": gb.choices[index]})
        else:
            update[axis] = [
                o.model_copy(update={"default": i == index})
                for i, o in enumerate(getattr(block, axis))
            ]
    return block.model_copy(update=update)


def enumerate_variants(spec: TLGSpec) -> list[Variant]:
    """Expand a spec's ``interactive:`` block into concrete spec variants.

    The all-defaults combination is always ``variants[0]`` and flagged
    ``is_default`` — it is byte-for-byte the batch output's spec.  A
    spec without an ``interactive:`` block yields exactly one default
    variant (itself).  In each variant spec, the ``interactive:`` block
    marks the chosen options as ``default: true``, so the YAML of a
    variant loads and its batch output is that variant.

    Args:
        spec: A validated spec, typically from
            [`load_spec()`][fleet.tlg.load_spec].

    Returns:
        list[Variant]: One entry per axis-choice combination, default
            first.

    Raises:
        SchemaError: If the variant space exceeds ``MAX_VARIANTS`` (500).

    Warns:
        UserWarning: If the variant space exceeds ``WARN_VARIANTS`` (100).

    Examples:
        Enumerate and run every declared variant::

            import fleet.tlg as tlg
            from fleet.tlg._variants import enumerate_variants

            spec = tlg.load_spec("specs/aet01.yaml")
            for v in enumerate_variants(spec):
                ard = tlg.run_spec(v.spec, adae, adsl=adsl)
    """
    if spec.interactive is None:
        return [Variant("v0", {}, spec, True)]

    axes = _axis_options(spec)
    total = math.prod(len(opts) for _, opts in axes)
    if total > MAX_VARIANTS:
        raise SchemaError(
            f"interactive: block declares {total} variants, above the hard "
            f"cap of {MAX_VARIANTS}. A static explorer of that size is "
            "unusable — trim the axis choices (a live server mode is the "
            "tool for open-ended exploration)."
        )
    if total > WARN_VARIANTS:
        warnings.warn(
            f"interactive: block declares {total} variants (> {WARN_VARIANTS}) "
            "— the explorer file will be large and slow to open.",
            UserWarning,
            stacklevel=2,
        )

    variants: list[Variant] = []
    for i, combo in enumerate(product(*[opts for _, opts in axes])):
        update: dict[str, Any] = {}
        labels: dict[str, str] = {}
        chosen: dict[str, int] = {}
        for (axis_name, _), (label, field_update, _default, index) in zip(axes, combo):
            update.update(field_update)
            labels[axis_name] = label
            chosen[axis_name] = index
        # The chosen options become the defaults, so a variant saved as
        # YAML loads and is its own batch output.
        update["interactive"] = _block_with_defaults(spec.interactive, chosen)
        variants.append(Variant(f"v{i}", labels, spec.model_copy(update=update), i == 0))
    return variants
