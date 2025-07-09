# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for InteractiveSSHConnection class."""

import logging
import re
import time
from subprocess import CalledProcessError, TimeoutExpired
from typing import Iterable, TYPE_CHECKING

from mfd_common_libs import TimeoutCounter, add_logging_level, log_levels
from mfd_typing.cpu_values import CPUArchitecture
from mfd_typing.os_values import OSBitness, OSType, OSName, SWITCHES_OS_NAME_REGEXES
from netaddr import IPAddress
from paramiko import SSHException, SSHClient, WarningPolicy, AuthenticationException
from paramiko.client import MissingHostKeyPolicy, AutoAddPolicy

from .base import AsyncConnection, ConnectionCompletedProcess
from .exceptions import (
    InteractiveSSHException,
    OsNotSupported,
    ConnectionCalledProcessError,
)
from .exceptions import SSHReconnectException
from .pathlib.path import CustomPath
from .process.interactive_ssh.base import InteractiveSSHProcess
from .process.ssh.base import SSHProcess
from .util.decorators import conditional_cache, clear_system_data_cache

if TYPE_CHECKING:
    from paramiko.channel import Channel
    from pydantic import (
        BaseModel,
    )
    from pathlib import Path  # noqa

logger = logging.getLogger(__name__)
add_logging_level(level_name="MODULE_DEBUG", level_value=log_levels.MODULE_DEBUG)
add_logging_level(level_name="CMD", level_value=log_levels.CMD)
add_logging_level(level_name="OUT", level_value=log_levels.OUT)
# set paramiko debug prints into WARNING level because of visible paramiko logs with mfd logs
logging.getLogger("paramiko").setLevel(logging.WARNING)
logging.getLogger("paramiko.transport").setLevel(logging.CRITICAL)

BUFFER_SIZE = 1024
IO_TIMEOUT = 10
NEW_LINE_PATTERN = "(\r\n|\r)"


