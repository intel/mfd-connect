# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Package for Connection implementations."""

import logging

logger = logging.getLogger(__name__)

import platform  # noqa E402

from mfd_typing import OSName  # noqa E402

from .base import Connection, AsyncConnection, PythonConnection  # noqa E402
from .local import LocalConnection  # noqa E402
from .rpyc import RPyCConnection  # noqa E402
from .tunneled_rpyc import TunneledRPyCConnection  # noqa E402
from .sol import SolConnection  # noqa E402
from .serial import SerialConnection  # noqa E402
from .telnet.telnet import TelnetConnection  # noqa E402

if platform.system() != OSName.ESXI.value:
    from .winrm import WinRmConnection  # noqa E402
    from .ssh import SSHConnection  # noqa E402
    from .interactive_ssh import InteractiveSSHConnection  # noqa E402
    from .tunneled_ssh import TunneledSSHConnection  # noqa E402
    from .rpyc_zero_deploy import RPyCZeroDeployConnection  # noqa E402
    from .pxssh import PxsshConnection  # noqa E402
