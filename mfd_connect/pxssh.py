# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""It's a Connection with pexpect pxssh for linux."""

import codecs
import logging
import platform
from pathlib import Path

from subprocess import CalledProcessError
from typing import Type, TYPE_CHECKING

from mfd_typing.os_values import OSBitness, OSType, OSName

from .util.decorators import conditional_cache, clear_system_data_cache

if "Linux" in platform.system():
    from pexpect import EOF, TIMEOUT
    from pexpect import pxssh
    from pexpect.pxssh import ExceptionPxssh

from .base import AsyncConnection, ConnectionCompletedProcess
from .exceptions import (
    ModuleFrameworkDesignError,
    ConnectionCalledProcessError,
    OsNotSupported,
    PxsshException,
    SSHReconnectException,
)
from .process.ssh.esxi import ESXiSSHProcess
from .process.ssh.posix import PosixSSHProcess

from mfd_common_libs import add_logging_level, log_levels

if TYPE_CHECKING:
    from typing import Iterable
    from .process import RemoteProcess
    from pydantic import BaseModel  # from pytest_mfd_config.models.topology import ConnectionModel

logger = logging.getLogger(__name__)
add_logging_level(level_name="MODULE_DEBUG", level_value=log_levels.MODULE_DEBUG)
add_logging_level(level_name="CMD", level_value=log_levels.CMD)
add_logging_level(level_name="OUT", level_value=log_levels.OUT)


