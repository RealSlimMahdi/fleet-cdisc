"""CDISC Rules Engine installer and discovery.

Manages downloading, installing, and locating the official CDISC Rules Engine
executable. The engine bundle is stored in a platform-appropriate location and
is discovered automatically by the validation subsystem.

Install locations:

- **macOS / Linux:** ``~/.fleet/cdisc-rules-engine/core/core``
- **Windows:** ``%LOCALAPPDATA%\\fleet\\cdisc-rules-engine\\core\\core.exe``

Discovery order:

1. ``validation.engine_path`` from ``study_config.yaml`` (team-shared).
2. ``FLEET_RULES_ENGINE`` environment variable (explicit executable path).
3. Managed install from ``fleet install-engine``.
4. Legacy ``../cdisc-rules-engine/core.py`` (development fallback).

The study config comes first so that a team lead's pinned engine is not
overridden by a stale environment variable on one machine (ADR 0003).
"""

from __future__ import annotations

import os
import platform
import stat
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping

# GitHub repository for the CDISC Rules Engine releases.
_GITHUB_REPO = "cdisc-org/cdisc-rules-engine"
_RELEASES_API = f"https://api.github.com/repos/{_GITHUB_REPO}/releases/latest"


def _fleet_home() -> Path:
    """Return the Fleet data directory, respecting platform conventions."""
    if platform.system().lower() == "windows":
        # %LOCALAPPDATA%\fleet  (e.g. C:\Users\user\AppData\Local\fleet)
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local) / "fleet"
        return Path.home() / "AppData" / "Local" / "fleet"
    # macOS / Linux: ~/.fleet
    return Path.home() / ".fleet"


FLEET_HOME = _fleet_home()
ENGINE_DIR = FLEET_HOME / "cdisc-rules-engine"


def _platform_asset_keywords() -> list[str]:
    """Return keywords to match against GitHub release asset names for this platform."""
    system = platform.system().lower()
    if system == "windows":
        return ["windows"]
    if system == "darwin":
        machine = platform.machine().lower()
        if machine == "arm64":
            return ["mac-apple-silicon", "mac-arm"]
        return ["mac-intel", "mac-x86"]
    # Linux
    return ["ubuntu-latest", "ubuntu", "linux"]


def _engine_filename() -> str:
    """Return the local filename for the engine executable."""
    if platform.system().lower() == "windows":
        return "core.exe"
    return "core"


def engine_path() -> Path:
    """Return the path to the managed engine binary (may not exist yet)."""
    return ENGINE_DIR / "core" / _engine_filename()


