"""The study's generated ``codelists.py``: the terms both CT notations check against.

The inline ``assign("AESEV", source="ae_severity", ct=AESEV)`` validates
against the class it is given.  :func:`spec_codelists` gives ``from_spec``
the same classes for its ``ct_codelist:`` IDs, read from the study's
``codelists.py``, so both notations of one step check the same terms.

Because both then trust the file, :func:`check_codelists` compares it with
the study:

a. the CT package it was generated from is not ``ct.package`` in
   ``study_config.yaml``;
b. its classes name different CT packages;
c. a ``codelist:`` or ``ct_codelist:`` ID of a ``define.yaml`` has no class
   in it;
d. the ``define.yaml`` files reference codelists, but it does not exist.

``from_spec`` warns about a, b and d, the inline path about a
(:func:`warn_if_class_stale`), each problem once per process;
``fleet check`` fails on all four.  The study is found by walking up from a
file (the ``define.yaml``, or the module of the class), never from the
working directory.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import warnings
from collections import Counter
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from fleet.core.exceptions import SpecError
from fleet.core.study_context import StudyConfigError, find_study_config, load_study_context
from fleet.ct.generator import codelist_references, extract_concept_ids

if TYPE_CHECKING:
    from fleet.core.study_context import StudyContext

#: The CT package in a CDISC Library Browser URL (``.../packages/sdtmct-2023-12-15/...``).
_URL_PACKAGE = re.compile(r"/packages/([^/]+)/")
_MARKER = re.compile(r"""^__ct_package__\s*=\s*["']([^"']+)["']""", re.MULTILINE)
_CONCEPT_ID = re.compile(r"""_concept_id\s*=\s*["']([^"']+)["']""")
_CLASS_URL = re.compile(
    r"""_concept_id\s*=\s*["']([^"']+)["']\s*\n\s*_cdisc_url\s*=\s*["']([^"']+)["']"""
)

#: Problems already reported in this process; each one warns once.
_WARNED: set[str] = set()

#: Codelist classes of a study, by config, config version and codelists.py version.
_RESOLVED: dict[tuple[Path, int, int | None], dict[str, type]] = {}


@dataclass(frozen=True)
class CodelistsFile:
    """What a generated ``codelists.py`` says about its own CT package.

    Attributes:
        path: The file.
        marker: Its ``__ct_package__`` marker; ``None`` in files generated
            before the marker existed.
        concept_ids: The concept ID of every class.
        class_packages: The CT package the ``_cdisc_url`` of each class
            names, by concept ID.
    """

    path: Path
    marker: str | None
    concept_ids: frozenset[str]
    class_packages: dict[str, str]

    @property
    def package(self) -> str | None:
        """The package it was generated from: the marker, else the one package its classes name."""
        if self.marker is not None:
            return self.marker
        packages = set(self.class_packages.values())
        return packages.pop() if len(packages) == 1 else None


def read_codelists_file(path: Path) -> CodelistsFile:
    """Read the CT package marker and the class URLs of a generated ``codelists.py``.

    The file is read as text, not imported.

    Args:
        path: The ``codelists.py`` file.

    Returns:
        CodelistsFile: Its marker, concept IDs and class packages.

    Examples:
        Name the package a study's codelists were generated from::

            from fleet.ct.study_codelists import read_codelists_file

            read_codelists_file(Path("metadata/sdtm/codelists.py")).package
            # "sdtmct-2023-12-15"
    """
    text = path.read_text(encoding="utf-8")
    marker = _MARKER.search(text)
    packages: dict[str, str] = {}
    for concept_id, url in _CLASS_URL.findall(text):
        found = _URL_PACKAGE.search(url)
        if found:
            packages[concept_id] = found[1]
    return CodelistsFile(
        path=path,
        marker=marker[1] if marker else None,
        concept_ids=frozenset(_CONCEPT_ID.findall(text)),
        class_packages=packages,
    )


def check_codelists(ctx: StudyContext, *, references: bool = False) -> list[str]:
    """Return how the study's ``codelists.py`` disagrees with the study, one message per problem.

    Runs checks a (package mismatch), b (mixed packages) and d (missing
    file); with *references*, also c (a referenced codelist without a
    class).  Each message ends with the command that fixes it.

    Args:
        ctx: The study.
        references: Also check that every codelist the ``define.yaml``
            files reference has a class in ``codelists.py``.

    Returns:
        list[str]: The problems; empty when the file agrees with the study.

    Examples:
        The codelists part of ``fleet check``::

            from fleet.core.study_context import load_study_context
            from fleet.ct.study_codelists import check_codelists

            ctx = load_study_context(Path("study_config.yaml"))
            for problem in check_codelists(ctx, references=True):
                print(problem)
    """
    path = ctx.codelists_file
    defines = {
        standard: define
        for standard, define in (
            ("sdtm", ctx.metadata_sdtm_dir / "define.yaml"),
            ("adam", ctx.metadata_adam_dir / "define.yaml"),
        )
        if define.is_file()
    }
    if not path.is_file():
        referenced = set().union(*(extract_concept_ids(d) for d in defines.values()))
        if not referenced:
            return []
        return [
            f"define.yaml references {_count(len(referenced), 'codelist', 'codelists')}, but "
            f"{_shown(path, ctx)} does not exist. Run: fleet init ct"
        ]

    file = read_codelists_file(path)
    problems: list[str] = []
    pinned = ctx.config.ct.package
    if file.package is not None and file.package != pinned:
        problems.append(_package_mismatch(file.package, pinned))
    counts = Counter(file.class_packages.values())
    if len(counts) > 1:
        mix = [
            f"{package} ({_count(n, 'class', 'classes')})" for package, n in counts.most_common()
        ]
        problems.append(
            f"codelists.py mixes {', '.join(mix[:-1])} and {mix[-1]}. Run: fleet init ct --force"
        )
    if references:
        for standard, define in defines.items():
            for dataset, variable, concept_id in codelist_references(define):
                if concept_id in file.concept_ids:
                    continue
                # fleet add-ct reads the SDTM IG, so it cannot add an ADaM dataset's codelists.
                fix = (
                    f"fleet add-ct --domains {dataset}"
                    if standard == "sdtm"
                    else "fleet init ct --force"
                )
                problems.append(
                    f"{dataset}.{variable} references codelist {concept_id}, "
                    f"which is not in codelists.py. Run: {fix}"
                )
    return list(dict.fromkeys(problems))


def spec_codelists(define_path: Path, *, stacklevel: int = 1) -> dict[str, type]:
    """Return the codelist classes of the study a ``define.yaml`` belongs to, by concept ID.

    The study is the first ``study_config.yaml`` above the folder of
    *define_path*.  The first time a version of the study's files is
    resolved, each problem of checks a, b and d warns once (see
    :func:`check_codelists`).  Values are still checked against the terms
    in the file: the warning names the fix, and CORE stays the authority.

    Args:
        define_path: The ``define.yaml`` that ``from_spec`` runs.
        stacklevel: Frame the warnings point at, counted from the caller
            as in :func:`warnings.warn`.

    Returns:
        dict[str, type]: The classes of the study's ``codelists.py`` by
            ``_concept_id``; empty outside a study or without the file.

    Raises:
        SpecError: When ``codelists.py`` exists but cannot be imported.

    Examples:
        Resolve ``ct_codelist: C66769`` the way ``from_spec`` does::

            from fleet.ct.study_codelists import spec_codelists

            AESEV = spec_codelists(Path("metadata/sdtm/define.yaml"))["C66769"]
            ae = raw.sdtm.assign("AESEV", source="ae_severity", ct=AESEV).to_frame()
    """
    config = find_study_config(define_path.resolve().parent)
    if config is None:
        return {}
    try:
        ctx = load_study_context(config)
    except StudyConfigError:
        return {}
    path = ctx.codelists_file
    key = (config, config.stat().st_mtime_ns, path.stat().st_mtime_ns if path.is_file() else None)
    if key not in _RESOLVED:
        for problem in check_codelists(ctx):
            _warn_once(problem, stacklevel=stacklevel + 1)
        _RESOLVED[key] = _classes_by_concept_id(path) if path.is_file() else {}
    return _RESOLVED[key]


def warn_if_class_stale(cls: type, *, stacklevel: int = 1) -> None:
    """Warn once when a codelist class comes from another CT package than its study pins.

    The study is the first ``study_config.yaml`` above the module that
    defines *cls*, never above the working directory.  The warning has the
    text of check a (see :func:`check_codelists`).  A class whose
    ``_cdisc_url`` names no package, or that lives outside a study, is not
    checked.

    Args:
        cls: A generated codelist class, as passed to ``assign(ct=...)``.
        stacklevel: Frame the warning points at, counted from the caller
            as in :func:`warnings.warn`.

    Examples:
        The check ``assign`` runs on its ``ct=`` class::

            from codelists import AESEV
            from fleet.ct.study_codelists import warn_if_class_stale

            warn_if_class_stale(AESEV)
            ae = raw.sdtm.assign("AESEV", source="ae_severity", ct=AESEV).to_frame()
    """
    url = getattr(cls, "_cdisc_url", None)
    found = _URL_PACKAGE.search(url) if isinstance(url, str) else None
    module_file = getattr(sys.modules.get(cls.__module__), "__file__", None)
    if found is None or not module_file:
        return
    pinned = _pinned_package(Path(module_file).resolve().parent)
    if pinned is not None and found[1] != pinned:
        _warn_once(_package_mismatch(found[1], pinned), stacklevel=stacklevel + 1)


@cache
def _pinned_package(folder: Path) -> str | None:
    """``ct.package`` of the study above *folder*, or ``None`` outside a study."""
    config = find_study_config(folder)
    if config is None:
        return None
    try:
        return load_study_context(config).config.ct.package
    except StudyConfigError:
        return None


def _classes_by_concept_id(path: Path) -> dict[str, type]:
    """Import *path* without registering it in ``sys.modules``; map its classes by concept ID."""
    spec = importlib.util.spec_from_file_location("_fleet_study_codelists", path)
    if spec is None or spec.loader is None:
        raise SpecError(f"{path}: cannot import the study's codelists module.")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as err:
        raise SpecError(f"{path}: cannot import the study's codelists module: {err}") from err
    return {
        cls._concept_id: cls
        for cls in vars(module).values()
        if isinstance(cls, type) and isinstance(getattr(cls, "_concept_id", None), str)
    }


def _count(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _package_mismatch(found: str, pinned: str) -> str:
    return (
        f"codelists.py was generated from {found}, but study_config.yaml pins {pinned}. "
        f"CT checks use the {found} terms. Run: fleet init ct --force"
    )


def _shown(path: Path, ctx: StudyContext) -> Path:
    """*path* relative to the study root when it is inside it."""
    try:
        return path.relative_to(ctx.study_root.resolve())
    except ValueError:
        return path


def _warn_once(message: str, *, stacklevel: int) -> None:
    if message not in _WARNED:
        _WARNED.add(message)
        warnings.warn(message, UserWarning, stacklevel=stacklevel + 1)


__all__ = [
    "CodelistsFile",
    "check_codelists",
    "read_codelists_file",
    "spec_codelists",
    "warn_if_class_stale",
]
