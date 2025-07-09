# Copyright (c) 2014-2019 Pahaz White.
# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
# *sshtunnel* - Initiate SSH tunnels via a remote gateway.
#
# ``sshtunnel`` works by opening a port forwarding SSH connection in the
# background, using threads.
#
# The connection(s) are closed when explicitly calling the
# :meth:`SSHTunnelForwarder.stop` method or using it as a context.
"""Module providing sshtunnel feature."""

import os
import random
import string
import sys
import socket
import getpass
import logging
import argparse
from typing import Any
import warnings
import threading
from select import select
from binascii import hexlify

import paramiko

if sys.version_info[0] < 3:  # pragma: no cover
    import Queue as queue
    import SocketServer as socketserver

    string_types = (basestring,)  # noqa
    input_ = raw_input  # noqa
else:  # pragma: no cover
    import queue
    import socketserver

    string_types = str
    input_ = input


__version__ = "0.4.1"
__author__ = "pahaz"


#: Timeout (seconds) for transport socket (``socket.settimeout``)
SSH_TIMEOUT = 0.1  # ``None`` may cause a block of transport thread
#: Timeout (seconds) for tunnel connection (open_channel timeout)
TUNNEL_TIMEOUT = 10.0

_DAEMON = True  #: Use daemon threads in connections
_CONNECTION_COUNTER = 1
_DEPRECATIONS = {
    "ssh_address": "ssh_address_or_host",
    "ssh_host": "ssh_address_or_host",
    "ssh_private_key": "ssh_pkey",
    "raise_exception_if_any_forwarder_have_a_problem": "mute_exceptions",
}

# logging
DEFAULT_LOGLEVEL = logging.ERROR  #: default level if no logger passed (ERROR)
TRACE_LEVEL = 1
logging.addLevelName(TRACE_LEVEL, "TRACE")
DEFAULT_SSH_DIRECTORY = "~/.ssh"

_StreamServer = socketserver.UnixStreamServer if os.name == "posix" else socketserver.TCPServer

#: Path of optional ssh configuration file
DEFAULT_SSH_DIRECTORY = "~/.ssh"
SSH_CONFIG_FILE = os.path.join(DEFAULT_SSH_DIRECTORY, "config")

########################
#                      #
#       Utils          #
#                      #
########################


def check_host(host: str) -> None:
    """
    Check if the host is a valid string.

    :param host: The host to check.
    :raises AssertionError: If the host is not a string.
    """
    assert isinstance(host, string_types), "IP is not a string ({0})".format(type(host).__name__)


def check_port(port: int) -> None:
    """
    Check if the port is a valid integer.

    :param port: The port to check.
    :raises AssertionError: If the port is not a number or is less than 0.
    """
    assert isinstance(port, int), "PORT is not a number"
    assert port >= 0, "PORT < 0 ({0})".format(port)


def check_address(address: tuple[str, int] | str) -> None:
    """
    Check if the format of the address is correct.

    :param address: The address to check.
    :raises ValueError: If the address has an incorrect format.
    """
    if isinstance(address, tuple):
        check_host(address[0])
        check_port(address[1])
    elif isinstance(address, string_types):
        if os.name != "posix":
            raise ValueError("Platform does not support UNIX domain sockets")
        if not (os.path.exists(address) or os.access(os.path.dirname(address), os.W_OK)):
            raise ValueError("ADDRESS not a valid socket domain socket ({0})".format(address))
    else:
        raise ValueError("ADDRESS is not a tuple, string, or character buffer ({0})".format(type(address).__name__))


def check_addresses(address_list: list[tuple[str, int] | str], is_remote: bool = False) -> None:
    """
    Check if the format of the addresses is correct.

    :param address_list: A list of addresses to check.
    :param is_remote: Whether the addresses are remote.
    :raises AssertionError: If the address list contains an invalid element.
    :raises ValueError: If any address in the list has an incorrect format.
    """
    assert all(isinstance(x, (tuple, string_types)) for x in address_list)
    if is_remote and any(isinstance(x, string_types) for x in address_list):
        raise AssertionError("UNIX domain sockets not allowed for remote addresses")

    for address in address_list:
        check_address(address)


def create_logger(
    logger: logging.Logger | None = None,
    loglevel: str | int | None = None,
    capture_warnings: bool = True,
    add_paramiko_handler: bool = True,
) -> logging.Logger:
    """
    Attach or create a new logger and add a console handler if not present.

    :param logger: A logger instance. A new one is created if None.
    :param loglevel: The logging level.
    :param capture_warnings: Whether to capture warnings.
    :param add_paramiko_handler: Whether to add a handler for paramiko.
    :return: The configured logger.
    """
    logger = logger or logging.getLogger("sshtunnel.SSHTunnelForwarder")
    if not any(isinstance(x, logging.Handler) for x in logger.handlers):
        logger.setLevel(loglevel or DEFAULT_LOGLEVEL)
        console_handler = logging.StreamHandler()
        _add_handler(logger, handler=console_handler, loglevel=loglevel or DEFAULT_LOGLEVEL)

    if loglevel:  # override if loglevel was set
        logger.setLevel(loglevel)
        for handler in logger.handlers:
            handler.setLevel(loglevel)

    if add_paramiko_handler:
        _check_paramiko_handlers(logger=logger)

    if capture_warnings and sys.version_info >= (2, 7):
        logging.captureWarnings(True)
        pywarnings = logging.getLogger("py.warnings")
        pywarnings.handlers.extend(logger.handlers)

    return logger


def _add_handler(
    logger: logging.Logger, handler: logging.Handler | None = None, loglevel: str | int | None = None
) -> None:
    """Add a handler to an existing logging.Logger object.

    :param logger: The logger to which the handler will be added.
    :param handler: The handler to add.
    :param loglevel: The logging level for the handler.
    """
    handler.setLevel(loglevel or DEFAULT_LOGLEVEL)
    if handler.level <= logging.DEBUG:
        _fmt = "%(asctime)s| %(levelname)-4.3s|%(threadName)10.9s/" "%(lineno)04d@%(module)-10.9s| %(message)s"
        handler.setFormatter(logging.Formatter(_fmt))
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s| %(levelname)-8s| %(message)s"))
    logger.addHandler(handler)


def _check_paramiko_handlers(logger: logging.Logger | None = None) -> None:
    """Add a console handler for paramiko.transport's logger if not present.

    :param logger: The logger to check and update.
    """
    paramiko_logger = logging.getLogger("paramiko.transport")
    if not paramiko_logger.handlers:
        if logger:
            paramiko_logger.handlers = logger.handlers
        else:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(
                logging.Formatter("%(asctime)s | %(levelname)-8s| PARAMIKO: " "%(lineno)03d@%(module)-10s| %(message)s")
            )
            paramiko_logger.addHandler(console_handler)


def address_to_str(address: tuple | str) -> str:
    """Convert an address (IP, port) tuple or string to a string representation."""
    if isinstance(address, tuple):
        return "{0[0]}:{0[1]}".format(address)
    return str(address)


def _remove_none_values(dictionary: dict) -> list:
    """Remove dictionary keys whose value is None."""
    return list(map(dictionary.pop, [i for i in dictionary if dictionary[i] is None]))


def generate_random_string(length: int) -> str:
    """Generate a random string of letters and digits."""
    letters = string.ascii_letters + string.digits
    return "".join(random.choice(letters) for _ in range(length))


########################
#                      #
#       Errors         #
#                      #
########################


class BaseSSHTunnelForwarderError(Exception):
    """Exception raised by :class:`SSHTunnelForwarder` errors."""

    def __init__(self, *args, **kwargs):
        """Initialize the error with a message."""
        self.value = kwargs.pop("value", args[0] if args else "")

    def __str__(self):
        """Return a string representation of the error."""
        return self.value


