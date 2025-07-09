# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for Zero Deploy RPyC."""

import codecs
import logging
import time
from pathlib import Path
from typing import Optional, TYPE_CHECKING

import rpyc
from funcy import retry
from mfd_common_libs import add_logging_level, log_levels, TimeoutCounter
from paramiko import WarningPolicy, AuthenticationException
from paramiko.ssh_exception import NoValidConnectionsError, SSHException
from plumbum import ProcessExecutionError, CommandNotFound
from plumbum.machines.paramiko_machine import ParamikoMachine
from rpyc.utils.zerodeploy import DeployedServer

from mfd_connect import RPyCConnection
from mfd_connect.exceptions import RPyCZeroDeployException

if TYPE_CHECKING:
    from rpyc import Connection
    from netaddr import IPAddress
    from plumbum.machines.paramiko_machine import ParamikoPopen
    from pydantic import BaseModel
    from pathlib import PurePath

logger = logging.getLogger(__name__)
add_logging_level(level_name="MODULE_DEBUG", level_value=log_levels.MODULE_DEBUG)


class RPyCZeroDeployConnection(RPyCConnection):
    """Class for Zero Deploy RPyC."""

    def __init__(
        self,
        ip: "IPAddress | str",
        *,
        port: int = None,
        path_extension: str = None,
        connection_timeout: int = 360,
        default_timeout: int | None = None,
        retry_timeout: int | None = None,
        retry_time: int = 5,
        username: str,
        password: str = None,
        keyfile: Path | str = None,
        python_executable: Path | str | None = None,
        model: "BaseModel | None" = None,
        cache_system_data: bool = True,
        **kwargs,
    ):
        """
        Initialize RPyC Connection via Zero Deploy.

        :param ip: Host identifier - IP address
        :param port: TCP port to use while connecting to host's responder.
        :param path_extension: PATH environment variable extension for calling commands.
        :param connection_timeout: Timeout value, if timeout last without response from server,
        client raises AsyncResultTimeout
        :param default_timeout: Timeout value for executing timeout for entire class.
        :param retry_timeout: Time for try of connection, in secs
        :param retry_time: Time between next try of connection, in secs
        :param username: Username for Zero Deploy
        :param password: Password for Zero Deploy, in exchange with keyfile
        :param keyfile: Path to ssh key for Zero Deploy, in exchange with password
        :param python_executable: Path to python for usage for server, if not passed uses default in system
        :param model: pydantic model of connection
        :param cache_system_data: Flag to cache system data like self._os_type, OS name, OS bitness and CPU architecture
        :raises RPyCZeroDeployException: if not passed auth data
                                         if connection via SSH failed
                                         if deploying RPyC server failed
        """
        if not (password or keyfile):
            raise RPyCZeroDeployException("Missing authentication argument password/keyfile ssh")
        self._username = username
        self._password = password
        if isinstance(keyfile, Path):
            self._keyfile = str(keyfile)
        else:
            self._keyfile = keyfile
        self._connection_timeout = connection_timeout
        if isinstance(python_executable, Path):
            self._python_executable = str(python_executable)
        else:
            self._python_executable = python_executable
        self._prepare_connection(ip, username, password, keyfile, connection_timeout, python_executable)
        logger.log(level=log_levels.MODULE_DEBUG, msg="Starting RPyC connection.")
        super().__init__(
            ip=ip,
            port=port,
            path_extension=path_extension,
            connection_timeout=connection_timeout,
            default_timeout=default_timeout,
            retry_timeout=retry_timeout,
            retry_time=retry_time,
            model=model,
            cache_system_data=cache_system_data,
            **kwargs,
        )

    def _prepare_connection(
        self,
        ip: str,
        username: str,
        password: Optional[str],
        keyfile: Optional[str],
        connection_timeout: int,
        python_executable: Optional[str],
    ) -> None:
        """
        Prepare RPyC server.

        Connects via SSH, deploys rpyc server, starts server.

        :raises RPyCZeroDeployException: if connection via SSH failed
                                         if deploying RPyC server failed
        """
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Creating connection via SSH with {ip}")
        try:
            self._mach = ParamikoMachine(
                host=ip,
                user=username,
                password=password,
                keyfile=keyfile,
                missing_host_policy=WarningPolicy(),
                connect_timeout=connection_timeout,
            )
        except (TimeoutError, AuthenticationException, NoValidConnectionsError) as e:
            raise RPyCZeroDeployException("Problem with establishing connection via SSH.") from e
        except Exception as e:
            raise RPyCZeroDeployException("Unexpected exception during connection via SSH.") from e
        logger.log(level=log_levels.MODULE_DEBUG, msg="Established SSH connection. Starting RPyC server.")
        try:
            self._server = DeployedServer(remote_machine=self._mach, python_executable=python_executable)
        except ProcessExecutionError as e:
            self._mach.close()
            raise RPyCZeroDeployException("Problem during deploying RPyC server via SSH.") from e
        except Exception as e:
            raise RPyCZeroDeployException("Unexpected exception during deploying RPyC server via SSH.") from e

    @retry(5, errors=OSError)
    def _create_connection(self) -> "Connection":
        """
        Create RPyC connection to the represented host.

        :return: RPyC connection object.
        """
        return self._server.classic_connect()

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback) -> None:  # noqa:ANN001
        self.close()

    def restart_platform(self) -> None:
        """
        Reboot host.

        :raises RPyCZeroDeployException: if platform doesn't disconnect; if command was not found
        """
        super().restart_platform()

    def shutdown_platform(self) -> None:
        """
        Shutdown host.

        :raises RPyCZeroDeployException: if platform doesn't disconnect; if command was not found
        """
        super().shutdown_platform()

    def send_command_and_disconnect_platform(self, command: str) -> None:
        """
        Send to host command and disconnect rpyc.

        Stopping Background Serving Thread
        Closing rpyc connection
        If send command failed, return code != 0 and raise ConnectionCalledProcessError
        Handle EOFError, which has been raised when dropped connection
        If command send correct, sleep 'sleep_time' for start rebooting and end responder

        :param command: Command to send
        :raises RPyCZeroDeployException: if platform doesn't disconnect; if command was not found
        """
        sleep_time = 10
        self._background_serving_thread.stop()
        try:
            self._connection.close()
            self._server.close()
            command_split = command.split(maxsplit=1)
            if len(command_split) > 1:
                command_name, command_args = command_split
                command_args = f" {command_args}"
            else:
                command_name = command_split[0]
                command_args = ""
            command_path = self._mach.which(command_name)
            command = f"{command_path}{command_args}"
            logger.log(level=log_levels.CMD, msg=f"Executing {command}")
            popen_process = self._mach[command].popen()
            self.__log_output_from_command(popen_process)
            try:
                self._mach.which(command_name)
            except SSHException:
                logger.log(level=log_levels.MODULE_DEBUG, msg="Dropped connection via SSH, expected")
            else:
                raise RPyCZeroDeployException(f"Platform doesn't disconnect after executed command: {command}")
        except RPyCZeroDeployException:
            raise
        except CommandNotFound as e:
            raise RPyCZeroDeployException(f"Not found {command} in system") from e
        except Exception as e:
            raise RPyCZeroDeployException("Unexpected exception during send and disconnect method.") from e
        time.sleep(sleep_time)

    def __log_output_from_command(self, process: "ParamikoPopen") -> None:
        """Log outputs from popen."""
        if process.stdout:
            stdout = codecs.decode(process.stdout.read(), encoding="utf-8", errors="backslashreplace")
            if stdout:
                logger.log(level=log_levels.OUT, msg=f">>stdout:\n{stdout}")
        if process.stderr:
            stderr = codecs.decode(process.stderr.read(), encoding="utf-8", errors="backslashreplace")
            if stderr:
                logger.log(level=log_levels.OUT, msg=f">>stderr:\n{stderr}")

    def wait_for_host(self, *, timeout: int = 60, retry_time: int = 5) -> None:
        """
        Wait for host availability.

        Trying deploy rpyc,
        if connected, establishing BackgroundServingThread

        :param timeout: Time to check until fail
        :param retry_time: Time for next check
        :raises TimeoutError: when timeout is expired
        """
        last_exception = None
        timeout_counter = TimeoutCounter(timeout)
        while not timeout_counter:
            try:
                logger.log(level=log_levels.MODULE_DEBUG, msg="Reconnecting...")
                self._prepare_connection(
                    self._ip,
                    self._username,
                    self._password,
                    self._keyfile,
                    self._connection_timeout,
                    self._python_executable,
                )
                self._connection = self._create_connection()
                if self._connection:
                    logger.log(level=log_levels.MODULE_DEBUG, msg="Connected via RPyC")
                    self._background_serving_thread = rpyc.BgServingThread(self.remote)
                    return
            except (RPyCZeroDeployException, OSError) as e:
                last_exception = e
                logger.log(
                    level=log_levels.MODULE_DEBUG,
                    msg=f"Connection does not established, waiting {retry_time} seconds and trying again",
                )
                time.sleep(retry_time)
        else:
            raise TimeoutError(f"Host does not wake up in {timeout} seconds") from last_exception

    def close(self) -> None:
        """Close RPyC deployed server including connections."""
        self.disconnect()
        if self._server:
            self._server.close()
        if self._mach:
            self._mach.close()

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
        raise NotImplementedError("Not implemented for RPyCZeroDeployConnection")
