# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for SSHConfigConnection tests."""

import socket
import textwrap
from pathlib import Path
from unittest.mock import patch, MagicMock

import paramiko
import pytest

from mfd_connect.ssh import SSHConnection
from mfd_connect.ssh_config import SSHConfigConnection
from mfd_connect.exceptions import OsNotSupported, SSHConfigException
from mfd_connect.util.ssh_config_parser import SSHHostConfig
from .test_ssh import TestSSHConnection


@pytest.fixture()
def ssh_config_file(tmp_path: Path) -> Path:
    """Create a temporary SSH config file with test entries."""
    config_content = textwrap.dedent("""\
        Host direct-host
            HostName 10.10.10.10
            User root
            StrictHostKeyChecking no
            IdentityFile /home/user/.ssh/id_rsa

        Host jump-host
            HostName 10.20.20.20
            User admin
            StrictHostKeyChecking no
            IdentityFile /home/user/.ssh/id_rsa

        Host tunneled-host
            HostName 192.168.0.1
            User testuser
            ProxyJump jump-host
            StrictHostKeyChecking no

        Host deep-host
            HostName 172.16.0.1
            User root
            ProxyJump tunneled-host
            StrictHostKeyChecking no

        Host dns-host
            HostName server.example.com
            User deploy
            StrictHostKeyChecking no
    """)
    config_file = tmp_path / "config"
    config_file.write_text(config_content)
    return config_file


