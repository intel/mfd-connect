# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for TelnetConnection class."""

import logging
import re
import time
import typing
from subprocess import CalledProcessError

from mfd_typing.cpu_values import CPUArchitecture
from netaddr import IPAddress
from typing import Union, Optional, Type, Iterable, List

from mfd_connect.util import EFI_SHELL_PROMPT_REGEX, UNIX_PROMPT_REGEX, SerialKeyCode
from mfd_connect.exceptions import ConnectionCalledProcessError, OsNotSupported
from mfd_typing.os_values import OSName, OSType, OSBitness
from ..pathlib.path import CustomPath

from ..base import Connection, ConnectionCompletedProcess
from ..exceptions import TelnetException
from .telnet_console import TelnetConsole

from mfd_common_libs import add_logging_level, log_levels, log_func_info
from mfd_connect.util import ansiterm
from ..util.console_utils import BLACK_BACKGROUND_COLOR, ANSITERM_COLS_SIZE, ANSITERM_ROWS_SIZE

if typing.TYPE_CHECKING:
    from pydantic import BaseModel  # from pytest_mfd_config.models.topology import ConnectionModel

logger = logging.getLogger(__name__)
add_logging_level(level_name="MODULE_DEBUG", level_value=log_levels.MODULE_DEBUG)
add_logging_level(level_name="CMD", level_value=log_levels.CMD)
add_logging_level(level_name="OUT", level_value=log_levels.OUT)


