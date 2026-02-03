# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: MIT
"""Tests for RShell server script."""

import importlib.util
import runpy
from pathlib import Path

import pytest


SERVER_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "mfd_connect" / "rshell_server.py"


def _load_server_module(module_name: str = "test_rs_server"):
    spec = importlib.util.spec_from_file_location(module_name, SERVER_SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestRShellServerScript:
    """Tests for RShell server script behavior."""

    @pytest.fixture()
    def server_module(self):
        module = _load_server_module()
        module.output_queue.clear()
        module.command_dict_queue.clear()
        module.clients.clear()
        return module

    def test_get_output_success(self, server_module):
        command_id = "cmd1"
        expected = server_module.output_object(output="hello", rc=0)
        server_module.output_queue[command_id] = expected

        result = server_module.get_output(command_id, timeout=0)

        assert result == expected

    def test_get_output_timeout(self, server_module):
        with pytest.raises(TimeoutError, match="Command timed out"):
            server_module.get_output("missing", timeout=-5)

    def test_get_output_waits_then_returns(self, server_module, monkeypatch):
        class _QueueProbe:
            def __init__(self):
                self.count = 0

            def get(self, _command_id, _default=None):
                self.count += 1
                if self.count == 1:
                    return None
                return server_module.output_object(output="later", rc=4)

        monkeypatch.setattr(server_module, "output_queue", _QueueProbe())
        monkeypatch.setattr(server_module.time, "sleep", lambda _x: None)

        result = server_module.get_output("cmd-later", timeout=0)

        assert result.output == "later"
        assert result.rc == 4

    def test_add_command_to_queue_new_and_existing_queue(self, server_module):
        first_id = server_module.add_command_to_queue("echo 1", "10.0.0.1")
        second_id = server_module.add_command_to_queue("echo 2", "10.0.0.1")

        assert first_id != second_id
        queue_obj = server_module.command_dict_queue["10.0.0.1"]
        assert queue_obj.qsize() == 2

    def test_health_check_endpoint(self, server_module):
        client = server_module.app.test_client()

        response_not_connected = client.get("/health/10.0.0.1")
        assert response_not_connected.status_code == 503

        server_module.clients.append("10.0.0.1")
        response_connected = client.get("/health/10.0.0.1")
        assert response_connected.status_code == 200
        assert response_connected.get_data(as_text=True) == "OK"

    def test_get_command_to_execute_endpoint(self, server_module):
        client = server_module.app.test_client()

        response_empty = client.get("/getCommandToExecute", environ_base={"REMOTE_ADDR": "1.2.3.4"})
        assert response_empty.status_code == 204
        assert "1.2.3.4" in server_module.clients

        command_id = server_module.add_command_to_queue("echo hi", "1.2.3.4")
        response_with_command = client.get("/getCommandToExecute", environ_base={"REMOTE_ADDR": "1.2.3.4"})

        assert response_with_command.status_code == 200
        assert response_with_command.get_data(as_text=True) == "echo hi"
        assert response_with_command.headers["CommandID"] == command_id

    def test_post_exception_endpoint(self, server_module):
        client = server_module.app.test_client()
        response = client.post("/exception", data=b"boom", headers={"CommandID": "cid-1"})

        assert response.status_code == 200
        assert server_module.output_queue["cid-1"].output == "boom"
        assert server_module.output_queue["cid-1"].rc == -1

    def test_execute_command_endpoint_paths(self, server_module, monkeypatch):
        client = server_module.app.test_client()

        response_missing = client.post("/execute_command", data={"timeout": "5", "ip": "1.1.1.1"})
        assert response_missing.status_code == 400

        response_end = client.post("/execute_command", data={"command": "end", "timeout": "5", "ip": "1.1.1.1"})
        assert response_end.status_code == 200
        assert response_end.get_data(as_text=True) == "No more commands available to run"

        response_reset = client.post(
            "/execute_command",
            data={"command": "reset -c", "timeout": "5", "ip": "1.1.1.1"},
        )
        assert response_reset.status_code == 200
        assert response_reset.get_data(as_text=True) == "Reset command sent"

        monkeypatch.setattr(
            server_module,
            "get_output",
            lambda _id, _timeout: server_module.output_object(output="result-output", rc=9),
        )
        response_normal = client.post(
            "/execute_command",
            data={"command": "uname -a", "timeout": "7", "ip": "1.1.1.1"},
        )

        assert response_normal.status_code == 200
        assert response_normal.get_data(as_text=True) == "result-output"
        assert response_normal.headers["rc"] == "9"
        assert response_normal.headers["Content-type"].startswith("text/plain")
        assert response_normal.headers["CommandID"]

    def test_disconnect_client_endpoint(self, server_module):
        client = server_module.app.test_client()
        server_module.clients.append("2.2.2.2")

        response_existing = client.post("/disconnect_client/2.2.2.2")
        assert response_existing.status_code == 200
        assert "2.2.2.2" not in server_module.clients

        response_missing = client.post("/disconnect_client/8.8.8.8")
        assert response_missing.status_code == 200

    def test_post_result_endpoint(self, server_module):
        client = server_module.app.test_client()

        response_default_rc = client.post("/post_result", data=b"output-a", headers={"CommandID": "cmd-a"})
        assert response_default_rc.status_code == 200
        assert server_module.output_queue["cmd-a"].output == "output-a"
        assert server_module.output_queue["cmd-a"].rc == -1

        response_given_rc = client.post(
            "/post_result",
            data=b"output-b",
            headers={"CommandID": "cmd-b", "rc": "3"},
        )
        assert response_given_rc.status_code == 200
        assert server_module.output_queue["cmd-b"].output == "output-b"
        assert server_module.output_queue["cmd-b"].rc == 3

    def test_main_block_starts_flask(self, monkeypatch):
        captured = {}

        def _fake_run(self, host, port):
            captured["host"] = host
            captured["port"] = port

        monkeypatch.setattr("flask.app.Flask.run", _fake_run)
        runpy.run_path(str(SERVER_SCRIPT_PATH), run_name="__main__")

        assert captured == {"host": "0.0.0.0", "port": 80}