class HandlerSSHTunnelForwarderError(BaseSSHTunnelForwarderError):
    """Exception for Tunnel forwarder errors."""

    pass


########################
#                      #
#       Handlers       #
#                      #
########################


class _ForwardHandler(socketserver.BaseRequestHandler):
    """Base handler for tunnel connections."""

    remote_address = None
    ssh_transport = None
    logger = None
    info = None

    def _redirect(self, chan: paramiko.Channel) -> None:
        """
        Redirect data between the SSH channel and the request socket.

        :param chan: The SSH channel to redirect data to/from.
        """
        while chan.active:
            rqst, _, _ = select([self.request, chan], [], [], 5)
            if self.request in rqst:
                data = self.request.recv(16384)
                if not data:
                    self.logger.log(TRACE_LEVEL, ">>> OUT {0} recv empty data >>>".format(self.info))
                    break
                if self.logger.isEnabledFor(TRACE_LEVEL):
                    self.logger.log(
                        TRACE_LEVEL,
                        ">>> OUT {0} send to {1}: {2} >>>".format(self.info, self.remote_address, hexlify(data)),
                    )
                chan.sendall(data)
            if chan in rqst:  # else
                if not chan.recv_ready():
                    self.logger.log(TRACE_LEVEL, "<<< IN {0} recv is not ready <<<".format(self.info))
                    break
                data = chan.recv(16384)
                if self.logger.isEnabledFor(TRACE_LEVEL):
                    hex_data = hexlify(data)
                    self.logger.log(TRACE_LEVEL, "<<< IN {0} recv: {1} <<<".format(self.info, hex_data))
                self.request.sendall(data)

    def handle(self) -> None:
        """Handle the incoming request."""
        uid = generate_random_string(5)
        self.info = "#{0} <-- {1}".format(uid, self.client_address or self.server.local_address)
        src_address = self.request.getpeername()
        if not isinstance(src_address, tuple):
            src_address = ("dummy", 12345)
        try:
            chan = self.ssh_transport.open_channel(
                kind="direct-tcpip", dest_addr=self.remote_address, src_addr=src_address, timeout=TUNNEL_TIMEOUT
            )
        except Exception as e:  # pragma: no cover
            msg_tupe = "ssh " if isinstance(e, paramiko.SSHException) else ""
            exc_msg = "open new channel {0}error: {1}".format(msg_tupe, e)
            log_msg = "{0} {1}".format(self.info, exc_msg)
            self.logger.log(TRACE_LEVEL, log_msg)
            raise HandlerSSHTunnelForwarderError(exc_msg)

        self.logger.log(TRACE_LEVEL, "{0} connected".format(self.info))
        try:
            self._redirect(chan)
        except socket.error:
            # Sometimes a RST is sent and a socket error is raised, treat this
            # exception. It was seen that a 3way FIN is processed later on, so
            # no need to make an ordered close of the connection here or raise
            # the exception beyond this point...
            self.logger.log(TRACE_LEVEL, "{0} sending RST".format(self.info))
        except Exception as e:
            self.logger.log(TRACE_LEVEL, "{0} error: {1}".format(self.info, repr(e)))
        finally:
            chan.close()
            self.request.close()
            self.logger.log(TRACE_LEVEL, "{0} connection closed.".format(self.info))


class _ForwardServer(socketserver.TCPServer):  # Not Threading
    """Non-threading version of the forward server."""

    allow_reuse_address = True  # faster rebinding

    def __init__(self, *args, **kwargs):
        """Initialize the forward server with a logger and a tunnel queue."""
        logger = kwargs.pop("logger", None)
        self.logger = logger or create_logger()
        self.tunnel_ok = queue.Queue(1)
        socketserver.TCPServer.__init__(self, *args, **kwargs)

    def handle_error(self, request: socket.socket, client_address: tuple) -> None:
        """
        Handle errors that occur during request processing.

        :param request: The socket request that caused the error.
        :param client_address: The address of the client that made the request.
        """
        (exc_class, exc, tb) = sys.exc_info()
        local_side = request.getsockname()
        remote_side = self.remote_address
        self.logger.error(
            "Could not establish connection from local {0} " "to remote {1} side of the tunnel: {2}".format(
                local_side, remote_side, exc
            )
        )
        try:
            self.tunnel_ok.put(False, block=False, timeout=0.1)
        except queue.Full:
            # wait untill tunnel_ok.get is called
            pass
        except exc:
            self.logger.error("unexpected internal error: {0}".format(exc))

    @property
    def local_address(self) -> tuple:
        """Return the local address of the server."""
        return self.server_address

    @property
    def local_host(self) -> str:
        """Return the local host of the server."""
        return self.server_address[0]

    @property
    def local_port(self) -> int:
        """Return the local port of the server."""
        return self.server_address[1]

    @property
    def remote_address(self) -> tuple:
        """Return the remote address of the server."""
        return self.RequestHandlerClass.remote_address

    @property
    def remote_host(self) -> str:
        """Return the remote host of the server."""
        return self.RequestHandlerClass.remote_address[0]

    @property
    def remote_port(self) -> int:
        """Return the remote port of the server."""
        return self.RequestHandlerClass.remote_address[1]


class _ThreadingForwardServer(socketserver.ThreadingMixIn, _ForwardServer):
    """Allow concurrent connections to each tunnel."""

    # If True, cleanly stop threads created by ThreadingMixIn when quitting
    # This value is overrides by SSHTunnelForwarder.daemon_forward_servers
    daemon_threads = _DAEMON


class _StreamForwardServer(_StreamServer):
    """Serve over domain sockets (does not work on Windows)."""

    def __init__(self, *args, **kwargs):
        """Initialize the stream forward server with a logger and a tunnel queue."""
        logger = kwargs.pop("logger", None)
        self.logger = logger or create_logger()
        self.tunnel_ok = queue.Queue(1)
        _StreamServer.__init__(self, *args, **kwargs)

    @property
    def local_address(self) -> tuple:
        """Return the local address of the server."""
        return self.server_address

    @property
    def local_host(self) -> None:
        """Return the local host of the server."""
        return None

    @property
    def local_port(self) -> None:
        """Return the local port of the server."""
        return None

    @property
    def remote_address(self) -> tuple:
        """Return the remote address of the server."""
        return self.RequestHandlerClass.remote_address

    @property
    def remote_host(self) -> str:
        """Return the remote host of the server."""
        return self.RequestHandlerClass.remote_address[0]

    @property
    def remote_port(self) -> int:
        """Return the remote port of the server."""
        return self.RequestHandlerClass.remote_address[1]


class _ThreadingStreamForwardServer(socketserver.ThreadingMixIn, _StreamForwardServer):
    """Allow concurrent connections to each tunnel."""

    # If True, cleanly stop threads created by ThreadingMixIn when quitting
    # This value is overrides by SSHTunnelForwarder.daemon_forward_servers
    daemon_threads = _DAEMON


