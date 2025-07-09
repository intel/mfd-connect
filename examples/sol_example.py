# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT

from mfd_connect import SolConnection
from mfd_connect.util import SerialKeyCode

conn_cfg = {"username": "root", "password": "***", "ip": "10.10.10.10", "connection_type": SolConnection}
conn_class = conn_cfg.pop("connection_type")
conn = conn_class(**conn_cfg)

# Execute command
res = conn.execute_command(command="ls", expected_return_codes=[0])
print(f"STDOUT:\n{res.stdout}\n")
print(f"RC:\n{res.return_code}\n")

# Get name of OS
print(conn.get_os_name())

# # Press F11 for boot menu in POST state
conn.send_key(SerialKeyCode.F11)
print(f"Screen text after F11:\n{conn.get_output_after_user_action()}")
