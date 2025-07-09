# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Utils for connections."""

import logging
from dataclasses import dataclass, InitVar
from typing import TYPE_CHECKING, Tuple

from mfd_connect import SSHConnection
from mfd_common_libs import add_logging_level, log_levels

if TYPE_CHECKING:
    from mfd_connect import (
        Connection,
        LocalConnection,
        RPyCConnection,
        SerialConnection,
        SolConnection,
        SSHConnection,
        TunneledSSHConnection,
        TunneledRPyCConnection,
        TelnetConnection,
    )

logger = logging.getLogger(__name__)
add_logging_level(level_name="MODULE_DEBUG", level_value=log_levels.MODULE_DEBUG)


def check_ssh_active_and_return_conn(conn: "Connection | None" = None, **kwargs) -> Tuple[bool, "Connection | None"]:
    """
    Check if SSH Connection is active and return connection handle if active.

    If existing connection is SSH (previously spawned), use the same connection to check if still active
    If connection not SSH/not specified, spawn SSH connection by providing ssh_ip, ssh_user, ssh_pwd in kwargs

    :param conn: Existing connection to the machine
    :param kwargs: ssh_ip, ssh_user, ssh_pwd to be given when existing connection is not SSH
    :return: True and ssh connection handle if ssh connection is active, else False with connection handle as None
    :raises AttributeError: when kwargs: ssh_ip, ssh_user, ssh_pwd are required, but missing
    """
    logger.log(
        level=log_levels.MODULE_DEBUG,
        msg="Checking if SSH Connection is active",
    )
    if not isinstance(conn, SSHConnection):
        if any(val is None for val in (kwargs.get("ssh_ip"), kwargs.get("ssh_user"), kwargs.get("ssh_pwd"))):
            raise AttributeError("SSH credentials: ssh_ip, ssh_user, ssh_pwd needed to spawn a new SSH Connection")
        try:
            ssh_conn = SSHConnection(
                ip=kwargs.get("ssh_ip"), username=kwargs.get("ssh_user"), password=kwargs.get("ssh_pwd")
            )
            return True, ssh_conn
        except Exception:
            return False, None
    else:
        if conn._connection.get_transport().is_active():
            return True, conn
    return False, None


@dataclass
class Connections:
    """Class for instantiated connections."""

    local: "LocalConnection | None" = None
    rpyc: "RPyCConnection | None" = None
    serial: "SerialConnection | None" = None
    sol: "SolConnection | None" = None
    ssh: "SSHConnection | None" = None
    tunneled_rpyc: "TunneledRPyCConnection | None" = None
    tunneled_ssh: "TunneledSSHConnection | None" = None
    telnet: "TelnetConnection | None" = None
    _connections: InitVar[list] = None

    def __post_init__(self, _connections: list):
        for connection in _connections:
            setattr(self, str(connection), connection)
