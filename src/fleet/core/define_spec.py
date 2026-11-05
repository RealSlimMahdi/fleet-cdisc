"""Validated envelope model for define.yaml / simplified spec files.

Fleet already validates the *derivation* half of a spec through the
algorithm registry (:mod:`fleet.core.spec_registry`).  This module covers
the other half — the envelope around it: top-level keys, dataset entries,
and variable metadata.  Without it a typo like ``datsets:`` parses fine,
matches nothing, and ``from_spec()`` silently returns the input frame.

Every reader that *executes* a spec (``from_spec``, ``build_dag``, NSV
metadata resolution) goes through :func:`load_define_spec`, so the format
is interpreted in exactly one place.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from fleet.core.exceptions import SpecError

#: Spec-format version this Fleet build writes (``fleet_spec_version``).
#: Version 2 is the verb vocabulary of ADR-0008.
SUPPORTED_SPEC_VERSION = 2


def check_spec_version(version: Any, *, source: str) -> None:
    """Raise ``SpecError`` when a spec declares another dialect version.

    Version 1 is the pre-ADR-0008 vocabulary; the message names
    ``fleet migrate --spec``, which rewrites it.
    """
    if version is None or version == SUPPORTED_SPEC_VERSION:
        return
    hint = (
        " Rewrite the file with `fleet migrate --spec <define.yaml> --write`."
        if version == 1
        else ""
    )
    raise SpecError(
        f"{source}: unsupported fleet_spec_version {version!r}. "
        f"This Fleet version supports fleet_spec_version {SUPPORTED_SPEC_VERSION}.{hint}"
    )


class CTBlock(BaseModel):
    """Top-level ``ct:`` block — opts a spec into CT validation."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    #: ``validate:`` in YAML — renamed because ``validate`` is taken on BaseModel.
    enabled: bool = Field(default=False, alias="validate")
    file: str | None = None


