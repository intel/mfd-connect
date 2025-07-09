# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
import codecs
import sys
from textwrap import dedent
from unittest.mock import patch

import pytest
from mfd_typing import OSName, OSBitness, OSType
from winrm import Protocol
from winrm.exceptions import WinRMTransportError
from winrm.transport import Transport

from mfd_connect.base import ConnectionCompletedProcess
from mfd_connect.exceptions import WinRMException, OsNotSupported, ConnectionCalledProcessError
from mfd_connect.process.winrm.base import WinRmProcess
from mfd_connect.winrm import WinRmConnection


class TestWinRMConnection:
    @pytest.fixture()
    def connection(self, mocker):
        with patch.object(WinRmConnection, "__init__", return_value=None):
            conn = WinRmConnection("10.10.10.10", "a", "***")
            conn._ip = "10.10.10.10"
            conn.username = "a"
            conn.password = "***"
            conn.cache_system_data = True
            conn._os_name = OSName.WINDOWS
            conn._os_type = OSType.WINDOWS
            conn._server = mocker.create_autospec(Protocol)
            conn._server.transport = mocker.create_autospec(Transport)
            conn._shell_id = "111"
            conn._cert_pem = None
            conn._cert_key_pem = None
            yield conn

    def test__connect(self, connection, mocker):
        protocol_mock = mocker.patch("mfd_connect.winrm.Protocol")
        protocol_mock_object = protocol_mock.return_value
        protocol_mock_object.open_shell.return_value = "121"  # shell_id
        connection._connect()
        assert connection._shell_id == "121"
        assert connection._server == protocol_mock_object
        protocol_mock.assert_called_once_with(
            endpoint="https://10.10.10.10:5986/wsman",
            username="a",
            password="***",
            transport="ntlm",
            server_cert_validation="ignore",
            proxy=None,
            cert_pem=None,
            cert_key_pem=None,
        )

    def test__connect_failure(self, connection, mocker):
        protocol_mock = mocker.patch("mfd_connect.winrm.Protocol")
        protocol_mock.side_effect = WinRMTransportError
        with pytest.raises(WinRMException, match="Found exception during connection to server"):
            connection._connect()

    def test__start_process(self, connection):
        connection._server.run_command.return_value = "12321"
        assert connection._start_process("dir") == "12321"
        connection._server.run_command.assert_called_once_with("111", "call", ["dir"])

    def test_disconnect(self, connection):
        connection.disconnect()
        connection._server.transport.close_session.assert_called_once()

    def test_start_process(self, connection, mocker):
        connection._start_process = mocker.create_autospec(connection._start_process)
        connection._start_process.return_value = "12321"
        process = connection.start_process("dir")
        assert process.command_id == "12321"
        assert process._connection_handle == connection
        assert isinstance(process, WinRmProcess)

    def test_get_os_name(self, connection, mocker):
        connection.execute_command = mocker.create_autospec(connection.execute_command)
        connection.execute_command.return_value = ConnectionCompletedProcess(
            "",
            stdout=dedent(
                """\
        Caption                          OSArchitecture
        -------                         --------------
        Microsoft Windows 10 Enterprise  64-bit


        """
            ),
            return_code=0,
        )
        assert connection.get_os_name() == OSName.WINDOWS

    def test_get_os_bitness(self, connection, mocker):
        connection.execute_command = mocker.create_autospec(connection.execute_command)
        connection.execute_command.return_value = ConnectionCompletedProcess(
            "",
            stdout=dedent(
                """\
        OSArchitecture
        --------------
        64-bit


        """
            ),
            return_code=0,
        )
        assert connection.get_os_bitness() == OSBitness.OS_64BIT

    def test_get_os_bitness_failure(self, connection, mocker):
        connection.execute_command = mocker.create_autospec(connection.execute_command)
        connection.execute_command.return_value = ConnectionCompletedProcess(
            "",
            stdout=dedent(
                """\
        OSArchitecture
        --------------
        12-bit


        """
            ),
            return_code=0,
        )
        with pytest.raises(OsNotSupported):
            connection.get_os_bitness()
        connection._os_type = OSType.POSIX
        with pytest.raises(OsNotSupported):
            connection.get_os_bitness()

    def test__execute_command(self, connection, mocker):
        connection._start_process = mocker.create_autospec(connection._start_process)
        connection._start_process.return_value = "12321"
        connection._server.get_command_output.return_value = (b"", b"", 0)
        assert connection._execute_command("dir") == (b"", b"", 0)
        connection._start_process.assert_called_once_with("dir")
        connection._server.get_command_output.assert_called_once_with("111", "12321")

    def test_execute_command_success(self, mocker, connection):
        command = "command"
        stdout, stderr = "stdout\n", "stderr\n"
        stdout_bytes = codecs.encode(stdout, "utf-8")
        stderr_bytes = codecs.encode(stderr, "utf-8")

        mocker.patch.object(connection, "_execute_command", return_value=(stdout_bytes, stderr_bytes, 0))

        expected_result = ConnectionCompletedProcess(args=command, stdout=stdout, return_code=0, stderr=stderr)
        result = connection.execute_command(command, stderr_to_stdout=False, expected_return_codes={0})

        assert (result.args, result.stdout, result.return_code, result.stderr) == (
            expected_result.args,
            expected_result.stdout,
            expected_result.return_code,
            expected_result.stderr,
        )

    def test_execute_command_success_with_stderr_to_stdout(self, mocker, connection):
        command = "command"
        stdout, stderr = "stdout\n", "stderr\n"
        stdout_bytes = codecs.encode(stdout, "utf-8")
        stderr_bytes = codecs.encode(stderr, "utf-8")

        mocker.patch.object(connection, "_execute_command", return_value=(stdout_bytes, stderr_bytes, 0))

        expected_result = ConnectionCompletedProcess(args=command, stdout=stdout + stderr, return_code=0, stderr=None)
        result = connection.execute_command(command, stderr_to_stdout=True, expected_return_codes={0})

        assert (result.args, result.stdout, result.return_code) == (
            expected_result.args,
            expected_result.stdout,
            expected_result.return_code,
        )

    def test_execute_command_failure(self, mocker, connection):
        command = "command"
        stdout, stderr = "stdout\n", "stderr\n"
        stdout_bytes = codecs.encode(stdout, "utf-8")
        stderr_bytes = codecs.encode(stderr, "utf-8")

        mocker.patch.object(connection, "_execute_command", return_value=(stdout_bytes, stderr_bytes, 1))

        with pytest.raises(ConnectionCalledProcessError):
            connection.execute_command(command, expected_return_codes={0})

    def test_execute_command_with_custom_exception(self, mocker, connection):
        class CustomException(ConnectionCalledProcessError):
            pass

        command = "command"
        stdout, stderr = "stdout\n", "stderr\n"
        stdout_bytes = codecs.encode(stdout, "utf-8")
        stderr_bytes = codecs.encode(stderr, "utf-8")

        mocker.patch.object(connection, "_execute_command", return_value=(stdout_bytes, stderr_bytes, 1))

        with pytest.raises(CustomException):
            connection.execute_command(command, expected_return_codes={0}, custom_exception=CustomException)

    def test_execute_powershell(self, mocker, connection):
        connection.execute_command = mocker.create_autospec(connection.execute_command)
        connection.execute_powershell("dir")
        connection.execute_command.assert_called_once_with(
            "powershell.exe -OutPutFormat Text -nologo -noninteractive "
            '"$host.UI.RawUI.BufferSize = new-object System.Management.Automation.Host.Size(512,3000);dir"',
            input_data=None,
            cwd=None,
            timeout=None,
            env=None,
            discard_stdout=False,
            discard_stderr=False,
            skip_logging=False,
            stderr_to_stdout=False,
            expected_return_codes=frozenset({0}),
            shell=False,
            custom_exception=None,
        )

    def test_init_sets_attributes_and_calls_methods(self, mocker):
        # Mock parent __init__, _connect, and log_connected_host_info
        parent_init = mocker.patch("mfd_connect.base.AsyncConnection.__init__")
        connect_mock = mocker.patch.object(WinRmConnection, "_connect")
        log_info_mock = mocker.patch.object(WinRmConnection, "log_connected_host_info")

        ip = "1.2.3.4"
        username = "user"
        password = "pass"
        cert_pem = "cert.pem"
        cert_key_pem = "key.pem"
        cache_system_data = False

        conn = WinRmConnection(ip, username, password, cache_system_data, cert_pem, cert_key_pem)

        parent_init.assert_called_once_with(ip=ip, cache_system_data=cache_system_data)
        assert conn.username == username
        assert conn.password == password
        assert conn._cert_pem == cert_pem
        assert conn._cert_key_pem == cert_key_pem
        assert conn._server is None
        assert conn._shell_id is None
        connect_mock.assert_called_once()
        log_info_mock.assert_called_once()

    def test_init_defaults(self, mocker):
        parent_init = mocker.patch("mfd_connect.base.AsyncConnection.__init__")
        connect_mock = mocker.patch.object(WinRmConnection, "_connect")
        log_info_mock = mocker.patch.object(WinRmConnection, "log_connected_host_info")

        ip = "1.2.3.4"
        username = "user"
        password = "pass"

        conn = WinRmConnection(ip, username, password)

        parent_init.assert_called_once_with(ip=ip, cache_system_data=True)
        assert conn.username == username
        assert conn.password == password
        assert conn._cert_pem is None
        assert conn._cert_key_pem is None
        assert conn._server is None
        assert conn._shell_id is None
        connect_mock.assert_called_once()
        log_info_mock.assert_called_once()

    def test_path_python_312plus(self, monkeypatch, connection, mocker):
        # Simulate Python 3.12+
        monkeypatch.setattr(sys, "version_info", (3, 13, 0))
        cpf = mocker.patch("mfd_connect.winrm.custom_path_factory", return_value="custom_path")
        result = connection.path("foo", bar=1)
        assert result == "custom_path"
        cpf.assert_called_once()
        # owner should be injected as self
        assert cpf.call_args.kwargs["owner"] is connection

    def test_path_python_pre312(self, monkeypatch, connection, mocker):
        # Simulate Python < 3.12
        monkeypatch.setattr(sys, "version_info", (3, 11, 0))
        cp = mocker.patch("mfd_connect.winrm.CustomPath", return_value="custom_path")
        result = connection.path("foo", bar=1)
        assert result == "custom_path"
        cp.assert_called_once()
        # owner should be injected as self
        assert cp.call_args.kwargs["owner"] is connection
