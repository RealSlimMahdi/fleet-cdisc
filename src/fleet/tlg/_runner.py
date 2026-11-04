"""
TLG spec runner — the YAML-as-workflow entry points.

``load_spec(path)`` turns a YAML file into the right spec model by
resolving its ``template:`` id through the registry, and ``run_spec``
dispatches the spec to the template's namespace method (or a
user-registered template function) — so a YAML file alone fully
reproduces a table::

    import polars as pl
    import fleet.tlg as tlg

    spec = tlg.load_spec("specs/aet01.yaml")
    ard = tlg.run_spec(spec, adae, adsl=adsl)

These are also the composition points for the ``fleet tlg run`` /
``fleet tlg list`` CLI commands.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import polars as pl
import yaml
from pydantic import ValidationError

from fleet.core.exceptions import SchemaError

from ._registry import TEMPLATES, OutputType, TemplateMeta
from ._specs import SummarySpecBase, TLGSpec
from .ae_namespace import AETLGNamespace
from .cm_namespace import CMTLGNamespace
from .dm_namespace import DMTLGNamespace
from .ds_namespace import DSTLGNamespace
from .eg_namespace import EGTLGNamespace
from .ex_namespace import EXTLGNamespace
from .lb_namespace import LBTLGNamespace
from .mh_namespace import MHTLGNamespace
from .vs_namespace import VSTLGNamespace

#: ``df.tlg`` sub-namespace attribute → implementing class.  Mirrors the
#: properties on :class:`fleet.tlg.namespace.TLGNamespace`.
NAMESPACE_CLASSES: dict[str, type[Any]] = {
    "ae": AETLGNamespace,
    "vs": VSTLGNamespace,
    "cm": CMTLGNamespace,
    "ex": EXTLGNamespace,
    "dm": DMTLGNamespace,
    "ds": DSTLGNamespace,
    "eg": EGTLGNamespace,
    "lb": LBTLGNamespace,
    "mh": MHTLGNamespace,
}

#: Treatment-arm columns tried, in order, when no ``groupby`` is given.
GROUPBY_CANDIDATES: tuple[str, ...] = ("TRTA", "TRT01A", "TRT01P")


def detect_groupby(columns: Iterable[str]) -> str | None:
    """The first :data:`GROUPBY_CANDIDATES` column present in *columns*.

    Args:
        columns: Column names of the analysis dataset.

    Returns:
        str | None: The detected treatment-arm column, or ``None`` when the
        caller must ask for one explicitly.

    Examples:
        Auto-detect the arm column of an ADAE::

            detect_groupby(adae.columns)  # -> 'TRTA'
    """
    present = set(columns)
    return next((c for c in GROUPBY_CANDIDATES if c in present), None)


def resolve_spec_cls(meta: TemplateMeta) -> type[TLGSpec]:
    """Return the spec model class validating YAML for *meta*.

    Resolution order: an explicit ``meta.spec_cls``, the namespace's
    builder spec table (built-ins), then ``SummarySpecBase`` (user
    templates registered without a spec class).

    Args:
        meta: Registry entry to resolve.

    Returns:
        type[TLGSpec]: The spec model class.

    Raises:
        SchemaError: If a built-in entry references an unknown namespace
            or a method without a registered spec class.
    """
    if meta.spec_cls is not None:
        return meta.spec_cls
    if meta.func is not None:
        return SummarySpecBase
    ns_cls = NAMESPACE_CLASSES.get(meta.namespace)
    if ns_cls is None:
        raise SchemaError(
            f"Template {meta.id!r} references unknown namespace "
            f"{meta.namespace!r}. Known: {sorted(NAMESPACE_CLASSES)}"
        )
    spec_cls = getattr(ns_cls, "_builder_specs", {}).get(meta.method)
    if spec_cls is None:
        raise SchemaError(
            f"Template {meta.id!r} ({meta.namespace}.{meta.method}) has no registered spec class."
        )
    return spec_cls


def load_spec(path: str | Path) -> TLGSpec:
    """Load a TLG spec from a YAML file, dispatching on its template id.

    The file must carry ``template: <id>``; the id resolves the concrete
    spec class through the template registry (built-ins and user
    registrations alike), so callers never need to know which spec class
    a YAML file belongs to.  All errors name the offending file.

    Args:
        path: Path to a YAML spec file.

    Returns:
        TLGSpec: The validated spec instance (a concrete subclass such
            as ``AEOverviewSpec``), ready for
            [`run_spec()`][fleet.tlg.run_spec].

    Raises:
        SchemaError: If the file is unreadable, is not valid YAML, lacks
            a ``template:`` id, references an unknown template, or fails
            spec-model validation.

    Examples:
        Reproduce a table from its YAML spec alone::

            import fleet.tlg as tlg

            spec = tlg.load_spec("specs/aet01.yaml")
            ard = tlg.run_spec(spec, adae, adsl=adsl)
    """
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise SchemaError(f"{p}: cannot read spec file: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SchemaError(f"{p}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise SchemaError(f"{p}: a TLG spec must be a YAML mapping, got {type(data).__name__}.")
    template_id = data.get("template")
    if not template_id:
        raise SchemaError(
            f"{p}: missing 'template:' key — load_spec() needs it to resolve "
            f"the spec class through the registry. Known ids: {sorted(TEMPLATES)}"
        )
    meta = TEMPLATES.get(template_id)
    if meta is None:
        raise SchemaError(
            f"{p}: unknown template id {template_id!r}. Known ids: {sorted(TEMPLATES)}"
        )
    spec_cls = resolve_spec_cls(meta)
    try:
        return spec_cls.model_validate(data)
    except ValidationError as exc:
        raise SchemaError(f"{p}: invalid {spec_cls.__name__} spec:\n{exc}") from exc


def run_spec(
    spec: TLGSpec,
    df: pl.DataFrame,
    *,
    adsl: pl.DataFrame | None = None,
    groupby: str | None = None,
) -> pl.DataFrame:
    """Execute a template-carrying spec against an analysis dataset.

    Dispatches ``spec.template`` through the registry to the template's
    namespace method (built-ins) or registered function (user
    templates).  Listings ignore *adsl* and *groupby* by design — they
    have no population denominator or column grouping.

    Args:
        spec: A spec carrying ``template=<id>`` (e.g. from
            [`load_spec()`][fleet.tlg.load_spec]).
        df: The primary analysis dataset (e.g. ADAE for ``aet01``).
        adsl: ADSL population for big-N denominators.
        groupby: Treatment-arm column override.

    Returns:
        pl.DataFrame: The ARD in the {cards} long layout (tables) or plain
            listing DataFrame (listings).

    Raises:
        SchemaError: If the spec carries no template id, the id is
            unknown, or the spec's class does not match the template's
            registered spec class.

    Examples:
        YAML file → published numbers, no code in between::

            import fleet.tlg as tlg

            spec = tlg.load_spec("specs/vst01.yaml")
            ard = tlg.run_spec(spec, advs, adsl=adsl, groupby="TRT01A")
    """
    if spec.template is None:
        raise SchemaError(
            "run_spec() needs spec.template to dispatch through the registry "
            "— set template=<id> on the spec (or in the YAML file). Known "
            f"ids: {sorted(TEMPLATES)}"
        )
    meta = TEMPLATES.get(spec.template)
    if meta is None:
        raise SchemaError(f"Unknown template id {spec.template!r}. Known ids: {sorted(TEMPLATES)}")
    expected_cls = resolve_spec_cls(meta)
    if not isinstance(spec, expected_cls):
        raise SchemaError(
            f"Template {meta.id!r} expects a {expected_cls.__name__} spec, "
            f"got {type(spec).__name__}. Load the spec via "
            "fleet.tlg.load_spec() to resolve the right class."
        )
    if meta.func is not None:
        return meta.func(df, adsl=adsl, spec=spec, groupby=groupby)
    ns = NAMESPACE_CLASSES[meta.namespace](df)
    method = getattr(ns, meta.method)
    if meta.output_type is OutputType.LISTING:
        return method(spec=spec)
    return method(spec=spec, adsl=adsl, groupby=groupby)


def spec_schema(template_id: str) -> dict[str, Any]:
    """Return the JSON Schema for a template's spec model.

    Generated via Pydantic's ``model_json_schema()`` — point an editor's
    YAML language server at the exported schema for auto-complete and
    inline validation of spec files.

    Args:
        template_id: Registry id (e.g. ``"aet01"``).

    Returns:
        dict[str, Any]: The JSON Schema of the template's spec class.

    Raises:
        SchemaError: If *template_id* is not registered.

    Examples:
        Export the AET01 spec schema for editor validation::

            import json

            import fleet.tlg as tlg

            schema = tlg.spec_schema("aet01")
            Path("aet01.schema.json").write_text(json.dumps(schema, indent=2))
    """
    meta = TEMPLATES.get(template_id)
    if meta is None:
        raise SchemaError(f"Unknown template id {template_id!r}. Known ids: {sorted(TEMPLATES)}")
    return resolve_spec_cls(meta).model_json_schema()
