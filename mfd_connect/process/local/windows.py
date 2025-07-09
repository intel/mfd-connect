# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for LocalProcess implementation for Windows."""

from typing import Optional

from mfd_typing.os_values import OSType

from .base import LocalProcess
from ...exceptions import RemoteProcessInvalidState


class WindowsLocalProcess(LocalProcess):
    """LocalProcess on Windows implementation."""

    os_type = OSType.WINDOWS

    def stop(self, wait: Optional[int] = 60) -> None:
        """
        Signal the process to stop gracefully.

        :param wait: Time in seconds to wait for the process to finish before returning.
                     If None - no waiting is performed.
        :raises RemoteProcessInvalidState: if process has already finished.
        """
        if self.running:
            super().stop()
            self.kill(wait=wait)  # In Windows - there's no known way to gracefully terminate python's child process
            # without killing it's parent at the same time. As a workaround - we substitute the stop() with kill() to
            # stop the process somehow, maybe not gracefully.
        else:
            raise RemoteProcessInvalidState("Process has already finished")
