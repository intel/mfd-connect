# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""
RShell Client Script.

Make sure that the Python UEFI interpreter is compiled with
Socket module support.

Usage::

    rshell_client.py <server_ip> [source_ip] [source_port]

The client polls the server for work, runs one command at a time and posts the result back.
Commands are executed with a blocking ``os.system()`` call, so a tool that waits for input on
the DUT stops the whole loop - every later command then times out on the server side. Keep
that in mind when adding tools: always run them in a non interactive/batch mode.
"""

__version__ = "1.2.0"

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
# Local port the outgoing connection is bound to. Only relevant together with source_address,
# which exists so that the server sees the expected client IP. Override it when the fixed
# port collides with sockets left in TIME_WAIT by previous connections.
if len(sys.argv) > 3:
    source_port = int(sys.argv[3])
else:
    source_port = 80

# How long to wait before retrying after a failed server interaction.
RETRY_WAIT_SECONDS = 5

os_name = os.name


def _sleep(interval):  # noqa: ANN001, ANN202
    """
    Simulate the sleep function for EFI shell as the sleep API from time module is not working on EFI shell.

    :param interval: time period the system to be in idle
    """
    start_ts = time.time()
    while time.time() < start_ts + interval:
        pass


time.sleep = _sleep


def _close(connection):  # noqa: ANN001, ANN202
    """Close a connection without letting a broken socket kill the client."""
    if connection is None:
        return
    try:
        connection.close()
    except Exception as exp:  # noqa: BLE001
        print("Ignoring error while closing the connection:", exp)


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
    source_address_parameter = (source_address, source_port) if source_address else None
    conn = None
    try:
        conn = client.HTTPConnection(http_server, source_address=source_address_parameter)
        # get the command from server
        _command = _get_command()
    except Exception as exp:  # noqa: BLE001
        # A transient network error must not end the client. If it did, the DUT would stop
        # asking for work and every following command would time out on the server.
        print("Failed to get a command from the server:", exp)
        _close(conn)
        time.sleep(RETRY_WAIT_SECONDS)
        continue

    if not _command:
        _close(conn)
        time.sleep(RETRY_WAIT_SECONDS)
        continue
    cmd_str, _id = _command
    cmd_str = cmd_str.decode("utf-8")
    cmd_name = cmd_str.split(" ")[0]
    if cmd_name == "end":
        print("No more commands available to run")
        _close(conn)
        exit(0)

    print("Executing", cmd_str)
    if cmd_name.startswith("reset"):
        print("Reset command received, shutting down the platform")
        os.system(cmd_str)  # execute reset command on machine
        _close(conn)
        exit(0)

    non_echo = False
    if cmd_name.startswith("echo"):
        cmd = cmd_str
    else:
        non_echo = True
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

        output = ""
        f = None
        if non_echo:
            f = open(out, "r", encoding=encoding)
            output = f.read()

        conn.request(
            "POST",
            "post_result",
            body=output,
            headers={"Content-Type": "text/plain", "Connection": "keep-alive", "CommandID": _id, "rc": rc},
        )
        if non_echo and f:
            f.close()
            os.system("del " + out)
    except Exception as exp:  # noqa: BLE001
        try:
            conn.request(
                "POST",
                "exception",
                body=cmd + str(exp),
                headers={"Content-Type": "text/plain", "Connection": "keep-alive", "CommandID": _id},
            )
        except Exception as report_exp:  # noqa: BLE001
            # Reporting failed too - stay alive so the next poll can still reach the server.
            print("Failed to report the error to the server:", report_exp)

    print("output posted to server")
    _close(conn)
    print("closed the connection")
    time.sleep(1)
