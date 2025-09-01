# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""
RShell Server Script.

This script implements a RESTful server using Flask to manage command execution
on connected RShell clients.
"""

import time
from collections import namedtuple
from queue import Queue
from uuid import uuid4

from flask import Flask, Response, request

__version__ = "1.0.0"

# Global command queue
output_object = namedtuple("OutputObject", ["output", "rc"])
command_object = namedtuple("CommandObject", ["command_id", "str"])

output_queue: dict[str, output_object] = dict()
command_dict_queue: dict[str, Queue] = dict()
clients: list = []

app = Flask(__name__)


def get_output(command_id: str, timeout: float = 600) -> output_object:
    """
    Retrieve the output for a given command ID.

    :param command_id: The ID of the command to retrieve output for.
    :param timeout: The maximum time to wait for output (in seconds).
    :return: The output for the given command ID.
    :raises TimeoutError: If the command times out.
    """
    print("Getting output for command ID:", command_id)
    print(f"Waiting for output {timeout} seconds")
    timeout = timeout + 5  # add time for client loop waiting
    while timeout > 0:
        result = output_queue.get(command_id, None)
        if result is not None:
            return result
        time.sleep(1)
        timeout -= 1
    raise TimeoutError("Command timed out")


def add_command_to_queue(command: str, ip_address: str) -> str:
    """
    Add a command to the global command queue.

    :param command: The command to add to the queue.
    :param ip_address: The IP address of the client.
    :return: The ID of the added command.
    """
    print("Adding command to queue:", command)
    _id = str(uuid4().int)
    if command_dict_queue.get(ip_address) is None:
        command_dict_queue[ip_address] = Queue()
    command_dict_queue[ip_address].put(command_object(command_id=_id, str=command))
    return _id


@app.route("/health/<ip>", methods=["GET"])
def health_check(ip: str) -> Response:
    """Health check endpoint."""
    if ip in clients:
        return Response("OK", status=200)
    else:
        return Response("Client not connected", status=503)


@app.route("/getCommandToExecute", methods=["GET"])
def get_command_to_execute() -> Response:
    """
    Get the next command to execute for the connected client.

    :return: The next command to execute.
    """
    ip_address = str(request.remote_addr)
    if ip_address not in clients:
        print(f"Client connected: {ip_address}")
        clients.append(ip_address)
    client_queue = command_dict_queue.get(ip_address, Queue())
    if not client_queue.empty():
        command_object = client_queue.get()
        return Response(
            command_object.str,
            status=200,
            mimetype="text/plain",
            headers={"CommandID": command_object.command_id},
        )
    else:
        return Response("No more elements left in the queue", status=204)


@app.route("/exception", methods=["POST"])
def post_exception() -> Response:
    """
    Receive exception details from the client.

    :param body: The exception details.
    :param CommandID: The ID of the command that caused the exception.
    :return: A response indicating the exception was received.
    """
    read_data = request.data
    command_id = str(request.headers.get("CommandID"))
    print("CommandID: ", command_id)
    print(str(read_data, encoding="utf-8"))
    output_queue[command_id] = output_object(output=str(read_data, encoding="utf-8"), rc=-1)
    return Response("Exception received", status=200)


@app.route("/execute_command", methods=["POST"])
def execute_command() -> Response:
    """
    Execute a command on the connected client.

    :param command: The command to execute.
    :param timeout: The maximum time to wait for command execution (in seconds).
    :param ip: The IP address of the client.
    :return: The output of the executed command.
    """
    timeout = int(request.form.get("timeout", 600))
    command = request.form.get("command")
    ip_address = str(request.form.get("ip"))
    if command:
        _id = add_command_to_queue(command, ip_address)
        if command == "end":
            return Response("No more commands available to run", status=200)
        process = get_output(_id, timeout)
        return Response(
            process.output.encode("utf-8"),
            status=200,
            headers={
                "Content-type": "text/plain",
                "CommandID": _id,
                "rc": process.rc,
            },
        )
    else:
        return Response("No command provided", status=400)


@app.route("/post_result", methods=["POST"])
def post_result() -> Response:
    """Receive command execution results from the client."""
    read_data = request.data
    command_id = str(request.headers.get("CommandID"))
    rc = int(request.headers.get("rc", -1))
    print("CommandID: ", command_id)
    print(str(read_data, encoding="utf-8"))
    output_queue[command_id] = output_object(output=str(read_data, encoding="utf-8"), rc=rc)
    return Response("Results received", status=200)


if __name__ == "__main__":
    print("Starting Flask REST server...")
    app.run(host="0.0.0.0", port=80)
