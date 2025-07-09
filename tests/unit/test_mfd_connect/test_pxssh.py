# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for pxssh tests."""

import platform

from subprocess import CalledProcessError
from unittest.mock import patch, Mock

import pytest
from mfd_typing.os_values import OSBitness, OSType, OSName

from mfd_connect import PxsshConnection
from mfd_connect.base import ConnectionCompletedProcess
from mfd_connect.exceptions import (
    PxsshException,
    OsNotSupported,
    ConnectionCalledProcessError,
    SSHReconnectException,
)


class TestPxsshConnection:
    """Tests of PxsshConnection."""

    CustomTestException = CalledProcessError

    @pytest.fixture()
    def pxssh(self):
        with patch.object(PxsshConnection, "__init__", return_value=None):
            pxssh = PxsshConnection(ip="10.10.10.10", username="", password="")
            pxssh._ip = "10.10.10.10"
            pxssh._username = ""
            pxssh._password = ""
            pxssh.cache_system_data = True
        return pxssh

    @pytest.fixture()
    def pxsshObj(self):
        pxsshObj = PxsshConnection(ip="10.10.10.10", username="", password="")
        pxsshObj._ip = "10.10.10.10"
        pxsshObj._username = ""
        pxsshObj._password = ""
        pxsshObj._prompts = "$"
        platform.system = Mock(return_value="windows")
        pxsshObj._connect = Mock(
            return_value=ConnectionCompletedProcess(return_code=None, args="command", stdout=None, stderr="stderr")
        )
        return pxsshObj

    @pytest.mark.skipif("Linux" not in platform.system(), reason="Skipping if not Linux.")
    def test_init_windows_exception(self, pxsshObj):
        platform.system = Mock(return_value="windows")
        with pytest.raises(PxsshException):
            PxsshConnection(ip="10.10.10.10", username="", password="")

    def test_get_os_type_os_not_supported(self, pxssh, mocker):
        pxssh.modules = mocker.Mock()
        pxssh._os_type = OSType.POSIX
        pxssh.enable_sudo()
        pxssh.execute_command = Mock(
            return_value=ConnectionCompletedProcess(return_code=1, args="command", stdout=None, stderr="stderr")
        )
        pxssh.cache_system_data = False
        with pytest.raises(OsNotSupported):
            pxssh.get_os_type()

    def test_get_os_type(self, pxssh):
        pxssh._os_type = OSType.POSIX
        pxssh.enable_sudo()
        pxssh.execute_command = Mock(
            return_value=ConnectionCompletedProcess(return_code=0, args="command", stdout=None, stderr="stderr")
        )
        pxssh.cache_system_data = False
        assert OSType.POSIX == pxssh.get_os_type()

    def test_get_os_name_os_not_supported(self, pxssh):
        pxssh._os_type = OSType.POSIX
        pxssh.enable_sudo()
        pxssh.execute_command = Mock(
            return_value=ConnectionCompletedProcess(
                return_code=1, args="command", stdout="UnknownOS\n", stderr="stderr"
            )
        )
        with pytest.raises(OsNotSupported):
            pxssh.get_os_name()

    def test_get_os_name_os(self, pxssh):
        pxssh._os_type = OSType.POSIX
        pxssh.enable_sudo()
        pxssh.execute_command = Mock(
            return_value=ConnectionCompletedProcess(return_code=1, args="command", stdout="Linux\n", stderr="stderr")
        )
        assert pxssh.get_os_name() == OSName.LINUX

    def test_get_os_bitness_os_not_supported(self, pxssh):
        pxssh._os_type = "Unknown OS"
        with pytest.raises(OsNotSupported):
            pxssh.get_os_bitness()

    @pytest.mark.parametrize("type_options", [OSType.POSIX])
    @pytest.mark.parametrize("architecture_options", ["amd64", "ia64", "x86_64"])
    def test_get_os_bitness_os_supported_64bit(self, pxssh, type_options, architecture_options):
        pxssh._os_type = type_options
        pxssh.execute_command = Mock(
            return_value=ConnectionCompletedProcess(
                return_code=0, args="command", stdout=architecture_options, stderr="stderr"
            )
        )
        assert pxssh.get_os_bitness() == OSBitness.OS_64BIT

    @pytest.mark.parametrize("type_options", [OSType.POSIX])
    @pytest.mark.parametrize("architecture_options", ["amd32", "ia32"])
    def test_get_os_bitness_os_supported_32bit(self, pxssh, type_options, architecture_options):
        pxssh._os_type = type_options
        pxssh.execute_command = Mock(
            return_value=ConnectionCompletedProcess(
                return_code=0, args="command", stdout=architecture_options, stderr="stderr"
            )
        )
        assert pxssh.get_os_bitness() == OSBitness.OS_32BIT

    def test_enable_sudo_posix(self, pxssh, mocker):
        pxssh._os_type = OSType.POSIX
        pxssh.enable_sudo()
        pxssh._exec_command = mocker.Mock(return_value=(None, None, None, 0))
        command = "sudo cmd arg1 arg2"
        pxssh.execute_command = Mock(
            return_value=ConnectionCompletedProcess(return_code=0, args=command, stdout=None, stderr="stderr")
        )
        assert pxssh.execute_command.return_value.args == "sudo cmd arg1 arg2"

    def test_enable_sudo_invalid_os_type(self, pxssh):
        pxssh._os_type = OSType.WINDOWS
        with pytest.raises(OsNotSupported, match=f"{pxssh._os_type} is not supported for enabling sudo!"):
            pxssh.enable_sudo()

    def test_disable_sudo(self, pxssh, mocker):
        pxssh._os_type = OSType.POSIX
        pxssh.enable_sudo()
        pxssh.disable_sudo()
        pxssh._exec_command = mocker.Mock(return_value=(None, None, None, 0))
        command = "cmd arg1 arg2"
        pxssh.execute_command = Mock(
            return_value=ConnectionCompletedProcess(return_code=0, args=command, stdout=None, stderr="stderr")
        )
        assert pxssh.execute_command.return_value.args == "cmd arg1 arg2"

    @pytest.mark.skipif("Linux" not in platform.system(), reason="Skipping if not Linux.")
    def test__connect(self, pxssh, mocker):
        pxssh.get_os_name = mocker.create_autospec(pxssh.get_os_name, return_value=OSName.LINUX)
        pxssh.get_os_type = mocker.create_autospec(pxssh.get_os_type, return_value=OSType.POSIX)
        pxssh._child = mocker.Mock()
        pxssh._child.expect = mocker.Mock(return_value=0)
        pxssh.get_os_name = mocker.Mock(return_value=OSName.LINUX)
        pxssh._os_type = mocker.Mock(return_value=OSType.POSIX)
        pxssh._process_classes = mocker.Mock(return_value=[OSName.LINUX])
        pxssh._connect()

    def test_execute_command_raise_custom_exception(self, pxssh, mocker):
        pxssh._exec_command = mocker.Mock(return_value=(None, None, None, 1))
        pxssh._adjust_command = mocker.Mock(return_value=("cmd arg1 arg2"))
        with pytest.raises(self.CustomTestException):
            pxssh.execute_command("cmd arg1 arg2", custom_exception=self.CustomTestException)

    def test_execute_command_not_raise_custom_exception(self, pxssh, mocker):
        pxssh._exec_command = mocker.Mock(return_value=(None, None, None, 1))
        pxssh._adjust_command = mocker.Mock(return_value=("cmd arg1 arg2"))
        ConnectionCalledProcessError(1, "ls")
        with pytest.raises(ConnectionCalledProcessError):
            pxssh.execute_command("cmd arg1 arg2", custom_exception=ConnectionCalledProcessError)

    def test_execute_command_success(self, pxssh):
        command = ("ip -br l").encode("ascii")
        expected_output = (
            "lo               UNKNOWN        00:00:00:00:00:00 <LOOPBACK,UP,LOWER_UP> \n"
            "eno1             UP             ac:1f:6b:91:f4:56 <BROADCAST,MULTICAST,UP,LOWER_UP> \n"
            "eno2             DOWN           ac:1f:6b:91:f4:57 <NO-CARRIER,BROADCAST,MULTICAST,UP> "
        ).encode("ascii")
        with patch.object(PxsshConnection, "_adjust_command", return_value=command) as mock_adjust_command:
            with patch.object(
                PxsshConnection, "_exec_command", return_value=(command, expected_output, "", 0)
            ) as mock_exec_command:
                pxssh.execute_command(command)
                mock_adjust_command.assert_called_once_with(command)
                mock_exec_command.assert_called_once_with(command, "", [])

    @pytest.mark.skipif("Linux" not in platform.system(), reason="Skipping if not Linux.")
    def test__exec_command_success(self, pxssh, mocker):
        pxssh.__init__ = mocker.create_autospec(pxssh.__init__, return_value=None)
        pxssh._child = mocker.Mock()
        pxssh._child.expect = mocker.Mock(return_value=0)
        pxssh._child.before = b"Command executed successfully"
        pxssh._child.signalstatus = None
        pxssh._child.exitstatus = 0
        command, stdout, signalstatus, exitstatus = pxssh._exec_command("ls", prompts=" $")
        pxssh._child.sendline.assert_called_once_with("ls")
        assert command == "ls"
        assert stdout == b"Command executed successfully"
        assert exitstatus == 0

    @pytest.mark.skipif("Linux" not in platform.system(), reason="Skipping if not Linux.")
    def test__exec_command_failure(self, pxssh, mocker):
        pxssh.__init__ = mocker.create_autospec(pxssh.__init__, return_value=None)
        pxssh._child = mocker.Mock()
        pxssh._child.expect = mocker.Mock(return_value=1)
        pxssh._child.prompts = mocker.Mock(return_value=0)
        pxssh._child.before = b"No prompt match for expected connection handle."
        pxssh._child.signalstatus = None
        pxssh._child.exitstatus = 0
        command, stdout, signalstatus, exitstatus = pxssh._exec_command("something", prompts=" $")
        pxssh._child.sendline.assert_called_once_with("something")
        assert command == "something"
        assert stdout == b"No prompt match for expected connection handle."
        assert exitstatus == 8

    @pytest.mark.skipif("Linux" not in platform.system(), reason="Skipping if not Linux.")
    def test__exec_command_error(self, pxssh, mocker):
        pxssh.__init__ = mocker.create_autospec(pxssh.__init__, return_value=None)
        pxssh._child = mocker.Mock()
        pxssh._child.expect = mocker.Mock(return_value=0)
        pxssh._child.before = b"FAILED, ERROR"
        pxssh._child.signalstatus = None
        pxssh._child.exitstatus = 0
        command, stdout, signalstatus, exitstatus = pxssh._exec_command("ls", prompts=" $")
        assert command == "ls"
        assert stdout == b"FAILED, ERROR"
        assert exitstatus == 5

    @pytest.mark.skipif("Linux" not in platform.system(), reason="Skipping if not Linux.")
    def test__exec_command_stderr_pipe(self, pxssh, mocker):
        pxssh.__init__ = mocker.create_autospec(pxssh.__init__, return_value=None)
        pxssh._child = mocker.Mock()
        pxssh._child.expect = mocker.Mock(return_value=0)
        pxssh._child.before = b"Command executed successfully"
        pxssh._child.signalstatus = None
        pxssh._child.exitstatus = 0
        pxssh._os_type = OSType.POSIX
        pxssh.enable_sudo()
        pxssh._exec_command = mocker.Mock(return_value=(None, None, b"backslashreplace", 0))
        pxssh.execute_command("cmd")

    @pytest.mark.skipif("Linux" not in platform.system(), reason="Skipping if not Linux.")
    def test__exec_command_custom_exception_expected_return_codes(self, pxssh, mocker):
        pxssh.__init__ = mocker.create_autospec(pxssh.__init__, return_value=None)
        pxssh._child = mocker.Mock()
        pxssh._child.expect = mocker.Mock(return_value=0)
        pxssh._child.before = b"Command executed successfully"
        pxssh._child.signalstatus = None
        pxssh._child.exitstatus = 0
        pxssh._os_type = OSType.POSIX
        pxssh.enable_sudo()
        pxssh._exec_command = mocker.Mock(return_value=(None, b"backslashreplace", None, 99))
        pxssh.execute_command("cmd", custom_exception=self.CustomTestException, expected_return_codes=[])

    @pytest.mark.skipif("Linux" not in platform.system(), reason="Skipping if not Linux.")
    def test__exec_command_ConnectionCalledProcessError(self, pxssh, mocker):
        pxssh.__init__ = mocker.create_autospec(pxssh.__init__, return_value=None)
        pxssh._child = mocker.Mock()
        pxssh._child.expect = mocker.Mock(return_value=0)
        pxssh._child.before = b"Command executed successfully"
        pxssh._child.signalstatus = None
        pxssh._child.exitstatus = 0
        pxssh._os_type = OSType.POSIX
        pxssh.enable_sudo()
        pxssh._exec_command = mocker.Mock(return_value=(None, None, None, None))
        with pytest.raises(ConnectionCalledProcessError):
            pxssh.execute_command("cmd")

    @pytest.mark.skipif("Linux" not in platform.system(), reason="Skipping if not Linux.")
    def test__exec_command_CustomTestException_no_expected_return(self, pxssh, mocker):
        pxssh.__init__ = mocker.create_autospec(pxssh.__init__, return_value=None)
        pxssh._child = mocker.Mock()
        pxssh._child.expect = mocker.Mock(return_value=0)
        pxssh._child.before = b"Command executed successfully"
        pxssh._child.signalstatus = None
        pxssh._child.exitstatus = 0
        pxssh._os_type = OSType.POSIX
        pxssh.enable_sudo()
        pxssh._exec_command = mocker.Mock(return_value=(None, None, None, None))
        with pytest.raises(self.CustomTestException):
            pxssh.execute_command("cmd", custom_exception=self.CustomTestException)

    @pytest.mark.skipif("Linux" not in platform.system(), reason="Skipping if not Linux.")
    def test__exec_command_custom_error(self, pxssh, mocker):
        pxssh.__init__ = mocker.create_autospec(pxssh.__init__, return_value=None)
        pxssh._child = mocker.Mock()
        pxssh._child.expect = mocker.Mock(return_value=0)
        custom_error_list = ["Custom Error", "Another Error"]
        pxssh._child.before = b"Operation resulted in Custom Error"
        pxssh._child.signalstatus = None
        pxssh._child.exitstatus = 0
        command, stdout, signalstatus, exitstatus = pxssh._exec_command(
            "ls", prompts=" $", error_list=custom_error_list
        )
        assert command == "ls"
        assert stdout == b"Operation resulted in Custom Error"
        assert exitstatus == 5

    def test__disconnect(self, pxssh, mocker):
        pxssh.__init__ = mocker.create_autospec(pxssh.__init__, return_value=None)
        pxssh._child = mocker.Mock()
        pxssh._child.close = mocker.Mock(return_value=0)
        pxssh._disconnect()

    def test__reconnect(self, pxssh, mocker):
        pxssh.__init__ = mocker.create_autospec(pxssh.__init__, return_value=None)
        pxssh._connect = mocker.Mock()
        pxssh._child = mocker.Mock()
        pxssh._reconnect()

    def test__reconnect_failure(self, pxssh, mocker):
        pxssh.__init__ = mocker.create_autospec(pxssh.__init__, return_value=None)
        pxssh._connect = mocker.Mock(return_value=0)
        pxssh._child = mocker.Mock(return_value=None)
        pxssh._child = None
        with pytest.raises(SSHReconnectException):
            pxssh._reconnect()

    def test__adjust_command(self, pxssh):
        pxssh._os_type = OSType.POSIX
        pxssh._os_type = OSType.POSIX
        pxssh.enable_sudo()
        cmd = "some cmd"
        assert pxssh._adjust_command(cmd) == "sudo " + cmd

    def test__adjust_command_disable_sudo(self, pxssh):
        pxssh._os_type = OSType.POSIX
        pxssh._os_type = OSType.POSIX
        pxssh.disable_sudo()
        cmd = "some cmd"
        assert pxssh._adjust_command(cmd) == cmd

    @pytest.mark.skipif("Linux" not in platform.system(), reason="Skipping if not Linux.")
    def test__exec_command_timeout(self, pxssh, mocker):
        pxssh.__init__ = mocker.create_autospec(pxssh.__init__, return_value=None)
        pxssh._child = mocker.Mock()
        pxssh._child.expect = mocker.Mock(return_value=2)
        command, stdout, signalstatus, exitstatus = pxssh._exec_command("timeout_command", prompts=" $")
        assert exitstatus == 8

    @pytest.mark.skipif("Linux" not in platform.system(), reason="Skipping if not Linux.")
    def test__exec_command_EOF(self, pxssh, mocker):
        pxssh.__init__ = mocker.create_autospec(pxssh.__init__, return_value=None)
        pxssh._child = mocker.Mock()
        pxssh._child.expect = mocker.Mock(return_value=1)
        command, stdout, signalstatus, exitstatus = pxssh._exec_command("EOF", prompts=" $")
        assert exitstatus == 8

    def test_start_process_exception(self, pxssh):
        with pytest.raises(NotImplementedError):
            pxssh.start_process(command="Some String")

    def test_start_processes_exception(self, pxssh):
        with pytest.raises(NotImplementedError):
            pxssh.start_processes(command="Some String")

    def test_path_exception(self, pxssh):
        with pytest.raises(NotImplementedError):
            pxssh.path()

    def test_restart_platform_exception(self, pxssh):
        with pytest.raises(NotImplementedError):
            pxssh.restart_platform()

    def test_shutdown_platform_exception(self, pxssh):
        with pytest.raises(NotImplementedError):
            pxssh.shutdown_platform()

    def test_wait_for_host_exception(self, pxssh):
        with pytest.raises(NotImplementedError):
            pxssh.wait_for_host()

    def test_disconnect_exception(self, pxssh):
        with pytest.raises(NotImplementedError):
            pxssh.disconnect()
