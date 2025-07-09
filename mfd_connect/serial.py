# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for SerialConnection class."""

import logging
import time
import re
import hashlib
import os

from mfd_typing.cpu_values import CPUArchitecture
from mfd_typing.os_values import OSName, OSType, OSBitness
from mfd_connect.util import UNIX_PROMPT_REGEX, MEV_IMC_SERIAL_BAUDRATE, Ansiterm
from mfd_connect.exceptions import RemoteProcessInvalidState
from mfd_common_libs import add_logging_level, log_levels
from subprocess import CalledProcessError
from typing import Iterable, Optional, Type, Union, TYPE_CHECKING, List
from pathlib import Path
from .base import Connection, AsyncConnection, ConnectionCompletedProcess
from .telnet.telnet import TelnetConnection
from .exceptions import (
    SerialException,
    TelnetException,
    TransferFileError,
    OsNotSupported,
)
from .util.console_utils import ANSITERM_ROWS_SIZE, ANSITERM_COLS_SIZE
from .util.decorators import conditional_cache, clear_system_data_cache

if TYPE_CHECKING:
    from .util import SerialKeyCode
    from pydantic import BaseModel  # from pytest_mfd_config.models.topology import ConnectionModel

logger = logging.getLogger(__name__)
add_logging_level(level_name="MODULE_DEBUG", level_value=log_levels.MODULE_DEBUG)
add_logging_level(level_name="CMD", level_value=log_levels.CMD)


