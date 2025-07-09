# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Package for winrm process."""

import codecs
import typing

from typing import Optional, Union

from winrm.exceptions import WinRMOperationTimeoutError

from mfd_connect.exceptions import RemoteProcessInvalidState
from mfd_connect.process import RemoteProcess

if typing.TYPE_CHECKING:
    from mfd_connect.winrm import WinRmConnection
    from typing import Iterator, IO
    from signal import Signals


class WinRmProcess(RemoteProcess):
    """Class for WinRM process."""

    def __init__(
        self,
        *,
        command_id: str,
        connection: "WinRmConnection",
    ) -> None:
        """
        Init of WinRmProcess.

        :param command_id: ID of executed command.
        :param connection: Reference to connection
        """
        super().__init__()

        self.log_path = None  # compatibility with RPyC
        self.log_file_stream = None  # compatibility with RPyC
        self.command_id = command_id
        self._connection_handle = connection
        self.shell_id = connection._shell_id
        self._stdout = None
        self._stderr = None
        self._return_code = None
        self._running = None

    @property
    def running(self) -> bool:  # noqa D102
        self._pull_data()
        return self._running

    @property
    def stdout_text(self) -> str:  # noqa D102
        _ = super().stdout_text
        if self._stdout is None:
            self._pull_data()
        return self._stdout

    @property
    def stderr_text(self) -> str:  # noqa D102
        _ = super().stderr_text
        if self._stderr is None:
            self._pull_data()
        return self._stderr

    @property
    def return_code(self) -> Optional[int]:  # noqa D102
        _ = super().return_code
        if self._return_code is None:
            self._pull_data()
        return self._return_code

    @property
    def stdin_stream(self) -> "IO":  # noqa D102
        raise NotImplementedError

    @property
    def stdout_stream(self) -> "IO":  # noqa D102
        raise NotImplementedError

    @property
    def stderr_stream(self) -> "IO":  # noqa D102
        raise NotImplementedError

    def get_stdout_iter(self) -> "Iterator":  # noqa D102
        raise NotImplementedError

    def get_stderr_iter(self) -> "Iterator":  # noqa D102
        raise NotImplementedError

    def wait(self, timeout: int = 60) -> int:  # noqa D102
        raise NotImplementedError

    def stop(self, wait: Optional[int] = 60) -> None:
        """
        Signal the process to stop gracefully.

        :param wait: Time in seconds to wait for the process to finish before returning.
                     If None - no waiting is performed.
        :raises RemoteProcessInvalidState: when found problem during stop
        :raises ModuleNotFoundError: when psutil is not available for remote machine
        """
        try:
            self._connection_handle._server.cleanup_command(self.shell_id, self.command_id)
        except Exception as e:
            raise RemoteProcessInvalidState("Found problem during stop") from e

    def kill(self, wait: Optional[int] = 60, with_signal: Optional[Union["Signals", str, int]] = None) -> None:
        """
        Kill the process forcefully.

        For WinRM is the same as stop.

        :param wait: Time in seconds to wait for the process to finish before returning.
                     If None - no waiting is performed.
        :param with_signal: Signal to be used for killing process, e.g. signal.SIGTERM
        :raises RemoteProcessInvalidState: when found problem during kill
        """
        self.stop()

    def _pull_data(self) -> None:
        """
        Pull data from command.

        API reads stdout, stderr, return code and status of process (if it's done or not).
        """
        try:
            self.__pull_data()
        except WinRMOperationTimeoutError:
            self._running = True  # todo refactor reading status of command

    def __pull_data(self) -> None:
        """
        Pull data from command.

        API reads stdout, stderr, return code and status of process (if it's done or not).
        """
        (
            _stdout_bytes,
            _stderr_bytes,
            self._return_code,
            command_done,
        ) = self._connection_handle._server._raw_get_command_output(self.shell_id, self.command_id)
        self._running = not command_done
        if _stdout_bytes:
            if self._stdout is None:
                self._stdout = ""
            self._stdout += codecs.decode(_stdout_bytes, encoding="utf-8", errors="backslashreplace")
        if _stderr_bytes:
            if self._stderr is None:
                self._stderr = ""
            self._stderr += codecs.decode(_stderr_bytes, encoding="utf-8", errors="backslashreplace")
