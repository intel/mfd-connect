# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Tunneled RPyC Connection implementation."""

import logging
import time
import typing
from typing import Union

import rpyc
from mfd_common_libs import log_levels
from netaddr import IPAddress
from rpyc import ClassicService

from .rpyc import RPyCConnection

if typing.TYPE_CHECKING:
    from pydantic import BaseModel
    from pathlib import PurePath

logger = logging.getLogger(__name__)


class TunneledRPyCConnection(RPyCConnection):
    """
    Implementation of RPyCConnection type using tunneled connection for remote usage.

    Operations will be performed on machine via RPyC connection.
    """

    def __init__(
        self,
        ip: "IPAddress | str",
        jump_host_ip: "IPAddress | str",
        *,
        port: int | None = None,
        jump_host_port: int | None = None,
        path_extension: str | None = None,
        connection_timeout: int = 360,
        default_timeout: int | None = None,
        jump_host_retry_timeout: int | None = None,
        jump_host_retry_time: int = 5,
        enable_bg_serving_thread: bool = False,
        model: "BaseModel | None" = None,
        cache_system_data: bool = True,
        **kwargs,
    ) -> None:
        """
        Initialise TunneledRPyCConnection class.

        :param ip: Host identifier - IP address
        :param jump_host_ip: Jump Host identifier - IP address
        :param port: TCP port to use while connecting to host's responder.
        :param jump_host_port: TCP port to use while connecting to jump host's responder.
        :param path_extension: PATH environment variable extension for calling commands.
        :param connection_timeout: Timeout value, if timeout last without response from server,
        client raises AsyncResultTimeout
        :param default_timeout: Timeout value for executing timeout for entire class.
        :param jump_host_retry_timeout: Time for try of connection, in secs
        :param jump_host_retry_time: Time between next try of connection, in secs
        :param enable_bg_serving_thread: Set to True if background serving thread must be activated, otherwise False
        :param model: pydantic model of connection
        :param cache_system_data: Flag to cache system data like self._os_type, OS name, OS bitness and CPU architecture
        """
        super().__init__(
            ip=jump_host_ip,
            port=jump_host_port,
            connection_timeout=connection_timeout,
            default_timeout=default_timeout,
            retry_timeout=jump_host_retry_timeout,
            retry_time=jump_host_retry_time,
            enable_bg_serving_thread=enable_bg_serving_thread,
            model=model,
            cache_system_data=cache_system_data,
            **kwargs,
        )
        self._tunnel_connection = self._connection
        self.path_extension = path_extension
        self._port = port
        self._connection_timeout = connection_timeout
        self._enable_bg_serving_thread = enable_bg_serving_thread

        self._connection = self._tunnel_connection.modules.rpyc.connect(
            str(ip),
            port=port or RPyCConnection.DEFAULT_RPYC_6_0_0_RESPONDER_PORT,
            service=ClassicService,
            keepalive=True,
            config={"sync_request_timeout": connection_timeout},
        )
        self._set_process_class()
        if self._enable_bg_serving_thread:
            self._background_serving_thread = rpyc.BgServingThread(self.remote)
            time.sleep(0.1)
        self.log_tunneled_host_info(ip)

    def __str__(self):
        return "tunneled_rpyc"

    def log_tunneled_host_info(self, ip: Union["IPAddress", str]) -> None:
        """Log information about connected host."""
        if logging.root.level <= log_levels.MODULE_DEBUG:
            if hasattr(self, "_os_type"):
                os_type = self._os_type
            else:
                os_type = self.get_os_type()
            if hasattr(self, "_os_name"):
                os_name = self._os_name
            else:
                os_name = self.get_os_name()
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg=f"{self.__class__.__name__} established with:"
                f" {os_type},"
                f" {os_name},"
                f" {self.get_os_bitness()},"
                f" {ip}",
            )

    def disconnect(self) -> None:
        """Close connection with host."""
        super().disconnect()
        self._tunnel_connection.close()

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
        raise NotImplementedError("Not implemented for TunneledRPyCConnection")
