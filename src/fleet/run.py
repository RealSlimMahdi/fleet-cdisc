"""Study run: build every dataset a study's define files declare.

``plan_study`` reads the define files of a study and returns a
:class:`StudyPlan`, the ordered steps of a study run, without building
anything. ``run_study`` takes a plan and yields one :class:`BuiltDataset`
per step. The module writes no file and prints nothing: ``fleet run``, a
notebook and a protocol adapter all start the same study run and decide
for themselves what to do with each built dataset. See ADR 0006 for the
rule on inputs and ``CONTEXT.md``, section "Running a study", for the terms.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import polars as pl

from fleet.core.define_spec import load_define_spec
from fleet.core.exceptions import DerivationError, StudyRunError
from fleet.core.frames import frame as _frame
from fleet.core.joins import refuse_repeated_keys

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from fleet.adam.namespace import AdamNamespace
    from fleet.core.define_spec import DatasetEntry
    from fleet.core.study_context import StudyContext
    from fleet.sdtm.namespace import SDTMNamespace

__all__ = [
    "DATASET_EXTENSIONS",
    "BuiltDataset",
    "DeclaredInput",
    "InputSource",
    "ResolvedInput",
    "Standard",
    "Step",
    "StudyPlan",
    "find_dataset_file",
    "plan_study",
    "run_study",
]

Standard = Literal["sdtm", "adam"]

#: Where a step's input came from.
InputSource = Literal[
    "seed", "built", "declared path", "raw directory", "sdtm directory", "adam directory"
]

#: Dataset file extensions searched by name in the data directories.
DATASET_EXTENSIONS = (".parquet", ".csv", ".xpt", ".sas7bdat")


@dataclass(frozen=True)
class DeclaredInput:
    """One entry of a dataset's ``inputs:`` block.

    Attributes:
        name: The input's name, as declared.
        path: Its ``path:``, relative to the study root, or ``None``.
    """

    name: str
    path: str | None


@dataclass(frozen=True)
class ResolvedInput:
    """One input of a step and where the study run took it from.

    Attributes:
        path: The file it was read from, or ``None`` for a seed or a
            dataset built earlier in the run.
        source: Which of the sources supplied it.
    """

    path: Path | None
    source: InputSource


@dataclass(frozen=True)
class Step:
    """One dataset of a study plan.

    Attributes:
        define: The define file that declares the dataset.
        standard: ``"sdtm"`` or ``"adam"``.
        dataset: The dataset name, upper-cased.
        inputs: The declared inputs, in order.  The first is the base
            frame; every other one is pinned under its name.
        carry_through: The declared variables with no derivation, which
            the run takes from the inputs unchanged (ADR 0006).
        text_columns: The variables of define type ``text`` and the raw
            columns their derivations name as ``source``.  A CSV input
            reads them as text, so SUBJID ``0012`` and LBORRES ``1.10``
            keep their characters.
        qualifiers: The SDTM variables with ``role: qualifier`` or
            ``algorithm: nsv``.  The run moves them to a SUPP dataset.
    """

    define: Path
    standard: Standard
    dataset: str
    inputs: tuple[DeclaredInput, ...]
    carry_through: tuple[str, ...]
    text_columns: tuple[str, ...] = ()
    qualifiers: tuple[str, ...] = ()


@dataclass(frozen=True)
class StudyPlan:
    """The ordered steps of a study run, fixed before the first one builds.

    Attributes:
        ctx: The study context the steps resolve against.
        steps: The steps, in run order.
    """

    ctx: StudyContext
    steps: tuple[Step, ...]


@dataclass(frozen=True)
class BuiltDataset:
    """What a study run yields for one step.

    Attributes:
        step: The step that was built.
        frame: The built dataset, materialised.  An SDTM dataset leaves out
            its qualifier variables, which are in *supp*.
        inputs: Each input of the step, by name, with where it came from.
        supp: The ``SUPP<domain>`` dataset of an SDTM step with qualifier
            variables (SDTMIG 3.4 section 8.4), else ``None``.
    """

    step: Step
    frame: pl.DataFrame
    inputs: dict[str, ResolvedInput]
    supp: pl.DataFrame | None = None


def plan_study(ctx: StudyContext, *, datasets: Sequence[str] | None = None) -> StudyPlan:
    """Read the study's define files and return the steps of a study run.

    The SDTM define comes first, then the ADaM define, each in file order.

    Args:
        ctx: The study context, from :func:`fleet.load_study_context`.
        datasets: Keep only these datasets (case-insensitive).  Default:
            every dataset in the define files.

    Returns:
        StudyPlan: The steps, in run order.

    Raises:
        StudyRunError: When neither define file exists, a name in
            *datasets* is not declared in them, or a planned dataset
            declares no inputs.

    Examples:
        List what ``fleet run`` would build::

            plan = fleet.plan_study(fleet.load_study_context("study_config.yaml"))
            [(s.standard, s.dataset) for s in plan.steps]
    """
    standards: tuple[Standard, ...] = ("sdtm", "adam")
    defines = [
        (ctx.metadata_dir(standard) / "define.yaml", standard)
        for standard in standards
        if (ctx.metadata_dir(standard) / "define.yaml").is_file()
    ]
    if not defines:
        raise StudyRunError(
            f"no define.yaml found under {ctx.metadata_sdtm_dir} or "
            f"{ctx.metadata_adam_dir}. Run `fleet init define` first."
        )

    steps: list[Step] = []
    for path, standard in defines:
        for entry in load_define_spec(path).datasets or []:
            steps.append(
                Step(
                    define=path,
                    standard=standard,
                    dataset=entry.name.upper(),
                    inputs=tuple(
                        DeclaredInput(name=i["name"], path=i.get("path")) for i in entry.inputs
                    ),
                    carry_through=tuple(v.name for v in entry.variables if v.derivation is None),
                    text_columns=_text_columns(entry),
                    qualifiers=_qualifiers(entry) if standard == "sdtm" else (),
                )
            )

    if datasets is not None:
        wanted = {d.upper() for d in datasets}
        known = sorted({s.dataset for s in steps})
        unknown = sorted(wanted - set(known))
        if unknown:
            raise StudyRunError(
                f"unknown dataset(s): {', '.join(unknown)}. "
                f"Datasets in the define files: {', '.join(known)}"
            )
        steps = [s for s in steps if s.dataset in wanted]

    for step in steps:
        if not step.inputs:
            raise StudyRunError(
                f"dataset {step.dataset}: the define declares no `inputs:`, so a study "
                "run cannot determine the source data. Add an inputs: block."
            )

    return StudyPlan(ctx=ctx, steps=tuple(steps))


def run_study(
    plan: StudyPlan,
    *,
    inputs: Mapping[str, pl.DataFrame] | None = None,
    strict: bool = True,
) -> Iterator[BuiltDataset]:
    """Build every step of a study plan, in order, and yield each built dataset.

    Writes no file and prints nothing.

    Args:
        plan: The plan from :func:`plan_study`.
        inputs: Frames the caller already holds, by dataset name.  A seed
            is used before any file.
        strict: Raise on an unknown spec algorithm (default).  ``False``
            warns and skips, as ``from_spec`` does.

    Yields:
        BuiltDataset: One per step, as soon as it is built.

    Raises:
        StudyRunError: When a seed is also a step of the plan, an input
            cannot be found, or a carry-through column needs a USUBJID
            that one side lacks or that has two different rows in the input.

    Examples:
        Build ADVS from an ADSL held in memory::

            plan = fleet.plan_study(ctx, datasets=["ADVS"])
            advs = next(fleet.run_study(plan, inputs={"ADSL": adsl})).frame
    """
    held: dict[str, _Held] = {
        name.upper(): _Held(frame, ResolvedInput(path=None, source="seed"))
        for name, frame in (inputs or {}).items()
    }
    text_columns = frozenset(c for s in plan.steps for c in s.text_columns)
    collisions = sorted(held.keys() & {s.dataset for s in plan.steps})
    if collisions:
        raise StudyRunError(
            f"{', '.join(collisions)} is both a seeded input and a step; "
            "plan with datasets= to leave it out."
        )

    for step in plan.steps:
        resolved = {d.name: _resolve_input(plan.ctx, d, held, text_columns) for d in step.inputs}
        frames = [held[d.name.upper()].frame for d in step.inputs]
        base, extras = frames[0], list(zip(step.inputs[1:], frames[1:], strict=True))

        for declared, extra in extras:
            cols = [c for c in extra.columns if c in step.carry_through and c not in base.columns]
            if not cols:
                continue
            if "USUBJID" not in base.columns or "USUBJID" not in extra.columns:
                raise StudyRunError(
                    f"dataset {step.dataset}: cannot carry {', '.join(cols)} from input "
                    f"'{declared.name}' because both frames must carry USUBJID."
                )
            try:
                carried = refuse_repeated_keys(
                    "fleet run", extra.select(["USUBJID", *cols]), ["USUBJID"], source=declared.name
                )
            except DerivationError as err:
                raise StudyRunError(f"dataset {step.dataset}: {err}") from err
            base = base.join(carried, on="USUBJID", how="left")

        ns = _namespace(base, step.standard)
        for declared, extra in extras:
            ns = ns.pin(declared.name.upper(), extra)
        built_frame = (
            ns.from_spec(step.define, dataset=step.dataset, strict=strict)
            .select(spec=step.define, dataset=step.dataset)
            .to_frame()
        )
        held[step.dataset] = _Held(built_frame, ResolvedInput(path=None, source="built"))
        if step.qualifiers:
            seq = f"{step.dataset}SEQ"
            supp = _frame(built_frame).sdtm.export_supp(
                spec=step.define,
                dataset=step.dataset,
                idvar=seq if seq in built_frame.columns else None,
                domain=step.dataset,
            )
            parent = built_frame.drop(step.qualifiers, strict=False)
            yield BuiltDataset(step=step, frame=parent, inputs=resolved, supp=supp)
            continue
        yield BuiltDataset(step=step, frame=built_frame, inputs=resolved)


def find_dataset_file(name: str, dirs: Sequence[Path]) -> Path | None:
    """Find ``<name>.<ext>`` (lower or upper stem) in the first directory that has it.

    Args:
        name: The dataset name, in any case.
        dirs: Directories to search, in order.

    Returns:
        Path | None: The first file found, or ``None``.

    Examples:
        Locate ADSL under the configured ADaM directory::

            path = fleet.run.find_dataset_file("ADSL", [ctx.adam_data_dir])
    """
    for directory in dirs:
        for stem in (name.lower(), name.upper()):
            for ext in DATASET_EXTENSIONS:
                candidate = directory / f"{stem}{ext}"
                if candidate.is_file():
                    return candidate
    return None


@dataclass(frozen=True)
class _Held:
    """A frame the run holds under a dataset name, and where it came from."""

    frame: pl.DataFrame
    origin: ResolvedInput


def _text_columns(entry: DatasetEntry) -> tuple[str, ...]:
    """The define text variables and the raw columns their derivations take as source."""
    columns: dict[str, None] = {}
    for v in entry.variables:
        if (v.type or "").lower() != "text":
            continue
        columns[v.name] = None
        source = (v.derivation or {}).get("source")
        if isinstance(source, str):
            columns[source] = None
    return tuple(columns)


def _qualifiers(entry: DatasetEntry) -> tuple[str, ...]:
    """The SDTM variables that belong in SUPP, as ``export_supp(spec=)`` reads them."""
    return tuple(
        v.name
        for v in entry.variables
        if v.role == "qualifier" or (v.derivation or {}).get("algorithm") == "nsv"
    )


def _namespace(df: pl.DataFrame, standard: Standard) -> SDTMNamespace | AdamNamespace:
    """The namespace a step runs in: the one place that branches on the standard."""
    return _frame(df).sdtm if standard == "sdtm" else _frame(df).adam


def _resolve_input(
    ctx: StudyContext,
    declared: DeclaredInput,
    held: dict[str, _Held],
    text_columns: frozenset[str] = frozenset(),
) -> ResolvedInput:
    """Find one declared input, loading it into *held* when it comes from a file.

    In order: a seed or a dataset built earlier in this run, then the
    input's ``path:`` relative to the study root, then the input's name in
    the raw, SDTM and ADaM data directories.  A declared path that does
    not exist is refused; it does not fall back to the name search.  A CSV
    input reads *text_columns* as text.
    """
    from fleet.io import load_raw_data

    key = declared.name.upper()
    if key in held:
        return held[key].origin

    def hold(file: Path, source: InputSource) -> ResolvedInput:
        options = (
            {"schema_overrides": dict.fromkeys(text_columns, pl.String)}
            if file.suffix.lower() == ".csv"
            else {}
        )
        frame = load_raw_data(file, **options).collect()
        held[key] = _Held(frame, ResolvedInput(path=file, source=source))
        return held[key].origin

    if declared.path is not None:
        file = ctx.resolve(declared.path)
        if not file.is_file():
            raise StudyRunError(
                f"input dataset '{declared.name}' not found: its declared path "
                f"{declared.path} does not exist under the study root {ctx.study_root}."
            )
        return hold(file, "declared path")

    directories: tuple[tuple[Path, InputSource], ...] = (
        (ctx.raw_data_dir, "raw directory"),
        (ctx.sdtm_data_dir, "sdtm directory"),
        (ctx.adam_data_dir, "adam directory"),
    )
    for directory, source in directories:
        found = find_dataset_file(declared.name, [directory])
        if found is not None:
            return hold(found, source)

    raise StudyRunError(
        f"input dataset '{declared.name}' not found. Searched for "
        f"{declared.name.lower()}/{declared.name.upper()} with extensions "
        f"{', '.join(DATASET_EXTENSIONS)} under: {', '.join(str(d) for d, _ in directories)}. "
        "Run the upstream dataset first (fleet run --dataset ...), place the file "
        "in one of those directories, or pass it as an input."
    )
