# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Package for winrm connection."""

import codecs
import logging
import re
import shlex
import sys
import typing
from subprocess import CalledProcessError
from typing import Optional, Iterable, Type, Tuple

import requests  # from pywinrm
from mfd_common_libs import log_levels, add_logging_level
from mfd_typing import OSBitness, OSType, OSName
from mfd_typing.cpu_values import CPUArchitecture
from winrm import Protocol
from winrm.exceptions import WinRMTransportError, WinRMOperationTimeoutError, InvalidCredentialsError

from mfd_connect.base import ConnectionCompletedProcess, AsyncConnection
from mfd_connect.exceptions import (
    ConnectionCalledProcessError,
    OsNotSupported,
    WinRMException,
    CPUArchitectureNotSupported,
)
from mfd_connect.pathlib.path import CustomPath, custom_path_factory
from mfd_connect.process.winrm.base import WinRmProcess
from mfd_connect.util.decorators import conditional_cache, clear_system_data_cache

if typing.TYPE_CHECKING:
    from mfd_connect.process import RemoteProcess
    from ipaddress import IPv4Address

urllib3_logger = logging.getLogger("urllib3")
spnego_logger = logging.getLogger("spnego")
urllib3_logger.setLevel(logging.CRITICAL)
spnego_logger.setLevel(logging.CRITICAL)

logger = logging.getLogger(__name__)

add_logging_level(level_name="MODULE_DEBUG", level_value=log_levels.MODULE_DEBUG)
add_logging_level(level_name="CMD", level_value=log_levels.CMD)


