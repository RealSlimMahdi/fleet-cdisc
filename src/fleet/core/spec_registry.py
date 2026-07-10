"""Single source of truth for spec-executable derivation algorithms.

Every algorithm that ``from_spec()`` can execute is declared **once** in
this module as a :class:`SpecAlgorithm` entry.  From that single
declaration Fleet derives:

* the per-algorithm **discriminated-union Pydantic models** (required
  fields required, ``extra="forbid"`` — a typo like ``recod_map`` is a
  validation error, not a silent column of nulls);
* the shared table-driven ``from_spec`` executor (replacing the previous
  duplicated SDTM/ADaM ``elif`` ladders);
* the ``derivation`` section of the published JSON schema
  (``fleet.define_xml.schema_builder``);
* the machine-checked **coverage matrix** (algorithm ↔ namespace verb ↔
  ``SPEC_UNSUPPORTED`` allowlist) used by the parity tests.

The ``SDTMAlgorithm`` / ``ADAMAlgorithm`` enums remain literal source
code in ``fleet.sdtm.models`` / ``fleet.adam.models`` for import
stability; a sync test asserts they always match this registry.

Examples:
    Validate and execute one spec variable::

        from fleet.core import spec_registry

        var = spec_registry.parse_variable_spec(
            "adam",
            {"target": "CHG", "algorithm": "chg", "aval": "AVAL", "base": "BASE"},
        )
        ns = spec_registry.execute_variable(vs_df.adam, var)
        result = ns.to_frame()
"""

from __future__ import annotations

import difflib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Annotated, Any, ClassVar, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, create_model, model_validator

__all__ = [
    "SPEC_UNSUPPORTED",
    "Param",
    "SpecAlgorithm",
    "SpecVariableBase",
    "algorithm_names",
    "coverage_matrix",
    "derivation_from_lineage",
    "execute_variable",
    "get_algorithm",
    "is_identity_copy",
    "model_for",
    "parse_variable_spec",
    "spec_algorithm",
    "suggest_algorithm",
    "variable_spec_union",
]


# --------------------------------------------------------------------- #
# Declaration dataclasses                                                #
# --------------------------------------------------------------------- #


@dataclass(frozen=True)
class Param:
    """One spec field of an algorithm and how it maps onto the verb call.

    Args:
        name: Spec field name (the YAML key inside the ``derivation`` block).
        annotation: Type annotation for the generated Pydantic field.
        kwarg: Verb keyword argument the value is passed to (defaults to
            *name*).
        default: Live default applied when the field is omitted.  This is
            the value the verb actually receives — no more unreachable
            ``getattr(var, "low", "LBSTNRLO")`` fallbacks.
        required: When ``True`` the field must be present in the spec.
        alias: Additional accepted YAML key (Pydantic alias), e.g.
            ``callable`` for ``callable_ref``.
        default_to_target: When the field is omitted (``None``), use the
            variable's ``target`` name as the value.
        identity_source: Marks the param as the algorithm's *input column*.
            When its resolved value equals ``target`` the derivation is an
            in-place / carry-through operation and is exempt from the
            ``from_spec`` overwrite guard.
        convert: Dispatch-time conversion: ``"pin"`` resolves the value as
            a pinned dataset name via ``_require_pin``; ``"exprs"`` parses
            a list of expression strings via ``parse_expression``.
        description: Short human-readable description (surfaces in the
            generated JSON schema).
    """

    name: str
    annotation: Any = str | None
    kwarg: str | None = None
    default: Any = None
    required: bool = False
    alias: str | None = None
    default_to_target: bool = False
    identity_source: bool = False
    convert: str | None = None
    description: str = ""


@dataclass(frozen=True)
class SpecAlgorithm:
    """A spec-executable algorithm: name, target verb, and parameter table.

    Args:
        name: Canonical algorithm name used in YAML (``algorithm:`` key).
        standard: ``"sdtm"`` or ``"adam"``.
        verb: Namespace method the algorithm drives (coverage matrix and
            default dispatch target).
        params: Ordered :class:`Param` declarations.
        aliases: Extra accepted spellings of the algorithm name
            (e.g. ``assign_dtc`` for ``date``).
        legacy_keys: Mapping of legacy spec key → canonical param name,
            normalised before validation (e.g. ``join_on`` → ``on``).
        takes_target: Whether the verb receives the variable name as its
            first positional argument.
        overwrite_guard: Whether the ``from_spec`` overwrite guard applies
            (``False`` for verbs that intentionally rewrite existing
            columns, e.g. ``notsubmitted``).
        dispatch: Optional custom executor ``(ns, var) -> ns`` for
            algorithms whose call shape is not expressible via *params*.
        description: One-line description for docs / JSON schema.
    """

    name: str
    standard: str
    verb: str
    params: tuple[Param, ...] = ()
    aliases: tuple[str, ...] = ()
    legacy_keys: dict[str, str] = field(default_factory=dict)
    takes_target: bool = True
    overwrite_guard: bool = True
    dispatch: Callable[[Any, SpecVariableBase], Any] | None = None
    description: str = ""

    @property
    def names(self) -> tuple[str, ...]:
        """All accepted algorithm spellings (canonical name first)."""
        return (self.name, *self.aliases)


# --------------------------------------------------------------------- #
# Generated model machinery                                               #
# --------------------------------------------------------------------- #

#: Variable-level metadata accepted on every algorithm model.  These keys
#: are merged in from the variable entry of a define.yaml (label, origin,
#: role, evaluator) and are legitimate on any derivation.
_META_FIELDS: tuple[str, ...] = ("label", "origin", "role", "evaluator")


