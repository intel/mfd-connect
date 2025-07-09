# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT

from mfd_connect import PxsshConnection

# LINUX
conn = PxsshConnection(username="", password="", ip="10.10.10.10")
print(conn.get_os_type())
print(conn.get_os_name())
print(conn.get_os_bitness())

# Execute command
ret = conn.execute_command(command="dir", prompts=" $", expected_return_codes=[0])
print("PROCESS STDOUT:")
print(f"STDOUT:\n{ret}\n")

ret = conn.execute_command(command="uname -a", prompts=" $", expected_return_codes=[0])
print("PROCESS STDOUT:")
print(f"STDOUT:\n{ret}\n")

conn.enable_sudo()

conn.disable_sudo()

conn._disconnect()

conn._reconnect()

ret = conn.execute_command(command="uname -a", prompts=" $", expected_return_codes=[0])
print("PROCESS STDOUT:")
print(f"STDOUT:\n{ret}\n")
