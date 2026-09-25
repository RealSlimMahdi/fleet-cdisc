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
    StudyConfigError,
    StudyContext,
    find_study_config,
    load_study_context,
)
from fleet.validation.engine import find_engine

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
    """

    standard: Resolved[Standard]
    ig_version: Resolved[str]
    custom_rules: Resolved[Path | None]
    engine: Resolved[Path | None]
    study_config: Path | None

    @property
    def engine_ig_version(self) -> str:
        """The IG version in the dashed form the engine takes (``"3-4"``)."""
        return self.ig_version.value.replace(".", "-")

    def header_lines(self) -> list[str]:
        """Each input with its source, for the report header."""
        rules = self.custom_rules.value
        engine = self.engine.value
        return [
            f"Standard:     {_IG_LABELS[self.standard.value]} ({self.standard.source})",
            f"IG version:   {self.ig_version.value} ({self.ig_version.source})",
            f"Custom rules: {rules if rules is not None else 'none'} ({self.custom_rules.source})",
            f"Engine:       {engine if engine is not None else 'not found'} ({self.engine.source})",
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
    config: Path | None = None,
    start: Path | None = None,
    environ: Mapping[str, str] | None = None,
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
        config: Study config file; replaces the search from *start*.
        start: Directory the study config is looked for from
            (default: the working directory).
        environ: Environment for ``FLEET_RULES_ENGINE``
            (default: ``os.environ``).

    Returns:
        RunSetup: The frozen record of the inputs.

    Raises:
        ValidationSetupError: The validation could not run: the study
            config is invalid, two sources name different standards, the
            IG version is not supported, or the custom rules directory does
            not exist.

    Examples:
        The setup the ``.adam.validate("ADAE")`` verb builds inside a study::

            setup = build_run_setup(name="ADAE", namespace="adam")
            setup.ig_version.value  # "1.1" when adam.ig_version is 1-1
            setup.ig_version.source  # "study config"
    """
    config_path = config if config is not None else find_study_config(start)
    ctx = _load(config_path) if config_path is not None else None

    std = _resolve_standard(standard, namespace, name, path, ctx)
    return RunSetup(
        standard=std,
        ig_version=_resolve_ig_version(version, std.value, ctx),
        custom_rules=_resolve_custom_rules(custom_rules, ctx),
        engine=_resolve_engine(engine, ctx, os.environ if environ is None else environ),
        study_config=config_path,
    )


#: Dataset file types a sweep picks up from a directory.
DATA_EXTENSIONS: tuple[str, ...] = (".parquet", ".csv", ".xpt", ".sas7bdat")


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
    config: Path | None = None,
    start: Path | None = None,
    environ: Mapping[str, str] | None = None,
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
        config: Study config file; replaces the search from *start*.
        start: Directory the study config is looked for from
            (default: the working directory).
        environ: Environment for ``FLEET_RULES_ENGINE``
            (default: ``os.environ``).

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
    files = _collect_files(paths or _data_dirs(config_path))

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
                config=config_path,
                environ=environ,
            )
        except ValidationSetupError as exc:
            datasets.append(SweepDataset(path, None, str(exc)))
            continue
        key = (setup.standard.value, path.stem.upper())
        if setup.engine.value is None:
            reason = (
                "Could not run: CDISC Rules Engine not found. Install it with "
                "`fleet install-engine` or set validation.engine_path / FLEET_RULES_ENGINE."
            )
            datasets.append(SweepDataset(path, None, reason))
        elif key in seen:
            reason = f"Could not run: another file in the sweep is already dataset {key[1]}."
            datasets.append(SweepDataset(path, None, reason))
        else:
            seen.add(key)
            datasets.append(SweepDataset(path, setup))
    return Sweep(tuple(datasets))


def _data_dirs(config_path: Path | None) -> list[Path]:
    if config_path is None:
        raise _refuse(
            "no dataset paths given and no study_config.yaml found. "
            "Pass files or directories, or run inside a study workspace."
        )
    ctx = _load(config_path)
    dirs = [d for d in (ctx.sdtm_data_dir, ctx.adam_data_dir) if d.is_dir()]
    if not dirs:
        raise _refuse(
            f"no data directories found under {ctx.study_root} "
            f"({ctx.config.paths.sdtm_data}, {ctx.config.paths.adam_data}). "
            "Run `fleet run` first or pass explicit paths."
        )
    return dirs


def _collect_files(paths: Sequence[str | Path]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for ext in DATA_EXTENSIONS:
                files.extend(sorted(p.glob(f"*{ext}")))
        elif p.is_file():
            files.append(p)
        else:
            raise _refuse(f"path not found: {p}")
    if not files:
        raise _refuse(f"no dataset files found. Pass {', '.join(DATA_EXTENSIONS)} files.")
    return files


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
        for std, data_dir in (("sdtm", ctx.sdtm_data_dir), ("adam", ctx.adam_data_dir)):
            if where.is_relative_to(data_dir):
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

    dotted = str(raw).strip().replace("-", ".")
    supported = SUPPORTED_IG_VERSIONS[standard]
    if dotted not in supported:
        label = _IG_LABELS[standard]
        raise _refuse(
            f"{label} {raw} (from the {source}) is not supported. "
            f"Supported {label} versions: {', '.join(supported)}."
        )
    return Resolved(dotted, source)


def _resolve_custom_rules(
    custom_rules: str | Path | None, ctx: StudyContext | None
) -> Resolved[Path | None]:
    configured = ctx.custom_rules_dir if ctx is not None else None
    if custom_rules is not None:
        rules, source = Path(custom_rules), "argument"
    elif configured is not None:
        rules, source = configured, "study config"
    else:
        return Resolved(None, "default")
    if not rules.is_dir():
        raise _refuse(f"the custom rules directory {rules} (from the {source}) does not exist.")
    return Resolved(rules, source)


def _resolve_engine(
    engine: str | Path | None, ctx: StudyContext | None, environ: Mapping[str, str]
) -> Resolved[Path | None]:
    if engine is not None:
        return Resolved(Path(engine), "argument")
    found = find_engine(ctx.engine_file if ctx is not None else None, environ)
    if found is None:
        return Resolved(None, "default")
    return Resolved(found[0], found[1])