class SpecVariableBase(BaseModel):
    """Base class for all generated per-algorithm variable-spec models.

    Unknown keys are **rejected** (``extra="forbid"``): a misspelled
    param fails validation instead of silently producing nulls.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    target: str

    _algo: ClassVar[SpecAlgorithm]
    _legacy: ClassVar[dict[str, str]] = {}

    @model_validator(mode="before")
    @classmethod
    def _normalise_legacy_keys(cls, data: Any) -> Any:
        """Rename legacy spec keys to their canonical param names."""
        legacy = cls._legacy
        if legacy and isinstance(data, dict):
            for old, new in legacy.items():
                if old in data and new not in data:
                    data = dict(data)
                    data[new] = data.pop(old)
        return data


def _model_name(algo: SpecAlgorithm) -> str:
    prefix = "SDTM" if algo.standard == "sdtm" else "ADAM"
    camel = "".join(part.capitalize() for part in algo.name.split("_"))
    return f"{prefix}{camel}Spec"


def _build_model(algo: SpecAlgorithm) -> type[SpecVariableBase]:
    """Generate the strict Pydantic model for one algorithm."""
    fields: dict[str, Any] = {
        "algorithm": (Literal[algo.names], Field(..., description=algo.description or None)),
    }
    for p in algo.params:
        default = ... if p.required else p.default
        fields[p.name] = (
            p.annotation,
            Field(default, alias=p.alias, description=p.description or None),
        )
    for meta in _META_FIELDS:
        fields.setdefault(meta, (str | None, Field(None)))
    if algo.standard == "adam":
        # depends_on drives the auto-flush staging in from_spec().
        fields.setdefault("depends_on", (list[str] | None, Field(None)))
    model = create_model(_model_name(algo), __base__=SpecVariableBase, **fields)
    model._algo = algo
    model._legacy = dict(algo.legacy_keys)
    return model


# --------------------------------------------------------------------- #
# Registry storage & registration                                         #
# --------------------------------------------------------------------- #

_REGISTRY: dict[str, dict[str, SpecAlgorithm]] = {"sdtm": {}, "adam": {}}
_MODELS: dict[tuple[str, str], type[SpecVariableBase]] = {}
_ADAPTERS: dict[str, TypeAdapter] = {}


def spec_algorithm(
    name: str,
    *,
    standard: str,
    verb: str,
    params: tuple[Param, ...] = (),
    aliases: tuple[str, ...] = (),
    legacy_keys: dict[str, str] | None = None,
    takes_target: bool = True,
    overwrite_guard: bool = True,
    dispatch: Callable[[Any, SpecVariableBase], Any] | None = None,
    description: str = "",
) -> SpecAlgorithm:
    """Declare a spec-executable algorithm (single source of truth).

    Registers the algorithm under *name* (and *aliases*) for *standard*
    and generates its strict Pydantic model.

    Args:
        name: Canonical algorithm name (``algorithm:`` value in YAML).
        standard: ``"sdtm"`` or ``"adam"``.
        verb: Namespace method the algorithm executes.
        params: Spec-field → verb-kwarg declarations.
        aliases: Additional accepted algorithm spellings.
        legacy_keys: Legacy spec key → canonical param name renames.
        takes_target: Whether the verb takes the target name positionally.
        overwrite_guard: Whether the overwrite guard applies to *target*.
        dispatch: Custom executor for non-tabular call shapes.
        description: One-line description for docs and JSON schema.

    Returns:
        SpecAlgorithm: The registered declaration.

    Raises:
        ValueError: If *name* or an alias is already registered for
            *standard*.

    Examples:
        Declare a spec algorithm executing the ``chg`` verb::

            spec_algorithm(
                "chg", standard="adam", verb="chg",
                params=(
                    Param("aval", annotation=str, default="AVAL"),
                    Param("base", annotation=str, default="BASE"),
                ),
            )
    """
    algo = SpecAlgorithm(
        name=name,
        standard=standard,
        verb=verb,
        params=params,
        aliases=aliases,
        legacy_keys=legacy_keys or {},
        takes_target=takes_target,
        overwrite_guard=overwrite_guard,
        dispatch=dispatch,
        description=description,
    )
    table = _REGISTRY[standard]
    for spelling in algo.names:
        if spelling in table:
            raise ValueError(f"Algorithm '{spelling}' is already registered for {standard}.")
        table[spelling] = algo
    _MODELS[(standard, name)] = _build_model(algo)
    return algo


# --------------------------------------------------------------------- #
# Lookup / validation API                                                 #
# --------------------------------------------------------------------- #


def get_algorithm(standard: str, name: str) -> SpecAlgorithm | None:
    """Return the algorithm registered under *name* (or alias), else None."""
    return _REGISTRY.get(standard, {}).get(name)


def algorithms(standard: str) -> list[SpecAlgorithm]:
    """Return the canonical algorithm declarations for *standard*."""
    seen: dict[str, SpecAlgorithm] = {}
    for algo in _REGISTRY[standard].values():
        seen.setdefault(algo.name, algo)
    return list(seen.values())


def algorithm_names(standard: str, *, include_aliases: bool = False) -> list[str]:
    """Return registered algorithm names for *standard*.

    Args:
        standard: ``"sdtm"`` or ``"adam"``.
        include_aliases: Also include accepted alias spellings.

    Returns:
        list[str]: Sorted algorithm names.
    """
    if include_aliases:
        return sorted(_REGISTRY[standard])
    return sorted({a.name for a in _REGISTRY[standard].values()})


def model_for(standard: str, name: str) -> type[SpecVariableBase]:
    """Return the generated Pydantic model for algorithm *name*."""
    algo = get_algorithm(standard, name)
    if algo is None:
        raise KeyError(f"No {standard} spec algorithm named '{name}'.")
    return _MODELS[(standard, algo.name)]


def variable_spec_union(standard: str) -> Any:
    """Return the discriminated union of all algorithm models for *standard*."""
    models = tuple(_MODELS[(standard, a.name)] for a in algorithms(standard))
    return Annotated[Union[models], Field(discriminator="algorithm")]  # noqa: UP007


def _adapter(standard: str) -> TypeAdapter:
    if standard not in _ADAPTERS:
        _ADAPTERS[standard] = TypeAdapter(variable_spec_union(standard))
    return _ADAPTERS[standard]


def parse_variable_spec(standard: str, data: Mapping[str, Any]) -> SpecVariableBase:
    """Validate a raw spec dict into its per-algorithm model.

    Args:
        standard: ``"sdtm"`` or ``"adam"``.
        data: Mapping with at least ``target`` and ``algorithm`` keys plus
            the algorithm's params.

    Returns:
        SpecVariableBase: The validated per-algorithm model instance.

    Raises:
        pydantic.ValidationError: On unknown algorithm, missing required
            fields, or unknown keys.

    Examples:
        Validate then execute one derivation against a pipeline::

            from fleet.core import spec_registry

            var = spec_registry.parse_variable_spec(
                "adam", {"target": "CHG", "algorithm": "chg"},
            )
            result = spec_registry.execute_variable(vs_df.adam, var).to_frame()
    """
    return _adapter(standard).validate_python(dict(data))


def suggest_algorithm(standard: str, name: str) -> str | None:
    """Return the closest registered algorithm name to *name*, if any."""
    matches = difflib.get_close_matches(name, list(_REGISTRY[standard]), n=1, cutoff=0.6)
    return matches[0] if matches else None


# --------------------------------------------------------------------- #
# Execution engine                                                        #
# --------------------------------------------------------------------- #


def _resolve_param(ns: Any, var: SpecVariableBase, p: Param, algo: SpecAlgorithm) -> Any:
    """Resolve one param value: target-default, then dispatch-time convert."""
    value = getattr(var, p.name)
    if value is None and p.default_to_target:
        value = var.target
    if p.convert == "pin":
        value = ns._require_pin(str(value).upper(), algo.name)
    elif p.convert == "exprs":
        from fleet.sdtm.utils import parse_expression

        value = [parse_expression(e) for e in (value or [])]
    return value


def _default_dispatch(ns: Any, var: SpecVariableBase) -> Any:
    """Table-driven executor: build kwargs from the param table, call the verb."""
    algo = type(var)._algo
    kwargs = {p.kwarg or p.name: _resolve_param(ns, var, p, algo) for p in algo.params}
    # Spec-level CT config (`ct: {validate: true}`) opts the assign family
    # into pass-through value validation — only algorithms that declare a
    # ct codelist param are affected.
    if getattr(ns, "_spec_ct_validate", False) and any(
        (p.kwarg or p.name) == "ct" for p in algo.params
    ):
        kwargs.setdefault("validate_values", True)
    method = getattr(ns, algo.verb)
    if algo.takes_target:
        return method(var.target, **kwargs)
    return method(**kwargs)


def _spec_block(var: SpecVariableBase) -> dict[str, Any]:
    """Rebuild the define.yaml ``derivation:`` block from a validated model.

    Variable-level metadata (``label``/``origin``/…) and ``target`` are
    stripped — they live at the variable level of a define.yaml.
    """
    data = var.model_dump(by_alias=True, exclude_none=True)
    data.pop("target", None)
    for meta in _META_FIELDS:
        data.pop(meta, None)
    return data


def _attach_spec_lineage(ns: Any, var: SpecVariableBase, algo: SpecAlgorithm, start: int) -> None:
    """Relabel lineage recorded during spec dispatch with the algorithm.

    The verbs a spec algorithm drives record their own name (a spec
    ``study_day`` executes the ``duration`` verb).  For correct
    attribution, every node created for the spec *target(s)* during the
    dispatch is relabelled with the algorithm name and given the
    validated spec block (``VariableNode.spec``) so ``to_spec_yaml()``
    round-trips it verbatim.  By-product columns (e.g. auto-generated
    ``--DTF`` flags) keep their verb attribution and get no spec block.
    """
    lineage = getattr(ns, "_lineage", None)
    if not lineage:
        return
    targets = {var.target}
    extra = getattr(var, "targets", None)
    if extra:
        targets.update(extra)
    block = _spec_block(var)
    for node in lineage[start:]:
        if node.name in targets:
            node.verb = algo.name
            node.spec = dict(block)


def execute_variable(ns: Any, var: SpecVariableBase) -> Any:
    """Execute one validated spec variable against namespace *ns*.

    Args:
        ns: An SDTM/ADaM namespace instance.
        var: A validated per-algorithm model from
            :func:`parse_variable_spec`.

    Returns:
        The namespace returned by the dispatched verb.
    """
    algo = type(var)._algo
    fn = algo.dispatch or _default_dispatch
    start = len(getattr(ns, "_lineage", []))
    out = fn(ns, var)
    _attach_spec_lineage(out, var, algo, start)
    return out


def is_identity_copy(var: SpecVariableBase) -> bool:
    """True when the derivation reads its own target column (in-place op).

    Used by the ``from_spec`` overwrite guard: ``source: USUBJID`` on a
    variable named ``USUBJID`` is a declared carry-through, not an
    accidental overwrite.
    """
    algo = type(var)._algo
    for p in algo.params:
        if not p.identity_source:
            continue
        value = getattr(var, p.name)
        if value is None and p.default_to_target:
            value = var.target
        if isinstance(value, str) and value == var.target:
            return True
    return False


# --------------------------------------------------------------------- #
# Reverse mapping (lineage → derivation block, for to_spec_yaml)          #
# --------------------------------------------------------------------- #

#: Captured verb kwargs that have no spec representation but do not
#: change the derived data — safe to drop when reverse-mapping.
_REVERSE_IGNORED_KWARGS: frozenset[str] = frozenset(
    {"ct_validator", "validate_values", "check_uniqueness", "fk", "verb"}
)

_MISSING = object()


def _candidate_algorithms(standard: str, verb: str) -> list[SpecAlgorithm]:
    """Algorithms that could have produced a lineage node with *verb*.

    A verb that *is* a registered algorithm name (legacy shims like
    ``hardcode_no_ct``, or spec-relabelled nodes like ``study_day``)
    maps directly.  Otherwise every algorithm driving *verb* is a
    candidate, ranked exact-name-match first, then by declared param
    count ascending (the smallest algorithm that covers the call wins).
    """
    direct = get_algorithm(standard, verb)
    if direct is not None:
        return [direct]
    candidates = [a for a in algorithms(standard) if a.verb == verb]
    candidates.sort(key=lambda a: (0 if a.name == verb else 1, len(a.params)))
    return candidates


def _try_build_block(algo: SpecAlgorithm, captured: dict[str, Any], node: Any) -> dict | None:
    """Build a derivation block for *algo* from captured kwargs, or ``None``.

    Fails (returns ``None``) when a required param is missing or when a
    captured non-default kwarg has no spec field — an emitted block must
    reproduce the call faithfully or not at all.
    """
    remaining = dict(captured)
    fields: dict[str, Any] = {}
    for p in algo.params:
        key = p.kwarg or p.name
        if key in remaining:
            value = remaining.pop(key)
        elif p.name in remaining:
            value = remaining.pop(p.name)
        else:
            value = _MISSING
        if value is _MISSING:
            # Identity/input params can be recovered from expression sources.
            if (p.identity_source or p.default_to_target) and len(node.sources) == 1:
                value = node.sources[0]
            elif p.required:
                return None
            else:
                continue
        if p.default_to_target and value == node.name:
            continue  # implicit — the spec defaults it to the target
        try:
            if p.default is not None and bool(value == p.default):
                continue
        except Exception:
            pass
        fields[p.name] = value
    if remaining:
        return None
    return {"algorithm": algo.name, **fields}


def derivation_from_lineage(standard: str, node: Any) -> tuple[str, dict | None, dict]:
    """Reverse-map one lineage ``VariableNode`` to a spec derivation block.

    Resolution order:

    1. ``node.spec`` (set by ``from_spec`` execution and ``@derivation``
       objects) round-trips verbatim.
    2. ``node.params`` (captured verb kwargs) are matched against the
       registry: the node's verb selects the candidate algorithm(s) and
       each captured kwarg must map onto a declared spec param.
    3. Anything else — unknown verb, unserialisable arguments (Polars
       expressions, DataFrames), spec-inexpressible kwargs — yields a
       ``"stub"`` status so the caller can emit an ``algorithm:
       callable`` placeholder.

    Args:
        standard: ``"sdtm"`` or ``"adam"``.
        node: A :class:`~fleet.core.dag.VariableNode`.

    Returns:
        tuple: ``(status, block, meta)`` where *status* is ``"ok"``
            (block usable), ``"stub"`` (not expressible), or
            ``"byproduct"`` (auto-generated side column, e.g. a
            ``--DTF`` flag — no block needed); *block* is the
            ``derivation:`` dict or ``None``; *meta* holds
            variable-level metadata (``label``/``origin``/…) captured
            alongside the call.

    Examples:
        Rebuild a block from an inline pipeline's lineage::

            from fleet.core import spec_registry
            from fleet.core.lineage import latest_lineage_of

            ns = raw_df.sdtm.assign("DOMAIN", value="DM")
            node = latest_lineage_of(ns)[0]
            status, block, _ = spec_registry.derivation_from_lineage("sdtm", node)
            assert status == "ok" and block["algorithm"] == "hardcode_no_ct"
    """
    from fleet.core.lineage import UNSERIALISABLE

    if node.spec:
        return ("ok", dict(node.spec), {})
    params = node.params
    if params is None:
        return ("stub", None, {})

    captured = dict(params)
    target = captured.pop("target", None)
    if isinstance(target, str) and target != node.name:
        # Node created as a side effect of deriving another target
        # (e.g. the auto-generated DTF flag of a date verb).
        return ("byproduct", None, {})

    meta = {
        k: captured.pop(k)
        for k in _META_FIELDS
        if k in captured and captured.get(k) is not UNSERIALISABLE
    }
    captured = {k: v for k, v in captured.items() if k not in _REVERSE_IGNORED_KWARGS}
    if any(v is UNSERIALISABLE for v in captured.values()):
        return ("stub", None, meta)

    for algo in _candidate_algorithms(standard, node.verb):
        block = _try_build_block(algo, captured, node)
        if block is not None:
            return ("ok", block, meta)
    return ("stub", None, meta)


# --------------------------------------------------------------------- #
# Custom dispatchers (non-tabular call shapes)                             #
# --------------------------------------------------------------------- #


def _dispatch_callable(ns: Any, var: SpecVariableBase) -> Any:
    """Resolve ``callable:`` to a registered Derivation or dotted path."""
    from fleet.core._resolve_callable import resolve_callable

    fn = resolve_callable(var.callable_ref or "")
    if hasattr(fn, "kind"):
        return ns.derivation(fn)
    return ns._materialise_then(fn(ns.to_frame()))


def _dispatch_sdtm_date(ns: Any, var: SpecVariableBase) -> Any:
    """SDTM date: source= / value= are exclusive; default source is target."""
    kwargs: dict[str, Any] = {
        "output": var.output,
        "time": var.time,
        "impute": var.impute,
        "impute_time": var.impute_time,
        "highest": var.highest,
        "flag": var.flag,
        "min_date": var.min_date,
        "max_date": var.max_date,
        "format": var.format,
    }
    if var.source is not None:
        kwargs["source"] = var.source
    elif var.value is not None:
        kwargs["value"] = var.value
    else:
        kwargs["source"] = var.target
    return ns.date(var.target, **kwargs)


def _dispatch_nsv(ns: Any, var: SpecVariableBase) -> Any:
    """NSV: label/origin/evaluator come from variable-level metadata."""
    return ns.nsv(
        var.target,
        source=var.source,
        value=var.value if var.source is None else None,
        label=var.label or "",
        origin=var.origin or "DERIVED",
        evaluator=var.evaluator,
    )


def _dispatch_pick(ns: Any, var: SpecVariableBase) -> Any:
    """pick(): multi-target verb; fall back to the variable name."""
    return ns.pick(
        var.targets or [var.target],
        events=var.events,
        by=var.by,
        order=var.order,
        mode=var.mode,
    )


# --------------------------------------------------------------------- #
# SDTM algorithm declarations                                             #
# --------------------------------------------------------------------- #

_STR_OR_NONE = str | None
_LIST_OR_NONE = list[str] | None

spec_algorithm(
    "assign_no_ct",
    standard="sdtm",
    verb="assign",
    params=(
        Param(
            "source",
            default_to_target=True,
            identity_source=True,
            description="Source column; defaults to the variable name (carry-through).",
        ),
    ),
    description="Copy a raw column without controlled-terminology mapping.",
)

spec_algorithm(
    "assign_ct",
    standard="sdtm",
    verb="assign",
    params=(
        Param("source", default_to_target=True, identity_source=True),
        Param(
            "ct_codelist",
            annotation=str,
            kwarg="ct",
            default="",
            description="CT codelist OID.",
        ),
        Param(
            "ct_mapping",
            annotation=dict[str, str] | None,
            kwarg="ct_map",
            description="Explicit raw→CT value mapping.",
        ),
    ),
    description="Copy a raw column applying controlled-terminology mapping.",
)

spec_algorithm(
    "date",
    standard="sdtm",
    verb="date",
    aliases=("assign_dtc",),
    legacy_keys={"input_format": "format"},
    dispatch=_dispatch_sdtm_date,
    params=(
        Param("source", identity_source=True, description="Source date column."),
        Param("value", description="Literal date value to broadcast."),
        Param("output", description="Output type override: 'dt' or 'dtm'."),
        Param("format", description="strftime format of the source column."),
        Param("time", description="Time column or 'HH:MM:SS' literal (DTM targets)."),
        Param("impute", annotation=str, default="first", description="Imputation strategy."),
        Param("impute_time", description="Time-part imputation override."),
        Param("highest", description="Maximum imputation ceiling (D/M/Y/h/m/s)."),
        Param(
            "flag",
            annotation=bool | str,
            default=True,
            description="Auto-generate DTF/TMF flags (bool) or explicit flag name.",
        ),
        Param("min_date", description="Lower clamp bound."),
        Param("max_date", description="Upper clamp bound."),
    ),
    description="Parse, convert, impute, and flag a date/datetime column (ISO 8601).",
)

spec_algorithm(
    "hardcode_ct",
    standard="sdtm",
    verb="assign",
    params=(
        Param("value", annotation=Any, required=True, description="Constant CT value."),
        Param("ct_codelist", kwarg="ct", description="CT codelist OID to validate against."),
    ),
    description="Hardcode a constant validated against controlled terminology.",
)

spec_algorithm(
    "hardcode_no_ct",
    standard="sdtm",
    verb="assign",
    aliases=("dataset_level",),
    params=(Param("value", annotation=Any, required=True, description="Constant value."),),
    description="Hardcode a constant value for all rows.",
)

spec_algorithm(
    "condition_add",
    standard="sdtm",
    verb="condition_add",
    params=(
        Param("condition", annotation=str, required=True, description="Boolean expression."),
        Param(
            "then_value",
            annotation=Any,
            required=True,
            description="Value emitted when the condition is true.",
        ),
    ),
    description="Set a value where a condition holds (null otherwise).",
)

spec_algorithm(
    "if_then_else",
    standard="sdtm",
    verb="case_when",
    params=(
        Param(
            "when",
            annotation=list[dict[str, Any]],
            required=True,
            description="Ordered when/then clause dicts.",
        ),
        Param(
            "else_value",
            annotation=Any,
            kwarg="else_",
            description="Fallback when no clause matches.",
        ),
    ),
    description="Multi-branch conditional derivation.",
)

spec_algorithm(
    "ae_aerel",
    standard="sdtm",
    verb="ae_aerel",
    params=(
        Param(
            "aerel_source",
            annotation=str,
            kwarg="source",
            default="ae_relationship",
            description="Raw relationship column.",
        ),
        Param(
            "aerel_map",
            annotation=dict[str, str] | None,
            description="Raw→AEREL mapping dict.",
        ),
    ),
    description="Map raw relationship values onto AEREL controlled terms.",
)

spec_algorithm(
    "merge",
    standard="sdtm",
    verb="merge",
    takes_target=False,
    legacy_keys={"join_on": "on"},
    params=(
        Param(
            "dataset",
            annotation=str,
            required=True,
            convert="pin",
            description="Pinned dataset name to merge (resolved via .pin()).",
        ),
        Param(
            "on",
            annotation=str | list[str],
            default="USUBJID",
            description="Join key column(s).",
        ),
        Param("how", annotation=str, default="left", description="Join strategy."),
        Param(
            "target_cols",
            annotation=_LIST_OR_NONE,
            kwarg="keep",
            description="Columns to keep from the joined result.",
        ),
    ),
    description="Join a pinned reference dataset into the pipeline.",
)

spec_algorithm(
    "group_by",
    standard="sdtm",
    verb="group_by",
    takes_target=False,
    params=(
        Param(
            "group_cols",
            annotation=list[str],
            kwarg="by",
            required=True,
            description="Grouping columns.",
        ),
        Param(
            "agg",
            annotation=_LIST_OR_NONE,
            convert="exprs",
            description="Aggregation expression strings.",
        ),
    ),
    description="Aggregate the frame by group columns.",
)

spec_algorithm(
    "notsubmitted",
    standard="sdtm",
    verb="notsubmitted",
    overwrite_guard=False,
    description="Null out a variable that is not submitted.",
)

spec_algorithm(
    "multiple_responses",
    standard="sdtm",
    verb="multiple_responses",
    params=(
        Param("source", default_to_target=True, identity_source=True),
        Param("delimiter", annotation=str, default="|", description="Response separator."),
    ),
    description="Explode a delimited multi-response field into rows.",
)

spec_algorithm(
    "seq",
    standard="sdtm",
    verb="seq",
    params=(
        Param(
            "order_by",
            annotation=str | list[str] | None,
            description="Sort column(s) for sequence order.",
        ),
        Param("groups", annotation=_LIST_OR_NONE, kwarg="by", description="Partition columns."),
        Param("start_at", annotation=int, default=1, description="First sequence number."),
    ),
    description="Assign the --SEQ sequence number within each group.",
)

spec_algorithm(
    "nsv",
    standard="sdtm",
    verb="nsv",
    dispatch=_dispatch_nsv,
    params=(
        Param("source", identity_source=True, description="Source column for the qualifier."),
        Param("value", annotation=Any, description="Constant qualifier value."),
    ),
    description="Declare a Non-Standard Variable (SUPPQUAL qualifier).",
)

spec_algorithm(
    "duration",
    standard="sdtm",
    verb="duration",
    legacy_keys={"source": "start"},
    params=(
        Param("start", annotation=str, required=True, description="Start date column."),
        Param("end", annotation=str, required=True, description="End date column."),
        Param("unit", annotation=str, default="days", description="Output unit."),
        Param("add_one", annotation=bool | None, description="CDISC +1 day convention."),
        Param(
            "out",
            annotation=str,
            default="numeric",
            description="Output style: numeric or iso8601.",
        ),
    ),
    description="Compute the duration between two dates.",
)

spec_algorithm(
    "callable",
    standard="sdtm",
    verb="derivation",
    dispatch=_dispatch_callable,
    params=(
        Param(
            "callable_ref",
            annotation=str,
            required=True,
            alias="callable",
            description="Registered derivation name or dotted Python path.",
        ),
    ),
    description="Escape hatch: run a registered or importable custom derivation.",
)


# --------------------------------------------------------------------- #
# ADaM algorithm declarations                                             #
# --------------------------------------------------------------------- #

spec_algorithm(
    "source",
    standard="adam",
    verb="assign",
    params=(
        Param(
            "source",
            identity_source=True,
            default_to_target=True,
            description="Predecessor column; defaults to the variable name.",
        ),
    ),
    description="Copy a column from the predecessor dataset.",
)

spec_algorithm(
    "derivation",
    standard="adam",
    verb="derivation",
    params=(
        Param(
            "expression",
            default_to_target=True,
            identity_source=True,
            description="Polars expression string (or bare column name).",
        ),
    ),
    description="Derive a column from a Polars expression string.",
)

spec_algorithm(
    "assigned",
    standard="adam",
    verb="assign",
    params=(Param("value", annotation=Any, required=True, description="Constant value."),),
    description="Assign a constant value for all rows.",
)

spec_algorithm(
    "recode",
    standard="adam",
    verb="recode",
    params=(
        Param("source", default_to_target=True, identity_source=True),
        Param(
            "recode_map",
            annotation=dict[Any, Any],
            required=True,
            description="Old-value → new-value mapping.",
        ),
        Param("default", annotation=Any, description="Fallback for unmapped values."),
    ),
    description="Map source values onto new values via a lookup dict.",
)

spec_algorithm(
    "rename",
    standard="adam",
    verb="assign",
    params=(Param("source", default_to_target=True, identity_source=True),),
    description="Copy a column under a new CDISC-compliant name.",
)

spec_algorithm(
    "condderivation",
    standard="adam",
    verb="case_when",
    params=(
        Param(
            "conditions",
            annotation=list[dict[str, Any]],
            kwarg="when",
            required=True,
            description="Ordered when/then condition dicts.",
        ),
        Param(
            "else_value",
            annotation=Any,
            kwarg="else_",
            description="Fallback when no condition matches.",
        ),
    ),
    description="Multi-branch conditional derivation.",
)

spec_algorithm(
    "lookup",
    standard="adam",
    verb="merge",
    takes_target=False,
    legacy_keys={"join_on": "on"},
    params=(
        Param(
            "dataset",
            annotation=str,
            required=True,
            convert="pin",
            description="Pinned dataset name to join (resolved via .pin()).",
        ),
        Param(
            "on",
            annotation=str | list[str],
            default="USUBJID",
            description="Join key column(s).",
        ),
        Param("how", annotation=str, default="left", description="Join strategy."),
        Param(
            "target_cols",
            annotation=_LIST_OR_NONE,
            kwarg="keep",
            description="Columns to keep from the joined result.",
        ),
        Param("where", description="Filter applied to the lookup dataset before joining."),
    ),
    description="SQL-style join against a pinned lookup dataset.",
)

spec_algorithm(
    "whereclauses",
    standard="adam",
    verb="whereclauses",
    takes_target=False,
    params=(Param("where", annotation=str, required=True, description="Row filter expression."),),
    description="Filter rows by a boolean expression.",
)

spec_algorithm(
    "study_day",
    standard="adam",
    verb="duration",
    params=(
        Param(
            "analysis_date",
            annotation=str,
            kwarg="end",
            required=True,
            description="Analysis date column (e.g. ADT).",
        ),
        Param(
            "reference_date",
            annotation=str,
            kwarg="start",
            required=True,
            description="Reference date column (e.g. TRTSDT).",
        ),
    ),
    description="Relative study day (analysis date vs reference date).",
)

spec_algorithm(
    "baseline",
    standard="adam",
    verb="baseline",
    params=(
        Param("aval", annotation=str, default="AVAL", description="Analysis value column."),
        Param(
            "baseline_flag",
            annotation=str,
            default="ABLFL",
            description="Baseline record flag column.",
        ),
        Param("groups", annotation=_LIST_OR_NONE, kwarg="by", description="Partition columns."),
    ),
    description="Propagate the baseline value to all records in a group.",
)

spec_algorithm(
    "chg",
    standard="adam",
    verb="chg",
    params=(
        Param("aval", annotation=str, default="AVAL"),
        Param("base", annotation=str, default="BASE"),
    ),
    description="Change from baseline (AVAL - BASE).",
)

spec_algorithm(
    "pchg",
    standard="adam",
    verb="pchg",
    params=(
        Param("aval", annotation=str, default="AVAL"),
        Param("base", annotation=str, default="BASE"),
    ),
    description="Percent change from baseline.",
)

spec_algorithm(
    "flag",
    standard="adam",
    verb="flag",
    legacy_keys={
        "flag_order_by": "order_by",
        "flag_value_col": "value_col",
        "flag_where": "where",
    },
    params=(
        Param(
            "criteria",
            annotation=str,
            required=True,
            description="Row expression or sentinel: first/last/max/min.",
        ),
        Param("groups", annotation=_LIST_OR_NONE, kwarg="by", description="Partition columns."),
        Param(
            "order_by",
            annotation=str | list[str] | None,
            description="Sort column(s) for first/last criteria.",
        ),
        Param("value_col", description="Column for max/min comparison."),
        Param("where", description="Candidate pre-filter expression."),
        Param(
            "flag_value",
            annotation=str,
            default="Y",
            description="Value emitted when the flag condition is met.",
        ),
    ),
    description="Derive a Y/null flag from criteria.",
)

spec_algorithm(
    "bmi",
    standard="adam",
    verb="bmi",
    params=(
        Param("weight", annotation=str, required=True, description="Weight column (kg)."),
        Param("height", annotation=str, required=True, description="Height column (cm)."),
    ),
    description="Body Mass Index from weight and height.",
)

spec_algorithm(
    "nrind",
    standard="adam",
    verb="nrind",
    legacy_keys={"value": "aval"},
    params=(
        Param(
            "aval",
            annotation=str,
            kwarg="value",
            default="AVAL",
            description="Analysis value column.",
        ),
        Param(
            "low",
            annotation=str,
            default="LBSTNRLO",
            description="Lower normal range column.",
        ),
        Param(
            "high",
            annotation=str,
            default="LBSTNRHI",
            description="Upper normal range column.",
        ),
    ),
    description="Reference-range indicator (LOW/NORMAL/HIGH).",
)

spec_algorithm(
    "on_treatment",
    standard="adam",
    verb="on_treatment",
    legacy_keys={"adt": "analysis_date", "trtsdt": "reference_date"},
    params=(
        Param(
            "analysis_date",
            annotation=str,
            kwarg="adt",
            default="ADT",
            description="Analysis date column.",
        ),
        Param(
            "reference_date",
            annotation=str,
            kwarg="trtsdt",
            default="TRTSDT",
            description="Treatment start date column.",
        ),
        Param(
            "trtedt",
            annotation=str,
            default="TRTEDT",
            description="Treatment end date column.",
        ),
        Param(
            "open_ended",
            annotation=bool,
            default=True,
            description="Treat a missing end date as still on treatment.",
        ),
    ),
    description="On-treatment flag from analysis vs treatment dates.",
)

spec_algorithm(
    "shift",
    standard="adam",
    verb="shift",
    params=(
        Param(
            "baseline_cat",
            annotation=str,
            required=True,
            description="Baseline category column.",
        ),
        Param(
            "post_cat",
            annotation=str,
            required=True,
            description="Post-baseline category column.",
        ),
        Param("sep", annotation=str, default=" to ", description="Join separator."),
    ),
    description="Shift-table category ('NORMAL to HIGH').",
)

spec_algorithm(
    "seq",
    standard="adam",
    verb="seq",
    params=(
        Param(
            "order_by",
            annotation=str | list[str] | None,
            description="Sort column(s) for sequence order.",
        ),
        Param("groups", annotation=_LIST_OR_NONE, kwarg="by", description="Partition columns."),
        Param("start_at", annotation=int, default=1, description="First sequence number."),
    ),
    description="Assign the ASEQ sequence number within each group.",
)

spec_algorithm(
    "bsa",
    standard="adam",
    verb="bsa",
    params=(
        Param("weight", annotation=str, required=True, description="Weight column (kg)."),
        Param("height", annotation=str, required=True, description="Height column (cm)."),
        Param("method", annotation=str, default="Mosteller", description="BSA formula."),
    ),
    description="Body Surface Area.",
)

spec_algorithm(
    "map",
    standard="adam",
    verb="map",
    aliases=("mean_arterial_pressure",),
    params=(
        Param("systolic", annotation=str, default="SYSBP", description="Systolic BP column."),
        Param("diastolic", annotation=str, default="DIABP", description="Diastolic BP column."),
    ),
    description="Mean Arterial Pressure.",
)

spec_algorithm(
    "qtc",
    standard="adam",
    verb="qtc",
    params=(
        Param("qt", annotation=str, default="QT", description="QT interval column (ms)."),
        Param("rr", annotation=str, default="RR", description="RR interval column (ms)."),
        Param("method", annotation=str, default="Fridericia", description="Correction formula."),
    ),
    description="Corrected QT interval.",
)

spec_algorithm(
    "atoxgr",
    standard="adam",
    verb="atoxgr",
    params=(
        Param("system", annotation=str, default="ctcae_v5", description="Grading system."),
        Param("direction", annotation=str, required=True, description="'L' or 'H'."),
        Param(
            "term_var",
            annotation=str,
            default="PARAMCD",
            description="Toxicity term variable.",
        ),
        Param("unit_var", description="Unit-of-measure variable."),
        Param(
            "signif_dig",
            annotation=int,
            default=5,
            description="Significant digits for comparisons.",
        ),
        Param(
            "indicators",
            annotation=dict[str, list[str]] | None,
            description="Baseline NRIND indicator lists.",
        ),
    ),
    description="Toxicity grade via criteria-file grading.",
)

spec_algorithm(
    "combine_grades",
    standard="adam",
    verb="combine_grades",
    params=(
        Param("low_var", annotation=str, default="ATOXGRL"),
        Param("high_var", annotation=str, default="ATOXGRH"),
        Param("low_desc_var", description="Low-direction description column."),
        Param("high_desc_var", description="High-direction description column."),
    ),
    description="Combine directional toxicity grades into one column.",
)

spec_algorithm(
    "date",
    standard="adam",
    verb="date",
    params=(
        Param("source", identity_source=True, description="Source date column."),
        Param("value", description="Literal date value to broadcast."),
        Param("output", description="Output type override: 'dt' or 'dtm'."),
        Param("time", description="Time column or 'HH:MM:SS' literal (DTM targets)."),
        Param("impute", annotation=str, default="first", description="Imputation strategy."),
        Param("impute_time", description="Time-part imputation override."),
        Param("highest", description="Maximum imputation ceiling (D/M/Y/h/m/s)."),
        Param(
            "flag",
            annotation=bool | str,
            default=True,
            description="Auto-generate DTF/TMF flags (bool) or explicit flag name.",
        ),
        Param("min_date", description="Lower clamp bound."),
        Param("max_date", description="Upper clamp bound."),
    ),
    description="Parse, convert, impute, and flag an analysis date column.",
)

spec_algorithm(
    "duration",
    standard="adam",
    verb="duration",
    legacy_keys={
        "analysis_date": "start",
        "reference_date": "end",
        "start_date": "start",
        "end_date": "end",
    },
    params=(
        Param("start", annotation=str, required=True, description="Start date column."),
        Param("end", annotation=str, required=True, description="End date column."),
        Param("unit", annotation=str, default="days", description="Output unit."),
        Param("add_one", annotation=bool | None, description="CDISC +1 day convention."),
        Param(
            "out",
            annotation=str,
            default="numeric",
            description="Output style: numeric or iso8601.",
        ),
    ),
    description="Compute the duration between two dates.",
)

spec_algorithm(
    "pick",
    standard="adam",
    verb="pick",
    dispatch=_dispatch_pick,
    params=(
        Param(
            "events",
            annotation=list[dict[str, Any]],
            required=True,
            description="Ordered event definition dicts.",
        ),
        Param(
            "targets",
            annotation=_LIST_OR_NONE,
            description="Output columns; defaults to the variable name.",
        ),
        Param("by", annotation=_LIST_OR_NONE, description="Grouping columns."),
        Param("order", annotation=str | list[str] | None, description="Sort order."),
        Param("mode", annotation=str, default="first", description="'first' or 'last'."),
    ),
    description="Select the first/last matching event per group.",
)

spec_algorithm(
    "first_date",
    standard="adam",
    verb="first_date",
    params=(
        Param(
            "from_dataset",
            annotation=str,
            required=True,
            convert="pin",
            description="Pinned event dataset name (resolved via .pin()).",
        ),
        Param("date_col", annotation=str, required=True, description="Date column to minimise."),
        Param("where", description="Filter applied before aggregation."),
        Param("groups", annotation=_LIST_OR_NONE, kwarg="by", description="Join key columns."),
    ),
    description="Earliest event date per subject from a pinned dataset.",
)

spec_algorithm(
    "last_date",
    standard="adam",
    verb="last_date",
    params=(
        Param(
            "from_dataset",
            annotation=str,
            required=True,
            convert="pin",
            description="Pinned event dataset name (resolved via .pin()).",
        ),
        Param("date_col", annotation=str, required=True, description="Date column to maximise."),
        Param("where", description="Filter applied before aggregation."),
        Param("groups", annotation=_LIST_OR_NONE, kwarg="by", description="Join key columns."),
    ),
    description="Latest event date per subject from a pinned dataset.",
)

spec_algorithm(
    "count_events",
    standard="adam",
    verb="count_events",
    aliases=("count",),
    params=(
        Param(
            "from_dataset",
            annotation=str,
            required=True,
            convert="pin",
            description="Pinned event dataset name (resolved via .pin()).",
        ),
        Param("where", description="Filter applied before counting."),
        Param("groups", annotation=_LIST_OR_NONE, kwarg="by", description="Join key columns."),
    ),
    description="Count matching records per subject from a pinned dataset.",
)

spec_algorithm(
    "callable",
    standard="adam",
    verb="derivation",
    dispatch=_dispatch_callable,
    params=(
        Param(
            "callable_ref",
            annotation=str,
            required=True,
            alias="callable",
            description="Registered derivation name or dotted Python path.",
        ),
    ),
    description="Escape hatch: run a registered or importable custom derivation.",
)


# --------------------------------------------------------------------- #
# Coverage matrix                                                          #
# --------------------------------------------------------------------- #

#: Public namespace verbs that are deliberately **inline-only** (not
#: expressible in a YAML spec).  The reverse-parity test asserts that
#: every public verb is either a registry `verb` or listed here — adding
#: a verb without deciding its spec story fails CI.
SPEC_UNSUPPORTED: dict[str, set[str]] = {
    "sdtm": {
        "study_day",  # pin-based reference join; spec uses duration/study_day forms
        "export_supp",  # terminal exporter, not a derivation
        "baseline_flag",  # inline flag sugar; no per-variable spec semantics yet
        "epoch_assign",  # trial-design lookup (TrialDesignMixin)
        "element_boundaries",  # trial-design lookup (TrialDesignMixin)
        "visit_map",  # trial-design lookup (TrialDesignMixin)
        "add_arms",  # TDD scaffolding (TrialDesignMixin)
        "add_criteria",  # TDD scaffolding (TrialDesignMixin)
        "add_disease_assessments",  # TDD scaffolding (TrialDesignMixin)
        "add_elements",  # TDD scaffolding (TrialDesignMixin)
        "add_milestones",  # TDD scaffolding (TrialDesignMixin)
        "add_parameters",  # TDD scaffolding (TrialDesignMixin)
        "add_visits",  # TDD scaffolding (TrialDesignMixin)
        "fetch_structure",  # TDD scaffolding (TrialDesignMixin)
        "study_header",  # TDD scaffolding (TrialDesignMixin)
        "flag",  # inline-only on SDTM (ADaM has the spec algorithm)
        "criterion",  # multi-column output; no single-target spec semantics
        "flag_first",  # per-mode wrapper over flag()
        "flag_last",  # per-mode wrapper over flag()
        "flag_extreme",  # per-mode wrapper over flag()
        "flag_exists",  # per-mode wrapper over flag()
        "flag_relative",  # per-mode wrapper over flag()
        "keep",  # column restriction; spec path uses select(spec=...)
        "verbs",  # discoverability helper, not a derivation
    },
    "adam": {
        "study_day",  # pin-based reference join; spec algorithm maps to duration
        "join_adsl",  # variadic pin sugar; spec uses lookup
        "merge_adsl",  # pin sugar; spec uses lookup
        "transform",  # spec equivalent is algorithm: callable
        "derive_summary_records",  # frame-reshaping; no single-target semantics
        "derive_locf_records",  # frame-reshaping; no single-target semantics
        "derive_param",  # frame-reshaping; no single-target semantics
        "criterion",  # returns a criterion builder, not a namespace
        "flag_first",  # per-mode wrapper over flag()
        "flag_last",  # per-mode wrapper over flag()
        "flag_extreme",  # per-mode wrapper over flag()
        "flag_exists",  # per-mode wrapper over flag()
        "flag_relative",  # per-mode wrapper over flag()
        "keep",  # column restriction; spec path uses select(spec=...)
        "verbs",  # discoverability helper, not a derivation
    },
}


def coverage_matrix() -> list[dict[str, Any]]:
    """Return the machine-readable algorithm ↔ verb coverage matrix.

    Returns:
        list[dict]: One row per registered algorithm with keys
            ``standard``, ``algorithm``, ``aliases``, ``verb``,
            ``params`` (name list) and ``required`` (name list).

    Examples:
        List which ADaM algorithms are spec-executable::

            from fleet.core.spec_registry import coverage_matrix

            adam_rows = [r for r in coverage_matrix() if r["standard"] == "adam"]
            print({r["algorithm"]: r["verb"] for r in adam_rows})
    """
    rows: list[dict[str, Any]] = []
    for standard in ("sdtm", "adam"):
        for algo in algorithms(standard):
            rows.append(
                {
                    "standard": standard,
                    "algorithm": algo.name,
                    "aliases": list(algo.aliases),
                    "verb": algo.verb,
                    "params": [p.name for p in algo.params],
                    "required": [p.name for p in algo.params if p.required],
                }
            )
    return rows


# --------------------------------------------------------------------- #
# JSON-schema generation                                                   #
# --------------------------------------------------------------------- #

_SCHEMA_STRIP_FIELDS: tuple[str, ...] = ("target", *_META_FIELDS)


def derivation_json_schema() -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the JSON-schema fragment for the define.yaml derivation block.

    Returns:
        tuple: ``(derivation_def, model_defs)`` where *derivation_def* is
            the schema object for ``$defs.derivation`` and *model_defs*
            maps model names to their per-algorithm schemas (to be merged
            into the document's top-level ``$defs``).

    The per-algorithm schemas are generated from the registry models via
    Pydantic (``TypeAdapter(...).json_schema()``), then stripped of the
    ``target`` and variable-level metadata fields, which live at the
    variable level of a define.yaml rather than inside ``derivation``.
    """
    model_defs: dict[str, Any] = {}
    branches: list[dict[str, Any]] = []
    for standard in ("sdtm", "adam"):
        schema = _adapter(standard).json_schema(by_alias=True, ref_template="#/$defs/{model}")
        model_defs.update(schema.pop("$defs", {}))
        branches.append(schema)

    for model_schema in model_defs.values():
        props = model_schema.get("properties", {})
        for name in _SCHEMA_STRIP_FIELDS:
            props.pop(name, None)
        required = [r for r in model_schema.get("required", []) if r not in _SCHEMA_STRIP_FIELDS]
        if required:
            model_schema["required"] = required
        else:
            model_schema.pop("required", None)

    # Backward-compat: a bare `callable:` block without `algorithm:` is
    # accepted by from_spec (the algorithm is injected automatically).
    branches.append(
        {
            "type": "object",
            "description": (
                "Backward-compat callable block — `algorithm: callable` is "
                "injected automatically when only `callable:` is present."
            ),
            "required": ["callable"],
            "properties": {"callable": {"type": "string"}},
            "additionalProperties": False,
        }
    )

    derivation_def = {
        "title": "Derivation",
        "description": (
            "Describes how a variable is derived by the Fleet pipeline "
            "engine. Validated per algorithm: unknown keys are rejected. "
            "Generated from fleet.core.spec_registry — do not edit by hand; "
            "run `python -m fleet.define_xml.schema_builder` to regenerate."
        ),
        "anyOf": branches,
    }
    return derivation_def, dict(sorted(model_defs.items()))
