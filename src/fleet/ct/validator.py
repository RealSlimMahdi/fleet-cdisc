"""CDISC Controlled Terminology validator with caching.

Provides a module-level singleton ``_validator`` for application-wide CT state.
Use ``get_validator()`` (or the re-exported ``fleet.get_validator``) to access it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from threading import Lock

from fleet.ct.loader import CTError, load_controlled_terminology

logger = logging.getLogger(__name__)


class CTValidator:
    """Validator for CDISC Controlled Terminology.

    Provides caching, lazy loading, and validation of SDTM/ADaM values
    against CDISC controlled terminology codelists.  Aliases are
    resolved **at load time**: registering ``{"SEX": "C66731"}`` rekeys
    a cache entry loaded under ``SEX`` to its NCI concept ID, so every
    lookup path (assign-family verbs, ``DatasetChecker``, direct API)
    reaches the same codelist by OID (``C66731``) or registered name
    (``SEX``) interchangeably — see :meth:`_resolve` for the resolution
    order.

    Usage:
        >>> from fleet import get_validator
        >>> validator = get_validator()
        >>> validator.load_ct_file("ct/cdisc_ct.yaml", aliases={"SEX": "C66731"})
        >>> validator.validate_value("SEX", "M")
        (True, "Value 'M' is valid for codelist 'C66731'")
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._ct_cache: dict[str, dict[str, str]] = {}
        self._codelist_aliases: dict[str, str] = {}
        self._ct_path: Path | None = None
        self._initialized: bool = False

    @classmethod
    def get_instance(cls) -> CTValidator:
        """Return the module-level singleton. Kept for backward compatibility."""
        return _validator

    def load_ct_file(
        self,
        ct_path: Path | str,
        aliases: dict[str, str] | None = None,
    ) -> None:
        """Load all codelists from a YAML or CSV file into the cache.

        Args:
            ct_path: Path or URL to the CT file (.yaml, .yml, .csv).
            aliases: Optional mapping of human-readable names to codelist codes,
                     e.g., {"SEX": "C66731", "RACE": "C74457"}.

        Raises:
            CTError: If the file cannot be loaded.
        """
        with self._lock:
            try:
                logger.info("Loading CT file from: %s", ct_path)
                self._ct_cache = load_controlled_terminology(ct_path)
                self._ct_path = Path(ct_path) if isinstance(ct_path, str) else ct_path
                self._initialized = True
                if aliases:
                    self._codelist_aliases.update(aliases)
                for alias, canonical in self._codelist_aliases.items():
                    self._normalise_alias(alias, canonical)
                logger.info("Loaded %d codelists from %s", len(self._ct_cache), ct_path)
            except CTError:
                raise

    def load_codelist(
        self,
        ct_path: Path | str,
        codelist_name: str,
        alias: str | None = None,
    ) -> None:
        """Lazy-load a single codelist from a file (skips if already cached).

        Args:
            ct_path: Path or URL to the CT file.
            codelist_name: Name or NCI code of codelist to load.
            alias: Optional human-readable name to register for this codelist.
        """
        with self._lock:
            if codelist_name in self._ct_cache:
                logger.debug("Codelist %s already cached", codelist_name)
                return
            try:
                data = load_controlled_terminology(ct_path, codelist_name)
                self._ct_cache.update(data)
                if alias:
                    self._codelist_aliases[alias] = codelist_name
                    self._normalise_alias(alias, codelist_name)
                logger.info("Lazy-loaded codelist: %s", codelist_name)
            except CTError as e:
                logger.warning(
                    "Could not load codelist '%s': %s. Validation will pass by default.",
                    codelist_name,
                    e,
                )

    def register_alias(self, alias: str, codelist_name: str) -> None:
        """Register a human-readable alias for a codelist code.

        Resolves immediately: when the cache was loaded keyed by the
        alias (e.g. a CT file using ``SEX:`` as the top-level key), the
        entry is rekeyed to the canonical concept ID so both spellings
        hit the same codelist.

        Args:
            alias: Human-readable name, e.g., "SEX".
            codelist_name: NCI codelist code, e.g., "C66731".
        """
        with self._lock:
            self._codelist_aliases[alias] = codelist_name
            self._normalise_alias(alias, codelist_name)

    def _normalise_alias(self, alias: str, canonical: str) -> None:
        """Rekey a cache entry stored under *alias* to *canonical*.

        Callers must hold ``self._lock``.  No-op when the canonical key
        already exists (the alias mapping alone then suffices).
        """
        if alias in self._ct_cache and canonical not in self._ct_cache:
            self._ct_cache[canonical] = self._ct_cache.pop(alias)

    def _resolve(self, codelist_name: str) -> str:
        """Resolve a codelist reference to its cache key.

        Resolution order (documented contract for both the verb path
        and the define/checker path):

        1. **Exact cache key** — the name as stored by the loaded CT
           file (post load-time normalisation this is the concept ID
           whenever an alias declared one).
        2. **Registered alias** — ``SEX`` → ``C66731`` via
           :meth:`register_alias` / the ``aliases=`` load parameter.
        3. **Reverse alias** — the name is the canonical target of a
           registered alias whose cache entry was never rekeyed
           (defensive; load-time normalisation makes this rare).

        Unresolvable names are returned unchanged so callers report the
        original spelling.
        """
        if codelist_name in self._ct_cache:
            return codelist_name
        canonical = self._codelist_aliases.get(codelist_name)
        if canonical is not None and canonical in self._ct_cache:
            return canonical
        for alias, target in self._codelist_aliases.items():
            if target == codelist_name and alias in self._ct_cache:
                return alias
        return codelist_name

    def validate_value(
        self,
        codelist_name: str,
        value: str | None,
        allow_null: bool = False,
    ) -> tuple[bool, str]:
        """Validate a single value against a codelist.

        Args:
            codelist_name: Codelist name or alias (e.g., "SEX" or "C66731").
            value: The value to validate (None is handled by allow_null).
            allow_null: Whether None is considered valid.

        Returns:
            Tuple (is_valid, message).
        """
        if value is None:
            if allow_null:
                return (True, f"Null value allowed for codelist '{codelist_name}'")
            return (False, f"Null value not allowed for codelist '{codelist_name}'")

        actual_cl = self._resolve(codelist_name)

        if actual_cl not in self._ct_cache:
            logger.warning(
                "Codelist '%s' not loaded — validation skipped for value '%s'",
                actual_cl,
                value,
            )
            return (True, f"Codelist '{actual_cl}' not loaded - validation skipped")

        codelist = self._ct_cache[actual_cl]
        if value in codelist:
            return (True, f"Value '{value}' is valid for codelist '{actual_cl}'")

        valid_str = ", ".join(sorted(codelist.keys()))
        return (
            False,
            f"Value '{value}' not in codelist '{actual_cl}'. Valid values: {valid_str}",
        )

    def has_codelist(self, codelist_name: str) -> bool:
        """Return True when a codelist (or alias) is loaded in the cache.

        Args:
            codelist_name: Codelist name, alias, or NCI concept ID.

        Returns:
            True if the codelist is available for validation.
        """
        actual_cl = self._resolve(codelist_name)
        return actual_cl in self._ct_cache

    def get_valid_values(self, codelist_name: str) -> list[str]:
        """Return all valid codes for a codelist.

        Args:
            codelist_name: Codelist name or alias.

        Returns:
            Sorted list of valid code strings, empty if codelist not loaded.
        """
        actual_cl = self._resolve(codelist_name)
        codelist = self._ct_cache.get(actual_cl, {})
        return sorted(codelist.keys())

    def get_cache_info(self) -> dict[str, object]:
        """Return diagnostic information about the current cache state."""
        return {
            "codelists_loaded": list(self._ct_cache.keys()),
            "aliases": dict(self._codelist_aliases),
            "ct_path": str(self._ct_path) if self._ct_path else None,
            "initialized": self._initialized,
        }

    def apply_ct_mapping(self, codelist_name: str, value: str | None) -> str | None:
        """Map an SDTM code to its decoded CT value (e.g., "M" → "Male").

        Returns the original value if the codelist is not loaded or value not found.
        """
        if value is None:
            return None
        actual_cl = self._resolve(codelist_name)
        codelist = self._ct_cache.get(actual_cl, {})
        return codelist.get(value, value)

    def get_decode_map(self, codelist_name: str) -> dict[str, str]:
        """Return a code-to-preferred-term mapping for a codelist.

        Each key is the submission value (e.g. ``"M"``) and the value is
        the preferred term / decode (e.g. ``"Male"``).  Returns an empty
        dict if the codelist is not loaded.

        Args:
            codelist_name: Codelist name, alias, or NCI concept ID.

        Returns:
            Dictionary mapping coded values to their preferred terms.
        """
        actual_cl = self._resolve(codelist_name)
        codelist = self._ct_cache.get(actual_cl, {})
        return {
            coded: info.get("preferred_term", coded) if isinstance(info, dict) else coded
            for coded, info in codelist.items()
        }


# Module-level singleton — created once when the module is first imported.
_validator = CTValidator()


def get_validator() -> CTValidator:
    """Return the module-level singleton CTValidator."""
    return _validator
