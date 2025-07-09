# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module of Interactive SSH Process."""

import logging
from time import sleep
from typing import Optional, Iterator, TYPE_CHECKING, IO

from mfd_common_libs import TimeoutCounter, add_logging_level, log_levels

from ..base import RemoteProcess
from ...exceptions import (
    RemoteProcessTimeoutExpired,
    RemoteProcessInvalidState,
    SSHRemoteProcessEndException,
)

if TYPE_CHECKING:
    from ...interactive_ssh import InteractiveSSHConnection

logger = logging.getLogger(__name__)
add_logging_level(level_name="MODULE_DEBUG", level_value=log_levels.MODULE_DEBUG)


class InteractiveSSHProcess(RemoteProcess):
    """Implementation of SSH Process."""

    """Interval for polling operations."""

    def get_stdout_iter(self) -> Iterator[str]:  # noqa D102
        return iter(self.stdout_text.splitlines())

    @property
    def stdin_stream(self) -> IO:  # noqa D102
        raise NotImplementedError("Not available for Interactive SSH")

    @property
    def stdout_stream(self) -> IO:  # noqa D102
        raise NotImplementedError("Not available for Interactive SSH")

    @property
    def stderr_stream(self) -> IO:  # noqa D102
        raise NotImplementedError("Not available for Interactive SSH")

    @property
    def stderr_text(self) -> str:  # noqa D102
        raise NotImplementedError("Not available for Interactive SSH")

    def get_stderr_iter(self) -> Iterator[str]:  # noqa D102
        raise NotImplementedError("Not available for Interactive SSH")

    @property
    def return_code(self) -> int | None:  # noqa D102
        return self._interactive_connection._get_return_code(self._command)

    def __init__(self, *, stdout: str | None = None, connection: "InteractiveSSHConnection", command: str) -> None:
        """
        Init of SSHProcess.

        :param stdout: Output stream from paramiko
        :param connection: Reference to connection
        """
        super().__init__()

        self._command = command
        self._stdout = stdout if stdout else ""

        self.log_path = None  # compatibility with RPyC
        self.log_file_stream = None  # compatibility with RPyC
        self._running = None
        self._interactive_connection = connection

    @property
    def stdout_text(self) -> str:
        """
        Full process stdout text.

        Not available until the process is stopped.

        :raises RemoteProcessInvalidState when process will be not completed.
        """
        _ = super().stdout_text
        self._read_channel()
        return self._stdout

    @property
    def running(self) -> bool:
        """Whenever the process is running or not."""
        if self._running is not None and not self._running:
            return False

        logger.log(level=log_levels.MODULE_DEBUG, msg="Checking if process is running.")
        if self._interactive_connection.prompt in self._read_channel():
            self._running = False
        else:
            self._running = True
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Process is running: {self._running}")
        return self._running

    def _read_channel(self) -> str:
        """
        Read channel and cleanup stdout.

        Update process object with stdout.
        :return: stdout from channel
        """
        chan = self._interactive_connection.read_channel()
        self._stdout += self._interactive_connection.cleanup_stdout(self._command, chan)
        return chan

    def wait(self, timeout: int = 60) -> int:
        """
        Wait for the process to conclude on its own.

        :param timeout: Time to wait for process to conclude.
        :return: Process return code.
        :raises RemoteProcessTimeoutExpired: If the process did not conclude before the timer ran out.
        """
        super().wait(timeout)

        timeout = TimeoutCounter(timeout)
        while not timeout:
            if not self.running:
                return self.return_code
            sleep(0.1)
        else:
            raise RemoteProcessTimeoutExpired()

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
            logger.log(level=log_levels.MODULE_DEBUG, msg="Sending CTRL+C to stop the process.")
            self._interactive_connection.write_to_channel("\x03", False)
            sleep(1)
            chan = self._read_channel()
            if self._interactive_connection.prompt in chan:
                self._running = False
                return
            raise SSHRemoteProcessEndException(f"Cannot stop process {self._command}")
        else:
            raise RemoteProcessInvalidState("Process has already finished")

    def kill(self, wait: Optional[int] = 60, **_) -> None:
        """
        Kill the process forcefully.

        :param wait: Time in seconds to wait for the process to finish before returning.
                     If None - no waiting is performed.
        :raises SSHRemoteProcessEndException: if cannot kill the process.
        :raises RemoteProcessInvalidState: if process has already finished.
        """
        if self.running:
            super().kill()
            logger.log(level=log_levels.MODULE_DEBUG, msg="Sending CTRL+C 3 times to kill the process.")
            self._interactive_connection.write_to_channel("\x03", False)
            self._interactive_connection.write_to_channel("\x03", False)
            self._interactive_connection.write_to_channel("\x03", False)
            sleep(1)
            chan = self._read_channel()
            if self._interactive_connection.prompt in chan:
                self._running = False
                return
        else:
            raise RemoteProcessInvalidState("Process has already finished")