class SSHTunnelForwarder(object):
    """
    SSH tunnel class.

    - Initialize a SSH tunnel to a remote host according to the input arguments.
    - Optionally:
      - Read an SSH configuration file (typically ``~/.ssh/config``).
      - Load keys from a running SSH agent (i.e., Pageant, GNOME Keyring).

    Raises
    ------
        BaseSSHTunnelForwarderError: Raised by SSHTunnelForwarder class methods.
        HandlerSSHTunnelForwarderError: Raised by tunnel forwarder threads.

    Attributes
    ----------
        tunnel_is_up (dict):
            Describe whether or not the other side of the tunnel was reported
            to be up (and we must close it) or not (skip shutting down that
            tunnel).

            Example::

                {('127.0.0.1', 55550): True,   # this tunnel is up
                 ('127.0.0.1', 55551): False}  # this one isn't

            where 55550 and 55551 are the local bind ports.

        skip_tunnel_checkup (bool):
            Disable tunnel checkup (default for backwards compatibility).
    """

    skip_tunnel_checkup = True
    # This option affects the `ForwardServer` and all his threads
    daemon_forward_servers = _DAEMON  #: flag tunnel threads in daemon mode
    # This option affect only `Transport` thread
    daemon_transport = _DAEMON  #: flag SSH transport thread in daemon mode

    def local_is_up(self, target: tuple) -> bool:
        """
        Check if a tunnel is up.

        (remote target's host is reachable on TCP target's port).

        :param target: A tuple of type (``str``, ``int``) indicating the
            listen IP address and port, or a valid UNIX domain socket path.
        :return: True if the tunnel is up, False otherwise.
        """
        try:
            check_address(target)
        except ValueError:
            self.logger.warning(
                "Target must be a tuple (IP, port), where IP "
                'is a string (i.e. "192.168.0.1") and port is '
                "an integer (i.e. 40000). Alternatively "
                "target can be a valid UNIX domain socket."
            )
            return False

        self.check_tunnels()
        return self.tunnel_is_up.get(target, True)

    def check_tunnels(self) -> None:
        """
        Check that if all tunnels are established and populates.

        :attr:`.tunnel_is_up`.
        """
        skip_tunnel_checkup = self.skip_tunnel_checkup
        try:
            # force tunnel check at this point
            self.skip_tunnel_checkup = False
            for _srv in self._server_list:
                self._check_tunnel(_srv)
        finally:
            self.skip_tunnel_checkup = skip_tunnel_checkup  # roll it back

    def _check_tunnel(self, _srv: object) -> None:
        """
        Check if tunnel is already established.

        :param _srv: The server object to check.
        :raises BaseSSHTunnelForwarderError: If the tunnel cannot be checked.
        """
        if self.skip_tunnel_checkup:
            self.tunnel_is_up[_srv.local_address] = True
            return
        self.logger.info("Checking tunnel to: {0}".format(_srv.remote_address))
        if isinstance(_srv.local_address, string_types):  # UNIX stream
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        else:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(TUNNEL_TIMEOUT)
        try:
            # Windows raises WinError 10049 if trying to connect to 0.0.0.0
            connect_to = ("127.0.0.1", _srv.local_port) if _srv.local_host == "0.0.0.0" else _srv.local_address
            s.connect(connect_to)
            self.tunnel_is_up[_srv.local_address] = _srv.tunnel_ok.get(timeout=TUNNEL_TIMEOUT * 1.1)
            self.logger.debug("Tunnel to {0} is DOWN".format(_srv.remote_address))
        except socket.error:
            self.logger.debug("Tunnel to {0} is DOWN".format(_srv.remote_address))
            self.tunnel_is_up[_srv.local_address] = False

        except queue.Empty:
            self.logger.debug("Tunnel to {0} is UP".format(_srv.remote_address))
            self.tunnel_is_up[_srv.local_address] = True
        finally:
            s.close()

    def _make_ssh_forward_handler_class(self, remote_address_: tuple) -> type:
        """
        Make SSH Handler class.

        :param remote_address_: The remote address to forward to.
        :return: A handler class that can handle SSH forwarding requests.
        """

        class Handler(_ForwardHandler):
            """Handle SSH forwarding requests."""

            remote_address = remote_address_
            ssh_transport = self._transport
            logger = self.logger

        return Handler

    def _make_ssh_forward_server_class(self, remote_address_: tuple) -> type:
        """
        Make SSH forward proxy Server class.

        :param remote_address_: The remote address to forward to.
        :return: The appropriate server class based on threading.
        """
        return _ThreadingForwardServer if self._threaded else _ForwardServer

    def _make_stream_ssh_forward_server_class(self, remote_address_: tuple) -> type:
        """
        Make SSH stream forward proxy Server class.

        :param remote_address_: The remote address to forward to.
        :return: The appropriate server class based on threading.
        """
        return _ThreadingStreamForwardServer if self._threaded else _StreamForwardServer

    def _make_ssh_forward_server(self, remote_address: tuple, local_bind_address: tuple) -> None:
        """
        Make SSH forward proxy Server class.

        :param remote_address: The remote address to forward to.
        :param local_bind_address: The local bind address to listen on.
        :raises BaseSSHTunnelForwarderError: If there is a problem setting up the
            SSH forwarder.
        :raises IOError: If the tunnel cannot be opened, possibly because
        the port is already in use or the destination is not reachable.
        """
        _Handler = self._make_ssh_forward_handler_class(remote_address)
        try:
            forward_maker_class = (
                self._make_stream_ssh_forward_server_class
                if isinstance(local_bind_address, string_types)
                else self._make_ssh_forward_server_class
            )
            _Server = forward_maker_class(remote_address)
            ssh_forward_server = _Server(
                local_bind_address,
                _Handler,
                logger=self.logger,
            )

            if ssh_forward_server:
                ssh_forward_server.daemon_threads = self.daemon_forward_servers
                self._server_list.append(ssh_forward_server)
                self.tunnel_is_up[ssh_forward_server.server_address] = False
            else:
                self._raise(
                    BaseSSHTunnelForwarderError,
                    "Problem setting up ssh {0} <> {1} forwarder. You can "
                    "suppress this exception by using the `mute_exceptions`"
                    "argument".format(address_to_str(local_bind_address), address_to_str(remote_address)),
                )
        except IOError:
            self._raise(
                BaseSSHTunnelForwarderError,
                "Couldn't open tunnel {0} <> {1} might be in use or " "destination not reachable".format(
                    address_to_str(local_bind_address), address_to_str(remote_address)
                ),
            )

    def __init__(
        self,
        ssh_address_or_host: str | tuple = None,
        ssh_config_file: str = SSH_CONFIG_FILE,
        ssh_host_key: str | None = None,
        ssh_password: str | None = None,
        ssh_pkey: str | None = None,
        ssh_private_key_password: str | None = None,
        ssh_proxy: str | None = None,
        ssh_proxy_enabled: bool = True,
        ssh_username: str | None = None,
        local_bind_address: tuple | None = None,
        local_bind_addresses: list[tuple] | None = None,
        logger: logging.Logger | None = None,
        mute_exceptions: bool = False,
        remote_bind_address: tuple | None = None,
        remote_bind_addresses: list[tuple] | None = None,
        set_keepalive: float = 5.0,
        threaded: bool = True,  # old version False
        compression: str | None = None,
        allow_agent: bool = True,  # look for keys from an SSH agent
        host_pkey_directories: list[str] | None = None,  # look for keys in ~/.ssh
        *args,
        **kwargs,  # for backwards compatibility
    ):
        """
        Initialize the SSH tunnel forwarder.

        :param ssh_address_or_host: The SSH address or host to connect to.
        :param ssh_config_file: Path to the SSH configuration file.
        :param ssh_host_key: The SSH host key to use.
        :param ssh_password: The SSH password to use.
        :param ssh_pkey: The SSH private key file to use.
        :param ssh_private_key_password: The password for the SSH private key.
        :param ssh_proxy: The SSH proxy command to use.
        :param ssh_proxy_enabled: Whether to enable the SSH proxy.
        :param ssh_username: The SSH username to use.
        :param local_bind_address: The local bind address (IP, port) for the tunnel.
        :param local_bind_addresses: A list of local bind addresses (IP, port) for the tunnel.
        :param logger: A logger instance for logging messages.
        :param mute_exceptions: Whether to suppress exceptions.
        :param remote_bind_address: The remote bind address (IP, port) for the tunnel.
        :param remote_bind_addresses: A list of remote bind addresses (IP, port) for the tunnel.
        :param set_keepalive: The keepalive interval for the SSH connection.
        :param threaded: Whether to allow concurrent connections to the tunnel.
        :param compression: Compression setting for the SSH connection.
        :param allow_agent: Whether to look for keys from an SSH agent.
        :param host_pkey_directories: Directories to look for host private keys.
        :param args: Additional positional arguments (for backwards compatibility).
        :param kwargs: Additional keyword arguments (for backwards compatibility).
        :raises ValueError: If any of the arguments are invalid.
        :raises AssertionError: If the SSH address or port is invalid.
        :raises IOError: If the SSH configuration file cannot be read.
        :raises AttributeError: If the SSH configuration file is None.
        :raises TypeError: If the SSH configuration file is not a string or None.
        """
        self.logger = logger or create_logger()

        self.ssh_host_key = ssh_host_key
        self.set_keepalive = set_keepalive
        self._server_list = []  # reset server list
        self.tunnel_is_up = {}  # handle tunnel status
        self._threaded = threaded
        self.is_alive = False
        # Check if deprecated arguments ssh_address or ssh_host were used
        for deprecated_argument in ["ssh_address", "ssh_host"]:
            ssh_address_or_host = self._process_deprecated(ssh_address_or_host, deprecated_argument, kwargs)
        # other deprecated arguments
        ssh_pkey = self._process_deprecated(ssh_pkey, "ssh_private_key", kwargs)

        self._raise_fwd_exc = (
            self._process_deprecated(None, "raise_exception_if_any_forwarder_have_a_problem", kwargs)
            or not mute_exceptions
        )

        if isinstance(ssh_address_or_host, tuple):
            check_address(ssh_address_or_host)
            (ssh_host, ssh_port) = ssh_address_or_host
        else:
            ssh_host = ssh_address_or_host
            ssh_port = kwargs.pop("ssh_port", None)

        if kwargs:
            raise ValueError("Unknown arguments: {0}".format(kwargs))

        # remote binds
        self._remote_binds = self._get_binds(remote_bind_address, remote_bind_addresses, is_remote=True)
        # local binds
        self._local_binds = self._get_binds(local_bind_address, local_bind_addresses)
        self._local_binds = self._consolidate_binds(self._local_binds, self._remote_binds)

        (
            self.ssh_host,
            self.ssh_username,
            ssh_pkey,  # still needs to go through _consolidate_auth
            self.ssh_port,
            self.ssh_proxy,
            self.compression,
        ) = self._read_ssh_config(
            ssh_host,
            ssh_config_file,
            ssh_username,
            ssh_pkey,
            ssh_port,
            ssh_proxy if ssh_proxy_enabled else None,
            compression,
            self.logger,
        )

        (self.ssh_password, self.ssh_pkeys) = self._consolidate_auth(
            ssh_password=ssh_password,
            ssh_pkey=ssh_pkey,
            ssh_pkey_password=ssh_private_key_password,
            allow_agent=allow_agent,
            host_pkey_directories=host_pkey_directories,
            logger=self.logger,
        )

        check_host(self.ssh_host)
        check_port(self.ssh_port)

        self.logger.info(
            "Connecting to gateway: {0}:{1} as user '{2}'".format(self.ssh_host, self.ssh_port, self.ssh_username)
        )

        self.logger.debug("Concurrent connections allowed: {0}".format(self._threaded))

    @staticmethod
    def _read_ssh_config(
        ssh_host: str,
        ssh_config_file: str | None,
        ssh_username: str | None = None,
        ssh_pkey: str | None = None,
        ssh_port: int | None = None,
        ssh_proxy: paramiko.ProxyCommand | None = None,
        compression: str | None = None,
        logger: logging.Logger | None = None,
    ) -> tuple[str, str, str | None, int, paramiko.ProxyCommand | None, bool]:
        """
        Read SSH configuration file.

        :param ssh_host: The SSH host to connect to.
        :param ssh_config_file: Path to the SSH configuration file.
        :param ssh_username: The SSH username to use.
        :param ssh_pkey: The SSH private key file to use.
        :param ssh_port: The SSH port to connect to.
        :param ssh_proxy: The SSH proxy command to use.
        :param compression: Compression setting for the SSH connection.
        :param logger: Logger instance for logging messages.
        :return: A tuple containing the SSH host, username, port, pkey, proxy command and compression settings.
        :raises IOError: If the SSH configuration file cannot be read.
        :raises AttributeError: If the SSH configuration file is None.
        :raises TypeError: If the SSH configuration file is not a string or None.
        :raises ValueError: If the SSH configuration file is not a valid path.
        :raises AssertionError: If the SSH host is not a string, or if the SSH port is not an integer or is less than 0.

        Return the SSH host, username, port, pkey, proxy command and compression settings.
        """
        ssh_config = paramiko.SSHConfig()
        if not ssh_config_file:  # handle case where it's an empty string
            ssh_config_file = None
            pass  # Add a placeholder statement to fix the syntax error

        # Try to read SSH_CONFIG_FILE
        try:
            # open the ssh config file
            with open(os.path.expanduser(ssh_config_file), "r") as f:
                ssh_config.parse(f)
            # looks for information for the destination system
            hostname_info = ssh_config.lookup(ssh_host)
            # gather settings for user, port and identity file
            # last resort: use the 'login name' of the user
            ssh_username = ssh_username or hostname_info.get("user")
            ssh_pkey = ssh_pkey or hostname_info.get("identityfile", [None])[0]
            ssh_host = hostname_info.get("hostname")
            ssh_port = ssh_port or hostname_info.get("port")

            proxycommand = hostname_info.get("proxycommand")
            ssh_proxy = ssh_proxy or (paramiko.ProxyCommand(proxycommand) if proxycommand else None)
            if compression is None:
                compression = hostname_info.get("compression", "")
                compression = True if compression.upper() == "YES" else False
        except IOError:
            if logger:
                logger.warning("Could not read SSH configuration file: {0}".format(ssh_config_file))
        except (AttributeError, TypeError):  # ssh_config_file is None
            if logger:
                logger.info("Skipping loading of ssh configuration file")
        finally:
            return (
                ssh_host,
                ssh_username or getpass.getuser(),
                ssh_pkey,
                int(ssh_port) if ssh_port else 22,  # fallback value
                ssh_proxy,
                compression,
            )

    @staticmethod
    def get_agent_keys(logger: logging.Logger | None = None) -> list:
        """
        Load public keys from any available SSH agent.

        ::param logger: Logger instance for logging messages.
        :return: A list of loaded SSH keys.
        :raises ValueError: If no keys are found and no password is provided.
        """
        paramiko_agent = paramiko.Agent()
        agent_keys = paramiko_agent.get_keys()
        if logger:
            logger.info("{0} keys loaded from agent".format(len(agent_keys)))
        return list(agent_keys)

    @staticmethod
    def get_keys(
        logger: logging.Logger | None = None, host_pkey_directories: list[str] | None = None, allow_agent: bool = False
    ) -> list:
        """
        Load public keys from any available SSH agent or local .ssh directory.

        :param logger: Logger instance for logging messages.
        :param host_pkey_directories: List of directories to search for SSH keys.
        :param allow_agent: Whether to load keys from an SSH agent.
        :return: A list of loaded SSH keys.
        :raises ValueError: If no keys are found and no password is provided.
        """
        keys = SSHTunnelForwarder.get_agent_keys(logger=logger) if allow_agent else []

        if host_pkey_directories is None:
            host_pkey_directories = [DEFAULT_SSH_DIRECTORY]

        paramiko_key_types = {"rsa": paramiko.RSAKey, "dsa": paramiko.DSSKey, "ecdsa": paramiko.ECDSAKey}
        if hasattr(paramiko, "Ed25519Key"):
            paramiko_key_types["ed25519"] = paramiko.Ed25519Key
        for directory in host_pkey_directories:
            for keytype in paramiko_key_types.keys():
                ssh_pkey_expanded = os.path.expanduser(os.path.join(directory, "id_{}".format(keytype)))
                try:
                    if os.path.isfile(ssh_pkey_expanded):
                        ssh_pkey = SSHTunnelForwarder.read_private_key_file(
                            pkey_file=ssh_pkey_expanded, logger=logger, key_type=paramiko_key_types[keytype]
                        )
                        if ssh_pkey:
                            keys.append(ssh_pkey)
                except OSError as exc:
                    if logger:
                        logger.warning("Private key file {0} check error: {1}".format(ssh_pkey_expanded, exc))
        if logger:
            logger.info("{0} key(s) loaded".format(len(keys)))
        return keys

    @staticmethod
    def _consolidate_binds(local_binds: list[tuple] | None, remote_binds: list[tuple] | None) -> list[tuple]:
        """
        Fill local_binds with defaults when no value/s were specified.

        leaving paramiko to decide in which local port the tunnel will be open.

        :param local_binds: List of local bind addresses (IP, port).
        :param remote_binds: List of remote bind addresses (IP, port).
        :return: A list of local bind addresses, filled with defaults if necessary.
        """
        count = len(remote_binds) - len(local_binds)
        if count < 0:
            raise ValueError("Too many local bind addresses " "(local_bind_addresses > remote_bind_addresses)")
        local_binds.extend([("0.0.0.0", 0) for x in range(count)])
        return local_binds

    @staticmethod
    def _consolidate_auth(
        ssh_password: str | None = None,
        ssh_pkey: str | None = None,
        ssh_pkey_password: str | None = None,
        allow_agent: bool = True,
        host_pkey_directories: list[str] | None = None,
        logger: logging.Logger | None = None,
    ) -> tuple[str | None, list[paramiko.pkey.PKey]]:
        """
        Get sure authentication information is in place.

        :param ssh_password: SSH password for the user.
        :param ssh_pkey: SSH private key file or paramiko.Pkey object.
        :param ssh_pkey_password: Password for the SSH private key.
        :param allow_agent: Whether to load keys from an SSH agent.
        :param host_pkey_directories: Directories to search for SSH keys.
        :param logger: Logger instance for logging messages.
        :return: A tuple containing the SSH password and a list of loaded SSH keys.

        ``ssh_pkey`` may be of classes:
            - ``str`` - in this case it represents a private key file; public
            key will be obtained from it
            - ``paramiko.Pkey`` - it will be transparently added to loaded keys.

        """
        ssh_loaded_pkeys = SSHTunnelForwarder.get_keys(
            logger=logger, host_pkey_directories=host_pkey_directories, allow_agent=allow_agent
        )

        if isinstance(ssh_pkey, string_types):
            ssh_pkey_expanded = os.path.expanduser(ssh_pkey)
            if os.path.exists(ssh_pkey_expanded):
                ssh_pkey = SSHTunnelForwarder.read_private_key_file(
                    pkey_file=ssh_pkey_expanded, pkey_password=ssh_pkey_password or ssh_password, logger=logger
                )
            elif logger:
                logger.warning("Private key file not found: {0}".format(ssh_pkey))
        if isinstance(ssh_pkey, paramiko.pkey.PKey):
            ssh_loaded_pkeys.insert(0, ssh_pkey)

        if ssh_password is None and not ssh_loaded_pkeys:
            raise ValueError("No password or public key available!")
        return (ssh_password, ssh_loaded_pkeys)

    def _raise(
        self, exception: type[BaseSSHTunnelForwarderError] = BaseSSHTunnelForwarderError, reason: str | None = None
    ) -> None:
        if self._raise_fwd_exc:
            raise exception(reason)
        else:
            self.logger.error(repr(exception(reason)))

    def _get_transport(self) -> paramiko.Transport:
        """Return the SSH transport to the remote gateway."""
        if self.ssh_proxy:
            if isinstance(self.ssh_proxy, paramiko.proxy.ProxyCommand):
                proxy_repr = repr(self.ssh_proxy.cmd[1])
            else:
                proxy_repr = repr(self.ssh_proxy)
            self.logger.debug("Connecting via proxy: {0}".format(proxy_repr))
            _socket = self.ssh_proxy
        else:
            _socket = (self.ssh_host, self.ssh_port)
        if isinstance(_socket, socket.socket):
            _socket.settimeout(SSH_TIMEOUT)
            _socket.connect((self.ssh_host, self.ssh_port))
        transport = paramiko.Transport(_socket)
        sock = transport.sock
        if isinstance(sock, socket.socket):
            sock.settimeout(SSH_TIMEOUT)
        transport.set_keepalive(self.set_keepalive)
        transport.use_compression(compress=self.compression)
        transport.daemon = self.daemon_transport
        # try to solve https://github.com/paramiko/paramiko/issues/1181
        # transport.banner_timeout = 200
        if isinstance(sock, socket.socket):
            sock_timeout = sock.gettimeout()
            sock_info = repr((sock.family, sock.type, sock.proto))
            self.logger.debug("Transport socket info: {0}, timeout={1}".format(sock_info, sock_timeout))
        return transport

    def _create_tunnels(self) -> None:
        """Create SSH tunnels on top of a transport to the remote gateway."""
        if not self.is_active:
            try:
                self._connect_to_gateway()
            except socket.gaierror:  # raised by paramiko.Transport
                msg = "Could not resolve IP address for {0}, aborting!".format(self.ssh_host)
                self.logger.error(msg)
                return
            except (paramiko.SSHException, socket.error) as e:
                template = "Could not connect to gateway {0}:{1} : {2}"
                msg = template.format(self.ssh_host, self.ssh_port, e.args[0])
                self.logger.error(msg)
                return
        for rem, loc in zip(self._remote_binds, self._local_binds):
            try:
                self._make_ssh_forward_server(rem, loc)
            except BaseSSHTunnelForwarderError as e:
                msg = "Problem setting SSH Forwarder up: {0}".format(e.value)
                self.logger.error(msg)

    @staticmethod
    def _get_binds(
        bind_address: tuple | None, bind_addresses: list[tuple] | None, is_remote: bool = False
    ) -> list[tuple]:
        """
        Get bind addresses for local or remote tunnels.

        :param bind_address: A single bind address (IP, port) tuple.
        :param bind_addresses: A list of bind addresses (IP, port) tuples.
        :param is_remote: If True, the bind addresses are for remote tunnels.
        :return: A list of bind addresses (IP, port) tuples.
        :raises ValueError: If both bind_address and bind_addresses are provided,
            or if neither is provided when is_remote is True.
        """
        addr_kind = "remote" if is_remote else "local"

        if not bind_address and not bind_addresses:
            if is_remote:
                raise ValueError(
                    "No {0} bind addresses specified. Use "
                    "'{0}_bind_address' or '{0}_bind_addresses'"
                    " argument".format(addr_kind)
                )
            else:
                return []
        elif bind_address and bind_addresses:
            raise ValueError(
                "You can't use both '{0}_bind_address' and "
                "'{0}_bind_addresses' arguments. Use one of "
                "them.".format(addr_kind)
            )
        if bind_address:
            bind_addresses = [bind_address]
        if not is_remote:
            # Add random port if missing in local bind
            for i, local_bind in enumerate(bind_addresses):
                if isinstance(local_bind, tuple) and len(local_bind) == 1:
                    bind_addresses[i] = (local_bind[0], 0)
        check_addresses(bind_addresses, is_remote)
        return bind_addresses

    @staticmethod
    def _process_deprecated(attrib: str | None, deprecated_attrib: str, kwargs: dict) -> str | None:
        """
        Process optional deprecate arguments.

        :param attrib: The attribute to check for deprecation.
        :param deprecated_attrib: The name of the deprecated attribute.
        :param kwargs: The keyword arguments to check for the deprecated attribute.
        :return: The value of the deprecated attribute if it exists in kwargs, otherwise returns attrib
        """
        if deprecated_attrib not in _DEPRECATIONS:
            raise ValueError("{0} not included in deprecations list".format(deprecated_attrib))
        if deprecated_attrib in kwargs:
            warnings.warn(
                "'{0}' is DEPRECATED use '{1}' instead".format(deprecated_attrib, _DEPRECATIONS[deprecated_attrib]),
                DeprecationWarning,
            )
            if attrib:
                raise ValueError(
                    "You can't use both '{0}' and '{1}'. " "Please only use one of them".format(
                        deprecated_attrib, _DEPRECATIONS[deprecated_attrib]
                    )
                )
            else:
                return kwargs.pop(deprecated_attrib)
        return attrib

    @staticmethod
    def read_private_key_file(
        pkey_file: str,
        pkey_password: str | None = None,
        key_type: type | None = None,
        logger: logging.Logger | None = None,
    ) -> paramiko.PKey | None:
        """
        Get SSH Public key from a private key file, given an optional password.

        :param pkey_file: The path to the private key file. File containing a private key (RSA, DSS or ECDSA)
        :param pkey_password: The password to decrypt the private key.
        :param key_type: The type of the key to read (e.g., paramiko.RSAKey).
            If None, it will try to read the key as RSA, DSS, ECDSA, and Ed25519
            in that order.
        :param logger: Optional logger to log debug messages.
        :return: An instance of paramiko.PKey or None if the key could not be loaded.
        """
        ssh_pkey = None
        key_types = (paramiko.RSAKey, paramiko.DSSKey, paramiko.ECDSAKey)
        if hasattr(paramiko, "Ed25519Key"):
            key_types += (paramiko.Ed25519Key,)
        for pkey_class in (key_type,) if key_type else key_types:
            try:
                ssh_pkey = pkey_class.from_private_key_file(pkey_file, password=pkey_password)
                if logger:
                    logger.debug("Private key file ({0}, {1}) successfully " "loaded".format(pkey_file, pkey_class))
                break
            except paramiko.PasswordRequiredException:
                if logger:
                    logger.error("Password is required for key {0}".format(pkey_file))
                break
            except paramiko.SSHException:
                if logger:
                    logger.debug(
                        "Private key file ({0}) could not be loaded " "as type {1} or bad password".format(
                            pkey_file, pkey_class
                        )
                    )
        return ssh_pkey

    def start(self) -> None:
        """
        Start the SSH tunnels.

        :raises BaseSSHTunnelForwarderError: If the session to the SSH gateway cannot be established.
        :raises HandlerSSHTunnelForwarderError: If an error occurs while opening tunnels.
        """
        if self.is_alive:
            self.logger.warning("Already started!")
            return
        self._create_tunnels()
        if not self.is_active:
            self._raise(BaseSSHTunnelForwarderError, reason="Could not establish session to SSH gateway")
        for _srv in self._server_list:
            thread = threading.Thread(
                target=self._serve_forever_wrapper, args=(_srv,), name="Srv-{0}".format(address_to_str(_srv.local_port))
            )
            thread.daemon = self.daemon_forward_servers
            thread.start()
            self._check_tunnel(_srv)
        self.is_alive = any(self.tunnel_is_up.values())
        if not self.is_alive:
            self._raise(HandlerSSHTunnelForwarderError, "An error occurred while opening tunnels.")

    def stop(self, force: bool = False) -> None:
        """
        Shut the tunnel down. By default we are always waiting until closing all connections.

        You can use `force=True` to force close connections.

        :param force: If True, close the transport immediately without waiting for connections.

        Keyword Arguments:
        -----------------
            force (bool):
                Force close current connections

                Default: False

                .. versionadded:: 0.2.2

        .. note:: This **had** to be handled with care before ``0.1.0``:

            - if a port redirection is opened
            - the destination is not reachable
            - we attempt a connection to that tunnel (``SYN`` is sent and
              acknowledged, then a ``FIN`` packet is sent and never
              acknowledged... weird)
            - we try to shutdown: it will not succeed until ``FIN_WAIT_2`` and
              ``CLOSE_WAIT`` time out.

        .. note::
            Handle these scenarios with :attr:`.tunnel_is_up`: if False, server
            ``shutdown()`` will be skipped on that tunnel
        """
        self.logger.info("Closing all open connections...")
        opened_address_text = ", ".join((address_to_str(k.local_address) for k in self._server_list)) or "None"
        self.logger.debug("Listening tunnels: " + opened_address_text)
        self._stop_transport(force=force)
        self._server_list = []  # reset server list
        self.tunnel_is_up = {}  # reset tunnel status

    def close(self) -> None:
        """Stop the an active tunnel, alias to :meth:`.stop`."""
        self.stop()

    def restart(self) -> None:
        """Restart connection to the gateway and tunnels."""
        self.stop()
        self.start()

    def _connect_to_gateway(self) -> None:
        """
        Open connection to SSH gateway.

         - First try with all keys loaded from an SSH agent (if allowed)
         - Then with those passed directly or read from ~/.ssh/config
         - As last resort, try with a provided password.
        """
        for key in self.ssh_pkeys:
            self.logger.debug("Trying to log in with key: {0}".format(hexlify(key.get_fingerprint())))
            try:
                self._transport = self._get_transport()
                self._transport.connect(hostkey=self.ssh_host_key, username=self.ssh_username, pkey=key)
                if self._transport.is_alive:
                    return
            except paramiko.AuthenticationException:
                self.logger.debug("Authentication error")
                self._stop_transport()

        if self.ssh_password is not None:  # avoid conflict using both pass and pkey
            self.logger.debug("Trying to log in with password: {0}".format("*" * len(self.ssh_password)))
            try:
                self._transport = self._get_transport()
                self._transport.connect(
                    hostkey=self.ssh_host_key, username=self.ssh_username, password=self.ssh_password
                )
                if self._transport.is_alive:
                    return
            except paramiko.AuthenticationException:
                self.logger.debug("Authentication error")
                self._stop_transport()

        self.logger.error("Could not open connection to gateway")

    def _serve_forever_wrapper(self, _srv: _StreamForwardServer, poll_interval: float = 0.1) -> None:
        """
        Serve the tunnel forever.

        :param _srv: The server to serve forever.
        :param poll_interval: The interval to poll for new connections.
        """
        self.logger.info(
            "Opening tunnel: {0} <> {1}".format(address_to_str(_srv.local_address), address_to_str(_srv.remote_address))
        )
        _srv.serve_forever(poll_interval)  # blocks until finished

        self.logger.info(
            "Tunnel: {0} <> {1} released".format(
                address_to_str(_srv.local_address), address_to_str(_srv.remote_address)
            )
        )

    def _stop_transport(self, force: bool = False) -> None:
        """
        Close the underlying transport when nothing more is needed.

        :param force: If True, close the transport immediately without waiting for connections.
        """
        try:
            self._check_is_started()
        except (BaseSSHTunnelForwarderError, HandlerSSHTunnelForwarderError) as e:
            self.logger.warning(e)
        if force and self.is_active:
            # don't wait connections
            self.logger.info("Closing ssh transport")
            self._transport.close()
            self._transport.stop_thread()
        for _srv in self._server_list:
            status = "up" if self.tunnel_is_up[_srv.local_address] else "down"
            self.logger.info(
                "Shutting down tunnel: {0} <> {1} ({2})".format(
                    address_to_str(_srv.local_address), address_to_str(_srv.remote_address), status
                )
            )
            _srv.shutdown()
            _srv.server_close()
            # clean up the UNIX domain socket if we're using one
            if isinstance(_srv, _StreamForwardServer):
                try:
                    os.unlink(_srv.local_address)
                except Exception as e:
                    self.logger.error("Unable to unlink socket {0}: {1}".format(_srv.local_address, repr(e)))
        self.is_alive = False
        if self.is_active:
            self.logger.info("Closing ssh transport")
            self._transport.close()
            self._transport.stop_thread()
        self.logger.debug("Transport is closed")

    @property
    def local_bind_port(self) -> int:
        """Return the port number listening for the tunnel."""
        # BACKWARDS COMPATIBILITY
        self._check_is_started()
        if len(self._server_list) != 1:
            raise BaseSSHTunnelForwarderError("Use .local_bind_ports property for more than one tunnel")
        return self.local_bind_ports[0]

    @property
    def local_bind_host(self) -> str:
        """Return the IP address listening for the tunnel."""
        # BACKWARDS COMPATIBILITY
        self._check_is_started()
        if len(self._server_list) != 1:
            raise BaseSSHTunnelForwarderError("Use .local_bind_hosts property for more than one tunnel")
        return self.local_bind_hosts[0]

    @property
    def local_bind_address(self) -> tuple[str, int]:
        """Return a tuple containing the local bind address (IP, port) of the tunnel."""
        # BACKWARDS COMPATIBILITY
        self._check_is_started()
        if len(self._server_list) != 1:
            raise BaseSSHTunnelForwarderError("Use .local_bind_addresses property for more than one tunnel")
        return self.local_bind_addresses[0]

    @property
    def local_bind_ports(self) -> list[int]:
        """Return a list containing the ports of local side of the TCP tunnels."""
        self._check_is_started()
        return [_server.local_port for _server in self._server_list if _server.local_port is not None]

    @property
    def local_bind_hosts(self) -> list[str]:
        """Return a list containing the IP addresses listening for the tunnels."""
        self._check_is_started()
        return [_server.local_host for _server in self._server_list if _server.local_host is not None]

    @property
    def local_bind_addresses(self) -> list[tuple[str, int]]:
        """Return a list of (IP, port) pairs for the local side of the tunnels."""
        self._check_is_started()
        return [_server.local_address for _server in self._server_list]

    @property
    def tunnel_bindings(self) -> dict[tuple[str, int], tuple[str, int]]:
        """Return a dictionary containing the active local<>remote tunnel_bindings."""
        return dict(
            (_server.remote_address, _server.local_address)
            for _server in self._server_list
            if self.tunnel_is_up[_server.local_address]
        )

    @property
    def is_active(self) -> bool:
        """Return True if the underlying SSH transport is up."""
        if "_transport" in self.__dict__ and self._transport.is_active():
            return True
        return False

    def _check_is_started(self) -> None:
        """Check if the tunnel is started."""
        if not self.is_active:  # underlying transport not alive
            msg = "Server is not started. Please .start() first!"
            raise BaseSSHTunnelForwarderError(msg)
        if not self.is_alive:
            msg = "Tunnels are not started. Please .start() first!"
            raise HandlerSSHTunnelForwarderError(msg)

    def __str__(self) -> str:
        """Return a string representation of the SSHTunnelForwarder object."""
        credentials = {
            "password": self.ssh_password,
            "pkeys": [(key.get_name(), hexlify(key.get_fingerprint())) for key in self.ssh_pkeys]
            if any(self.ssh_pkeys)
            else None,
        }
        _remove_none_values(credentials)
        template = os.linesep.join(
            [
                "{0} object",
                "ssh gateway: {1}:{2}",
                "proxy: {3}",
                "username: {4}",
                "authentication: {5}",
                "hostkey: {6}",
                "status: {7}started",
                "keepalive messages: {8}",
                "tunnel connection check: {9}",
                "concurrent connections: {10}allowed",
                "compression: {11}requested",
                "logging level: {12}",
                "local binds: {13}",
                "remote binds: {14}",
            ]
        )
        return template.format(
            self.__class__,
            self.ssh_host,
            self.ssh_port,
            self.ssh_proxy.cmd[1] if self.ssh_proxy else "no",
            self.ssh_username,
            credentials,
            self.ssh_host_key if self.ssh_host_key else "not checked",
            "" if self.is_alive else "not ",
            "disabled" if not self.set_keepalive else "every {0} sec".format(self.set_keepalive),
            "disabled" if self.skip_tunnel_checkup else "enabled",
            "" if self._threaded else "not ",
            "" if self.compression else "not ",
            logging.getLevelName(self.logger.level),
            self._local_binds,
            self._remote_binds,
        )

    def __repr__(self) -> str:
        """Return a string representation of the SSHTunnelForwarder object."""
        return self.__str__()

    def __enter__(self) -> "SSHTunnelForwarder":
        """Start the tunnel when entering the context manager."""
        try:
            self.start()
            return self
        except KeyboardInterrupt:
            self.__exit__()

    def __exit__(self, *args) -> None:
        """Close the tunnel when exiting the context manager."""
        self.stop(force=True)

    def __del__(self) -> None:
        """Ensure the tunnel is stopped when the object is deleted."""
        if self.is_active or hasattr(self, "is_alive") and self.is_alive:
            self.logger.warning(
                "It looks like you didn't call the .stop() before "
                "the SSHTunnelForwarder obj was collected by "
                "the garbage collector! Running .stop(force=True)"
            )
            self.stop(force=True)


