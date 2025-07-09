# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT

import subprocess
from signal import SIGTERM, SIGINT

from mfd_connect import RPyCConnection

# Create mfd_connect object
conn_win = RPyCConnection(ip="XXX")  # EXAMPLE windows machine IP
conn_lnx = RPyCConnection(ip="XXX")  # EXAMPLE of LNX machine IP
# both machines have to have RPyC version above 4.0
conn = RPyCConnection(ip="XXX", ssl_certfile="cert.pem", ssl_keyfile="key.pem")  # EXAMPLE of SSL connection

# Execute command

res = conn_win.execute_command(command="netsh interface ip show address", shell=True, expected_return_codes={0, 1})
print(f"STDERR:\n{res.stderr}\n")
print(f"STDOUT:\n{res.stdout}\n")
print(f"RETURN_CODE:\n{res.return_code}\n")

res = conn_win.execute_powershell(command="Get-VMSwitch | fl", shell=False, expected_return_codes={0, 1})
print(f"STDERR:\n{res.stderr}\n")
print(f"STDOUT:\n{res.stdout}\n")
print(f"RETURN_CODE:\n{res.return_code}\n")

for conn, command in zip([conn_win, conn_lnx], ["netsh interface ip show address", "ip a"]):
    res = conn.execute_command(command=command, shell=True, expected_return_codes={0, 1})
    print(f"STDERR:\n{res.stderr}\n")
    print(f"STDOUT:\n{res.stdout}\n")
    print(f"RETURN_CODE:\n{res.return_code}\n")

for conn, cmd in zip([conn_win, conn_lnx], ["dir", "ls"]):
    # Create asynchronous process
    proc = conn.start_process(command=cmd, shell=True)
    # Read stdout line by line in realtime
    print("PROCESS STDOUT:")

    for line in proc.get_stdout_iter():
        print(line.strip())

    # Use installed python modules
    file_list = conn.modules().os.listdir()
    print(f"RESULT OF MODULES USAGE:\n{file_list}")

    # restart platform
    conn.restart_platform()
    conn.wait_for_host(360)

    proc = conn.start_process(command=cmd, shell=True)

    # Read stdout line by line in realtime after restart
    print("PROCESS STDOUT:")

    for line in proc.get_stdout_iter():
        print(line.strip())


# Execute command with custom exception
class MyException(subprocess.CalledProcessError):
    pass


for conn, command in zip([conn_win, conn_lnx], ["dir NonExistsFolder", "ls NonExistsFolder"]):
    res = conn.execute_command(command=command, shell=True, expected_return_codes={0}, custom_exception=MyException)
    # raises MyException


cmd = "ping localhost"

# Send signals to process
proc = conn_lnx.start_process(command=cmd, shell=True)
proc.stop()  # stop process using SIGINT
proc.kill(with_signal=SIGTERM)  # kill process using SIGTERM
proc.kill(with_signal=SIGINT)  # kill process using SIGINT
proc.kill(with_signal=2)  # kill process using SIGINT
proc.kill(with_signal="sigint")  # kill process using SIGINT