class TestSSHConfigConnection(TestSSHConnection):
    """Tests of SSHConfigConnection."""

    @pytest.fixture()
    def ssh(self):
        with patch.object(SSHConfigConnection, "__init__", return_value=None):
            ssh = SSHConfigConnection(host="test-host")
            ssh._connection_details = {
                "hostname": "10.10.10.10",
                "port": 22,
                "username": "root",
                "password": "root",
            }
            ssh._ip = "10.10.10.10"
            ssh._default_timeout = None
            ssh._mnemonic = "test-host"
            ssh._host_config = SSHHostConfig(
                hostname="10.10.10.10",
                user="root",
                port=22,
                strict_host_key_checking=False,
            )
            ssh._proxy_clients = []
            ssh._proxy_sock = None
            ssh.cache_system_data = True
            ssh.disable_sudo()
            return ssh

    def test_str_function(self, ssh: SSHConfigConnection) -> None:
        """Override inherited test — SSHConfigConnection has different __str__."""
        assert str(ssh) == "ssh_config(test-host)"

    def test_constructor_direct_host(self, mocker, ssh_config_file: Path) -> None:
        """Test that direct host calls SSHConnection.__init__ with resolved params."""
        mocker.patch.object(SSHConnection, "__init__", return_value=None)
        SSHConfigConnection(host="direct-host", config_path=ssh_config_file)
        call_kwargs = SSHConnection.__init__.call_args[1]
        assert call_kwargs["ip"] == "10.10.10.10"
        assert call_kwargs["port"] == 22
        assert call_kwargs["username"] == "root"
        assert call_kwargs["password"] is None
        assert "key_path" not in call_kwargs
        assert call_kwargs["skip_key_verification"] is True
        assert call_kwargs["model"] is None
        assert call_kwargs["default_timeout"] is None
        assert call_kwargs["cache_system_data"] is True

    def test_constructor_direct_host_with_password(self, mocker, ssh_config_file: Path) -> None:
        """Test that password is passed through to SSHConnection.__init__."""
        mocker.patch.object(SSHConnection, "__init__", return_value=None)
        SSHConfigConnection(
            host="direct-host",
            password="secret",
            config_path=ssh_config_file,
        )
        call_kwargs = SSHConnection.__init__.call_args
        assert call_kwargs[1]["password"] == "secret"

    def test_constructor_unknown_host_raises_ssh_config_exception(self, ssh_config_file: Path) -> None:
        """Test that unknown mnemonic raises SSHConfigException."""
        with pytest.raises(SSHConfigException, match="Failed to resolve SSH config"):
            SSHConfigConnection(host="nonexistent", config_path=ssh_config_file)

    def test_constructor_missing_config_raises_ssh_config_exception(self, tmp_path: Path) -> None:
        """Test that missing config file raises SSHConfigException."""
        with pytest.raises(SSHConfigException, match="Failed to resolve SSH config"):
            SSHConfigConnection(
                host="whatever",
                config_path=tmp_path / "nonexistent",
            )

    def test_constructor_dns_hostname_resolved(self, mocker, ssh_config_file: Path) -> None:
        """Test that DNS hostname is resolved to IP before passing to SSHConnection."""
        mocker.patch.object(SSHConnection, "__init__", return_value=None)
        mocker.patch("mfd_connect.ssh_config.socket.gethostbyname", return_value="93.184.216.34")
        SSHConfigConnection(host="dns-host", config_path=ssh_config_file)
        call_kwargs = SSHConnection.__init__.call_args[1]
        assert call_kwargs["ip"] == "93.184.216.34"

    def test_constructor_dns_resolution_failure_raises_ssh_config_exception(
        self, mocker, ssh_config_file: Path
    ) -> None:
        """Test that DNS resolution failure raises SSHConfigException."""
        mocker.patch(
            "mfd_connect.ssh_config.socket.gethostbyname",
            side_effect=socket.gaierror("Name resolution failed"),
        )
        with pytest.raises(SSHConfigException, match="Cannot resolve hostname"):
            SSHConfigConnection(host="dns-host", config_path=ssh_config_file)

    def test_constructor_proxied_host_builds_chain(self, mocker, ssh_config_file: Path) -> None:
        """Test that proxied host builds proxy chain before calling super().__init__."""
        mock_build = mocker.patch.object(
            SSHConfigConnection,
            "_build_proxy_chain",
            return_value=MagicMock(),
        )
        mocker.patch.object(SSHConnection, "__init__", return_value=None)
        conn = SSHConfigConnection(host="tunneled-host", config_path=ssh_config_file)
        mock_build.assert_called_once()
        assert conn._proxy_sock is not None
        assert conn._host_config.proxy_jump == "jump-host"

    def test_constructor_cleanup_on_failure(self, mocker, ssh_config_file: Path) -> None:
        """Test that proxy clients are closed if SSHConnection.__init__ fails."""
        mocker.patch.object(
            SSHConfigConnection,
            "_build_proxy_chain",
            return_value=MagicMock(),
        )
        mocker.patch.object(SSHConnection, "__init__", side_effect=Exception("connection failed"))
        with pytest.raises(Exception, match="connection failed"):
            SSHConfigConnection(host="tunneled-host", config_path=ssh_config_file)

    def test_constructor_proxy_chain_unexpected_error_raises_ssh_config_exception(
        self, mocker, ssh_config_file: Path
    ) -> None:
        """Test that non-SSHConfigException from _build_proxy_chain is wrapped."""
        mocker.patch.object(
            SSHConfigConnection,
            "_build_proxy_chain",
            side_effect=OSError("network unreachable"),
        )
        with pytest.raises(SSHConfigException, match="Failed to build proxy chain"):
            SSHConfigConnection(host="tunneled-host", config_path=ssh_config_file)

    def test_connect_injects_sock_for_proxied(self, ssh: SSHConfigConnection) -> None:
        """Test that _connect injects sock into connection_details for proxied hosts."""
        mock_sock = MagicMock()
        ssh._proxy_sock = mock_sock
        with patch.object(SSHConnection, "_connect"):
            ssh._connect()
        assert ssh._connection_details["sock"] is mock_sock
        assert ssh._connection_details["look_for_keys"] is True
        assert ssh._connection_details["allow_agent"] is True

    def test_connect_no_sock_for_direct(self, ssh: SSHConfigConnection) -> None:
        """Test that _connect does not inject sock for direct hosts."""
        ssh._proxy_sock = None
        with patch.object(SSHConnection, "_connect"):
            ssh._connect()
        assert "sock" not in ssh._connection_details
        assert ssh._connection_details["look_for_keys"] is True
        assert ssh._connection_details["allow_agent"] is True

    def test_connect_injects_key_filename_from_config(self, ssh: SSHConfigConnection) -> None:
        """Test that _connect injects key_filename from host config identity files."""
        ssh._host_config = SSHHostConfig(
            hostname="10.10.10.10",
            user="root",
            identity_file=["/home/user/.ssh/id_rsa"],
            strict_host_key_checking=False,
        )
        with patch.object(SSHConnection, "_connect"):
            ssh._connect()
        assert ssh._connection_details["key_filename"] == ["/home/user/.ssh/id_rsa"]

    def test_connect_no_key_filename_when_no_identity_file(self, ssh: SSHConfigConnection) -> None:
        """Test that _connect does not inject key_filename when no identity files."""
        ssh._host_config = SSHHostConfig(
            hostname="10.10.10.10",
            user="root",
            strict_host_key_checking=False,
        )
        with patch.object(SSHConnection, "_connect"):
            ssh._connect()
        assert "key_filename" not in ssh._connection_details

    def test_connect_strict_host_key_sets_reject_policy(self, ssh: SSHConfigConnection) -> None:
        """Test that _connect sets RejectPolicy on target host when strict checking enabled."""
        ssh._host_config = SSHHostConfig(
            hostname="10.10.10.10",
            user="root",
            strict_host_key_checking=True,
        )
        ssh._connection = MagicMock()
        with patch.object(SSHConnection, "_connect"):
            ssh._connect()

        ssh._connection.set_missing_host_key_policy.assert_called_once()
        policy = ssh._connection.set_missing_host_key_policy.call_args[0][0]
        assert isinstance(policy, paramiko.RejectPolicy)
        ssh._connection.load_system_host_keys.assert_called_once()

    def test_connect_auth_none_fallback(self, ssh: SSHConfigConnection) -> None:
        """Test that _connect falls back to auth_none when no auth methods available."""
        ssh._connection = MagicMock()
        mock_transport = MagicMock()
        ssh._connection.get_transport.return_value = mock_transport

        with patch.object(
            SSHConnection,
            "_connect",
            side_effect=paramiko.AuthenticationException("No authentication methods available"),
        ):
            with patch.object(SSHConfigConnection, "_complete_post_connect_setup"):
                ssh._connect()

        mock_transport.auth_none.assert_called_once_with("root")

    def test_connect_auth_none_failure_reraises(self, ssh: SSHConfigConnection) -> None:
        """Test that _connect reraises original error when auth_none also fails."""
        ssh._connection = MagicMock()
        mock_transport = MagicMock()
        mock_transport.auth_none.side_effect = paramiko.AuthenticationException("auth_none failed")
        ssh._connection.get_transport.return_value = mock_transport

        with patch.object(
            SSHConnection,
            "_connect",
            side_effect=paramiko.AuthenticationException("No authentication methods available"),
        ):
            with pytest.raises(paramiko.AuthenticationException, match="No authentication methods available"):
                ssh._connect()

    def test_connect_other_ssh_exception_not_caught(self, ssh: SSHConfigConnection) -> None:
        """Test that non-auth SSHExceptions are not intercepted."""
        with patch.object(
            SSHConnection,
            "_connect",
            side_effect=paramiko.SSHException("Connection refused"),
        ):
            with pytest.raises(paramiko.SSHException, match="Connection refused"):
                ssh._connect()

    def test_disconnect_closes_proxy_clients(self, ssh: SSHConfigConnection) -> None:
        """Test that disconnect closes proxy clients."""
        mock_client1 = MagicMock()
        mock_client2 = MagicMock()
        ssh._proxy_clients = [mock_client1, mock_client2]
        ssh._connection = MagicMock()
        ssh.disconnect()
        mock_client1.close.assert_called_once()
        mock_client2.close.assert_called_once()
        assert ssh._proxy_clients == []

    def test_reconnect_rebuilds_proxy_chain(self, ssh: SSHConfigConnection) -> None:
        """Test that _reconnect rebuilds proxy chain for proxied hosts."""
        ssh._host_config = SSHHostConfig(
            hostname="192.168.0.1",
            user="root",
            proxy_jump="jump-host",
            proxy_chain=[
                SSHHostConfig(hostname="10.20.20.20", user="admin"),
            ],
        )
        old_client = MagicMock()
        ssh._proxy_clients = [old_client]
        new_sock = MagicMock()
        with patch.object(SSHConfigConnection, "_build_proxy_chain", return_value=new_sock):
            with patch.object(SSHConnection, "_reconnect"):
                ssh._reconnect()
        old_client.close.assert_called_once()
        assert ssh._proxy_sock is new_sock

    def test_reconnect_skips_chain_for_direct(self, ssh: SSHConfigConnection) -> None:
        """Test that _reconnect skips chain rebuild for direct hosts."""
        ssh._host_config = SSHHostConfig(
            hostname="10.10.10.10",
            user="root",
        )
        with patch.object(SSHConfigConnection, "_build_proxy_chain") as mock_build:
            with patch.object(SSHConnection, "_reconnect"):
                ssh._reconnect()
        mock_build.assert_not_called()

    def test_build_proxy_chain_single_hop(self, ssh: SSHConfigConnection) -> None:
        """Test building a proxy chain with a single hop."""
        jump_config = SSHHostConfig(
            hostname="10.20.20.20",
            user="admin",
            identity_file=["/home/user/.ssh/id_rsa"],
            strict_host_key_checking=False,
        )
        host_config = SSHHostConfig(
            hostname="192.168.0.1",
            user="root",
            proxy_jump="jump-host",
            proxy_chain=[jump_config],
        )
        mock_transport = MagicMock()
        mock_channel = MagicMock()
        mock_transport.open_channel.return_value = mock_channel

        with patch("mfd_connect.ssh_config.paramiko.SSHClient") as MockSSHClient:
            mock_client = MagicMock()
            mock_client.get_transport.return_value = mock_transport
            MockSSHClient.return_value = mock_client

            result = ssh._build_proxy_chain(host_config)

        mock_client.connect.assert_called_once()
        connect_kwargs = mock_client.connect.call_args
        assert connect_kwargs[1]["hostname"] == "10.20.20.20"
        assert connect_kwargs[1]["username"] == "admin"
        mock_transport.open_channel.assert_called_with(
            "direct-tcpip",
            ("192.168.0.1", 22),
            ("127.0.0.1", 0),
        )
        assert result is mock_channel

    def test_build_proxy_chain_connection_failure(self, ssh: SSHConfigConnection) -> None:
        """Test that proxy chain build failure raises SSHConfigException."""
        jump_config = SSHHostConfig(
            hostname="10.20.20.20",
            user="admin",
            strict_host_key_checking=False,
        )
        host_config = SSHHostConfig(
            hostname="192.168.0.1",
            user="root",
            proxy_jump="jump-host",
            proxy_chain=[jump_config],
        )
        with patch("mfd_connect.ssh_config.paramiko.SSHClient") as MockSSHClient:
            mock_client = MagicMock()
            mock_client.connect.side_effect = paramiko.AuthenticationException("connection failed")
            mock_client.get_transport.return_value = None
            MockSSHClient.return_value = mock_client

            with pytest.raises(SSHConfigException, match="Failed to connect to proxy hop"):
                ssh._build_proxy_chain(host_config)

    def test_build_proxy_chain_auth_none_fallback(self, ssh: SSHConfigConnection) -> None:
        """Test that proxy chain falls back to auth_none for hops without keys."""
        jump_config = SSHHostConfig(
            hostname="10.20.20.20",
            user="admin",
            strict_host_key_checking=False,
        )
        host_config = SSHHostConfig(
            hostname="192.168.0.1",
            user="root",
            proxy_jump="jump-host",
            proxy_chain=[jump_config],
        )
        mock_transport = MagicMock()
        mock_channel = MagicMock()
        mock_transport.open_channel.return_value = mock_channel

        with patch("mfd_connect.ssh_config.paramiko.SSHClient") as MockSSHClient:
            mock_client = MagicMock()
            mock_client.connect.side_effect = paramiko.AuthenticationException("No authentication methods available")
            mock_client.get_transport.return_value = mock_transport
            MockSSHClient.return_value = mock_client

            result = ssh._build_proxy_chain(host_config)

        mock_transport.auth_none.assert_called_once_with("admin")
        assert result is mock_channel

    def test_build_proxy_chain_auth_none_failure(self, ssh: SSHConfigConnection) -> None:
        """Test that proxy chain raises when auth_none also fails for a hop."""
        jump_config = SSHHostConfig(
            hostname="10.20.20.20",
            user="admin",
            strict_host_key_checking=False,
        )
        host_config = SSHHostConfig(
            hostname="192.168.0.1",
            user="root",
            proxy_jump="jump-host",
            proxy_chain=[jump_config],
        )
        mock_transport = MagicMock()
        mock_transport.auth_none.side_effect = paramiko.AuthenticationException("auth_none denied")

        with patch("mfd_connect.ssh_config.paramiko.SSHClient") as MockSSHClient:
            mock_client = MagicMock()
            mock_client.connect.side_effect = paramiko.AuthenticationException("No authentication methods available")
            mock_client.get_transport.return_value = mock_transport
            MockSSHClient.return_value = mock_client

            with pytest.raises(SSHConfigException, match="Failed to connect to proxy hop"):
                ssh._build_proxy_chain(host_config)

    def test_close_proxy_clients_handles_exceptions(self, ssh: SSHConfigConnection) -> None:
        """Test that _close_proxy_clients handles exceptions gracefully."""
        mock_client = MagicMock()
        mock_client.close.side_effect = Exception("close failed")
        ssh._proxy_clients = [mock_client]
        ssh._close_proxy_clients()
        assert ssh._proxy_clients == []

    def test_build_proxy_chain_open_channel_failure_cleans_up(self, ssh: SSHConfigConnection) -> None:
        """Test that open_channel failure in proxy chain build cleans up clients."""
        jump_config = SSHHostConfig(
            hostname="10.20.20.20",
            user="admin",
            strict_host_key_checking=False,
        )
        host_config = SSHHostConfig(
            hostname="192.168.0.1",
            user="root",
            proxy_jump="jump-host",
            proxy_chain=[jump_config],
        )
        mock_transport = MagicMock()
        mock_transport.open_channel.side_effect = OSError("channel failed")

        with patch("mfd_connect.ssh_config.paramiko.SSHClient") as MockSSHClient:
            mock_client = MagicMock()
            mock_client.get_transport.return_value = mock_transport
            MockSSHClient.return_value = mock_client

            with pytest.raises(SSHConfigException, match="Failed to build proxy chain"):
                ssh._build_proxy_chain(host_config)
        assert ssh._proxy_clients == []

    def test_connect_auth_none_no_transport_reraises(self, ssh: SSHConfigConnection) -> None:
        """Test that _connect reraises when transport is None after AuthenticationException."""
        ssh._connection = MagicMock()
        ssh._connection.get_transport.return_value = None

        with patch.object(
            SSHConnection,
            "_connect",
            side_effect=paramiko.AuthenticationException("No auth"),
        ):
            with pytest.raises(paramiko.AuthenticationException, match="No auth"):
                ssh._connect()

    def test_complete_post_connect_setup_normal(self, ssh: SSHConfigConnection) -> None:
        """Test _complete_post_connect_setup detects OS and sets process class."""
        ssh._connection = MagicMock()
        ssh._connection.get_transport.return_value = MagicMock(__str__=lambda s: "connected")
        mock_process_class = MagicMock()
        mock_process_class._os_name = ["Linux"]
        ssh._process_classes = [mock_process_class]

        with patch.object(ssh, "get_os_name", return_value="Linux"):
            with patch.object(ssh, "get_os_type", return_value="posix"):
                ssh._complete_post_connect_setup()

        assert ssh._process_class is mock_process_class
        assert ssh._os_type == "posix"

    def test_complete_post_connect_setup_awaiting_auth(self, ssh: SSHConfigConnection) -> None:
        """Test _complete_post_connect_setup handles awaiting auth."""
        ssh._connection = MagicMock()
        mock_transport = MagicMock(__str__=lambda s: "awaiting auth")
        ssh._connection.get_transport.return_value = mock_transport
        mock_process_class = MagicMock()
        mock_process_class._os_name = ["Linux"]
        ssh._process_classes = [mock_process_class]

        with patch.object(ssh, "get_os_name", return_value="Linux"):
            with patch.object(ssh, "get_os_type", return_value="posix"):
                ssh._complete_post_connect_setup()

        mock_transport.auth_interactive_dumb.assert_called_once_with("root")

    def test_complete_post_connect_setup_os_not_supported(self, ssh: SSHConfigConnection) -> None:
        """Test _complete_post_connect_setup raises OsNotSupported for unknown OS."""
        ssh._connection = MagicMock()
        ssh._connection.get_transport.return_value = MagicMock(__str__=lambda s: "connected")
        ssh._process_classes = []  # No matching process class

        with patch.object(ssh, "get_os_name", return_value="UnknownOS"):
            with patch.object(ssh, "get_os_type", return_value="unknown"):
                with pytest.raises(OsNotSupported, match="Not implemented process"):
                    ssh._complete_post_connect_setup()

    def test_connect_proxy_hop_strict_host_key_checking(self, ssh: SSHConfigConnection) -> None:
        """Test that strict host key checking uses RejectPolicy."""
        hop = SSHHostConfig(
            hostname="10.20.20.20",
            user="admin",
            strict_host_key_checking=True,
        )
        with patch("mfd_connect.ssh_config.paramiko.SSHClient") as MockSSHClient:
            mock_client = MagicMock()
            mock_client.get_transport.return_value = MagicMock()
            MockSSHClient.return_value = mock_client

            ssh._connect_proxy_hop(hop)

        mock_client.set_missing_host_key_policy.assert_called_once()
        policy = mock_client.set_missing_host_key_policy.call_args[0][0]
        assert isinstance(policy, paramiko.RejectPolicy)
        mock_client.load_system_host_keys.assert_called_once()

    def test_connect_proxy_hop_via_gateway_transport(self, ssh: SSHConfigConnection) -> None:
        """Test that proxy hop tunnels through existing gateway transport."""
        hop = SSHHostConfig(
            hostname="192.168.0.1",
            user="root",
            strict_host_key_checking=False,
        )
        mock_gateway = MagicMock()
        mock_channel = MagicMock()
        mock_gateway.open_channel.return_value = mock_channel

        with patch("mfd_connect.ssh_config.paramiko.SSHClient") as MockSSHClient:
            mock_client = MagicMock()
            mock_client.get_transport.return_value = MagicMock()
            MockSSHClient.return_value = mock_client

            ssh._connect_proxy_hop(hop, gateway_transport=mock_gateway)

        mock_gateway.open_channel.assert_called_once_with(
            "direct-tcpip",
            ("192.168.0.1", 22),
            ("127.0.0.1", 0),
        )
        connect_kwargs = mock_client.connect.call_args[1]
        assert connect_kwargs["sock"] is mock_channel

    def test_build_proxy_chain_two_hops(self, ssh: SSHConfigConnection) -> None:
        """Test building a proxy chain with two hops uses gateway transport."""
        hop1 = SSHHostConfig(
            hostname="10.20.20.20",
            user="admin",
            strict_host_key_checking=False,
        )
        hop2 = SSHHostConfig(
            hostname="192.168.0.1",
            user="root",
            strict_host_key_checking=False,
            proxy_jump="jump-host",
            proxy_chain=[hop1],
        )
        host_config = SSHHostConfig(
            hostname="172.16.0.1",
            user="root",
            proxy_jump="tunneled-host",
            proxy_chain=[hop2, hop1],
        )
        mock_transport1 = MagicMock()
        mock_transport2 = MagicMock()
        mock_final_channel = MagicMock()
        mock_transport2.open_channel.return_value = mock_final_channel

        with patch("mfd_connect.ssh_config.paramiko.SSHClient") as MockSSHClient:
            client1 = MagicMock()
            client1.get_transport.return_value = mock_transport1
            client2 = MagicMock()
            client2.get_transport.return_value = mock_transport2
            MockSSHClient.side_effect = [client1, client2]

            result = ssh._build_proxy_chain(host_config)

        assert result is mock_final_channel
        assert len(ssh._proxy_clients) == 2
        # Second hop should use first hop's transport for tunneling
        mock_transport1.open_channel.assert_called_once()