def open_tunnel(*args: Any, **kwargs: Any) -> SSHTunnelForwarder:
    """
    Open an SSH Tunnel, wrapper for :class:`SSHTunnelForwarder`.

    :param destination: SSH server's IP address and port in the format
        (``ssh_address``, ``ssh_port``)
    :param skip_tunnel_checkup: Enable/disable the local side check and populate
    :param debug_level: log level for :class:`logging.Logger` instance, i.e. ``DEBUG``
    :param args: positional arguments for :class:`SSHTunnelForwarder`
    :param kwargs: keyword arguments for :class:`SSHTunnelForwarder`

    .. note::
        A value of ``debug_level`` set to 1 == ``TRACE`` enables tracing mode
    .. note::
        See :class:`SSHTunnelForwarder` for keyword arguments

    **Example**::

        from sshtunnel import open_tunnel

        with open_tunnel(SERVER,
                         ssh_username=SSH_USER,
                         ssh_port=22,
                         ssh_password=SSH_PASSWORD,
                         remote_bind_address=(REMOTE_HOST, REMOTE_PORT),
                         local_bind_address=('', LOCAL_PORT)) as server:
            def do_something(port):
                pass

            print("LOCAL PORTS:", server.local_bind_port)

            do_something(server.local_bind_port)
    """
    # Attach a console handler to the logger or create one if not passed
    loglevel = kwargs.pop("debug_level", None)
    logger = kwargs.get("logger", None) or create_logger(loglevel=loglevel)
    kwargs["logger"] = logger

    ssh_address_or_host = kwargs.pop("ssh_address_or_host", None)
    # Check if deprecated arguments ssh_address or ssh_host were used
    for deprecated_argument in ["ssh_address", "ssh_host"]:
        ssh_address_or_host = SSHTunnelForwarder._process_deprecated(ssh_address_or_host, deprecated_argument, kwargs)

    ssh_port = kwargs.pop("ssh_port", 22)
    skip_tunnel_checkup = kwargs.pop("skip_tunnel_checkup", True)
    block_on_close = kwargs.pop("block_on_close", None)
    if block_on_close:
        warnings.warn(
            "'block_on_close' is DEPRECATED. You should use either"
            " .stop() or .stop(force=True), depends on what you do"
            " with the active connections. This option has no"
            " affect since 0.3.0",
            DeprecationWarning,
        )
    if not args:
        if isinstance(ssh_address_or_host, tuple):
            args = (ssh_address_or_host,)
        else:
            args = ((ssh_address_or_host, ssh_port),)
    forwarder = SSHTunnelForwarder(*args, **kwargs)
    forwarder.skip_tunnel_checkup = skip_tunnel_checkup
    return forwarder


