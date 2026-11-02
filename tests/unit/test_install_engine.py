"""``fleet install-engine`` installs the CORE release that Fleet is tested with.

No network: ``httpx.Client`` is a fake that records the release URL it gets,
and the download step only creates an empty executable file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleet import cli
from fleet.validation import engine as eng


@pytest.fixture
def fake_github(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace GitHub with a fake release and return the list of URLs asked for."""
    httpx = pytest.importorskip("httpx")
    monkeypatch.setattr(eng, "ENGINE_DIR", tmp_path / "cdisc-rules-engine")
    keyword = eng._platform_asset_keywords()[0]
    release = {
        "tag_name": "v0.15",
        "assets": [{"name": f"core-{keyword}.zip", "browser_download_url": "https://x"}],
    }
    urls: list[str] = []

    class Client:
        def __init__(self, **kwargs: object) -> None: ...
        def __enter__(self) -> Client:
            return self

        def __exit__(self, *exc: object) -> None: ...
        def get(self, url: str, **kwargs: object) -> object:
            urls.append(url)
            return httpx.Response(200, json=release, request=httpx.Request("GET", url))

    def download(url: str, asset_name: str) -> None:
        eng.engine_path().parent.mkdir(parents=True)
        eng.engine_path().touch()

    monkeypatch.setattr(httpx, "Client", Client)
    monkeypatch.setattr(eng, "_download_and_install", download)
    return urls


def test_default_tag_is_the_core_release_fleet_is_tested_with() -> None:
    # CORE 0.15.0 is published on GitHub under the tag "v0.15".
    assert eng.DEFAULT_ENGINE_TAG == "v0.15"


def test_install_engine_downloads_the_pinned_tag_by_default(fake_github: list[str]) -> None:
    eng.install_engine()

    assert fake_github == [
        "https://api.github.com/repos/cdisc-org/cdisc-rules-engine/releases/tags/v0.15"
    ]


def test_the_pinned_tag_gives_no_warning(
    fake_github: list[str], capsys: pytest.CaptureFixture
) -> None:
    eng.install_engine()

    assert "not tested" not in capsys.readouterr().err


def test_latest_downloads_the_newest_release_and_warns(
    fake_github: list[str], capsys: pytest.CaptureFixture
) -> None:
    eng.install_engine(version="latest")

    assert fake_github == [
        "https://api.github.com/repos/cdisc-org/cdisc-rules-engine/releases/latest"
    ]
    err = capsys.readouterr().err
    assert "Warning:" in err
    assert "not tested with Fleet" in err
    assert "v0.15" in err


def test_cli_default_version_is_the_pinned_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: dict[str, object] = {}

    def fake_install(*, version: str, force: bool) -> Path:
        asked["version"] = version
        return Path("core")

    monkeypatch.setattr(eng, "install_engine", fake_install)

    cli.main(["install-engine"])

    assert asked["version"] == eng.DEFAULT_ENGINE_TAG


def test_cli_accepts_latest(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: dict[str, object] = {}

    def fake_install(*, version: str, force: bool) -> Path:
        asked["version"] = version
        return Path("core")

    monkeypatch.setattr(eng, "install_engine", fake_install)

    cli.main(["install-engine", "--version", "latest"])

    assert asked["version"] == "latest"
