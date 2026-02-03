# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: MIT
"""RShell Connection Class."""

import logging
from math import e
import sys
import time
import typing
from ipaddress import IPv4Address, IPv6Address
from subprocess import CalledProcessError

import requests
from mfd_common_libs import add_logging_level, log_levels, TimeoutCounter
from mfd_typing.cpu_values import CPUArchitecture
from mfd_typing.os_values import OSBitness, OSName, OSType

from mfd_connect.exceptions import ConnectionCalledProcessError, OsNotSupported
from mfd_connect.local import LocalConnection
from mfd_connect.pathlib.path import CustomPath, custom_path_factory
from mfd_connect.process.base import RemoteProcess
from mfd_connect.util.decorators import conditional_cache

from .base import Connection, ConnectionCompletedProcess

if typing.TYPE_CHECKING:
    from pydantic import (
        BaseModel,  # from pytest_mfd_config.models.topology import ConnectionModel
    )


logger = logging.getLogger(__name__)
add_logging_level(level_name="MODULE_DEBUG", level_value=log_levels.MODULE_DEBUG)
add_logging_level(level_name="CMD", level_value=log_levels.CMD)
add_logging_level(level_name="OUT", level_value=log_levels.OUT)


# Time to wait for platform to transition to off state after reset command is issued;  
# can be adjusted based on requirements and observed behavior of platforms. 
PLATFORM_POWER_TRANSITION_DELAY_SECONDS = 10  


