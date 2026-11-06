"""Fleet logging utilities for verb-layer diagnostics.

Verb-layer diagnostics (``inspect``, ``explain``, ``trail``, ``nodup``,
``validate`` report output) emit through the ``"fleet"`` logger
hierarchy instead of ``print()``, so batch runs can route, capture, or
silence them with the standard :mod:`logging` API::

    import logging

    logging.getLogger("fleet").setLevel(logging.WARNING)   # silence
    logging.getLogger("fleet").addHandler(my_file_handler)  # route

Default behaviour
-----------------
A ``NullHandler`` is attached to the ``"fleet"`` logger at import time.
The first time a diagnostic is emitted, Fleet lazily attaches a plain
``INFO``-level handler writing to ``sys.stdout`` — *unless* the user has
already attached their own handler to the ``"fleet"`` logger, or set the
logger to a level above ``INFO``.  A ``"fleet"`` logger with no level of
its own is set to ``INFO``, so a routed handler receives the diagnostics.
Rationale:
these verbs are explicitly invoked to be *read* (``.inspect()``,
``.trail()``, ``.nodup()``), so silent-by-default would break the
documented interactive UX; any user configuration takes precedence, and
:func:`disable_console` turns the default handler off entirely.
A program that configures the root logger with ``logging.basicConfig``
calls :func:`disable_console` to keep each line once.

The ``fleet`` command line also writes every ``WARNING`` of the ``"fleet"``
logger to ``sys.stderr`` (:func:`enable_cli_warnings`).

The default handler resolves ``sys.stdout`` at emit time (late binding),
so output redirection and pytest's ``capsys`` capture keep working.
"""

from __future__ import annotations

import logging
import sys

_FLEET_LOGGER = logging.getLogger("fleet")
_FLEET_LOGGER.addHandler(logging.NullHandler())


class _StdoutHandler(logging.StreamHandler):
    """Stream handler that resolves ``sys.stdout`` at emit time.

    Late binding keeps output visible under tools that swap
    ``sys.stdout`` after handler creation (pytest's ``capsys``,
    notebook kernels, output redirection).
    """

    def __init__(self) -> None:
        super().__init__(sys.stdout)

    @property
    def stream(self):  # noqa: D102 — property overriding base attribute
        return sys.stdout

    @stream.setter
    def stream(self, value) -> None:
        # Always sys.stdout — assignments from the base class are ignored.
        pass


_console_handler: _StdoutHandler | None = None
_cli_warning_handler: logging.Handler | None = None
_auto_checked = False


class _StderrHandler(logging.StreamHandler):
    """Stream handler that resolves ``sys.stderr`` at emit time."""

    def __init__(self) -> None:
        super().__init__(sys.stderr)

    @property
    def stream(self):  # noqa: D102 — property overriding base attribute
        return sys.stderr

    @stream.setter
    def stream(self, value) -> None:
        pass


def enable_cli_warnings() -> logging.Handler:
    """Write every ``WARNING`` of the ``fleet`` logger to ``sys.stderr``.

    The ``fleet`` command line calls it at start, so a skipped domain or a
    missing codelist reaches the user.  This handler does not count as a
    user handler: the stdout report of ``fleet validate`` still prints.

    Returns:
        logging.Handler: The active stderr handler.

    Examples:
        Show Fleet warnings on stderr in a script::

            from fleet.core.log import enable_cli_warnings

            enable_cli_warnings()
    """
    global _cli_warning_handler
    if _cli_warning_handler is None:
        _cli_warning_handler = _StderrHandler()
        _cli_warning_handler.setLevel(logging.WARNING)
        _cli_warning_handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        _FLEET_LOGGER.addHandler(_cli_warning_handler)
    return _cli_warning_handler


def get_logger(name: str = "fleet") -> logging.Logger:
    """Return a logger inside the ``fleet`` logger hierarchy.

    Args:
        name: Either a module ``__name__`` already under ``fleet.*`` or
            an arbitrary suffix that is attached as a child of the
            ``fleet`` logger.

    Returns:
        logging.Logger: The requested logger.

    Examples:
        Route Fleet diagnostics into an application logger config::

            from fleet.core.log import get_logger

            log = get_logger("fleet.sdtm")
            log.info("custom diagnostic")
    """
    if name == "fleet" or name.startswith("fleet."):
        return logging.getLogger(name)
    return _FLEET_LOGGER.getChild(name)


def enable_console(level: int = logging.INFO) -> logging.Handler:
    """Attach (or retune) the stdout console handler on the ``fleet`` logger.

    Args:
        level: Minimum level for the console handler (default ``INFO``).

    Returns:
        logging.Handler: The active console handler.

    Examples:
        Show Fleet diagnostics on stdout in a batch script::

            from fleet.core.log import enable_console

            enable_console()
    """
    global _console_handler
    if _console_handler is None:
        _console_handler = _StdoutHandler()
        _console_handler.setFormatter(logging.Formatter("%(message)s"))
        _FLEET_LOGGER.addHandler(_console_handler)
    _console_handler.setLevel(level)
    if _FLEET_LOGGER.level == logging.NOTSET or _FLEET_LOGGER.level > level:
        _FLEET_LOGGER.setLevel(level)
    return _console_handler


def disable_console() -> None:
    """Remove the default stdout console handler from the ``fleet`` logger.

    After this call, Fleet diagnostics only reach handlers the user has
    configured (or nothing, via the ``NullHandler``).

    Examples:
        Silence Fleet diagnostics in a batch run::

            from fleet.core.log import disable_console

            disable_console()
    """
    global _console_handler, _auto_checked
    if _console_handler is not None:
        _FLEET_LOGGER.removeHandler(_console_handler)
        _console_handler = None
    # Prevent the lazy default from re-attaching afterwards.
    _auto_checked = True


def _user_has_fleet_handlers() -> bool:
    """Return True if the user attached their own handler to ``fleet``."""
    return any(
        not isinstance(h, logging.NullHandler)
        and h is not _console_handler
        and h is not _cli_warning_handler
        for h in _FLEET_LOGGER.handlers
    )


def ensure_default_handler() -> None:
    """Attach the default stdout handler once, unless user-configured.

    Called by diagnostic verbs before emitting.  A ``fleet`` logger with no
    level gets ``INFO``.  No-op after the first call, when the user set the
    logger above ``INFO`` (silence), or when the user attached a handler
    to the ``fleet`` logger (route).
    """
    global _auto_checked
    if _auto_checked:
        return
    _auto_checked = True
    if _FLEET_LOGGER.level == logging.NOTSET:
        _FLEET_LOGGER.setLevel(logging.INFO)
    if _FLEET_LOGGER.level > logging.INFO or _user_has_fleet_handlers():
        return
    enable_console(logging.INFO)
