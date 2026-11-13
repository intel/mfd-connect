# Copyright (C) 2025-2026 Intel Corporation
# SPDX-License-Identifier: MIT
"""
RShell Server Script.

This script implements a RESTful server using Flask to manage command execution
on connected RShell clients.

Flow:
    1. ``/execute_command``      - caller queues a command and blocks until its result arrives.
    2. ``/getCommandToExecute``  - the EFI client polls for the next command to run.
    3. ``/post_result``          - the EFI client returns the command output.
    4. ``/exception``            - the EFI client reports a failure instead of an output.

Because the EFI client polls in a slow loop (and some commands take minutes), a waiter may
give up before its result arrives. Such a command is marked as *abandoned* so that:
    * it is skipped when the client asks for the next command (it is never executed late), and
    * its result is dropped on arrival instead of being stored forever.

This keeps the caller and the EFI client in sync after a timeout and keeps memory bounded.

The server also tracks client liveness. The EFI client executes commands with a blocking
``os.system()`` call, so a command that hangs on the DUT (for example a tool waiting for a
key press) stops the polling loop for good. From the caller side this is indistinguishable
from a slow command, therefore every timeout is reported together with a diagnosis telling
whether the client kept polling or went silent while executing an earlier command.
"""

import threading
import time
from collections import OrderedDict
from queue import Queue
from typing import NamedTuple, NoReturn
from uuid import uuid4

from flask import Flask, Response, abort, request
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge, ServiceUnavailable, TooManyRequests

__version__ = "1.3.0"

# How long the EFI client sleeps between polls - added to the caller timeout as a grace period.
CLIENT_LOOP_WAIT_SECONDS = 5
# How long an output that nobody collected is kept before it is evicted.
STALE_OUTPUT_TTL_SECONDS = 600
# Hard caps protecting the server against unbounded memory growth.
MAX_STORED_OUTPUTS = 512
MAX_ABANDONED_COMMAND_IDS = 512
MAX_PENDING_COMMANDS_PER_CLIENT = 256
MAX_ACTIVE_COMMANDS = 512
MAX_CLIENTS = 256
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_STORED_OUTPUT_BYTES = 64 * 1024 * 1024
# Longest single wait inside get_output() - keeps the waiting loop responsive.
OUTPUT_WAIT_SLICE_SECONDS = 1.0
# How long a client may stay silent before /health reports it as gone. The client does not poll
# while it executes a command, so this has to comfortably exceed a normal command duration.
CLIENT_LIVENESS_TIMEOUT_SECONDS = 300
# Keep unfinished-command diagnostics after their waiter and client admission slot are gone.
RUNNING_COMMAND_TTL_SECONDS = 3600
# Header carrying the human readable explanation of a 504 back to RShellConnection.
TIMEOUT_REASON_HEADER = "X-RShell-Timeout-Reason"
MAX_TIMEOUT_REASON_LENGTH = 1024


# Global command queue
class OutputObject(NamedTuple):
    """Store command output together with its return code."""

    output: str
    rc: int


class CommandObject(NamedTuple):
    """Store queued command metadata sent to a specific client."""

    command_id: str
    str: str


class RunningCommand(NamedTuple):
    """Store the command a client picked up and has not reported back yet."""

    command_id: str
    command: str
    started_at: float


output_object = OutputObject
command_object = CommandObject

# Results waiting to be collected by their /execute_command caller.
output_queue: "OrderedDict[str, OutputObject]" = OrderedDict()
output_queue_timestamps: dict[str, float] = dict()
output_sizes: dict[str, int] = dict()
output_errors: dict[str, tuple[int, str]] = dict()
active_commands: dict[str, str] = dict()
control_command_deadlines: dict[str, float] = dict()
# Commands whose caller already gave up - results must not be stored and they must not run.
abandoned_command_ids: "OrderedDict[str, float]" = OrderedDict()
# Per client (IP) queue of commands waiting to be picked up.
command_dict_queue: dict[str, Queue] = dict()
clients: list = []
# Last time (monotonic) each client asked for work - used to tell a slow command from a dead client.
client_last_seen: dict[str, float] = dict()
# Command each client picked up last and has not reported back yet.
client_running_command: dict[str, RunningCommand] = dict()

