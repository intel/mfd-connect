# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT

from mfd_connect import RPyCZeroDeployConnection
import logging

logging.basicConfig(level=logging.DEBUG)

# using normal definition
conn = RPyCZeroDeployConnection(
    ip="10.10.10.10", username="***", password="***", python_executable="/usr/local/py37/bin/python3.7"
)
res = conn.execute_command(command="ip a", shell=True, expected_return_codes={0, 1})
conn.close()

# using context manager
with RPyCZeroDeployConnection(
    ip="10.10.10.10", username="***", password="***", python_executable="/usr/local/py37/bin/python3.7"
) as conn:
    res = conn.execute_command(command="ip a", shell=True, expected_return_codes={0, 1})
    print(f"STDERR:\n{res.stderr}\n")
    print(f"STDOUT:\n{res.stdout}\n")
    print(f"RETURN_CODE:\n{res.return_code}\n")

    # Create asynchronous process
    proc = conn.start_process(command="ls", shell=True)
    # Read stdout line by line in realtime
    print("PROCESS STDOUT:")

    for line in proc.get_stdout_iter():
        print(line.strip())

    # Use installed python modules
    file_list = conn.modules().os.listdir()
    print(f"RESULT OF MODULES USAGE:\n{file_list}")

    proc = conn.start_process(command="ping localhost -c 5", shell=True)

    # Read stdout line by line in realtime after restart
    print("PROCESS STDOUT:")

    for line in proc.get_stdout_iter():
        print(line.strip())