class RShellConnection(Connection):
    """RShell Connection Class."""

    def __init__(
        self,
        ip: str | IPv4Address | IPv6Address,
        server_ip: str | IPv4Address | IPv6Address | None = "127.0.0.1",
        model: "BaseModel | None" = None,
        cache_system_data: bool = True,
        connection_timeout: int = 60,
    ):
        """
        Initialize RShellConnection.

        :param ip: The IP address of the RShell server.
        :param server_ip: The IP address of the server to connect to (optional).
        :param model: The Pydantic model to use for the connection (optional).
        :param cache_system_data: Whether to cache system data (default: True).
        """
        super().__init__(model=model, cache_system_data=cache_system_data)
        self._ip = ip
        self.server_ip = server_ip if server_ip else "127.0.0.1"
        self.server_process = None
        if server_ip == "127.0.0.1":
            # start Rshell server
            self.server_process = self._run_server()
            time.sleep(5)
        self.wait_for_connection(connection_timeout)

    def wait_for_connection(self, connection_timeout: int) -> None:
        """Wait for connection to RShell server to be established."""
        timeout = TimeoutCounter(connection_timeout)
        while not timeout:
            logger.log(level=log_levels.MODULE_DEBUG, msg="Checking RShell server health")
            try:
                status_code = requests.get(
                    f"http://{self.server_ip}/health/{self._ip}", proxies={"no_proxy": "*"}
                ).status_code
            except requests.RequestException as e:
                logger.log(level=log_levels.MODULE_DEBUG, msg=f"RShell server health check failed with error: {e}")
                status_code = None
            if status_code == 200:
                logger.log(level=log_levels.MODULE_DEBUG, msg="RShell server is healthy")
                break
            time.sleep(5)
        else:
            raise TimeoutError("Connection of Client to RShell server timed out")

    def disconnect(self, stop_client: bool = False, stop_server: bool = False) -> None:
        """
        Disconnect connection.

        Stop local RShell server if established.

        :param stop_client: Whether to stop the RShell client (default: False).
        """
        requests.post(f"http://{self.server_ip}/disconnect_client/{self._ip}", proxies={"no_proxy": "*"})
        if stop_client:
            logger.log(level=log_levels.MODULE_DEBUG, msg="Stopping RShell client")
            self.execute_command("end")
        if stop_server and self.server_process:
            self.stop_server()

    def _run_server(self) -> RemoteProcess:
        """Run RShell server locally."""
        conn = LocalConnection()
        server_file = conn.path(__file__).parent / "rshell_server.py"
        return conn.start_process(f"{conn.modules().sys.executable} {server_file}")

    def execute_command(
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
        skip_logging: bool = False,
        expected_return_codes: list[int] | None = None,
        shell: bool = False,
        custom_exception: type[CalledProcessError] | None = None,
    ) -> ConnectionCompletedProcess:
        """
        Execute a command on the remote server.

        :param command: The command to execute.
        :param timeout: The timeout for the command execution (optional).
        :return: The result of the command execution.
        """
        if input_data is not None:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg="Input data is not supported for RShellConnection and will be ignored.",
            )

        if cwd is not None:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg="CWD is not supported for RShellConnection and will be ignored.",
            )

        if env is not None:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg="Environment variables are not supported for RShellConnection and will be ignored.",
            )

        if stderr_to_stdout:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg="Redirecting stderr to stdout is not supported for RShellConnection and will be ignored.",
            )

        if discard_stdout:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg="Discarding stdout is not supported for RShellConnection and will be ignored.",
            )

        if discard_stderr:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg="Discarding stderr is not supported for RShellConnection and will be ignored.",
            )

        if skip_logging:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg="Skipping logging is not supported for RShellConnection and will be ignored.",
            )

        if expected_return_codes is not None:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg="Expected return codes are not supported for RShellConnection and will be ignored.",
            )

        if shell:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg="Shell execution is not supported for RShellConnection and will be ignored.",
            )

        if custom_exception:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg="Custom exceptions are not supported for RShellConnection and will be ignored.",
            )
        timeout_string = f" with timeout {timeout} seconds" if timeout is not None else ""
        logger.log(level=log_levels.CMD, msg=f"Executing >{self._ip}> '{command}',{timeout_string}")

        response = requests.post(
            f"http://{self.server_ip}/execute_command",
            data={"command": command, "timeout": timeout, "ip": self._ip},
            proxies={"no_proxy": "*"},
        )
        completed_process = ConnectionCompletedProcess(
            args=command,
            stdout=response.text,
            return_code=int(response.headers.get("rc", -1)),
        )
        logger.log(
            level=log_levels.MODULE_DEBUG,
            msg=f"Finished executing '{command}', rc={completed_process.return_code}",
        )
        if skip_logging:
            return completed_process

        stdout = completed_process.stdout
        if stdout:
            logger.log(level=log_levels.OUT, msg=f"stdout>>\n{stdout}")

        return completed_process

    def path(self, *args, **kwargs) -> CustomPath:
        """Path represents a filesystem path."""
        if sys.version_info >= (3, 12):
            kwargs["owner"] = self
            return custom_path_factory(*args, **kwargs)

        return CustomPath(*args, owner=self, **kwargs)

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
        if self._check_if_efi_shell():
            return OSType.EFISHELL

        if self._check_if_unix():
            return OSType.POSIX

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
            return OSBitness.OS_64BIT  # current requirements describe only EFISHELL as required
        raise OsNotSupported("Client OS is not supported")

    @conditional_cache
    def get_cpu_architecture(self) -> CPUArchitecture:
        """Get CPU architecture."""
        if self._check_if_efi_shell():
            return CPUArchitecture.X86_64
        raise OsNotSupported("'get_cpu_architecture' not supported on that OS")

    def restart_platform(self) -> None:
        """Restart the platform."""
        self.execute_command("reset -c")
        time.sleep(PLATFORM_POWER_TRANSITION_DELAY_SECONDS)
        self.disconnect()

    def warm_reboot_platform(self) -> None:
        """Warm reboot the platform."""
        self.execute_command("reset -w")
        time.sleep(PLATFORM_POWER_TRANSITION_DELAY_SECONDS)
        self.disconnect()

    def shutdown_platform(self) -> None:
        """Shutdown the platform."""
        self.execute_command("reset -s")
        time.sleep(PLATFORM_POWER_TRANSITION_DELAY_SECONDS)
        self.disconnect()

    def wait_for_host(self, timeout: int = 60) -> None:
        """
        Wait for the host to be reachable.

        :param timeout: Timeout in seconds.
        """
        self.wait_for_connection(timeout)

    def stop_server(self) -> None:
        """Stop the RShell server."""
        if self.server_process:
            logger.log(level=log_levels.MODULE_DEBUG, msg="Stopping RShell server")
            self.server_process.kill()
            logger.log(level=log_levels.MODULE_DEBUG, msg="RShell server stopped")
            logger.log(level=log_levels.MODULE_DEBUG, msg=self.server_process.stdout_text)