# Guards every structure above. Re-entrant so helpers can be called with the lock already held.
_state_lock = threading.RLock()
_output_available = threading.Condition(_state_lock)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_OUTPUT_BYTES


def _cleanup_stale_outputs(now: float | None = None, ttl: int = STALE_OUTPUT_TTL_SECONDS) -> None:
    """
    Remove orphaned command outputs that have been kept longer than the configured TTL.

    Also expires undelivered control commands and bounds retained running-command diagnostics,
    stored outputs and abandoned command IDs.

    :param now: Reference time (``time.monotonic()`` based). Defaults to the current time.
    :param ttl: Maximum age, in seconds, of an uncollected output.
    """
    with _state_lock:
        current_time = time.monotonic() if now is None else now

        for command_id, deadline in list(control_command_deadlines.items()):
            if current_time >= deadline:
                print(f"Control command {command_id} expired before delivery")
                _abandon_command(command_id)

        stale_outputs = [cid for cid, created in list(output_queue_timestamps.items()) if current_time - created >= ttl]
        for command_id in stale_outputs:
            _abandon_command(command_id)

        stale_abandoned = [cid for cid, created in list(abandoned_command_ids.items()) if current_time - created >= ttl]
        for command_id in stale_abandoned:
            abandoned_command_ids.pop(command_id, None)

        while len(output_queue) > MAX_STORED_OUTPUTS:
            _abandon_command(next(iter(output_queue)))

        while len(abandoned_command_ids) > MAX_ABANDONED_COMMAND_IDS:
            abandoned_command_ids.popitem(last=False)

        for ip, running in list(client_running_command.items()):
            if running.command_id not in active_commands and (
                current_time - running.started_at >= RUNNING_COMMAND_TTL_SECONDS
                or len(client_running_command) > MAX_CLIENTS
            ):
                client_running_command.pop(ip, None)

        busy_clients = set(active_commands.values())
        for ip, last_seen in list(client_last_seen.items()):
            if current_time - last_seen > CLIENT_LIVENESS_TIMEOUT_SECONDS and ip not in busy_clients:
                client_last_seen.pop(ip, None)
                command_dict_queue.pop(ip, None)
                if ip in clients:
                    clients.remove(ip)


def _abandon_command(command_id: str) -> None:
    """
    Mark a command as no longer awaited, so it is neither executed late nor stored on arrival.

    :param command_id: The ID of the command whose caller gave up.
    """
    with _output_available:
        abandoned_command_ids[command_id] = time.monotonic()
        ip = active_commands.pop(command_id, None)
        control_command_deadlines.pop(command_id, None)
        output_queue.pop(command_id, None)
        output_queue_timestamps.pop(command_id, None)
        output_sizes.pop(command_id, None)
        output_errors.pop(command_id, None)
        client_queue = command_dict_queue.get(ip)
        if client_queue is not None:
            pending = []
            while not client_queue.empty():
                queued = client_queue.get_nowait()
                if queued.command_id != command_id:
                    pending.append(queued)
            for queued in pending:
                client_queue.put_nowait(queued)
            if client_queue.empty():
                command_dict_queue.pop(ip, None)
        while len(abandoned_command_ids) > MAX_ABANDONED_COMMAND_IDS:
            abandoned_command_ids.popitem(last=False)
        _output_available.notify_all()


