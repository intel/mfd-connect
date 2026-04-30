# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: MIT
"""Unit tests for execute_command_as_user on RPyCConnection."""

from unittest.mock import patch, MagicMock

import pytest
from mfd_typing.os_values import OSName, OSType

from mfd_connect import RPyCConnection
from mfd_connect.exceptions import RunAsUserError, RunAsUserNotSupportedError


class TestExecuteCommandAsUser:
    """Tests for RPyCConnection.execute_command_as_user."""

    @pytest.fixture()
    def rpyc(self, mocker):
        with patch.object(RPyCConnection, "__init__", return_value=None):
            conn = RPyCConnection(ip="10.10.10.10")
            conn._ip = "10.10.10.10"
            conn._os_type = conn._cached_os_type = OSType.POSIX
            conn._default_timeout = None
            conn.path_extension = None
            conn.cache_system_data = True
            return conn

    def test_posix_with_password_uses_sudo_S(self, rpyc, mocker):
        rpyc.get_os_name = mocker.Mock(return_value=OSName.LINUX)
        rpyc.execute_command = mocker.Mock()
        rpyc.execute_command_as_user(
            "/bin/tool -i -l",
            user="qv_user",
            password="secret",
        )
        called_cmd = rpyc.execute_command.call_args[0][0]
        called_kwargs = rpyc.execute_command.call_args[1]
        assert called_cmd.startswith("sudo -S -p '' -u qv_user --")
        assert "/bin/tool -i -l" in called_cmd
        assert called_kwargs["input_data"] == "secret\n"

    def test_posix_without_password_uses_sudo_n(self, rpyc, mocker):
        rpyc.get_os_name = mocker.Mock(return_value=OSName.FREEBSD)
        rpyc.execute_command = mocker.Mock()
        rpyc.execute_command_as_user(
            "/bin/tool -i -l",
            user="qv_user",
            password="",
        )
        called_cmd = rpyc.execute_command.call_args[0][0]
        called_kwargs = rpyc.execute_command.call_args[1]
        assert called_cmd.startswith("sudo -n -u qv_user --")
        assert called_kwargs["input_data"] is None

    def test_unsupported_os_raises(self, rpyc, mocker):
        rpyc.get_os_name = mocker.Mock(return_value=OSName.EFISHELL)
        with pytest.raises(RunAsUserNotSupportedError):
            rpyc.execute_command_as_user(
                "tool",
                user="u",
                password="p",
            )

    def test_windows_requires_password(self, rpyc, mocker):
        rpyc.get_os_name = mocker.Mock(return_value=OSName.WINDOWS)
        with pytest.raises(RunAsUserError):
            rpyc.execute_command_as_user(
                "C:\\nvmupdate.exe -i",
                user="qv_user",
                password="",
            )

    def test_windows_logon_failure_raises_runasusererror(self, rpyc, mocker):
        rpyc.get_os_name = mocker.Mock(return_value=OSName.WINDOWS)
        modules = MagicMock()
        modules.tempfile.mkstemp.side_effect = [(1, "C:\\Temp\\out"), (2, "C:\\Temp\\err")]
        modules.os.close = MagicMock()
        modules.win32security.LogonUser.side_effect = RuntimeError("boom")
        rpyc.modules = mocker.Mock(return_value=modules)
        with pytest.raises(RunAsUserError):
            rpyc.execute_command_as_user(
                "tool.exe",
                user="qv_user",
                password="secret",
            )

    def test_windows_happy_path_returns_completed_process(self, rpyc, mocker):
        rpyc.get_os_name = mocker.Mock(return_value=OSName.WINDOWS)
        modules = MagicMock()
        modules.tempfile.mkstemp.side_effect = [(1, "C:\\Temp\\out"), (2, "C:\\Temp\\err")]
        modules.win32event.WAIT_TIMEOUT = 258
        modules.win32event.INFINITE = -1
        modules.win32event.WaitForSingleObject.return_value = 0
        modules.win32process.GetExitCodeProcess.return_value = 1
        modules.win32process.CreateProcessAsUser.return_value = (object(), object(), 1234, 1)

        out_handle = MagicMock()
        out_handle.__enter__.return_value.read.return_value = b"Administrator privileges are needed to run application.\r\n"
        err_handle = MagicMock()
        err_handle.__enter__.return_value.read.return_value = b""
        modules.builtins.open.side_effect = [out_handle, err_handle]
        rpyc.modules = mocker.Mock(return_value=modules)

        result = rpyc.execute_command_as_user(
            "C:\\nvmupdate.exe -i -l",
            user="qv_user",
            password="secret",
            expected_return_codes=None,
        )
        assert result.return_code == 1
        assert "Administrator privileges are needed" in result.stdout

    def test_default_raises_not_implemented_on_base(self):
        from mfd_connect.base import Connection
        instance = Connection.__new__(Connection)
        with pytest.raises(NotImplementedError):
            instance.execute_command_as_user("x", user="u", password="p")
