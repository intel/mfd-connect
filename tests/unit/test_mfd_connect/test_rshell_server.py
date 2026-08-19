# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: MIT
"""Tests for RShell server script."""

import importlib.util
import runpy
import sys
import threading
import time
from pathlib import Path

import pytest


SERVER_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "mfd_connect" / "rshell_server" / "rshell_server.py"


def _load_server_module(module_name: str = "test_rs_server"):
    """Load the rshell_server module dynamically for testing."""
    spec = importlib.util.spec_from_file_location(module_name, SERVER_SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    sys.modules[module_name] = module
    return module


class TestRShellServerScript:
    """Tests for RShell server script behavior."""

    @pytest.fixture()
    def server_module(self):
        module = _load_server_module()
        module.output_queue.clear()
        module.output_queue_timestamps.clear()
        module.abandoned_command_ids.clear()
        module.command_dict_queue.clear()
        module.clients.clear()
        module.client_last_seen.clear()
        module.client_running_command.clear()
        return module

    def test_get_output_success(self, server_module):
        command_id = "cmd1"
        expected = server_module.output_object(output="hello", rc=0)
        server_module.output_queue[command_id] = expected
        server_module.output_queue_timestamps[command_id] = 123.0

        result = server_module.get_output(command_id, timeout=0)

        assert result == expected
        assert command_id not in server_module.output_queue
        assert command_id not in server_module.output_queue_timestamps

    def test_get_output_timeout(self, server_module):
        with pytest.raises(TimeoutError, match="Command timed out"):
            server_module.get_output("missing", timeout=-5)

    def test_get_output_timeout_marks_command_as_abandoned(self, server_module):
        """A caller that gives up must mark its command so it is not executed/stored later."""
        with pytest.raises(TimeoutError):
            server_module.get_output("gone", timeout=-5)

        assert "gone" in server_module.abandoned_command_ids

    def test_get_output_is_woken_up_by_posted_result(self, server_module):
        """Waiting is event driven - the waiter returns as soon as the result is stored."""

        def _post_later():
            time.sleep(0.1)
            server_module._store_output("cmd-later", "later", 4)

        threading.Thread(target=_post_later, daemon=True).start()

        started = time.monotonic()
        result = server_module.get_output("cmd-later", timeout=10)
        elapsed = time.monotonic() - started

        assert result.output == "later"
        assert result.rc == 4
        assert elapsed < 2, "waiter should be notified instead of polling"

    def test_store_output_drops_result_of_abandoned_command(self, server_module):
        """Late results must not be kept in memory once nobody waits for them anymore."""
        server_module._abandon_command("dead-cmd")

        stored = server_module._store_output("dead-cmd", "late output", 0)

        assert stored is False
        assert "dead-cmd" not in server_module.output_queue
        assert "dead-cmd" not in server_module.output_queue_timestamps
        assert "dead-cmd" not in server_module.abandoned_command_ids

    def test_add_command_to_queue_new_and_existing_queue(self, server_module):
        first_id = server_module.add_command_to_queue("echo 1", "10.0.0.1")
        second_id = server_module.add_command_to_queue("echo 2", "10.0.0.1")

        assert first_id != second_id
        queue_obj = server_module.command_dict_queue["10.0.0.1"]
        assert queue_obj.qsize() == 2

    def test_add_command_to_queue_is_bounded(self, server_module):
        """Per-client queue must not grow without limits."""
        limit = server_module.MAX_PENDING_COMMANDS_PER_CLIENT
        for index in range(limit + 25):
            server_module.add_command_to_queue(f"echo {index}", "10.0.0.9")

        assert server_module.command_dict_queue["10.0.0.9"].qsize() <= limit

    def test_health_check_endpoint(self, server_module):
        client = server_module.app.test_client()

        response_not_connected = client.get("/health/10.0.0.1")
        assert response_not_connected.status_code == 503

        server_module.clients.append("10.0.0.1")
        server_module.client_last_seen["10.0.0.1"] = time.monotonic()
        response_connected = client.get("/health/10.0.0.1")
        assert response_connected.status_code == 200
        assert response_connected.get_data(as_text=True) == "OK"

    def test_health_check_reports_client_that_stopped_polling(self, server_module):
        """A client that was seen once but went silent must not look healthy forever."""
        client = server_module.app.test_client()
        server_module.clients.append("10.0.0.1")
        server_module.client_last_seen["10.0.0.1"] = (
            time.monotonic() - server_module.CLIENT_LIVENESS_TIMEOUT_SECONDS - 10
        )

        response = client.get("/health/10.0.0.1")

        assert response.status_code == 503
        assert "stopped polling" in response.get_data(as_text=True)

    def test_health_check_requires_a_poll_before_reporting_healthy(self, server_module):
        """Being present in 'clients' is not enough - the client has to have polled."""
        client = server_module.app.test_client()
        server_module.clients.append("10.0.0.1")

        assert client.get("/health/10.0.0.1").status_code == 503

    def test_poll_refreshes_liveness_and_tracks_running_command(self, server_module):
        client = server_module.app.test_client()
        command_id = server_module.add_command_to_queue("FS0:\\Tools\\nvmupdate64e.efi /i /l", "1.2.3.4")

        client.get("/getCommandToExecute", environ_base={"REMOTE_ADDR": "1.2.3.4"})

        assert "1.2.3.4" in server_module.client_last_seen
        running = server_module.client_running_command["1.2.3.4"]
        assert running.command_id == command_id
        assert running.command == "FS0:\\Tools\\nvmupdate64e.efi /i /l"

    def test_posting_result_clears_running_command(self, server_module):
        client = server_module.app.test_client()
        command_id = server_module.add_command_to_queue("ver", "1.2.3.4")
        client.get("/getCommandToExecute", environ_base={"REMOTE_ADDR": "1.2.3.4"})

        client.post(
            "/post_result",
            data=b"out",
            headers={"CommandID": command_id, "rc": "0"},
            environ_base={"REMOTE_ADDR": "1.2.3.4"},
        )

        assert "1.2.3.4" not in server_module.client_running_command

    def test_diagnose_timeout_for_unknown_client(self, server_module):
        reason = server_module.diagnose_timeout("9.9.9.9", "ver", time.monotonic())

        assert "never contacted the server" in reason

    def test_diagnose_timeout_detects_client_stuck_on_earlier_command(self, server_module):
        """The exact situation from the field: the client blocks in os.system() and stops polling."""
        now = time.monotonic()
        server_module.client_last_seen["1.2.3.4"] = now - 700
        server_module.client_running_command["1.2.3.4"] = server_module.RunningCommand(
            command_id="old",
            command="FS0:\\Tools\\nvmupdate64e.efi /i /l",
            started_at=now - 700,
        )

        reason = server_module.diagnose_timeout("1.2.3.4", "ls FS0:\\Tools\\nut_upd1.cfg", waiting_since=now - 600)

        assert "stopped polling" in reason
        assert "nvmupdate64e.efi /i /l" in reason
        assert "hangs on the DUT" in reason

    def test_diagnose_timeout_for_slow_but_alive_client(self, server_module):
        now = time.monotonic()
        server_module.client_last_seen["1.2.3.4"] = now

        reason = server_module.diagnose_timeout("1.2.3.4", "slow command", waiting_since=now - 600)

        assert "alive and polling" in reason
        assert "bigger timeout" in reason

    def test_diagnose_timeout_when_client_took_this_command_and_never_returned(self, server_module):
        """First timeout of a hanging command: the client fetched it but never reported back."""
        now = time.monotonic()
        server_module.client_last_seen["1.2.3.4"] = now - 600
        server_module.client_running_command["1.2.3.4"] = server_module.RunningCommand(
            command_id="cid-1",
            command="FS0:\\Tools\\nvmupdate64e.efi /i /l",
            started_at=now - 600,
        )

        reason = server_module.diagnose_timeout(
            "1.2.3.4",
            "FS0:\\Tools\\nvmupdate64e.efi /i /l",
            waiting_since=now - 605,
            command_id="cid-1",
        )

        assert "picked this command up" in reason
        assert "never reported back" in reason

    def test_execute_command_timeout_sends_reason_header_and_empty_body(self, server_module):
        """The body must stay empty so the caller never stores an error page as stdout."""
        client = server_module.app.test_client()

        response = client.post("/execute_command", data={"command": "ver", "timeout": "-5", "ip": "1.2.3.4"})

        assert response.status_code == 504
        assert response.get_data() == b""
        assert response.headers["rc"] == "-1"
        assert response.headers[server_module.TIMEOUT_REASON_HEADER]

    def test_disconnect_client_clears_liveness_state(self, server_module):
        """A reconnecting client must not inherit the liveness state of the previous session."""
        client = server_module.app.test_client()
        server_module.add_command_to_queue("ver", "1.2.3.4")
        client.get("/getCommandToExecute", environ_base={"REMOTE_ADDR": "1.2.3.4"})
        assert "1.2.3.4" in server_module.client_last_seen

        client.post("/disconnect_client/1.2.3.4")

        assert "1.2.3.4" not in server_module.client_last_seen
        assert "1.2.3.4" not in server_module.client_running_command
        assert client.get("/health/1.2.3.4").status_code == 503

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

    def test_get_command_to_execute_skips_abandoned_commands(self, server_module):
        """Abandoned commands must never reach the client, otherwise it stays one command behind."""
        client = server_module.app.test_client()
        abandoned_id = server_module.add_command_to_queue("slow command", "1.2.3.4")
        server_module._abandon_command(abandoned_id)
        live_id = server_module.add_command_to_queue("echo alive", "1.2.3.4")

        response = client.get("/getCommandToExecute", environ_base={"REMOTE_ADDR": "1.2.3.4"})

        assert response.status_code == 200
        assert response.headers["CommandID"] == live_id
        assert response.get_data(as_text=True) == "echo alive"
        assert abandoned_id not in server_module.abandoned_command_ids

    def test_get_command_to_execute_returns_204_when_only_abandoned(self, server_module):
        client = server_module.app.test_client()
        abandoned_id = server_module.add_command_to_queue("slow command", "1.2.3.4")
        server_module._abandon_command(abandoned_id)

        response = client.get("/getCommandToExecute", environ_base={"REMOTE_ADDR": "1.2.3.4"})

        assert response.status_code == 204

    def test_post_exception_endpoint(self, server_module):
        client = server_module.app.test_client()
        response = client.post("/exception", data=b"boom", headers={"CommandID": "cid-1"})

        assert response.status_code == 200
        assert server_module.output_queue["cid-1"].output == "boom"
        assert server_module.output_queue["cid-1"].rc == -1
        assert "cid-1" in server_module.output_queue_timestamps

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

    def test_execute_command_returns_gateway_timeout_instead_of_html_error(self, server_module):
        """A timeout must not return a Flask HTML 500 page, which the caller stores as stdout."""
        client = server_module.app.test_client()

        response = client.post(
            "/execute_command",
            data={
                "command": "FS0:\\Tools\\nvmupdate64e.efi /i /l",
                "timeout": "-5",
                "ip": "1.1.1.1",
            },
        )

        assert response.status_code == 504
        assert response.get_data(as_text=True) == ""
        assert response.headers["rc"] == "-1"
        assert "<!doctype html>" not in response.get_data(as_text=True)

    def test_timed_out_command_does_not_desync_next_command(self, server_module):
        """After a timeout the next command must succeed - the server has to re-sync."""
        client = server_module.app.test_client()
        ip = "10.102.23.150"

        timed_out = client.post(
            "/execute_command",
            data={"command": "slow", "timeout": "-5", "ip": ip},
        )
        assert timed_out.status_code == 504

        # The stale command must not be handed out to the client anymore.
        assert client.get("/getCommandToExecute", environ_base={"REMOTE_ADDR": ip}).status_code == 204

        next_id = server_module.add_command_to_queue("ver", ip)
        handed_out = client.get("/getCommandToExecute", environ_base={"REMOTE_ADDR": ip})
        assert handed_out.status_code == 200
        assert handed_out.headers["CommandID"] == next_id

        server_module._store_output(next_id, "UEFI Shell", 0)
        assert server_module.get_output(next_id, timeout=1).output == "UEFI Shell"

    def test_disconnect_client_endpoint(self, server_module):
        client = server_module.app.test_client()
        server_module.clients.append("2.2.2.2")
        server_module.add_command_to_queue("echo hi", "2.2.2.2")

        response_existing = client.post("/disconnect_client/2.2.2.2")
        assert response_existing.status_code == 200
        assert "2.2.2.2" not in server_module.clients
        assert "2.2.2.2" not in server_module.command_dict_queue

        response_missing = client.post("/disconnect_client/8.8.8.8")
        assert response_missing.status_code == 200

    def test_disconnect_client_abandons_pending_commands(self, server_module):
        """Pending commands of a disconnected client must not be executed after reconnect."""
        client = server_module.app.test_client()
        server_module.clients.append("3.3.3.3")
        pending_id = server_module.add_command_to_queue("echo hi", "3.3.3.3")

        client.post("/disconnect_client/3.3.3.3")

        assert pending_id in server_module.abandoned_command_ids
        assert server_module._store_output(pending_id, "late", 0) is False

    def test_post_result_endpoint(self, server_module):
        client = server_module.app.test_client()

        response_default_rc = client.post("/post_result", data=b"output-a", headers={"CommandID": "cmd-a"})
        assert response_default_rc.status_code == 200
        assert server_module.output_queue["cmd-a"].output == "output-a"
        assert server_module.output_queue["cmd-a"].rc == -1
        assert "cmd-a" in server_module.output_queue_timestamps

        response_given_rc = client.post(
            "/post_result",
            data=b"output-b",
            headers={"CommandID": "cmd-b", "rc": "3"},
        )
        assert response_given_rc.status_code == 200
        assert server_module.output_queue["cmd-b"].output == "output-b"
        assert server_module.output_queue["cmd-b"].rc == 3
        assert "cmd-b" in server_module.output_queue_timestamps

    def test_cleanup_stale_outputs_removes_expired_entries_only(self, server_module):
        # Timestamps simulate time.monotonic() values (seconds since arbitrary boot reference).
        # now=4000 s, ttl=3600 s  ->  stale (t=10) is evicted, fresh (t=500) is kept.
        server_module.output_queue["stale"] = server_module.output_object(output="old", rc=-1)
        server_module.output_queue_timestamps["stale"] = 10.0
        server_module.output_queue["fresh"] = server_module.output_object(output="new", rc=0)
        server_module.output_queue_timestamps["fresh"] = 500.0

        server_module._cleanup_stale_outputs(now=4000.0, ttl=3600)

        assert "stale" not in server_module.output_queue
        assert "stale" not in server_module.output_queue_timestamps
        assert server_module.output_queue["fresh"].output == "new"

    def test_cleanup_stale_outputs_expires_abandoned_ids(self, server_module):
        server_module.abandoned_command_ids["old"] = 10.0
        server_module.abandoned_command_ids["recent"] = 3900.0

        server_module._cleanup_stale_outputs(now=4000.0, ttl=600)

        assert "old" not in server_module.abandoned_command_ids
        assert "recent" in server_module.abandoned_command_ids

    def test_output_queue_is_hard_capped(self, server_module):
        """Even without TTL expiry the stored outputs must stay bounded."""
        limit = server_module.MAX_STORED_OUTPUTS
        for index in range(limit + 120):
            server_module._store_output(f"cid-{index}", "payload", 0)

        assert len(server_module.output_queue) <= limit
        assert len(server_module.output_queue_timestamps) == len(server_module.output_queue)

    def test_concurrent_access_is_thread_safe(self, server_module):
        """Werkzeug serves requests in threads - shared state must not raise or corrupt."""
        errors = []

        def _worker(worker_id):
            try:
                for index in range(30):
                    command_id = f"w{worker_id}-{index}"
                    server_module._store_output(command_id, "data", 0)
                    server_module.get_output(command_id, timeout=1)
                    server_module.add_command_to_queue(f"cmd{index}", f"10.0.1.{worker_id}")
                    server_module._cleanup_stale_outputs()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=_worker, args=(worker_id,)) for worker_id in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert not errors
        assert not server_module.output_queue

    def test_run_function_starts_flask(self, server_module, monkeypatch):
        """Test that the run() function starts Flask with correct host and port."""
        captured = {}

        def _fake_run(self, host, port):
            captured["host"] = host
            captured["port"] = port

        monkeypatch.setattr("flask.app.Flask.run", _fake_run)
        server_module.run()

        assert captured == {"host": "0.0.0.0", "port": 80}

    def test_main_block_starts_flask(self, monkeypatch):
        captured = {}

        def _fake_run(self, host, port):
            captured["host"] = host
            captured["port"] = port

        monkeypatch.setattr("flask.app.Flask.run", _fake_run)
        runpy.run_path(str(SERVER_SCRIPT_PATH), run_name="__main__")

        assert captured == {"host": "0.0.0.0", "port": 80}
