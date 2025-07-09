# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module of Posix process."""

from signal import Signals, SIGTERM, SIGINT
from typing import Optional, List, TYPE_CHECKING, Union

from mfd_typing.os_values import OSName

from .base import SSHProcess
from ...exceptions import RemoteProcessInvalidState, SSHRemoteProcessEndException

if TYPE_CHECKING:
    from mfd_connect import SSHConnection


class PosixSSHProcess(SSHProcess):
    """Implementation of Posix SSH process."""

    _os_name = {OSName.LINUX, OSName.FREEBSD}

    def stop(self, wait: Optional[int] = 60) -> None:
        """
        Signal the process to stop gracefully.

        :param wait: Time in seconds to wait for the process to finish before returning.
                     If None - no waiting is performed.
        :raises SSHRemoteProcessEndException: if cannot stop the process.
        :raises RemoteProcessInvalidState: if process has already finished.
        """
        if self.running:
            super().stop()
            command = f"kill -{SIGINT} {self.pid}"
            result = self._connection_handle.execute_command(command=command, expected_return_codes=None)
            if result.return_code != 0:
                raise SSHRemoteProcessEndException(f"Cannot stop process pid:{self.pid}")
        else:
            raise RemoteProcessInvalidState("Process has already finished")

    def kill(self, wait: Optional[int] = 60, with_signal: Union[Signals, str, int] = SIGTERM) -> None:
        """
        Kill the process forcefully.

        :param wait: Time in seconds to wait for the process to finish before returning.
                     If None - no waiting is performed.
        :param with_signal: Signal to be used for killing process, e.g. signal.SIGTERM.
        :raises SSHRemoteProcessEndException: if cannot kill the process.
        :raises RemoteProcessInvalidState: if process has already finished.
        """
        if self.running:
            super().kill()
            self._kill(self.pid, with_signal=with_signal)
            if wait is not None:
                self.wait(timeout=wait)
        else:
            raise RemoteProcessInvalidState("Process has already finished")

    @staticmethod
    def _find_pids(connection: "SSHConnection", name: str) -> List[int]:
        """
        Find PIDs by name.

        :param connection: connection
        :param name: name of process, generated in start process
        :return: List of PIDs if any PID exists
        :raises RemoteProcessInvalidState: if cannot find PID
        """
        command = f"ps aux | grep 'true {name}' | grep -v grep | awk '{{print $2}}'"
        result = connection.execute_command(command=command)
        parent_pid = result.stdout.rstrip()
        if not parent_pid:
            raise RemoteProcessInvalidState("Process is finished, cannot find PID")
        result = connection.execute_command(command=f"pgrep -P {parent_pid}", expected_return_codes=None)
        pids = result.stdout.rstrip()
        if not pids or result.return_code != 0:
            raise RemoteProcessInvalidState("Process is finished, cannot find PID")
        return [int(pid) for pid in pids.splitlines()]

    def _kill(self, pid: int, with_signal: Union[Signals, str, int]) -> None:
        """
        Kill process.

        :param pid: Process pid
        :param with_signal: Signal to be used for killing process, e.g. signal.SIGTERM/15/"SIGTERM"
        :raises SSHRemoteProcessEndException: if cannot kill the process.
        """
        if isinstance(with_signal, str) and with_signal.lower() == "sigkill":  # enable SIGKILL on windows controller
            with_signal = 9
        kill_command = f"kill -{with_signal} {pid}"
        result = self._connection_handle.execute_command(kill_command, expected_return_codes=None)
        if result.return_code != 0:
            raise SSHRemoteProcessEndException(f"Cannot kill process pid:{pid}")