def _store_output(command_id: str, output: str, rc: int) -> bool:
    """
    Persist command output together with its insertion timestamp and wake up the waiter.

    Results of abandoned commands are dropped instead of being kept forever.

    :param command_id: The ID of the command the output belongs to.
    :param output: The command output.
    :param rc: The return code of the command.
    :return: True when the output was stored, False when it was dropped as abandoned.
    """
    with _output_available:
        _cleanup_stale_outputs()
        if command_id not in active_commands or command_id in output_queue or command_id in output_errors:
            abandoned_command_ids.pop(command_id, None)
            print(f"Dropping unsolicited or duplicate output for command {command_id}")
            return False
        size = len(output.encode("utf-8"))
        if size > MAX_OUTPUT_BYTES:
            _fail_output(command_id, RequestEntityTooLarge(description="RShell command output exceeds the size limit"))
        if len(output_queue) >= MAX_STORED_OUTPUTS or sum(output_sizes.values()) + size > MAX_STORED_OUTPUT_BYTES:
            _fail_output(command_id, ServiceUnavailable(description="RShell result storage is full"))
        output_queue[command_id] = output_object(output=output, rc=rc)
        output_queue_timestamps[command_id] = time.monotonic()
        output_sizes[command_id] = size
        _cleanup_stale_outputs()
        _output_available.notify_all()
        return True


def _fail_output(command_id: str, error: HTTPException) -> NoReturn:
    """Reject an output and notify its waiting caller without retaining the payload."""
    with _output_available:
        if command_id in active_commands and command_id not in output_queue:
            output_errors[command_id] = (error.get_response().status_code, error.description)
            _output_available.notify_all()
    raise error


def _check_client_limit(ip_address: str) -> None:
    """Reject new clients when all client slots are occupied."""
    known_clients = set(clients) | set(client_last_seen) | set(active_commands.values())
    if ip_address not in known_clients and len(known_clients) >= MAX_CLIENTS:
        raise TooManyRequests(description="RShell client limit reached")


def _mark_client_finished(ip_address: str, command_id: str) -> None:
    """
    Record that a client reported back, so it is no longer considered busy nor silent.

    :param ip_address: The IP address the result came from.
    :param command_id: The ID of the command the client reported.
    """
    with _state_lock:
        running = client_running_command.get(ip_address)
        if running is not None and running.command_id == command_id:
            client_running_command.pop(ip_address, None)
        if ip_address in clients:
            client_last_seen[ip_address] = time.monotonic()


def diagnose_timeout(ip_address: str, command: str, waiting_since: float, command_id: str | None = None) -> str:
    """
    Explain why a command timed out, based on whether the EFI client kept polling.

    The EFI client runs commands through a blocking ``os.system()`` call, so a tool that hangs
    on the DUT stops the polling loop permanently. Distinguishing that from a genuinely slow
    command is impossible for the caller, hence this explicit diagnosis.

    :param ip_address: The IP address of the client the command was queued for.
    :param command: The command that timed out.
    :param waiting_since: Monotonic timestamp of the moment the caller started waiting.
    :param command_id: The ID of the command that timed out, when known.
    :return: Human readable reason.
    """
    with _state_lock:
        last_seen = client_last_seen.get(ip_address)
        running = client_running_command.get(ip_address)
        if last_seen is None and running is not None:
            last_seen = running.started_at

    if last_seen is None:
        return (
            f"the RShell client {ip_address} has never contacted the server - "
            f"check that rshell_client.py is running on the DUT"
        )

    now = time.monotonic()

    if running is not None and command_id is not None and running.command_id == command_id:
        busy_for = now - running.started_at
        return (
            f"the RShell client {ip_address} picked this command up {busy_for:.0f}s ago and never reported "
            f"back - '{command}' is either still running or hangs on the DUT (for example waiting for "
            f"input); run it manually with output redirected to a file to check"
        )

    if last_seen < waiting_since:
        idle_for = now - last_seen
        reason = (
            f"the RShell client {ip_address} stopped polling {idle_for:.0f}s ago, so it never asked "
            f"for this command"
        )
        if running is not None:
            busy_for = now - running.started_at
            reason += f"; it is still blocked executing '{running.command}' started {busy_for:.0f}s ago"
        return reason + " - the command most likely hangs on the DUT (for example waiting for input)"

    return (
        f"the RShell client {ip_address} is alive and polling, but '{command}' did not finish in time - "
        f"consider passing a bigger timeout"
    )


