# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module of ESXi process."""

from typing import List, TYPE_CHECKING

from mfd_typing.os_values import OSName

from .posix import PosixSSHProcess
from ..base import ESXiRemoteProcess
from ...exceptions import RemoteProcessInvalidState

if TYPE_CHECKING:
    from mfd_connect import SSHConnection


class ESXiSSHProcess(PosixSSHProcess, ESXiRemoteProcess):
    """Implementation of Posix SSH process."""

    _os_name = {OSName.ESXI}

    @staticmethod
    def _find_pids(connection: "SSHConnection", name: str) -> List[int]:
        """
        Find PIDs by name.

        :param connection: connection
        :param name: name of process, generated in start process
        :return: List of PIDs if any PID exists
        :raises RemoteProcessInvalidState: if cannot find PID
        """
        command = f"ps -c | grep 'true {name}' | grep -v grep | awk '{{print $2}}'"
        result = connection.execute_command(command=command)
        parent_pid = result.stdout
        if not parent_pid:
            raise RemoteProcessInvalidState("Process is finished, cannot find PID")

        #    x       mq24844644  24844644  ping
        children_pids = ESXiRemoteProcess._find_children_process(connection, int(parent_pid))

        if not children_pids:
            raise RemoteProcessInvalidState("Process is finished, cannot find children PIDs")
        return children_pids