class VariableEntry(BaseModel):
    """One entry in a dataset's ``variables:`` list.

    Every key of the define-spec JSON schema ``$defs.variable`` is declared,
    and an unknown key is refused, so a misspelled ``derivaton:`` cannot
    drop a derivation with no message.  The JSON schema type-checks the
    metadata keys in the define_xml path.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    type: str | None = None
    label: str | None = None
    length: Any = None
    significant_digits: Any = None
    mandatory: Any = None
    core: Any = None
    origin: str | None = None
    origin_source: str | None = None
    predecessor: str | None = None
    codelist: Any = None
    role: str | None = None
    sdtm_role: str | None = None
    evaluator: str | None = None
    comment: Any = None
    crf_pages: Any = None
    derivation: dict[str, Any] | None = None


def _unknown_variable_keys(dataset: str, variables: Any) -> None:
    """Raise ``ValueError`` that names the first unknown key of a variable entry."""
    if not isinstance(variables, list):
        return
    known = set(VariableEntry.model_fields)
    for var in variables:
        if not isinstance(var, dict):
            continue
        for key in var:
            if key in known:
                continue
            hint = difflib.get_close_matches(str(key), sorted(known), n=1)
            did_you_mean = f" (did you mean {hint[0]!r}?)" if hint else ""
            raise ValueError(
                f"{dataset}.{var.get('name', '?')}: unknown key {key!r}{did_you_mean}. "
                f"A variable takes only: {', '.join(VariableEntry.model_fields)}."
            )


#: A SAS dataset name (``DM``, ``ADSL``).  Dataset names become file names
#: and Snakefile lines, so the pattern also keeps ``../`` and ``;`` out.
DATASET_NAME = r"^[A-Z][A-Z0-9]{1,7}$"

#: The logical name of a ``dataset_input`` (``dm_raw``, ``DM``).
INPUT_NAME = r"^[A-Za-z][A-Za-z0-9_]*$"

#: SDTMIG trial design datasets: reference data, not records per subject.
TRIAL_DESIGN_DATASETS = frozenset({"TA", "TE", "TV", "TI", "TS", "TD", "TM"})


def default_repeating(name: str) -> bool:
    """Return the Define-XML ``Repeating`` default of a dataset with no ``repeating:`` key.

    DM, ADSL and the trial design datasets have no more than one record
    per subject (or no subject at all): ``No``.  Every other dataset: ``Yes``.

    Args:
        name: The dataset name (``DM``, ``ADAE``).

    Returns:
        bool: True when the dataset repeats per subject.

    References:
        CDISC Define-XML 2.1 example ``defineV21-SDTM.xml``; ADR-0041.

    Examples:
        The defaults of DM and AE::

            from fleet.core.define_spec import default_repeating

            assert default_repeating("DM") is False
            assert default_repeating("AE") is True
    """
    return name not in TRIAL_DESIGN_DATASETS | {"DM", "ADSL"}


def default_is_reference_data(name: str, dataset_class: str | None) -> bool:
    """Return the Define-XML ``IsReferenceData`` default of a dataset with no key.

    A trial design dataset (TA, TE, TV, TI, TS, TD, TM, or class
    ``TRIAL DESIGN``) is reference data: ``Yes``.  Every other dataset: ``No``.

    Args:
        name: The dataset name (``TS``).
        dataset_class: The ``class:`` of the dataset, if any.

    Returns:
        bool: True when the dataset is reference data.

    References:
        CDISC Define-XML 2.1 example ``defineV21-SDTM.xml``; ADR-0041.

    Examples:
        TS is reference data, AE is not::

            from fleet.core.define_spec import default_is_reference_data

            assert default_is_reference_data("TS", None) is True
            assert default_is_reference_data("AE", "EVENTS") is False
    """
    return name in TRIAL_DESIGN_DATASETS or (dataset_class or "").upper() == "TRIAL DESIGN"


class DatasetEntry(BaseModel):
    """One entry in the top-level ``datasets:`` list."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = Field(pattern=DATASET_NAME)
    variables: list[VariableEntry] = Field(default_factory=list)
    inputs: list[dict[str, Any]] = Field(default_factory=list)
    output: str | None = None
    output_format: str | None = None
    label: str | None = None
    structure: str | None = None
    repeating: Any = None
    is_reference_data: bool | None = None
    keys: Any = None
    value_level: Any = None
    class_: Any = Field(default=None, alias="class")
    subclass: str | None = None
    domain: str | None = None
    #: Row-removing steps in pipeline order, each anchored ``after:`` a variable (ADR-0034).
    row_steps: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _variable_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            _unknown_variable_keys(str(data.get("name", "?")), data.get("variables"))
        return data

    @model_validator(mode="after")
    def _input_names(self) -> DatasetEntry:
        for entry in self.inputs:
            name = entry.get("name")
            if not isinstance(name, str) or not re.match(INPUT_NAME, name):
                raise ValueError(
                    f"dataset {self.name}: input name {name!r} must match {INPUT_NAME} "
                    "(a logical name such as dm_raw or DM, not a path)"
                )
        return self


class DefineSpec(BaseModel):
    """A parsed spec file — either format ``from_spec()`` accepts.

    ``datasets:`` is the full define.yaml shape (one entry per domain,
    each variable carrying a ``derivation:`` block).  ``variables:`` with
    ``domain:``/``dataset:`` is the simplified single-dataset shape whose
    entries hold inline algorithm fields.
    """

    model_config = ConfigDict(extra="forbid")

    study: dict[str, Any] = Field(default_factory=dict)
    codelists: list[dict[str, Any]] = Field(default_factory=list)
    datasets: list[DatasetEntry] | None = None
    fleet_spec_version: int | None = None
    derivations_module: str | None = None
    ct: CTBlock = Field(default_factory=CTBlock)
    output_format: str = "parquet"

    # Simplified single-dataset format.
    domain: str | None = None
    dataset: str | None = None
    variables: list[dict[str, Any]] | None = None

    @model_validator(mode="after")
    def _require_a_format(self) -> DefineSpec:
        if self.datasets is None and self.variables is None:
            raise ValueError(
                "spec declares neither 'datasets:' (define.yaml format) nor "
                "'variables:' (simplified format)"
            )
        return self

    @model_validator(mode="after")
    def _unique_dataset_names(self) -> DefineSpec:
        seen: dict[str, int] = {}
        for nr, entry in enumerate(self.datasets or [], start=1):
            first = seen.setdefault(entry.name.upper(), nr)
            if first != nr:
                raise ValueError(
                    f"dataset {entry.name} is declared twice (datasets {first} and {nr}). "
                    "Keep one entry per dataset."
                )
        return self

    def select(self, dataset: str | None) -> DatasetEntry:
        """Return the requested dataset entry from a define.yaml spec.

        Args:
            dataset: Dataset name to select; may be ``None`` when the spec
                declares exactly one dataset.

        Returns:
            DatasetEntry: The matching dataset.

        Raises:
            DerivationError: When *dataset* is unknown, or omitted for a
                multi-dataset spec.
        """
        from fleet.core.exceptions import DerivationError

        datasets = self.datasets or []
        names = [d.name for d in datasets]
        if dataset is None:
            if len(datasets) != 1:
                raise DerivationError(
                    f"define.yaml contains {len(datasets)} datasets {names}. "
                    "Pass dataset= to select one."
                )
            return datasets[0]
        for entry in datasets:
            if entry.name.upper() == dataset.upper():
                return entry
        raise DerivationError(f"Dataset '{dataset}' not found in define.yaml. Available: {names}")


