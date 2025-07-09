# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT

import logging
import time

from mfd_connect.tunneled_rpyc import TunneledRPyCConnection

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def connect_to_windows_os():
    logger.debug("Through Linux to Windows")
    tunneled_connection = TunneledRPyCConnection(ip="10.10.10.10", jump_host_ip="10.10.10.11")

    logger.debug(tunneled_connection.get_os_name())

    path_windows = tunneled_connection.path(r"C:\k_test")
    logger.debug(f"Is {str(path_windows)} a dir? - {path_windows.is_dir()}")

    ping_process = tunneled_connection.start_process("ping.exe -t localhost", shell=False)
    logger.debug("Wait 10 seconds!")
    time.sleep(10)
    logger.debug(f"Process is running: {ping_process.running}")
    logger.debug("Stop process")
    ping_process.stop()
    logger.debug(f"Process is running: {ping_process.running}")

    logger.debug(f"Return code: {ping_process.return_code}")

    tunneled_connection.disconnect()


connect_to_windows_os()
