# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for SSHConfigConnection class."""

import logging
import socket
from pathlib import Path
from typing import TYPE_CHECKING

import paramiko
from mfd_common_libs import add_logging_level, log_levels
from netaddr import AddrFormatError, IPAddress
from paramiko import AuthenticationException

from .exceptions import OsNotSupported, SSHConfigException
from .ssh import SSHConnection
from .util.ssh_config_parser import SSHHostConfig, parse_ssh_config, resolve_host

if TYPE_CHECKING:
    from pydantic import BaseModel

logger = logging.getLogger(__name__)
add_logging_level(level_name="MODULE_DEBUG", level_value=log_levels.MODULE_DEBUG)


class SSHConfigConnection(SSHConnection):
    """
    SSH connection resolved from ~/.ssh/config Host mnemonics.

    Resolves hostname, user, port, identity file, StrictHostKeyChecking,
    and ProxyJump chains from the SSH config file.

    For ProxyJump chains, it automatically sets up paramiko transport chaining
    through the intermediate jump hosts.

    Usage example:
    >>> conn = SSHConfigConnection(host="b1.a.host")
    >>> res = conn.execute_command("hostname", shell=True)
    test
    """

    def __init__(
        self,
        host: str,
        *args,
        password: str | None = None,
        config_path: "str | Path | None" = None,
        model: "BaseModel | None" = None,
        default_timeout: int | None = None,
        cache_system_data: bool = True,
        **kwargs,
    ) -> None:
        """
        Initialise SSHConfigConnection from an SSH config Host mnemonic.

        For direct hosts (no ProxyJump), the connection parameters are resolved
        from the config and passed to SSHConnection.

        For hosts with ProxyJump, a transport chain is built through
        intermediate hops using paramiko channels before connecting to the target.

        :param host: Host mnemonic from ~/.ssh/config (e.g. "b1.a.host", "imc", "acc").
        :param password: Optional password for the target host. If None, key-based auth
                         from config IdentityFile is used.
        :param config_path: Path to SSH config file (default: ~/.ssh/config).
        :param model: Pydantic model of connection.
        :param default_timeout: Timeout value for execute_command.
        :param cache_system_data: Flag to cache system data like self._os_type, OS name,
                                  OS bitness and CPU architecture.
        :raises SSHConfigException: If mnemonic cannot be resolved or connection fails.
        """
        try:
            ssh_config = parse_ssh_config(config_path)
            host_config = resolve_host(host, ssh_config)
        except (FileNotFoundError, ValueError) as e:
            raise SSHConfigException(f"Failed to resolve SSH config for host '{host}': {e}") from e

        self._mnemonic = host
        self._host_config = host_config
        self._proxy_clients: list[paramiko.SSHClient] = []
        self._proxy_sock: "paramiko.channel.Channel | None" = None

        if host_config.proxy_chain:
            try:
                self._proxy_sock = self._build_proxy_chain(host_config)
            except SSHConfigException:
                raise
            except Exception as e:
                self._close_proxy_clients()
                raise SSHConfigException(f"Failed to build proxy chain for host '{host}': {e}") from e

        # HostName may be a DNS name; SSHConnection requires an IP address.
        try:
            IPAddress(host_config.hostname)
            ip = host_config.hostname
        except (ValueError, AddrFormatError):
            try:
                ip = socket.gethostbyname(host_config.hostname)
            except socket.gaierror as e:
                raise SSHConfigException(
                    f"Cannot resolve hostname '{host_config.hostname}' for host '{host}': {e}"
                ) from e

        try:
            super().__init__(
                ip=ip,
                port=host_config.port,
                username=host_config.user,
                password=password,
                skip_key_verification=not host_config.strict_host_key_checking,
                model=model,
                default_timeout=default_timeout,
                cache_system_data=cache_system_data,
                **kwargs,
            )
        except Exception:
            self._close_proxy_clients()
            raise

    def __str__(self) -> str:
        """Return string representation."""
        return f"ssh_config({self._mnemonic})"

    def _connect(self) -> None:
        """
        Connect via SSH, injecting proxy sock if a ProxyJump chain exists.

        Overrides SSHConnection._connect to inject the tunneled channel
        as a socket parameter, enable key/agent discovery (mirroring OpenSSH),
        and handle ``auth_none`` fallback for devices that accept
        unauthenticated connections (e.g., IMC controllers via tunnel).

        :raises OsNotSupported: if os not found in available process classes.
        """
        if self._proxy_sock is not None:
            self._connection_details["sock"] = self._proxy_sock

        # Inject identity files from SSH config separately so that host key
        # policy selection (RejectPolicy vs AutoAddPolicy) is not coupled
        # to the presence of a key file.
        if self._host_config.identity_file:
            self._connection_details["key_filename"] = self._host_config.identity_file

        # SSH config connections mirror OpenSSH: always try default keys
        # and SSH agent regardless of host-key verification settings.
        self._connection_details["look_for_keys"] = True
        self._connection_details["allow_agent"] = True

        # Override SSHConnection's default WarningPolicy with RejectPolicy
        # when strict host key checking is enabled, matching OpenSSH behaviour.
        if self._host_config.strict_host_key_checking:
            self._connection.set_missing_host_key_policy(paramiko.RejectPolicy())
            self._connection.load_system_host_keys()

        try:
            super()._connect()
        except AuthenticationException as e:
            # Fallback: try "none" authentication.
            # Some devices (e.g., IMC controllers) accept unauthenticated
            # connections when accessed through a tunnel.
            transport = self._connection.get_transport()
            if transport is None:
                raise
            try:
                transport.auth_none(self._connection_details.get("username", ""))
            except AuthenticationException:
                raise e from None
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg="Authenticated using 'none' method",
            )
            self._complete_post_connect_setup()

    def _complete_post_connect_setup(self) -> None:
        """
        Complete post-connection setup after ``auth_none`` fallback.

        Performs the same post-connect steps as ``SSHConnection._connect``:
        handles additional authentication requests and detects the OS type
        and process class.

        :raises OsNotSupported: if os not found in available process classes.
        """
        key_auth = str(self._connection.get_transport())
        if "awaiting auth" in key_auth:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg="SSH server requested additional authentication",
            )
            self._connection.get_transport().auth_interactive_dumb(self._connection_details["username"])

        os_name = self.get_os_name()
        self._os_type = self.get_os_type()
        for process_class in self._process_classes:
            if os_name in process_class._os_name:
                self._process_class = process_class
                break
        else:
            raise OsNotSupported(f"Not implemented process for read os name {os_name}")

    def _build_proxy_chain(self, host_config: SSHHostConfig) -> "paramiko.channel.Channel":
        """
        Build paramiko transport chain through ProxyJump hops.

        Connects to each intermediate host in sequence, using the previous
        hop's transport to open a channel to the next hop. Returns a channel
        to the final target host for use as a socket.

        :param host_config: Resolved SSHHostConfig with proxy_chain.
        :return: Paramiko channel connected to the target host.
        :raises SSHConfigException: If any hop in the chain fails to connect.
        """
        chain = list(reversed(host_config.proxy_chain))
        gateway_transport = None

        try:
            for hop in chain:
                client = self._connect_proxy_hop(hop, gateway_transport)
                gateway_transport = client.get_transport()
                self._proxy_clients.append(client)

            target_channel = gateway_transport.open_channel(
                "direct-tcpip",
                (host_config.hostname, host_config.port),
                ("127.0.0.1", 0),
            )
        except SSHConfigException:
            raise
        except Exception as e:
            self._close_proxy_clients()
            raise SSHConfigException(f"Failed to build proxy chain: {e}") from e
        return target_channel

    def _connect_proxy_hop(
        self,
        hop: SSHHostConfig,
        gateway_transport: "paramiko.Transport | None" = None,
    ) -> paramiko.SSHClient:
        """
        Connect a single proxy hop, with ``auth_none`` fallback.

        Configures host key policy, builds connect kwargs, optionally tunnels
        through an existing gateway transport, and falls back to ``auth_none``
        for devices that accept unauthenticated connections.

        :param hop: Resolved config for this hop.
        :param gateway_transport: Transport of the previous hop (None for first hop).
        :return: Connected paramiko SSHClient for this hop.
        :raises SSHConfigException: If the hop cannot be authenticated.
        """
        client = paramiko.SSHClient()
        if hop.strict_host_key_checking:
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            client.load_system_host_keys()
        else:
            client.set_missing_host_key_policy(paramiko.WarningPolicy())

        connect_kwargs: dict = {
            "hostname": hop.hostname,
            "port": hop.port,
            "username": hop.user,
        }
        if hop.identity_file:
            connect_kwargs["key_filename"] = hop.identity_file

        if gateway_transport is not None:
            channel = gateway_transport.open_channel(
                "direct-tcpip",
                (hop.hostname, hop.port),
                ("127.0.0.1", 0),
            )
            connect_kwargs["sock"] = channel

        try:
            client.connect(**connect_kwargs, compress=True)
        except AuthenticationException as e:
            # Fallback: try "none" authentication for this hop.
            # Some devices (e.g. IMC controllers) accept unauthenticated
            # connections when accessed through a tunnel.
            transport = client.get_transport()
            if transport is None:
                self._close_proxy_clients()
                raise SSHConfigException(f"Failed to connect to proxy hop '{hop.hostname}': {e}") from e
            try:
                transport.auth_none(hop.user)
            except AuthenticationException:
                self._close_proxy_clients()
                raise SSHConfigException(f"Failed to connect to proxy hop '{hop.hostname}': {e}") from e
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg=f"Proxy hop '{hop.hostname}': authenticated using 'none' method",
            )
        return client

    def _close_proxy_clients(self) -> None:
        """Close all proxy hop SSH clients in reverse order."""
        for client in reversed(self._proxy_clients):
            try:
                client.close()
            except Exception:
                pass
        self._proxy_clients = []

    def _reconnect(self) -> None:
        """
        Reconnect, rebuilding proxy chain if needed.

        For ProxyJump connections, rebuilds the entire transport chain
        before reconnecting to the target host.

        :raises SSHReconnectException: in case of fail in establishing connection.
        """
        if self._host_config.proxy_chain:
            self._close_proxy_clients()
            self._proxy_sock = self._build_proxy_chain(self._host_config)
        super()._reconnect()

    def disconnect(self) -> None:
        """Close connection and all proxy hop clients."""
        super().disconnect()
        self._close_proxy_clients()
