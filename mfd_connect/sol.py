# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""It's a Connection for Serial over LAN protocol."""

import logging
import platform
import re
import sys
import time
import typing

from mfd_typing.cpu_values import CPUArchitecture
from netaddr import IPAddress
from subprocess import CalledProcessError
from typing import Iterable, List, Type, Optional

import pexpect
import pexpect.popen_spawn
from mfd_typing.os_values import OSName, OSType, OSBitness
from mfd_common_libs import add_logging_level, log_levels, log_func_info

from .util.decorators import conditional_cache
from .util.serial_utils import SerialKeyCode
from .base import Connection, ConnectionCompletedProcess
from .exceptions import SolException, ConnectionCalledProcessError, OsNotSupported
from .pathlib.path import CustomPath, custom_path_factory

if typing.TYPE_CHECKING:
    from pydantic import BaseModel  # from pytest_mfd_config.models.topology import ConnectionModel

logger = logging.getLogger(__name__)
add_logging_level(level_name="MODULE_DEBUG", level_value=log_levels.MODULE_DEBUG)
add_logging_level(level_name="CMD", level_value=log_levels.CMD)
add_logging_level(level_name="OUT", level_value=log_levels.OUT)


class SolConnection(Connection):
    """Handling communication via SOL (Serial Over LAN)."""

    def __init__(
        self,
        username: str,
        password: str,
        ip: str,
        model: "BaseModel | None" = None,
        cache_system_data: bool = True,
    ):
        """
        Class init, preparing variables.

        :param username: Username to login
        :param password: Password to login
        :param ip: Ip where user will login
        :param model: pydantic model of connection
        :param cache_system_data: Flag to cache system data like self._os_type, OS name, OS bitness and CPU architecture
        """
        super().__init__(model=model, cache_system_data=cache_system_data)
        # checking existing of required tool
        self._ipmi_tool_name = "ipmiutil"
        if "Windows" in platform.system():
            raise SolException("Windows is not supported as test controller, yet")
        try:
            pexpect.popen_spawn.PopenSpawn(f"{self._ipmi_tool_name} -h").wait()
        except FileNotFoundError as e:
            logger.log(level=log_levels.MODULE_DEBUG, msg=f"{self._ipmi_tool_name} does not exists in OS")
            raise SolException(e)
        self._username = username
        self._password = password
        self._ip = IPAddress(ip)
        # -F forcing lan type, -V privileges type (4 - admin)
        self._ipmi_parameters = f"-F lan2 -U {self._username} -P {self._password} -N {self._ip} -V 4"
        self._connection_handle = self._establish_connection(retry_count=5)
        self._prompt = [
            "\\\> \\x1b\[0m\\x1b\[37m\\x1b\[40m",  # noqa: W605
            "Shell> \\x1b\[0m\\x1b\[37m\\x1b\[40m",  # noqa: W605
        ]

    def __str__(self):
        return "sol"

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
        :param cwd: Not implemented in SolConnection
        :param shell: flag, if its in efi shell, enabling different flow for EFI Shell and Pre-OS
        :param expected_return_codes: Iterable object(eg. list) of expected return codes
        if it's None, in returned Process return code is not available
        :param env: not implemented in SolConnection
        :param input_data: not implemented in SolConnection
        :param stderr_to_stdout: not implemented in SolConnection, because SolConnection doesn't have stderr
        :param discard_stderr: not implemented in SolConnection, because SolConnection doesn't have stderr
        :param discard_stdout: Don't capture stdout stream
        :param skip_logging: Skip logging of stdout/stderr if captured
        :param custom_exception: Enable us to raise our exception if program exits with an unexpected return code.
        custom_exception must inherit from CalledProcessError to use its fields like returncode, cmd, output, stderr

        :return: Completed process object
        :raises ConnectionCalledProcessError: if program exits with an unexpected return code
        """
        output = ""
        returncode = None

        # Pexpect buffer will be cleared before and after sending command and after getting return code
        self._clear_buffer()

        logger.log(level=log_levels.CMD, msg=f"Executing {self._ip}>'{command}', cwd: {cwd}")

        if shell:
            self._send_to_shell(command, retry_count=5)
            self.wait_for_string(self._prompt, timeout=timeout)
        else:
            self._connection_handle.send(command + "\r")
            self.wait_for_string([], expect_timeout=True, timeout=timeout)
        if not discard_stdout:
            output = self._connection_handle.before.decode("ASCII", errors="ignore")
            output = self._parse_output(output)
            if output and not skip_logging:
                logger.log(level=log_levels.OUT, msg=f"output>>\n{output}")

        self._clear_buffer()

        # return code is available in shell only,
        # gathering return code only if required by user via expected_return_codes field
        if shell and expected_return_codes:
            returncode = self._get_return_code()
            self._clear_buffer()

        if custom_exception and not expected_return_codes:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg=f"Return codes are ignored, passed exception: {custom_exception} will be not raised.",
            )

        # returning process if rc is not required (in efishell or in pre-os) or if this rc is expected
        if returncode is None or returncode in expected_return_codes:
            completed_process = ConnectionCompletedProcess(args=command, stdout=output, return_code=returncode)
            return completed_process
        else:
            if custom_exception:
                raise custom_exception(returncode=returncode, cmd=command, output=output)
            raise ConnectionCalledProcessError(returncode=returncode, cmd=command, output=output)

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
        raise NotImplementedError("Not implemented in SOL")

    def _clear_buffer(self) -> None:
        """Clear pexpect buffer."""
        if self._connection_handle.before:
            self._connection_handle.expect([r".+", pexpect.EOF, pexpect.TIMEOUT], timeout=1)

    def restart_platform(self) -> None:
        """Reboot host."""
        raise NotImplementedError("Restart is not implemented in SOL")

    def shutdown_platform(self) -> None:
        """Shutdown host."""
        raise NotImplementedError("Shutdown is not implemented in SOL")

    def wait_for_host(self, timeout: int = 60) -> None:
        """
        Wait for host availability.

        :param timeout: Time to check until fail
        :raises TimeoutError: when timeout is expired
        """
        raise NotImplementedError("Wait for host is not implemented in SOL")

    def _get_return_code(self) -> int:
        """Check lasterror in UEFI Shell."""
        logger.log(level=log_levels.MODULE_DEBUG, msg="Getting lasterror from EFI Shell")
        cmd_last_error = "set lasterror"
        lasterror_output = self.execute_command(cmd_last_error, expected_return_codes=None).stdout
        lasterror_regex = re.compile("lasterror = (.*)")
        for line in lasterror_output.split("\n"):
            match = lasterror_regex.match(line)
            if match:
                lasterror = match.group(1)
                logger.log(level=log_levels.MODULE_DEBUG, msg=f"return code is: {lasterror}")
                return int(lasterror, 0)
        logger.log(level=log_levels.MODULE_DEBUG, msg="lasterror not found")
        return -1

    def _send_to_shell(self, command: str = "", retry_count: int = 10, reset_communication: bool = False) -> None:
        # clearing buffer
        while self.wait_for_string(self._prompt, expect_timeout=True, timeout=2) < len(self._prompt):
            continue
        cursor_position = 0
        if retry_count == 0 and reset_communication:
            raise SolException(f"Problem while sending '{command}' command")

        # Reset Sol communication and retry sending command
        if retry_count == 0 and not reset_communication:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg="Resetting Sol communication and retrying to send command : {command}",
            )
            self._reset_communication_handle()
            return self._send_to_shell(command=command, retry_count=10, reset_communication=True)

        len_of_command = len(command)
        # code below is here because limited buffer length when sending
        buffer_size = 15
        while cursor_position < len_of_command:
            if (cursor_position + buffer_size) <= len_of_command:
                self._connection_handle.send(command[cursor_position : (cursor_position + buffer_size)])
                time.sleep(0.5)
            else:
                self._connection_handle.send(command[cursor_position:len_of_command])
                time.sleep(0.5)
            cursor_position += buffer_size
        # parsing what we've sent - before [send_enter]
        try:
            block_size_to_read = 5000
            timeout = 5
            read_text = self._connection_handle.read_nonblocking(block_size_to_read, timeout).decode(
                "ASCII", errors="ignore"
            )
        except pexpect.TIMEOUT:  # timeout when there is empty buffer
            read_text = ""
            self.send_key(SerialKeyCode.escape, sleeptime=1)
            self.send_key(SerialKeyCode.enter, sleeptime=1)
        # convert it to human-readable format using _parse_output
        buffer_after_send = self._parse_output(read_text, one_line=True)
        if command in buffer_after_send.split("\n"):
            self.send_key(SerialKeyCode.enter)
        else:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg=f"Sending command '{command}' ends with error! [ESC] x2 & re-trying...",
            )
            self.send_key(SerialKeyCode.escape, count=2, sleeptime=1)
            self.send_key(SerialKeyCode.enter, sleeptime=1)
            # cleaning buffer
            while self.wait_for_string(self._prompt, expect_timeout=True, timeout=1) < len(self._prompt):
                continue
            logger.log(level=log_levels.CMD, msg=f"buffer: {buffer_after_send}")
            logger.log(level=log_levels.CMD, msg=f"command: {command}")
            return self._send_to_shell(
                command=command, retry_count=retry_count - 1, reset_communication=reset_communication
            )

    def _establish_connection(self, retry_count: int = 0) -> "pexpect.spawn":
        logger.log(level=log_levels.MODULE_DEBUG, msg="Establishing SUT control handle via IPMI Serial Over LAN!")

        # clearing old session first
        self._deactivate_sol_session(), "Deactivating sol session failed"

        # establishing new session
        logger.log(level=log_levels.MODULE_DEBUG, msg="Activating new SoL IPMI session...")
        command = f"{self._ipmi_tool_name} sol -a {self._ipmi_parameters}"

        # place for os dependency
        sol_connection_process = pexpect.spawn(command)

        expected_strings = ["SOL session is running", pexpect.TIMEOUT, pexpect.EOF]
        index_of_found_string = sol_connection_process.expect(expected_strings, timeout=10)
        if index_of_found_string != 0:
            if retry_count:
                logger.log(level=log_levels.MODULE_DEBUG, msg="Fatal Error while establishing SoL session! Retrying...")
                self._establish_connection(retry_count - 1)
            else:
                raise SolException(f"SoL sessions activation failure: {sol_connection_process.before}")
        logger.log(level=log_levels.MODULE_DEBUG, msg="...Done!")

        return sol_connection_process

    def _deactivate_sol_session(self) -> None:
        # clearing old session
        logger.log(level=log_levels.MODULE_DEBUG, msg="Clearing/Deactivating previous SoL IPMI session...")
        process = pexpect.popen_spawn.PopenSpawn(f"{self._ipmi_tool_name} sol -d {self._ipmi_parameters}", timeout=60)
        correct_responses = [
            "completed successfully",
            "Invalid Session Handle or Empty Buffer",
        ]
        expect_index = process.expect(correct_responses)
        if expect_index > len(correct_responses) - 1:
            raise SolException(f"Fatal Error while deactivating previous SoL session! \n{process.before}")

    @log_func_info(logger)
    def wait_for_string(self, string_list: List[str], expect_timeout: bool = False, timeout: int = 30) -> int:
        """
        Expect one of strings from list on client.

        :param string_list:  must be list of strings
        :param expect_timeout: is pexpect.TIMEOUT one of expected values
        :param timeout: timeout for pexpect.expect.
        Default value here is 30 seconds because it's default value for pexpect.expect
        :return: which element of the list was found
        """
        try:
            temp_list = string_list[:]
            if expect_timeout:
                temp_list.append(pexpect.TIMEOUT)
            return self._connection_handle.expect(temp_list, timeout=timeout)
        except (pexpect.TIMEOUT, pexpect.EOF) as e:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg=f"Catched wait_for_string exception! timeout: {timeout} seconds: '{temp_list}' not found",
            )
            self._reset_communication_handle()  # cleaning SOL Connection for next tests
            raise SolException(f"wait_for_string exception! '{temp_list}' not found, details:\n {e.value}")

    def _reset_communication_handle(self) -> None:
        """Close pexpect child and re-establish pexpect session."""
        logger.log(level=log_levels.MODULE_DEBUG, msg="Closing pexpect child and re-establishing Sol session")
        if self._connection_handle:
            self._connection_handle = None
        time.sleep(2)  # small timeout before next session
        self._connection_handle = self._establish_connection(retry_count=5)

    def go_to_option_on_screen(self, option: str, send_enter: bool = True) -> bool:
        """
        Move down on platform screen by pressing down_arrow to find given option.

        :param option: string value of wanted option, can handle a part of name
        :param send_enter: flag, after found option selecting it by pressing enter
        """
        last_found_option = None
        self._refresh_first_option()

        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Looking for option: {option}")
        while True:
            selected_option = " ".join(self.get_output_after_user_action(True).splitlines())

            if not selected_option:
                logger.log(
                    level=log_levels.MODULE_DEBUG,
                    msg="Cannot read selected option from screen for continuing option searching...",
                )
                return False

            logger.log(level=log_levels.OUT, msg=f"Current option: {selected_option}")

            if last_found_option == selected_option:
                logger.log(level=log_levels.MODULE_DEBUG, msg=f"Searched option: {option} was not found")
                logger.log(
                    level=log_levels.MODULE_DEBUG,
                    msg=f"Last option: {last_found_option} vs Current option: {selected_option}",
                )
                return False

            last_found_option = selected_option

            if option.casefold() in selected_option.casefold():
                logger.log(
                    level=log_levels.MODULE_DEBUG,
                    msg=f"Searched option: {option} found in mapped options: {selected_option}",
                )
                if send_enter:
                    self.send_key(SerialKeyCode.enter, sleeptime=1)
                return True

            self._clear_buffer()
            self.send_key(SerialKeyCode.down_arrow, sleeptime=1)

    def _refresh_first_option(self) -> None:
        """Refresh option and clear buffer between sending commands."""
        self.send_key(SerialKeyCode.down_arrow, sleeptime=1)
        self.wait_for_string([], expect_timeout=True, timeout=1)
        self._clear_buffer()
        self.send_key(SerialKeyCode.up_arrow, sleeptime=1)

    def get_output_after_user_action(self, selected_option: bool = False) -> str:
        """
        Get output from SOL, usage: usually after sending key.

        :param selected_option: getting selected option from screen
        :return: Gathered output
        """
        self.wait_for_string([], expect_timeout=True, timeout=1)
        output = self._connection_handle.before.decode("ASCII", errors="ignore")
        return self._parse_output(output, selected_option)

    def send_key(self, key: SerialKeyCode, count: int = 1, sleeptime: float = 0.5) -> None:
        """
        Send via sol key of keyboard.

        :param key: Enum of SerialKeyCode
        :param count: number of sends
        :param sleeptime: sleep between sends
        """
        for _ in range(count):
            self._connection_handle.send(key.value)
            time.sleep(sleeptime)

    @staticmethod
    @log_func_info(logger)
    def _parse_output(
        output_to_parse: str, selection: bool = False, legacy: bool = False, one_line: bool = False
    ) -> str:
        """
        Parse output from Serial over LAN.

        :param one_line: enable flow for confirmation of sent command
        :param selection: enable flow for reading selected option
        :param legacy: enable flow for legacy bios mode
        :param output_to_parse - string from console, from handle.before
        :return - string with pre-cleaning, lines separated by new line character
        """
        if output_to_parse == "":
            return output_to_parse
        if not selection:
            return SolConnection._parse(one_line, output_to_parse)
        else:  # selected option
            return SolConnection._parse_selection(legacy, output_to_parse)

    @staticmethod
    def _parse(one_line: bool, output_to_parse: str) -> str:
        """
        Parse output from Serial over LAN.

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
        lines = cleaned_string.split("\r\r\n")
        output_lines = [line for line in lines if "" != line and "'~?' for help.]" not in line]
        # skip _prompt line
        pattern = re.compile(r"FS\d:\\.*")
        if not output_lines:
            return "\n".join(output_lines)
        if "Shell>" in output_lines[-1] or pattern.match(output_lines[-1]):
            output_lines = output_lines[:-1]
        return "\n".join(output_lines)

    @staticmethod
    def _parse_selection(legacy: bool, output_to_parse: str) -> str:
        """
        Parse output from PreOS and get selected option.

        :param legacy: enable flow for legacy bios mode
        :param output_to_parse - string from console, from handle.before
        :return - string with pre-cleaning, lines separated by new line character
        """
        output_lines = []
        entries = ("".join(output_to_parse)).split("\x1b")
        selected_pattern = r"\[44m(.+)"  # color of selected option, blue background
        pattern = re.compile(selected_pattern)
        for elem in entries:
            matched_pattern = pattern.match(elem)
            if matched_pattern:  # BootMenu
                line = matched_pattern.groups()[0]
                if legacy:
                    # Legacy
                    if "*" not in line:
                        output_lines[-1] += " " + line
                    else:
                        output_lines.append(line)
                else:
                    # EFI
                    output_lines.append(line)

        if output_lines:
            return "\n".join(output_lines)

        logger.log(level=log_levels.MODULE_DEBUG, msg="Selected option not found, trying method for GRUB2")
        selected_pattern = r"\[47m"  # color of selected option, grey background
        pattern = re.compile(selected_pattern)
        for i, elem in enumerate(entries):
            matched_pattern = pattern.match(elem)
            if matched_pattern:
                # next line could be selected option
                if i + 1 < len(entries):
                    if "*" in entries[i + 1]:
                        output_lines.append(entries[i + 1])
        return "\n".join(output_lines)

    def _check_if_unix(self) -> bool:
        """Check if Unix is the client OS."""
        unix_check_command = "uname -a"
        try:
            result = self.execute_command(unix_check_command, expected_return_codes=[0, 127])
            return not result.return_code
        except ConnectionCalledProcessError:
            return False

    def _get_unix_distribution(self) -> OSName:
        """Check distribution of connected Unix OS."""
        unix_check_command = "uname -o"
        result = self.execute_command(unix_check_command, expected_return_codes=[0, 127])
        for os in OSName:
            if os.value in result.stdout:
                return os
        raise OsNotSupported("Client OS not supported")

    def _check_if_efi_shell(self) -> bool:
        """Check if EFI shell is the client OS."""
        efi_shell_check_command = "ver"
        output = self.execute_command(
            efi_shell_check_command, shell=False, expected_return_codes=None, timeout=5
        ).stdout
        return any(out in output for out in ["UEFI Shell", "UEFI Interactive Shell"])

    @conditional_cache
    def get_os_type(self) -> OSType:
        """Get type of client OS."""
        if self._check_if_unix():
            return OSType.POSIX

        if self._check_if_efi_shell():
            return OSType.EFISHELL

        raise OsNotSupported("Client OS not supported")

    @conditional_cache
    def get_os_name(self) -> OSName:
        """Get name of client OS."""
        if self._check_if_efi_shell():
            return OSName.EFISHELL

        if self._check_if_unix():
            return self._get_unix_distribution()

        raise OsNotSupported("Client OS not supported")

    @conditional_cache
    def get_os_bitness(self) -> OSBitness:
        """Get bitness of client os."""
        if self._check_if_efi_shell():
            return OSBitness.OS_64BIT  # current requirements describe only required EFISHELL
        raise OsNotSupported("Client OS is not supported")

    @conditional_cache
    def get_cpu_architecture(self) -> CPUArchitecture:
        """Get CPU architecture."""
        if self._check_if_efi_shell():
            return CPUArchitecture.X86_64
        raise OsNotSupported("'get_cpu_architecture' not supported on that OS")

    def path(self, *args, **kwargs) -> CustomPath:
        """Path represents a filesystem path."""
        if sys.version_info >= (3, 12):
            kwargs["owner"] = self
            return custom_path_factory(*args, **kwargs)

        return CustomPath(*args, owner=self, **kwargs)

    def get_cwd(self) -> str:
        """
        Get current working directory.

        :raises SolException: if cwd is unavailable
        """
        logger.log(level=log_levels.MODULE_DEBUG, msg="Getting current working directory.")
        output = self.execute_command("set").stdout
        match = re.findall(r"cwd = (.*)", output)
        if match:
            return match[0]

        msg = "Could not get current working directory."
        logger.log(level=log_levels.MODULE_DEBUG, msg=msg)
        raise SolException(msg)

    def disconnect(self) -> None:
        """Close connection with client. Not required for SOL."""
        logger.log(level=log_levels.MODULE_DEBUG, msg="Disconnect is not required for SOL connection.")

    @property
    def ip(self) -> IPAddress:
        """IP address to which the connection is established."""
        return self._ip
