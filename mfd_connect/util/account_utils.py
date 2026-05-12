# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: MIT
"""RPC utils for account management."""

from typing import TYPE_CHECKING, Iterable, Type
from subprocess import CalledProcessError

from mfd_typing.os_values import OSType

from mfd_connect.exceptions import OsNotSupported

if TYPE_CHECKING:
    from mfd_connect.base import Connection, ConnectionCompletedProcess


def _escape_cmd_argument(value: str) -> str:
    """Escape a value for use as a quoted ``cmd.exe`` argument."""
    return value.replace('"', '""')


def _build_windows_create_user_command(username: str, password: str) -> str:
    """
    Build a command that creates a local Windows user.

    :param username: Local user name to create.
    :param password: Initial password for the user.
    :return: ``net user`` command for creating the user.
    :raises ValueError: If required arguments are missing.
    """
    if not username:
        raise ValueError("username is required to create a Windows user")
    if not password:
        raise ValueError("password is required to create a Windows user")

    escaped_username = _escape_cmd_argument(username)
    escaped_password = _escape_cmd_argument(password)
    return f'net user "{escaped_username}" "{escaped_password}" /add'


def _build_windows_delete_user_command(username: str) -> str:
    """
    Build a command that deletes a local Windows user.

    :param username: Local user name to delete.
    :return: ``net user`` command for deleting the user.
    :raises ValueError: If required arguments are missing.
    """
    if not username:
        raise ValueError("username is required to delete a Windows user")

    escaped_username = _escape_cmd_argument(username)
    return f'net user "{escaped_username}" /delete'


def create_user(
    connection: "Connection",
    username: str,
    password: str,
    *,
    expected_return_codes: Iterable | None = frozenset({0}),
    custom_exception: Type[CalledProcessError] | None = None,
    skip_logging: bool = False,
) -> "ConnectionCompletedProcess":
    """
    Create a local system user on a supported platform.

    :param connection: Connection used for command execution.
    :param username: Local user name to create.
    :param password: Initial password for the user.
    :param expected_return_codes: Return codes considered successful.
    :param custom_exception: Exception class raised on unexpected return code.
    :param skip_logging: Skip stdout/stderr logging for this execution.
    :return: Completed process result.
    :raises OsNotSupported: If current OS is not supported.
    """
    if connection._os_type == OSType.WINDOWS:
        return _create_user_windows(
            connection=connection,
            username=username,
            password=password,
            expected_return_codes=expected_return_codes,
            custom_exception=custom_exception,
            skip_logging=skip_logging,
        )
    raise OsNotSupported(f"Creating users is not supported for OS type: {connection._os_type}")


def delete_user(
    connection: "Connection",
    username: str,
    *,
    expected_return_codes: Iterable | None = frozenset({0}),
    custom_exception: Type[CalledProcessError] | None = None,
    skip_logging: bool = False,
) -> "ConnectionCompletedProcess":
    """
    Delete a local system user on a supported platform.

    :param connection: Connection used for command execution.
    :param username: Local user name to delete.
    :param expected_return_codes: Return codes considered successful.
    :param custom_exception: Exception class raised on unexpected return code.
    :param skip_logging: Skip stdout/stderr logging for this execution.
    :return: Completed process result.
    :raises OsNotSupported: If current OS is not supported.
    """
    if connection._os_type == OSType.WINDOWS:
        return _delete_user_windows(
            connection=connection,
            username=username,
            expected_return_codes=expected_return_codes,
            custom_exception=custom_exception,
            skip_logging=skip_logging,
        )
    raise OsNotSupported(f"Deleting users is not supported for OS type: {connection._os_type}")


def _create_user_windows(
    *,
    connection: "Connection",
    username: str,
    password: str,
    expected_return_codes: Iterable | None,
    custom_exception: Type[CalledProcessError] | None,
    skip_logging: bool,
) -> "ConnectionCompletedProcess":
    """Create a local Windows user using ``net user``."""
    command = _build_windows_create_user_command(username=username, password=password)
    return connection.execute_command(
        command,
        shell=True,
        expected_return_codes=expected_return_codes,
        custom_exception=custom_exception,
        skip_logging=skip_logging,
    )


def _delete_user_windows(
    *,
    connection: "Connection",
    username: str,
    expected_return_codes: Iterable | None,
    custom_exception: Type[CalledProcessError] | None,
    skip_logging: bool,
) -> "ConnectionCompletedProcess":
    """Delete a local Windows user using ``net user``."""
    command = _build_windows_delete_user_command(username=username)
    return connection.execute_command(
        command,
        shell=True,
        expected_return_codes=expected_return_codes,
        custom_exception=custom_exception,
        skip_logging=skip_logging,
    )