class InteractiveSSHConnection(AsyncConnection):
    """
    Implementation of SSHConnection type for remote usage.

    Operations will be performed on machine via SSH connection.

    Usage example:
    >>> conn = InteractiveSSHConnection()
    >>> proc = conn.start_process('ping localhost', shell=True)
    test
    """

    def __init__(
        self,
        ip: "IPAddress | str",
        *,
        port: int = 22,
        username: str,
        password: str | None,
        key_path: "list[str | Path] | str | Path | None" = None,
        skip_key_verification: bool = False,
        model: "BaseModel | None" = None,
        default_timeout: int | None = None,
        cache_system_data: bool = True,
        **_,
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
        :param cache_system_data: Flag to cache system data like self._os_type and OS name
        """
        super().__init__(ip, model, default_timeout, cache_system_data)
        self._prompt = None
        self._ip = IPAddress(ip)
        self._connection_tmp = SSHClient()
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
            self._connection_tmp.load_system_host_keys()

        self._connection_tmp.set_missing_host_key_policy(policy)
        try:
            self._connect()
        except SSHException as e:
            raise InteractiveSSHException("Found problem with connection") from e

        self._process_class = InteractiveSSHProcess
        self._process = None
        self._os_type = self.get_os_type()

    def __str__(self):
        return "interactive_ssh"

    def _connect(self) -> None:
        """
        Connect via ssh.

        Set correct process class
        :raises OsNotSupported: if os not found in available process classes
        """
        self._connection_tmp.connect(**self._connection_details, compress=True)

        key_auth = str(self._connection_tmp.get_transport())
        if "awaiting auth" in key_auth:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg="SSH server requested additional authentication",
            )
            (self._connection_tmp.get_transport()).auth_interactive_dumb(self._connection_details["username"])

        self._connection = self._connection_tmp.invoke_shell(width=511, height=1000)
        self._connection.settimeout(IO_TIMEOUT)
        time.sleep(2)  # wait for banners
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Prompt is {self.prompt}")

    def disconnect(self) -> None:
        """Close connection."""
        self._connection.close()
        self._connection_tmp.close()

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
    def _remote(self) -> "Channel":
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
        """Get type of os."""
        result = ""
        command_map = [
            (
                OSType.WINDOWS,
                "powershell.exe -OutPutFormat Text -nologo -noninteractive "
                '"Get-WmiObject -Class Win32_OperatingSystem | Select-Object -Property Caption, OSArchitecture"',
            ),
            (OSType.POSIX, "uname -a"),
            (OSType.SWITCH, "show version"),
            (OSType.SWITCH, "show system"),
        ]
        for os_type, command in command_map:
            result = self.execute_command(command, expected_return_codes=[0, 1, 127])
            if result.return_code:
                continue
            return os_type
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Debug data of os_type method: {result}")
        raise OsNotSupported("OS not supported")

    def _get_os_name_for_switch(self, result: "ConnectionCompletedProcess") -> OSName | None:
        """
        Check switch output.

        :param result: Result of command execution
        :return: OSName if matched
        """
        for switch_os_name, regex_list in SWITCHES_OS_NAME_REGEXES.items():
            return (
                switch_os_name if any(re.search(regex, result.stdout, re.IGNORECASE) for regex in regex_list) else None
            )

    @conditional_cache
    def get_os_name(self) -> OSName:
        """Get name of os."""
        result = ""
        command_list = [
            "powershell.exe -OutPutFormat Text -nologo -noninteractive "
            '"Get-WmiObject -Class Win32_OperatingSystem | Select-Object -Property Caption, OSArchitecture"',
            "uname -s",
            "show version",
            "show system",
        ]
        for command in command_list:
            result = self.execute_command(command, expected_return_codes=[0, 1, 127])
            if result.return_code:
                continue
            for os in OSName:
                if os.casefold() in result.stdout.casefold():
                    return OSName(os)
            # check for switches
            return self._get_os_name_for_switch(result)

        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Debug data of os_type method: {result}")
        raise OsNotSupported("OS not supported")

    def get_os_bitness(self) -> OSBitness:
        """Get bitness of Host OS."""
        raise NotImplementedError("Not implemented in Interactive SSH")

    def get_cpu_architecture(self) -> CPUArchitecture:
        """Get CPU Architecture."""
        raise NotImplementedError("Not implemented in Interactive SSH")

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
        discard_both_command = {
            OSType.WINDOWS: ">nul 2>&1",
            OSType.POSIX: ">/dev/null 2>&1",
        }

        # spaces on posix required
        posix_closing_bracket = f"{';' if not command.rstrip().endswith('&') else ''} }}"
        grouping_brackets = {
            OSType.WINDOWS: ("(", ")"),
            OSType.POSIX: ("{ ", posix_closing_bracket),
        }

        opening_bracket, closing_bracket = grouping_brackets.get(self._os_type, ("", ""))
        command = f"{opening_bracket}{command}{closing_bracket}"

        if discard_stdout and discard_stderr:
            command = f"{command} {discard_both_command.get(self._os_type, '')}"
        elif discard_stdout:
            command = f"{command} {discard_stdout_command.get(self._os_type, '')}"
        elif discard_stderr:
            command = f"{command} {discard_stderr_command.get(self._os_type, '')}"

        return command

    def execute_command(
        self,
        command: str,
        *,
        input_data: str | None = None,
        cwd: str | None = None,
        timeout: int | None = None,
        env: dict | None = None,
        stderr_to_stdout: bool = True,
        discard_stdout: bool = False,
        discard_stderr: bool = False,
        skip_logging: bool = False,
        expected_return_codes: Iterable | None = frozenset({0}),
        shell: bool = False,
        custom_exception: type[CalledProcessError] | None = None,
    ) -> "ConnectionCompletedProcess":
        """
        Run program and wait for its completion.

        :param command: Command to execute, with all necessary arguments
        :param input_data: Data to pass to program on the standard input
        :param cwd: Directory to start program execution in
        :param timeout: Program execution timeout, in seconds
        :param env: Environment to execute the program in
        :param stderr_to_stdout: Redirect stderr to stdout.
                                 In InteractiveSSH this option must be set to True as we operate on one channel.
        :param discard_stdout: Don't capture stdout stream.
                               Not supported in InteractiveSSH as in one channel we can't separate stdout from stderr.
        :param discard_stderr: Don't capture stderr stream.
                               Not supported in InteractiveSSH as in one channel we can't separate stdout from stderr.
        :param skip_logging: Skip logging of stdout/stderr if captured
        :param expected_return_codes: Return codes to be considered acceptable.
                                      If None - any return code is considered acceptable
        :param shell: Start process in a shell. Allows usage of shell constructions like pipes etc.
        :param custom_exception: Enable us to raise our exception if program exits with an unexpected return code.
        custom_exception must inherit from CalledProcessError to use its fields like returncode, cmd, output, stderr

        :return: ConnectionCompletedProcess object
        :raises TimeoutExpired: if program doesn't conclude before timeout is reached
        :raises ValueError: if command has invalid characters inside
        :raises ConnectionCalledProcessError: if program exits with an unexpected return code
        """
        if stderr_to_stdout is False:
            logger.warning("stderr_to_stdout flag is not supported in InteractiveSSHConnection. It will be ignored.")
        if discard_stdout or discard_stderr:
            logger.warning(
                "discard_stdout and discard_stderr flags are not supported in InteractiveSSHConnection."
                "They will be ignored."
            )

        if cwd is not None:
            self._start_process(f"cd {cwd}", timeout, env)
            self.refresh_prompt()

        return_code = None
        self._start_process(command, timeout, env)
        time.sleep(2)
        chan = self.read_channel()
        output = self.cleanup_stdout(command, chan)
        _timeout_value = timeout or self.default_timeout or IO_TIMEOUT
        _timeout_counter = TimeoutCounter(_timeout_value)
        while not _timeout_counter:
            if self.prompt in chan:
                break
            time.sleep(1)
            chan = self.read_channel()
            output += self.cleanup_stdout(command, chan)
        else:
            raise TimeoutExpired(
                f"Command '{command}' did not finish in {_timeout_value} seconds",
                _timeout_value,
            )

        if custom_exception and not expected_return_codes:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg=f"Return codes are ignored, passed exception: {custom_exception} will be not raised.",
            )
        if expected_return_codes is not None:
            return_code = self._get_return_code(
                output=output,
                timeout=timeout,
                env=env,
            )
        if not expected_return_codes or return_code in expected_return_codes:
            completed_process = ConnectionCompletedProcess(
                args=command,
                stdout=output,
                stderr="",
                stdout_bytes=b"",
                stderr_bytes=b"",
                return_code=return_code,
            )
            return completed_process
        else:
            if custom_exception:
                raise custom_exception(returncode=return_code, cmd=command, output=output, stderr="")
            raise ConnectionCalledProcessError(returncode=return_code, cmd=command, output=output, stderr="")

    def _get_return_code(
        self,
        output: str,
        timeout: int | None = None,
        env: dict | None = None,
    ) -> int | None:
        """
        Get return code from channel.

        :param env: Environment to execute the program in
        :param output: Output from channel
        :param timeout: Program execution timeout, in seconds
        :return: Return code of executed command
        """
        if hasattr(self, "_os_type") and self._os_type != OSType.SWITCH:
            if self._os_type == OSType.WINDOWS:
                cmd = "echo %errorlevel%"
            elif self._os_type == OSType.POSIX:
                cmd = "echo $?"
            else:
                raise Exception(f"Unsupported OS Type {self._os_type} for getting return code")
            self._start_process(cmd, timeout, env)
            time.sleep(2)
            rc_chan = self.cleanup_stdout(cmd, self.read_channel())
            try:
                rc = int(rc_chan.splitlines()[-1].strip())
            except Exception as e:
                logger.log(
                    level=log_levels.MODULE_DEBUG,
                    msg=f"Cannot get return code from channel: {rc_chan}",
                )
                logger.log(level=log_levels.MODULE_DEBUG, msg=e)
                rc = None
        else:
            invalid_responses = [
                r"% Invalid input detected",
                r"% Unrecognized command",
                r"syntax error, expecting",
                r"Error: Unrecognized command",
                r"%Error",
                r"command not found",
                r"Syntax Error: unexpected argument",
            ]
            for pattern in invalid_responses:
                match = re.search(pattern, output, flags=re.I)
                if match:
                    rc = 1
                    break
            else:
                rc = 0
        return rc

    def _start_process(
        self,
        command: str,
        timeout: int | None = None,
        environment: dict | None = None,
    ) -> None:
        """
        Injected some arguments for Paramiko exec_command.

        In InteractiveSSHConnection, we operate on one channel during all commands' executions,
        that's why it's different from normal SSH and that's why we just flush and write here in this method.

        :param command: the command to execute
        :param timeout:
            set command's channel timeout. See `.Channel.settimeout`
        :param environment:
            a dict of shell environment variables, to be merged into the
            default environment that the remote command executes within.

            .. warning::
                Servers may silently reject some environment variables; see the
                warning in `.Channel.set_environment_variable` for details.

        :raises: `.SSHException` -- if the server fails to execute the command
        """
        if timeout is not None:
            self._connection.settimeout(timeout)

        if environment:
            self._connection.update_environment(environment)

        self.flush()

        self.write_to_channel(command, with_enter=True)

    def read_channel(self) -> str:
        """Read channel."""
        chan = ""
        try:
            while self._connection.recv_ready():
                chan += self._connection.recv(BUFFER_SIZE).decode()
            return chan
        except TimeoutError:
            return chan
        except Exception:
            raise Exception("Cannot read channel")

    def write_to_channel(self, data: str, with_enter: bool = True) -> None:
        """
        Write to channel.

        :param data: Data to write
        :param with_enter: Add enter at the end of data
        """
        self._connection.send(bytes(data, encoding="utf-8"))
        if with_enter:
            self._connection.send(b"\n")

    def flush(self) -> None:
        """Flush channel."""
        while self._connection.recv_ready():
            self._connection.recv(BUFFER_SIZE)

    def refresh_prompt(self) -> None:
        """Refresh prompt."""
        self._prompt = self._read_prompt()

    @property
    def prompt(self) -> str:
        """Get prompt from connection."""
        if self._prompt is None:
            self._prompt = self._read_prompt()
        return self._prompt

    def _read_prompt(self) -> str:
        self.flush()  # flush everything from before
        self.write_to_channel("\n", False)  # enter key
        time.sleep(2)
        chan = str(self._connection.recv(BUFFER_SIZE), encoding="utf-8").strip()
        if not chan:
            raise InteractiveSSHException("Cannot read prompt")
        prompt = chan.splitlines()[-1]
        self.flush()  # flush everything after (just in case)
        logger.debug(prompt)
        return prompt

    def start_process(
        self,
        command: str,
        *,
        cwd: str | None = None,
        env: dict | None = None,
        stderr_to_stdout: bool = False,
        discard_stdout: bool = False,
        discard_stderr: bool = False,
        cpu_affinity: int | list[int] | str | None = None,
        shell: bool = False,
        enable_input: bool = False,
        log_file: bool = False,
        output_file: str | None = None,
        get_pty: bool = False,
    ) -> "InteractiveSSHProcess":
        """
        Start process.

        :param command: Command to execute, with all necessary arguments
        :param cwd: Directory to start program execution in, not used for SSH
        :param env: Environment to execute the program in
        :param stderr_to_stdout: Redirect stderr to stdout, ignored if discard_stderr is set to True, not used for SSH
        :param discard_stdout: Don't capture stdout stream, not used for SSH
        :param discard_stderr: Don't capture stderr stream, not used for SSH
        :param cpu_affinity: Processor numbers the process will run on in a format chosen by the user. Not used for SSH.
        :param shell: Start process in a shell. Allows usage of shell constructions like pipes etc., not used for SSH
        :param enable_input: Whether or not allow writing to process' stdin, not used for SSH
        :param log_file: Switch to enable redirection to generated by method log file. Not used for ssh.
        :param output_file: Path to file as redirection of command output, interchangeably with log_file param.
            Not used for ssh.
        :param get_pty:
            Request a pseudo-terminal from the server (default ``False``). Enables passing key codes to process.
            See `.Channel.get_pty`
            Not used for interactive ssh.
        :return: Running process, RemoteProcess object
        """
        if cwd is not None:
            self._start_process(f"cd {cwd}", environment=env)
            self.refresh_prompt()

        if self._process is not None:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg="Process already started. Cannot run more than 1 process.",
            )
            return self._process
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

        logger.log(level=log_levels.CMD, msg=f"Starting process >{self._ip}> '{command}'")
        if cpu_affinity is not None:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg="Used cpu affinity, but it's not functional for SSH.",
            )
        if output_file is not None:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg="Used output_file, but it's not functional for SSH.",
            )
        if log_file is True:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg="Used log_file, but it's not functional for SSH.",
            )

        self._start_process(
            command,
            environment=env,
        )

        self._process = self._process_class(
            stdout=None,
            connection=self,
            command=command,
        )
        return self._process

    def start_processes(
        self,
        command: str,
        *,
        cwd: str | None = None,
        env: dict | None = None,
        stderr_to_stdout: bool = False,
        discard_stdout: bool = False,
        discard_stderr: bool = False,
        cpu_affinity: int | list[int] | str | None = None,
        shell: bool = False,
        enable_input: bool = False,
        get_pty: bool = False,
        log_file: bool = False,
        output_file: str | None = None,
    ) -> list["SSHProcess"]:
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
        raise NotImplementedError("Not implemented in Interactive SSH")

    def start_process_by_start_tool(
        self,
        command: str,
        *,
        cwd: str | None = None,
        discard_stdout: bool = False,
        cpu_affinity: int | list[int] | str | None = None,  # noqa
        output_file: str | None = None,  # noqa
        numa_node: int | None = None,  # noqa
        **kwargs,
    ) -> "InteractiveSSHProcess":
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

    def execute_powershell(
        self,
        command: str,
        *,
        input_data: str | None = None,
        cwd: str | None = None,
        timeout: int = None,
        env: dict | None = None,
        stderr_to_stdout: bool = False,
        discard_stdout: bool = False,
        discard_stderr: bool = False,
        skip_logging: bool = False,
        expected_return_codes: Iterable | None = frozenset({0}),
        shell: bool = False,
        custom_exception: type[CalledProcessError] = None,
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
        raise NotImplementedError("Not implemented in Interactive SSH")

    def restart_platform(self) -> None:
        """
        Reboot host.

        Internal dict of reboot platform commands
        """
        raise NotImplementedError("Not implemented in Interactive SSH")

    def shutdown_platform(self) -> None:
        """
        Shutdown host.

        Internal dict of shutdown platform commands
        """
        raise NotImplementedError("Not implemented in Interactive SSH")

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
        raise NotImplementedError("Not implemented in Interactive SSH")

    def enable_sudo(self) -> None:
        """
        Enable sudo for command execution.

        :raises OsNotSupported: when os_type is different from posix
        """
        raise NotImplementedError("Not implemented in Interactive SSH")

    def disable_sudo(self) -> None:
        """Disable sudo for command execution."""
        raise NotImplementedError("Not implemented in Interactive SSH")

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

    def cleanup_stdout(self, command: str, stdout: str, prompt: bool = True) -> str:
        """
        Clean stdout from command and prompt.

        :param command: Command to remove from stdout
        :param stdout: Output from command
        :param prompt: Flag for removing prompt
        :return: Cleaned stdout
        """
        stdout = re.sub(rf"({re.escape(command)}(\n|\r\n|\r)*)", "", stdout)
        if prompt is True:
            stdout = re.sub(rf"({re.escape(self.prompt)}\s*(\n|\r\n|\r)*)", "", stdout)
        stdout = re.sub(NEW_LINE_PATTERN, "\n", stdout)
        return stdout