class SpecYamlLoader(yaml.SafeLoader):
    """``yaml.SafeLoader`` that keeps define values as written.

    PyYAML follows YAML 1.1, where a bare ``on``, ``off``, ``yes`` or ``no``
    is a boolean.  A define.yaml names the join key of ``merge`` with
    ``on:``, so that key must stay a string (#87).  YAML 1.1 also reads
    ``010`` as octal 8, ``12:30`` as 750 and ``2024-01-15`` as a date, so
    only plain decimal numbers are resolved: ``010``, ``12:30`` and
    ``2024-01-15`` stay text.  A duplicate key is refused with its line,
    and so is a value its explicit tag cannot read (``!!float abc``) and an
    alias inside its own anchor (``a: &x {b: *x}``).
    """

    def compose_node(self, parent: Any, index: Any) -> Any:
        open_anchors: set[str] = self.__dict__.setdefault("_open_anchors", set())
        event = self.peek_event()
        if isinstance(event, yaml.AliasEvent) and event.anchor in open_anchors:
            raise yaml.composer.ComposerError(
                None,
                None,
                f"alias *{event.anchor} refers to itself: the file nests too deep "
                "or expands too much",
                event.start_mark,
            )
        anchor = None if isinstance(event, yaml.AliasEvent) else getattr(event, "anchor", None)
        if anchor:
            open_anchors.add(anchor)
        try:
            return super().compose_node(parent, index)
        finally:
            if anchor:
                open_anchors.discard(anchor)

    def construct_object(self, node: yaml.Node, deep: bool = False) -> Any:
        try:
            return super().construct_object(node, deep=deep)
        except (ValueError, TypeError) as err:
            raise yaml.constructor.ConstructorError(
                None, None, f"{node.tag}: {err}", node.start_mark
            ) from err

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=True)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key {key!r}",
                    key_node.start_mark,
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


SpecYamlLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)
# Replace the YAML 1.1 resolver for every first character it was registered on.
for _first in list("yYnNoOtTfF"):
    SpecYamlLoader.yaml_implicit_resolvers[_first] = [
        (tag, regexp)
        for tag, regexp in SpecYamlLoader.yaml_implicit_resolvers.get(_first, [])
        if tag != "tag:yaml.org,2002:bool"
        or regexp.pattern == r"^(?:true|True|TRUE|false|False|FALSE)$"
    ]
# Drop the YAML 1.1 int (octal, sexagesimal), float (sexagesimal) and date resolvers.
_YAML11_NUMBER_TAGS = {
    "tag:yaml.org,2002:int",
    "tag:yaml.org,2002:float",
    "tag:yaml.org,2002:timestamp",
}
for _first, _resolvers in list(SpecYamlLoader.yaml_implicit_resolvers.items()):
    SpecYamlLoader.yaml_implicit_resolvers[_first] = [
        (tag, regexp) for tag, regexp in _resolvers if tag not in _YAML11_NUMBER_TAGS
    ]
SpecYamlLoader.add_implicit_resolver(
    "tag:yaml.org,2002:int",
    re.compile(r"^[-+]?(?:0|[1-9][0-9]*)$"),
    list("-+0123456789"),
)
SpecYamlLoader.add_implicit_resolver(
    "tag:yaml.org,2002:float",
    re.compile(
        r"^(?:[-+]?(?:0|[1-9][0-9]*)?\.[0-9]+(?:[eE][-+]?[0-9]+)?"
        r"|[-+]?(?:0|[1-9][0-9]*)\.(?:[eE][-+]?[0-9]+)?"
        r"|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$"
    ),
    list("-+0123456789."),
)