class TelnetConnection(Connection):
    """Class handling communication through Telnet protocol."""

    _TELNET_BROKE_ERRORS = (EOFError, OSError, BrokenPipeError, ConnectionResetError, AttributeError)

    def __init__(
        self,
        ip: str,
        *,
        port: int,
        username: str,
        password: str,
        login_prompt: str = "login: ",
        password_prompt: str = "Password: ",
        prompt_regex: str = UNIX_PROMPT_REGEX,
        execution_retries: int = 2,
        retry_cooldown: int = 2,
        buffer_size: int | None = None,
        login_timeout: int = 15,
        is_veloce: bool = False,
        model: "BaseModel | None" = None,
    ):
        """
        Initialise class.

        :param ip: IP address of host
        :param port: Port for telnet connection
        :param username: Username to login
        :param password: Password to login
        :param login_prompt: Prompt appearing when asking for username during login
        :param password_prompt: Prompt appearing when asking for password during login
        :param prompt_regex: Regex for prompt appearing after logging in, determine whether SUT is booted to UEFI or OS
        :param execution_retries: Number of times executing of commands will be retried in case of dropped connection
        :param retry_cooldown: Cooldown before retrying to get return code
        :param buffer_size: Size of line buffer when executing commands
        :param login_timeout: Timeout used when waiting for login/password prompt and after-credentials prompt to appear
        :param is_veloce: Set to True if connecting to Veloce setups (increases timeout values for executing commands)
        :param model: pydantic model of connection
        """
        super().__init__(model)
        self._ip = IPAddress(ip)
        self._username = username
        self._password = password
        self._login_prompt = login_prompt
        self._password_prompt = password_prompt
        self._port = port
        self._prompt = prompt_regex
        self._execution_retries = execution_retries
        self._retry_cooldown = retry_cooldown
        if buffer_size is None:
            self._buffer_size = 256 if is_veloce else 2048
        self._login_timeout = login_timeout
        self._is_veloce = is_veloce
        self._establish_telnet_connection()

    def __str__(self):
        return "telnet"

    def _in_pre_os(self) -> bool:
        return self._prompt == EFI_SHELL_PROMPT_REGEX

    def _establish_telnet_connection(self) -> None:
        """
        Establish connection with telnet, check if connected and then login to console.

        :raises TelnetException: if encountered unexpected exception when connecting,
                                 if connection was not established after retrying
        """
        for attempt in range(self._execution_retries):
            try:
                logger.log(level=log_levels.MODULE_DEBUG, msg="Trying to connect to target...")
                self._connect()
                if self.console.is_connected():
                    if not self._in_pre_os() and (self._username and self._password is not None):
                        logger.log(level=log_levels.MODULE_DEBUG, msg="Trying to login to console...")
                        self._login()
                        return
                    else:
                        logger.log(
                            level=log_levels.MODULE_DEBUG, msg="Credentials weren't provided. Skipping login part"
                        )
                        return
            except self._TELNET_BROKE_ERRORS:
                logger.log(
                    level=log_levels.MODULE_DEBUG,
                    msg="Telnet connection is broken - reconnecting and retrying to login",
                )
            except Exception as e:
                raise TelnetException("Error when trying to establish Telnet connection") from e
        else:
            raise TelnetException(
                f"Could not establish telnet connection to target after {self._execution_retries} retries"
            )

    def _connect(self) -> None:
        """Create connection for telnet console."""
        try:
            self.console = TelnetConsole(ip=str(self._ip), port=self._port)
            logger.log(level=log_levels.MODULE_DEBUG, msg="Console connection created")

        except ConnectionRefusedError:
            # This might happen if there was other problem than dropped connection - that's fine
            logger.log(level=log_levels.MODULE_DEBUG, msg="Telnet connection is refused - already connected?")

    def _login(self) -> None:
        """
        Login to telnet console.

        :raises TelnetException: if could not login to console after retrying
        """
        for attempt in range(self._execution_retries):
            try:
                self._enter_credentials()
                return
            except self._TELNET_BROKE_ERRORS as e:
                logger.log(
                    level=log_levels.MODULE_DEBUG,
                    msg=f"Telnet connection is broken - reconnecting and retrying to login (exception type: {type(e)})",
                )
                self._connect()
        else:
            raise TelnetException(f"Could not login to console after {self._execution_retries} retries")

    def _enter_credentials(self) -> None:
        """
        Enter credentials to console prompt.

        :raises ConnectionResetError: if failed to enter credentials successfully
        """
        logger.log(level=log_levels.MODULE_DEBUG, msg="Writing newline to prompt")
        prompt_pattern_list = [self._login_prompt.encode(), self._prompt.encode()]
        self.console.write()
        logger.log(
            level=log_levels.MODULE_DEBUG,
            msg=f"Waiting for login prompt, {prompt_pattern_list}",
        )

        time.sleep(1)
        pattern_index, match, output = self.console.expect(prompt_pattern_list, self._login_timeout)
        is_login_prompt_found = pattern_index != -1
        is_already_logged_in = pattern_index == 1
        if not is_login_prompt_found:
            raise ConnectionResetError("Login prompt not found")
        logger.log(
            level=log_levels.MODULE_DEBUG,
            msg=f"Found {prompt_pattern_list[pattern_index]} pattern, read from console: {output}",
        )
        if is_already_logged_in:
            return
        logger.log(level=log_levels.MODULE_DEBUG, msg="Writing username to prompt")
        self.console.write(self._username)

        if self._password is not None:
            logger.log(level=log_levels.MODULE_DEBUG, msg="Waiting for password prompt")
            pattern_index, match, output = self.console.expect([self._password_prompt.encode()], self._login_timeout)
            is_password_prompt_found = pattern_index != -1
            if not is_password_prompt_found:
                logger.log(level=log_levels.MODULE_DEBUG, msg="Password prompt not found, expecting command prompt")
                self.console.write(b"\n")
            else:
                logger.log(level=log_levels.MODULE_DEBUG, msg="Writing password to prompt")
                self.console.write(self._password)

        logger.log(level=log_levels.MODULE_DEBUG, msg="Waiting for prompt")
        pattern_index, match, output = self.console.expect([self._prompt.encode()], self._login_timeout)
        is_prompt_found = pattern_index != -1
        if not is_prompt_found:
            raise ConnectionResetError("Prompt not found after entering credentials")
        logger.log(level=log_levels.MODULE_DEBUG, msg="Prompt found")

    def _clear_cmdline(self) -> None:
        """Clear commandline and wait for prompt."""
        if not self._in_pre_os():
            flush_buffers_timeout = 3 if self._is_veloce else 0.5
            self.console.write("\x03")  # ^C to make sure we are not stuck at cmdline
            self.console.write("\x15")  # ^U to clear the line before cursor
            self.console.write("\x0c")  # ^L to rewrite the line for sanity
            self.console.flush_buffers(timeout=flush_buffers_timeout)  # flush buffers, cooldown for prompt to appear
        else:
            logger.log(level=log_levels.MODULE_DEBUG, msg="Nothing to clear on UEFI Shell console.")

    def _prepare_cmdline(self) -> None:
        """Try to clear commandline and reconnect to serial if telnet connection broke."""
        for i in range(1, self._execution_retries + 1):
            try:
                logger.log(
                    level=log_levels.MODULE_DEBUG,
                    msg="Clearing console",
                )
                self._clear_cmdline()
                break
            except self._TELNET_BROKE_ERRORS:
                logger.log(
                    level=log_levels.MODULE_DEBUG,
                    msg=f"Telnet broke while clearing cmdline - {self._execution_retries - i} reconnection tries left",
                )
                self._connect()
        else:
            raise TelnetException("Reached retries count for clearing commandline, telnet connection is breaking")

    def _write_to_console(  # noqa: C901
        self,
        command: Union[str, bytes],
        *,
        timeout: float,
        fire_and_forget: bool = False,
        execution_retries: Optional[int] = None,
        send_key: bool = False,
    ) -> Optional[str]:
        """
        Write command to console, wait for timeout duration and handle exceptions if allowed.

        :param command: Command to be written to console
        :param timeout: Timeout for expecting prompt to reappear
        :param fire_and_forget: Execute command and ignore any output or return code from it
        :param execution_retries: How many times executing the command will be retried
        :param send_key: Flag to control buffer for sending key
        :return: Output from command or None if fire_and_forget set to True
        :raises TelnetException: if could not execute command after retrying
        """

        def _handle_telnet_broke_error(exception: Exception) -> str:
            """
            Retry executing the command when expected exception has been raised.

            :param exception: Exception which has been raised
            :return: Output from retried command execution
            """
            if not execution_retries:
                raise TelnetException("Reached retries count, command was not executed")
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg=f"Telnet broke - {type(exception)} - {execution_retries} reconnection tries left",
            )
            self._connect()
            return self._write_to_console(
                command, timeout=timeout, execution_retries=execution_retries - 1, send_key=send_key
            )

        if execution_retries is None:
            execution_retries = self._execution_retries

        if isinstance(command, str):
            command = command.encode()

        for i in range(0, len(command), self._buffer_size):
            try:
                end = b"\r" if self._in_pre_os() else b"\n"
                if send_key is True:  # sending keys not require enter press
                    end = b""
                self.console.write(buffer=command[i : i + self._buffer_size], end=end)
            except self._TELNET_BROKE_ERRORS as e:
                # before command is triggered it's safe to retry it after reconnecting
                return _handle_telnet_broke_error(e)

        sleep_time = 1 if self._is_veloce else 0.5
        time.sleep(sleep_time)

        if fire_and_forget:
            return

        try:
            pattern_index, match, output = self.console.expect([self._prompt.encode()], timeout)
            # output = self.console.telnet.read_very_eager()
        except self._TELNET_BROKE_ERRORS as e:
            # command is already triggered, it might be risky to retry execution of some
            # instructions, so we allow to disable this feature
            return _handle_telnet_broke_error(e)

        return output.decode()

    def _check_if_unix(self) -> bool:
        """Check if Unix is the client OS."""
        unix_check_command = "uname -a"
        try:
            result = self.execute_command(unix_check_command, expected_return_codes=[0, 127])
            is_unix = not result.return_code
            if is_unix:
                self._prompt = UNIX_PROMPT_REGEX
            return is_unix
        except ConnectionCalledProcessError:
            return False

    def _check_if_efi_shell(self) -> bool:
        """Check if EFI shell is the client OS."""
        efi_shell_check_command = "ver"
        output = self.execute_command(
            efi_shell_check_command, shell=False, expected_return_codes=None, timeout=5
        ).stdout
        return "UEFI Shell" in output

    def _get_unix_distribution(self) -> OSName:
        """Check distribution of connected Unix OS."""
        unix_check_command = "uname -o"
        result = self.execute_command(unix_check_command, expected_return_codes=[0, 127])
        for os in OSName:
            if os.value in result.stdout:
                return os
        raise OsNotSupported("Client OS not supported")

    def _get_return_code(self, timeout: int = 20) -> int:
        """
        Check return code of last executed command.

        :param timeout: Timeout for executing return code check command
        :return: Parsed return code
        :raises TelnetException: if could not retrieve return code
        """
        if self._in_pre_os():
            logger.log(level=log_levels.MODULE_DEBUG, msg="Getting lasterror from EFI Shell")
            cmd_last_error = "set lasterror"
            lasterror_output = self._write_to_console(command=cmd_last_error, timeout=timeout)

            lasterror_output = self._parse_uefi_shell_output(one_line=True, output_to_parse=lasterror_output)
            lasterror_regex = re.compile("lasterror = (.*)")
            for line in lasterror_output.split("\n"):
                match = lasterror_regex.match(line)
                if match:
                    lasterror = match.group(1)
                    logger.log(level=log_levels.MODULE_DEBUG, msg=f"return code is: {lasterror}")
                    return int(lasterror, 0)
            logger.log(level=log_levels.MODULE_DEBUG, msg="lasterror not found")
            return -1

        else:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg="Retrieving last return code",
            )
            for i in range(0, self._execution_retries + 1):
                output = self._write_to_console("echo $?", timeout=timeout)
                rc_pattern = r"^(?P<return_code>-?\d+)$"
                stripped_output = "".join([f"{line.strip()}\n" for line in output.splitlines()])
                match = re.search(pattern=rc_pattern, string=stripped_output, flags=re.MULTILINE)
                if match:
                    return_code = int(match.group("return_code"))
                    break
                else:
                    logger.log(level=log_levels.MODULE_DEBUG, msg="Cannot find return code in output")
                    time.sleep(self._retry_cooldown)
                    logger.log(
                        level=log_levels.OUT,
                        msg=f"Output from return code command: {output}",
                    )
                    logger.log(
                        level=log_levels.MODULE_DEBUG,
                        msg=f"Failed to retrieve last failed return code - {self._execution_retries - i - 1} "
                        f"tries left",
                    )
            else:
                if not output:
                    raise TelnetException(
                        "Missing output - check if there is "
                        "any established connection to serial device e.g. through `minicom` or `screen`"
                    )
                else:
                    raise TelnetException(f"Could not retrieve return code from output - {output}")

            return return_code

    @staticmethod
    @log_func_info(logger)
    def _parse_output(output_to_parse: str, selection: bool = False, one_line: bool = False) -> str:
        """
        Parse output from Serial.

        :param one_line: enable flow for confirmation of sent command
        :param selection: enable flow for reading selected option
        :param output_to_parse - string from console, from handle.before
        :return - string with pre-cleaning, lines separated by new line character
        """
        if output_to_parse == "":
            return output_to_parse
        if not selection:
            return TelnetConnection._parse_uefi_shell_output(one_line, output_to_parse)
        else:  # selected option
            return TelnetConnection._parse_selection(output_to_parse)

    @staticmethod
    def _parse_uefi_shell_output(one_line: bool, output_to_parse: str) -> str:
        """
        Parse output from Serial.

        :param one_line: enable flow for confirmation of sent command
        :param output_to_parse - string from console, from handle.before
        :return - string with pre-cleaning, lines separated by new line character
        """
        cleaned_string = ""
        command_started = False
        for _char in output_to_parse:
            if _char == "\x1b":
                command_started = True
            if command_started:
                if _char == "\x48" or _char == "\x6d":
                    command_started = False
            else:
                cleaned_string += _char
        if one_line:
            return cleaned_string
        lines = cleaned_string.split("\r\n")
        output_lines = [line for line in lines if "" != line and "'~?' for help.]" not in line]
        # skip _prompt line
        pattern = re.compile(r"FS\d:\\.*")
        if not output_lines:
            return "\n".join(output_lines)
        if "Shell>" in output_lines[-1] or pattern.match(output_lines[-1]):
            output_lines = output_lines[:-1]
        return "\n".join(output_lines)

    @staticmethod
    def _parse_selection(output_to_parse: str) -> str:
        """
        Parse output from PreOS and get selected option.

        :param output_to_parse - string from console, from handle.before
        :return - string with pre-cleaning, lines separated by new line character
        """
        background_colors = [BLACK_BACKGROUND_COLOR]
        term = ansiterm.Ansiterm(ANSITERM_ROWS_SIZE, ANSITERM_COLS_SIZE)
        term.feed(output_to_parse)
        selected_lines = ""
        start = 0
        for y in range(ANSITERM_ROWS_SIZE):
            color_old = ""
            for tile in term.get_tiles(y * ANSITERM_COLS_SIZE, y * ANSITERM_COLS_SIZE + ANSITERM_COLS_SIZE):
                color_new = tile.color
                if color_new != color_old:
                    if start:
                        #  Looking for first selected lines in output
                        logger.log(
                            level=log_levels.MODULE_DEBUG,
                            msg=f"Selected options: {selected_lines}",
                        )
                        return selected_lines
                if color_new.get("bg") in background_colors and (tile.glyph != " " or start):
                    start = 1
                    selected_lines += tile.glyph
                color_old = color_new
        if not selected_lines:
            raise TelnetException("Cannot find any selected line in provided output...")
        logger.log(
            level=log_levels.MODULE_DEBUG,
            msg=f"Found selected options: {selected_lines}",
        )
        return selected_lines

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
        :param timeout: Program execution timeout, in seconds
        :param cwd: Not implemented in TelnetConnection
        :param shell: Not implemented in TelnetConnection
        :param expected_return_codes: Iterable object(eg. list) of expected return codes
        if it's None, in returned Process return code is not available
        :param env: Not implemented in TelnetConnection
        :param input_data: Not implemented in TelnetConnection
        :param stderr_to_stdout: Not implemented in TelnetConnection, because TelnetConnection doesn't have stderr
        :param discard_stderr: Not implemented in TelnetConnection, because TelnetConnection doesn't have stderr
        :param discard_stdout: Don't capture stdout stream
        :param skip_logging: Skip logging of stdout/stderr if captured
        :param custom_exception: Enable us to raise our exception if program exits with an unexpected return code.
        custom_exception must inherit from CalledProcessError to use its fields like returncode, cmd, output, stderr

        :return: Completed process object
        :raises ConnectionCalledProcessError: if program exits with an unexpected return code
        :raises TelnetException: if failed to clear commandline before executing command,
                                 if failed to properly execute command
        """
        self._prepare_cmdline()

        logger.log(level=log_levels.CMD, msg=f"Executing >{self._ip}> '{command}', cwd: {cwd}")
        output = self._write_to_console(command, timeout=timeout)

        return_code = self._get_return_code(timeout=timeout)

        logger.log(
            level=log_levels.MODULE_DEBUG,
            msg=f"Finished executing '{command}', rc={return_code}",
        )
        if self._in_pre_os():
            output = self._parse_uefi_shell_output(one_line=True, output_to_parse=output)

        if not discard_stdout:
            output = output[output.find("\n") + 1 :]  # remove command from output
            output = output[: output.rfind("\n")]  # remove prompt from end of command output
            if not skip_logging:
                logger.log(level=log_levels.OUT, msg=f"output>>\n{output}")
        else:
            output = ""

        if custom_exception and not expected_return_codes:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg=f"Return codes are ignored, passed exception: {custom_exception} will be not raised.",
            )

        if not expected_return_codes or return_code in expected_return_codes:
            completed_process = ConnectionCompletedProcess(args=command, stdout=output, return_code=return_code)
            return completed_process
        else:
            if custom_exception:
                raise custom_exception(returncode=return_code, cmd=command, output=output)
            raise ConnectionCalledProcessError(returncode=return_code, cmd=command, output=output)

    def fire_and_forget(
        self,
        command: str,
    ) -> None:
        """
        Run program but don't wait for its completion, ignoring output and return code.

        :param command: Command to execute, with all necessary arguments

        :raises TelnetException: if failed to clear commandline before executing command,
                                 if failed to properly execute command
        """
        self._prepare_cmdline()

        logger.log(level=log_levels.CMD, msg=f"Executing '{command}'")
        self._write_to_console(command, timeout=0, fire_and_forget=True)
        logger.log(
            level=log_levels.MODULE_DEBUG,
            msg=f"Command '{command}' executed in fire-and-forget mode.",
        )

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
        raise NotImplementedError("Not implemented in Telnet")

    def restart_platform(self) -> None:
        """Reboot host."""
        raise NotImplementedError("Not implemented in Telnet")

    def shutdown_platform(self) -> None:
        """Shutdown host."""
        raise NotImplementedError("Not implemented in Telnet")

    def wait_for_host(self, timeout: int = 60) -> None:
        """
        Wait for host availability.

        :param timeout: Time to check until fail
        :raises TimeoutError: when timeout is expired
        """
        raise NotImplementedError("Not implemented in Telnet")

    def get_os_type(self) -> OSType:
        """Get type of client os."""
        if self._check_if_unix():
            return OSType.POSIX

        if self._check_if_efi_shell():
            return OSType.EFISHELL

        raise OsNotSupported("Client OS not supported")

    def get_os_name(self) -> OSName:
        """Get name of client OS."""
        if self._check_if_efi_shell():
            return OSName.EFISHELL

        if self._check_if_unix():
            return self._get_unix_distribution()

        raise OsNotSupported("Client OS not supported")

    def get_os_bitness(self) -> OSBitness:
        """Get bitness of client os."""
        self._os_type = self.get_os_type()
        if self._os_type == OSType.WINDOWS:
            windows_check_command = (
                "Get-WmiObject -Class Win32_OperatingSystem | Select-Object -Property OSArchitecture"
            )
            command = windows_check_command.replace('"', '\\"')
            command = f'powershell.exe -OutPutFormat Text -nologo -noninteractive "{command}"'
            result = self.execute_command(command, shell=False, expected_return_codes=[0, 1, 127])
        elif self._os_type == OSType.POSIX:
            unix_check_command = "uname -m"  # get machine info
            result = self.execute_command(unix_check_command, expected_return_codes=[0, 127])
        else:  # must be EFI shell
            raise OsNotSupported("Cannot determine OS Bitness for EFI Shell.")
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Debug data of os_bitness method: {result.stdout}")
        if "64" in result.stdout:
            return OSBitness.OS_64BIT
        elif "32" in result.stdout or "86" in result.stdout or "armv7l" in result.stdout or "arm" in result.stdout:
            return OSBitness.OS_32BIT
        else:
            raise OsNotSupported(f"Cannot determine OS Bitness for Host: {self._ip}")

    def get_cpu_architecture(self) -> CPUArchitecture:
        """Get CPU architecture of Host."""
        raise NotImplementedError("get_cpu_architecture is not implemented in Telnet")

    def path(self, *args, **kwargs) -> CustomPath:
        """Path represents a filesystem path."""
        return CustomPath(*args, owner=self, **kwargs)

    def disconnect(self) -> None:
        """Close connection with client. Not required for Telnet."""
        logger.log(level=log_levels.MODULE_DEBUG, msg="Disconnect is not required for Telnet connection.")

    def go_to_option_on_screen(self, *, option: str, send_enter: bool = True) -> bool:
        """
        Move down on platform screen by pressing down_arrow to find given option.

        :param option: string value of wanted option, can handle a part of name
        :param send_enter: flag, after found option selecting it by pressing enter
        """
        last_found_option = None

        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Looking for option: {option}")

        # Refresh value on the first bios option
        self.send_key(key=SerialKeyCode.down_arrow, sleeptime=1)
        self.send_key(key=SerialKeyCode.up_arrow, sleeptime=1)

        while True:
            option_list = self.get_output_after_user_action(selected_option=True).split("\n")

            if not option_list[-1]:
                logger.log(
                    level=log_levels.MODULE_DEBUG,
                    msg="Cannot read selected option from screen for continuing option searching...",
                )
                return False

            logger.log(level=log_levels.OUT, msg=f"Current option: {option_list[-1]}")

            if last_found_option == option_list[-1]:
                logger.log(level=log_levels.MODULE_DEBUG, msg=f"Searched option: {option} was not found")
                logger.log(
                    level=log_levels.MODULE_DEBUG,
                    msg=f"Last option: {last_found_option} vs Current option: {option_list[-1]}",
                )
                return False

            last_found_option = option_list[-1]

            if option in last_found_option:
                logger.log(
                    level=log_levels.MODULE_DEBUG,
                    msg=f"Searched option: {option} found in mapped options: {last_found_option}",
                )
                if send_enter:
                    self.send_key(key=SerialKeyCode.enter, sleeptime=1)
                return True

            self.send_key(key=SerialKeyCode.down_arrow, sleeptime=1)

    def send_key(self, *, key: SerialKeyCode, count: int = 1, sleeptime: float = 0.5) -> None:
        """
        Send key code via serial.

        :param key: Enum of SerialKeyCode
        :param count: number of sends
        :param sleeptime: sleep between sends
        """
        for _ in range(count):
            self._write_to_console(command=key.value, timeout=sleeptime, fire_and_forget=True, send_key=True)
            time.sleep(sleeptime)

    def get_output_after_user_action(self, *, selected_option: bool = False) -> str:
        """
        Get output from Serial, usage: usually after sending key.

        :param selected_option: getting selected option from screen
        :return: Gathered output
        """
        output = self.console.read().decode("ASCII", errors="ignore")
        return self._parse_output(output, selected_option)

    @log_func_info(logger)
    def wait_for_string(self, *, string_list: List[str], expect_timeout: bool = False, timeout: int = 30) -> int:
        """
        Expect one of strings from list on client.

        :param string_list:  must be list of strings
        :param expect_timeout: is TIMEOUT one of expected values
        :param timeout: timeout for telnet.console.expect.
        Default value here is 30 seconds because it's default value for expect
        :return: which element of the list was found
        """
        pattern_list = [list_elem.encode() for list_elem in string_list]
        try:
            pattern_index, _, text = self.console.expect(pattern_list=pattern_list, timeout=timeout)
            found = pattern_index != -1
            if not found and not expect_timeout:
                details = f"\nRaw data:{text}" if text else ""
                msg = f"Timeout exceeded{details}"
                raise TimeoutError(msg)
            return pattern_index
        except (EOFError, TimeoutError) as e:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg=f"Caught wait_for_string exception! timeout: {timeout} seconds: '{pattern_list}' not found",
            )
            raise TelnetException(f"wait_for_string exception! '{pattern_list}' not found, details:\n{e}")
