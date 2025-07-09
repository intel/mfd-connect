# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
import time
import logging

logging.basicConfig(level=logging.DEBUG)
from mfd_connect.interactive_ssh import InteractiveSSHConnection

conn = InteractiveSSHConnection(ip="10.10.10.10", username="", password="", skip_key_verification=True)
logging.debug(conn.get_os_name())
logging.debug(conn.get_os_type())
proc = conn.start_process("ping localhost")
time.sleep(2)
proc.stop()
logging.debug(proc.stdout_text)
logging.debug(proc.return_code)
