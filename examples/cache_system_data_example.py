# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
import logging
from typing import TYPE_CHECKING

from mfd_common_libs import add_logging_level, log_levels
from mfd_common_libs.log_levels import MODULE_DEBUG

from mfd_connect import RPyCConnection, SSHConnection, LocalConnection

logger = logging.getLogger(__name__)
add_logging_level(level_name="MODULE_DEBUG", level_value=log_levels.MODULE_DEBUG)
add_logging_level(level_name="CMD", level_value=log_levels.CMD)
add_logging_level(level_name="OUT", level_value=log_levels.OUT)
logging.basicConfig(level=logging.DEBUG)

if TYPE_CHECKING:
    from mfd_connect import Connection


def check_cache_feature(connection: "Connection") -> None:
    for i in range(10):
        if i == 4:
            conn.cache_system_data = False
            logger.log(
                level=MODULE_DEBUG,
                msg="***************CACHE set to FALSE***************",
            )
        logger.log(level=MODULE_DEBUG, msg=f"Iter: {i}")
        logger.log(level=MODULE_DEBUG, msg=f"OS NAME: {connection.get_os_name()}")
        logger.log(level=MODULE_DEBUG, msg=f"OS type: {connection._os_type}")
        logger.log(level=MODULE_DEBUG, msg=f"OS bitness: {connection.get_os_bitness()}")
        logger.log(
            level=MODULE_DEBUG, msg=f"OS CPU arch: {connection.get_cpu_architecture()}"
        )
        if i == 4:
            conn.cache_system_data = True
            logger.log(
                level=MODULE_DEBUG,
                msg="***************CACHE set to TRUE***************",
            )


if __name__ == "__main__":
    connections = [
        SSHConnection(ip="10.10.10.10", username="***", password="***"),
        RPyCConnection(ip="10.10.10.11"),
        LocalConnection(),
    ]
    for conn in connections:
        check_cache_feature(conn)
        conn.disconnect()
