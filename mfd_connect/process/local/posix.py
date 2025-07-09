# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for LocalProcess implementation for POSIX-compliant OS'es."""

import signal

from contextlib import suppress
from typing import Optional

from mfd_typing.os_values import OSType

from .base import LocalProcess
from ...exceptions import RemoteProcessInvalidState


class POSIXLocalProcess(LocalProcess):
    """LocalProcess on POSIX-compliant OS'es."""

    os_type = OSType.POSIX

    def stop(self, wait: Optional[int] = 60) -> None:
        """
        Signal the process to stop gracefully.

        :param wait: Time in seconds to wait for the process to finish before returning.
                     If None - no waiting is performed.
        :raises RemoteProcessInvalidState: if process has already finished.
        """
        if self.running:
            super().stop()
            with suppress(ProcessLookupError):
                self._process.send_signal(signal.SIGINT)

            if wait is not None:
                self.wait(timeout=wait)
        else:
            raise RemoteProcessInvalidState("Process has already finished")