def _bindlist(input_str: str) -> tuple[str, int]:
    """
    Define type of data expected for remote and local bind address lists.

    Returns a tuple (ip_address, port) whose elements are (str, int).
    :param input_str: String in the format "IP_ADDRESS:PORT" or just "IP_ADDRESS".
    :raises argparse.ArgumentTypeError: If the input string is not in the expected format.
    :return: Tuple containing the IP address and port number.
    """
    try:
        ip_port = input_str.split(":")
        if len(ip_port) == 1:
            _ip = ip_port[0]
            _port = None
        else:
            (_ip, _port) = ip_port  # Ensure this line is properly formatted and separated
        if not _ip and not _port:
            raise AssertionError
        elif not _port:
            _port = "22"  # default port if not given
        return _ip, int(_port)
    except ValueError:
        raise argparse.ArgumentTypeError("Address tuple must be of type IP_ADDRESS:PORT")
    except AssertionError:
        raise argparse.ArgumentTypeError("Both IP:PORT can't be missing!")


def _parse_arguments(args: list[str] = None) -> argparse.Namespace:
    """Parse arguments directly passed from CLI."""
    parser = argparse.ArgumentParser(
        description="Pure python ssh tunnel utils\n" "Version {0}".format(__version__),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument(
        "ssh_address",
        type=str,
        help="SSH server IP address (GW for SSH tunnels)\n"
        'set with "-- ssh_address" if immediately after '
        "-R or -L",
    )

    parser.add_argument("-U", "--username", type=str, dest="ssh_username", help="SSH server account username")

    parser.add_argument(
        "-p", "--server_port", type=int, dest="ssh_port", default=22, help="SSH server TCP port (default: 22)"
    )

    parser.add_argument("-P", "--password", type=str, dest="ssh_password", help="SSH server account password")

    parser.add_argument(
        "-R",
        "--remote_bind_address",
        type=_bindlist,
        nargs="+",
        default=[],
        metavar="IP:PORT",
        required=True,
        dest="remote_bind_addresses",
        help="Remote bind address sequence: "
        "ip_1:port_1 ip_2:port_2 ... ip_n:port_n\n"
        "Equivalent to ssh -Lxxxx:IP_ADDRESS:PORT\n"
        "If port is omitted, defaults to 22.\n"
        "Example: -R 10.10.10.10: 10.10.10.10:5900",
    )

    parser.add_argument(
        "-L",
        "--local_bind_address",
        type=_bindlist,
        nargs="*",
        dest="local_bind_addresses",
        metavar="IP:PORT",
        help="Local bind address sequence: "
        "ip_1:port_1 ip_2:port_2 ... ip_n:port_n\n"
        "Elements may also be valid UNIX socket domains: \n"
        "/tmp/foo.sock /tmp/bar.sock ... /tmp/baz.sock\n"
        "Equivalent to ssh -LPORT:xxxxxxxxx:xxxx, "
        "being the local IP address optional.\n"
        "By default it will listen in all interfaces "
        "(0.0.0.0) and choose a random port.\n"
        "Example: -L :40000",
    )

    parser.add_argument("-k", "--ssh_host_key", type=str, help="Gateway's host key")

    parser.add_argument(
        "-K",
        "--private_key_file",
        dest="ssh_private_key",
        metavar="KEY_FILE",
        type=str,
        help="RSA/DSS/ECDSA private key file",
    )

    parser.add_argument(
        "-S",
        "--private_key_password",
        dest="ssh_private_key_password",
        metavar="KEY_PASSWORD",
        type=str,
        help="RSA/DSS/ECDSA private key password",
    )

    parser.add_argument("-t", "--threaded", action="store_true", help="Allow concurrent connections to each tunnel")

    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase output verbosity (default: {0})".format(logging.getLevelName(DEFAULT_LOGLEVEL)),
    )

    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version="%(prog)s {version}".format(version=__version__),
        help="Show version number and quit",
    )

    parser.add_argument(
        "-x",
        "--proxy",
        type=_bindlist,
        dest="ssh_proxy",
        metavar="IP:PORT",
        help="IP and port of SSH proxy to destination",
    )

    parser.add_argument(
        "-c",
        "--config",
        type=str,
        default=SSH_CONFIG_FILE,
        dest="ssh_config_file",
        help="SSH configuration file, defaults to {0}".format(SSH_CONFIG_FILE),
    )

    parser.add_argument(
        "-z",
        "--compress",
        action="store_true",
        dest="compression",
        help="Request server for compression over SSH transport",
    )

    parser.add_argument(
        "-n", "--noagent", action="store_false", dest="allow_agent", help="Disable looking for keys from an SSH agent"
    )

    parser.add_argument(
        "-d",
        "--host_pkey_directories",
        nargs="*",
        dest="host_pkey_directories",
        metavar="FOLDER",
        help="List of directories where SSH pkeys (in the format `id_*`) " "may be found",
    )
    return vars(parser.parse_args(args))


