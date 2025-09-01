# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""
RShell Client Script.

Make sure that the Python UEFI interpreter is compiled with
Socket module support.
"""

__version__ = "1.0.0"

try:
    import httplib as client
except ImportError:
    from http import client
import sys
import os
import time

# get http server ip
http_server = sys.argv[1]
if len(sys.argv) > 2:
    source_address = sys.argv[2]
else:
    source_address = None

os_name = os.name


def _sleep(interval):  # noqa: ANN001, ANN202
    """
    Simulate the sleep function for EFI shell as the sleep API from time module is not working on EFI shell.

    :param interval time period the system to be in idle
    """
    start_ts = time.time()
    while time.time() < start_ts + interval:
        pass


time.sleep = _sleep


def _get_command():  # noqa: ANN202
    """Get the command from server to execute on client machine."""
    # construct the list of tests by interacting with server
    conn.request("GET", "getCommandToExecute")
    rsp = conn.getresponse()
    status = rsp.status
    _id = rsp.getheader("CommandID")
    if status == 204:
        return None

    print("Waiting for command from server: ")
    data_received = rsp.read()
    print(data_received)
    test_list = data_received.split(b",")

    return test_list[0], _id  # return only the first command


while True:
    # Connect to server
    source_address_parameter = (source_address, 80) if source_address else None
    conn = client.HTTPConnection(http_server, source_address=source_address_parameter)
    # get the command from server
    _command = _get_command()
    if not _command:
        conn.close()
        time.sleep(5)
        continue
    cmd_str, _id = _command
    cmd_str = cmd_str.decode("utf-8")
    cmd_name = cmd_str.split(" ")[0]
    if cmd_name == "end":
        print("No more commands available to run")
        conn.close()
        exit(0)

    print("Executing", cmd_str)

    out = cmd_name + ".txt"
    cmd = cmd_str + " > " + out

    time.sleep(5)
    rc = os.system(cmd)  # execute command on machine
    print("Executed the command")
    time.sleep(5)

    print("Posting the results to server")
    # send response to server
    try:
        if os_name == "edk2":
            encoding = "utf-16"
        else:
            encoding = "utf-8"

        f = open(out, "r", encoding=encoding)

        conn.request(
            "POST",
            "post_result",
            body=f.read(),
            headers={"Content-Type": "text/plain", "Connection": "keep-alive", "CommandID": _id, "rc": rc},
        )
        f.close()
        os.system("del " + out)
    except Exception as exp:
        conn.request(
            "POST",
            "exception",
            body=cmd + str(exp),
            headers={"Content-Type": "text/plain", "Connection": "keep-alive", "CommandID": _id},
        )

    print("output posted to server")
    conn.close()
    print("closed the connection")
    time.sleep(1)
