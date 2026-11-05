"""The CDISC Library client and ``fleet add-ct`` over a mocked HTTP transport (c1-844).

The answers in ``tests/fixtures/ct/cdisc_library_dm.json`` have the shape of
the CDISC Library API: the SDTMIG 3.4 dataset list, the DM dataset, and the
SEX codelist of sdtmct-2023-12-15.
"""

from __future__ import annotations

import functools
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from fleet import cli
from fleet.core.exceptions import CTError, CTNotFoundError
from fleet.ct.api import CDISCClient, CDISCClientConfig
from fleet.ct.generator import existing_concept_ids

LIBRARY = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "ct" / "cdisc_library_dm.json").read_text(
        encoding="utf-8"
    )
)


def _library(request: httpx.Request) -> httpx.Response:
    path = request.url.path.removeprefix("/api")
    if request.headers.get("api-key") != "test-key":
        return httpx.Response(401)
    if path not in LIBRARY:
        return httpx.Response(404)
    return httpx.Response(200, json=LIBRARY[path])


def _use_transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    client = functools.partial(httpx.Client, transport=httpx.MockTransport(handler))
    monkeypatch.setattr("fleet.ct.api.httpx.Client", client)


def _run(argv: list[str]) -> int:
    try:
        cli.main(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def test_add_ct_writes_the_codelists_of_the_domain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CDISC_API_KEY", "test-key")
    _use_transport(monkeypatch, _library)
    output = tmp_path / "codelists.py"

    assert _run(["add-ct", "--domains", "DM", "--ig", "3-4", "--output", str(output)]) == 0

    text = output.read_text(encoding="utf-8")
    assert existing_concept_ids(output) == {"C66731"}
    assert "sdtmct-2023-12-15" in text
    spec = importlib.util.spec_from_file_location("codelists_under_test", output)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert [module.SEX.F, module.SEX.M, module.SEX.U] == ["F", "M", "U"]
    assert "UNDIFFERENTIATED" in text


@pytest.mark.parametrize(
    ("response", "error", "match"),
    [
        (httpx.Response(401), CTError, r"authentication failed \(401\)"),
        (httpx.Response(404), CTNotFoundError, "Resource not found"),
        (httpx.Response(500), CTError, r"request failed \(500\)"),
        (
            httpx.Response(200, text="<html>Sign in</html>", headers={"content-type": "text/html"}),
            CTError,
            "not JSON",
        ),
    ],
    ids=["401", "404", "500", "html"],
)
def test_a_failed_request_raises_a_ct_error_with_the_reason(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response, error: type, match: str
) -> None:
    _use_transport(monkeypatch, lambda request: response)

    with CDISCClient(CDISCClientConfig(api_key="test-key")) as client:
        with pytest.raises(error, match=match):
            client.get_codelist("C66731")


def test_a_network_error_raises_a_ct_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _use_transport(monkeypatch, refuse)

    with CDISCClient(CDISCClientConfig(api_key="test-key")) as client:
        with pytest.raises(CTError, match="Network error"):
            client.get_codelist("C66731")


def test_the_client_sends_the_api_key_and_reads_the_codelist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_transport(monkeypatch, _library)

    with CDISCClient(CDISCClientConfig(api_key="test-key")) as client:
        codelist = client.get_codelist("C66731", package="sdtmct-2023-12-15")

    assert [t["submissionValue"] for t in codelist["terms"]] == ["F", "M", "U", "UNDIFFERENTIATED"]
