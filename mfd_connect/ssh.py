# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for SSHConnection class."""

import codecs
import logging
import random
import sys
from shlex import quote
import time
from subprocess import CalledProcessError
from typing import Iterable, Type, Optional, Dict, Tuple, List, Union, TYPE_CHECKING

from mfd_common_libs import TimeoutCounter, add_logging_level, log_levels
from mfd_typing.cpu_values import CPUArchitecture
from mfd_typing.os_values import OSBitness, OSType, OSName
from netaddr import IPAddress
from paramiko import SSHException, SSHClient, WarningPolicy, AuthenticationException
from paramiko.client import MissingHostKeyPolicy, AutoAddPolicy

from .base import AsyncConnection, ConnectionCompletedProcess
from .exceptions import (
    ModuleFrameworkDesignError,
    ConnectionCalledProcessError,
    OsNotSupported,
    CPUArchitectureNotSupported,
)
from .exceptions import SSHReconnectException, RemoteProcessTimeoutExpired
from .pathlib.path import CustomPath, custom_path_factory
from .process.ssh.base import SSHProcess
from .process.ssh.esxi import ESXiSSHProcess
from .process.ssh.posix import PosixSSHProcess
from .process.ssh.windows import WindowsSSHProcess
from .util.decorators import conditional_cache, clear_system_data_cache

if TYPE_CHECKING:
    from paramiko.channel import Channel, ChannelFile, ChannelStdinFile, ChannelStderrFile
    from pathlib import Path, PurePath
    from pydantic import BaseModel  # from pytest_mfd_config.models.topology import ConnectionModel

logger = logging.getLogger(__name__)
add_logging_level(level_name="MODULE_DEBUG", level_value=log_levels.MODULE_DEBUG)
add_logging_level(level_name="CMD", level_value=log_levels.CMD)
add_logging_level(level_name="OUT", level_value=log_levels.OUT)
# set paramiko debug prints into WARNING level because of visible paramiko logs with mfd logs
logging.getLogger("paramiko").setLevel(logging.WARNING)
logging.getLogger("paramiko.transport").setLevel(logging.CRITICAL)