class PxsshConnection(AsyncConnection):
    """Handling execute command with expected prompt."""

    _process_classes = [PosixSSHProcess, ESXiSSHProcess]

    def __init__(
        self,
        ip: str,
        username: str,
        password: str,
        *args,
        login_timeout: int = 500,
        skip_key_verification: bool = False,
        model: "BaseModel | None" = None,
        prompts: str = "# $",
        cache_system_data: bool = True,
        **pexpect_args,
    ) -> None:
        """Class init, preparing variables.

        :param ip: IP address of SSH server
        :param username: Username for connection
        :param password: Password for connection
        :param login_timeout: Handle timeout in connection
        :param skip_key_verification: To skip checking of host's key, equivalent of StrictHostKeyChecking=no
        :param model: pydantic model of connection
        :param prompt: pexpect Expected prompts
        :param cache_system_data: Flag to cache system data like self._os_type, OS name and OS bitness
        :param pexpect_args: extra pexpect arguments
        """
        super().__init__(ip=ip, model=model, cache_system_data=cache_system_data)
        self.__use_sudo = False
        self._username = username
        self._password = password
        self._prompts = prompts
        try:
            self._connect()
        except ExceptionPxssh as e:
            raise ModuleFrameworkDesignError("Found problem with connection") from e
        if "windows" in platform.system().casefold():
            raise PxsshException("Windows is not supported as test controller, yet")

    def _connect(self) -> None:
        """
        Connect via ssh.

        Set correct process class
        :raises ExceptionPxssh: if connection is not successful
        """
        try:
            self._child = pxssh.pxssh(options={"StrictHostKeyChecking": "no"})
            self._child.login(self._ip, self._username, self._password)
            index = self._child.prompt()
            if index == 0:
                logger.log(level=log_levels.MODULE_DEBUG, msg=self._child.before.decode("utf-8"))
            os_name = self.get_os_name()
            self._os_type = self.get_os_type()
            for process_class in self._process_classes:
                if os_name in process_class._os_name:
                    self._process_class = process_class
                    break
        except pxssh.ExceptionPxssh as e:
            logger.log(level=log_levels.MODULE_DEBUG, msg="Pxssh failed on login.")
            logger.log(level=log_levels.MODULE_DEBUG, msg=e)

    @conditional_cache
    def get_os_type(self) -> OSType:
        """Get type of client os.

        :return: OSType
        :raises: OsNotSupported: for not supported OS client.
        """
        unix_check_command = "uname -a"  # get architecture and os name
        result = self.execute_command(unix_check_command, prompts=" $", expected_return_codes=[0])
        if result.return_code:
            logger.log(level=log_levels.MODULE_DEBUG, msg=f"Debug data of os_type method: {result}")
            raise OsNotSupported("Client OS not supported")
        return OSType.POSIX

    @conditional_cache
    def get_os_name(self) -> OSName:
        """Get name of client OS.

        :return: OSName
        :raises: OsNotSupported: for not supported OS client.
        """
        unix_check_command = "uname -s"
        # get kernel name - consistent with platform.system, which read first part of uname
        result = self.execute_command(unix_check_command, prompts=" $", expected_return_codes=[0])
        for os_type in OSName:
            if os_type.value in result.stdout:
                return os_type
        raise OsNotSupported("Client OS not supported")

    @conditional_cache
    def get_os_bitness(self) -> OSBitness:
        """Get bitness of client os.

        :return: OSBitness
        :raises: OsNotSupported: for not supported OS client.
        """
        if self._os_type == OSType.POSIX:
            unix_check_command = "uname -m"  # get machine info
            result = self.execute_command(unix_check_command, prompts=" $", expected_return_codes=[0])
        else:
            raise OsNotSupported("OS Bitness is not supported for this client OS")
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Debug data of os_bitness method: {result.stdout}")
        if "64" in result.stdout:
            return OSBitness.OS_64BIT
        else:
            return OSBitness.OS_32BIT

    def _exec_command(
        self, command: str, prompts: str | None = "", error_list: list[str] = [], timeout: int = 120
    ) -> tuple[str]:
        """
        Execute command with expected prompt.

        :param command: Command to be executed
        :param prompts: Expected prompt
        :param error_list: Any expected errors to check in stdout
        :param timeout: Expected time out for command
        :return: stdin_pipe, stdout_pipe, stderr_pipe, returncode as
            input command, cli output string, signal status and exit status
        """
        _error_list = ["FAILED", "Invalid input", "ERROR", "not found", "Syntax error", "Segmentation fault"]
        _error_list = error_list if error_list else _error_list
        self._child.sendline(command)
        i = self._child.expect([prompts if prompts != "" else self._prompts, EOF, TIMEOUT], timeout=timeout)
        if i == 0:
            logger.log(level=log_levels.MODULE_DEBUG, msg=self._child.before)
            if any(error in self._child.before.decode("utf-8") for error in _error_list):
                # 5   EIO I/O error
                self._child.exitstatus = 5
            else:
                self._child.exitstatus = 0
            return command, self._child.before, self._child.signalstatus, self._child.exitstatus
        else:
            logger.log(level=log_levels.MODULE_DEBUG, msg="No prompt match for expected connection handle.")
            # 8 ENOEXEC Exec format error
            return command, self._child.before, self._child.signalstatus, 8

    def execute_command(
        self,
        command: str,
        prompts: str | None = "",
        error_list: list[str] = [],
        *,
        input_data: str = None,
        cwd: str = None,
        timeout: int = None,
        env: dict = None,
        stderr_to_stdout: bool = False,
        discard_stdout: bool = False,
        discard_stderr: bool = False,
        expected_return_codes: "Iterable | None" = frozenset({0}),
        shell: bool = False,
        custom_exception: Type[CalledProcessError] = None,
    ) -> "ConnectionCompletedProcess":
        """
        Run program and wait for its completion.

        :param command: Command to execute, with all necessary arguments
        :param prompts: Expected prompt with execute command
        :param error_list: Any expected errors to check in stdout
        :param input_data: Data to pass to program on the standard input
        :param cwd: Directory to start program execution in
        :param timeout: Program execution timeout, in seconds
        :param env: Environment to execute the program in
        :param stderr_to_stdout: Redirect stderr to stdout, ignored if discard_stderr is set to True
        :param discard_stdout: Don't capture stdout stream
        :param discard_stderr: Don't capture stderr stream
        :param expected_return_codes: Return codes to be considered acceptable.
                                      If None - any return code is considered acceptable
        :param shell: Start process in a shell. Allows usage of shell constructions like pipes etc.
        :param custom_exception: Enable us to raise our exception if program exits with an unexpected return code.
        custom_exception must inherit from CalledProcessError to use its fields like returncode, cmd, output, stderr

        :return: ConnectionCompletedProcess object
        :raises TimeoutExpired: if program doesn't conclude before timeout is reached
        :raises ConnectionCalledProcessError: if program exits with an unexpected return code
        """
        super().execute_command(
            command,
            input_data=input_data,
            cwd=cwd,
            timeout=timeout,
            env=env,
            stderr_to_stdout=stderr_to_stdout,
            discard_stdout=discard_stdout,
            discard_stderr=discard_stderr,
            expected_return_codes=expected_return_codes,
            shell=shell,
        )

        command = self._adjust_command(command)
        logger.log(level=log_levels.CMD, msg=f"Executing >{self._ip}> '{command}', cwd: {cwd}")
        stdin_pipe, stdout_pipe, stderr_pipe, returncode = self._exec_command(command, prompts, error_list)
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Finished executing '{command}' ")
        stdout, stderr = None, None
        if stdout_pipe:
            stdout = codecs.decode(stdout_pipe, encoding="utf-8", errors="backslashreplace")
            if stdout:
                logger.log(level=log_levels.OUT, msg=f"Output:\nstdout>>\n{stdout}")

        if stderr_pipe:
            stderr = codecs.decode(stderr_pipe, encoding="utf-8", errors="backslashreplace")
            if stderr:
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

    def _adjust_command(self, command: str) -> str:
        """
        Adjust command.

        :param command: command to adjust
        :return: command
        """
        if self.__use_sudo:
            return f'sudo sh -c "{command}"' if "echo" in command else f"sudo {command}"
        return command

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

    def _disconnect(self) -> None:
        """To terminate ssh connection."""
        self._child.close()
        logger.log(level=log_levels.MODULE_DEBUG, msg="Connection Terminated")

    @clear_system_data_cache
    def _reconnect(self) -> None:
        """
        Reconnect to SSHClient.

        :raises SSHReconnectException: in case of fail in establishing connection
        """
        logger.log(level=log_levels.MODULE_DEBUG, msg="Connection lost, reconnecting")
        self._connect()
        if not self._child:
            logger.log(level=log_levels.MODULE_DEBUG, msg="Connection lost.")
            raise SSHReconnectException("Cannot reconnect to host!")
        logger.log(level=log_levels.MODULE_DEBUG, msg="Reconnection successful.")

    def start_process(
        self,
        command: str,
        *,
        cwd: str = None,
        env: dict = None,
        stderr_to_stdout: bool = False,
        discard_stdout: bool = False,
        discard_stderr: bool = False,
        cpu_affinity: int | list[int] | str | None = None,
        shell: bool = False,
        enable_input: bool = False,
        log_file: bool = False,
        output_file: str | None = None,
    ) -> "RemoteProcess":
        """
        Start process.

        :param command: Command to execute, with all necessary arguments
        :param cwd: Directory to start program execution in
        :param env: Environment to execute the program in
        :param stderr_to_stdout: Redirect stderr to stdout, ignored if discard_stderr is set to True
        :param discard_stdout: Don't capture stdout stream
        :param discard_stderr: Don't capture stderr stream
        :param cpu_affinity: Processor numbers the process will run on in a format chosen by the user.
                             Acceptable formats are: cpu=1, cpu=[1, 2, 3, 6], cpu="1, 4, 5", cpu="1-7", cpu="0, 2-6"
        :param shell: Start process in a shell. Allows usage of shell constructions like pipes etc.
        :param enable_input: Whether or not allow writing to process' stdin
        :param log_file: Switch to enable redirection to generated by method log file
        :param output_file: Path to file as redirection of command output, interchangeably with log_file param.
        :return: Running process, RemoteProcess object
        """
        raise NotImplementedError("start_process not yet implemented for PxsshConnection.")

    def start_processes(
        self,
        command: str,
        *,
        cwd: str = None,
        env: dict = None,
        stderr_to_stdout: bool = False,
        discard_stdout: bool = False,
        discard_stderr: bool = False,
        cpu_affinity: int | list[int] | str | None = None,
        shell: bool = False,
        enable_input: bool = False,
        log_file: bool = False,
        output_file: str | None = None,
    ) -> list["RemoteProcess"]:
        """
        Start processes.

        Use start_processes if you need to execute cmd which will trigger more than one process,
        and you want to receive list of new processes.

        :param command: Command to execute, with all necessary arguments
        :param cwd: Directory to start program execution in
        :param env: Environment to execute the program in
        :param stderr_to_stdout: Redirect stderr to stdout, ignored if discard_stderr is set to True
        :param discard_stdout: Don't capture stdout stream
        :param discard_stderr: Don't capture stderr stream
        :param cpu_affinity: Processor numbers the process will run on in a format chosen by the user.
                             Acceptable formats are: cpu=1, cpu=[1, 2, 3, 6], cpu="1, 4, 5", cpu="1-7", cpu="0, 2-6"
        :param shell: Start process in a shell. Allows usage of shell constructions like pipes etc.
        :param enable_input: Whether or not allow writing to process' stdin
        :param log_file: Switch to enable redirection to generated by method log file
        :param output_file: Path to file as redirection of command output, interchangeably with log_file param.
        :return: List of running processes, RemoteProcess objects
        """
        raise NotImplementedError("start_processes not yet implemented for PxsshConnection.")

    def path(self) -> Path:
        """
        Path represents a filesystem path.

        :return: Path object for Connection
        """
        raise NotImplementedError("Not implemented in PxsshConnection")

    def restart_platform(self) -> None:
        """Reboot host."""
        raise NotImplementedError("Not implemented in PxsshConnection")

    def shutdown_platform(self) -> None:
        """Shutdown host."""
        raise NotImplementedError("Not implemented in PxsshConnection")

    def wait_for_host(self, timeout: int = 60) -> None:
        """
        Wait for host availability.

        :param timeout: Time to check until fail
        :raises TimeoutError: when timeout is expired
        """
        raise NotImplementedError("Not implemented in PxsshConnection")

    def disconnect(self) -> None:
        """Close connection with host."""
        raise NotImplementedError("Not implemented in PxsshConnection")
