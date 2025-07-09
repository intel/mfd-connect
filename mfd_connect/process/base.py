# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for generic RemoteProcess interface."""

import re
from abc import ABC, abstractmethod
from signal import Signals, SIGTERM
from typing import IO, Optional, Iterator, Union, List

from .. import Connection
from ..exceptions import RemoteProcessInvalidState


class RemoteProcess(ABC):
    """
    Modular Framework Design abstraction for the OS process.

    Serves as an interface to implement, should not be directly instantiated.
    """

    @property
    @abstractmethod
    def running(self) -> bool:
        """Whenever the process is running or not."""
        pass

    @property
    @abstractmethod
    def stdin_stream(self) -> IO:
        """
        Process stdin stream.

        :raises RemoteProcessStreamNotAvailable when stdin stream will be not available.
        """
        pass

    @property
    @abstractmethod
    def stdout_stream(self) -> IO:
        """
        Process stdout stream.

        Should be avoided if stdout_text or get_stdout_iter() can be used instead.

        :raises RemoteProcessStreamNotAvailable when stdout stream will be not available.
        """
        pass

    @property
    @abstractmethod
    def stderr_stream(self) -> IO:
        """
        Process stderr stream.

        Should be avoided if stderr_text or get_stderr_iter() can be used instead.

        :raises RemoteProcessStreamNotAvailable when stderr stream will be not available.
        """
        pass

    @property
    @abstractmethod
    def stdout_text(self) -> str:
        """
        Full process stdout text.

        Not available until the process is stopped.

        :raises RemoteProcessInvalidState when process will be not completed.
        """
        if self.running:
            raise RemoteProcessInvalidState("Process is still running.")

    @property
    @abstractmethod
    def stderr_text(self) -> str:
        """
        Full process stderr text.

        Not available until the process is stopped.

        :raises RemoteProcessInvalidState when process will be not completed.
        """
        if self.running:
            raise RemoteProcessInvalidState("Process is still running.")

    @abstractmethod
    def get_stdout_iter(self) -> Iterator[str]:
        """
        Get iterator over stdout lines of the process.

        Unlike stdout_text - this is available while the process is running.
        If the process is still running, but iterator has come to the end of the
        available data - next() will block until new data arrives or process concludes.
        Each call of the method will produce new iterator, starting from the beginning
        of the process output.

        :return: Iterator over stdout lines of the process.
        """
        pass

    @abstractmethod
    def get_stderr_iter(self) -> Iterator[str]:
        """
        Get iterator over stderr lines of the process.

        Unlike stderr_text - this is available while the process is running.
        If the process is still running, but iterator has come to the end of the
        available data - next() will block until new data arrives or process concludes.
        Each call of the method will produce new iterator, starting from the beginning
        of the process output.

        :return: Iterator over stderr lines of the process.
        """
        pass

    @property
    @abstractmethod
    def return_code(self) -> Optional[int]:
        """
        Return code of the process.

        Negative value if the process was killed.
        Zero or positive value if the return code was retrieved.
        Not available until the process is stopped.

        :raises RemoteProcessInvalidState when process will be not completed.
        """
        if self.running:
            raise RemoteProcessInvalidState("Process is still running.")

    @abstractmethod
    def wait(self, timeout: int = 60) -> int:
        """
        Wait for the process to conclude on its own.

        :param timeout: Time to wait for process to conclude.
        :return: Process return code.
        :raises RemoteProcessTimeoutExpired: If the process did not conclude before the timer ran out.
        """
        assert timeout > 0, "'timeout' parameter must be greater than zero"

    @abstractmethod
    def stop(self, wait: Optional[int] = 60) -> None:
        """
        Signal the process to stop gracefully.

        :param wait: Time in seconds to wait for the process to finish before returning.
                     If None - no waiting is performed.
        :raises RemoteProcessInvalidState: when process cannot be found in system, or found problem during stop
        :raises ModuleNotFoundError: when psutil is not available for remote machine
        """
        assert wait is None or wait > 0, "'wait' parameter must be greater than zero"

    @abstractmethod
    def kill(self, wait: Optional[int] = 60, with_signal: Union[Signals, str, int] = SIGTERM) -> None:
        """
        Kill the process forcefully.

        :param wait: Time in seconds to wait for the process to finish before returning.
                     If None - no waiting is performed.
        :param with_signal: Signal to be used for killing process, e.g. signal.SIGTERM
        :raises RemoteProcessInvalidState: when process cannot be found in system, or found problem during kill
        :raises ModuleNotFoundError: when psutil is not available for remote machine
        """
        assert wait is None or wait > 0, "'wait' parameter must be greater than zero"


class ESXiRemoteProcess(RemoteProcess):
    """Remote process of ESXi OS with common implementation for each connection."""

    @staticmethod
    def _find_children_process(connection: "Connection", pid: int) -> List[int]:
        """
        Find children processes for Popen process.

        Call ps command with tree. First line is our popen PID.
        Parsing indents for bottom lines until indent is smaller than popen process.

        ps_process_result contains processes info starting with line of our pid.
        For that line we calculate indentation level (count of pairs Shift Out + Shift In characters).
        We store IDs until indentation is lower or equal to first process (means it's not a child of process)

        :param connection: Connection object to machine
        :param pid: ID of process to find children
        :return: List of children processes
        """
        command = f"ps -c -J | grep -v grep | grep {pid} -A 10000"  # -A means trailing context
        ps_process_result = connection.execute_command(command, shell=True)
        regex = rb"\x0e[mtxq\s]*\x0f[mtxq\s]*(\d+)?"  # Shift Out - Shift In Char pairs with dashes (m, t, x, q chars)
        child_list = []
        lines = ps_process_result.stdout_bytes.splitlines()
        if len(lines) > 0:
            start_indentation_level = len(re.findall(regex, lines[0]))
            for line in lines[1:]:
                match = re.findall(regex, line)
                current_indentation_level = len(match)
                if current_indentation_level <= start_indentation_level or not match:
                    break
                value = match[-1]  # last group match according to regex contains process id
                if isinstance(value, bytes):
                    value = value.decode()
                try:
                    child_list.append(int(value))
                except ValueError:
                    pass
        return child_list
