# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: MIT
"""Tests for RShell client script."""

import runpy
import sys
import types
from pathlib import Path
from unittest.mock import mock_open

import pytest


CLIENT_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "mfd_connect" / "rshell_client.py"


class _FakeResponse:
    def __init__(self, status: int, body: bytes, command_id: str):
        self.status = status
        self._body = body
        self._command_id = command_id

    def getheader(self, key: str):
        if key == "CommandID":
            return self._command_id
        return None

    def read(self):
        return self._body


class _FakeHTTPConnection:
    scenarios = []
    instances = []

    def __init__(self, host, source_address=None):
        self.host = host
        self.source_address = source_address
        self.requests = []
        self.closed = False
        self.scenario = _FakeHTTPConnection.scenarios.pop(0)
        _FakeHTTPConnection.instances.append(self)

    def request(self, method, path, body=None, headers=None):
        if method == "POST" and path == "post_result" and self.scenario.get("raise_post_result"):
            raise RuntimeError("post-result-failed")
        self.requests.append({"method": method, "path": path, "body": body, "headers": headers or {}})

    def getresponse(self):
        return _FakeResponse(
            status=self.scenario.get("status", 204),
            body=self.scenario.get("body", b""),
            command_id=self.scenario.get("command_id", "cid"),
        )

    def close(self):
        self.closed = True


def _run_client(monkeypatch, scenarios, argv, *, os_name="posix", with_httplib=False, file_content="file-output"):
    _FakeHTTPConnection.scenarios = list(scenarios)
    _FakeHTTPConnection.instances = []

    import http.client as http_client_module
    import os
    import time
    import builtins

    monkeypatch.setattr(http_client_module, "HTTPConnection", _FakeHTTPConnection)
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(os, "name", os_name, raising=False)

    system_calls = []

    def _fake_system(cmd):
        system_calls.append(cmd)
        return 0

    monkeypatch.setattr(os, "system", _fake_system)

    time_values = iter(range(0, 10000, 3))
    monkeypatch.setattr(time, "time", lambda: next(time_values))

    m_open = mock_open(read_data=file_content)
    monkeypatch.setattr(builtins, "open", m_open)

    monkeypatch.setattr(builtins, "exit", lambda code=0: (_ for _ in ()).throw(SystemExit(code)))

    if with_httplib:
        httplib_stub = types.ModuleType("httplib")
        httplib_stub.HTTPConnection = _FakeHTTPConnection
        monkeypatch.setitem(sys.modules, "httplib", httplib_stub)
    else:
        if "httplib" in sys.modules:
            monkeypatch.delitem(sys.modules, "httplib", raising=False)

    with pytest.raises(SystemExit):
        runpy.run_path(str(CLIENT_SCRIPT_PATH), run_name="__main__")

    return {
        "instances": _FakeHTTPConnection.instances,
        "system_calls": system_calls,
        "open_mock": m_open,
    }


class TestRShellClientScript:
    """Tests for RShell client script behavior."""

    def test_client_flow_with_no_command_then_end(self, monkeypatch):
        result = _run_client(
            monkeypatch,
            scenarios=[
                {"status": 204, "body": b"", "command_id": "cid-none"},
                {"status": 200, "body": b"end", "command_id": "cid-end"},
            ],
            argv=["rshell_client.py", "127.0.0.1", "10.0.0.2"],
        )

        instances = result["instances"]
        assert len(instances) == 2
        assert instances[0].source_address == ("10.0.0.2", 80)
        assert instances[1].source_address == ("10.0.0.2", 80)
        assert instances[0].closed is True
        assert instances[1].closed is True

    def test_client_echo_flow_posts_result(self, monkeypatch):
        result = _run_client(
            monkeypatch,
            scenarios=[
                {"status": 200, "body": b"echo hello", "command_id": "cid-echo"},
                {"status": 200, "body": b"end", "command_id": "cid-end"},
            ],
            argv=["rshell_client.py", "127.0.0.1"],
            with_httplib=True,
        )

        first_requests = result["instances"][0].requests
        assert first_requests[0]["method"] == "GET"
        assert first_requests[0]["path"] == "getCommandToExecute"
        assert first_requests[1]["method"] == "POST"
        assert first_requests[1]["path"] == "post_result"
        assert first_requests[1]["body"] == ""
        assert first_requests[1]["headers"]["CommandID"] == "cid-echo"
        assert "echo hello" in result["system_calls"]

    def test_client_non_echo_flow_edk2_reads_file_and_deletes(self, monkeypatch):
        result = _run_client(
            monkeypatch,
            scenarios=[
                {"status": 200, "body": b"ls -la", "command_id": "cid-ls"},
                {"status": 200, "body": b"end", "command_id": "cid-end"},
            ],
            argv=["rshell_client.py", "127.0.0.1"],
            os_name="edk2",
            file_content="non-echo-output",
        )

        result["open_mock"].assert_called_once_with("ls.txt", "r", encoding="utf-16")
        first_requests = result["instances"][0].requests
        assert first_requests[1]["path"] == "post_result"
        assert first_requests[1]["body"] == "non-echo-output"
        assert "ls -la > ls.txt" in result["system_calls"]
        assert "del ls.txt" in result["system_calls"]

    def test_client_reset_flow_executes_reset_and_exits(self, monkeypatch):
        result = _run_client(
            monkeypatch,
            scenarios=[
                {"status": 200, "body": b"reset -c", "command_id": "cid-reset"},
            ],
            argv=["rshell_client.py", "127.0.0.1"],
        )

        assert "reset -c" in result["system_calls"]
        assert result["instances"][0].closed is True

    def test_client_post_result_exception_falls_back_to_exception_endpoint(self, monkeypatch):
        result = _run_client(
            monkeypatch,
            scenarios=[
                {"status": 200, "body": b"uname -a", "command_id": "cid-uname", "raise_post_result": True},
                {"status": 200, "body": b"end", "command_id": "cid-end"},
            ],
            argv=["rshell_client.py", "127.0.0.1"],
        )

        first_requests = result["instances"][0].requests
        assert first_requests[-1]["path"] == "exception"
        assert first_requests[-1]["headers"]["CommandID"] == "cid-uname"
        assert "post-result-failed" in first_requests[-1]["body"]

    def test_client_non_echo_uses_utf8_when_not_edk2(self, monkeypatch):
        result = _run_client(
            monkeypatch,
            scenarios=[
                {"status": 200, "body": b"dir", "command_id": "cid-dir"},
                {"status": 200, "body": b"end", "command_id": "cid-end"},
            ],
            argv=["rshell_client.py", "127.0.0.1"],
            os_name="posix",
            file_content="utf8-output",
        )

        result["open_mock"].assert_called_once_with("dir.txt", "r", encoding="utf-8")