#: The largest define.yaml in the repository holds about 2,000 YAML nodes at
#: depth 8.  These limits leave room for a study 500 times larger and still
#: stop a recursive anchor or an alias bomb before it exhausts the process.
_MAX_EXPANDED_NODES = 1_000_000
_MAX_DEPTH = 100


def _check_expansion(root: yaml.Node) -> None:
    """Refuse a document whose aliases expand too much or that nests too deep.

    The walk follows aliases as the constructor does, so a recursive anchor
    expands forever and meets the node limit.  It uses an explicit stack, so
    it cannot itself exhaust the Python stack.
    """
    count, stack = 0, [(root, 1)]
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > _MAX_EXPANDED_NODES or depth > _MAX_DEPTH:
            raise yaml.YAMLError(
                "the file nests too deep or expands too much "
                f"(limits: depth {_MAX_DEPTH}, {_MAX_EXPANDED_NODES:,} nodes after aliases)"
            )
        if isinstance(node, yaml.MappingNode):
            stack.extend((value, depth + 1) for _, value in node.value)
        elif isinstance(node, yaml.SequenceNode):
            stack.extend((item, depth + 1) for item in node.value)


def load_spec_yaml(text: str) -> Any:
    """Parse define.yaml text with :class:`SpecYamlLoader`.

    A recursive anchor, an alias bomb or a very deep nesting is refused
    with a ``yaml.YAMLError``, so every reader (``from_spec``, ``fleet
    check``, ``fleet define-xml``, the language server) stays alive.

    Args:
        text: The YAML document.

    Returns:
        The parsed document (a mapping for a define.yaml), or ``None`` for
        an empty document.

    Raises:
        yaml.YAMLError: On invalid YAML, or a document that nests too deep
            or expands too much.

    Examples:
        The ``on:`` key of a merge stays a string::

            from fleet.core.define_spec import load_spec_yaml

            block = load_spec_yaml("algorithm: merge\non: USUBJID\n")
            assert block == {"algorithm": "merge", "on": "USUBJID"}
    """
    loader = SpecYamlLoader(text)
    try:
        try:
            root = loader.get_single_node()
        except RecursionError:
            raise yaml.YAMLError("the file nests too deep or expands too much") from None
        if root is None:
            return None
        _check_expansion(root)
        return loader.construct_document(root)
    finally:
        loader.dispose()


def standard_of(study_standard: object, path: str | Path = "") -> str | None:
    """The registry standard a spec targets: ``"sdtm"``, ``"adam"`` or ``None``.

    The spec's own ``study.standard`` wins (SDTMIG and SENDIG give
    ``"sdtm"``, ADaMIG gives ``"adam"``).  Without it, the nearest folder
    named ``sdtm`` or ``adam`` above the file decides, so
    ``/work/sdtm/S01/metadata/adam/define.yaml`` is ADaM.  The path is split
    on both separators, so a Windows path reads the same on any system.

    Args:
        study_standard: The ``study.standard`` value, or ``None``.
        path: The spec file path, used when the spec does not say.

    Returns:
        str | None: The standard, or ``None`` when neither source says.

    Examples:
        Pick the namespace for a spec with no study block::

            from fleet.core.define_spec import standard_of

            assert standard_of(None, "/work/sdtm/S01/metadata/adam/define.yaml") == "adam"
    """
    declared = str(study_standard or "").upper()
    if "SDTM" in declared or "SEND" in declared:
        return "sdtm"
    if "ADAM" in declared:
        return "adam"
    for part in reversed(re.split(r"[\\/]", str(path))):
        if part.lower() in ("sdtm", "adam"):
            return part.lower()
    return None


#: The JSON schema of a define.yaml (hand-owned parts plus the generated derivations).
DEFINE_SCHEMA_PATH = (
    Path(__file__).parents[1] / "define_xml" / "schemas" / "define_spec_schema.json"
)


