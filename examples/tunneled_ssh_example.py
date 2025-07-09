# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT

import time

from mfd_connect import TunneledSSHConnection

# LINUX
conn = TunneledSSHConnection(
    ip="192.168.0.1",
    jump_host_ip="10.10.10.10",
    username="user",
    password="***",
    jump_host_username="root",
    jump_host_password="***",
)  # change to appropriate credentials

os_type = conn.get_os_type()
os_name = conn.get_os_name()
print(f"Detected os type: {os_type}\n")
print(f"Detected os name: {os_name}\n")
res = conn.execute_command(command="dir", cwd="/")
print("PROCESS STDOUT:")
print(f"STDOUT:\n{res.stdout}\n")
print(f"STDERR:\n{res.stderr}\n")

proc = conn.start_process(command="ping 192.168.0.2")  # change to appropriate credentials

time.sleep(5)

proc2 = conn.start_process(command="ping 192.168.0.2 -c 10")  # change to appropriate credentials

proc.kill()

for line in proc2.get_stdout_iter():
    print(line.strip())


# LINUX
# this connection selects free local bind address and free jump host port
conn = TunneledSSHConnection(
    ip="192.168.0.1",
    jump_host_ip="10.10.10.10",
    username="user",
    password="***",
    jump_host_username="root",
    jump_host_password="***",
    jump_host_port=None,
    local_bind_port=None,
)  # change to appropriate credentials
res = conn.execute_command(command="dir", cwd="/")
print("PROCESS STDOUT:")
print(f"STDOUT:\n{res.stdout}\n")
print(f"STDERR:\n{res.stderr}\n")


for line in proc2.get_stdout_iter():
    print(line.strip())