class SerialConnection(Connection):
    """Class handling communication via Serial."""

    def __init__(
        self,
        connection: AsyncConnection,
        *,
        username: str | None = None,
        password: str | None = None,
        telnet_port: int,
        serial_device: str,
        login_prompt: str = "login: ",
        password_prompt: str = "Password: ",
        prompt_regex: str = UNIX_PROMPT_REGEX,
        baudrate: int = MEV_IMC_SERIAL_BAUDRATE,
        execution_retries: int = 2,
        retry_cooldown: int = 2,
        buffer_size: int | None = None,
        login_timeout: int = 15,
        is_veloce: bool = False,
        with_redirection: bool = True,
        serial_logs_path: str | Path = None,
        model: "BaseModel | None" = None,
        cache_system_data: bool = True,
    ):
        """
        Initialise SerialConnection.

        :param connection: Connection handle to host controller
        :param username: Username for target
        :param password: Password for target
        :param telnet_port: Port for netcat redirection
        :param serial_device: Serial device to connect to
        :param login_prompt: Prompt appearing when asking for username during login
        :param password_prompt: Prompt appearing when asking for password during login
        :param prompt_regex: Regex for prompt appearing after logging in, determines whether it is pre-OS or OS case
        :param baudrate: Baudrate for serial device
        :param execution_retries: Number of times executing of commands will be retried in case of dropped connection
        :param retry_cooldown: Cooldown before retrying to get return code
        :param buffer_size: Size of line buffer when executing commands
        :param login_timeout: Timeout used when waiting for login/password prompt and after-credentials prompt to appear
        :param is_veloce: Set to True if connecting to Veloce setups (increases constant values for executing commands)
        :param with_redirection: Set to True if you wish to prepare Telnet session under the hood via netcat redirection
        :param model: pydantic model of connection
        :param cache_system_data: Flag to cache system data like self._os_type, OS name and OS bitness
        """
        super().__init__(model=model, cache_system_data=cache_system_data)
        self._ip = connection._ip
        self._telnet_port = telnet_port
        self._serial_device = serial_device
        self._baudrate = baudrate
        self._is_veloce = is_veloce
        self._redirection = with_redirection
        self._serial_logs_path = serial_logs_path

        # host where serial is connected
        self._remote_host = connection

        # run netcat with forwarding char device
        if self._redirection:
            self._run_netcat()

        try:
            self._telnet_connection = TelnetConnection(
                ip=self._ip,
                username=username,
                password=password,
                port=telnet_port,
                login_prompt=login_prompt,
                password_prompt=password_prompt,
                prompt_regex=prompt_regex,
                execution_retries=execution_retries,
                retry_cooldown=retry_cooldown,
                buffer_size=buffer_size,
                login_timeout=login_timeout,
                is_veloce=is_veloce,
            )
        except TelnetException:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg="Could not connect to target, setting baudrate for serial device and retrying...",
            )
            self._set_baudrate()
            try:
                self._telnet_connection = TelnetConnection(
                    ip=self._ip,
                    username=username,
                    password=password,
                    port=telnet_port,
                    login_prompt=login_prompt,
                    password_prompt=password_prompt,
                    prompt_regex=prompt_regex,
                    execution_retries=execution_retries,
                    retry_cooldown=retry_cooldown,
                    buffer_size=buffer_size,
                    login_timeout=login_timeout,
                    is_veloce=is_veloce,
                )
            except TelnetException as e:
                raise SerialException(f"Could not connect to target after setting baudrate to {baudrate}") from e

    def __str__(self):
        return "serial"

    def _run_netcat(self, start_netcat_wait_time: float = 0.5) -> None:
        """Start netcat server and forward traffic from char device to/from TCP."""
        logger.log(level=log_levels.MODULE_DEBUG, msg="Killing old netcat connections on host")
        self._remote_host.execute_command(f'pkill -f "nc -k -l -4 {self._telnet_port}"', expected_return_codes=None)

        logger.log(level=log_levels.MODULE_DEBUG, msg="Starting netcat server on host")
        netcat_server_command = f"nc -k -l -4 {self._telnet_port} > {self._serial_device} < {self._serial_device}"
        self._server_process = self._remote_host.start_process(netcat_server_command, shell=True)

        logger.log(level=log_levels.MODULE_DEBUG, msg="Waiting for netcat server to start...")
        time.sleep(start_netcat_wait_time)

        if not self._server_process.running:
            raise SerialException(
                "Netcat server did not start properly. Make sure pppd connection is not blocking this device."
            )
        logger.log(level=log_levels.MODULE_DEBUG, msg="Netcat sender server is running")

        if self._serial_logs_path:
            logger.log(level=log_levels.MODULE_DEBUG, msg="Path for serial logs given. Logs will be gathered by tee.")
            self._trigger_tee_serial_logging(start_netcat_wait_time)

    def _trigger_tee_serial_logging(self, start_netcat_wait_time: float) -> None:
        """
        Trigger tee process to log serial communication.

        :param start_netcat_wait_time: sleep time after netcat triggering
        :raises SerialException: When processes are not running.
        """
        # tee will create file, but not folder
        dir_path = os.path.dirname(self._serial_logs_path)
        if dir_path:
            self._remote_host.path(dir_path).mkdir(parents=True, exist_ok=True)

        nc_localhost_telnet_port = f"nc 127.0.0.1 {self._telnet_port}"

        logger.log(level=log_levels.MODULE_DEBUG, msg="Killing old netcat localhost process.")
        self._remote_host.execute_command(f'pkill -f "{nc_localhost_telnet_port}"', expected_return_codes=None)

        logger.log(level=log_levels.MODULE_DEBUG, msg="Starting nc | tee logging...")
        self._tee_logging_processes_list = self._remote_host.start_processes(
            f"{nc_localhost_telnet_port} | tee {self._serial_logs_path}", shell=True
        )
        time.sleep(start_netcat_wait_time)

        if any(not process.running for process in self._tee_logging_processes_list):
            raise SerialException("Triggering tee did not succeed.")
        logger.log(level=log_levels.MODULE_DEBUG, msg="nc | tee logging processes started properly.")

    def _set_baudrate(self) -> None:
        """
        Initialize serial device baud rate.

        This method's purpose is to enable serial device communication through Telnet when no previous
        connection was established. Without it, there would be no login prompt appearing for Telnet.

        :raises ConnectionCalledProcessError: if executing or killing `screen` or `stty` command failed
        """
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Setting {self._baudrate} for device {self._serial_device}")
        res = self._remote_host.execute_command(
            command=f"screen -dm {self._serial_device} {self._baudrate}", expected_return_codes={0, 127}
        )
        if res.return_code == 127:
            logger.log(
                level=log_levels.MODULE_DEBUG, msg="Unable to execute screen command to set baud rate, trying stty..."
            )
            self._remote_host.execute_command(command=f"stty -F {self._serial_device} {self._baudrate}", shell=True)
            return

        self._remote_host.execute_command("pkill screen")

    def _get_baudrate(self) -> int:
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Getting {self._baudrate} for device {self._serial_device}")
        res = self._remote_host.execute_command(
            command=f"stty < {self._serial_device}", shell=True, expected_return_codes={0}
        )
        pattern = r"^speed\s(?P<rate>\d*)\sbaud.*$"
        match = re.match(pattern=pattern, string=res.stdout, flags=re.MULTILINE)

        if match:
            return int(match.group("rate"))
        else:
            raise SerialException(f"Couldn't get baudrate for device: {self._serial_device}")

    def _check_control_sum(self, *, local_path: Union[str, Path], remote_path: Union[str, Path]) -> None:
        """
        Check control sum of local file and remote file.

        :param local_path: Path of local file
        :param remote_path: Path of remote file
        :raises TransferFileError: if control sums are not equal
        """
        try:
            # get sha256sum for remote file
            remote_sha256sum_stdout = self._telnet_connection.execute_command(f"sha256sum {remote_path}").stdout
            remote_sha256sum = remote_sha256sum_stdout.split(" ", 1)[0]

            # get sha256sum for local file
            local_sha256sum = hashlib.sha256(open(local_path, "rb").read()).hexdigest()
        except Exception as e:
            raise TransferFileError("Failed to get control sums") from e

        if local_sha256sum == remote_sha256sum:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg=f"Correct sha256sum for file, local: {local_sha256sum}, remote: {remote_sha256sum}",
            )
        else:
            raise TransferFileError(f"Incorrect sha256sum, local: {local_sha256sum}, remote: {remote_sha256sum}")

    def execute_command(
        self,
        command: str,
        *,
        input_data: str = None,
        cwd: str = None,
        timeout: int = 30,
        env: dict = None,
        stderr_to_stdout: bool = False,
        discard_stdout: bool = False,
        discard_stderr: bool = False,
        skip_logging: bool = False,
        expected_return_codes: Optional[Iterable] = frozenset({0}),
        shell: bool = True,
        custom_exception: Type[CalledProcessError] = None,
    ) -> "ConnectionCompletedProcess":
        """
        Run program and wait for it's completion.

        :param command: Command to execute, with all necessary arguments
        :param input_data: Not implemented in SerialConnection
        :param cwd: Not implemented in SerialConnection
        :param timeout: Program execution timeout, in seconds
        :param env: Not implemented in SerialConnection
        :param stderr_to_stdout: Not implemented in SerialConnection, because SerialConnection doesn't have stderr
        :param discard_stdout: Don't capture stdout stream
        :param discard_stderr: Not implemented in SerialConnection, because SerialConnection doesn't have stderr
        :param skip_logging: Skip logging of stdout/stderr if captured
        :param expected_return_codes: Iterable object(eg. list) of expected return codes
        if it's None, in returned Process return code is not available
        :param shell: Not implemented in SerialConnection
        :param custom_exception: Enable us to raise our exception if program exits with an unexpected return code.
        custom_exception must inherit from CalledProcessError to use its fields like returncode, cmd, output, stderr

        :return: Completed process object
        :raises ConnectionCalledProcessError: if program exits with an unexpected return code
        :raises SerialException: if failed to clear commandline before executing command,
                                 if failed to properly execute command
        """
        try:
            completed_process = self._telnet_connection.execute_command(
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
                custom_exception=custom_exception,
            )
        except TelnetException as e:
            raise SerialException("Error when trying to execute command") from e

        return completed_process

    def fire_and_forget(
        self,
        command: str,
    ) -> None:
        """
        Run program but don't wait for its completion, ignoring output and return code.

        :param command: Command to execute, with all necessary arguments

        :raises SerialException: if failed to clear commandline before executing command,
                                 if failed to properly execute command
        """
        try:
            self._telnet_connection.fire_and_forget(command)
        except TelnetException as e:
            raise SerialException("Error when trying to execute command in fire-and-forget mode") from e

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
        raise NotImplementedError("Not implemented in Serial")

    def restart_platform(self) -> None:
        """Reboot host."""
        raise NotImplementedError("Not implemented in Serial")

    def shutdown_platform(self) -> None:
        """Shutdown host."""
        raise NotImplementedError("Not implemented in Serial")

    def wait_for_host(self, timeout: int = 60) -> None:
        """
        Wait for host availability.

        :param timeout: Time to check until fail
        :raises TimeoutError: when timeout is expired
        """
        raise NotImplementedError("Not implemented in Serial")

    @conditional_cache
    def get_os_type(self) -> OSType:
        """Get type of client os."""
        unix_check_command = "uname -a"  # get architecture and os name
        result = self.execute_command(unix_check_command, expected_return_codes=[0, 127])
        if result.return_code:
            logger.log(level=log_levels.MODULE_DEBUG, msg=f"Debug data of os_type method: {result}")
            raise OsNotSupported("Client OS not supported")
        return OSType.POSIX

    @conditional_cache
    def get_os_name(self) -> OSName:
        """Get name of client OS."""
        unix_check_command = "uname -s"
        # get kernel name - consistent with platform.system, which read first part of uname
        result = self.execute_command(unix_check_command, expected_return_codes=[0, 127])
        for os_type in OSName:
            if os_type.value in result.stdout:
                return os_type
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Debug data of os_name method: {result}")
        raise OsNotSupported("Client OS not supported")

    @conditional_cache
    def get_os_bitness(self) -> OSBitness:
        """Get bitness of client os."""
        unix_check_command = "uname -m"  # get machine info
        result = self.execute_command(unix_check_command, expected_return_codes=[0, 127])
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Debug data of os_bitness method: {result.stdout}")
        if "64" in result.stdout:
            return OSBitness.OS_64BIT
        elif "32" in result.stdout or "86" in result.stdout or "armv7l" in result.stdout or "arm" in result.stdout:
            return OSBitness.OS_32BIT
        else:
            raise OsNotSupported(f"Cannot determine OS Bitness for Host: {self._ip}")

    def get_cpu_architecture(self) -> CPUArchitecture:
        """Get CPU architecture."""
        raise NotImplementedError("'get_cpu_architecture' not implemented in Serial")

    def stop_logging(self) -> None:
        """Kill logging in serial movement."""
        if self._serial_logs_path:
            logger.info("Killing tee logging processes on the remote host.")
            for process in self._tee_logging_processes_list:
                try:
                    process.kill()
                except RemoteProcessInvalidState as error:
                    logger.warning(f"Process: {process.pid} has already finished: {error}")

    @property
    def path(self) -> Path:
        """
        Path represents a filesystem path.

        :return: Path object for Connection
        """
        raise NotImplementedError("Not implemented in Serial")

    @clear_system_data_cache
    def disconnect(self) -> None:
        """Stop netcat server on host and disconnect from it."""
        self._server_process.kill()
        self.stop_logging()
        self._remote_host.disconnect()
        logger.log(level=log_levels.MODULE_DEBUG, msg="Stopped netcat server and disconnected from host.")

    def send_key(self, *, key: "SerialKeyCode", count: int = 1, sleeptime: float = 0.5) -> None:
        """
        Send key code via serial.

        :param key: Enum of SerialKeyCode
        :param count: number of sends
        :param sleeptime: sleep between sends
        """
        self._telnet_connection.send_key(key=key, count=count, sleeptime=sleeptime)

    def go_to_option_on_screen(self, *, option: str, send_enter: bool) -> bool:
        """
        Move down on platform screen by pressing down_arrow to find given option.

        :param option: string value of wanted option, can handle a part of name
        :param send_enter: flag, after found option selecting it by pressing enter
        """
        return self._telnet_connection.go_to_option_on_screen(option=option, send_enter=send_enter)

    def wait_for_string(self, *, string_list: List[str], expect_timeout: bool = False, timeout: int = 30) -> int:
        """
        Expect one of strings from list on client.

        :param string_list:  must be list of strings
        :param expect_timeout: is pexpect.TIMEOUT one of expected values
        :param timeout: timeout for pexpect.expect.
        Default value here is 30 seconds because it's default value for pexpect.expect
        :return: which element of the list was found
        """
        return self._telnet_connection.wait_for_string(
            string_list=string_list, expect_timeout=expect_timeout, timeout=timeout
        )

    def get_output_after_user_action(self) -> str:
        """
        Get output from serial, usage: usually after sending key.

        :return: Gathered output
        """
        output = self._telnet_connection.console.read().decode("ASCII", errors="ignore")
        term = Ansiterm(ANSITERM_ROWS_SIZE, ANSITERM_COLS_SIZE)
        term.feed(output)
        output = "\n".join(
            term.get_string(y * ANSITERM_COLS_SIZE, y * ANSITERM_COLS_SIZE + ANSITERM_COLS_SIZE)
            for y in range(ANSITERM_ROWS_SIZE)
        )
        return output

    def get_screen_field_value(self, field_regex: str, group_name: Optional[str]) -> Optional[str]:
        """
        Get value of field using regex.

        :param field_regex: Regex to define field.
        :param group_name: Name of group in regex to return, Optional
        :return: Read value or None if not found.
        """
        output = self.get_output_after_user_action()
        matches = re.search(field_regex, output, re.M)
        if matches:
            if group_name is None:
                return matches.group()
            else:
                return matches.group(group_name)
        else:
            return None