def get_output(command_id: str, timeout: float = 600) -> OutputObject:
    """
    Retrieve the output for a given command ID, waiting until it arrives.

    The wait is event driven - the caller is woken up as soon as the result is posted.

    :param command_id: The ID of the command to retrieve output for.
    :param timeout: The maximum time to wait for output (in seconds).
    :return: The output for the given command ID.
    :raises TimeoutError: If the command times out.
    """
    print("Getting output for command ID:", command_id)
    print(f"Waiting for output {timeout} seconds")
    deadline = time.monotonic() + timeout + CLIENT_LOOP_WAIT_SECONDS
    with _output_available:
        while True:
            error = output_errors.pop(command_id, None)
            if error is not None:
                _abandon_command(command_id)
                abort(error[0], description=error[1])
            result = output_queue.pop(command_id, None)
            if result is not None:
                _abandon_command(command_id)
                return result
            if command_id not in active_commands:
                _abandon_command(command_id)
                raise TimeoutError("Command is no longer pending")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _abandon_command(command_id)
                raise TimeoutError("Command timed out")
            _output_available.wait(min(remaining, OUTPUT_WAIT_SLICE_SECONDS))


def add_command_to_queue(command: str, ip_address: str, timeout: float = 600) -> str:
    """
    Add a command to the global command queue.

    :param command: The command to add to the queue.
    :param ip_address: The IP address of the client.
    :param timeout: Delivery timeout for control commands, in seconds, before the client poll grace period.
    :return: The ID of the added command.
    """
    print("Adding command to queue:", command)
    _id = str(uuid4().int)
    with _state_lock:
        _cleanup_stale_outputs()
        _check_client_limit(ip_address)
        if len(active_commands) >= MAX_ACTIVE_COMMANDS:
            raise TooManyRequests(description="RShell active command limit reached")
        client_queue = command_dict_queue.get(ip_address)
        if client_queue is None:
            client_queue = Queue()
            command_dict_queue[ip_address] = client_queue
        if client_queue.qsize() >= MAX_PENDING_COMMANDS_PER_CLIENT:
            raise TooManyRequests(description="RShell client command queue is full")
        active_commands[_id] = ip_address
        if command == "end" or command.startswith("reset"):
            control_command_deadlines[_id] = time.monotonic() + timeout + CLIENT_LOOP_WAIT_SECONDS
        client_queue.put(command_object(command_id=_id, str=command))
    return _id


@app.route("/health/<ip>", methods=["GET"])
def health_check(ip: str) -> Response:
    """
    Report whether the RShell client is connected and still polling.

    A client that was seen once but went silent is reported as gone, otherwise a dead client
    would look healthy for the rest of the run.
    """
    with _state_lock:
        last_seen = client_last_seen.get(ip)
        connected = ip in clients and last_seen is not None
    if not connected or last_seen is None:
        return Response("Client not connected", status=503)
    silent_for = time.monotonic() - last_seen
    if silent_for <= CLIENT_LIVENESS_TIMEOUT_SECONDS:
        return Response("OK", status=200)
    return Response(f"Client stopped polling {silent_for:.0f}s ago", status=503)


@app.route("/getCommandToExecute", methods=["GET"])
def get_command_to_execute() -> Response:
    """
    Get the next command to execute for the connected client.

    Commands whose caller already timed out are skipped, so the client never falls behind.
    Every poll also refreshes the client liveness marker - the client only asks for work once
    the previous command finished.

    :return: The next command to execute.
    """
    ip_address = str(request.remote_addr)
    with _state_lock:
        _cleanup_stale_outputs()
        _check_client_limit(ip_address)
        if ip_address not in clients:
            print(f"Client connected: {ip_address}")
            clients.append(ip_address)
        client_last_seen[ip_address] = time.monotonic()
        client_running_command.pop(ip_address, None)
        client_queue = command_dict_queue.get(ip_address)
        while client_queue is not None and not client_queue.empty():
            queued_command = client_queue.get()
            if queued_command.command_id not in active_commands:
                abandoned_command_ids.pop(queued_command.command_id, None)
                print(f"Skipping abandoned command {queued_command.command_id} for {ip_address}")
                continue
            if client_queue.empty():
                command_dict_queue.pop(ip_address, None)
            if queued_command.str == "end" or queued_command.str.startswith("reset"):
                active_commands.pop(queued_command.command_id, None)
                control_command_deadlines.pop(queued_command.command_id, None)
            client_running_command[ip_address] = RunningCommand(
                command_id=queued_command.command_id,
                command=queued_command.str,
                started_at=time.monotonic(),
            )
            _cleanup_stale_outputs()
            return Response(
                queued_command.str,
                status=200,
                mimetype="text/plain",
                headers={"CommandID": queued_command.command_id},
            )
    return Response("No more elements left in the queue", status=204)


