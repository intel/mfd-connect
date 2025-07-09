# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT

import logging
from mfd_connect import TelnetConnection
from mfd_common_libs import log_levels, add_logging_level

add_logging_level(level_name="MODULE_DEBUG", level_value=log_levels.MODULE_DEBUG)
logging.basicConfig(level=log_levels.MODULE_DEBUG)
logger = logging.getLogger(__name__)

conn = TelnetConnection(
    ip="10.10.10.10",
    username="user",
    password="***",
    port=23,
)

res = conn.execute_command("uname -a")
logger.info(res)
logger.info(f"Output from command: {res.stdout}")

res = conn.execute_command("ls /usr/bin")
logger.info(res)
logger.info(f"Output from command: {res.stdout}")

res = conn.execute_command("ping 1234.1.1.1")  # command should raise exception
logger.info(res)
