"""Single source of truth for spec-executable derivations: the verb is the algorithm.

Every verb a define.yaml can run is declared **once** here with
:func:`spec_verb`.  The ``algorithm:`` value of a ``derivation:`` block is
the verb name, and the YAML keys are the keyword arguments of the verb
(ADR-0008).  The rule for the programmer: remove ``.verb("TARGET", `` and
the last ``)``; what stays is the YAML block.

From the verb signature, read on first lookup, Fleet derives:

* the strict per-verb **Pydantic model** (required fields required,
  ``extra="forbid"``, so a typo like ``recod_map`` is a validation error,
  not a silent column of nulls);
* the **YAML type** of every key, through a fixed table: a Polars
  expression is an expression string, a frame is the name of a pinned
  dataset, a codelist class is a codelist id, a ``@derivation`` object is
  its registered name or dotted path;
* the table-driven ``from_spec`` executor and the reverse mapping that
  ``to_spec_yaml()`` and the static converter apply;
* the ``derivation`` section of the published JSON schema and the
  machine-checked coverage matrix (verb ↔ ``SPEC_UNSUPPORTED``).

A declaration says only what a signature cannot say: the keyword arguments
kept out of the spec, the ones that exclude each other, the ones the spec
requires although the verb has a default, which argument is the input
column, and the Define-XML method text.

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

import builtins
import collections.abc
import difflib
import inspect
import keyword
import re
import types
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Annotated, Any, ClassVar, Literal, Union, get_args, get_origin

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, create_model, model_validator

__all__ = [
    "SPEC_UNSUPPORTED",
    "SpecAlgorithm",
    "SpecField",
    "SpecVariableBase",
    "algorithm_names",
    "algorithms",
    "coverage_matrix",
    "derivation_from_lineage",
    "execute_variable",
    "get_algorithm",
    "is_identity_copy",
    "model_for",
    "parse_variable_spec",
    "render_formal_expression",
    "render_method_text",
    "spec_verb",
    "suggest_algorithm",
    "variable_spec_union",
    "with_codelist",
]


# --------------------------------------------------------------------- #
# Declaration dataclasses                                                #
# --------------------------------------------------------------------- #


@dataclass(frozen=True)
class SpecField:
    """One YAML key of a verb, derived from the verb signature (ADR-0008).

    Args:
        name: The YAML key.  The keyword argument without a trailing
            underscore that avoids a Python keyword (``else_`` is ``else``).
        kwarg: The keyword argument of the verb the value is passed to.
        annotation: The YAML type: the Python type after the conversion
            table (an expression is a string, a frame is a pin name).
        required: Whether the key must be present in the spec.
        default: The default the verb applies when the key is omitted.
        convert: Dispatch-time conversion: ``"pin"`` resolves a pinned
            dataset name, ``"expr"`` parses an expression string.
        description: The ``Args:`` line of the verb docstring.
        extra: True for a spec-only key that is not a keyword of the verb
            (``callable`` on ``derivation``, ``targets`` on ``pick``).
    """

    name: str
    kwarg: str
    annotation: Any
    required: bool
    default: Any = None
    convert: str | None = None
    description: str = ""
    extra: bool = False


@dataclass(frozen=True)
class SpecAlgorithm:
    """A spec-executable verb: what the signature cannot say, plus the derived fields.

    Args:
        name: The ``algorithm:`` value in YAML. It is the verb name.
        standard: ``"sdtm"`` or ``"adam"``.
        verb: Namespace method the algorithm drives. Dotted for a
            sub-namespace verb (``onco.best_overall_response``).
        params: The derived :class:`SpecField` entries, in signature order.
        exclude: Keyword arguments kept out of the spec.
        exclusive: Keyword arguments of which at most one may be given.
        one_of: Keyword arguments of which exactly one must be given.
        required: Keyword arguments the spec requires although the verb
            has a default (the spec may be stricter, never looser).
        target_default: Keyword arguments that take the variable name
            when omitted (a carry-through ``source``).
        identity: The keyword that names the input column; when its
            value is the target the derivation is an in-place operation,
            exempt from the ``from_spec`` overwrite guard.
        extra: Spec-only fields as ``(name, annotation, default)``.
        takes_target: Whether the verb receives the variable name as its
            first positional argument.
        overwrite_guard: Whether the ``from_spec`` overwrite guard applies.
        dispatch: Optional custom executor ``(ns, var) -> ns``.
        description: One-line description for docs and the JSON schema.
        method_text: Define-XML ``MethodDef`` text shapes as
            ``(keys, template)`` pairs: the first shape whose keys are all
            given in the block renders, so one verb keeps the standards
            vocabulary a reviewer reads ("mapped to controlled
            terminology" when ``ct`` is given).  Review as content.
    """

    name: str
    standard: str
    verb: str
    params: tuple[SpecField, ...] = ()
    exclude: tuple[str, ...] = ()
    exclusive: tuple[str, ...] = ()
    one_of: tuple[str, ...] = ()
    required: tuple[str, ...] = ()
    target_default: tuple[str, ...] = ()
    identity: str | None = None
    extra: tuple[tuple[str, Any, Any], ...] = ()
    takes_target: bool = True
    overwrite_guard: bool = True
    dispatch: Callable[[Any, SpecVariableBase], Any] | None = None
    description: str = ""
    method_text: tuple[tuple[frozenset[str], str], ...] = ()


# --------------------------------------------------------------------- #
# Generated model machinery                                               #
# --------------------------------------------------------------------- #

#: Variable-level metadata accepted on every algorithm model.  These keys
#: are merged in from the variable entry of a define.yaml (label, origin,
#: role, evaluator) and are legitimate on any derivation.
_META_FIELDS: tuple[str, ...] = ("label", "origin", "role", "evaluator")

#: Keyword arguments no spec exposes: validators and runtime switches.
_ALWAYS_EXCLUDED: frozenset[str] = frozenset(
    {"ct_validator", "validate_values", "check_uniqueness"}
)


class SpecVariableBase(BaseModel):
    """Base of every generated per-verb model."""

    model_config = ConfigDict(extra="forbid")

    _algo: ClassVar[SpecAlgorithm]

    target: str

    @model_validator(mode="after")
    def _check_argument_groups(self) -> SpecVariableBase:
        """Enforce the ``exclusive`` and ``one_of`` groups of the declaration."""
        algo = type(self)._algo
        given = {f.kwarg for f in algo.params if getattr(self, f.kwarg, None) is not None}
        if algo.exclusive and len(given & set(algo.exclusive)) > 1:
            raise ValueError(f"{', '.join(algo.exclusive)} exclude each other; give one of them.")
        if algo.one_of and len(given & set(algo.one_of)) != 1:
            raise ValueError(f"exactly one of {', '.join(algo.one_of)} is required.")
        return self


def _model_name(algo: SpecAlgorithm) -> str:
    prefix = "SDTM" if algo.standard == "sdtm" else "ADAM"
    camel = "".join(part.capitalize() for part in re.split(r"[._]", algo.name))
    return f"{prefix}{camel}Spec"


def _build_model(algo: SpecAlgorithm) -> type[SpecVariableBase]:
    """Generate the strict Pydantic model for one verb."""
    fields: dict[str, Any] = {
        "algorithm": (Literal[algo.name], Field(..., description=algo.description or None)),
    }
    for f in algo.params:
        default = ... if f.required else f.default
        alias = f.name if f.name != f.kwarg else None
        fields[f.kwarg] = (
            f.annotation,
            Field(default, alias=alias, description=f.description or None),
        )
    for meta in _META_FIELDS:
        fields.setdefault(meta, (str | None, Field(None)))
    if algo.standard == "adam":
        # depends_on drives the auto-flush staging in from_spec().
        fields.setdefault("depends_on", (list[str] | None, Field(None)))
    model = create_model(_model_name(algo), __base__=SpecVariableBase, **fields)
    model._algo = algo
    return model


# --------------------------------------------------------------------- #
# Reading the verb signature                                              #
# --------------------------------------------------------------------- #

_SECTION_RE = re.compile(r"^[A-Z][A-Za-z ]*:\s*$")
_ARG_RE = re.compile(r"^(\*{0,2}\w+)(?:\s*\([^)]*\))?:\s*(.*)$")
# A full stop then a space ends a sentence, unless it closes "e.g.", "i.e.", "etc." or "vs.".
_SENTENCE_END_RE = re.compile(r"(?<!\be\.g)(?<!\bi\.e)(?<!\betc)(?<!\bvs)\. ")
_FRAME_TYPES: tuple[type, ...] = (pl.DataFrame, pl.LazyFrame)


def _namespace_class(standard: str) -> type | None:
    """The namespace class whose methods the *standard*'s verbs are.

    Imported here, not at module load: the namespaces import this module.
    """
    if standard == "sdtm":
        from fleet.sdtm.namespace import SDTMNamespace

        return SDTMNamespace
    if standard == "adam":
        from fleet.adam.namespace import AdamNamespace

        return AdamNamespace
    return None


class _AnyForUnknownNames(dict):
    """Namespace for annotation evaluation: a name imported under ``TYPE_CHECKING`` is ``Any``."""

    def __missing__(self, name: str) -> Any:
        return getattr(builtins, name, Any)


def _eval_annotation(annotation: Any, fn: Any) -> Any:
    """Resolve a (possibly string) annotation in the namespace of *fn*.

    The namespaces import ``Callable``, ``Derivation`` or ``CTValidator``
    under ``TYPE_CHECKING`` only, so those names are missing at run time.
    ``Callable`` is restored (the lambda form is dropped from the YAML type)
    and any other missing name reads as ``Any``.
    """
    if annotation is inspect.Parameter.empty:
        return Any
    if not isinstance(annotation, str):
        return annotation
    namespace = _AnyForUnknownNames(getattr(fn, "__globals__", {}))
    namespace.setdefault("Callable", collections.abc.Callable)
    try:
        return eval(annotation, {"__builtins__": __builtins__}, namespace)  # noqa: S307
    except Exception:
        return Any


def _namespace_method(standard: str, verb: str) -> Any | None:
    """The function behind *verb* on the *standard*'s namespace.

    A dotted verb walks the sub-namespace properties through their return
    annotations (``adam.onco.best_overall_response``).
    """
    cls = _namespace_class(standard)
    if cls is None:
        return None
    *path, name = verb.split(".")
    for part in path:
        prop = getattr(cls, part, None)
        fget = getattr(prop, "fget", None)
        if fget is None:
            return None
        sub = _eval_annotation(inspect.signature(fget).return_annotation, fget)
        if sub is Any or not isinstance(sub, type):
            # A TYPE_CHECKING-only annotation: ask the property on an empty frame.
            try:
                sub = type(fget(cls(pl.DataFrame())))
            except Exception:
                return None
        cls = sub
    fn = getattr(cls, name, None)
    return fn if callable(fn) else None


def _docstring_arg_descriptions(fn: Any) -> dict[str, str]:
    """First sentence of each ``Args:`` entry of a Google-style docstring."""
    doc = inspect.getdoc(fn) or ""
    out: dict[str, str] = {}
    in_args = False
    current: str | None = None
    for line in doc.splitlines():
        stripped = line.strip()
        if _SECTION_RE.match(stripped):
            in_args = stripped == "Args:"
            current = None
            continue
        if not in_args or not stripped:
            continue
        indent = len(line) - len(line.lstrip())
        m = _ARG_RE.match(stripped)
        if m and indent <= 4:
            current = m.group(1).lstrip("*")
            out[current] = m.group(2).strip()
        elif current is not None:
            out[current] = f"{out[current]} {stripped}".strip()
    for name, text in out.items():
        end = _SENTENCE_END_RE.search(text)
        out[name] = text[: end.start() + 1] if end else text
    return out


def _is_callable_type(tp: Any) -> bool:
    return tp is Callable or get_origin(tp) is collections.abc.Callable


def _yaml_type(tp: Any) -> tuple[Any, str | None]:
    """The YAML type of a Python annotation, and the conversion it needs.

    The table of ADR-0008: a Polars expression is an expression string, a
    frame is the name of a pinned dataset, a codelist class is a codelist
    id.  A zero-argument callable (the lambda form) stays inline-only and
    is dropped from the union.  A string form the verb already parses needs
    no conversion.
    """
    if tp is pl.Expr:
        return str, "expr"
    if tp in _FRAME_TYPES:
        return str, "pin"
    if tp is type:
        return str, None
    origin = get_origin(tp)
    if origin in (Union, types.UnionType):
        members: list[Any] = []
        kinds: set[str] = set()
        args = [arg for arg in get_args(tp) if not _is_callable_type(arg)]
        for arg in args:
            yt, kind = _yaml_type(arg)
            if kind:
                kinds.add(kind)
            if yt not in members:
                members.append(yt)
        if str in args or list[str] in args:
            kinds.discard("expr")  # the verb parses the string form itself
        yaml_tp = Union[tuple(members)] if len(members) > 1 else members[0]  # noqa: UP007
        return yaml_tp, (kinds.pop() if len(kinds) == 1 else None)
    if origin is list and get_args(tp):
        inner, kind = _yaml_type(get_args(tp)[0])
        return list[inner], kind  # type: ignore[valid-type]
    return tp, None


def _yaml_name(kwarg: str) -> str:
    """``else_`` is written ``else`` in YAML: one trailing underscore goes."""
    if kwarg.endswith("_") and keyword.iskeyword(kwarg[:-1]):
        return kwarg[:-1]
    return kwarg


def _fields_from_signature(algo: SpecAlgorithm, fn: Any) -> tuple[SpecField, ...]:
    """Derive the YAML keys of *algo* from the signature of its verb."""
    sig = inspect.signature(fn)
    docs = _docstring_arg_descriptions(fn)
    params = [p for name, p in sig.parameters.items() if name != "self"]
    if algo.takes_target and params:
        params = params[1:]
    excluded = _ALWAYS_EXCLUDED | set(algo.exclude)
    fields: list[SpecField] = []
    for p in params:
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD) or p.name in excluded:
            continue
        annotation, convert = _yaml_type(_eval_annotation(p.annotation, fn))
        has_default = p.default is not p.empty
        if p.name in algo.target_default:
            required, default = False, None
            annotation = annotation | None if annotation is not Any else annotation
        else:
            required = not has_default or p.name in algo.required
            default = None if required else p.default
        fields.append(
            SpecField(
                name=_yaml_name(p.name),
                kwarg=p.name,
                annotation=annotation,
                required=required,
                default=default,
                convert=convert,
                description=docs.get(p.name, ""),
            )
        )
    for name, annotation, default in algo.extra:
        fields.append(
            SpecField(name, name, annotation, required=False, default=default, extra=True)
        )
    return tuple(fields)


# --------------------------------------------------------------------- #
# Registry storage & registration                                         #
# --------------------------------------------------------------------- #

_DECLARED: dict[str, dict[str, SpecAlgorithm]] = {"sdtm": {}, "adam": {}}
_RESOLVED: dict[tuple[str, str], SpecAlgorithm] = {}
_MODELS: dict[tuple[str, str], type[SpecVariableBase]] = {}
_ADAPTERS: dict[str, TypeAdapter] = {}


def spec_verb(
    verb: str,
    *,
    standard: str,
    exclude: tuple[str, ...] = (),
    exclusive: tuple[str, ...] = (),
    one_of: tuple[str, ...] = (),
    required: tuple[str, ...] = (),
    target_default: tuple[str, ...] = (),
    identity: str | None = None,
    extra: tuple[tuple[str, Any, Any], ...] = (),
    takes_target: bool = True,
    overwrite_guard: bool = True,
    dispatch: Callable[[Any, SpecVariableBase], Any] | None = None,
    description: str = "",
    method_text: tuple[tuple[set[str] | frozenset[str], str], ...] = (),
) -> SpecAlgorithm:
    """Declare that *verb* can run from a define.yaml (single source of truth).

    The YAML keys come from the verb signature on first lookup, so the
    declaration states only what the signature cannot say.

    Args:
        verb: The verb name, which is the ``algorithm:`` value in YAML.
            Dotted for a sub-namespace verb.
        standard: ``"sdtm"`` or ``"adam"``.
        exclude: Keyword arguments kept out of the spec.
        exclusive: Keyword arguments of which at most one may be given.
        one_of: Keyword arguments of which exactly one must be given.
        required: Keyword arguments the spec requires although the verb
            has a default.
        target_default: Keyword arguments that take the variable name
            when omitted.
        identity: The keyword that names the input column.
        extra: Spec-only fields as ``(name, annotation, default)``.
        takes_target: Whether the verb takes the target name positionally.
        overwrite_guard: Whether the overwrite guard applies to *target*.
        dispatch: Custom executor for non-tabular call shapes.
        description: One-line description for docs and the JSON schema.
        method_text: Define-XML text shapes, ``(keys, template)``.

    Returns:
        SpecAlgorithm: The declaration (fields resolved on first lookup).

    Raises:
        ValueError: If *verb* is already registered for *standard*.

    Examples:
        Declare the ``chg`` verb for ADaM specs::

            spec_verb(
                "chg",
                standard="adam",
                description="Change from baseline (AVAL - BASE).",
                method_text=((set(), "Change from baseline: {aval} - {base}."),),
            )
    """
    if verb in _DECLARED[standard]:
        raise ValueError(f"Algorithm '{verb}' is already registered for {standard}.")
    algo = SpecAlgorithm(
        name=verb,
        standard=standard,
        verb=verb,
        exclude=exclude,
        exclusive=exclusive,
        one_of=one_of,
        required=required,
        target_default=target_default,
        identity=identity,
        extra=extra,
        takes_target=takes_target,
        overwrite_guard=overwrite_guard,
        dispatch=dispatch,
        description=description,
        method_text=tuple((frozenset(keys), text) for keys, text in method_text),
    )
    _DECLARED[standard][verb] = algo
    _ADAPTERS.pop(standard, None)
    return algo


def _resolved(declared: SpecAlgorithm) -> SpecAlgorithm:
    """The declaration with its fields read from the verb signature (cached)."""
    key = (declared.standard, declared.name)
    if key not in _RESOLVED:
        fn = _namespace_method(declared.standard, declared.verb)
        if fn is None:
            raise LookupError(
                f"spec_verb({declared.verb!r}, standard={declared.standard!r}): "
                f"the {declared.standard} namespace has no such verb."
            )
        _RESOLVED[key] = replace(declared, params=_fields_from_signature(declared, fn))
    return _RESOLVED[key]


# --------------------------------------------------------------------- #
# Lookup / validation API                                                 #
# --------------------------------------------------------------------- #


def get_algorithm(standard: str, name: str) -> SpecAlgorithm | None:
    """Return the verb registered under *name* for *standard*, else None."""
    declared = _DECLARED.get(standard, {}).get(name)
    return None if declared is None else _resolved(declared)


def algorithms(standard: str) -> list[SpecAlgorithm]:
    """Return the resolved declarations for *standard*, in registration order."""
    return [_resolved(a) for a in _DECLARED[standard].values()]


def algorithm_names(standard: str) -> list[str]:
    """Return the sorted ``algorithm:`` values for *standard*."""
    return sorted(_DECLARED[standard])


def model_for(standard: str, name: str) -> type[SpecVariableBase]:
    """Return the generated Pydantic model for the verb *name*."""
    algo = get_algorithm(standard, name)
    if algo is None:
        raise KeyError(f"No {standard} spec algorithm named '{name}'.")
    key = (standard, algo.name)
    if key not in _MODELS:
        _MODELS[key] = _build_model(algo)
    return _MODELS[key]


def variable_spec_union(standard: str) -> Any:
    """Return the discriminated union of all verb models for *standard*."""
    models = tuple(model_for(standard, name) for name in _DECLARED[standard])
    return Annotated[Union[models], Field(discriminator="algorithm")]  # noqa: UP007


def _adapter(standard: str) -> TypeAdapter:
    if standard not in _ADAPTERS:
        _ADAPTERS[standard] = TypeAdapter(variable_spec_union(standard))
    return _ADAPTERS[standard]


def parse_variable_spec(standard: str, data: Mapping[str, Any]) -> SpecVariableBase:
    """Validate a raw spec dict into its per-verb model.

    Args:
        standard: ``"sdtm"`` or ``"adam"``.
        data: Mapping with at least ``target`` and ``algorithm`` keys plus
            the keyword arguments of the verb.

    Returns:
        SpecVariableBase: The validated per-verb model instance.

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
    matches = difflib.get_close_matches(name, list(_DECLARED[standard]), n=1, cutoff=0.6)
    return matches[0] if matches else None


def with_codelist(standard: str, block: Mapping[str, Any], codelist: str | None) -> dict[str, Any]:
    """Fill ``ct`` from the variable's ``codelist:`` when the block omits it (ADR-0008).

    A verb with a ``ct`` keyword checks its values against the codelist the
    variable declares, so the id is written once.  A ``ct_map`` with no
    codelist anywhere is an error, because a mapping needs a codelist.

    Args:
        standard: ``"sdtm"`` or ``"adam"``.
        block: The ``derivation:`` block, with its ``algorithm``.
        codelist: The ``codelist:`` of the variable, if any.

    Returns:
        dict: The block, with ``ct`` filled in when it applies.

    Raises:
        ValueError: When the block maps values with ``ct_map`` and neither
            ``ct`` nor the variable's ``codelist:`` names the codelist.
    """
    algo = get_algorithm(standard, str(block.get("algorithm", "")))
    if algo is None or "ct" in block or not any(f.kwarg == "ct" for f in algo.params):
        return dict(block)
    if codelist:
        return {**block, "ct": codelist}
    if block.get("ct_map"):
        raise ValueError(
            "ct_map needs a codelist: give ct: in the derivation, or codelist: on the variable."
        )
    return dict(block)


# --------------------------------------------------------------------- #
# Execution engine                                                        #
# --------------------------------------------------------------------- #


def _convert(ns: Any, algo: SpecAlgorithm, f: SpecField, value: Any) -> Any:
    """Apply the dispatch-time conversion of the YAML type table."""
    if value is None or f.convert is None:
        return value
    if f.convert == "pin":
        if isinstance(value, list):
            return [ns._require_pin(str(v).upper(), algo.name) for v in value]
        return ns._require_pin(str(value).upper(), algo.name)
    if f.convert == "expr":
        from fleet.sdtm.utils import parse_expression

        if isinstance(value, list):
            return [parse_expression(e) for e in value]
        return parse_expression(value)
    return value


def _takes_target_default(var: SpecVariableBase, algo: SpecAlgorithm, kwarg: str) -> bool:
    """Whether an omitted *kwarg* takes the variable name.

    Not when another member of its exclusive group is given: ``assign``
    with ``value`` is a constant, not a copy of the target column.
    """
    if kwarg not in algo.target_default:
        return False
    if kwarg in algo.exclusive:
        others = (k for k in algo.exclusive if k != kwarg)
        return all(getattr(var, k, None) is None for k in others)
    return True


def _resolve_field(ns: Any, var: SpecVariableBase, f: SpecField, algo: SpecAlgorithm) -> Any:
    """Resolve one field value: target default, then conversion."""
    value = getattr(var, f.kwarg)
    if value is None and _takes_target_default(var, algo, f.kwarg):
        value = var.target
    return _convert(ns, algo, f, value)


def _method(ns: Any, verb: str) -> Any:
    """The bound verb on *ns*, walking sub-namespaces for a dotted name."""
    obj = ns
    for part in verb.split("."):
        obj = getattr(obj, part)
    return obj


def _default_dispatch(ns: Any, var: SpecVariableBase) -> Any:
    """Table-driven executor: the keys become the keyword arguments of the verb."""
    algo = type(var)._algo
    kwargs = {f.kwarg: _resolve_field(ns, var, f, algo) for f in algo.params if not f.extra}
    # Spec-level CT config (`ct: {validate: true|false}`) sets the value check of
    # the verbs with a codelist keyword.
    spec_ct_validate = getattr(ns, "_spec_ct_validate", None)
    if spec_ct_validate is not None and "ct" in kwargs:
        kwargs.setdefault("validate_values", spec_ct_validate)
    # from_spec put the study's codelists.py classes here; an ID they lack stays a string.
    codelists = getattr(ns, "_spec_codelists", None)
    if codelists and isinstance(kwargs.get("ct"), str):
        kwargs["ct"] = codelists.get(kwargs["ct"], kwargs["ct"])
    method = _method(ns, algo.verb)
    if algo.takes_target:
        return method(var.target, **kwargs)
    return method(**kwargs)


def _spec_block(var: SpecVariableBase) -> dict[str, Any]:
    """Rebuild the define.yaml ``derivation:`` block from a validated model.

    Only the keys the spec gave are kept (defaults stay implicit), so the
    block round-trips verbatim.  Variable-level metadata
    (``label``/``origin``/…) and ``target`` are stripped — they live at
    the variable level of a define.yaml.
    """
    data = var.model_dump(by_alias=True, exclude_none=True, exclude_unset=True)
    data.pop("target", None)
    for meta in _META_FIELDS:
        data.pop(meta, None)
    return data


def _attach_spec_lineage(ns: Any, var: SpecVariableBase, start: int) -> None:
    """Give the lineage nodes of the spec target(s) the validated block.

    The verb records its own name, which is the algorithm.  The block is
    attached as ``VariableNode.spec`` so ``to_spec_yaml()`` round-trips it
    verbatim, pinned frames and codelist classes included.  By-product
    columns (an auto-generated ``--DTF`` flag) get no block.
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
            node.spec = dict(block)


def execute_variable(ns: Any, var: SpecVariableBase) -> Any:
    """Execute one validated spec variable against namespace *ns*.

    Args:
        ns: An SDTM/ADaM namespace instance.
        var: A validated per-verb model from :func:`parse_variable_spec`.

    Returns:
        The namespace returned by the dispatched verb.
    """
    algo = type(var)._algo
    fn = algo.dispatch or _default_dispatch
    start = len(getattr(ns, "_lineage", []))
    out = fn(ns, var)
    _attach_spec_lineage(out, var, start)
    return out


def is_identity_copy(var: SpecVariableBase) -> bool:
    """True when the derivation reads its own target column (in-place op).

    Used by the ``from_spec`` overwrite guard: ``source: USUBJID`` on a
    variable named ``USUBJID`` is a declared carry-through, not an
    accidental overwrite.
    """
    algo = type(var)._algo
    if algo.identity is None:
        return False
    value = getattr(var, algo.identity, None)
    if value is None and _takes_target_default(var, algo, algo.identity):
        value = var.target
    return isinstance(value, str) and value == var.target


# --------------------------------------------------------------------- #
# Reverse mapping (lineage → derivation block, for to_spec_yaml)          #
# --------------------------------------------------------------------- #

#: Captured kwargs that never appear in a spec block: validators, runtime
#: switches, and lineage bookkeeping.
_REVERSE_IGNORED_KWARGS: frozenset[str] = _ALWAYS_EXCLUDED | {"fk", "verb"}


def _build_block(algo: SpecAlgorithm, captured: dict[str, Any], node: Any) -> dict | None:
    """Build a derivation block from captured kwargs, or ``None``.

    Fails (returns ``None``) when a required key is missing or when a
    captured non-default kwarg has no YAML key — an emitted block must
    reproduce the call faithfully or not at all.
    """
    remaining = dict(captured)
    fields: dict[str, Any] = {}
    for f in algo.params:
        if f.extra:
            continue
        if f.kwarg in remaining:
            value = remaining.pop(f.kwarg)
        elif (f.kwarg == algo.identity or f.kwarg in algo.target_default) and len(
            node.sources
        ) == 1:
            value = node.sources[0]
        elif f.required:
            return None
        else:
            continue
        if f.kwarg in algo.target_default and value == node.name:
            continue  # implicit — the spec defaults it to the target
        try:
            if f.default is not None and bool(value == f.default):
                continue
        except Exception:
            pass
        fields[f.name] = value
    if remaining:
        return None
    return {"algorithm": algo.name, **fields}


def derivation_from_lineage(standard: str, node: Any) -> tuple[str, dict | None, dict]:
    """Reverse-map one lineage ``VariableNode`` to a spec derivation block.

    Resolution order:

    1. ``node.spec`` (set by ``from_spec`` execution and ``@derivation``
       objects) round-trips verbatim.
    2. ``node.params`` (captured verb kwargs) become the keys of the block
       of the verb the node records: one verb, one block.
    3. Anything else — unknown verb, unserialisable arguments (Polars
       expressions, DataFrames), spec-inexpressible kwargs — yields a
       ``"stub"`` status so the caller can emit a placeholder.

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
            assert status == "ok" and block == {"algorithm": "assign", "value": "DM"}
    """
    from fleet.core.lineage import UNSERIALISABLE

    if node.spec:
        return ("ok", dict(node.spec), {})
    if node.verb == "source":
        # source() is carry-through sugar: a define.yaml writes it as assign.
        src = node.sources[0] if node.sources else node.name
        block: dict[str, Any] = {"algorithm": "assign"}
        if src != node.name:
            block["source"] = src
        return ("ok", block, {})
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

    algo = get_algorithm(standard, node.verb)
    if algo is not None:
        block = _build_block(algo, captured, node)
        if block is not None:
            return ("ok", block, meta)
    return ("stub", None, meta)


# --------------------------------------------------------------------- #
# Define-XML method text (single choke point for both spec paths)          #
# --------------------------------------------------------------------- #

#: ``{key}`` placeholders inside a method text template.
_TEMPLATE_KEYS_RE = re.compile(r"{(\w+)}")


def _fmt_value(value: Any) -> str:
    """Render one value as reviewer-readable prose (no Python reprs)."""
    if isinstance(value, dict):
        return "; ".join(f"{k} → {v}" for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return str(value)


def _is_study_day(algorithm: str, params: Mapping[str, Any], target: str | None) -> bool:
    """Whether a ``duration`` block follows the study-day rule of the verb.

    The verb applies the SDTMIG study-day rule (no day 0) to a ``*DY``
    target in days when ``add_one`` is not given.

    References:
        SDTMIG 3.4, section 4.4.4 (Use of the Study Day Variables).
    """
    return (
        algorithm == "duration"
        and bool(target)
        and str(target).endswith("DY")
        and params.get("unit", "days") in (None, "days")
        and params.get("add_one") is None
    )


def render_method_text(
    standard: str,
    algorithm: str,
    params: Mapping[str, Any],
    *,
    target: str | None = None,
) -> str | None:
    """Reviewer-facing derivation text for a Define-XML ``MethodDef``.

    The single text source both spec paths share: the spec-driven
    generator passes the validated ``derivation:`` block, the inline
    path passes the block reverse-mapped from lineage — identical input,
    identical submission text.  Fleet verb docstrings are never used
    (API-shaped, generic, and unstable across Fleet versions).

    Resolution: the first ``method_text`` shape of the verb whose keys are
    all given in the block (defaults filled), otherwise text synthesised
    from the registry ``description`` plus the given keys.

    Args:
        standard: ``"sdtm"`` or ``"adam"``.
        algorithm: Algorithm name from the derivation block.
        params: The derivation block minus ``algorithm``.
        target: Variable name, available to templates as ``{target}``.

    Returns:
        str | None: The rendered text, or ``None`` for an unregistered
        algorithm (caller decides the fallback).

    Examples:
        Render the text for a change-from-baseline derivation::

            from fleet.core.spec_registry import render_method_text

            text = render_method_text("adam", "chg", {})
            assert text == "Change from baseline: AVAL - BASE."
    """
    algo = get_algorithm(standard, algorithm)
    if algo is None:
        return None

    given = {k for k, v in params.items() if v is not None}
    if _is_study_day(algorithm, params, target):
        return _STUDY_DAY_TEXT.format(start=params.get("start"), end=params.get("end"))
    values: dict[str, Any] = {"target": target or ""}
    for f in algo.params:
        raw = params.get(f.name)
        if raw is None and f.kwarg in algo.target_default:
            raw = target
        if raw is None:
            raw = f.default
        values[f.name] = None if raw is None else _fmt_value(raw)
    for keys, template in algo.method_text:
        if keys <= given and all(
            values.get(k) is not None for k in _TEMPLATE_KEYS_RE.findall(template)
        ):
            return template.format(**values)

    base = (algo.description or f"Fleet '{algo.name}' derivation.").rstrip(".")
    shown = [
        f"{f.name.replace('_', ' ')}: {_fmt_value(params[f.name])}"
        for f in algo.params
        if params.get(f.name) is not None
    ]
    if shown:
        return f"{base} ({'; '.join(shown)})."
    return f"{base}."


def render_formal_expression(
    standard: str,
    algorithm: str,
    params: Mapping[str, Any],
    *,
    target: str | None = None,
) -> str | None:
    """Machine-readable provenance for ``FormalExpression Context="Python/Fleet"``.

    Renders the faithful Fleet call — the verb, plus the block's keys as
    keyword arguments in signature order — so a reviewer can reproduce the
    derivation.  The method is named after the class that defines it on
    the *standard*'s namespace, so the path is the one runtime lineage
    records in ``VariableNode.method`` for the same derivation.

    Args:
        standard: ``"sdtm"`` or ``"adam"``.
        algorithm: Algorithm name from the derivation block.
        params: The derivation block minus ``algorithm``.
        target: Variable name, rendered as the first positional argument
            for target-taking verbs.

    Returns:
        str | None: e.g. ``fleet...SharedVerbsMixin.assign('AEREL',
        source='AEREL_')``, or ``None`` for an unregistered algorithm.
    """
    algo = get_algorithm(standard, algorithm)
    if algo is None:
        return None
    from fleet.core.lineage import defining_method_path

    # The class from_spec runs on, so the path is the one lineage records.
    if "." in algo.verb:
        fn = _namespace_method(standard, algo.verb)
        dotted = f"{fn.__module__}.{fn.__qualname__}"
    else:
        dotted = defining_method_path(_namespace_class(standard), algo.verb)
    args: list[str] = []
    if target and algo.takes_target:
        args.append(repr(target))
    for f in algo.params:
        value = params.get(f.name)
        if value is not None:
            args.append(f"{f.kwarg}={value!r}")
    return f"{dotted}({', '.join(args)})"


# --------------------------------------------------------------------- #
# Custom dispatchers (non-tabular call shapes)                             #
# --------------------------------------------------------------------- #


def _dispatch_derivation(ns: Any, var: SpecVariableBase) -> Any:
    """``callable:`` resolves a registered Derivation or dotted path; else the expression."""
    if var.callable:
        from fleet.core._resolve_callable import resolve_callable

        fn = resolve_callable(var.callable)
        if hasattr(fn, "kind"):
            if fn.targets and var.target not in fn.targets:
                from fleet.core.exceptions import SpecError

                raise SpecError(
                    f"callable {var.callable!r} writes {fn.targets}, not {var.target}. "
                    f"Name the function {var.target}, or end its expression with "
                    f".alias({var.target!r})."
                )
            return ns.derivation(fn)
        return ns._materialise_then(fn(ns.to_frame()))
    return _default_dispatch(ns, var)


def _dispatch_nsv(ns: Any, var: SpecVariableBase) -> Any:
    """NSV: label/origin/evaluator come from variable-level metadata."""
    return ns.nsv(
        var.target,
        source=var.source,
        value=var.value if var.source is None else None,
        label=var.label or "",
        origin=var.origin or "Derived",
        evaluator=var.evaluator,
    )


def _dispatch_pick(ns: Any, var: SpecVariableBase) -> Any:
    """pick(): multi-target verb; fall back to the variable name.

    A ``source:`` name in an event is a pinned dataset (ADR-0008 rule 3).
    """
    events = [
        {**e, "source": ns._require_pin(e["source"].upper(), "pick")}
        if isinstance(e, dict) and isinstance(e.get("source"), str)
        else e
        for e in var.events or []
    ]
    return ns.pick(
        var.targets or [var.target],
        events=events,
        by=var.by,
        order=var.order,
        mode=var.mode,
    )


# --------------------------------------------------------------------- #
# Define-XML method text shared by both standards                         #
# --------------------------------------------------------------------- #

_ASSIGN_TEXT = (
    ({"value", "ct"}, "Set to the controlled terminology value '{value}' for all records."),
    ({"value"}, "Set to '{value}' for all records."),
    ({"source", "ct"}, "Value of {source} mapped to controlled terminology."),
    (set(), "Direct copy of {source}."),
)
_DATE_TEXT = ((set(), "ISO 8601 date/time derived from {source} (imputation: {impute})."),)
_MERGE_TEXT = ((set(), "Records merged from {dataset} (join key: {on})."),)
_DURATION_TEXT = ((set(), "Duration from {start} to {end}, in {unit}."),)
#: ``duration`` on a ``*DY`` target in days is a study day (no day 0), not a span.
_STUDY_DAY_TEXT = "Study day of {end} relative to {start}."
_DERIVATION_TEXT = (({"expression"}, "Derived as: {expression}."),)
_CALLABLE_FIELD = (("callable", str | None, None),)


# --------------------------------------------------------------------- #
# SDTM verbs                                                              #
# --------------------------------------------------------------------- #

spec_verb(
    "assign",
    standard="sdtm",
    exclusive=("source", "value"),
    target_default=("source",),
    identity="source",
    description="Copy a column or set a constant, with optional controlled terminology.",
    method_text=_ASSIGN_TEXT,
)

spec_verb(
    "date",
    standard="sdtm",
    exclusive=("source", "value"),
    target_default=("source",),
    identity="source",
    description="Parse, convert, impute, and flag a date/datetime column (ISO 8601).",
    method_text=_DATE_TEXT,
)

spec_verb(
    "condition_add",
    standard="sdtm",
    description="Set a value where a condition holds (null otherwise).",
    method_text=((set(), "Set to '{then_value}' where {condition}; null otherwise."),),
)

spec_verb("case_when", standard="sdtm", description="Multi-branch conditional derivation.")

spec_verb(
    "ae_aerel",
    standard="sdtm",
    description="Map raw relationship values onto AEREL controlled terms.",
)

spec_verb(
    "merge",
    standard="sdtm",
    required=("dataset", "on"),
    takes_target=False,
    exclude=("validate",),
    description="Join a pinned reference dataset into the pipeline.",
    method_text=_MERGE_TEXT,
)

spec_verb(
    "group_by",
    standard="sdtm",
    takes_target=False,
    description="Aggregate the frame by group columns.",
)

spec_verb(
    "notsubmitted",
    standard="sdtm",
    overwrite_guard=False,
    description="Null out a variable that is not submitted.",
)

spec_verb(
    "multiple_responses",
    standard="sdtm",
    target_default=("source",),
    identity="source",
    description="Explode a delimited multi-response field into rows.",
)

spec_verb("seq", standard="sdtm", description="Assign the --SEQ sequence number within each group.")

spec_verb(
    "nsv",
    standard="sdtm",
    exclude=("label", "origin", "evaluator"),
    identity="source",
    dispatch=_dispatch_nsv,
    description="Declare a Non-Standard Variable (SUPPQUAL qualifier).",
)

spec_verb(
    "duration",
    standard="sdtm",
    description="Compute the duration between two dates.",
    method_text=_DURATION_TEXT,
)

spec_verb(
    "derivation",
    standard="sdtm",
    one_of=("expression", "callable"),
    extra=_CALLABLE_FIELD,
    dispatch=_dispatch_derivation,
    description=(
        "Derive a column from a Polars expression string, or run a registered or "
        "importable study derivation (callable)."
    ),
    method_text=_DERIVATION_TEXT,
)


# --------------------------------------------------------------------- #
# ADaM verbs                                                              #
# --------------------------------------------------------------------- #

spec_verb(
    "assign",
    standard="adam",
    exclusive=("source", "value"),
    target_default=("source",),
    identity="source",
    description="Copy a column or set a constant, with optional controlled terminology.",
    method_text=_ASSIGN_TEXT,
)

spec_verb(
    "derivation",
    standard="adam",
    one_of=("expression", "callable"),
    extra=_CALLABLE_FIELD,
    dispatch=_dispatch_derivation,
    description=(
        "Derive a column from a Polars expression string, or run a registered or "
        "importable study derivation (callable)."
    ),
    method_text=_DERIVATION_TEXT,
)

spec_verb(
    "recode",
    standard="adam",
    target_default=("source",),
    identity="source",
    description="Map source values onto new values via a lookup dict.",
    method_text=((set(), "Values of {source} recoded as: {recode_map}."),),
)

spec_verb("case_when", standard="adam", description="Multi-branch conditional derivation.")

spec_verb(
    "merge",
    standard="adam",
    required=("dataset", "on"),
    takes_target=False,
    exclude=("validate",),
    description="SQL-style join against a pinned dataset.",
    method_text=_MERGE_TEXT,
)

spec_verb(
    "whereclauses",
    standard="adam",
    takes_target=False,
    description="Filter rows by a boolean expression.",
)

spec_verb(
    "duration",
    standard="adam",
    description="Compute the duration between two dates (a study day is end minus start).",
    method_text=_DURATION_TEXT,
)

spec_verb(
    "baseline",
    standard="adam",
    description="Propagate the baseline value to all records in a group.",
    method_text=((set(), "Value of {aval} at the baseline record ({baseline_flag} = 'Y')."),),
)

spec_verb(
    "chg",
    standard="adam",
    description="Change from baseline (AVAL - BASE).",
    method_text=((set(), "Change from baseline: {aval} - {base}."),),
)

spec_verb(
    "pchg",
    standard="adam",
    description="Percent change from baseline.",
    method_text=((set(), "Percent change from baseline: 100 * ({aval} - {base}) / {base}."),),
)

spec_verb("flag", standard="adam", description="Derive a Y/null flag from criteria.")

spec_verb(
    "bmi",
    standard="adam",
    description="Body Mass Index from weight and height.",
    method_text=((set(), "Body Mass Index (kg/m2) from {weight} and {height}."),),
)

spec_verb(
    "nrind",
    standard="adam",
    description="Reference-range indicator (LOW/NORMAL/HIGH).",
    method_text=((set(), "Reference range indicator: {value} compared with {low} and {high}."),),
)

spec_verb(
    "on_treatment",
    standard="adam",
    description="On-treatment flag from analysis vs treatment dates.",
    method_text=((set(), "Set to 'Y' when {adt} falls between {trtsdt} and {trtedt}."),),
)

spec_verb(
    "shift",
    standard="adam",
    description="Shift-table category ('NORMAL to HIGH').",
    method_text=((set(), "Shift from {baseline_cat} to {post_cat}."),),
)

spec_verb("seq", standard="adam", description="Assign the ASEQ sequence number within each group.")

spec_verb(
    "bsa",
    standard="adam",
    description="Body Surface Area.",
    method_text=((set(), "Body Surface Area ({method} formula) from {weight} and {height}."),),
)

spec_verb(
    "map",
    standard="adam",
    description="Mean Arterial Pressure.",
    method_text=((set(), "Mean Arterial Pressure from {systolic} and {diastolic}."),),
)

spec_verb(
    "qtc",
    standard="adam",
    description="Corrected QT interval.",
    method_text=(
        (
            set(),
            "QT interval corrected using the {method} formula, from {qt} (ms) and {rr} ({rr_unit}).",
        ),
    ),
)

spec_verb("atoxgr", standard="adam", description="Toxicity grade via criteria-file grading.")

spec_verb(
    "combine_grades",
    standard="adam",
    description="Combine directional toxicity grades into one column.",
)

spec_verb(
    "date",
    standard="adam",
    exclusive=("source", "value"),
    target_default=("source",),
    identity="source",
    description="Parse, convert, impute, and flag an analysis date column.",
    method_text=_DATE_TEXT,
)

spec_verb(
    "pick",
    standard="adam",
    extra=(("targets", list[str] | None, None),),
    dispatch=_dispatch_pick,
    description="Select the first/last matching event per group.",
)

spec_verb(
    "first_date",
    standard="adam",
    description="Earliest event date per subject from a pinned dataset.",
    method_text=((set(), "Earliest {date_col} per subject from {from_dataset}."),),
)

spec_verb(
    "last_date",
    standard="adam",
    description="Latest event date per subject from a pinned dataset.",
    method_text=((set(), "Latest {date_col} per subject from {from_dataset}."),),
)

spec_verb(
    "count_events",
    standard="adam",
    description="Count matching records per subject from a pinned dataset.",
    method_text=((set(), "Count of qualifying records per subject from {from_dataset}."),),
)


def _trtemfl_text() -> tuple[tuple[set[str], str], ...]:
    """Method text shapes of ``treatment_emergent``, most specific first."""
    shapes: list[tuple[set[str], str]] = []
    for offset in (True, False):
        for window in (True, False):
            for ended in (True, False):
                ref = "{trtsdt} + {offset_days} days" if offset else "{trtsdt}"
                text = "Set to 'Y' when {start_date} is on or after " + ref
                if window:
                    text += " and on or before {trtedt} + {end_window} days"
                text += ", or when {start_date} is missing; null when {trtsdt} is missing"
                text += " or {end_date} is before {trtsdt}." if ended else "."
                keys = {"offset_days"} if offset else set()
                shapes.append((keys | ({"end_window"} if window else set()), text))
    return tuple(shapes)


spec_verb(
    "occds.treatment_emergent",
    standard="adam",
    description="Treatment-emergent flag, as admiral derive_var_trtemfl.",
    method_text=_trtemfl_text(),
)


# --------------------------------------------------------------------- #
# Inline-only verbs (machine-checked allowlist)                           #
# --------------------------------------------------------------------- #

#: Namespace verbs that deliberately have **no** spec form, with the
#: reason.  The parity test asserts every public verb is either registered
#: above or listed here — nothing falls through the cracks silently.
SPEC_UNSUPPORTED: dict[str, set[str]] = {
    "sdtm": {
        "study_day",  # pin-based reference join; no spec form yet (duration gives a day 0)
        "export_supp",  # terminal exporter; fleet run calls it for qualifier variables
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
        "flag",  # inline-only on SDTM (ADaM has the spec verb)
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
        "study_day",  # pin-based reference join; no spec form yet (duration gives a day 0)
        "source",  # variadic carry-through sugar; to_spec_yaml writes it as assign
        "join_adsl",  # variadic pin sugar; a define.yaml uses merge
        "merge_adsl",  # pin sugar; a define.yaml uses merge
        "transform",  # spec equivalent is derivation with callable:
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
        list[dict]: One row per registered verb with keys ``standard``,
            ``algorithm``, ``verb``, ``params`` (YAML key list) and
            ``required`` (YAML key list).

    Examples:
        List which ADaM verbs are spec-executable::

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
                    "verb": algo.verb,
                    "params": [f.name for f in algo.params],
                    "required": [f.name for f in algo.params if f.required],
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
            maps model names to their per-verb schemas (to be merged
            into the document's top-level ``$defs``).

    The per-verb schemas are generated from the registry models via
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

    # A bare `callable:` block without `algorithm:` is accepted by
    # from_spec (`algorithm: derivation` is injected automatically).
    branches.append(
        {
            "type": "object",
            "description": (
                "Shorthand callable block — `algorithm: derivation` is "
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
            "engine. The algorithm is the verb; the keys are its keyword "
            "arguments. Validated per verb: unknown keys are rejected. "
            "Generated from fleet.core.spec_registry — do not edit by hand; "
            "run `python -m fleet.define_xml.schema_builder` to regenerate."
        ),
        "anyOf": branches,
    }
    return derivation_def, dict(sorted(model_defs.items()))
