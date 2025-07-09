# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for RPyCProcess implementation for Windows."""

import logging

from signal import Signals, SIGTERM
from typing import Optional, Union, Iterator, IO

from mfd_common_libs import log_levels
from mfd_typing.os_values import OSType
from .base import RPyCProcess
from ...exceptions import RemoteProcessInvalidState, RemoteProcessStreamNotAvailable

logger = logging.getLogger(__name__)


class WindowsRPyCProcess(RPyCProcess):
    """RPycProcess on Windows implementation."""

    _os_type = OSType.WINDOWS

    def stop(self, wait: Optional[int] = 60) -> None:
        """
        Signal the process to stop gracefully.

        :param wait: Time in seconds to wait for the process to finish before returning.
                     If None - no waiting is performed.
        :raises RemoteProcessInvalidState: if process has already finished.
        """
        if self.running:
            super().stop()
            self._get_and_kill_process(with_signal=self._owner.modules().signal.CTRL_C_EVENT)

            if wait is not None:
                self.wait(timeout=wait)
        else:
            raise RemoteProcessInvalidState("Process has already finished")

    def kill(self, wait: Optional[int] = 60, with_signal: Union[Signals, str, int] = SIGTERM) -> None:
        """
        Kill the process forcefully.

        :param wait: Time in seconds to wait for the process to finish before returning.
                     If None - no waiting is performed.
        :param with_signal: Signal to be used for killing process, e.g. signal.SIGTERM/15/'SIGTERM'
        """
        supported_signals = ["SIGTERM", "CTRL_C_EVENT", "CTRL_BREAK_EVENT"]
        signal_name = with_signal.name if isinstance(with_signal, Signals) else str(with_signal)
        if signal_name not in supported_signals:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg=f"{signal_name} is not supported on Windows. Changing signal to SIGTERM",
            )
            with_signal = self._owner.modules().signal.SIGTERM
        super().kill(wait=wait, with_signal=with_signal)


class WindowsRPyCProcessByStart(WindowsRPyCProcess):
    """Class for process started on Windows using `start` command."""

    @property
    def stdin_stream(self) -> IO:  # noqa D102
        raise RemoteProcessStreamNotAvailable("stdin stream is not available for that process")

    @property
    def stdout_stream(self) -> IO:  # noqa D102
        raise RemoteProcessStreamNotAvailable("stdout stream is not available for that process")

    @property
    def stderr_stream(self) -> IO:  # noqa D102
        raise RemoteProcessStreamNotAvailable("stderr stream is not available for that process")

    def get_stdout_iter(self) -> Iterator[str]:  # noqa D102
        if self.log_path is None:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg="Discarded stdout, output is not available.",
            )
            return iter([])
        with self.log_path.open("r+") as log_file:
            return iter(log_file.readlines())

    def get_stderr_iter(self) -> Iterator[str]:  # noqa D102
        # Stderr is not supported on Windows, because it's aggregated with stdout
        # potentially can redirect stderr to next log file together with stderr log file, todo
        return iter([])

    @property
    def stdout_text(self) -> str:  # noqa D102
        _ = super().stdout_text  # noqa F841
        return "".join(self.get_stdout_iter())

    @property
    def stderr_text(self) -> str:  # noqa D102
        logger.log(
            level=log_levels.MODULE_DEBUG,
            msg="Stderr is not supported on Windows, because it's aggregated with stdout",
        )
        return super().stderr_text
