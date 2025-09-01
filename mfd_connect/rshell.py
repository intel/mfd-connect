# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""RShell Connection Class."""

import logging
import sys
import time
import typing
from ipaddress import IPv4Address, IPv6Address
from subprocess import CalledProcessError

import requests
from mfd_common_libs import add_logging_level, log_levels, TimeoutCounter
from mfd_typing.cpu_values import CPUArchitecture
from mfd_typing.os_values import OSBitness, OSName, OSType

from mfd_connect.local import LocalConnection
from mfd_connect.pathlib.path import CustomPath, custom_path_factory
from mfd_connect.process.base import RemoteProcess

from .base import Connection, ConnectionCompletedProcess

if typing.TYPE_CHECKING:
    from pydantic import (
        BaseModel,  # from pytest_mfd_config.models.topology import ConnectionModel
    )


logger = logging.getLogger(__name__)
add_logging_level(level_name="MODULE_DEBUG", level_value=log_levels.MODULE_DEBUG)
add_logging_level(level_name="CMD", level_value=log_levels.CMD)
add_logging_level(level_name="OUT", level_value=log_levels.OUT)


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
        timeout = TimeoutCounter(connection_timeout)
        while not timeout:
            logger.log(level=log_levels.MODULE_DEBUG, msg="Checking RShell server health")
            status_code = requests.get(
                f"http://{self.server_ip}/health/{self._ip}", proxies={"no_proxy": "*"}
            ).status_code
            if status_code == 200:
                logger.log(level=log_levels.MODULE_DEBUG, msg="RShell server is healthy")
                break
            time.sleep(5)
        else:
            raise TimeoutError("Connection of Client to RShell server timed out")

    def disconnect(self, stop_client: bool = False) -> None:
        """
        Disconnect connection.

        Stop local RShell server if established.

        :param stop_client: Whether to stop the RShell client (default: False).
        """
        if stop_client:
            logger.log(level=log_levels.MODULE_DEBUG, msg="Stopping RShell client")
            self.execute_command("end")
        if self.server_process:
            logger.log(level=log_levels.MODULE_DEBUG, msg="Stopping RShell server")
            self.server_process.kill()
            logger.log(level=log_levels.MODULE_DEBUG, msg="RShell server stopped")
            logger.log(level=log_levels.MODULE_DEBUG, msg=self.server_process.stdout_text)

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

    def get_os_name(self) -> OSName:  # noqa: D102
        raise NotImplementedError

    def get_os_type(self) -> OSType:  # noqa: D102
        raise NotImplementedError

    def get_os_bitness(self) -> OSBitness:  # noqa: D102
        raise NotImplementedError

    def get_cpu_architecture(self) -> CPUArchitecture:  # noqa: D102
        raise NotImplementedError

    def restart_platform(self) -> None:  # noqa: D102
        raise NotImplementedError

    def shutdown_platform(self) -> None:  # noqa: D102
        raise NotImplementedError

    def wait_for_host(self, timeout: int = 60) -> None:  # noqa: D102
        raise NotImplementedError
