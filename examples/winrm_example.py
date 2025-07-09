# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT

import logging
import time

from mfd_connect.winrm import WinRmConnection

logging.basicConfig(level=logging.DEBUG)
conn = WinRmConnection(username="a", password="***", ip="10.10.10.10")


os_type = conn.get_os_type()
os_name = conn.get_os_name()
res = conn.start_process(
    command="ping localhost -n 5",
)
if res.running:
    time.sleep(5)
    if not res.running:
        logging.debug(res.stdout_text)
    else:
        logging.debug("Still running")
else:
    logging.debug(res.stdout_text)
conn.execute_command(
    command="ping localhost -n 5",
)
