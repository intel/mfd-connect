# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
from textwrap import dedent

import pytest
from unittest.mock import patch, MagicMock

from mfd_common_libs import log_levels
from mfd_typing import OSType, OSName
from paramiko import SSHClient
from paramiko.channel import Channel

from paramiko.ssh_exception import SSHException, AuthenticationException
from subprocess import TimeoutExpired, CalledProcessError

from mfd_connect.exceptions import (
    ModuleFrameworkDesignError,
    SSHReconnectException,
    OsNotSupported,
)
from mfd_connect.interactive_ssh import InteractiveSSHConnection, IO_TIMEOUT
from mfd_connect.process.interactive_ssh.base import InteractiveSSHProcess


class TestInteractiveSSHConnection:
    @pytest.fixture
    def ssh(self, mocker):
        mocker.patch("mfd_connect.interactive_ssh.time.sleep")
        ip = "192.168.1.1"
        username = "user"
        password = "pass"
        port = 22
        with patch.object(InteractiveSSHConnection, "__init__", return_value=None):
            conn = InteractiveSSHConnection(ip=ip, username=username, password=password, port=port)
            conn._connection_details = {
                "hostname": ip,
                "port": 22,
                "username": username,
                "password": password,
            }
            conn._ip = ip
            conn._default_timeout = None
            # conn._os_type = OSType.SWITCH
            conn._process_class = InteractiveSSHProcess
            conn._prompt = "switch>"
            conn._connection = mocker.create_autospec(Channel)
            conn._connection_tmp = mocker.create_autospec(SSHClient)
            conn._process = None
            conn.cache_system_data = True
            yield conn

    def test_init_successful_connection(self, ssh):
        assert ssh._ip == "192.168.1.1"
        assert ssh._connection_details["username"] == "user"
        assert ssh._connection_details["password"] == "pass"
        assert ssh._connection_details["port"] == 22

    def test_init_connection_failure(self):
        with pytest.raises(ModuleFrameworkDesignError):
            with patch.object(SSHClient, "connect", side_effect=SSHException("Connection failed")):
                InteractiveSSHConnection(ip="192.168.1.1", username="user", password="***")

    def test_init(self, mocker):
        mocker.patch("mfd_connect.interactive_ssh.InteractiveSSHConnection.get_os_type")
        mocker.patch("mfd_connect.interactive_ssh.InteractiveSSHConnection._connect")
        InteractiveSSHConnection(ip="192.168.1.1", username="user", password="***")

    def test_reconnect_successful(self, ssh):
        with patch.object(SSHClient, "get_transport") as mock_transport:
            mock_transport.return_value.is_active.return_value = True
            ssh._reconnect()
            assert ssh._connection.get_transport().is_active()

    def test_reconnect_failure(self, ssh, mocker):
        ssh._connect = mocker.create_autospec(ssh._connect)
        ssh._connection.get_transport.return_value.is_active.return_value = False
        with pytest.raises(SSHReconnectException):
            ssh._reconnect()

    def test_os_not_supported(self, ssh):
        with patch.object(
            InteractiveSSHConnection,
            "execute_command",
            return_value=MagicMock(return_code=1),
        ):
            with pytest.raises(OsNotSupported):
                ssh.get_os_type()

    def test_cleanup_stdout(self, ssh):
        command = 'echo "Hello World"'
        output = f"{command}\nHello World\n{ssh.prompt}\n"
        clean_output = ssh.cleanup_stdout(command, output)
        assert clean_output == "Hello World\n"

    def test_verify_command_correctness(self, ssh):
        with pytest.raises(ValueError):
            ssh._verify_command_correctness("reboot;")
        with pytest.raises(ValueError):
            ssh._verify_command_correctness("shutdown ||")
        with pytest.raises(ValueError):
            ssh._verify_command_correctness("update &&")

    def test_start_process(self, ssh):
        with patch.object(InteractiveSSHConnection, "_start_process"):
            process = ssh.start_process("ls")
            assert isinstance(process, InteractiveSSHProcess)

    def test_start_process_with_cwd(self, ssh, mocker):
        mocker.patch.object(ssh, "_start_process")
        mocker.patch.object(ssh, "refresh_prompt")

        process = ssh.start_process("ls", cwd="/tmp")

        ssh.refresh_prompt.assert_called()
        assert isinstance(process, InteractiveSSHProcess)

    def test_start_process_second_process(self, ssh, mocker, caplog):
        caplog.set_level(level=log_levels.MODULE_DEBUG)
        ssh._process = mocker.Mock()
        assert ssh.start_process("ls") == ssh._process
        assert "Process already started. Cannot run more than 1 process." in caplog.text

    def test_start_process_not_supported_flags(self, ssh, mocker, caplog):
        caplog.set_level(level=log_levels.MODULE_DEBUG)
        with patch.object(InteractiveSSHConnection, "_start_process"):
            assert ssh.start_process("ls", cpu_affinity=1, output_file="", log_file=True)
        assert "Used cpu affinity, but it's not functional for SSH." in caplog.text
        assert "Used output_file, but it's not functional for SSH." in caplog.text
        assert "Used log_file, but it's not functional for SSH." in caplog.text

    def test_disconnect(self, ssh):
        ssh.disconnect()
        ssh._connection.close.assert_called()
        ssh._connection_tmp.close.assert_called()

    def test_path_raises_not_implemented_error(self, ssh):
        with pytest.raises(NotImplementedError):
            ssh.path()

    def test_enable_sudo_raises_not_implemented_error(self, ssh):
        with pytest.raises(NotImplementedError):
            ssh.enable_sudo()

    def test_disable_sudo_raises_not_implemented_error(self, ssh):
        with pytest.raises(NotImplementedError):
            ssh.disable_sudo()

    def test_shutdown_platform_raises_not_implemented_error(self, ssh):
        with pytest.raises(NotImplementedError):
            ssh.shutdown_platform()

    def test_restart_platform_raises_not_implemented_error(self, ssh):
        with pytest.raises(NotImplementedError):
            ssh.restart_platform()

    def test_execute_powershell_raises_not_implemented_error(self, ssh):
        with pytest.raises(NotImplementedError):
            ssh.execute_powershell("")

    def test_start_processes_raises_not_implemented_error(self, ssh):
        with pytest.raises(NotImplementedError):
            ssh.start_processes("")

    def test_wait_for_host(self, ssh, mocker):
        ssh._connection.get_transport().is_active().return_value = True
        ssh._connect = mocker.Mock(side_effect=[OSError, AuthenticationException, None])
        mocker.patch("mfd_connect.interactive_ssh.time.sleep")
        ssh.wait_for_host(10)

    def test_wait_for_host_fail(self, ssh, mocker):
        ssh._connect = mocker.Mock(side_effect=OSError)
        mocker.patch("mfd_connect.interactive_ssh.time.sleep")
        mocker.patch("mfd_connect.interactive_ssh.TimeoutCounter", return_value=True)
        with pytest.raises(TimeoutError):
            ssh.wait_for_host(1)

    def test_start_process_by_start_tool(self, ssh, mocker):
        ssh.start_process = mocker.Mock()
        ssh.start_process_by_start_tool("ls")
        ssh.start_process.assert_called_with(command="ls", cwd=None, discard_stdout=False)

    def test_read_prompt_returns_correct_prompt(self, ssh, mocker):
        mocker.patch.object(ssh, "flush")
        mocker.patch.object(ssh, "write_to_channel")
        ssh._connection.recv.return_value = b"test_prompt\n"
        assert ssh._read_prompt() == "test_prompt"

    def test_read_prompt_handles_empty_prompt(self, ssh, mocker):
        mocker.patch.object(ssh, "flush")
        mocker.patch.object(ssh, "write_to_channel")
        ssh._connection.recv.return_value = b"\n"
        with pytest.raises(ModuleFrameworkDesignError):
            ssh._read_prompt()

    def test_read_prompt_handles_multiline_prompt(self, ssh, mocker):
        mocker.patch.object(ssh, "flush")
        mocker.patch.object(ssh, "write_to_channel")
        ssh._connection.recv.return_value = b"line1\nline2\nprompt_line\n"
        assert ssh._read_prompt() == "prompt_line"

    def test_prompt(self, ssh, mocker):
        mocker.patch.object(ssh, "_read_prompt", return_value="prompt")
        assert ssh.prompt == "switch>"
        ssh._read_prompt.assert_not_called()
        ssh._prompt = None
        assert ssh.prompt == "prompt"
        ssh._read_prompt.assert_called_once()

    def test_refresh_prompt(self, ssh, mocker):
        mocker.patch.object(ssh, "_read_prompt", return_value="prompt")
        ssh.refresh_prompt()
        assert ssh.prompt == "prompt"
        ssh._read_prompt.assert_called_once()

    def test_flush(self, ssh):
        ssh._connection.recv_ready.side_effect = [True, False]
        ssh.flush()
        ssh._connection.recv.assert_called_with(1024)

    def test_write_to_channel(self, ssh, mocker):
        ssh.write_to_channel("test")
        ssh._connection.send.assert_has_calls([mocker.call(b"test"), mocker.call(b"\n")])

    def test_write_to_channel_no_newline(self, ssh, mocker):
        ssh.write_to_channel("test", with_enter=False)
        ssh._connection.send.assert_called_once_with(b"test")

    def test_read_channel_when_connection_is_ready(self, ssh, mocker):
        mocker.patch.object(ssh._connection, "recv_ready", side_effect=[True, False])
        mocker.patch.object(ssh._connection, "recv", return_value=b"test")
        result = ssh.read_channel()
        assert result == "test"

    def test_read_channel_when_connection_is_not_ready(self, ssh, mocker):
        mocker.patch.object(ssh._connection, "recv_ready", return_value=False)
        result = ssh.read_channel()
        assert result == ""

    def test_read_channel_when_timeout_error_occurs(self, ssh, mocker):
        mocker.patch.object(ssh._connection, "recv_ready", side_effect=TimeoutError)
        result = ssh.read_channel()
        assert result == ""

    def test_read_channel_when_other_exception_occurs(self, ssh, mocker):
        mocker.patch.object(ssh._connection, "recv_ready", side_effect=Exception)
        with pytest.raises(Exception, match="Cannot read channel"):
            ssh.read_channel()

    def test_start_process_executes_command_successfully(self, ssh, mocker):
        mocker.patch.object(ssh._connection, "settimeout")
        mocker.patch.object(ssh._connection, "update_environment")
        mocker.patch.object(ssh, "flush")
        mocker.patch.object(ssh, "write_to_channel")
        ssh._start_process("ls", timeout=10, environment={"TEST": "test"})
        ssh._connection.settimeout.assert_called_once_with(10)
        ssh._connection.update_environment.assert_called_once_with({"TEST": "test"})
        ssh.flush.assert_called_once()
        ssh.write_to_channel.assert_called_once_with("ls", with_enter=True)

    def test_start_process_executes_command_without_timeout_and_environment(self, ssh, mocker):
        mocker.patch.object(ssh._connection, "settimeout")
        mocker.patch.object(ssh._connection, "update_environment")
        mocker.patch.object(ssh, "flush")
        mocker.patch.object(ssh, "write_to_channel")
        ssh._start_process("ls")
        ssh._connection.settimeout.assert_not_called()
        ssh._connection.update_environment.assert_not_called()
        ssh.flush.assert_called_once()
        ssh.write_to_channel.assert_called_once_with("ls", with_enter=True)

    def test_get_return_code_for_windows_os(self, ssh, mocker):
        ssh._os_type = OSType.WINDOWS
        mocker.patch.object(ssh, "_start_process")
        mocker.patch.object(ssh, "cleanup_stdout", return_value="0\n")
        mocker.patch.object(ssh, "read_channel", return_value="0\n")
        result = ssh._get_return_code("output")
        assert result == 0

    def test_get_return_code_for_posix_os(self, ssh, mocker):
        ssh._os_type = OSType.POSIX
        mocker.patch.object(ssh, "_start_process")
        mocker.patch.object(ssh, "cleanup_stdout", return_value="0\n")
        mocker.patch.object(ssh, "read_channel", return_value="0\n")
        result = ssh._get_return_code("output")
        assert result == 0

    def test_get_return_code_for_unsupported_os(self, ssh):
        ssh._os_type = "UNSUPPORTED"
        with pytest.raises(Exception, match="Unsupported OS Type"):
            ssh._get_return_code("output")

    def test_get_return_code_for_switch_os_with_invalid_input_detected(self, ssh):
        ssh._os_type = OSType.SWITCH
        result = ssh._get_return_code("% Invalid input detected")
        assert result == 1

    def test_get_return_code_for_switch_os_without_invalid_input_detected(self, ssh):
        ssh._os_type = OSType.SWITCH
        result = ssh._get_return_code("output")
        assert result == 0

    def test_execute_command_successfully(self, ssh, mocker):
        mocker.patch.object(ssh, "_start_process")
        mocker.patch("mfd_connect.interactive_ssh.time.sleep")
        mocker.patch.object(ssh, "read_channel", side_effect=["first part\n", "output\nswitch>"])
        mocker.patch.object(ssh, "cleanup_stdout", side_effect=["first part\n", "output"])
        mocker.patch.object(ssh, "_get_return_code", return_value=0)
        result = ssh.execute_command("ls")
        assert result.stdout == "first part\noutput"
        assert result.stderr == ""
        assert result.return_code == 0

    def test_execute_command_successfully_with_cwd(self, ssh, mocker):
        mocker.patch.object(ssh, "_start_process")
        mocker.patch.object(ssh, "refresh_prompt")
        mocker.patch("mfd_connect.interactive_ssh.time.sleep")
        mocker.patch.object(ssh, "read_channel", side_effect=["first part\n", "output\nswitch>"])
        mocker.patch.object(ssh, "cleanup_stdout", side_effect=["first part\n", "output"])
        mocker.patch.object(ssh, "_get_return_code", return_value=0)

        result = ssh.execute_command("ls", cwd="/tmp")

        ssh.refresh_prompt.assert_called()
        assert result.stdout == "first part\noutput"
        assert result.stderr == ""
        assert result.return_code == 0

    def test_execute_command_with_timeout_error(self, ssh, mocker):
        mocker.patch.object(ssh, "_start_process")
        mocker.patch("mfd_connect.interactive_ssh.TimeoutCounter", return_value=True)
        mocker.patch.object(ssh, "read_channel", return_value="output")
        mocker.patch.object(ssh, "cleanup_stdout", return_value="output")
        mocker.patch.object(ssh, "_get_return_code", return_value=0)
        with pytest.raises(TimeoutExpired):
            ssh.execute_command("ls", timeout=1)

    def test_execute_command_with_unexpected_return_code(self, ssh, mocker):
        mocker.patch.object(ssh, "_start_process")
        mocker.patch.object(ssh, "read_channel", return_value="output\nswitch>")
        mocker.patch.object(ssh, "cleanup_stdout", return_value="output")
        mocker.patch.object(ssh, "_get_return_code", return_value=1)
        with pytest.raises(CalledProcessError):
            ssh.execute_command("ls", expected_return_codes={0})

    def test_execute_command_with_custom_exception(self, ssh, mocker):
        class CustomException(CalledProcessError):
            pass

        mocker.patch.object(ssh, "_start_process")
        mocker.patch.object(ssh, "read_channel", return_value="output\nswitch>")
        mocker.patch.object(ssh, "cleanup_stdout", return_value="output")
        mocker.patch.object(ssh, "_get_return_code", return_value=1)
        with pytest.raises(CustomException):
            ssh.execute_command("ls", expected_return_codes={0}, custom_exception=CustomException)

    def test_execute_command_custom_exception_without_expected_rc(self, ssh, mocker, caplog):
        caplog.set_level(level=log_levels.MODULE_DEBUG)

        class CustomException(CalledProcessError):
            pass

        mocker.patch.object(ssh, "_start_process")
        mocker.patch.object(ssh, "read_channel", return_value="output\nswitch>")
        mocker.patch.object(ssh, "cleanup_stdout", return_value="output")
        ssh.execute_command("ls", expected_return_codes=None, custom_exception=CustomException)
        assert f"Return codes are ignored, passed exception: {CustomException} will be not raised." in caplog.text

    def test__add_discard_commands_windows(self, ssh):
        ssh._os_type = OSType.WINDOWS
        cmd = "command"
        assert ssh._add_discard_commands(cmd, discard_stdout=False, discard_stderr=False) == cmd
        assert ssh._add_discard_commands(cmd, discard_stdout=True, discard_stderr=False) == f"({cmd}) >nul"
        assert ssh._add_discard_commands(cmd, discard_stdout=False, discard_stderr=True) == f"({cmd}) 2>nul"
        assert ssh._add_discard_commands(cmd, discard_stdout=True, discard_stderr=True) == f"({cmd}) >nul 2>&1"

    def test__add_discard_commands_linux(self, ssh):
        ssh._os_type = OSType.POSIX
        cmd = "command"
        assert ssh._add_discard_commands(cmd, discard_stdout=False, discard_stderr=False) == cmd
        assert ssh._add_discard_commands(cmd, discard_stdout=True, discard_stderr=False) == f"{{ {cmd}; }} >/dev/null"
        assert ssh._add_discard_commands(cmd, discard_stdout=False, discard_stderr=True) == f"{{ {cmd}; }} 2>/dev/null"
        assert (
            ssh._add_discard_commands(cmd, discard_stdout=True, discard_stderr=True) == f"{{ {cmd}; }} >/dev/null 2>&1"
        )

        assert (
            ssh._add_discard_commands(f"{cmd} &", discard_stdout=True, discard_stderr=False)
            == f"{{ {cmd} & }} >/dev/null"
        )

    def test_get_os_name_returns_correct_os(self, ssh, mocker):
        mocker.patch.object(
            ssh,
            "execute_command",
            return_value=MagicMock(return_code=0, stdout="windows"),
        )
        result = ssh.get_os_name()
        assert result == OSName.WINDOWS

    def test_get_os_name_raises_os_not_supported(self, ssh, mocker):
        mocker.patch.object(ssh, "execute_command", return_value=MagicMock(return_code=1, stdout=""))
        with pytest.raises(OsNotSupported):
            ssh.get_os_name()

    def test_get_os_name_returns_mellanox(self, ssh, mocker):
        stdout = dedent("""\
        Product name:      MLNX-OS
        Product release:   3.6.3200
        Build ID:          #1-dev
        Build date:        2017-03-09 17:55:58
        Target arch:       x86_64
        Target hw:         x86_64
        Built by:          jenkins@e3f42965d5ee""")
        mocker.patch.object(ssh, "execute_command", return_value=MagicMock(return_code=0, stdout=stdout))
        result = ssh.get_os_name()
        assert result == OSName.MELLANOX

    def test_get_os_bitness_raises_not_implemented_error(self, ssh):
        with pytest.raises(NotImplementedError):
            ssh.get_os_bitness()

    def test_get_cpu_architecture_raises_not_implemented_error(self, ssh):
        with pytest.raises(NotImplementedError):
            ssh.get_cpu_architecture()

    def test_remote_property_returns_active_connection(self, ssh, mocker):
        mocker.patch.object(
            ssh._connection,
            "get_transport",
            return_value=mocker.Mock(is_active=mocker.Mock(return_value=True)),
        )
        result = ssh._remote
        assert result == ssh._connection

    def test_remote_property_reconnects_if_connection_not_active(self, ssh, mocker):
        mocker.patch.object(ssh._connection, "get_transport", return_value=False)
        mocker.patch.object(ssh, "_reconnect")
        result = ssh._remote
        assert result == ssh._connection
        ssh._reconnect.assert_called_once()

    def test_remote_property_reconnects_if_no_transport(self, ssh, mocker):
        mocker.patch.object(ssh._connection, "get_transport", return_value=None)
        mocker.patch.object(ssh, "_reconnect")
        result = ssh._remote
        assert result == ssh._connection
        ssh._reconnect.assert_called_once()

    def test_connect_successfully(self, ssh, mocker):
        mocker.patch.object(ssh._connection_tmp, "connect")
        mocker.patch.object(ssh._connection_tmp, "get_transport", return_value="connected")
        mocker.patch.object(ssh._connection_tmp, "invoke_shell")
        mocker.patch.object(ssh._connection, "settimeout")
        ssh._connect()
        ssh._connection_tmp.connect.assert_called_once_with(**ssh._connection_details, compress=True)
        ssh._connection_tmp.invoke_shell.assert_called_once_with(width=511, height=1000)
        ssh._connection.settimeout.assert_called_once_with(IO_TIMEOUT)

    def test_connect_with_awaiting_auth(self, ssh, mocker):
        mocker.patch.object(ssh._connection_tmp, "connect")
        mocker.patch.object(
            ssh._connection_tmp,
            "get_transport",
            return_value=mocker.Mock(__str__=mocker.Mock(return_value="awaiting auth")),
        )
        mocker.patch.object(ssh._connection_tmp, "invoke_shell")
        mocker.patch.object(ssh._connection, "settimeout")
        ssh._connect()
        ssh._connection_tmp.connect.assert_called_once_with(**ssh._connection_details, compress=True)
        ssh._connection_tmp.get_transport().auth_interactive_dumb.assert_called_once_with(
            ssh._connection_details["username"]
        )
        ssh._connection_tmp.invoke_shell.assert_called_once_with(width=511, height=1000)
        ssh._connection.settimeout.assert_called_once_with(IO_TIMEOUT)

    def test__str__(self, ssh):
        assert str(ssh) == "interactive_ssh"