def _cli_main(args: list[str] = None, **extras) -> None:
    """Pass input arguments to open_tunnel.

    Mandatory: ssh_address, -R (remote bind address list)

    Optional:
    -U (username) we may gather it from SSH_CONFIG_FILE or current username
    -p (server_port), defaults to 22
    -P (password)
    -L (local_bind_address), default to 0.0.0.0:22
    -k (ssh_host_key)
    -K (private_key_file), may be gathered from SSH_CONFIG_FILE
    -S (private_key_password)
    -t (threaded), allow concurrent connections over tunnels
    -v (verbose), up to 3 (-vvv) to raise loglevel from ERROR to DEBUG
    -V (version)
    -x (proxy), ProxyCommand's IP:PORT, may be gathered from config file
    -c (ssh_config), ssh configuration file (defaults to SSH_CONFIG_FILE)
    -z (compress)
    -n (noagent), disable looking for keys from an Agent
    -d (host_pkey_directories), look for keys on these folders
    """
    arguments = _parse_arguments(args)
    # Remove all "None" input values
    _remove_none_values(arguments)
    verbosity = min(arguments.pop("verbose"), 4)
    levels = [logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG, TRACE_LEVEL]
    arguments.setdefault("debug_level", levels[verbosity])
    # do this while supporting py27/py34 instead of merging dicts
    for extra, value in extras.items():
        arguments.setdefault(extra, value)
    with open_tunnel(**arguments) as tunnel:
        if tunnel.is_alive:
            input_("""

            Press <Ctrl-C> or <Enter> to stop!

            """)


if __name__ == "__main__":  # pragma: no cover
    _cli_main()
