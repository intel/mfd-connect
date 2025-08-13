# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for TunneledSSHConnection class."""

import mfd_connect.sshtunnel as sshtunnel
import logging

from netaddr import IPAddress
from typing import Iterable, Type, TYPE_CHECKING, Optional, List, Union
from subprocess import CalledProcessError
from mfd_common_libs import add_logging_level, log_levels
from .exceptions import SSHTunnelException
from .ssh import SSHConnection

if TYPE_CHECKING:
    from .process.ssh.base import SSHProcess
    from .base import ConnectionCompletedProcess
    from pydantic import BaseModel
    from pathlib import PurePath

logger = logging.getLogger(__name__)
add_logging_level(level_name="MODULE_DEBUG", level_value=log_levels.MODULE_DEBUG)
add_logging_level(level_name="CMD", level_value=log_levels.CMD)
# set paramiko debug prints into WARNING level because of visible paramiko logs with mfd logs
logging.getLogger("paramiko").setLevel(logging.WARNING)
logging.getLogger("paramiko.transport").setLevel(logging.CRITICAL)

local_bind_ports_in_use = []
DEFAULT_LOCAL_BIND_PORT = 10022


class TunneledSSHConnection(SSHConnection):
    """
    Implementation of SSHConnection type using tunneled connection for remote usage.

    Operations will be performed on machine via SSH connection.

    Usage example:
    >>> conn = TunneledSSHConnection(ip="192.168.0.1", jump_host_ip="10.10.10.10")
    >>> res = conn.execute_command("echo something", shell=True)
    test
    """

    def __init__(
        self,
        ip: str,
        jump_host_ip: str,
        *args,
        port: int = 22,
        jump_host_port: int | None = 22,
        local_bind_port: int = DEFAULT_LOCAL_BIND_PORT,
        tunnel_start_retries: int = 10,
        username: str,
        password: str,
        jump_host_username: str,
        jump_host_password: str,
        skip_key_verification: bool = False,
        model: "BaseModel | None" = None,
        default_timeout: int | None = None,
        cache_system_data: bool = True,
        **kwargs,
    ) -> None:
        """
        Initialise TunneledSSHConnection.

        :param ip: IP address of target SSH server
        :param jump_host_ip: IP address of jump host SSH server
        :param port: port of target SSH server
        :param jump_host_port: port of jump host SSH server
        :param local_bind_port: port on which SSH tunnel will be bound locally. Every connection should have unique port
        :param tunnel_start_retries: number of retries with incremented local bind port when provided is not available
        :param username: username for target server
        :param password: password for target server
        :param jump_host_username: username for jump host server
        :param jump_host_password: password for jump host server
        :param skip_key_verification: skip checking of key of tunneled connection, same as StrictHostKeyChecking=no
        :param model: pydantic model of connection
        :param default_timeout: Timeout value for executing timeout for entire class.
        :param cache_system_data: Flag to cache system data like self._os_type, OS name, OS bitness and CPU architecture
        :raises SSHTunnelException: when could not start SSH tunnel to target via jump host
        """
        if local_bind_port is None:
            local_bind_port = DEFAULT_LOCAL_BIND_PORT

        self._target_ip = ip
        # added number of used local bind ports to not affect number of retires
        for _ in range(tunnel_start_retries + len(local_bind_ports_in_use)):
            if local_bind_port in local_bind_ports_in_use:
                logger.log(
                    level=log_levels.MODULE_DEBUG,
                    msg=f"local_bind_port: {local_bind_port} is already in use. Trying to find available one.",
                )
                local_bind_port += 1
                continue
            else:
                local_bind_ports_in_use.append(local_bind_port)

            ssh_address_or_host = self._set_ssh_address_or_host(jump_host_port, jump_host_ip)
            local_bind_address = "0.0.0.0", local_bind_port
            remote_bind_address = (str(IPAddress(ip)), port)
            try:
                self._tunnel = sshtunnel.SSHTunnelForwarder(
                    ssh_address_or_host=ssh_address_or_host,
                    remote_bind_address=remote_bind_address,
                    ssh_username=jump_host_username,
                    ssh_password=jump_host_password,
                    local_bind_address=local_bind_address,
                    **kwargs,
                )
                self._tunnel.start()
                break
            except sshtunnel.HandlerSSHTunnelForwarderError:
                logger.log(
                    level=log_levels.MODULE_DEBUG,
                    msg=f"Cannot start tunnel to {ip}:{port} via {jump_host_ip}:{jump_host_port} "
                    f"using local bind port {local_bind_port}, retrying with {local_bind_port+1}",
                )
                local_bind_port += 1
        else:
            raise SSHTunnelException(
                f"Cannot start tunnel to {ip}:{port} via {jump_host_ip}:{jump_host_port}. "
                f"Make sure that local bind ports are not in use."
            )

        logger.log(
            level=log_levels.MODULE_DEBUG,
            msg=f'Tunnel status: {"active" if self._tunnel.is_active else "disabled"}, '
            f"local bind port: {local_bind_port}",
        )
        super().__init__(
            ip="127.0.0.1",
            username=username,
            password=password,
            port=local_bind_port,
            model=model,
            skip_key_verification=skip_key_verification,
            default_timeout=default_timeout,
            cache_system_data=cache_system_data,
            **kwargs,
        )

    def __str__(self):
        return "tunneled_ssh"

    @property
    def ip(self) -> str:
        """IP address of the target SSH server."""
        return self._target_ip

    def _set_ssh_address_or_host(self, jump_host_port: Optional[int], jump_host_ip: str) -> str:
        """
        Set ssh_address_or_host for SSHTunnelForwarder instance.

        If jump_host_port set to None is passed, the SSHTunnelForwarder instance can quickly pick free jump_host_port.

        :param jump_host_port: the port on the jump host the SSH tunnel uses
        :param jump_host_ip: the ip of the jump host the SSH tunnel uses
        :return: set ssh_address_or_host for SSHTunnelForwarder instance
        """
        if jump_host_port:
            ssh_address_or_host = (str(IPAddress(jump_host_ip)), jump_host_port)
        else:
            ssh_address_or_host = str(IPAddress(jump_host_ip))
        return ssh_address_or_host

    def disconnect(self) -> None:
        """Close connection and stop tunnel."""
        super().disconnect()
        self._tunnel.stop()

    def _reconnect_tunnel_if_not_available(self) -> None:
        """
        Check if SSH tunnel is active. If not, try to reconnect it.

        :raises SSHTunnelException: when failed to reconnect inactive SSH tunnel
        """
        if self._tunnel.is_active:
            return

        logger.log(level=log_levels.MODULE_DEBUG, msg="Tunnel is not active, trying to restart...")
        self._tunnel.restart()

        if not self._tunnel.is_active:
            raise SSHTunnelException("Tunnel is not active and failed to restart")

        logger.log(level=log_levels.MODULE_DEBUG, msg="Tunnel reconnected successfully.")

    def execute_command(
        self,
        command: str,
        *,
        input_data: str = None,
        cwd: str = None,
        timeout: int = None,
        env: dict = None,
        stderr_to_stdout: bool = False,
        discard_stdout: bool = False,
        discard_stderr: bool = False,
        skip_logging: bool = False,
        expected_return_codes: Optional[Iterable] = frozenset({0}),
        shell: bool = False,
        custom_exception: Type[CalledProcessError] = None,
        get_pty: bool = False,
    ) -> "ConnectionCompletedProcess":
        """
        Run program and wait for it's completion.

        :param command: Command to execute, with all necessary arguments
        :param input_data: Data to pass to program on the standard input
        :param cwd: Directory to start program execution in
        :param timeout: Program execution timeout, in seconds
        :param env: Environment to execute the program in
        :param stderr_to_stdout: Redirect stderr to stdout, ignored if discard_stderr is set to True
        :param discard_stdout: Don't capture stdout stream
        :param discard_stderr: Don't capture stderr stream
        :param skip_logging: Skip logging of stdout/stderr if captured
        :param expected_return_codes: Return codes to be considered acceptable.
                                      If None - any return code is considered acceptable
        :param shell: Start process in a shell. Allows usage of shell constructions like pipes etc.
        :param custom_exception: Enable us to raise our exception if program exits with an unexpected return code.
        :param get_pty: Request a pseudo-terminal from the server.
        custom_exception must inherit from CalledProcessError to use its fields like returncode, cmd, output, stderr

        :return: ConnectionCompletedProcess object
        :raises TimeoutExpired: if program doesn't conclude before timeout is reached
        :raises ConnectionCalledProcessError: if program exits with an unexpected return code
        :raises SSHTunnelException: when failed to reconnect inactive SSH tunnel
        """
        self._reconnect_tunnel_if_not_available()
        return super().execute_command(
            command=command,
            input_data=input_data,
            cwd=cwd,
            timeout=timeout,
            env=env,
            stderr_to_stdout=stderr_to_stdout,
            discard_stdout=discard_stdout,
            discard_stderr=discard_stderr,
            skip_logging=skip_logging,
            expected_return_codes=expected_return_codes,
            shell=shell,
            custom_exception=custom_exception,
            get_pty=get_pty,
        )

    def start_process(
        self,
        command: str,
        *,
        cwd: str = None,
        env: dict = None,
        stderr_to_stdout: bool = False,
        discard_stdout: bool = False,
        discard_stderr: bool = False,
        cpu_affinity: Optional[Union[int, List[int], str]] = None,
        shell: bool = False,
        enable_input: bool = False,
        log_file: bool = False,
        output_file: Optional[str] = None,
    ) -> "SSHProcess":
        """
        Start process.

        :param command: Command to execute, with all necessary arguments
        :param cwd: Directory to start program execution in
        :param env: Environment to execute the program in
        :param stderr_to_stdout: Redirect stderr to stdout, ignored if discard_stderr is set to True
        :param discard_stdout: Don't capture stdout stream
        :param discard_stderr: Don't capture stderr stream
        :param cpu_affinity: Processor numbers the process will run on in a format chosen by the user. Not used for SSH.
        :param shell: Start process in a shell. Allows usage of shell constructions like pipes etc.
        :param enable_input: Whether or not allow writing to process' stdin
        :param log_file: Switch to enable redirection to generated by method log file. Not used for ssh.
        :param output_file: Path to file as redirection of command output, interchangeably with log_file param.
            Not used for ssh.
        :return: Running process, RemoteProcess object
        :raises SSHTunnelException: when failed to reconnect inactive SSH tunnel
        """
        self._reconnect_tunnel_if_not_available()
        return super().start_process(
            command=command,
            cwd=cwd,
            env=env,
            stderr_to_stdout=stderr_to_stdout,
            discard_stdout=discard_stdout,
            discard_stderr=discard_stderr,
            shell=shell,
            enable_input=enable_input,
        )

    def start_processes(
        self,
        command: str,
        *,
        cwd: str = None,
        env: dict = None,
        stderr_to_stdout: bool = False,
        discard_stdout: bool = False,
        discard_stderr: bool = False,
        shell: bool = False,
        enable_input: bool = False,
        log_file: bool = False,
        output_file: Optional[str] = None,
    ) -> List["SSHProcess"]:
        """
        Start processes.

        Use start_processes if you need to execute cmd which will trigger more than one process and
        you want to receive list of new processes.

        :param command: Command to execute, with all necessary arguments
        :param cwd: Directory to start program execution in
        :param env: Environment to execute the program in
        :param stderr_to_stdout: Redirect stderr to stdout, ignored if discard_stderr is set to True
        :param discard_stdout: Don't capture stdout stream
        :param discard_stderr: Don't capture stderr stream
        :param shell: Start process in a shell. Allows usage of shell constructions like pipes etc.
        :param enable_input: Whether or not allow writing to process' stdin
        :param log_file: Switch to enable redirection to generated by method log file
        :param output_file: Path to file as redirection of command output, interchangeably with log_file param.
        :return: List of running processes, RemoteProcess objects
        :raises SSHTunnelException: when failed to reconnect inactive SSH tunnel
        """
        self._reconnect_tunnel_if_not_available()
        return super().start_processes(
            command=command,
            cwd=cwd,
            env=env,
            stderr_to_stdout=stderr_to_stdout,
            discard_stdout=discard_stdout,
            discard_stderr=discard_stderr,
            shell=shell,
            enable_input=enable_input,
        )

    def _reconnect(self) -> None:
        """
        Reconnect to SSHClient.

        :raises SSHReconnectException: in case of fail in establishing connection
        :raises SSHTunnelException: when failed to reconnect inactive SSH tunnel
        """
        self._reconnect_tunnel_if_not_available()
        super()._reconnect()

    def download_file_from_url(
        self,
        url: str,
        destination_file: "PurePath",
        username: str | None = None,
        password: str | None = None,
        headers: dict[str, str] | None = None,
        hide_credentials: bool = True,
    ) -> None:
        """
        Download file from url.

        Note: For authentication use either credentials (username & password) or headers - do not combine them.

        :param url: URL of file
        :param destination_file: Path for destination of file
        :param username: Optional username
        :param password: Optional password
        :param headers: Optional headers
        :param hide_credentials: Flag to hide credentials in temporary environment variables
        :raises: UnavailableServerException, if server is not available
        :raises: TransferFileError, on failure
        """
        raise NotImplementedError("Not implemented for TunneledSSHConnection")
