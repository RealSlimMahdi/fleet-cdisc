"""The public introspection surface for protocol adapters (ADR-0001).

Tooling that needs to *describe* Fleet — a language server offering
``algorithm:`` completions, an editor rendering hover docs, a linter
checking a ``define.yaml`` — consumes this module and nothing else.
Analysts writing derivations want :mod:`fleet.sdtm` and
:mod:`fleet.adam` instead.

``__all__`` is the contract, and it is **additive-only within a major
version**: names and return fields may be added, but nothing is removed
or renamed except on a major.  A client therefore declares a *minimum*
Fleet version (read from ``serverInfo.version`` in the language-server
handshake) and never a maximum.

The returned dataclasses are deliberately narrow copies rather than
Fleet's own registry objects: a :class:`~fleet.core.spec_registry.SpecAlgorithm`
carries a ``dispatch`` callable and an overwrite guard, which are
execution internals that must stay free to change.

Examples:
    Offer every ADaM algorithm as a completion item::

        from fleet import introspect

        items = [
            {"label": algo.name, "documentation": algo.description}
            for algo in introspect.algorithms("adam")
        ]

    Explain one algorithm on hover::

        from fleet import introspect

        algo = introspect.get_algorithm("sdtm", "assign")
        doc = introspect.algorithm_doc("assign")
        markdown = f"**{algo.name}** — {algo.description}\\n\\n{doc.summary}"
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

__all__ = [
    "AlgorithmDoc",
    "AlgorithmInfo",
    "DerivationProblem",
    "ParamInfo",
    "Standard",
    "algorithm_doc",
    "algorithms",
    "check_derivation",
    "define_schema",
    "get_algorithm",
    "load_spec_yaml",
    "renamed_algorithm",
    "standard_of",
    "suggest_algorithm",
]

#: A CDISC standard Fleet can execute spec algorithms for.
Standard = Literal["sdtm", "adam"]

_STANDARDS: tuple[str, ...] = ("sdtm", "adam")


@dataclass(frozen=True, slots=True)
class ParamInfo:
    """One parameter of a spec algorithm.

    Args:
        name: Spec field name (the YAML key inside the ``derivation`` block).
        required: Whether the field must be present in the spec.
        description: Short human-readable description, possibly empty.
    """

    name: str
    required: bool
    description: str


@dataclass(frozen=True, slots=True)
class AlgorithmInfo:
    """A spec-executable algorithm as tooling sees it.

    Args:
        name: Canonical algorithm name (the ``algorithm:`` value).
        standard: The standard the algorithm belongs to.
        description: One-line description, possibly empty.
        params: Declared parameters, in spec order.
    """

    name: str
    standard: Standard
    description: str
    params: tuple[ParamInfo, ...]


@dataclass(frozen=True, slots=True)
class AlgorithmDoc:
    """The docstring of the verb an algorithm dispatches to.

    Args:
        summary: First sentence of the verb's docstring.
        verb_path: Dotted ``module.Class.method`` path of that verb.
    """

    summary: str
    verb_path: str


@dataclass(frozen=True, slots=True)
class DerivationProblem:
    """One reason ``from_spec()`` refuses a ``derivation:`` block.

    Args:
        key: The block key the problem is about, or ``None`` when it is
            about the block as a whole (two keys that exclude each other).
        message: The text ``from_spec()`` gives, prefixed with the key.
    """

    key: str | None
    message: str


def _check_standard(standard: str) -> None:
    """Reject an unknown standard identically for every call in the surface."""
    if standard not in _STANDARDS:
        valid = ", ".join(repr(s) for s in _STANDARDS)
        raise ValueError(f"Unknown standard {standard!r}. Valid standards are {valid}.")


def algorithms(standard: Standard) -> tuple[AlgorithmInfo, ...]:
    """Return every algorithm registered for *standard*.

    Not cached: ``spec_algorithm()`` is public, so an algorithm registered
    after the first call must still show up in completions.

    Args:
        standard: ``"sdtm"`` or ``"adam"``.

    Returns:
        tuple[AlgorithmInfo, ...]: One entry per verb.

    Raises:
        ValueError: If *standard* is not a known CDISC standard.

    Examples:
        Build the ``algorithm:`` completion list for a define.yaml::

            from fleet import introspect

            labels = [algo.name for algo in introspect.algorithms("sdtm")]
    """
    _check_standard(standard)

    from fleet.core import spec_registry

    return tuple(_to_info(algo) for algo in spec_registry.algorithms(standard))


def get_algorithm(standard: Standard, name: str) -> AlgorithmInfo | None:
    """Return the algorithm registered under *name*, or ``None``.

    Args:
        standard: ``"sdtm"`` or ``"adam"``.
        name: Algorithm name or accepted alias.

    Returns:
        AlgorithmInfo | None: The algorithm, or ``None`` when *name* is
            not registered for *standard*.

    Raises:
        ValueError: If *standard* is not a known CDISC standard.

    Examples:
        Offer the parameter keys of the algorithm under the cursor::

            from fleet import introspect

            algo = introspect.get_algorithm("adam", "chg")
            keys = [param.name for param in algo.params] if algo else []
    """
    _check_standard(standard)

    from fleet.core import spec_registry

    algo = spec_registry.get_algorithm(standard, name)
    return None if algo is None else _to_info(algo)


def suggest_algorithm(standard: Standard, name: str) -> str | None:
    """Return the registered algorithm closest to *name*, if any.

    Args:
        standard: ``"sdtm"`` or ``"adam"``.
        name: The unrecognised spelling to match against.

    Returns:
        str | None: The closest algorithm name, or ``None`` when nothing
            is close enough to suggest.

    Raises:
        ValueError: If *standard* is not a known CDISC standard.

    Examples:
        Turn an unknown algorithm into a did-you-mean diagnostic::

            from fleet import introspect

            suggestion = introspect.suggest_algorithm("sdtm", "asign_ct")
            message = f"Unknown algorithm. Did you mean '{suggestion}'?"
    """
    _check_standard(standard)

    from fleet.core import spec_registry

    return spec_registry.suggest_algorithm(standard, name)


def renamed_algorithm(name: str) -> str | None:
    """Return the current name of a pre-ADR-0008 algorithm name, or ``None``.

    ``fleet migrate --spec`` rewrites a file that still uses the old
    names, so a tool can point the user to it.

    Args:
        name: The algorithm name as written in the file.

    Returns:
        str | None: The current name (``"assign"`` for ``"hardcode_no_ct"``),
            or ``None`` when *name* is not an old name.

    Examples:
        Turn an old name into a migrate hint::

            from fleet import introspect

            new = introspect.renamed_algorithm("hardcode_no_ct")
            message = f"Old name of '{new}'. Run fleet migrate --spec." if new else ""
    """
    from fleet.tools.migrate_spec import ALGORITHM_RENAMES

    return ALGORITHM_RENAMES.get(name)


def check_derivation(
    standard: Standard,
    block: dict[str, Any],
    *,
    target: str = "VAR",
    codelist: str | None = None,
) -> tuple[DerivationProblem, ...]:
    """Return why ``from_spec()`` would refuse one ``derivation:`` block.

    The block is checked by the same per-algorithm model ``from_spec()``
    uses, after the variable's ``codelist:`` fills ``ct`` (ADR-0008).  An
    unknown algorithm gives one problem; use :func:`suggest_algorithm` for
    a better message.

    Args:
        standard: ``"sdtm"`` or ``"adam"``.
        block: The ``derivation:`` block, with its ``algorithm`` key.
        target: The variable the block derives.
        codelist: The ``codelist:`` of the variable, if any.

    Returns:
        tuple[DerivationProblem, ...]: Empty when the block is valid.

    Raises:
        ValueError: If *standard* is not a known CDISC standard.

    Examples:
        Put a red line on a misspelled key::

            from fleet import introspect

            problems = introspect.check_derivation(
                "sdtm", {"algorithm": "assign", "sorce": "sex"}
            )
            assert problems[0].key == "sorce"
    """
    _check_standard(standard)

    from pydantic import ValidationError

    from fleet.core import spec_registry

    try:
        data = spec_registry.with_codelist(standard, block, codelist)
    except ValueError as exc:
        return (DerivationProblem(None, str(exc)),)
    try:
        spec_registry.parse_variable_spec(standard, {"target": target, **data})
    except ValidationError as exc:
        problems = []
        for error in exc.errors():
            location = error["loc"]
            message = str(error["msg"]).removeprefix("Value error, ")
            key = str(location[1]) if len(location) > 1 else None
            problems.append(DerivationProblem(key, f"{key}: {message}" if key else message))
        return tuple(problems)
    return ()


def standard_of(study_standard: object, path: str = "") -> Standard | None:
    """Return the standard a spec targets, from its ``study.standard`` or its path.

    The spec's own ``study.standard`` wins; without it, the nearest folder
    named ``sdtm`` or ``adam`` above the file decides.  ``fleet define-xml``
    and ``fleet spec-to-code`` decide the same way.

    Args:
        study_standard: The ``study.standard`` value, or ``None``.
        path: The spec file path.

    Returns:
        Standard | None: ``"sdtm"``, ``"adam"``, or ``None`` when neither
            source says.

    Examples:
        Offer only the algorithms of the file's standard::

            from fleet import introspect

            std = introspect.standard_of(None, "/study/metadata/adam/define.yaml")
            names = [a.name for a in introspect.algorithms(std)] if std else []
    """
    from fleet.core.define_spec import standard_of as _standard_of

    return _standard_of(study_standard, path)  # type: ignore[return-value]


def algorithm_doc(name: str) -> AlgorithmDoc | None:
    """Return the docstring summary of the verb *name* dispatches to.

    Kept separate from :class:`AlgorithmInfo` on purpose: resolving a
    docstring imports and scans the verb-bearing namespace modules, which
    is too expensive for the per-keystroke completion path.

    Args:
        name: Canonical algorithm name.

    Returns:
        AlgorithmDoc | None: Summary and dotted verb path, or ``None``
            when the algorithm has no resolvable verb.

    Examples:
        Add the verb's own words to a hover card::

            from fleet import introspect

            doc = introspect.algorithm_doc("baseline")
            markdown = f"{doc.summary}\\n\\nVerb: `{doc.verb_path}`" if doc else ""
    """
    from fleet.core.algorithm_resolver import resolve_algorithm_docstring

    summary, verb_path = resolve_algorithm_docstring(name)
    if summary is None or verb_path is None:
        return None
    return AlgorithmDoc(summary=summary, verb_path=verb_path)


@lru_cache(maxsize=1)
def define_schema() -> dict[str, Any]:
    """Return the generated JSON schema for ``define.yaml`` specs.

    Returns:
        dict[str, Any]: The parsed schema, cached across calls.

    Examples:
        Validate a spec document against the shipped schema::

            import jsonschema

            from fleet import introspect

            validator = jsonschema.Draft202012Validator(introspect.define_schema())
            problems = list(validator.iter_errors({"study": {}}))
    """
    import json

    from fleet.define_xml.schema_builder import SCHEMA_PATH

    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _to_info(algo: Any) -> AlgorithmInfo:
    """Copy a registry ``SpecAlgorithm`` into its public, frozen counterpart."""
    return AlgorithmInfo(
        name=algo.name,
        standard=algo.standard,
        description=algo.description,
        params=tuple(
            ParamInfo(name=p.name, required=p.required, description=p.description)
            for p in algo.params
        ),
    )


def load_spec_yaml(text: str) -> Any:
    """Parse define.yaml text the way ``from_spec`` does.

    The spec dialect reads booleans the YAML 1.2 way (``true`` and ``false``
    only), so the ``on:`` join key of ``merge`` stays a string.  A tool that
    parses a define.yaml itself must use this loader, or it sees the key
    ``True`` where Fleet sees ``on``.

    Args:
        text: The YAML document.

    Returns:
        The parsed document, or ``None`` for an empty one.

    Raises:
        yaml.YAMLError: On invalid YAML.

    Examples:
        Read the blocks of a file the editor holds::

            from fleet import introspect

            data = introspect.load_spec_yaml(editor_text) or {}
    """
    from fleet.core.define_spec import load_spec_yaml as _load

    return _load(text)