@app.route("/exception", methods=["POST"])
def post_exception() -> Response:
    """
    Receive exception details from the client.

    :param body: The exception details.
    :param CommandID: The ID of the command that caused the exception.
    :return: A response indicating the exception was received.
    """
    return _receive_output(-1, "Exception received")


def _receive_output(rc: int, message: str) -> Response:
    """Receive a size-limited result or exception for a pending command."""
    command_id = str(request.headers.get("CommandID"))
    try:
        read_data = request.data
    except RequestEntityTooLarge as error:
        _fail_output(command_id, error)
    print("CommandID: ", command_id)
    print(str(read_data, encoding="utf-8"))
    _mark_client_finished(str(request.remote_addr), command_id)
    stored = _store_output(command_id, str(read_data, encoding="utf-8"), rc=rc)
    return Response(message if stored else "Output no longer awaited", status=200)


@app.errorhandler(HTTPException)
def report_http_error(error: HTTPException) -> Response:
    """Report transport failures separately from command stdout."""
    app.logger.warning("RShell request failed: %s", error.description)
    return Response(
        b"",
        status=error.code,
        headers={"rc": "-1", "X-RShell-Error": error.description},
    )


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
    if not command:
        return Response("No command provided", status=400)

    _id = add_command_to_queue(command, ip_address, timeout)
    if command == "end":
        return Response("No more commands available to run", status=200)
    if command.startswith("reset"):
        return Response("Reset command sent", status=200)

    waiting_since = time.monotonic()
    try:
        process = get_output(_id, timeout)
    except TimeoutError:
        # Return a clean gateway timeout instead of a Flask HTML 500 page, which the caller
        # would otherwise store verbatim as the command stdout. The body stays empty on
        # purpose - the explanation travels in a header so it never pollutes stdout.
        reason = diagnose_timeout(ip_address, command, waiting_since, command_id=_id)
        print(f"Command {_id} timed out after {timeout}s - marked as abandoned; {reason}")
        return Response(
            b"",
            status=504,
            headers={
                "Content-type": "text/plain",
                "CommandID": _id,
                "rc": "-1",
                TIMEOUT_REASON_HEADER: reason.encode("unicode_escape").decode("ascii")[:MAX_TIMEOUT_REASON_LENGTH],
            },
        )
    finally:
        with _state_lock:
            _abandon_command(_id)

    return Response(
        process.output.encode("utf-8"),
        status=200,
        headers={
            "Content-type": "text/plain",
            "CommandID": _id,
            "rc": str(process.rc),
        },
    )


@app.route("/disconnect_client/<ip_address>", methods=["POST"])
def disconnect_client(ip_address: str) -> Response:
    """
    Disconnect a client from the server and drop everything queued for it.

    :param ip_address: The IP address of the client to disconnect.
    """
    with _output_available:
        if ip_address in clients:
            clients.remove(ip_address)
        client_last_seen.pop(ip_address, None)
        client_running_command.pop(ip_address, None)
        for command_id, ip in list(active_commands.items()):
            if ip == ip_address:
                _abandon_command(command_id)
        command_dict_queue.pop(ip_address, None)
        _cleanup_stale_outputs()
        print(f"Client disconnected: {ip_address}")
    return Response("Client disconnected", status=200)


@app.route("/post_result", methods=["POST"])
def post_result() -> Response:
    """Receive command execution results from the client."""
    rc = int(request.headers.get("rc", -1))
    return _receive_output(rc, "Results received")


def run() -> None:
    """Run the Flask REST server."""
    print("Starting Flask REST server...")
    app.run(host="0.0.0.0", port=80)


if __name__ == "__main__":
    run()