class WinRmConnection(AsyncConnection):
    """Class for WinRM connection."""

    def start_processes(  # noqa D102
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
    ) -> list["RemoteProcess"]:
        raise NotImplementedError

    def __init__(
        self,
        ip: "IPv4Address | str",
        username: str,
        password: str,
        cache_system_data: bool = True,
        cert_pem: str | None = None,
        cert_key_pem: str | None = None,
    ) -> None:
        """
        Initialize WinRM connection.

        Create shell on the remote machine using Windows Remote Management protocol.

        :param ip: IP address of machine
        :param username: Username for connection
        :param password: Password for connection, optional for using key, pass None for no password
        :param cache_system_data: Flag to cache system data like self._os_type, OS name, OS bitness and CPU architecture
        :param cert_pem: Path to certificate in PEM format, optional
        :param cert_key_pem: Path to certificate key in PEM format, optional
        """
        super().__init__(ip=ip, cache_system_data=cache_system_data)
        self.username = username
        self.password = password
        self._server = None
        self._shell_id = None
        self._cert_pem = cert_pem
        self._cert_key_pem = cert_key_pem

        self._connect()
        self.log_connected_host_info()

    def _connect(self) -> None:
        """Prepare connection using provided credentials."""
        try:
            self._server = Protocol(
                endpoint=f"https://{self.ip}:5986/wsman",
                username=self.username,
                password=self.password,
                transport="ntlm",
                server_cert_validation="ignore" if not self._cert_pem else "validate",
                proxy=None,
                cert_pem=self._cert_pem,
                cert_key_pem=self._cert_key_pem,
            )
            self._shell_id = str(self._server.open_shell())

        except (
            WinRMTransportError,
            WinRMOperationTimeoutError,
            InvalidCredentialsError,
            requests.exceptions.ConnectionError,
            Exception,
        ) as e:
            raise WinRMException("Found exception during connection to server") from e

    def execute_command(
        self,
        command: str,
        *,
        input_data: Optional[str] = None,
        cwd: Optional[str] = None,
        timeout: Optional[int] = None,
        env: Optional[dict] = None,
        stderr_to_stdout: bool = False,
        discard_stdout: bool = False,
        discard_stderr: bool = False,
        skip_logging: bool = False,
        expected_return_codes: Optional[Iterable] = frozenset({0}),
        shell: bool = False,
        custom_exception: Type[CalledProcessError] = None,
    ) -> ConnectionCompletedProcess:
        """
        Send command on the remote host via WinRM protocol.

        Not functional for WinRM:
        input_data
        cwd
        timeout
        env
        discard_stdout
        discard_stderr
        shell

        :param command: Command to execute.
        :param stderr_to_stdout: Redirect stderr to stdout, ignored if discard_stderr is set to True
        :param skip_logging: Skip logging of stdout/stderr if captured
        :param expected_return_codes: Return codes to be considered acceptable.
                                      If None - any return code is considered acceptable
        :param custom_exception: Enable us to raise our exception if program exits with an unexpected return code.
        custom_exception must inherit from CalledProcessError to use its fields like returncode, cmd, output, stderr

        :return: stdout and stderr from command execution
        """
        logger.log(level=log_levels.CMD, msg=f"Executing >{self.ip}> '{command}'")
        stdout_bytes, stderr_bytes, return_code = self._execute_command(command)
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Finished executing '{command}' ")

        stdout, stderr = None, None

        new_line_pattern = b"(\r\n|\r)"

        if stdout_bytes is not None:
            stdout_bytes = re.sub(new_line_pattern, b"\n", stdout_bytes)
            stdout = codecs.decode(stdout_bytes, encoding="utf-8", errors="backslashreplace")
            if stdout and not skip_logging:
                logger.log(level=log_levels.OUT, msg=f"output:\nstdout>>\n{stdout}")

        if stderr_bytes is not None:
            stderr_bytes = re.sub(new_line_pattern, b"\n", stderr_bytes)
            stderr = codecs.decode(stderr_bytes, encoding="utf-8", errors="backslashreplace")
            if stderr and not skip_logging:
                logger.log(level=log_levels.OUT, msg=f"stderr>>\n{stderr}")

        if stderr_to_stdout:
            stdout += stderr
            stderr = None

        if custom_exception and not expected_return_codes:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg=f"Return codes are ignored, passed exception: {custom_exception} will be not raised.",
            )
        if not expected_return_codes or return_code in expected_return_codes:
            return ConnectionCompletedProcess(args=command, stdout=stdout, return_code=return_code, stderr=stderr)
        else:
            if custom_exception:
                raise custom_exception(returncode=return_code, cmd=command, output=stdout, stderr=stderr)
            raise ConnectionCalledProcessError(returncode=return_code, cmd=command, output=stdout, stderr=stderr)

    def _execute_command(self, command: str) -> Tuple[bytes, bytes, int]:
        """
        Low API for executing command.

        Start process and get output (waiting for end of process)
        :param command: Command to execute
        :return: Tuple with stdout, stderr bytes and return code
        """
        command_id = self._start_process(command)
        stdout_bytes, stderr_bytes, return_code = self._server.get_command_output(self._shell_id, command_id)
        return stdout_bytes, stderr_bytes, return_code

    def _start_process(self, command: str) -> str:
        """
        Low API for starting process.

        :param command: Command to start
        :return: WinRM ID of executed process.
        """
        command = shlex.split(command, posix=False)
        command_id = str(self._server.run_command(self._shell_id, "call", command))
        return command_id

    @clear_system_data_cache
    def disconnect(self) -> None:
        """Close WiRM connection on the remote host."""
        self._server.transport.close_session()

    def start_process(
        self,
        command: str,
    ) -> WinRmProcess:
        """
        Start process via winrm and get command id.

        :param command: Command to execute.
        """
        logger.log(level=log_levels.CMD, msg=f"Starting process >{self.ip}> '{command}'")
        return WinRmProcess(command_id=self._start_process(command), connection=self)

    @conditional_cache
    def get_os_name(self) -> OSName:
        """Get name of client OS."""
        windows_check_command = (
            "Get-WmiObject -Class Win32_OperatingSystem | Select-Object -Property Caption, OSArchitecture"
        )
        result = self.execute_powershell(windows_check_command, expected_return_codes=[0, 1, 127])
        if result.return_code:
            raise OsNotSupported("Client OS not supported")
        else:
            return OSName.WINDOWS

    def get_os_type(self) -> OSType:
        """Get type of client os."""
        return OSType.WINDOWS

    @conditional_cache
    def get_os_bitness(self) -> OSBitness:
        """Get bitness of client os."""
        if self._os_type == OSType.WINDOWS:
            windows_check_command = (
                "Get-WmiObject -Class Win32_OperatingSystem | Select-Object -Property OSArchitecture"
            )
            result = self.execute_powershell(windows_check_command, shell=False, expected_return_codes=[0, 1, 127])
        else:
            raise OsNotSupported("OS Bitness is not supported for this client OS")
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Debug data of os_bitness method: {result.stdout}")
        if "64" in result.stdout:
            return OSBitness.OS_64BIT
        elif "32" in result.stdout or "86" in result.stdout or "armv7l" in result.stdout:
            return OSBitness.OS_32BIT
        else:
            raise OsNotSupported("OS Bitness is not supported for this client OS")

    @conditional_cache
    def get_cpu_architecture(self) -> CPUArchitecture:
        """Get CPU Architecture."""
        if self._os_type == OSType.WINDOWS:
            windows_check_command = (
                "Get-WmiObject -Class Win32_OperatingSystem | Select-Object -Property OSArchitecture"
            )
            result = self.execute_powershell(windows_check_command, shell=False, expected_return_codes=[0, 1, 127])
        else:
            raise OsNotSupported("CPU Architecture is not supported for this client OS")
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Debug data of cpu_architecture method: {result.stdout}")
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

    def restart_platform(self) -> None:  # noqa D102
        raise NotImplementedError

    def shutdown_platform(self) -> None:  # noqa D102
        raise NotImplementedError

    def wait_for_host(self, timeout: int = 60) -> None:  # noqa D102
        raise NotImplementedError

    def path(self, *args, **kwargs) -> CustomPath:
        """Path represents a filesystem path."""
        if sys.version_info >= (3, 12):
            kwargs["owner"] = self
            return custom_path_factory(*args, **kwargs)

        return CustomPath(*args, owner=self, **kwargs)

    def execute_powershell(  # noqa D102
        self,
        command: str,
        *,
        input_data: Optional[str] = None,
        cwd: Optional[str] = None,
        timeout: Optional[int] = None,
        env: Optional[dict] = None,
        stderr_to_stdout: bool = False,
        discard_stdout: bool = False,
        discard_stderr: bool = False,
        skip_logging: bool = False,
        expected_return_codes: Optional[Iterable] = frozenset({0}),
        shell: bool = False,
        custom_exception: Type[CalledProcessError] = None,
    ) -> "ConnectionCompletedProcess":
        extend_buffer_size_command = (
            "$host.UI.RawUI.BufferSize = new-object System.Management.Automation.Host.Size(512,3000);"
        )
        if '"' in command:
            command = command.replace('"', '\\"')
        command = f'powershell.exe -OutPutFormat Text -nologo -noninteractive "{extend_buffer_size_command}{command}"'
        return self.execute_command(
            command=command,
            input_data=input_data,
            cwd=cwd,
            timeout=timeout,
            env=env,
            discard_stdout=discard_stdout,
            discard_stderr=discard_stderr,
            skip_logging=skip_logging,
            stderr_to_stdout=stderr_to_stdout,
            expected_return_codes=expected_return_codes,
            shell=shell,
            custom_exception=custom_exception,
        )
