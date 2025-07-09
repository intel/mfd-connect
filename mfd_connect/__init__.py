# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Package for Connection implementations."""

import sys
import logging

logger = logging.getLogger(__name__)

if "-m" in sys.argv and "mfd_connect.rpyc_server" in sys.argv:
    logger.log(logging.DEBUG, "Running as a module - skipping importing in mfd_connect.__init__")
else:
    import platform

    from mfd_typing import OSName

    from .base import Connection, AsyncConnection, PythonConnection
    from .local import LocalConnection
    from .rpyc import RPyCConnection
    from .tunneled_rpyc import TunneledRPyCConnection
    from .sol import SolConnection
    from .serial import SerialConnection
    from .telnet.telnet import TelnetConnection
    from .winrm import WinRmConnection

    if platform.system() != OSName.ESXI.value:
        from .ssh import SSHConnection
        from .interactive_ssh import InteractiveSSHConnection
        from .tunneled_ssh import TunneledSSHConnection
        from .rpyc_zero_deploy import RPyCZeroDeployConnection
        from .pxssh import PxsshConnection
