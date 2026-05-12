# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: MIT

import pytest
from mfd_typing.os_values import OSType

from mfd_connect.exceptions import OsNotSupported
from mfd_connect.util import account_utils


class DummyConnection:
    def __init__(self, os_type):
        """Initialize a dummy connection that simulates the behavior of a real connection for testing purposes."""
        self._os_type = os_type
        self.execute_command_calls = []

    def execute_command(self, *args, **kwargs):
        self.execute_command_calls.append((args, kwargs))
        return "ok"


class TestAccountUtils:
    def test_escape_cmd_argument(self):
        assert account_utils._escape_cmd_argument('a"b') == 'a""b'

    def test_build_windows_create_user_command(self):
        command = account_utils._build_windows_create_user_command('user"name', 'pass"word')
        assert command == 'net user "user""name" "pass""word" /add'

    @pytest.mark.parametrize(
        "username,password,error",
        [
            ("", "pwd", "username is required to create a Windows user"),
            ("user", "", "password is required to create a Windows user"),
        ],
    )
    def test_build_windows_create_user_command_validation(self, username, password, error):
        with pytest.raises(ValueError, match=error):
            account_utils._build_windows_create_user_command(username, password)

    def test_build_windows_delete_user_command(self):
        command = account_utils._build_windows_delete_user_command('user"name')
        assert command == 'net user "user""name" /delete'

    def test_build_windows_delete_user_command_validation(self):
        with pytest.raises(ValueError, match="username is required to delete a Windows user"):
            account_utils._build_windows_delete_user_command("")

    def test_create_user_windows_dispatch(self):
        connection = DummyConnection(OSType.WINDOWS)
        result = account_utils.create_user(connection=connection, username="john", password="pwd")

        assert result == "ok"
        assert len(connection.execute_command_calls) == 1
        args, kwargs = connection.execute_command_calls[0]
        assert args[0] == 'net user "john" "pwd" /add'
        assert kwargs["shell"] is True

    def test_delete_user_windows_dispatch(self):
        connection = DummyConnection(OSType.WINDOWS)
        result = account_utils.delete_user(connection=connection, username="john")

        assert result == "ok"
        assert len(connection.execute_command_calls) == 1
        args, kwargs = connection.execute_command_calls[0]
        assert args[0] == 'net user "john" /delete'
        assert kwargs["shell"] is True

    @pytest.mark.parametrize("function_call", ["create", "delete"])
    def test_user_management_not_supported(self, function_call):
        connection = DummyConnection(OSType.POSIX)

        with pytest.raises(OsNotSupported):
            if function_call == "create":
                account_utils.create_user(connection=connection, username="john", password="pwd")
            else:
                account_utils.delete_user(connection=connection, username="john")
