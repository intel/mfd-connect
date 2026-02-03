# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for rshell tests."""

import sys
import types
import runpy
from pathlib import Path
from subprocess import CalledProcessError
from unittest.mock import Mock, patch

import pytest
import requests
from mfd_typing.cpu_values import CPUArchitecture
from mfd_typing.os_values import OSBitness, OSName, OSType

from mfd_connect.base import ConnectionCompletedProcess
from mfd_connect.exceptions import ConnectionCalledProcessError, OsNotSupported
from mfd_connect.rshell import PLATFORM_POWER_TRANSITION_DELAY_SECONDS, RShellConnection


class TestRShellConnection:
    """Tests of RShellConnection."""

    @pytest.fixture()
    def rshell(self):
        with patch.object(RShellConnection, "__init__", return_value=None):
            conn = RShellConnection(ip="10.10.10.10")
        conn._ip = "10.10.10.10"
        conn.server_ip = "127.0.0.1"
        conn.server_process = None
        conn.cache_system_data = False
        return conn

    def test_init_local_server_start(self, mocker):
        run_server = mocker.patch("mfd_connect.rshell.RShellConnection._run_server", return_value=Mock())
        wait_for_connection = mocker.patch("mfd_connect.rshell.RShellConnection.wait_for_connection")
        sleep = mocker.patch("mfd_connect.rshell.time.sleep")

        conn = RShellConnection(ip="10.10.10.10", server_ip="127.0.0.1", connection_timeout=17)

        assert conn.server_process is not None
        assert conn.server_ip == "127.0.0.1"
        run_server.assert_called_once()
        sleep.assert_called_once_with(5)
        wait_for_connection.assert_called_once_with(17)

    def test_init_with_remote_server_ip_does_not_auto_start(self, mocker):
        run_server = mocker.patch("mfd_connect.rshell.RShellConnection._run_server")
        wait_for_connection = mocker.patch("mfd_connect.rshell.RShellConnection.wait_for_connection")

        conn = RShellConnection(ip="10.10.10.10", server_ip="192.168.0.10", connection_timeout=4)

        assert conn.server_ip == "192.168.0.10"
        assert conn.server_process is None
        run_server.assert_not_called()
        wait_for_connection.assert_called_once_with(4)

    def test_wait_for_connection_success_after_retry(self, rshell, mocker):
        get = mocker.patch(
            "mfd_connect.rshell.requests.get",
            side_effect=[
                requests.RequestException("boom"),
                Mock(status_code=200),
            ],
        )
        sleep = mocker.patch("mfd_connect.rshell.time.sleep")

        rshell.wait_for_connection(connection_timeout=10)

        assert get.call_count == 2
        sleep.assert_called_once_with(5)

    def test_wait_for_connection_timeout(self, rshell, mocker):
        class FakeTimeoutCounter:
            def __init__(self, _timeout):
                self._checks = 0

            def __bool__(self):
                self._checks += 1
                return self._checks >= 2

        mocker.patch("mfd_connect.rshell.TimeoutCounter", FakeTimeoutCounter)
        mocker.patch("mfd_connect.rshell.requests.get", return_value=Mock(status_code=503))
        mocker.patch("mfd_connect.rshell.time.sleep")

        with pytest.raises(TimeoutError, match="Connection of Client to RShell server timed out"):
            rshell.wait_for_connection(connection_timeout=1)

    def test_disconnect_no_optional_actions(self, rshell, mocker):
        post = mocker.patch("mfd_connect.rshell.requests.post")
        rshell.execute_command = mocker.Mock()
        rshell.stop_server = mocker.Mock()

        rshell.disconnect(stop_client=False, stop_server=False)

        post.assert_called_once_with("http://127.0.0.1/disconnect_client/10.10.10.10", proxies={"no_proxy": "*"})
        rshell.execute_command.assert_not_called()
        rshell.stop_server.assert_not_called()

    def test_disconnect_with_optional_actions(self, rshell, mocker):
        mocker.patch("mfd_connect.rshell.requests.post")
        rshell.execute_command = mocker.Mock()
        rshell.stop_server = mocker.Mock()
        rshell.server_process = Mock()

        rshell.disconnect(stop_client=True, stop_server=True)

        rshell.execute_command.assert_called_once_with("end")
        rshell.stop_server.assert_called_once()

    def test_disconnect_stop_server_true_without_server_process(self, rshell, mocker):
        mocker.patch("mfd_connect.rshell.requests.post")
        rshell.stop_server = mocker.Mock()

        rshell.disconnect(stop_server=True)

        rshell.stop_server.assert_not_called()

    def test_run_server(self, rshell, mocker):
        conn = mocker.Mock()
        server_file = Path("C:/tmp/rshell.py")
        conn.path.return_value = server_file
        conn.modules().sys.executable = "python_exe"
        conn.start_process.return_value = "proc"
        mocker.patch("mfd_connect.rshell.LocalConnection", return_value=conn)

        result = rshell._run_server()

        assert result == "proc"
        conn.start_process.assert_called_once_with(f"python_exe {server_file.parent / 'rshell_server.py'}")

    def test_type_checking_import_block_executes(self, monkeypatch):
        class _FakeBaseModel:
            pass

        pydantic_stub = types.ModuleType("pydantic")
        pydantic_stub.BaseModel = _FakeBaseModel
        monkeypatch.setitem(sys.modules, "pydantic", pydantic_stub)

        import typing as typing_module

        monkeypatch.setattr(typing_module, "TYPE_CHECKING", True, raising=False)
        rshell_path = Path(__file__).resolve().parents[3] / "mfd_connect" / "rshell.py"
        runpy.run_path(str(rshell_path), run_name="mfd_connect._rshell_typecheck")

    def test_execute_command_with_all_unsupported_args_and_skip_logging(self, rshell, mocker):
        post = mocker.patch("mfd_connect.rshell.requests.post")
        post.return_value = Mock(text="out", headers={"rc": "7"})

        result = rshell.execute_command(
            "echo hello",
            input_data="in",
            cwd="/tmp",
            timeout=9,
            env={"A": "B"},
            stderr_to_stdout=True,
            discard_stdout=True,
            discard_stderr=True,
            skip_logging=True,
            expected_return_codes=[0],
            shell=True,
            custom_exception=CalledProcessError,
        )

        assert result.args == "echo hello"
        assert result.stdout == "out"
        assert result.return_code == 7
        post.assert_called_once_with(
            "http://127.0.0.1/execute_command",
            data={"command": "echo hello", "timeout": 9, "ip": "10.10.10.10"},
            proxies={"no_proxy": "*"},
        )

    def test_execute_command_logs_stdout_and_default_rc(self, rshell, mocker):
        mocker.patch("mfd_connect.rshell.requests.post", return_value=Mock(text="stdout", headers={}))

        result = rshell.execute_command("echo hi")

        assert result.return_code == -1
        assert result.stdout == "stdout"

    def test_execute_command_no_stdout(self, rshell, mocker):
        mocker.patch("mfd_connect.rshell.requests.post", return_value=Mock(text="", headers={"rc": "0"}))

        result = rshell.execute_command("echo hi")

        assert result.return_code == 0
        assert result.stdout == ""

    def test_path_python_312_plus(self, rshell, monkeypatch, mocker):
        monkeypatch.setattr(sys, "version_info", (3, 12, 0))
        factory = mocker.patch("mfd_connect.rshell.custom_path_factory", return_value="cp")

        path = rshell.path("abc")

        assert path == "cp"
        assert factory.call_args.kwargs["owner"] is rshell

    def test_path_python_pre_312(self, rshell, monkeypatch, mocker):
        monkeypatch.setattr(sys, "version_info", (3, 11, 9))
        custom_path = mocker.patch("mfd_connect.rshell.CustomPath", return_value="legacy")

        path = rshell.path("abc")

        assert path == "legacy"
        assert custom_path.call_args.kwargs["owner"] is rshell

    def test_check_if_unix_true_false_and_exception(self, rshell, mocker):
        rshell.execute_command = mocker.Mock(
            side_effect=[
                ConnectionCompletedProcess(args="uname -a", return_code=0, stdout="ok"),
                ConnectionCompletedProcess(args="uname -a", return_code=1, stdout="bad"),
                ConnectionCalledProcessError(1, "uname -a"),
            ]
        )

        assert rshell._check_if_unix() is True
        assert rshell._check_if_unix() is False
        assert rshell._check_if_unix() is False

    def test_get_unix_distribution_supported_and_unsupported(self, rshell, mocker):
        rshell.execute_command = mocker.Mock(
            side_effect=[
                ConnectionCompletedProcess(args="uname -o", return_code=0, stdout="Linux GNU"),
                ConnectionCompletedProcess(args="uname -o", return_code=0, stdout="NotSupportedOS"),
            ]
        )

        assert rshell._get_unix_distribution() == OSName.LINUX
        with pytest.raises(OsNotSupported, match="Client OS not supported"):
            rshell._get_unix_distribution()

    def test_check_if_efi_shell_true_and_false(self, rshell, mocker):
        rshell.execute_command = mocker.Mock(
            side_effect=[
                ConnectionCompletedProcess(args="ver", return_code=0, stdout="UEFI Shell v2"),
                ConnectionCompletedProcess(args="ver", return_code=0, stdout="Some other shell"),
            ]
        )

        assert rshell._check_if_efi_shell() is True
        assert rshell._check_if_efi_shell() is False

    def test_get_os_type_paths(self, rshell, mocker):
        rshell._check_if_efi_shell = mocker.Mock(side_effect=[True, False, False])
        rshell._check_if_unix = mocker.Mock(side_effect=[True, False])

        assert rshell.get_os_type() == OSType.EFISHELL
        assert rshell.get_os_type() == OSType.POSIX
        with pytest.raises(OsNotSupported, match="Client OS not supported"):
            rshell.get_os_type()

    def test_get_os_name_paths(self, rshell, mocker):
        rshell._check_if_efi_shell = mocker.Mock(side_effect=[True, False, False])
        rshell._check_if_unix = mocker.Mock(side_effect=[True, False])
        rshell._get_unix_distribution = mocker.Mock(return_value=OSName.LINUX)

        assert rshell.get_os_name() == OSName.EFISHELL
        assert rshell.get_os_name() == OSName.LINUX
        with pytest.raises(OsNotSupported, match="Client OS not supported"):
            rshell.get_os_name()

    def test_get_os_bitness_paths(self, rshell, mocker):
        rshell._check_if_efi_shell = mocker.Mock(side_effect=[True, False])

        assert rshell.get_os_bitness() == OSBitness.OS_64BIT
        with pytest.raises(OsNotSupported, match="Client OS is not supported"):
            rshell.get_os_bitness()

    def test_get_cpu_architecture_paths(self, rshell, mocker):
        rshell._check_if_efi_shell = mocker.Mock(side_effect=[True, False])

        assert rshell.get_cpu_architecture() == CPUArchitecture.X86_64
        with pytest.raises(OsNotSupported, match="'get_cpu_architecture' not supported on that OS"):
            rshell.get_cpu_architecture()

    def test_restart_platform(self, rshell, mocker):
        rshell.execute_command = mocker.Mock()
        rshell.disconnect = mocker.Mock()
        sleep = mocker.patch("mfd_connect.rshell.time.sleep")

        rshell.restart_platform()

        rshell.execute_command.assert_called_once_with("reset -c")
        sleep.assert_called_once_with(PLATFORM_POWER_TRANSITION_DELAY_SECONDS)
        rshell.disconnect.assert_called_once()

    def test_warm_reboot_platform(self, rshell, mocker):
        rshell.execute_command = mocker.Mock()
        rshell.disconnect = mocker.Mock()
        sleep = mocker.patch("mfd_connect.rshell.time.sleep")

        rshell.warm_reboot_platform()

        rshell.execute_command.assert_called_once_with("reset -w")
        sleep.assert_called_once_with(PLATFORM_POWER_TRANSITION_DELAY_SECONDS)
        rshell.disconnect.assert_called_once()

    def test_shutdown_platform(self, rshell, mocker):
        rshell.execute_command = mocker.Mock()
        rshell.disconnect = mocker.Mock()
        sleep = mocker.patch("mfd_connect.rshell.time.sleep")

        rshell.shutdown_platform()

        rshell.execute_command.assert_called_once_with("reset -s")
        sleep.assert_called_once_with(PLATFORM_POWER_TRANSITION_DELAY_SECONDS)
        rshell.disconnect.assert_called_once()

    def test_wait_for_host(self, rshell, mocker):
        rshell.wait_for_connection = mocker.Mock()

        rshell.wait_for_host(timeout=22)

        rshell.wait_for_connection.assert_called_once_with(22)

    def test_stop_server_with_and_without_process(self, rshell, mocker):
        rshell.server_process = None
        rshell.stop_server()

        server_process = mocker.Mock()
        server_process.stdout_text = "server out"
        rshell.server_process = server_process

        rshell.stop_server()

        server_process.kill.assert_called_once()
