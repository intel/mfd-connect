# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT

import logging
from mfd_connect import SerialConnection, SSHConnection, LocalConnection
from mfd_common_libs import log_levels, add_logging_level

add_logging_level(level_name="MODULE_DEBUG", level_value=log_levels.MODULE_DEBUG)
logging.basicConfig(level=log_levels.MODULE_DEBUG)
logger = logging.getLogger(__name__)


host_info = {"ip": "10.10.10.10", "username": "user", "password": "***"}
# host_conn = LocalConnection()  # use when connecting to serial device on the same setup
host_conn = SSHConnection(ip=host_info["ip"], username=host_info["username"], password=host_info["password"])

conn = SerialConnection(
    connection=host_conn,
    username="***",
    password="***",
    telnet_port=1240,
    serial_device="/dev/ttyUSB1",
    login_prompt="expected login: ",
    is_veloce=False,
)

res = conn.execute_command("uname -a")
logger.info(res)
logger.info(f"Output from command: {res.stdout}")

res = conn.execute_command("ls /usr/bin")
logger.info(res)
logger.info(f"Output from command: {res.stdout}")

res = conn.execute_command("ping 1234.1.1.1")  # command should raise exception
logger.info(res)

res = conn.fire_and_forget(
    "pppd -detach lock 192.168.10.1:192.168.10.100 /dev/ttyS0 460800"
)  # command will ignore output and return code
logger.info(res)
