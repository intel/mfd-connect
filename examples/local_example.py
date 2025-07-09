# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
import subprocess

from mfd_connect import LocalConnection

# Create mfd_connect object
conn = LocalConnection()

# Execute command
res = conn.execute_command(command="net %i 'This is test text'", shell=True, expected_return_codes={0, 1})
print(f"STDERR:\n{res.stderr}\n")
print(f"STDOUT:\n{res.stdout}\n")
print(f"RETURN_CODE:\n{res.return_code}\n")

# Create asynchronous process
proc = conn.start_process(command="dir", shell=True)
# Read stdout line by line in realtime
print("PROCESS STDOUT:")
for line in proc.get_stdout_iter():
    print(line.strip())

# Use installed python modules
file_list = conn.modules().os.listdir()
print(f"RESULT OF MODULES USAGE:\n{file_list}")

# Get type of os
os_type = conn.get_os_type()
print(f"Type of OS:\n{os_type}")

# Get name of os
os_name = conn.get_os_name()
print(f"Name of OS:\n{os_name}")


# Execute command with custom exception
class MyException(subprocess.CalledProcessError):
    pass


res = conn.execute_command(
    command="dir NonExistsFolder", shell=True, expected_return_codes={0}, custom_exception=MyException
)
# raises MyException

conn.enable_sudo()
# execute command will call ls with sudo
conn.execute_command(command="ls", shell=True, expected_return_codes={0, 1})
conn.disable_sudo()