class SSHConnection(AsyncConnection):
    """
    Implementation of SSHConnection type for remote usage.

    Operations will be performed on machine via SSH connection.

    Usage example:
    >>> conn = SSHConnection()
    >>> res = conn.execute_command("echo something", shell=True)
    test
    """

    _process_classes = [WindowsSSHProcess, PosixSSHProcess, ESXiSSHProcess]

    def __init__(
        self,
        ip: str,
        *args,
        port: int = 22,
        username: str,
        password: Optional[str],
        key_path: "list[str | Path] | str | Path | None" = None,
        skip_key_verification: bool = False,
        model: "BaseModel | None" = None,
        default_timeout: int | None = None,
        cache_system_data: bool = True,
        **kwargs,
    ) -> None:
        """
        Initialise SSHConnection.

        If a private key requires a password to unlock it,
        and a password is passed in, that password will be used to attempt to unlock the key.

        :param ip: IP address of SSH server
        :param port: port of SSH server
        :param username: Username for connection
        :param password: Password for connection, optional for using key, pass None for no password
        :param key_path: the filename, or list of filenames, of optional private key(s)
                         and/or certs to try for authentication, supported types: RSAKey, DSSKey, ECDSAKey, Ed25519Key
        :param skip_key_verification: To skip checking of host's key, equivalent of StrictHostKeyChecking=no
        :param model: pydantic model of connection
        :param default_timeout: Timeout value for executing timeout for entire class.
        :param cache_system_data: Flag to cache system data like self._os_type, OS name, OS bitness and CPU architecture
        """
        super().__init__(ip, model, default_timeout, cache_system_data)
        self.__use_sudo = False
        self._ip = IPAddress(ip)
        self._connection = SSHClient()
        self._connection_details = {
            "hostname": str(self._ip),
            "port": port,
            "username": username,
        }
        if password is not None:
            self._connection_details["password"] = password

        if key_path:
            self._connection_details["key_filename"] = key_path

        if key_path:
            policy = AutoAddPolicy()
        elif skip_key_verification:
            policy = MissingHostKeyPolicy()
            self._connection_details["look_for_keys"] = False
        else:
            policy = WarningPolicy()
            self._connection.load_system_host_keys()

        self._connection.set_missing_host_key_policy(policy)
        try:
            self._connect()
        except SSHException as e:
            raise ModuleFrameworkDesignError("Found problem with connection") from e

        self.log_connected_host_info()

    def __str__(self):
        return "ssh"

    def _connect(self) -> None:
        """
        Connect via ssh.

        Set correct process class
        :raises OsNotSupported: if os not found in available process classes
        """
        self._connection.connect(**self._connection_details, compress=True)
        key_auth = str(self._connection.get_transport())
        if "awaiting auth" in key_auth:
            logger.log(level=log_levels.MODULE_DEBUG, msg="SSH server requested additional authentication")
            (self._connection.get_transport()).auth_interactive_dumb(self._connection_details["username"])

        os_name = self.get_os_name()
        self._os_type = self.get_os_type()
        for process_class in self._process_classes:
            if os_name in process_class._os_name:
                self._process_class = process_class
                break
        else:
            raise OsNotSupported(f"Not implemented process for read os name {os_name}")

    def disconnect(self) -> None:
        """Close connection."""
        self._connection.close()

    @clear_system_data_cache
    def _reconnect(self) -> None:
        """
        Reconnect to SSHClient.

        :raises SSHReconnectException: in case of fail in establishing connection
        """
        logger.log(level=log_levels.MODULE_DEBUG, msg="Connection lost, reconnecting")
        self._connect()
        if not self._connection.get_transport().is_active():
            logger.log(level=log_levels.MODULE_DEBUG, msg="Connection lost.")
            raise SSHReconnectException("Cannot reconnect to host!")
        logger.log(level=log_levels.MODULE_DEBUG, msg="Reconnection successful.")

    @property
    def _remote(self) -> "SSHClient":
        """
        Renew connection in case of drop.

        If connection is not active, reconnect method is called, and SSHClient is returned.
        """
        # need to check if transport is available (after disconnect it isn't)
        if not self._connection.get_transport() or not self._connection.get_transport().is_active():
            self._reconnect()
        return self._connection

    @conditional_cache
    def get_os_type(self) -> OSType:
        """Get type of client os."""
        windows_check_command = (
            "Get-WmiObject -Class Win32_OperatingSystem | Select-Object -Property Caption, OSArchitecture"
        )
        command = windows_check_command.replace('"', '\\"')
        command = f'powershell.exe -OutPutFormat Text -nologo -noninteractive "{command}"'
        result = self.execute_command(command, shell=False, expected_return_codes=[0, 1, 127])
        if result.return_code:
            unix_check_command = "uname -a"  # get architecture and os name
            result = self.execute_command(unix_check_command, expected_return_codes=[0, 127])
            if result.return_code:
                logger.log(level=log_levels.MODULE_DEBUG, msg=f"Debug data of os_type method: {result}")
                raise OsNotSupported("Client OS not supported")
            return OSType.POSIX
        else:
            return OSType.WINDOWS

    @conditional_cache
    def get_os_name(self) -> OSName:
        """Get name of client os."""
        windows_check_command = (
            "Get-WmiObject -Class Win32_OperatingSystem | Select-Object -Property Caption, OSArchitecture"
        )
        command = windows_check_command.replace('"', '\\"')
        command = f'powershell.exe -OutPutFormat Text -nologo -noninteractive "{command}"'
        result = self.execute_command(command, shell=False, expected_return_codes=[0, 1, 127])
        if result.return_code:
            unix_check_command = "uname -s"
            # get kernel name - consistent with platform.system, which read first part of uname
            result = self.execute_command(unix_check_command, expected_return_codes=[0, 127])
            for os in OSName:
                if os.value in result.stdout:
                    return os
            logger.log(level=log_levels.MODULE_DEBUG, msg=f"Debug data of os_name method: {result}")
            raise OsNotSupported("Client OS not supported")
        else:
            return OSName.WINDOWS

    @conditional_cache
    def _get_os_bitness_arch(self, os_type: OSType) -> "ConnectionCompletedProcess":
        """
        Get OS/CPU machine.

        :param os_type: Type of OS
        :return: ConnectionCompletedProcess object on success
        :raises OsNotSupported: If command execution cannot be finished correctly
        """
        if os_type == OSType.WINDOWS:
            windows_check_command = (
                "Get-WmiObject -Class Win32_OperatingSystem | Select-Object -Property OSArchitecture"
            )
            command = windows_check_command.replace('"', '\\"')
            command = f'powershell.exe -OutPutFormat Text -nologo -noninteractive "{command}"'
            result = self.execute_command(command, shell=False, expected_return_codes=[0, 1, 127])
        elif os_type == OSType.POSIX:
            unix_check_command = "uname -m"  # get machine info
            result = self.execute_command(unix_check_command, expected_return_codes=[0, 127])
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Debug data of the method: {result.stdout}")
        return result

    @conditional_cache
    def get_os_bitness(self) -> OSBitness:
        """Get bitness of Host OS."""
        if self._os_type in (OSType.WINDOWS, OSType.POSIX):
            result = self._get_os_bitness_arch(self._os_type)
        else:  # must be EFI shell
            raise OsNotSupported("Cannot determine OS Bitness for EFI Shell.")
        if "64" in result.stdout:
            return OSBitness.OS_64BIT
        elif "32" in result.stdout or "86" in result.stdout or "armv7l" in result.stdout or "arm" in result.stdout:
            return OSBitness.OS_32BIT
        else:
            raise OsNotSupported(f"Cannot determine OS Bitness for Host: {self._ip}")

    @conditional_cache
    def get_cpu_architecture(self) -> CPUArchitecture:
        """Get CPU Architecture."""
        if self._os_type in (OSType.WINDOWS, OSType.POSIX):
            result = self._get_os_bitness_arch(self._os_type)
        else:  # must be EFI shell
            raise OsNotSupported("Cannot determine CPU Architecture for EFI Shell.")
        if "aarch64" in result.stdout:
            return CPUArchitecture.ARM64
        elif "64" in result.stdout:
            return CPUArchitecture.X86_64
        elif "armv7l" in result.stdout or "arm" in result.stdout:
            return CPUArchitecture.ARM
        elif "32" in result.stdout or "86" in result.stdout:
            return CPUArchitecture.X86
        else:
            raise CPUArchitectureNotSupported(f"Cannot determine CPU Architecture for Host: {self._ip}")

    def _exec_command(
        self,
        command: str,
        input_data: str,
        bufsize: int = -1,
        timeout: int = None,
        get_pty: bool = False,
        environment: Dict = None,
        stderr_to_stdout: bool = False,
        discard_stdout: bool = False,
        discard_stderr: bool = False,
        cwd: str = "",
    ) -> Tuple:
        """
        Injected some arguments for Paramiko exec_command.

        Execute a command on the SSH server.  A new `.Channel` is opened and
        the requested command is executed.  The command's input and output
        streams are returned as Python ``file``-like objects representing
        stdin, stdout, and stderr.

        :param str command: the command to execute
        :param int bufsize:
            interpreted the same way as by the built-in ``file()`` function in
            Python
        :param int timeout:
            set command's channel timeout. See `.Channel.settimeout`
        :param bool get_pty:
            Request a pseudo-terminal from the server (default ``False``).
            See `.Channel.get_pty`
        :param dict environment:
            a dict of shell environment variables, to be merged into the
            default environment that the remote command executes within.

            .. warning::
                Servers may silently reject some environment variables; see the
                warning in `.Channel.set_environment_variable` for details.
        :param stderr_to_stdout: Redirect stderr to stdout, ignored if discard_stderr is set to True
        :param discard_stdout: Don't capture stdout stream
        :param discard_stderr: Don't capture stderr stream
        :param input_data: Data to pass to program on the standard input
        :return:
            the stdin, stdout, stderr and return code of the executing command, as a
            4-tuple

        :raises: `.SSHException` -- if the server fails to execute the command
        """
        stdin, stdout, stderr, random_name, chan = self._start_process(
            command=command,
            enable_input=bool(input_data),
            bufsize=bufsize,
            cwd=cwd,
            timeout=timeout,
            get_pty=get_pty,
            environment=environment,
            stderr_to_stdout=stderr_to_stdout,
            discard_stdout=discard_stdout,
            discard_stderr=discard_stderr,
        )

        if input_data:
            stdin.write(input_data)

        if timeout is not None:
            self._terminate_command_after_timeout(command, timeout, chan, stdin, stdout, stderr, random_name)

        return stdin, stdout, stderr, chan.recv_exit_status()

    def _add_discard_commands(self, command: str, discard_stdout: bool, discard_stderr: bool) -> str:
        """
        Modify command's suffix to discard the output on the shell level.

        :param command: Command to be modified
        :param discard_stdout: Flag for discarding stdout stream
        :param discard_stderr: Flag for discarding stderr stream
        :return: Modified command.
        """
        if not discard_stdout and not discard_stderr:
            return command

        discard_stdout_command = {OSType.WINDOWS: ">nul", OSType.POSIX: ">/dev/null"}
        discard_stderr_command = {OSType.WINDOWS: "2>nul", OSType.POSIX: "2>/dev/null"}
        discard_both_command = {OSType.WINDOWS: ">nul 2>&1", OSType.POSIX: ">/dev/null 2>&1"}

        # spaces on posix required
        posix_closing_bracket = f"{';' if not command.rstrip().endswith('&') else ''} }}"
        grouping_brackets = {OSType.WINDOWS: ("(", ")"), OSType.POSIX: ("{ ", posix_closing_bracket)}

        opening_bracket, closing_bracket = grouping_brackets.get(self._os_type, ("", ""))
        command = f"{opening_bracket}{command}{closing_bracket}"

        if discard_stdout and discard_stderr:
            command = f"{command} {discard_both_command.get(self._os_type, '')}"
        elif discard_stdout:
            command = f"{command} {discard_stdout_command.get(self._os_type, '')}"
        elif discard_stderr:
            command = f"{command} {discard_stderr_command.get(self._os_type, '')}"

        return command

    def _terminate_command_after_timeout(
        self,
        command: str,
        timeout: int,
        chan: "Channel",
        stdin: Optional["ChannelStdinFile"],
        stdout: Optional["ChannelFile"],
        stderr: Optional["ChannelStderrFile"],
        random_name: float | str,
    ) -> None:
        """
        Terminate command execution if the specified timeout expires.

        :param command: Command being executed
        :param timeout: Timeout [sec] for the command to be completed
        :param chan: Paramiko channel for command to be executed
        :param stdin: Stdin file-like object for the command being executed
        :param stdout: Stdout file-like object for the command being executed
        :param stderr: Stderr file-like object for the command being executed
        :param random_name: Float random number which will help us find our process in the system
        :raises RemoteProcessTimeoutExpired: If command is forcefully terminated due to timeout expired
        """
        proc_timeout = TimeoutCounter(timeout)
        while not proc_timeout:
            if chan.exit_status_ready():
                break
            time.sleep(0.1)
        else:
            chan.close()
            if stdout:
                output = stdout.read()
                output = codecs.decode(output, encoding="utf-8", errors="backslashreplace")
                logger.log(level=logging.DEBUG, msg=f"Output captured before command termination: {output}")
            process = self._process_class(
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                unique_name=random_name,
                connection=self,
                channel=chan,
            )
            if process.running:
                process.kill()
            raise RemoteProcessTimeoutExpired(
                f"Timeout of {timeout} seconds expired during execution of '{command}' command"
            )

    def handle_execution_reconnect(
        self,
        command: str,
        *,
        input_data: str | None = None,
        cwd: str | None = None,
        timeout: int | None = None,
        env: dict | None = None,
        stderr_to_stdout: bool = False,
        discard_stdout: bool = False,
        discard_stderr: bool = False,
        custom_exception: Type[CalledProcessError] | None = None,
        reconnect_attempts: int = 5,
        attempt_delay: int = 6,
    ) -> None:
        """
        Try to reconnect to and make attempts to execute test command.

        :param command: Command to execute, with all necessary arguments
        :param input_data: Data to pass to program on the standard input
        :param cwd: Directory to start program execution in
        :param timeout: Program execution timeout, in seconds
        :param env: Environment to execute the program in
        :param stderr_to_stdout: Redirect stderr to stdout, ignored if discard_stderr is set to True
        :param discard_stdout: Don't capture stdout stream
        :param discard_stderr: Don't capture stderr stream
        :param custom_exception: Enable us to raise our exception if program exits with an unexpected return code.
        :param reconnect_attempts: Number of attempts to reconnect to the host if connection is lost.
        :param attempt_delay: Delay between reconnection attempts.
        custom_exception must inherit from CalledProcessError to use its fields like returncode, cmd, output, stderr

        :raises TimeoutExpired: if program doesn't conclude before timeout is reached
        :raises ValueError: if command has invalid characters inside
        :raises ConnectionCalledProcessError: if program exits with an unexpected return code
        """
        while reconnect_attempts > 0:
            reconnect_success = False
            try:
                self._reconnect()
                reconnect_success = True
            except SSHReconnectException as rec_err:
                logger.log(level=log_levels.MODULE_DEBUG, msg=f"Connection drop while trying to reconnect: {rec_err}")

            if not reconnect_success:
                time.sleep(attempt_delay)
                reconnect_attempts -= 1
                continue

            try:
                _stdin_pipe, _stdout_pipe, _stderr_pipe, rc = self._exec_command(
                    "hostname",
                    input_data=input_data,
                    environment=env,
                    cwd=cwd,
                    timeout=timeout,
                    stderr_to_stdout=stderr_to_stdout,
                    discard_stdout=discard_stdout,
                    discard_stderr=discard_stderr,
                    get_pty=False,
                )
                if rc == 0:
                    logger.log(level=log_levels.MODULE_DEBUG, msg="Successfully executed test command after reconnect")
                    return
            except Exception as e:
                reconnect_attempts -= 1
                logger.log(
                    level=log_levels.MODULE_DEBUG,
                    msg=f"Connection drop after reconnect when executing test command: {e}",
                )
        else:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg=f"Unable to execute command '{command}' after multiple attempts to reconnect",
            )
            if custom_exception:
                raise custom_exception(returncode=-1, cmd=command, output="", stderr="")
            raise ConnectionCalledProcessError(returncode=-1, cmd=command, output="", stderr="")

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
        reconnect_attempts: int = 5,
        attempt_delay: int = 6,
        get_pty: bool = False,
    ) -> "ConnectionCompletedProcess":
        """
        Run program and wait for its completion.

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
        :param reconnect_attempts: Number of attempts to reconnect to the host if connection is lost.
        :param attempt_delay: Delay between reconnection attempts.
        :param get_pty: Request a pseudo-terminal from the server.
        custom_exception must inherit from CalledProcessError to use its fields like returncode, cmd, output, stderr

        :return: ConnectionCompletedProcess object
        :raises TimeoutExpired: if program doesn't conclude before timeout is reached
        :raises ValueError: if command has invalid characters inside
        :raises ConnectionCalledProcessError: if program exits with an unexpected return code
        """
        timeout = self.default_timeout if timeout is None else timeout
        super().execute_command(
            command,
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
        )

        if get_pty:
            logger.log(
                level=log_levels.MFD_INFO,
                msg="[Warning] A pseudo-terminal was requested, "
                "but please be aware that this is not recommended and may lead to unexpected behavior.",
            )

        self._verify_command_correctness(command)
        command = self._adjust_command(command)

        success_execution = False
        try:
            logger.log(level=log_levels.CMD, msg=f"Executing >{self._ip}> '{command}', cwd: {cwd}")

            stdin_pipe, stdout_pipe, stderr_pipe, returncode = self._exec_command(
                command,
                input_data=input_data,
                environment=env,
                cwd=cwd,
                timeout=timeout,
                stderr_to_stdout=stderr_to_stdout,
                discard_stdout=discard_stdout,
                discard_stderr=discard_stderr,
                get_pty=get_pty,
            )
            success_execution = True
        except Exception as e:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg=f"Connection drop: {e}, will attempt to reconnect {reconnect_attempts} times.",
            )

        if not success_execution:
            self.handle_execution_reconnect(
                command,
                input_data=input_data,
                cwd=cwd,
                timeout=timeout,
                env=env,
                stderr_to_stdout=stderr_to_stdout,
                discard_stdout=discard_stdout,
                discard_stderr=discard_stderr,
                custom_exception=custom_exception,
                reconnect_attempts=reconnect_attempts,
                attempt_delay=attempt_delay,
            )

            logger.log(level=log_levels.CMD, msg=f"Executing >{self._ip}> '{command}' after reconnect, cwd: {cwd}")
            stdin_pipe, stdout_pipe, stderr_pipe, returncode = self._exec_command(
                command,
                input_data=input_data,
                environment=env,
                cwd=cwd,
                timeout=timeout,
                stderr_to_stdout=stderr_to_stdout,
                discard_stdout=discard_stdout,
                discard_stderr=discard_stderr,
                get_pty=get_pty,
            )

        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Finished executing '{command}' ")

        stdout, stderr = None, None

        if stdout_pipe:
            stdout_pipe_output = stdout_pipe.read()
            stdout = codecs.decode(stdout_pipe_output, encoding="utf-8", errors="backslashreplace")
            if stdout and not skip_logging:
                logger.log(level=log_levels.OUT, msg=f"output:\nstdout>>\n{stdout}")

        if stderr_pipe:
            stderr_pipe_output = stderr_pipe.read()
            stderr = codecs.decode(stderr_pipe_output, encoding="utf-8", errors="backslashreplace")
            if stderr and not skip_logging:
                logger.log(level=log_levels.OUT, msg=f"stderr>>\n{stderr}")

        if custom_exception and not expected_return_codes:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg=f"Return codes are ignored, passed exception: {custom_exception} will be not raised.",
            )

        if not expected_return_codes or returncode in expected_return_codes:
            completed_process = ConnectionCompletedProcess(
                args=command,
                stdout=stdout,
                stderr=stderr,
                stdout_bytes=locals().get("stdout_pipe_output", b""),
                stderr_bytes=locals().get("stderr_pipe_output", b""),
                return_code=returncode,
            )
            return completed_process
        else:
            if custom_exception:
                raise custom_exception(returncode=returncode, cmd=command, output=stdout, stderr=stderr)
            raise ConnectionCalledProcessError(returncode=returncode, cmd=command, output=stdout, stderr=stderr)

    def _start_process(
        self,
        command: str,
        enable_input: bool = False,
        bufsize: int = -1,
        cwd: str = None,
        timeout: int = None,
        get_pty: bool = False,
        environment: Dict = None,
        stderr_to_stdout: bool = False,
        discard_stdout: bool = False,
        discard_stderr: bool = False,
        log_path: "Path | None" = None,
    ) -> Tuple["ChannelStdinFile", "ChannelFile", "ChannelStderrFile", float, "Channel"]:
        """
        Injected some arguments for Paramiko exec_command.

        Execute a command on the SSH server.  A new `.Channel` is opened and
        the requested command is executed.  The command's input and output
        streams are returned as Python ``file``-like objects representing
        stdin, stdout, and stderr.

        :param str command: the command to execute
        :param enable_input: flag for enabling input stream
        :param int bufsize:
            interpreted the same way as by the built-in ``file()`` function in
            Python
        :param int timeout:
            set command's channel timeout. See `.Channel.settimeout`
        :param bool get_pty:
            Request a pseudo-terminal from the server (default ``False``).
            See `.Channel.get_pty`
        :param dict environment:
            a dict of shell environment variables, to be merged into the
            default environment that the remote command executes within.

            .. warning::
                Servers may silently reject some environment variables; see the
                warning in `.Channel.set_environment_variable` for details.
        :param stderr_to_stdout: Redirect stderr to stdout, ignored if discard_stderr is set to True
        :param discard_stdout: Don't capture stdout stream
        :param discard_stderr: Don't capture stderr stream
        :return:
            the stdin, stdout, stderr, generated name of the executing command and channel, as a
            5-tuple

        :raises: `.SSHException` -- if the server fails to execute the command
        """
        chan = self._remote.get_transport().open_session(timeout=timeout)

        if get_pty:
            chan.get_pty()

        chan.settimeout(timeout)

        if environment:
            chan.update_environment(environment)

        command = self._add_discard_commands(command, discard_stdout, discard_stderr)
        command = f"{command} > {quote(str(log_path))}" if log_path else command

        random_name = random.random()
        if not hasattr(self.__class__, "_os_type") or self._cached_os_type is None:
            # We're here before connection fully set up,
            # most likely this is execute_command checking OS (__init__ -> _connect), no need to use cmd and timeout
            pass
        elif self._os_type == OSType.WINDOWS:
            if cwd:
                command = f"cd {cwd} && {command}"
            command = f"title {random_name} && {command}"
        else:
            if cwd:
                command = f"cd {cwd}; {command}"

            # When triggered in bg - & operator is chaining commands, no need for && addition
            chain_operator = " &&" if command.rstrip()[-1] != "&" else ""
            random_addition = f"{chain_operator} true {random_name}"
            command = f"{command}{random_addition}"

        chan.exec_command(command)

        stdin = chan.makefile_stdin("wb", bufsize) if enable_input else None
        stdout = chan.makefile("r", bufsize) if not discard_stdout else None
        stderr = chan.makefile_stderr("r", bufsize) if not discard_stderr else None

        if stderr_to_stdout:
            chan.set_combine_stderr(combine=True)

        return stdin, stdout, stderr, random_name, chan

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
        get_pty: bool = False,
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
        :param log_file: Switch to enable redirection to generated by method log file
        :param output_file: Path to file as redirection of command output, interchangeably with log_file param.
        :param get_pty:
            Request a pseudo-terminal from the server (default ``False``). Enables passing key codes to process.
            See `.Channel.get_pty`
        :return: Running process, RemoteProcess object
        """
        super().start_process(
            command,
            cwd=cwd,
            env=env,
            stderr_to_stdout=stderr_to_stdout,
            discard_stdout=discard_stdout,
            discard_stderr=discard_stderr,
            shell=shell,
            enable_input=enable_input,
        )
        self._verify_command_correctness(command)

        command = self._adjust_command(command)

        logger.log(level=log_levels.CMD, msg=f"Starting process >{self._ip}> '{command}', cwd: {cwd}")
        if cpu_affinity is not None:
            logger.log(level=log_levels.MODULE_DEBUG, msg="Used cpu affinity, but it's not functional for SSH.")

        log_path = self._prepare_log_file(command, log_file, output_file)
        if log_path is not None:
            log_file = True

        _stdin, _stdout, _stderr, _unique_name_of_process, _ = self._start_process(
            command,
            environment=env,
            cwd=cwd,
            stderr_to_stdout=stderr_to_stdout,
            discard_stdout=discard_stdout,
            discard_stderr=discard_stderr,
            enable_input=enable_input,
            get_pty=get_pty,
            log_path=log_path,
        )

        return self._process_class(
            stdin=_stdin,
            stdout=_stdout,
            stderr=_stderr,
            unique_name=_unique_name_of_process,
            connection=self,
            log_path=log_path,
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
        cpu_affinity: Optional[Union[int, List[int], str]] = None,
        shell: bool = False,
        enable_input: bool = False,
        get_pty: bool = False,
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
        :param cpu_affinity: Processor numbers the process will run on in a format chosen by the user.
                Not used for SSH
        :param shell: Start process in a shell. Allows usage of shell constructions like pipes etc.
        :param enable_input: Whether or not allow writing to process' stdin
        :param output_file: Path to file as redirection of command output, interchangeably with log_file param.
            Not used for SSH
        :param log_file: Switch to enable redirection to generated by method log file. Not used for SSH
        :param get_pty:
            Request a pseudo-terminal from the server (default ``False``). Enables passing key codes to process.
            See `.Channel.get_pty`
        :param log_file: Switch to enable redirection to generated by method log file
        :param output_file: Path to file as redirection of command output, interchangeably with log_file param.
        :return: List of running processes, RemoteProcess objects
        """
        command = self._adjust_command(command)

        logger.log(level=log_levels.CMD, msg=f"Starting processes >{self._ip}> '{command}', cwd: {cwd}")
        if cpu_affinity is not None:
            logger.log(level=log_levels.MODULE_DEBUG, msg="Used cpu affinity, but it's not functional for SSH.")
        if output_file is not None:
            logger.log(level=log_levels.MODULE_DEBUG, msg="Used output_file, but it's not functional for SSH.")
        if log_file is not None:
            logger.log(level=log_levels.MODULE_DEBUG, msg="Used log_file, but it's not functional for SSH.")
        _stdin, _stdout, _stderr, _unique_name_of_process, _ = self._start_process(
            command,
            environment=env,
            cwd=cwd,
            stderr_to_stdout=stderr_to_stdout,
            discard_stdout=discard_stdout,
            discard_stderr=discard_stderr,
            enable_input=enable_input,
            get_pty=get_pty,
        )

        return [
            self._process_class(
                stdin=_stdin,
                stdout=_stdout,
                stderr=_stderr,
                unique_name=_unique_name_of_process,
                pid=pid,
                connection=self,
            )
            for pid in self._process_class._find_pids(self, _unique_name_of_process)
        ]

    def _adjust_command(self, command: str) -> str:
        """
        Adjust command.

        :param command: command to adjust
        :return: command
        """
        if self.__use_sudo:
            return f'sudo sh -c "{command}"' if "echo" in command else f"sudo {command}"
        return command

    def start_process_by_start_tool(
        self,
        command: str,
        *,
        cwd: str = None,
        discard_stdout: bool = False,
        cpu_affinity: Optional[Union[int, List[int], str]] = None,  # noqa
        output_file: Optional[str] = None,  # noqa
        numa_node: Optional[int] = None,  # noqa
        **kwargs,
    ) -> "SSHProcess":
        """
        Start process using start command on Windows.

        :param command: Command to execute, with all necessary arguments
        :param cwd: Directory to start program execution in
        :param discard_stdout: Don't capture stdout stream
        :return: Running process, SSHProcess object
        """
        logger.log(
            level=log_levels.MODULE_DEBUG,
            msg="start_process_by_start_tool for SSH is limited to just starting process",
        )
        return self.start_process(command=command, cwd=cwd, discard_stdout=discard_stdout, **kwargs)

    def send_command_and_disconnect_platform(self, command: str, timeout: int = 5) -> None:
        """
        Send command to host and disconnect.

        Linux:
        - ConnectionCalledProcessError will be raised when dropping connection via SIGHUP
        - ConnectionResetError will be raised when connection is reset by peer
        - RemoteProcessTimeoutExpired will be raised when command is not finished before timeout
        Windows:
        - No issues found

        :param command: Command to send
        :param timeout: Time to wait after command
        """
        sleep_time = 10
        try:
            self.execute_command(command, discard_stdout=True, discard_stderr=True)
        except RemoteProcessTimeoutExpired as e:
            logger.log(level=log_levels.MODULE_DEBUG, msg=f"Timeout expired: {e}")
        except ConnectionResetError as e:
            logger.log(level=log_levels.MODULE_DEBUG, msg=f"Connection reset caught: {e}")
        except ConnectionCalledProcessError as e:
            accepted_messages = ["SIGHUP", "CTRL_BREAK_EVENT"]
            if any(msg in str(e) for msg in accepted_messages):
                # ConnectionCalledProcessError: Command 'sudo shutdown -r now' died with (controller OS depended)
                # <Signals.SIGHUP> (on linux controller)
                # <Signals.CTRL_BREAK_EVENT>(on windows controller)
                logger.log(level=log_levels.MODULE_DEBUG, msg="Dropped connection via SSH, expected")
            else:
                raise e
        finally:
            self.disconnect()
        time.sleep(sleep_time)

    def execute_powershell(
        self,
        command: str,
        *,
        input_data: Optional[str] = None,
        cwd: Optional[str] = None,
        timeout: int = None,
        env: Optional[dict] = None,
        stderr_to_stdout: bool = False,
        discard_stdout: bool = False,
        discard_stderr: bool = False,
        skip_logging: bool = False,
        expected_return_codes: Optional[Iterable] = frozenset({0}),
        shell: bool = False,
        custom_exception: Type[CalledProcessError] = None,
    ) -> "ConnectionCompletedProcess":
        """
        Run program and wait for it is completion.

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
        custom_exception must inherit from CalledProcessError to use its fields like returncode, cmd, output, stderr

        :return: ConnectionCompletedProcess object
        :raises TimeoutExpired: if program doesn't conclude before timeout is reached
        :raises ConnectionCalledProcessError: if program exits with an unexpected return code
        """
        raise NotImplementedError("Not implemented in SSH")

    def restart_platform(self) -> None:
        """
        Reboot host.

        Internal dict of reboot platform commands
        """
        posix_command = self._adjust_command("shutdown -r now")
        restart_commands = {OSType.WINDOWS: "shutdown /r /f -t 0", OSType.POSIX: posix_command}
        self.send_command_and_disconnect_platform(restart_commands[self._os_type])

    def shutdown_platform(self) -> None:
        """
        Shutdown host.

        Internal dict of shutdown platform commands
        """
        posix_command = self._adjust_command("shutdown -h now")
        shutdown_commands = {OSType.WINDOWS: "shutdown /s /f -t 0", OSType.POSIX: posix_command}
        self.send_command_and_disconnect_platform(shutdown_commands[self._os_type])

    def wait_for_host(self, timeout: int = 60) -> None:
        """
        Wait for host availability.

        Trying connect via ssh

        :param timeout: Time to check until fail
        :raises TimeoutError: when timeout is expired
        """
        sleep_before_retry = 10
        timeout_counter = TimeoutCounter(timeout)
        while not timeout_counter:
            try:
                logger.log(level=log_levels.MODULE_DEBUG, msg="Reconnecting...")
                self._connect()
                if self._connection.get_transport().is_active():
                    return
            except (OSError, AuthenticationException):
                # OS not started, or 'system is booting up. Unprivileged users are not permitted to log in yet'
                logger.log(
                    level=log_levels.MODULE_DEBUG,
                    msg=f"Connection does not established, waiting {sleep_before_retry} seconds and trying again",
                )
                time.sleep(sleep_before_retry)
        else:
            raise TimeoutError(f"Host does not wake up in {timeout} seconds")

    def path(self, *args, **kwargs) -> CustomPath:
        """Path represents a filesystem path."""
        if sys.version_info >= (3, 12):
            kwargs["owner"] = self
            return custom_path_factory(*args, **kwargs)

        return CustomPath(*args, owner=self, **kwargs)

    def enable_sudo(self) -> None:
        """
        Enable sudo for command execution.

        :raises OsNotSupported: when os_type is different from posix
        """
        if self._os_type != OSType.POSIX:
            raise OsNotSupported(f"{self._os_type} is not supported for enabling sudo!")

        logger.log(level=log_levels.MODULE_DEBUG, msg="Enabled sudo for command execution.")
        self.__use_sudo = True

    def disable_sudo(self) -> None:
        """Disable sudo for command execution."""
        logger.log(level=log_levels.MODULE_DEBUG, msg="Disabled sudo for command execution.")
        self.__use_sudo = False

    def _verify_command_correctness(self, command: str) -> None:
        """
        Check if command doesn't contain not allowed characters on the end of the command.

        They are not allowed because conflicts with `&& true <sha>` addition for pid searching.

        :param command: Command to check
        :raises ValueError: When command contains invalid characters
        """
        not_allowed_characters = ["\n", "\r", ";", "|", "||", "&&"]
        # check last character (escaped are in one index)
        if any(command.rstrip(" ").endswith(c) for c in not_allowed_characters):
            raise ValueError("Command contains not allowed characters")

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
        if self.get_os_name() == OSName.WINDOWS:
            raise OsNotSupported("Downloading files from URL on Windows is not supported for SSHConnection.")

        if hide_credentials:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg="hide_credentials flag is not supported for SSHConnection. For continue execution, "
                "the flag will be forced to be set on False.",
            )
            hide_credentials = False
        return super().download_file_from_url(
            url,
            destination_file,
            username=username,
            password=password,
            headers=headers,
            hide_credentials=hide_credentials,
        )
