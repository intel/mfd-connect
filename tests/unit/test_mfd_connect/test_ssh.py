# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for ssh tests."""

import logging
import os
import random
import re
import sys
import time
from contextlib import nullcontext as does_not_raise
from pathlib import Path
from subprocess import CalledProcessError
from unittest.mock import patch, Mock, MagicMock

import paramiko
import pytest
from mfd_common_libs import log_levels
from mfd_common_libs.log_levels import MODULE_DEBUG
from mfd_typing.cpu_values import CPUArchitecture
from mfd_typing.os_values import OSBitness, OSType, OSName
from paramiko import AuthenticationException
from paramiko.channel import ChannelFile

import mfd_connect
from mfd_connect import SSHConnection
from mfd_connect.base import ConnectionCompletedProcess
from mfd_connect.exceptions import (
    OsNotSupported,
    ConnectionCalledProcessError,
    SSHReconnectException,
    RemoteProcessTimeoutExpired,
    CPUArchitectureNotSupported,
)


class TestSSHConnection:
    """Tests of SSHConnection."""

    CustomTestException = CalledProcessError

    @pytest.fixture()
    def ssh(self):
        with patch.object(SSHConnection, "__init__", return_value=None):
            ssh = SSHConnection(username="root", password="***", ip="10.10.10.10")
            ssh._connection_details = {"hostname": "10.10.10.10", "port": 22, "username": "root", "password": "root"}
            ssh._ip = "10.10.10.10"
            ssh._default_timeout = None
            ssh.cache_system_data = True
            ssh.disable_sudo()
            return ssh

    def test_get_os_bitness_os_not_supported(self, ssh):
        ssh._os_type = "Unknown"
        with pytest.raises(OsNotSupported):
            ssh.get_os_bitness()

    @pytest.mark.parametrize("type_options", [OSType.WINDOWS, OSType.POSIX])
    @pytest.mark.parametrize("architecture_options", ["dunno"])
    def test_get_os_bitness_os_arch_not_supported(self, ssh, type_options, architecture_options):
        ssh._os_type = type_options
        ssh.execute_command = Mock(
            return_value=ConnectionCompletedProcess(
                return_code=0, args="command", stdout=architecture_options, stderr="stderr"
            )
        )
        with pytest.raises(OsNotSupported):
            ssh.get_os_bitness()

    @pytest.mark.parametrize("type_options", [OSType.WINDOWS, OSType.POSIX])
    @pytest.mark.parametrize("architecture_options", ["amd64", "ia64", "x86_64"])
    def test_get_os_bitness_os_supported_64bit(self, ssh, type_options, architecture_options):
        ssh._os_type = type_options
        ssh.execute_command = Mock(
            return_value=ConnectionCompletedProcess(
                return_code=0, args="command", stdout=architecture_options, stderr="stderr"
            )
        )
        assert ssh.get_os_bitness() == OSBitness.OS_64BIT

    @pytest.mark.parametrize("type_options", [OSType.WINDOWS, OSType.POSIX])
    @pytest.mark.parametrize("architecture_options", ["i386", "i586", "x86", "ia32", "armv7l", "arm"])
    def test_get_os_bitness_os_supported_32bit(self, ssh, type_options, architecture_options):
        ssh._os_type = type_options
        ssh.execute_command = Mock(
            return_value=ConnectionCompletedProcess(
                return_code=0, args="command", stdout=architecture_options, stderr="stderr"
            )
        )
        assert ssh.get_os_bitness() == OSBitness.OS_32BIT

    @pytest.mark.parametrize("type_options", [OSType.WINDOWS, OSType.POSIX])
    def test_get_os_bitness_os_supported_aarch64(self, ssh, type_options):
        ssh._os_type = type_options
        ssh.execute_command = Mock(
            return_value=ConnectionCompletedProcess(return_code=0, args="command", stdout="aarch64", stderr="stderr")
        )
        assert ssh.get_os_bitness() == OSBitness.OS_64BIT

    @pytest.mark.parametrize("type_options", [OSType.WINDOWS, OSType.POSIX])
    def test_get_cpu_architecture_aarch64(self, ssh, type_options):
        ssh._os_type = type_options
        ssh.execute_command = Mock(
            return_value=ConnectionCompletedProcess(return_code=0, args="command", stdout="aarch64", stderr="stderr")
        )
        assert ssh.get_cpu_architecture() == CPUArchitecture.ARM64

    @pytest.mark.parametrize("type_options", [OSType.WINDOWS, OSType.POSIX])
    @pytest.mark.parametrize("architecture_options", ["i386", "i586", "x86", "ia32"])
    def test_get_cpu_architecture_x86(self, ssh, type_options, architecture_options):
        ssh._os_type = type_options
        ssh.execute_command = Mock(
            return_value=ConnectionCompletedProcess(
                return_code=0, args="command", stdout=architecture_options, stderr="stderr"
            )
        )
        assert ssh.get_cpu_architecture() == CPUArchitecture.X86

    @pytest.mark.parametrize("type_options", [OSType.WINDOWS, OSType.POSIX])
    @pytest.mark.parametrize("architecture_options", ["armv7l", "arm"])
    def test_get_cpu_architecture_ARM(self, ssh, type_options, architecture_options):
        ssh._os_type = type_options
        ssh.execute_command = Mock(
            return_value=ConnectionCompletedProcess(
                return_code=0, args="command", stdout=architecture_options, stderr="stderr"
            )
        )
        assert ssh.get_cpu_architecture() == CPUArchitecture.ARM

    @pytest.mark.parametrize("type_options", [OSType.WINDOWS, OSType.POSIX])
    @pytest.mark.parametrize("architecture_options", ["amd64", "ia64", "x86_64"])
    def test_get_cpu_architecture_XH86_64(self, ssh, type_options, architecture_options):
        ssh._os_type = type_options
        ssh.execute_command = Mock(
            return_value=ConnectionCompletedProcess(
                return_code=0, args="command", stdout=architecture_options, stderr="stderr"
            )
        )
        assert ssh.get_cpu_architecture() == CPUArchitecture.X86_64

    @pytest.mark.parametrize("type_options", [OSType.WINDOWS, OSType.POSIX])
    @pytest.mark.parametrize("architecture_options", ["dunno"])
    def test_get_cpu_architecture_not_supported(self, ssh, type_options, architecture_options):
        ssh._os_type = type_options
        ssh.execute_command = Mock(
            return_value=ConnectionCompletedProcess(
                return_code=0, args="command", stdout=architecture_options, stderr="stderr"
            )
        )
        with pytest.raises(CPUArchitectureNotSupported):
            ssh.get_cpu_architecture()

    @pytest.mark.parametrize("type_options", [OSType.WINDOWS, OSType.POSIX])
    def test_get_os_bitness_os_supported_non_expected_bitness(self, ssh, type_options):
        ssh._os_type = type_options
        ssh.execute_command = Mock(
            return_value=ConnectionCompletedProcess(return_code=0, args="command", stdout="2-bit", stderr="stderr")
        )
        with pytest.raises(OsNotSupported):
            ssh.get_os_bitness()

    @pytest.mark.parametrize("type_options", [OSType.WINDOWS, OSType.POSIX])
    def test_get_os_type(self, ssh, type_options):
        ssh._os_type = type_options
        if type_options == OSType.WINDOWS:
            ssh.execute_command = Mock(
                return_value=ConnectionCompletedProcess(
                    return_code=0, args="command", stdout="Microsoft Windows", stderr="stderr"
                )
            )
            assert ssh.get_os_type() == OSType.WINDOWS
        else:
            ssh.execute_command = Mock(
                side_effect=[
                    ConnectionCompletedProcess(
                        return_code=1, args="command", stdout="unrecognized command", stderr="stderr"
                    ),
                    ConnectionCompletedProcess(return_code=0, args="command", stdout="Linux", stderr="stderr"),
                ]
            )
            assert ssh.get_os_type() == OSType.POSIX

    @pytest.mark.parametrize("type_options", [OSType.WINDOWS, OSType.POSIX])
    def test_get_os_name(self, ssh, type_options):
        ssh._os_type = type_options
        if type_options == OSType.WINDOWS:
            ssh.execute_command = Mock(
                return_value=ConnectionCompletedProcess(
                    return_code=0, args="command", stdout="Microsoft Windows 11 Enterprise", stderr="stderr"
                )
            )
            assert ssh.get_os_name() == OSName.WINDOWS
        else:
            ssh.execute_command = Mock(
                side_effect=[
                    ConnectionCompletedProcess(
                        return_code=1, args="command", stdout="unrecognized command", stderr="stderr"
                    ),
                    ConnectionCompletedProcess(return_code=0, args="command", stdout="Linux", stderr="stderr"),
                ]
            )
            assert ssh.get_os_name() == OSName.LINUX

    cwd_test_params = {"random_name": "1231", "command_to_send": "ls", "cwd_folder": "folder"}

    @pytest.mark.parametrize(
        "type_options, correct_command",
        [
            (
                OSType.WINDOWS,
                f'title {cwd_test_params["random_name"]} && cd {cwd_test_params["cwd_folder"]} '
                f'&& {cwd_test_params["command_to_send"]}',
            ),
            (
                OSType.POSIX,
                f'cd {cwd_test_params["cwd_folder"]}; {cwd_test_params["command_to_send"]} '
                f'&& true {cwd_test_params["random_name"]}',
            ),
        ],
    )
    def test__start_process_cwd(self, ssh, mocker, type_options, correct_command):
        random_cache = random.random
        ssh._os_type = type_options
        random.random = mocker.Mock(return_value=self.cwd_test_params["random_name"])
        ssh._connection = Mock()
        ssh.SSHClient = mocker.Mock()
        ssh._start_process(command=self.cwd_test_params["command_to_send"], cwd=self.cwd_test_params["cwd_folder"])
        ssh._connection.get_transport().open_session().exec_command.assert_called_once_with(correct_command)
        random.random = random_cache

    def test__exec_command_cwd(self, ssh, mocker):
        random_cache = random.random
        random.random = mocker.Mock()
        random.random.return_value = "random_name"
        ssh._os_type = OSType.WINDOWS
        ssh._connection = mocker.Mock()
        ssh.SSHClient = mocker.Mock()

        correct_command = (
            f'title random_name && cd {self.cwd_test_params["cwd_folder"]} '
            f'&& {self.cwd_test_params["command_to_send"]}'
        )
        ssh._exec_command(
            command=self.cwd_test_params["command_to_send"], cwd=self.cwd_test_params["cwd_folder"], input_data=None
        )
        ssh._connection.get_transport().open_session().exec_command.assert_called_once_with(correct_command)
        random.random = random_cache

    def test_wait_for_host(self, ssh, mocker):
        ssh._connection = mocker.Mock()
        ssh.SSHClient = mocker.Mock()
        ssh._connection.get_transport().is_active().return_value = True
        ssh._connect = mocker.Mock(side_effect=[OSError, AuthenticationException, None])
        time.sleep = mocker.Mock(return_value=None)
        ssh.wait_for_host(10)

    def test_wait_for_host_fail(self, ssh, mocker):
        ssh._connection = mocker.Mock()
        ssh.SSHClient = mocker.Mock()
        ssh._connect = mocker.Mock(side_effect=OSError)
        time.sleep = mocker.Mock(return_value=None)
        with pytest.raises(TimeoutError):
            ssh.wait_for_host(1)

    @pytest.mark.skipif(os.name == "nt", reason="Sighup doesn't exist on Windows, test is not required.")
    def test_send_command_and_disconnect_platform_with_sighup(self, ssh, mocker):
        time.sleep = mocker.Mock(return_value=None)
        ssh._connection = mocker.Mock()
        ssh.SSHClient = mocker.Mock()
        ssh.disconnect = mocker.Mock()
        e = ConnectionCalledProcessError(-1, "ls")
        ssh.execute_command = mocker.Mock(side_effect=e)
        ssh.send_command_and_disconnect_platform("")

    def test_send_command_and_disconnect_platform(self, ssh, mocker):
        time.sleep = mocker.Mock(return_value=None)
        ssh._connection = mocker.Mock()
        ssh.SSHClient = mocker.Mock()
        ssh.disconnect = mocker.Mock()
        ssh.execute_command = mocker.Mock()
        ssh.send_command_and_disconnect_platform("")

    def test_send_command_and_disconnect_platform_fail(self, ssh, mocker):
        time.sleep = mocker.Mock()
        time.sleep.return_value = None
        ssh._connection = mocker.Mock()
        ssh.SSHClient = mocker.Mock()
        e = ConnectionCalledProcessError(1, "ls")
        ssh.execute_command = mocker.Mock(side_effect=e)
        with pytest.raises(ConnectionCalledProcessError):
            ssh.send_command_and_disconnect_platform("")

    @pytest.mark.parametrize("e", [RemoteProcessTimeoutExpired(), ConnectionResetError()])
    def test_send_command_and_disconnect_platform_timeout_or_conn_reset(self, ssh, mocker, e):
        time.sleep = mocker.Mock()
        time.sleep.return_value = None
        ssh._connection = mocker.Mock()
        ssh.SSHClient = mocker.Mock()
        ssh.execute_command = mocker.Mock(side_effect=e)
        with does_not_raise():
            ssh.send_command_and_disconnect_platform("")

    def test___reconnect_successful(self, ssh, mocker):
        log_debug = mocker.patch("mfd_connect.ssh.logger.log")
        ssh._connect = mocker.Mock()
        ssh._connection = mocker.create_autospec(mfd_connect.ssh.SSHClient)
        ssh._connection.get_transport = mocker.Mock(return_value=mocker.Mock(is_active=mocker.Mock(return_value=True)))
        ssh._reconnect()
        log_debug.assert_called_with(level=log_levels.MODULE_DEBUG, msg="Reconnection successful.")

    def test___reconnect_failed(self, ssh, mocker):
        log_debug = mocker.patch("mfd_connect.ssh.logger.log")
        ssh._connect = mocker.Mock()
        ssh._connection = mocker.create_autospec(mfd_connect.ssh.SSHClient)
        ssh._connection.get_transport = mocker.Mock(return_value=mocker.Mock(is_active=mocker.Mock(return_value=False)))
        with pytest.raises(SSHReconnectException):
            ssh._reconnect()
        log_debug.assert_called_with(level=log_levels.MODULE_DEBUG, msg="Connection lost.")

    def test__connection_check_and_reconnect_transport_is_active(self, ssh, mocker):
        ssh._connection = mocker.create_autospec(mfd_connect.ssh.SSHClient)
        ssh._connection.get_transport = mocker.Mock(return_value=mocker.Mock(is_active=mocker.Mock(return_value=True)))
        ssh._reconnect = mocker.Mock()
        ssh._remote()
        ssh._reconnect.assert_not_called()

    def test__connection_check_and_reconnect_transport_is_not_active(self, ssh, mocker):
        ssh._connection = mocker.create_autospec(mfd_connect.ssh.SSHClient)
        ssh._connection.get_transport = mocker.Mock(return_value=mocker.Mock(is_active=mocker.Mock(return_value=False)))
        ssh._reconnect = mocker.Mock()
        ssh._remote()
        ssh._reconnect.assert_called_once()

    def test_execute_command_raise_custom_exception(self, ssh, mocker):
        ssh._exec_command = mocker.Mock(return_value=(None, None, None, 1))
        with pytest.raises(self.CustomTestException):
            ssh.execute_command("cmd arg1 arg2", custom_exception=self.CustomTestException)

    def test_execute_command_not_raise_custom_exception(self, ssh, mocker):
        ssh._exec_command = mocker.Mock(return_value=(None, None, None, 0))
        ssh.execute_command("cmd arg1 arg2", custom_exception=self.CustomTestException)

    def test_execute_command_with_reconnect_success(self, ssh, mocker):
        ssh._verify_command_correctness = mocker.Mock()
        ssh._adjust_command = mocker.Mock(return_value="test_command")
        ssh._exec_command = mocker.Mock(side_effect=[EOFError, (None, None, None, 0)])
        ssh.handle_execution_reconnect = mocker.Mock()

        result = ssh.execute_command("test_command")
        ssh.handle_execution_reconnect.assert_called_once()

        ssh._exec_command.assert_any_call(
            "test_command",
            input_data=None,
            cwd=None,
            timeout=None,
            environment=None,
            stderr_to_stdout=False,
            discard_stdout=False,
            discard_stderr=False,
            get_pty=False,
        )
        assert result.return_code == 0

    def test_execute_command_skip_logging_provided(self, ssh, mocker, caplog):
        caplog.set_level(0)
        channel = mocker.create_autospec(ChannelFile)
        channel.read.return_value = b"someoutput"
        ssh._exec_command = mocker.Mock(return_value=(None, channel, channel, 0))
        ssh.execute_command("cmd arg1 arg2", skip_logging=True)
        assert not any("someoutput" in msg for msg in caplog.messages)

        ssh.execute_command("cmd arg1 arg2", skip_logging=False)
        assert len([msg for msg in caplog.messages if "someoutput" in msg]) == 2  # stdout + stderr log

    def test_execute_command_get_pty_warning(self, ssh, mocker, caplog):
        caplog.set_level(0)
        ssh._exec_command = mocker.Mock(return_value=(None, None, None, 0))
        ssh.execute_command("cmd arg1 arg2", get_pty=True)
        assert next(("pseudo-terminal" in msg for msg in caplog.messages), None) is not None

    def test_connect_additional_auth(self, ssh, mocker, caplog):
        caplog.set_level(logging.DEBUG)
        ssh._connection = mocker.create_autospec(mfd_connect.ssh.SSHClient)
        ssh._connection.get_transport().__str__.return_value = (
            "<paramiko.Transport at 0x7808aa08 (cipher aes128-ctr, " "128 bits) (connected; awaiting auth)>"
        )
        ssh.get_os_name = mocker.create_autospec(ssh.get_os_name, return_value=OSName.LINUX)
        ssh.get_os_type = mocker.create_autospec(ssh.get_os_type, return_value=OSType.POSIX)
        ssh._connect()
        ssh._connection.get_transport().auth_interactive_dumb.assert_called_with("root")
        ssh.get_os_name.assert_called()
        assert ["SSH server requested additional authentication"] == [rec.message for rec in caplog.records]

    def test_connect(self, ssh, mocker):
        ssh._connection = mocker.create_autospec(mfd_connect.ssh.SSHClient)
        ssh._connection.get_transport().__str__.return_value = (
            "<paramiko.Transport at 0xbd6b0888 (cipher aes128-ctr, " "128 bits) (active; 0 open channel(s))>"
        )
        ssh.get_os_name = mocker.create_autospec(ssh.get_os_name, return_value=OSName.LINUX)
        ssh.get_os_type = mocker.create_autospec(ssh.get_os_type, return_value=OSType.POSIX)
        ssh._connect()
        ssh.get_os_name.assert_called()

    def test_str_function(self, ssh):
        assert str(ssh) == "ssh"

    def test_enable_sudo_posix(self, ssh, mocker):
        ssh._os_type = OSType.POSIX
        ssh.enable_sudo()
        ssh._exec_command = mocker.Mock(return_value=(None, None, None, 0))
        ssh._connection = mocker.create_autospec(mfd_connect.ssh.SSHClient)
        completed_process = ssh.execute_command("cmd arg1 arg2", custom_exception=self.CustomTestException)
        assert completed_process.args == "sudo cmd arg1 arg2"

    def test_enable_sudo_echo_cmd(self, ssh, mocker):
        ssh._os_type = OSType.POSIX
        ssh.enable_sudo()
        ssh._exec_command = mocker.Mock(return_value=(None, None, None, 0))
        ssh._connection = mocker.create_autospec(mfd_connect.ssh.SSHClient)
        completed_process = ssh.execute_command("echo arg > /some/restricted/path")
        assert completed_process.args == 'sudo sh -c "echo arg > /some/restricted/path"'

    def test_enable_sudo_invalid_os_type(self, ssh):
        ssh._os_type = OSType.WINDOWS
        with pytest.raises(OsNotSupported, match=f"{ssh._os_type} is not supported for enabling sudo!"):
            ssh.enable_sudo()

    def test_disable_sudo(self, ssh, mocker):
        ssh._os_type = OSType.POSIX
        ssh.enable_sudo()
        ssh.disable_sudo()
        ssh._exec_command = mocker.Mock(return_value=(None, None, None, 0))
        ssh._connection = mocker.create_autospec(mfd_connect.ssh.SSHClient)
        completed_process = ssh.execute_command("cmd arg1 arg2", custom_exception=self.CustomTestException)
        assert completed_process.args == "cmd arg1 arg2"

    def test_ip_property(self, ssh):
        assert ssh.ip == "10.10.10.10"

    def test_init_with_model(self, mocker):
        mocker.patch("paramiko.SSHClient", return_value=mocker.Mock())
        mocker.patch(
            "mfd_connect.SSHConnection._connect",
        )
        mocker.patch(
            "mfd_connect.SSHConnection.log_connected_host_info",
        )
        model = mocker.Mock()
        obj = SSHConnection(ip="10.10.10.10", model=model, username="", password="")
        assert obj.model == model
        obj = SSHConnection(ip="10.10.10.10", username="", password="")
        assert obj.model is None

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

    def test__terminate_command_after_timeout(self, ssh, mocker):
        time.sleep = mocker.Mock()
        mocker.patch("mfd_common_libs.timeout_counter.TimeoutCounter.__bool__", return_value=True)

        chan = mocker.create_autospec(paramiko.Channel)
        chan.exit_status_ready.return_value = False
        ssh._process_class = mocker.Mock()

        with pytest.raises(RemoteProcessTimeoutExpired):
            ssh._terminate_command_after_timeout("cmd", 1, chan, None, None, None, 0.123)
        chan.close.assert_called_once()
        ssh._process_class().kill.assert_called_once()

    def test__verify_command_correctness(self, ssh):
        ssh._verify_command_correctness("echo pid")
        with pytest.raises(ValueError, match="Command contains not allowed characters"):
            ssh._verify_command_correctness("echo pid\n")
        with pytest.raises(ValueError, match="Command contains not allowed characters"):
            ssh._verify_command_correctness("echo pid\r ")
        with pytest.raises(ValueError, match="Command contains not allowed characters"):
            ssh._verify_command_correctness("echo pid |")

    def test_execute_command_invalid_character_check(self, ssh):
        with pytest.raises(ValueError, match="Command contains not allowed characters"):
            ssh.execute_command("cmd arg1 arg2;")

    @pytest.fixture()
    def ssh_conn_with_timeout(self):
        with patch.object(SSHConnection, "__init__", return_value=None):
            ssh = SSHConnection(username="root", password="***", ip="10.10.10.10")
            ssh._connection_details = {"hostname": "10.10.10.10", "port": 22, "username": "root", "password": "root"}
            ssh._ip = "10.10.10.10"
            ssh._default_timeout = 1
            ssh.cache_system_data = True
            ssh.disable_sudo()
            return ssh

    def test_execute_with_timeout(self, ssh_conn_with_timeout, ssh, mocker):
        ssh_conn_with_timeout._exec_command = mocker.create_autospec(
            ssh_conn_with_timeout._exec_command, return_value=(None, None, None, 0)
        )
        ssh._exec_command = mocker.create_autospec(ssh._exec_command, return_value=(None, None, None, 0))
        ssh_conn_with_timeout.execute_command("ping localhost")
        ssh.execute_command("ping localhost")

        ssh_conn_with_timeout._exec_command.assert_called_with(
            "ping localhost",
            cwd=None,
            discard_stderr=False,
            discard_stdout=False,
            environment=None,
            get_pty=False,
            input_data=None,
            stderr_to_stdout=False,
            timeout=1,
        )
        ssh._exec_command.assert_called_with(
            "ping localhost",
            cwd=None,
            discard_stderr=False,
            discard_stdout=False,
            environment=None,
            get_pty=False,
            input_data=None,
            stderr_to_stdout=False,
            timeout=None,
        )

    def test_restart_platform_ssh(self, ssh, mocker):
        ssh._os_type = OSType.POSIX
        ssh._connection = mocker.create_autospec(mfd_connect.ssh.SSHClient)
        ssh.send_command_and_disconnect_platform = mocker.Mock()
        ssh.restart_platform()
        ssh.send_command_and_disconnect_platform.assert_called_with(
            "shutdown -r now",
        )

    def test_shutdown_platform_ssh_no_sudo(self, ssh, mocker):
        ssh._os_type = OSType.POSIX
        ssh.disable_sudo()
        ssh.send_command_and_disconnect_platform = mocker.Mock()
        ssh.shutdown_platform()
        ssh.send_command_and_disconnect_platform.assert_called_with("shutdown -h now")

    def test_shutdown_platform_ssh_sudo(self, ssh, mocker):
        ssh._os_type = OSType.POSIX
        ssh.enable_sudo()
        ssh.send_command_and_disconnect_platform = mocker.Mock()
        ssh.shutdown_platform()
        ssh.send_command_and_disconnect_platform.assert_called_with("sudo shutdown -h now")

    def test_handle_execution_reconnect_success(self, ssh, mocker):
        time.sleep = mocker.Mock(return_value=None)
        ssh._reconnect = mocker.Mock()
        ssh._exec_command = mocker.Mock(return_value=(None, None, None, 0))
        ssh.handle_execution_reconnect("test_command")
        ssh._reconnect.assert_called_once()
        ssh._exec_command.assert_called_once_with(
            "hostname",
            input_data=None,
            cwd=None,
            timeout=None,
            environment=None,
            stderr_to_stdout=False,
            discard_stdout=False,
            discard_stderr=False,
            get_pty=False,
        )

    def test_handle_execution_reconnect_fail_success(self, ssh, mocker):
        time.sleep = mocker.Mock(return_value=None)
        ssh._reconnect = mocker.Mock(side_effect=[SSHReconnectException, None])
        ssh._exec_command = mocker.Mock(return_value=(None, None, None, 0))
        ssh.handle_execution_reconnect("test_command")
        ssh._exec_command.assert_called_once_with(
            "hostname",
            input_data=None,
            cwd=None,
            timeout=None,
            environment=None,
            stderr_to_stdout=False,
            discard_stdout=False,
            discard_stderr=False,
            get_pty=False,
        )
        assert ssh._reconnect.call_count == 2
        assert ssh._exec_command.call_count == 1

    def test_handle_execution_reconnect_success_test_cmd_fail_success(self, ssh, mocker):
        time.sleep = mocker.Mock(return_value=None)
        ssh._reconnect = mocker.Mock()
        ssh._exec_command = mocker.Mock(side_effect=[SSHReconnectException, (None, None, None, 0)])
        ssh.handle_execution_reconnect("test_command")
        ssh._exec_command.assert_any_call(
            "hostname",
            input_data=None,
            cwd=None,
            timeout=None,
            environment=None,
            stderr_to_stdout=False,
            discard_stdout=False,
            discard_stderr=False,
            get_pty=False,
        )
        assert ssh._reconnect.call_count == 2
        assert ssh._exec_command.call_count == 2

    def test_handle_execution_reconnect_success_test_cmd_fail(self, ssh, mocker):
        time.sleep = mocker.Mock(return_value=None)
        ssh._reconnect = mocker.Mock()
        ssh._exec_command = mocker.Mock(
            side_effect=[SSHReconnectException, SSHReconnectException, SSHReconnectException, SSHReconnectException]
        )

        with pytest.raises(ConnectionCalledProcessError):
            ssh.handle_execution_reconnect("test_command", reconnect_attempts=2)

        ssh._exec_command.assert_any_call(
            "hostname",
            input_data=None,
            cwd=None,
            timeout=None,
            environment=None,
            stderr_to_stdout=False,
            discard_stdout=False,
            discard_stderr=False,
            get_pty=False,
        )
        assert ssh._reconnect.call_count == 2
        assert ssh._exec_command.call_count == 2

    def test_download_file_from_url_windows_ssh_no_supported(self, ssh, mocker):
        ssh.get_os_name = mocker.Mock(return_value=OSName.WINDOWS)
        with pytest.raises(
            OsNotSupported, match=re.escape("Downloading files from URL on Windows is not supported for SSHConnection.")
        ):
            ssh.download_file_from_url("http://url.com", Path("something.txt"), username="***", password="***")

    def test_download_file_from_url(self, ssh, mocker, caplog):
        caplog.set_level(MODULE_DEBUG)
        ssh.get_os_name = mocker.Mock(return_value=OSName.LINUX)
        mock_download_func = mocker.patch(
            "mfd_connect.base.download_file_unix", return_value=mocker.Mock(return_code=0, stdout="")
        )
        ssh._manage_temporary_envs = mocker.Mock()
        ssh._generate_random_string = mocker.Mock(return_value="9yDOrm4D")
        path = Path("/path/to/destination")
        ssh.download_file_from_url("http://url.com", path, username="***", password="***")

        mock_download_func.assert_called_once_with(
            connection=ssh,
            url="http://url.com",
            destination_file=path,
            options=" -u ***:*** ",
        )
        assert (
            "hide_credentials flag is not supported for SSHConnection. For continue execution, "
            "the flag will be forced to be set on False."
        ) in caplog.text

    def test_download_file_from_url_no_hidden_creds(self, ssh, mocker, caplog):
        caplog.set_level(MODULE_DEBUG)
        ssh.get_os_name = mocker.Mock(return_value=OSName.LINUX)
        mock_download_func = mocker.patch(
            "mfd_connect.base.download_file_unix", return_value=mocker.Mock(return_code=0, stdout="")
        )
        ssh._manage_temporary_envs = mocker.Mock()
        ssh._generate_random_string = mocker.Mock(return_value="9yDOrm4D")
        path = Path("/path/to/destination")
        ssh.download_file_from_url("http://url.com", path, username="***", password="***", hide_credentials=False)

        mock_download_func.assert_called_once_with(
            connection=ssh,
            url="http://url.com",
            destination_file=path,
            options=" -u ***:*** ",
        )
        assert (
            "hide_credentials flag is not supported for SSHConnection. For continue execution, "
            "the flag will be forced to be set on False."
        ) not in caplog.text

    class TestSSHConnectionStartProcess:
        """Tests for SSHConnection start_process method."""

        @pytest.fixture()
        def ssh(self):
            with patch("mfd_connect.ssh.SSHConnection.__init__", return_value=None):
                ssh = SSHConnection.__new__(SSHConnection)
                ssh._ip = "10.10.10.10"
                ssh._verify_command_correctness = MagicMock()
                ssh._adjust_command = MagicMock(side_effect=lambda x: x)
                ssh._process_class = MagicMock()
                ssh._start_process = MagicMock(return_value=(None, None, None, "unique_name", None))
                return ssh

        def test_start_process_calls_prepare_log_file(self, ssh):
            with patch.object(ssh, "_prepare_log_file", return_value=None) as prepare_log_file_mock:
                ssh.start_process(
                    command="ls",
                    cwd=None,
                    env=None,
                    stderr_to_stdout=False,
                    discard_stdout=False,
                    discard_stderr=False,
                    cpu_affinity=None,
                    shell=False,
                    enable_input=False,
                    log_file=True,
                    output_file=None,
                    get_pty=False,
                )
                prepare_log_file_mock.assert_called_once()

        def test_start_process_sets_log_file_true_if_log_path(self, ssh):
            # Patch _prepare_log_file to return a dummy log_path
            with patch.object(ssh, "_prepare_log_file", return_value="dummy_log_path") as prepare_log_file_mock:
                # log_file is initially False, but should be set to True if log_path is not None
                ssh.start_process(
                    command="ls",
                    cwd=None,
                    env=None,
                    stderr_to_stdout=False,
                    discard_stdout=False,
                    discard_stderr=False,
                    cpu_affinity=None,
                    shell=False,
                    enable_input=False,
                    log_file=False,
                    output_file=None,
                    get_pty=False,
                )
                prepare_log_file_mock.assert_called_once()

        def test_path_python_313plus(self, monkeypatch, ssh, mocker):
            # Simulate Python 3.13+
            ssh.cache_system_data = mocker.Mock()
            monkeypatch.setattr(sys, "version_info", (3, 13, 0))
            cpf = mocker.patch("mfd_connect.ssh.custom_path_factory", return_value="custom_path")
            result = ssh.path("foo", bar=1)
            assert result == "custom_path"
            cpf.assert_called_once()
            # owner should be injected as self
            assert cpf.call_args.kwargs["owner"] is ssh

        def test_path_python_pre313(self, monkeypatch, ssh, mocker):
            # Simulate Python < 3.13
            ssh.cache_system_data = mocker.Mock()
            monkeypatch.setattr(sys, "version_info", (3, 10, 0))
            cp = mocker.patch("mfd_connect.ssh.CustomPath", return_value="custom_path")
            result = ssh.path("foo", bar=1)
            assert result == "custom_path"
            cp.assert_called_once()
            # owner should be injected as self
            assert cp.call_args.kwargs["owner"] is ssh
