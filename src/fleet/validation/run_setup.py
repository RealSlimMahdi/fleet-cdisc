"""Run setup: the resolved inputs of one validation, with the source of each.

Every surface that validates (the ``.validate()`` verb and ``fleet validate``
today; the MCP tool and ``fleet check`` in later steps) builds a
:class:`RunSetup` with :func:`build_run_setup` and resolves nothing itself.
``fleet validate`` builds one per dataset through :func:`build_sweep`.
See ADR 0003.

Each input is taken from the first source that gives it: an explicit
argument, then the study config, then the environment (engine only), then
the built-in default.  A setup that cannot be resolved is refused with
:class:`~fleet.core.exceptions.ValidationSetupError`: the validation
**could not run**.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from fleet.core.exceptions import ValidationSetupError
from fleet.core.study_context import (
    AcceptedFinding,
    StudyConfigError,
    StudyContext,
    find_study_config,
    load_study_context,
)
from fleet.validation.engine import engine_version, find_engine, untested_note

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

Standard = Literal["sdtm", "adam"]

#: Where an input came from, as printed in the report header.
Source = Literal[
    "argument",
    "namespace",
    "data directory",
    "dataset name",
    "study config",
    "environment",
    "default",
]

#: IG versions Fleet accepts, fixed to what CORE ships (ADR 0003).
SUPPORTED_IG_VERSIONS: dict[str, tuple[str, ...]] = {
    "sdtm": ("3.2", "3.3", "3.4"),
    "adam": ("1.0", "1.1", "1.2", "1.3"),
}

#: IG version used when neither an argument nor the study config gives one.
DEFAULT_IG_VERSIONS: dict[str, str] = {"sdtm": "3.4", "adam": "1.3"}

#: Seconds before an engine run is stopped when neither --timeout nor the
#: study config gives a limit.
DEFAULT_TIMEOUT = 300.0

_IG_LABELS: dict[str, str] = {"sdtm": "SDTMIG", "adam": "ADaMIG"}


@dataclass(frozen=True)
class Resolved[T]:
    """One input of a run setup and the source it came from."""

    value: T
    source: Source


@dataclass(frozen=True)
class RunSetup:
    """The resolved inputs of one validation, fixed before the engine starts.

    Attributes:
        standard: ``"sdtm"`` or ``"adam"``.
        ig_version: Dotted IG version (``"3.4"``), checked against
            :data:`SUPPORTED_IG_VERSIONS`.
        custom_rules: Directory of custom CORE rules, or ``None``.
        engine: Engine executable, or ``None`` when none was found.
        study_config: The ``study_config.yaml`` used, or ``None``.
        timeout: Seconds before an engine run is stopped.
        accepted: The findings ``validation.accepted`` accepts (ADR-0017).
        define_xml: The Define-XML CORE checks with the datasets (``-dxp``),
            or ``None``.  Only an argument sets it; it is never a default.
    """

    standard: Resolved[Standard]
    ig_version: Resolved[str]
    custom_rules: Resolved[Path | None]
    engine: Resolved[Path | None]
    study_config: Path | None
    timeout: Resolved[float] = Resolved(DEFAULT_TIMEOUT, "default")
    accepted: tuple[AcceptedFinding, ...] = ()
    define_xml: Resolved[Path | None] = Resolved(None, "default")

    @property
    def engine_version(self) -> str:
        """The engine version (see :func:`~fleet.validation.engine.engine_version`).

        Asked only when read, because it starts the engine: building a run
        setup, as ``fleet check`` does, runs no program a study file names.
        ``"unknown"`` when no engine was found.
        """
        return engine_version(self.engine.value) if self.engine.value is not None else "unknown"

    @property
    def engine_ig_version(self) -> str:
        """The IG version in the dashed form the engine takes (``"3-4"``)."""
        return self.ig_version.value.replace(".", "-")

    def header_lines(self) -> list[str]:
        """Each input with its source, for the report header."""
        rules = self.custom_rules.value
        engine = self.engine.value
        define = (
            [f"Define-XML:   {self.define_xml.value} ({self.define_xml.source})"]
            if self.define_xml.value is not None
            else []
        )
        return [
            f"Standard:     {_IG_LABELS[self.standard.value]} ({self.standard.source})",
            f"IG version:   {self.ig_version.value} ({self.ig_version.source})",
            f"Custom rules: {rules if rules is not None else 'none'} ({self.custom_rules.source})",
            *define,
            f"Engine:       {engine if engine is not None else 'not found'} ({self.engine.source})",
            f"CORE version: {self.engine_version}{untested_note(self.engine_version)}",
            f"Timeout:      {self.timeout.value:g} s ({self.timeout.source})",
            f"Accepted:     {len(self.accepted)} finding rule(s)",
            f"Study config: {self.study_config or 'no study config'}",
        ]


def build_run_setup(
    *,
    name: str | None = None,
    path: Path | None = None,
    namespace: Standard | None = None,
    standard: Standard | None = None,
    version: str | None = None,
    custom_rules: str | Path | None = None,
    engine: str | Path | None = None,
    timeout: float | None = None,
    config: Path | None = None,
    start: Path | None = None,
    environ: Mapping[str, str] | None = None,
    define_xml: str | Path | None = None,
) -> RunSetup:
    """Resolve every input of one validation and record where each came from.

    Args:
        name: Dataset name (``"AE"``, ``"ADSL"``), as the verb receives it.
        path: Dataset file.  Its file stem is the dataset name, and a
            configured data directory that contains it also names the
            standard.
        namespace: The namespace the verb runs on.
        standard: Forces the standard; no other source is consulted.
        version: IG version, ``"3-4"`` or ``"3.4"``.
        custom_rules: Directory of custom CORE rules.
        engine: Engine executable.
        timeout: Seconds before an engine run is stopped.
        config: Study config file; replaces the search from *start*.
        start: Directory the study config is looked for from
            (default: the working directory).
        environ: Environment for ``FLEET_RULES_ENGINE``
            (default: ``os.environ``).
        define_xml: A Define-XML file CORE checks with the datasets.
            Opt-in only: Fleet never passes a define by default.

    Returns:
        RunSetup: The frozen record of the inputs.

    Raises:
        ValidationSetupError: The validation could not run: the study
            config is invalid, two sources name different standards, the
            IG version is not supported, the custom rules directory does
            not exist, or the Define-XML file does not exist.

    Examples:
        The setup the ``.adam.validate("ADAE")`` verb builds inside a study::

            setup = build_run_setup(name="ADAE", namespace="adam")
            setup.ig_version.value  # "1.1" when adam.ig_version is 1-1
            setup.ig_version.source  # "study config"
    """
    config_path = config if config is not None else find_study_config(start)
    ctx = _load(config_path) if config_path is not None else None

    std = _resolve_standard(standard, namespace, name, path, ctx)
    ig_version = _resolve_ig_version(version, std.value, ctx)
    rules = _resolve_custom_rules(custom_rules, ctx)
    exe = _resolve_engine(engine, ctx, os.environ if environ is None else environ)
    return RunSetup(
        standard=std,
        ig_version=ig_version,
        custom_rules=rules,
        engine=exe,
        study_config=config_path,
        timeout=_resolve_timeout(timeout, ctx),
        accepted=tuple(ctx.config.validation.accepted) if ctx is not None else (),
        define_xml=_resolve_define_xml(define_xml),
    )


def _resolve_define_xml(define_xml: str | Path | None) -> Resolved[Path | None]:
    if define_xml is None:
        return Resolved(None, "default")
    path = Path(define_xml).resolve()
    if not path.is_file():
        raise _refuse(f"the Define-XML file {define_xml} (from the argument) does not exist.")
    return Resolved(path, "argument")


#: Dataset file types a sweep picks up from a directory (any case).  A
#: ``.json`` file counts only when it is Dataset-JSON (see :func:`is_dataset_json`).
DATA_EXTENSIONS: tuple[str, ...] = (".parquet", ".csv", ".xpt", ".sas7bdat", ".json")

#: Bytes read from the start of a ``.json`` file to see whether it is Dataset-JSON.
_JSON_HEAD = 1 << 20


def is_dataset_json(path: Path) -> bool:
    """Whether *path* holds Dataset-JSON: its start names ``datasetJSONVersion`` and ``columns``.

    A data folder can also hold other JSON files, such as an engine report
    or ``pipeline_dag.json``; a sweep skips them.

    Args:
        path: A ``.json`` file.

    Returns:
        bool: ``True`` when both Dataset-JSON keys occur in the first MB.
    """
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            head = fh.read(_JSON_HEAD)
    except OSError:
        return False
    return '"datasetJSONVersion"' in head and '"columns"' in head


@dataclass(frozen=True)
class SweepDataset:
    """One dataset of a sweep: its run setup, or why it could not run.

    Attributes:
        path: The dataset file.
        setup: The resolved inputs, or ``None`` when the dataset could not run.
        reason: Why the dataset could not run, or ``None``.
    """

    path: Path
    setup: RunSetup | None
    reason: str | None = None

    @property
    def name(self) -> str:
        """The dataset name: the upper-case file stem (``"ADSL"``)."""
        return self.path.stem.upper()


@dataclass(frozen=True)
class Sweep:
    """The datasets of one ``fleet validate`` call, fixed before the engine starts."""

    datasets: tuple[SweepDataset, ...]
    #: Files of a swept directory that are not datasets, so not validated.
    skipped: tuple[Path, ...] = ()

    @property
    def could_not_run(self) -> list[SweepDataset]:
        """The datasets whose run setup was refused."""
        return [d for d in self.datasets if d.setup is None]

    def runs(self) -> dict[Standard, list[SweepDataset]]:
        """The datasets that can run, grouped by standard: one engine run each."""
        runs: dict[Standard, list[SweepDataset]] = {}
        for d in self.datasets:
            if d.setup is not None:
                runs.setdefault(d.setup.standard.value, []).append(d)
        return runs


def build_sweep(
    paths: Sequence[str | Path] = (),
    *,
    standard: Standard | None = None,
    version: str | None = None,
    custom_rules: str | Path | None = None,
    engine: str | Path | None = None,
    timeout: float | None = None,
    config: Path | None = None,
    start: Path | None = None,
    environ: Mapping[str, str] | None = None,
    define_xml: str | Path | None = None,
) -> Sweep:
    """Resolve the run setup of every dataset a ``fleet validate`` call names.

    With no *paths*, the sweep takes every dataset file in the configured
    SDTM and ADaM data directories.  Each dataset gets its own run setup
    from :func:`build_run_setup`; a refused dataset is kept with its
    reason, and the other datasets still run.

    Args:
        paths: Dataset files or directories.  Default: the configured data
            directories.
        standard: Forces the standard of every dataset.
        version: IG version, ``"3-4"`` or ``"3.4"``.
        custom_rules: Directory of custom CORE rules.
        engine: Engine executable.
        timeout: Seconds before an engine run is stopped.
        config: Study config file; replaces the search from *start*.
        start: Directory the study config is looked for from
            (default: the working directory).
        environ: Environment for ``FLEET_RULES_ENGINE``
            (default: ``os.environ``).
        define_xml: A Define-XML file CORE checks with the datasets (opt-in).

    Returns:
        Sweep: Every dataset with its run setup or its reason.

    Raises:
        ValidationSetupError: No dataset to validate: a path does not
            exist, no file was found, or no paths were given outside a study.

    Examples:
        The sweep ``fleet validate`` runs inside a study::

            sweep = build_sweep()
            for standard, datasets in sweep.runs().items():
                print(standard, [d.name for d in datasets])
    """
    config_path = config if config is not None else find_study_config(start)
    files, skipped = _collect_files(paths or _data_dirs(config_path))

    datasets: list[SweepDataset] = []
    seen: set[tuple[Standard, str]] = set()
    for path in files:
        try:
            setup = build_run_setup(
                path=path,
                standard=standard,
                version=version,
                custom_rules=custom_rules,
                engine=engine,
                timeout=timeout,
                config=config_path,
                environ=environ,
                define_xml=define_xml,
            )
        except ValidationSetupError as exc:
            datasets.append(SweepDataset(path, None, str(exc)))
            continue
        key = (setup.standard.value, path.stem.upper())
        if setup.engine.value is None:
            datasets.append(SweepDataset(path, None, missing_engine_reason(setup)))
        elif key in seen:
            reason = f"Could not run: another file in the sweep is already dataset {key[1]}."
            datasets.append(SweepDataset(path, None, reason))
        else:
            seen.add(key)
            datasets.append(SweepDataset(path, setup))
    return Sweep(tuple(datasets), tuple(skipped))


def missing_engine_reason(setup: RunSetup) -> str:
    """Why a run setup with no engine could not run; a missing pinned engine is named.

    Args:
        setup: A run setup whose ``engine.value`` is ``None``.

    Returns:
        str: ``"Could not run: ..."``.
    """
    if setup.engine.source == "study config" and setup.study_config is not None:
        pinned = _load(setup.study_config).config.validation.engine_path
        return (
            f"Could not run: validation.engine_path in {setup.study_config} names the "
            f"engine {pinned}, and that file does not exist. Fleet does not fall back to "
            "another engine for a pinned study (ADR 0003)."
        )
    return (
        "Could not run: CDISC Rules Engine not found. Install it with "
        "`fleet install-engine` or set validation.engine_path / FLEET_RULES_ENGINE."
    )


def _data_dirs(config_path: Path | None) -> list[Path]:
    if config_path is None:
        raise _refuse(
            "no dataset paths given and no study_config.yaml found. "
            "Pass files or directories, or run inside a study workspace."
        )
    ctx = _load(config_path)
    # A data folder both standards share is swept once.
    dirs = list(dict.fromkeys(d for d in (ctx.sdtm_data_dir, ctx.adam_data_dir) if d.is_dir()))
    if not dirs:
        raise _refuse(
            f"no data directories found under {ctx.study_root} "
            f"({ctx.config.paths.sdtm_data}, {ctx.config.paths.adam_data}). "
            "Run `fleet run` first or pass explicit paths."
        )
    return dirs


def _collect_files(paths: Sequence[str | Path]) -> tuple[list[Path], list[Path]]:
    """The dataset files *paths* name, and the other files of each swept directory."""
    files: list[Path] = []
    skipped: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for f in sorted(p.iterdir()):
                if not f.is_file() or f.name.startswith("."):
                    continue
                suffix = f.suffix.lower()
                if suffix in DATA_EXTENSIONS and (suffix != ".json" or is_dataset_json(f)):
                    files.append(f)
                else:
                    skipped.append(f)
        elif p.is_file():
            files.append(p)
        else:
            raise _refuse(f"path not found: {p}")
    if not files:
        named = f" Skipped: {', '.join(p.name for p in skipped)}." if skipped else ""
        raise _refuse(f"no dataset files found. Pass {', '.join(DATA_EXTENSIONS)} files.{named}")
    return files, skipped


def _refuse(reason: str) -> ValidationSetupError:
    return ValidationSetupError(f"Could not run: {reason}")


def _load(config_path: Path) -> StudyContext:
    if not config_path.is_file():
        raise _refuse(f"the study config {config_path} does not exist.")
    try:
        return load_study_context(config_path)
    except StudyConfigError as exc:
        raise _refuse(f"the study config {config_path} is invalid. {exc}") from exc


def _standard_of_name(name: str) -> Standard:
    return "adam" if name.upper().startswith("AD") else "sdtm"


def _resolve_standard(
    standard: Standard | None,
    namespace: Standard | None,
    name: str | None,
    path: Path | None,
    ctx: StudyContext | None,
) -> Resolved[Standard]:
    if standard is not None:
        if standard not in _IG_LABELS:
            raise _refuse(f"unknown standard {standard!r}. Choose 'sdtm' or 'adam'.")
        return Resolved(standard, "argument")

    claims: list[Resolved[Standard]] = []
    if namespace is not None:
        claims.append(Resolved(namespace, "namespace"))
    if path is not None and ctx is not None:
        where = path.resolve()
        # Only the deepest data directory that holds the file names its standard;
        # one folder that both standards share names none.
        holding = [
            (std, data_dir)
            for std, data_dir in (("sdtm", ctx.sdtm_data_dir), ("adam", ctx.adam_data_dir))
            if where.is_relative_to(data_dir)
        ]
        if len(holding) == 2 and holding[0][1] == holding[1][1]:
            holding = []
        if holding:
            std, _ = max(holding, key=lambda pair: len(pair[1].parts))
            claims.append(Resolved(std, "data directory"))
    dataset = path.stem if path is not None else name
    if dataset:
        claims.append(Resolved(_standard_of_name(dataset), "dataset name"))

    if not claims:
        raise _refuse("standard unclear: no dataset and no standard given.")
    for other in claims[1:]:
        if other.value != claims[0].value:
            hint = " Pass --standard to force it." if path is not None else ""
            raise _refuse(
                f"standard unclear for {dataset or path}: the {claims[0].source} says "
                f"{_IG_LABELS[claims[0].value]}, the {other.source} says "
                f"{_IG_LABELS[other.value]}.{hint}"
            )
    return claims[0]


def _resolve_ig_version(
    version: str | None, standard: Standard, ctx: StudyContext | None
) -> Resolved[str]:
    declared = getattr(ctx.config, standard).ig_version if ctx is not None else None
    if version is not None:
        raw, source = version, "argument"
    elif declared is not None:
        raw, source = declared, "study config"
    else:
        raw, source = DEFAULT_IG_VERSIONS[standard], "default"
    return Resolved(check_ig_version(standard, raw, source), source)


def check_ig_version(standard: Standard, version: str, source: Source = "argument") -> str:
    """Return *version* dotted, or refuse an IG version Fleet does not support.

    Args:
        standard: ``"sdtm"`` or ``"adam"``.
        version: IG version, ``"3.4"`` or ``"3-4"``.
        source: Where the version came from, for the message.

    Returns:
        str: The dotted version (``"3.4"``).

    Raises:
        ValidationSetupError: The version is not in :data:`SUPPORTED_IG_VERSIONS`.

    Examples:
        ``check_ig_version("sdtm", "3-4")`` gives ``"3.4"``;
        ``check_ig_version("sdtm", "3.1.3")`` raises.
    """
    dotted = str(version).strip().replace("-", ".")
    if standard not in SUPPORTED_IG_VERSIONS:
        raise _refuse(f"unknown standard {standard!r}. Choose 'sdtm' or 'adam'.")
    supported = SUPPORTED_IG_VERSIONS[standard]
    if dotted not in supported:
        label = _IG_LABELS[standard]
        raise _refuse(
            f"{label} {version} (from the {source}) is not supported. "
            f"Supported {label} versions: {', '.join(supported)}."
        )
    return dotted


def _resolve_custom_rules(
    custom_rules: str | Path | None, ctx: StudyContext | None
) -> Resolved[Path | None]:
    configured = ctx.custom_rules_dir if ctx is not None else None
    if custom_rules is not None:
        rules, source = Path(custom_rules).resolve(), "argument"
    elif configured is not None:
        rules, source = configured, "study config"
    else:
        return Resolved(None, "default")
    if not rules.is_dir():
        raise _refuse(f"the custom rules directory {rules} (from the {source}) does not exist.")
    return Resolved(rules, source)


def _resolve_timeout(timeout: float | None, ctx: StudyContext | None) -> Resolved[float]:
    configured = ctx.config.validation.timeout if ctx is not None else None
    if timeout is not None:
        if timeout <= 0:
            raise _refuse(f"the timeout must be a positive number of seconds, not {timeout}.")
        return Resolved(float(timeout), "argument")
    if configured is not None:
        return Resolved(float(configured), "study config")
    return Resolved(DEFAULT_TIMEOUT, "default")


def _resolve_engine(
    engine: str | Path | None, ctx: StudyContext | None, environ: Mapping[str, str]
) -> Resolved[Path | None]:
    if engine is not None:
        return Resolved(Path(engine).resolve(), "argument")
    pinned = ctx.engine_file if ctx is not None else None
    if pinned is not None and not pinned.is_file():
        # One pinned rule build per study (ADR 0003): no fallback to another engine.
        return Resolved(None, "study config")
    found = find_engine(pinned, environ)
    if found is None:
        return Resolved(None, "default")
    return Resolved(found[0], found[1])
