"""``fleet lsp`` and ``fleet mcp`` as separate processes over stdio (c1-852).

The in-process tests do not see a change in the wire output of pygls or the
MCP SDK. These tests start each server the way an editor does and speak its
protocol: LSP with Content-Length frames, MCP with one JSON message per line.
Each read has a 10 s timeout, so a hung server fails the test.
"""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
from collections.abc import Callable
from typing import IO, Any

import pytest

TIMEOUT = 10.0

BAD_ALGO_SPEC = """\
study:
  standard: SDTMIG
datasets:
  - name: DM
    variables:
      - name: SEX
        derivation:
          algorithm: asign
          source: sex
"""


def _start(*args: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-c", "from fleet.cli import main; main()", *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )


def _reader(read_one: Callable[[IO[bytes]], dict[str, Any] | None], out: IO[bytes]):
    """Read messages on a thread; ``next_message`` waits at most TIMEOUT seconds."""
    messages: queue.Queue[dict[str, Any] | None] = queue.Queue()

    def pump() -> None:
        while (message := read_one(out)) is not None:
            messages.put(message)
        messages.put(None)

    threading.Thread(target=pump, daemon=True).start()

    def next_message(match: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
        while True:
            try:
                message = messages.get(timeout=TIMEOUT)
            except queue.Empty:
                pytest.fail(f"no matching message within {TIMEOUT} s")
            if message is None:
                pytest.fail("the server closed stdout before the expected message")
            if match(message):
                return message

    return next_message


# ------------------------------------------------------------------ #
# LSP: Content-Length frames                                           #
# ------------------------------------------------------------------ #


def _lsp_send(proc: subprocess.Popen[bytes], message: dict[str, Any]) -> None:
    body = json.dumps({"jsonrpc": "2.0", **message}).encode("utf-8")
    proc.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
    proc.stdin.flush()


def _lsp_read(out: IO[bytes]) -> dict[str, Any] | None:
    length = None
    while True:
        line = out.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        name, _, value = line.decode("ascii").partition(":")
        if name.strip().lower() == "content-length":
            length = int(value.strip())
    return json.loads(out.read(length or 0))


def test_lsp_initialize_diagnostics_and_shutdown_over_stdio() -> None:
    pytest.importorskip("pygls", reason="lsp extra (pygls) not installed")
    proc = _start("lsp", "--stdio")
    try:
        next_message = _reader(_lsp_read, proc.stdout)

        _lsp_send(
            proc,
            {"id": 1, "method": "initialize", "params": {"processId": None, "capabilities": {}}},
        )
        init = next_message(lambda m: m.get("id") == 1)
        assert init["result"]["serverInfo"]["name"]
        assert init["result"]["serverInfo"]["version"]
        _lsp_send(proc, {"method": "initialized", "params": {}})

        uri = "file:///tmp/define.yaml"
        _lsp_send(
            proc,
            {
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "yaml",
                        "version": 1,
                        "text": BAD_ALGO_SPEC,
                    }
                },
            },
        )
        diagnostics = next_message(
            lambda m: (
                m.get("method") == "textDocument/publishDiagnostics" and m["params"]["uri"] == uri
            )
        )
        messages = [d["message"] for d in diagnostics["params"]["diagnostics"]]
        assert any("Did you mean 'assign'?" in message for message in messages)

        _lsp_send(proc, {"id": 2, "method": "shutdown"})
        assert next_message(lambda m: m.get("id") == 2)["result"] is None
        _lsp_send(proc, {"method": "exit"})
        assert proc.wait(timeout=TIMEOUT) == 0
    finally:
        proc.kill()


# ------------------------------------------------------------------ #
# MCP: one JSON message per line                                       #
# ------------------------------------------------------------------ #


def _mcp_send(proc: subprocess.Popen[bytes], message: dict[str, Any]) -> None:
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", **message}).encode("utf-8") + b"\n")
    proc.stdin.flush()


def _mcp_read(out: IO[bytes]) -> dict[str, Any] | None:
    line = out.readline()
    return json.loads(line) if line else None


def test_mcp_initialize_and_a_failing_tool_call_over_stdio() -> None:
    pytest.importorskip("mcp", reason="mcp extra not installed")
    proc = _start("mcp", "--stdio")
    try:
        next_message = _reader(_mcp_read, proc.stdout)

        _mcp_send(
            proc,
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "fleet-tests", "version": "0"},
                },
            },
        )
        init = next_message(lambda m: m.get("id") == 1)
        assert init["result"]["serverInfo"]["name"]
        _mcp_send(proc, {"method": "notifications/initialized"})

        _mcp_send(
            proc,
            {
                "id": 2,
                "method": "tools/call",
                "params": {"name": "fleet_ct_terms", "arguments": {"codelist": "NOPE_CL"}},
            },
        )
        call = next_message(lambda m: m.get("id") == 2)
        assert call["result"]["isError"] is True
        text = " ".join(part.get("text", "") for part in call["result"]["content"])
        assert "codelist 'NOPE_CL' is not loaded" in text

        proc.stdin.close()
        assert proc.wait(timeout=TIMEOUT) == 0
    finally:
        proc.kill()
