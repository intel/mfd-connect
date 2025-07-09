# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for RPyCProcess implementation for ESXi OS."""

import logging
import typing
from contextlib import suppress
from typing import Optional, Union

from mfd_common_libs import log_levels
from mfd_typing.os_values import OSName

from .posix import PosixRPyCProcess
from ..base import ESXiRemoteProcess

if typing.TYPE_CHECKING:
    from signal import Signals

logger = logging.getLogger(__name__)


class ESXiRPyCProcess(PosixRPyCProcess, ESXiRemoteProcess):
    """RPyCProcess on ESXi OS."""

    _os_names = [OSName.ESXI]

    def _get_and_kill_process(self, with_signal: Optional[Union["Signals", str, int]] = None) -> None:
        """
        Kill process and all of its children processes.

        :param with_signal: Signal used for killing processes - be aware it must be signal from remote connection
        """
        with_signal = self._convert_to_signal_object(with_signal)
        ps_process_result = self._owner.execute_command(
            f"ps -Tcjstv | grep -v grep | egrep 'WID|{self._process.pid}' | awk '{{print $10}}'", shell=True
        )
        children = None
        if "/bin/sh" in ps_process_result.stdout:
            logger.log(
                level=log_levels.MODULE_DEBUG, msg="Process started with children, looking for children processes"
            )
            children = ESXiRemoteProcess._find_children_process(self._owner, self._process.pid)
        with suppress(ProcessLookupError):
            logger.log(
                level=log_levels.MODULE_DEBUG, msg=f"Sending {with_signal.name} signal to process {self._process.pid}"
            )
            self._owner.modules().os.kill(self._process.pid, with_signal)
            if children is not None:
                for child in children:
                    logger.log(
                        level=log_levels.MODULE_DEBUG, msg=f"Sending {with_signal.name} signal to process {child}"
                    )
                    self._owner.modules().os.kill(child, with_signal)
