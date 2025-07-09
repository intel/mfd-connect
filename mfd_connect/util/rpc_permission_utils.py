# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""RPC utils for managing permissions."""

from typing import TYPE_CHECKING, Union

from mfd_typing import OSName

from mfd_connect import LocalConnection, SSHConnection, TunneledSSHConnection, RPyCConnection
from mfd_connect.tunneled_rpyc import TunneledRPyCConnection
from pathlib import Path

if TYPE_CHECKING:
    from mfd_connect import Connection


def change_mode(connection: "Connection", path: Union[str, "Path"], mode: int) -> None:
    """
    Change access permission of a file or directory.

    :param connection: Connection object
    :param path: Path to file or directory
    :param mode: Operating-system mode bitfield. eg. 0o775
    """
    supported_connections = (
        LocalConnection,
        SSHConnection,
        TunneledSSHConnection,
        TunneledRPyCConnection,
        RPyCConnection,
    )
    supported_os = (OSName.LINUX, OSName.FREEBSD, OSName.ESXI)

    _validate_environment(connection, supported_connections, supported_os, path, "Chmod")

    connection.path(path).chmod(mode)


def change_owner(connection: "Connection", path: Union[str, Path], user: str, group: str = "") -> None:
    """
    Change ownership of a file or directory.

    :param connection: Connection object
    :param path: Path to file or directory
    :param user: Username to transfer ownership to
    :param group: Group to transfer ownership to
    """
    supported_connections = (
        LocalConnection,
        SSHConnection,
        TunneledSSHConnection,
        TunneledRPyCConnection,
        RPyCConnection,
    )
    supported_os = (OSName.LINUX, OSName.FREEBSD, OSName.ESXI)

    _validate_environment(connection, supported_connections, supported_os, path, "Chown")

    if group == "":
        connection.execute_command(f"chown {user} {path}")
    else:
        connection.execute_command(f"chown {user}:{group} {path}")


def _validate_environment(
    connection: "Connection",
    supported_connections: tuple["Connection", ...],
    supported_os: tuple["OSName", ...],
    path: Union[str, Path],
    command: str,
) -> None:
    """
    Check if command can be executed.

    :param connection: Connection command is executing on
    :param supported_connections: tuple of supported connections
    :param supported_os: tuple of supported os
    :param path: path to the file
    :param command: command name (Capitalized)
    """
    if connection.get_os_name() not in supported_os:
        raise NotImplementedError(f"{command} is not supported on this system")
    if not isinstance(connection, supported_connections):
        raise Exception("Connection type not supported")

    if not connection.path(path).exists():
        raise Exception(f"{path} not found")