def find_engine(
    configured: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[Path, Literal["study config", "environment", "default"]] | None:
    """Find the CDISC Rules Engine executable and say where it came from.

    Order: *configured* (``validation.engine_path``), then
    ``FLEET_RULES_ENGINE``, then the managed install, then the legacy
    sibling checkout.  A candidate that is not a file is skipped.

    Args:
        configured: The engine path from the study config, already resolved.
        environ: Environment to read ``FLEET_RULES_ENGINE`` from
            (default: ``os.environ``).

    Returns:
        ``(path, source)``, or ``None`` when no engine is found.
    """
    if configured is not None and configured.is_file():
        return configured, "study config"

    env = (os.environ if environ is None else environ).get("FLEET_RULES_ENGINE")
    if env and Path(env).is_file():
        return Path(env), "environment"

    managed = engine_path()
    if managed.is_file():
        return managed, "default"

    legacy = Path(__file__).parent.parent.parent.parent / "cdisc-rules-engine" / "core.py"
    if legacy.is_file():
        return legacy, "default"

    return None


def discover_engine(study_root: Path | None = None) -> Path | None:
    """Find the CDISC Rules Engine executable.

    Discovery order:

    1. ``validation.engine_path`` from ``study_config.yaml`` (if *study_root* given).
    2. ``FLEET_RULES_ENGINE`` environment variable.
    3. Managed install (``~/.fleet/cdisc-rules-engine/core/core``).
    4. Legacy ``../cdisc-rules-engine/core.py`` (development fallback).

    Args:
        study_root: Optional study root directory. When provided, the
            ``study_config.yaml`` is checked for a configured engine path.

    Returns:
        Path to the engine executable, or ``None`` if not found.
    """
    configured = _engine_path_from_study_config(study_root) if study_root is not None else None
    found = find_engine(configured)
    return found[0] if found is not None else None


def _engine_path_from_study_config(study_root: Path) -> Path | None:
    """Read validation.engine_path from study_config.yaml if it exists."""
    import yaml

    config_file = study_root / "study_config.yaml"
    if not config_file.is_file():
        return None

    try:
        with open(config_file) as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return None

    engine_str = (data.get("validation") or {}).get("engine_path")
    if not engine_str:
        return None

    p = Path(engine_str)
    # Resolve relative paths against the study root
    if not p.is_absolute():
        p = (study_root / p).resolve()
    return p


def install_engine(*, version: str = "latest", force: bool = False) -> Path:
    """Download the CDISC Rules Engine bundle from GitHub Releases.

    The CDISC Rules Engine is distributed as a PyInstaller ``--onedir`` bundle
    (a directory containing the executable plus all dependencies). The archive
    is extracted into ``~/.fleet/cdisc-rules-engine/`` (or the platform
    equivalent).

    Args:
        version: Release tag to download (default: ``"latest"``).
        force: Re-download even if the engine is already installed.

    Returns:
        Path to the installed executable.

    Raises:
        RuntimeError: If the download or installation fails.
    """
    import httpx

    dest = engine_path()
    if dest.is_file() and not force:
        print(f"Engine already installed at {dest}")
        print("Use --force to re-download.")
        return dest

    keywords = _platform_asset_keywords()

    # Resolve the release URL
    if version == "latest":
        release_url = _RELEASES_API
    else:
        tag = version if version.startswith("v") else f"v{version}"
        release_url = f"https://api.github.com/repos/{_GITHUB_REPO}/releases/tags/{tag}"

    print(f"Fetching release info from {_GITHUB_REPO} ({version})...")

    with httpx.Client(follow_redirects=True, timeout=30) as client:
        resp = client.get(release_url, headers={"Accept": "application/vnd.github+json"})
        if resp.status_code == 404:
            raise RuntimeError(
                f"Release '{version}' not found. "
                f"Check https://github.com/{_GITHUB_REPO}/releases for available versions."
            )
        resp.raise_for_status()
        release = resp.json()

    tag_name = release.get("tag_name", version)
    assets = release.get("assets", [])

    # Find the matching asset for this platform
    asset = _match_asset(assets, keywords)
    if asset is None:
        available = [a["name"] for a in assets]
        raise RuntimeError(
            f"No binary found for this platform (keywords: {keywords}).\n"
            f"Available assets: {available}\n"
            f"You may need to build from source or open an issue at "
            f"https://github.com/{_GITHUB_REPO}/issues"
        )

    asset_name = asset["name"]
    download_url = asset["browser_download_url"]
    print(f"Downloading {tag_name} ({asset_name})...")

    _download_and_install(download_url, asset_name)

    if not dest.is_file():
        raise RuntimeError(
            f"Installation succeeded but executable not found at {dest}.\n"
            f"Contents of {ENGINE_DIR}: {list(ENGINE_DIR.iterdir()) if ENGINE_DIR.exists() else 'N/A'}"
        )

    # Make executable on POSIX systems
    if platform.system().lower() != "windows":
        dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    print(f"Installed CDISC Rules Engine → {dest}")
    return dest


def _match_asset(assets: list[dict], keywords: list[str]) -> dict | None:
    """Find the best matching release asset for the given platform keywords.

    Tries keywords in priority order (e.g. ``mac-apple-silicon`` before
    ``mac-intel``) and skips checksum/signature files.
    """
    for kw in keywords:
        for asset in assets:
            name = asset["name"].lower()
            if kw in name and not name.endswith((".sha256", ".md5", ".sig")):
                return asset
    return None


def _download_and_install(url: str, asset_name: str) -> None:
    """Download and extract the full engine bundle into ENGINE_DIR.

    The CDISC Rules Engine is a PyInstaller ``--onedir`` bundle: the archive
    contains a ``core/`` directory with the executable and all its
    dependencies. We extract the entire directory into ENGINE_DIR.
    """
    import shutil

    import httpx

    # Download to a temp file
    suffix = "." + asset_name.rsplit(".", 1)[-1] if "." in asset_name else ""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    archive_path = Path(tmp.name)
    tmp.close()

    try:
        with httpx.Client(follow_redirects=True, timeout=300) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                downloaded = 0

                with open(archive_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = downloaded * 100 // total
                            mb = downloaded / (1024 * 1024)
                            total_mb = total / (1024 * 1024)
                            sys.stdout.write(f"\r  {mb:.1f} / {total_mb:.1f} MB ({pct}%)")
                            sys.stdout.flush()

                if total:
                    print()

        # Extract into a temp dir first, then move atomically
        with tempfile.TemporaryDirectory() as staging:
            staging_path = Path(staging)
            lower = asset_name.lower()

            if lower.endswith(".zip"):
                import zipfile

                with zipfile.ZipFile(archive_path) as zf:
                    zf.extractall(staging_path)
            elif lower.endswith((".tar.gz", ".tgz")):
                import tarfile

                with tarfile.open(archive_path, "r:gz") as tf:
                    tf.extractall(staging_path)  # noqa: S202
            else:
                raise RuntimeError(f"Unknown archive format: {asset_name}")

            # The archive typically contains a top-level "core/" directory.
            # Find it and move it into ENGINE_DIR.
            extracted_core = _find_bundle_dir(staging_path)
            if extracted_core is None:
                contents = [p.name for p in staging_path.iterdir()]
                raise RuntimeError(
                    f"Could not find 'core' directory in archive.\nTop-level contents: {contents}"
                )

            # Clean previous install
            target = ENGINE_DIR / "core"
            if target.exists():
                shutil.rmtree(target)
            ENGINE_DIR.mkdir(parents=True, exist_ok=True)
            shutil.move(str(extracted_core), str(target))

        print(f"Extracted {_count_files(target)} files into {target}")

    finally:
        archive_path.unlink(missing_ok=True)


def _find_bundle_dir(root: Path) -> Path | None:
    """Find the PyInstaller bundle directory (named 'core') in extracted contents."""
    # Direct child named "core"
    direct = root / "core"
    if direct.is_dir():
        return direct

    # Single top-level directory that contains a "core" executable
    children = list(root.iterdir())
    if len(children) == 1 and children[0].is_dir():
        return children[0]

    return None


def _count_files(path: Path) -> int:
    return sum(1 for _ in path.rglob("*") if _.is_file())


def uninstall_engine() -> bool:
    """Remove the managed engine installation.

    Returns:
        True if the installation was removed, False if nothing was installed.
    """
    import shutil

    target = ENGINE_DIR / "core"
    if target.exists():
        shutil.rmtree(target)
        print(f"Removed {target}")
        return True
    print("No managed engine installation found.")
    return False


def doctor(study_root: Path | None = None) -> dict[str, str]:
    """Check the health of the CDISC Rules Engine installation.

    Args:
        study_root: Optional study root directory; when given,
            ``validation.engine_path`` from its ``study_config.yaml`` is
            honoured during engine discovery.

    Returns:
        A dict of check names to status strings.
    """
    import subprocess

    checks: dict[str, str] = {}

    # Engine discovery
    found = discover_engine(study_root)
    if found is None:
        checks["engine"] = "NOT FOUND — run `fleet install-engine`"
        checks["version"] = "N/A"
        checks["pyreadstat"] = _check_pyreadstat()
        return checks

    checks["engine"] = str(found)

    # Check if it's the legacy Python script or a binary
    is_legacy = found.suffix == ".py"
    checks["type"] = "legacy (core.py)" if is_legacy else "binary"

    # Try running validate --help to confirm the binary works
    try:
        if is_legacy:
            cmd = ["python", str(found), "validate", "--help"]
            cwd = str(found.parent)
        else:
            cmd = [str(found), "validate", "--help"]
            cwd = None

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
            cwd=cwd,
        )
        if result.returncode == 0:
            checks["status"] = "OK — validate command available"
        else:
            stderr = (result.stderr.strip())[:200]
            checks["status"] = f"ERROR (exit {result.returncode}) — {stderr}"
    except FileNotFoundError:
        checks["status"] = "ERROR — executable not runnable"
    except subprocess.TimeoutExpired:
        checks["status"] = "ERROR — timed out"
    except Exception as exc:
        checks["status"] = f"ERROR — {exc}"

    # pyreadstat
    checks["pyreadstat"] = _check_pyreadstat()

    return checks


def _check_pyreadstat() -> str:
    try:
        import pyreadstat  # noqa: F401

        return "installed"
    except ImportError:
        return "NOT INSTALLED — run `uv sync --extra io`"