def _schema_lines(path: Path, data: dict[str, Any]) -> list[str]:
    """One message line per schema error of *data*, at most five, with a migrate hint."""
    import json

    import jsonschema

    from fleet.tools.migrate_spec import ALGORITHM_RENAMES

    schema = json.loads(DEFINE_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(jsonschema.Draft202012Validator(schema).iter_errors(data))
    empty = [
        e.json_path[2:]
        for e in errors
        if e.json_path in ("$.study.description", "$.study.originator")
        and e.validator == "minLength"
    ]
    lines: list[str] = []
    for e in errors:
        if e.json_path[2:] in empty:
            continue
        old = e.instance.get("algorithm") if isinstance(e.instance, dict) else None
        if isinstance(old, str) and old in ALGORITHM_RENAMES:
            lines.append(
                f"  - {e.json_path}: algorithm {old!r} is the old name of "
                f"{ALGORITHM_RENAMES[old]!r}. Run: fleet migrate --spec {path}"
            )
        else:
            lines.append(f"  - {e.json_path}: {e.message}")
    lines = list(dict.fromkeys(lines))[:5]
    if empty:
        lines.insert(
            0,
            f"  - {' and '.join(empty)} {'is' if len(empty) == 1 else 'are'} empty. "
            "Write the text in this file, or create the study with "
            "`fleet new --description ... --company ...`.",
        )
    return lines


def read_define_yaml(path: str | Path, *, validate_schema: bool = True) -> dict[str, Any]:
    """Read a define.yaml (the format with ``study:`` and ``datasets:``) as a mapping.

    Args:
        path: The define.yaml file.
        validate_schema: When True (default), check the file against the
            define-spec JSON schema.

    Returns:
        dict[str, Any]: The parsed define.

    Raises:
        SpecSchemaError: When the YAML does not parse, the document is not
            a mapping with ``datasets:``, or the schema refuses it (the
            schema also needs ``study:``).  An old algorithm name gets a ``fleet migrate --spec`` hint.

    Examples:
        Read the pilot SDTM define::

            from fleet.core.define_spec import read_define_yaml

            data = read_define_yaml("examples/cdiscpilot01/sdtm/define.yaml")
            names = [ds["name"] for ds in data["datasets"]]
    """
    from fleet.core.exceptions import SpecSchemaError

    p = Path(path)
    try:
        data = load_spec_yaml(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as err:
        raise SpecSchemaError(f"{p}: invalid YAML: {err}") from err
    if not isinstance(data, dict) or "datasets" not in data:
        kind = (
            "an empty file"
            if data is None
            else "a mapping with no datasets:"
            if isinstance(data, dict)
            else f"a {type(data).__name__}"
        )
        raise SpecSchemaError(
            f"{p}: a define.yaml is a mapping with study: and datasets:; this file is {kind}."
        )
    if validate_schema:
        validate_define_data(p, data)
    return data


def validate_define_data(path: str | Path, data: dict[str, Any]) -> None:
    """Check a parsed define.yaml against the define-spec JSON schema.

    Args:
        path: The file the data came from, for the message.
        data: The parsed define.

    Raises:
        SpecSchemaError: Naming at most five schema errors.

    Examples:
        Check a define read with no schema check::

            from fleet.core.define_spec import read_define_yaml, validate_define_data

            data = read_define_yaml("define.yaml", validate_schema=False)
            validate_define_data("define.yaml", data)
    """
    from fleet.core.exceptions import SpecSchemaError

    lines = _schema_lines(Path(path), data)
    if lines:
        msgs = "\n".join(lines)
        from fleet.tools.migrate_spec import migrate_hint

        raise SpecSchemaError(
            f"{path}: define YAML failed schema validation:\n{msgs}{migrate_hint(data)}"
        )


def load_define_spec(path: str | Path) -> DefineSpec:
    """Load and validate a define.yaml / simplified spec file.

    Args:
        path: Path to the YAML specification file.

    Returns:
        DefineSpec: The validated spec envelope.

    Raises:
        SpecError: On unreadable YAML, a non-mapping document, unknown
            keys, or a missing ``name:`` on a dataset or variable.

    Examples:
        Inspect a spec before executing it::

            from fleet.core.define_spec import load_define_spec

            spec = load_define_spec("examples/cdiscpilot01/sdtm/define.yaml")
            names = [d.name for d in spec.datasets or []]
    """
    p = Path(path)
    try:
        data = load_spec_yaml(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as err:
        raise SpecError(f"{p}: invalid YAML: {err}") from err
    if not isinstance(data, dict):
        raise SpecError(f"{p}: spec must be a YAML mapping, got {type(data).__name__}.")
    try:
        return DefineSpec.model_validate(data)
    except ValidationError as err:
        raise SpecError(f"{p}: {err}") from err
