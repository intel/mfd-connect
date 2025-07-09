# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for RPyCProcess implementation for POSIX-compliant OS'es."""

from signal import SIGINT
from typing import Optional

from mfd_typing.os_values import OSType, OSName

from .base import RPyCProcess
from ...exceptions import RemoteProcessInvalidState


class PosixRPyCProcess(RPyCProcess):
    """RPyCProcess on POSIX-compliant OS'es."""

    _os_type = OSType.POSIX
    _os_names = [OSName.LINUX, OSName.FREEBSD]

    def stop(self, wait: Optional[int] = 60) -> None:
        """
        Signal the process to stop gracefully.

        :param wait: Time in seconds to wait for the process to finish before returning.
                     If None - no waiting is performed.
        :raises RemoteProcessInvalidState: if process has already finished.
        """
        if self.running:
            super().stop()
            self._get_and_kill_process(with_signal=SIGINT)

            if wait is not None:
                self.wait(timeout=wait)
        else:
            raise RemoteProcessInvalidState("Process has already finished")
