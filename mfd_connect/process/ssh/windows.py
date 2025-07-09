# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module of Windows process."""

import logging
from signal import Signals, SIGTERM
from typing import Optional, List, TYPE_CHECKING, Union

from mfd_common_libs import log_levels
from mfd_typing.os_values import OSName

from .base import SSHProcess
from ...exceptions import RemoteProcessInvalidState, SSHRemoteProcessEndException

if TYPE_CHECKING:
    from mfd_connect import SSHConnection

logger = logging.getLogger(__name__)


class WindowsSSHProcess(SSHProcess):
    """Implementation of Windows SSH process."""

    _os_name = {OSName.WINDOWS}

    def stop(self, wait: Optional[int] = 60) -> None:
        """
        Signal the process to stop gracefully.

        :param wait: Time in seconds to wait for the process to finish before returning.
                     If None - no waiting is performed.
        """
        raise NotImplementedError("Stop method is not implemented for Windows")

    def kill(self, wait: Optional[int] = 60, with_signal: Union[Signals, str, int] = SIGTERM) -> None:
        """
        Kill the process forcefully.

        :param wait: Time in seconds to wait for the process to finish before returning.
                     If None - no waiting is performed.
        :param with_signal: Signal to be used for killing process, e.g. signal.SIGTERM. Do nothing with SSH
        :raises SSHRemoteProcessEndException: if cannot kill the process.
        :raises RemoteProcessInvalidState: if process has already finished.
        """
        if self.running:
            super().kill()
            logger.log(level=log_levels.MODULE_DEBUG, msg="Using signals on Windows for killing process is available.")
            self._kill(self.pid)
            if wait is not None:
                self.wait(timeout=wait)
        else:
            raise RemoteProcessInvalidState("Process has already finished")

    @staticmethod
    def _find_pids(connection: "SSHConnection", name: str) -> List[int]:
        """
        Find PID on Windows by name.

        Looking for /c "title (name)"
        In start process Windows require 'title random_stuff &&' injected before command
        :param connection: connection
        :param name: name of process, generated in start process
        :return: List of PIDs if any PID exists
        :raises RemoteProcessInvalidState: if cannot find PID
        """
        result = connection.execute_command(
            command=f'powershell -command "Get-CimInstance Win32_Process '
            f"| Where-Object -Match -Property CommandLine -Value .*\/c\s\Dtitle\s{name}.* "  # noqa: W605
            f'| Select-Object  -ExpandProperty ProcessId"'
        )
        pids = result.stdout.strip()
        if not pids:
            raise RemoteProcessInvalidState("Process is finished, cannot find PID")
        return [int(pid) for pid in pids.splitlines()]

    def _kill(self, pid: int) -> None:
        kill_command = f"taskkill /F /PID {pid}"
        result = self._connection_handle.execute_command(kill_command, expected_return_codes=None)
        if result.return_code != 0:
            raise SSHRemoteProcessEndException(f"Cannot kill process pid:{pid}")
