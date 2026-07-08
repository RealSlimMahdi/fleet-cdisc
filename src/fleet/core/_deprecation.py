"""Deprecation helpers for the verb/kwarg naming unification.

Two decorators drive every deprecation shim in Fleet:

* :func:`deprecated_kwargs` — accept legacy keyword spellings
  (``groups=`` → ``by=``, ``target_cols=`` → ``keep=``, ...) while
  emitting a ``FutureWarning``.
* :func:`deprecated_verb` — mark a whole verb as a deprecated alias of
  a canonical verb (``assign_no_ct`` → ``assign``).

Warnings are emitted **once per (call site, name) per session** so a
pipeline calling a legacy verb in a loop does not flood the console,
and test suites that exercise old spellings stay quiet after the first
hit.  ``reset_warning_registry()`` clears the registry (used by tests).
"""

from __future__ import annotations

import functools
import sys
import warnings
from typing import TYPE_CHECKING, ParamSpec, TypeVar

from fleet.core.exceptions import VerbUsageError

if TYPE_CHECKING:
    from collections.abc import Callable

P = ParamSpec("P")
R = TypeVar("R")

#: (call-site, deprecation-key) pairs that already warned this session.
_WARNED: set[tuple[str, str]] = set()


def reset_warning_registry() -> None:
    """Clear the once-per-session registry (test helper)."""
    _WARNED.clear()


def warn_deprecated(key: str, message: str, *, stacklevel: int = 3) -> None:
    """Emit *message* as a ``FutureWarning`` once per (call site, key).

    Args:
        key: Deduplication key, e.g. ``"flag.groups"`` or ``"assign_no_ct"``.
        message: The warning text.
        stacklevel: Passed to :func:`warnings.warn`; the default of 3
            points at the caller of the decorated verb.
    """
    try:
        frame = sys._getframe(stacklevel - 1)
        site = f"{frame.f_code.co_filename}:{frame.f_lineno}"
    except Exception:  # pragma: no cover — frame introspection best-effort
        site = "<unknown>"
    dedupe = (site, key)
    if dedupe in _WARNED:
        return
    _WARNED.add(dedupe)
    warnings.warn(message, FutureWarning, stacklevel=stacklevel)


def deprecated_kwargs(**aliases: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Accept legacy keyword spellings for a verb, with a ``FutureWarning``.

    Args:
        **aliases: ``old_name="new_name"`` pairs.  When a caller passes
            ``old_name=``, the value is forwarded as ``new_name=`` and a
            once-per-site ``FutureWarning`` is emitted.

    Returns:
        The decorator.

    Raises:
        VerbUsageError: At call time, when both the old and the new
            spelling are passed together.

    Examples:
        Accept ``groups=`` as a legacy alias of ``by=``::

            @deprecated_kwargs(groups="by")
            def seq(self, target, *, by=None, ...):
                ...
    """

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            for old, new in aliases.items():
                if old not in kwargs:
                    continue
                if new in kwargs:
                    raise VerbUsageError(
                        f"{fn.__name__}() got both '{old}=' (deprecated) and "
                        f"'{new}='. Pass only '{new}='."
                    )
                kwargs[new] = kwargs.pop(old)
                warn_deprecated(
                    f"{fn.__name__}.{old}",
                    f"{fn.__name__}(): keyword '{old}=' is deprecated; use '{new}=' instead.",
                )
            return fn(*args, **kwargs)

        wrapper.__fleet_kwarg_aliases__ = dict(aliases)  # type: ignore[attr-defined]
        return wrapper

    return decorator


def deprecated_verb(name: str, *, use: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Mark a verb as a deprecated alias of a canonical verb.

    The decorated method keeps working but emits a once-per-site
    ``FutureWarning`` pointing at the canonical spelling, and is marked
    so ``verbs()`` listings can skip it.

    Args:
        name: The deprecated verb name (for the warning key/message).
        use: The canonical verb (may include a hint such as
            ``"assign(..., value=)"``).

    Returns:
        The decorator.

    Examples:
        Keep ``hardcode_no_ct`` working as an ``assign`` alias::

            @deprecated_verb("hardcode_no_ct", use="assign(target, value=...)")
            def hardcode_no_ct(self, target, *, value):
                return self._assign_impl(target, value=value, verb="hardcode_no_ct")
    """

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            warn_deprecated(
                name,
                f".{name}() is deprecated; use .{use} instead. "
                "Run `python -m fleet.tools.migrate <files...> --write` to "
                "rewrite call sites automatically.",
            )
            return fn(*args, **kwargs)

        wrapper.__fleet_deprecated__ = use  # type: ignore[attr-defined]
        return wrapper

    return decorator
