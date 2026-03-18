"""CDISC Library API client for downloading Controlled Terminology.

Wraps ``httpx`` to authenticate against the CDISC Library REST API and
retrieve CT packages, codelists, and individual term metadata.

Configuration is loaded from environment variables (or a ``.env`` file)
via ``pydantic-settings``:

- ``CDISC_API_KEY`` — required API key issued by CDISC.
- ``CDISC_BASE_URL`` — optional override (default: ``https://library.cdisc.org/api``).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from ..core.exceptions import CTError

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://library.cdisc.org/api"


@dataclass(frozen=True)
class CDISCClientConfig:
    """Configuration for the CDISC Library API client.

    Values are resolved in order:
    1. Explicit constructor arguments.
    2. Environment variables (``CDISC_API_KEY``, ``CDISC_BASE_URL``).
    3. A ``.env`` file in the working directory (loaded lazily via *dotenv*
       if the ``python-dotenv`` package is installed).

    Args:
        api_key: CDISC Library API key.
        base_url: Root URL for the CDISC Library API.
    """

    api_key: str = ""
    base_url: str = _DEFAULT_BASE_URL

    def __post_init__(self) -> None:
        # Allow env-vars / .env to fill in blanks.
        if not self.api_key:
            _try_load_dotenv()
            key = os.environ.get("CDISC_API_KEY", "")
            object.__setattr__(self, "api_key", key)
        if self.base_url == _DEFAULT_BASE_URL:
            env_url = os.environ.get("CDISC_BASE_URL", "")
            if env_url:
                object.__setattr__(self, "base_url", env_url.rstrip("/"))


def _try_load_dotenv() -> None:
    """Best-effort load of a ``.env`` file into ``os.environ``.

    Uses ``python-dotenv`` when available, otherwise falls back to a
    minimal stdlib parser that handles ``KEY=VALUE`` lines.
    """
    try:
        from dotenv import load_dotenv

        load_dotenv()
        return
    except ImportError:
        pass

    # Stdlib fallback: walk up to find .env
    env_path = Path.cwd() / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass
class CDISCClient:
    """HTTP client for the CDISC Library REST API.

    Args:
        config: Optional explicit configuration.  When omitted the client
            auto-discovers credentials from the environment / ``.env``.

    Examples:
        Fetch the SEX codelist::

            client = CDISCClient()
            terms = client.get_codelist("C66731")
    """

    config: CDISCClientConfig = field(default_factory=CDISCClientConfig)
    _http: httpx.Client = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.config.api_key:
            raise CTError(
                "CDISC API key is required. Set the CDISC_API_KEY environment "
                "variable, add it to a .env file, or pass it explicitly via "
                "CDISCClientConfig(api_key=...)."
            )
        self._http = httpx.Client(
            base_url=self.config.base_url,
            headers={
                "api-key": self.config.api_key,
                "Accept": "application/json",
            },
            timeout=30.0,
            follow_redirects=True,
        )

    # -- public helpers ------------------------------------------------- #

    def get_packages(self, product: str = "sdtmct") -> list[dict[str, Any]]:
        """List available CT packages for a product.

        Args:
            product: Product key recognised by the CDISC Library
                (e.g. ``"sdtmct"``, ``"adamct"``).

        Returns:
            List of package metadata dicts (keys vary by CDISC version).

        Raises:
            CTError: On network or authentication failure.
        """
        data = self._get(f"/mdr/ct/packages?type={product}")
        packages: list[dict[str, Any]] = data.get("_links", {}).get("packages", [])
        return packages

    def get_codelist(
        self,
        concept_id: str,
        *,
        package: str = "sdtmct-2023-12-15",
    ) -> dict[str, Any]:
        """Download a single codelist by NCI concept ID.

        Args:
            concept_id: NCI concept identifier (e.g. ``"C66731"``).
            package: CT package version string.

        Returns:
            Raw JSON dict from the CDISC Library containing
            ``submissionValue``, ``conceptId``, ``terms``, etc.

        Raises:
            CTError: On network, authentication, or 404 errors.
        """
        return self._get(f"/mdr/ct/packages/{package}/codelists/{concept_id}")

    # -- internals ------------------------------------------------------ #

    def _get(self, path: str) -> dict[str, Any]:
        """Perform an authenticated GET and return the JSON payload."""
        try:
            response = self._http.get(path)
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 401:
                raise CTError(
                    "CDISC API authentication failed (401). "
                    "Check your CDISC_API_KEY."
                ) from exc
            if status == 404:
                raise CTError(
                    f"Resource not found on CDISC Library: {path}"
                ) from exc
            raise CTError(
                f"CDISC API request failed ({status}): {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            raise CTError(
                f"Network error contacting CDISC Library: {exc}"
            ) from exc

    def close(self) -> None:
        """Close the underlying HTTP transport."""
        self._http.close()

    def __enter__(self) -> CDISCClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
