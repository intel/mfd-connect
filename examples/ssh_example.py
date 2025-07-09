# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT

import time

import subprocess

from mfd_connect import SSHConnection

# LINUX
# using ssh keys without password for keys
conn = SSHConnection(ip="10.10.10.10", username="root", password=None, key_path="/root/.ssh/id_rsa_gen")
# using password
conn = SSHConnection(username="root", password="***", ip="10.10.10.10")


os_type = conn.get_os_type()
os_name = conn.get_os_name()
print(f"Detected os type: {os_type}\n")
print(f"Detected os name: {os_name}\n")
res = conn.execute_command(command="dir", cwd="/")
print("PROCESS STDOUT:")
print(f"STDOUT:\n{res.stdout}\n")
print(f"STDERR:\n{res.stderr}\n")

proc = conn.start_process(command="ping 10.10.10.11")

time.sleep(5)

proc2 = conn.start_process(command="ping 10.10.10.11 -c 10")

proc.kill()

for line in proc2.get_stdout_iter():
    print(line.strip())

# WINDOWS
conn = SSHConnection(username="administrator", password="***", ip="10.10.10.20")

os_type = conn.get_os_type()
os_name = conn.get_os_name()
print(f"Detected os type: {os_type}\n")
print(f"Detected os name: {os_name}\n")

# Execute command
res = conn.execute_command(command="dir", cwd="c:\\")
print("PROCESS STDOUT:")
print(f"STDOUT:\n{res.stdout}\n")
print(f"STDERR:\n{res.stderr}\n")


# Execute command with custom exception
class MyException(subprocess.CalledProcessError):
    pass


res = conn.execute_command(command="dir nonExistsFolder", cwd="c:\\", custom_exception=MyException)
# raises MyException
print("PROCESS STDOUT:")
print(f"STDOUT:\n{res.stdout}\n")
print(f"STDERR:\n{res.stderr}\n")

proc = conn.start_process(command="ping 10.10.10.10 -n 100")

time.sleep(1)

proc2 = conn.start_process(command="ping 10.10.10.11 -n 10")

proc.kill()

for line in proc2.get_stdout_iter():
    print(line.strip())
