"""The study's generated ``codelists.py``: the terms both CT notations check against.

The inline ``assign("AESEV", source="ae_severity", ct=AESEV)`` validates
against the class it is given.  :func:`spec_codelists` gives ``from_spec``
the same classes for its ``ct:`` IDs, read from the study's
``codelists.py``, so both notations of one step check the same terms.

Because both then trust the file, :func:`check_codelists` compares it with
the study:

a. a CT package it was generated from is not pinned in ``study_config.yaml``
   (``ct.package``, ``ct.adam_package``);
b. its classes name two packages of one product (two SDTM CT dates);
c. a ``codelist:`` or ``ct:`` ID of a ``define.yaml`` has no class
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
from pathlib import Path
from typing import TYPE_CHECKING

from fleet.core.exceptions import SpecError
from fleet.core.study_context import (
    DEFAULT_ADAM_CT,
    StudyConfigError,
    find_study_config,
    load_study_context,
)
from fleet.ct.generator import codelist_references, extract_concept_ids

if TYPE_CHECKING:
    from fleet.core.study_context import StudyContext

#: The CT package in a CDISC Library Browser URL (``.../packages/sdtmct-2023-12-15/...``).
_URL_PACKAGE = re.compile(r"/packages/([^/]+)/")

#: Problems already reported in this process; each one warns once.
_WARNED: set[str] = set()


def load_codelists(path: Path) -> tuple[tuple[str, ...], dict[str, type]]:
    """Import a generated ``codelists.py``: the CT packages it came from, and its classes.

    The packages are the ``__ct_packages__`` marker (an SDTM and an ADaM
    package) or the ``__ct_package__`` marker.  A file generated before the
    markers existed gives the one package the ``_cdisc_url`` of its classes
    names.  The module is not added to ``sys.modules``.

    Args:
        path: The ``codelists.py`` file.

    Returns:
        tuple[tuple[str, ...], dict[str, type]]: The packages (empty when
            unknown) and the classes by ``_concept_id``.

    Raises:
        SpecError: When the file cannot be imported.

    Examples:
        The packages of a study's codelists, and its AESEV class::

            from fleet.ct.study_codelists import load_codelists

            packages, classes = load_codelists(Path("metadata/sdtm/codelists.py"))
            AESEV = classes["C66769"]
    """
    spec = importlib.util.spec_from_file_location("_fleet_study_codelists", path)
    if spec is None or spec.loader is None:
        raise SpecError(f"{path}: cannot import the study's codelists module.")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as err:
        raise SpecError(f"{path}: cannot import the study's codelists module: {err}") from err
    classes = {
        cls._concept_id: cls
        for cls in vars(module).values()
        if isinstance(cls, type) and isinstance(getattr(cls, "_concept_id", None), str)
    }
    packages = getattr(module, "__ct_packages__", None)
    if packages is None:
        single = getattr(module, "__ct_package__", None)
        found = {_class_package(cls) for cls in classes.values()} - {None}
        packages = (single,) if single else (tuple(found) if len(found) == 1 else ())
    return tuple(packages), classes


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

    Raises:
        SpecError: When ``codelists.py`` cannot be imported.

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
            f"{path} does not exist. Run: fleet init ct"
        ]

    packages, classes = load_codelists(path)
    problems: list[str] = []
    pins = ctx.config.ct.pins
    if any(p not in pins for p in packages):
        problems.append(_package_mismatch(", ".join(packages), ", ".join(pins)))
    counts = Counter(p for p in map(_class_package, classes.values()) if p)
    products = Counter(p.split("-", 1)[0] for p in counts)
    if any(n > 1 for n in products.values()):
        mix = [f"{p} ({_count(n, 'class', 'classes')})" for p, n in counts.most_common()]
        problems.append(
            f"codelists.py mixes {', '.join(mix[:-1])} and {mix[-1]}. Run: fleet init ct --force"
        )
    if references:
        for standard, define in defines.items():
            for dataset, variable, concept_id in codelist_references(define):
                if concept_id in classes:
                    continue
                problems.append(
                    f"{dataset}.{variable} references codelist {concept_id}, "
                    f"which is not in codelists.py{_missing_fix(ctx, standard, dataset)}"
                )
    return list(dict.fromkeys(problems))


def spec_codelists(define_path: Path) -> dict[str, type]:
    """Return the codelist classes of the study a ``define.yaml`` belongs to, by concept ID.

    The study is the first ``study_config.yaml`` above the folder of
    *define_path*.  Each problem of checks a, b and d warns once per
    process, at the caller of ``from_spec`` (see :func:`check_codelists`).
    Values are still checked against the terms in the file: the warning
    names the fix, and CORE stays the authority.

    Args:
        define_path: The ``define.yaml`` that ``from_spec`` runs.

    Returns:
        dict[str, type]: The classes of the study's ``codelists.py`` by
            ``_concept_id``; empty outside a study or without the file.

    Raises:
        SpecError: When ``codelists.py`` exists but cannot be imported.

    Examples:
        Resolve ``ct: C66769`` the way ``from_spec`` does::

            from fleet.ct.study_codelists import spec_codelists

            AESEV = spec_codelists(Path("metadata/sdtm/define.yaml"))["C66769"]
            ae = raw.sdtm.assign("AESEV", source="ae_severity", ct=AESEV).to_frame()
    """
    ctx = _study(define_path.resolve().parent)
    if ctx is None:
        return {}
    for problem in check_codelists(ctx):
        _warn_once(problem, stacklevel=4)  # _warn_once, spec_codelists, from_spec, caller
    path = ctx.codelists_file
    return load_codelists(path)[1] if path.is_file() else {}


def warn_if_class_stale(cls: type) -> None:
    """Warn once when a codelist class comes from another CT package than its study pins.

    The study is the first ``study_config.yaml`` above the module that
    defines *cls*, never above the working directory.  The warning has the
    text of check a (see :func:`check_codelists`) and points at the caller
    of ``assign``.  A class whose ``_cdisc_url`` names no package, or that
    lives outside a study, is not checked.

    Args:
        cls: A generated codelist class, as passed to ``assign(ct=...)``.

    Examples:
        The check ``assign`` runs on its ``ct=`` class::

            from codelists import AESEV
            from fleet.ct.study_codelists import warn_if_class_stale

            warn_if_class_stale(AESEV)
            ae = raw.sdtm.assign("AESEV", source="ae_severity", ct=AESEV).to_frame()
    """
    package = _class_package(cls)
    module_file = getattr(sys.modules.get(cls.__module__), "__file__", None)
    if package is None or not module_file:
        return
    ctx = _study(Path(module_file).resolve().parent)
    if ctx is not None and package not in ctx.config.ct.pins:
        # _warn_once, warn_if_class_stale, _assign_impl, assign, caller
        _warn_once(_package_mismatch(package, ", ".join(ctx.config.ct.pins)), stacklevel=5)


def _study(folder: Path) -> StudyContext | None:
    """The study of the first ``study_config.yaml`` above *folder*; ``None`` outside a study."""
    config = find_study_config(folder)
    if config is None:
        return None
    try:
        return load_study_context(config)
    except StudyConfigError:
        return None


def _class_package(cls: type) -> str | None:
    """The CT package the ``_cdisc_url`` of a codelist class names, if any."""
    url = getattr(cls, "_cdisc_url", None)
    found = _URL_PACKAGE.search(url) if isinstance(url, str) else None
    return found[1] if found else None


def _count(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _missing_fix(ctx: StudyContext, standard: str, dataset: str) -> str:
    """The end of the check c message: the fix that can add the codelist."""
    if standard == "sdtm":
        return f". Run: fleet add-ct --domains {dataset}"
    if ctx.config.ct.adam_package is None:
        # fleet add-ct reads the SDTM IG; an ADaM-only codelist (DTYPE) needs the ADaM pin.
        return (
            ", and study_config.yaml pins no ADaM CT package. Set ct.adam_package "
            f"(for example {DEFAULT_ADAM_CT}), then run: fleet init ct --force"
        )
    return f". Run: fleet init ct --force (it looks in {', '.join(ctx.config.ct.pins)})"


def _package_mismatch(found: str, pinned: str) -> str:
    return (
        f"codelists.py was generated from {found}, but study_config.yaml pins {pinned}. "
        f"CT checks use the {found} terms. Run: fleet init ct --force"
    )


def _warn_once(message: str, *, stacklevel: int) -> None:
    """Warn unless this process already did; *stacklevel* as in :func:`warnings.warn`."""
    if message not in _WARNED:
        _WARNED.add(message)
        warnings.warn(message, UserWarning, stacklevel=stacklevel)


__all__ = [
    "check_codelists",
    "load_codelists",
    "spec_codelists",
    "warn_if_class_stale",
]
