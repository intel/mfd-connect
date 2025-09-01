# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
import logging
logging.basicConfig(level=logging.DEBUG)
from mfd_connect.rshell import RShellConnection 

# LINUX
conn = RShellConnection(ip="10.10.10.10") # start and connect to rshell server
# conn = RShellConnection(ip="10.10.10.10", server_ip="10.10.10.11") # connect to rshell server
conn.execute_command("ls")
conn.disconnect(True)
