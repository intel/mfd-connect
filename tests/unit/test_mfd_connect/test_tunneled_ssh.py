"""Module for tunneled SSH tests."""

import re

# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
import mfd_connect.sshtunnel as sshtunnel
import pytest
from netaddr import IPAddress

from mfd_connect import SSHConnection, TunneledSSHConnection
from mfd_connect.tunneled_ssh import DEFAULT_LOCAL_BIND_PORT, local_bind_ports_in_use
from .test_ssh import TestSSHConnection
from mfd_connect.exceptions import SSHTunnelException
from mfd_common_libs import log_levels


class TestTunneledSSHConnection(TestSSHConnection):
    @pytest.fixture()
    def ssh(self, mocker):
        mocker.patch.object(TunneledSSHConnection, "__init__", return_value=None)
        ssh = TunneledSSHConnection(
            username="root",
            password="***",
            ip="192.168.0.1",
            jump_host_ip="10.10.10.10",
            jump_host_username="user",
            jump_host_password="pass",
        )
        ssh._connection_details = {"hostname": "127.0.0.1", "port": 10022, "username": "root", "password": "root"}
        ssh._tunnel = mocker.create_autospec(sshtunnel.SSHTunnelForwarder)
        ssh._tunnel.is_active.return_value = True
        ssh._ip = "127.0.0.1"
        ssh.cache_system_data = True
        ssh.disable_sudo()
        ssh._target_ip = "192.168.0.1"
        ssh._default_timeout = None
        return ssh

    def test_constructor_super_init_parameters(self, mocker):
        mocker.patch.object(SSHConnection, "__init__", return_value=None)
        mocker.patch.object(sshtunnel.SSHTunnelForwarder, "__init__", return_value=None)
        mocker.patch.object(sshtunnel.SSHTunnelForwarder, "start", return_value=None)
        tunneled_ssh_conn = TunneledSSHConnection(
            username="root",
            password="***",
            ip="192.168.0.1",
            jump_host_ip="10.10.10.10",
            jump_host_username="user",
            jump_host_password="pass",
            skip_key_verification=True,
        )
        super(TunneledSSHConnection, tunneled_ssh_conn).__init__.assert_called_with(
            ip="127.0.0.1",
            username="root",
            password="***",
            port=10022,
            model=None,
            skip_key_verification=True,
            default_timeout=None,
            cache_system_data=True,
        )

    def test_tunnel_start_ports_not_set(self, mocker):
        connection_kwargs = {
            "ip": "192.168.0.1",
            "jump_host_ip": "10.10.10.10",
            "username": "root",
            "password": "root",
            "jump_host_username": "user",
            "jump_host_password": "pass",
            "jump_host_port": None,
            "local_bind_port": None,
            "tunnel_start_retries": 1,
        }
        mocker.patch.object(SSHConnection, "__init__", return_value=None)
        mock_forwarder = mocker.patch("mfd_connect.sshtunnel.SSHTunnelForwarder")
        _ = TunneledSSHConnection(**connection_kwargs)
        free_local_bind_port = local_bind_ports_in_use[-1]
        mock_forwarder.assert_called_once_with(
            ssh_address_or_host=connection_kwargs["jump_host_ip"],
            remote_bind_address=(connection_kwargs["ip"], 22),
            ssh_username=connection_kwargs["jump_host_username"],
            ssh_password=connection_kwargs["jump_host_password"],
            local_bind_address=("0.0.0.0", free_local_bind_port),
        )

    def test_set_ssh_address_or_host_jump_host_port_not_set(self, mocker):
        jump_host_ip = "10.10.10.10"
        connection_kwargs = {
            "ip": "192.168.0.1",
            "jump_host_ip": jump_host_ip,
            "username": "root",
            "password": "root",
            "jump_host_username": "user",
            "jump_host_password": "pass",
            "jump_host_port": None,
            "local_bind_port": None,
            "tunnel_start_retries": 1,
        }
        mocker.patch.object(SSHConnection, "__init__", return_value=None)
        mocker.patch("mfd_connect.sshtunnel.SSHTunnelForwarder")
        tunneled_ssh_connection = TunneledSSHConnection(**connection_kwargs)
        assert tunneled_ssh_connection._set_ssh_address_or_host(None, jump_host_ip) == str(IPAddress(jump_host_ip))

    def test_set_ssh_address_or_host_jump_host_port_set(self, mocker):
        jump_host_ip = "10.10.10.10"
        jump_host_port = 22
        connection_kwargs = {
            "ip": "192.168.0.1",
            "jump_host_ip": jump_host_ip,
            "username": "root",
            "password": "root",
            "jump_host_username": "user",
            "jump_host_password": "pass",
            "jump_host_port": jump_host_port,
            "local_bind_port": None,
            "tunnel_start_retries": 1,
        }
        mocker.patch.object(SSHConnection, "__init__", return_value=None)
        mocker.patch("mfd_connect.sshtunnel.SSHTunnelForwarder")
        tunneled_ssh_connection = TunneledSSHConnection(**connection_kwargs)
        exp_result = (str(IPAddress(jump_host_ip)), jump_host_port)
        assert tunneled_ssh_connection._set_ssh_address_or_host(jump_host_port, jump_host_ip) == exp_result

    def test_tunnel_start(self, mocker):
        log_debug = mocker.patch("mfd_connect.tunneled_ssh.logger.log")
        connection_kwargs = {
            "ip": "192.168.0.1",
            "jump_host_ip": "10.10.10.10",
            "username": "root",
            "password": "root",
            "jump_host_username": "user",
            "jump_host_password": "pass",
        }

        mocker.patch.object(SSHConnection, "__init__", return_value=None)
        mocker.patch("mfd_connect.sshtunnel.SSHTunnelForwarder", autospec=True)
        local_bind_port = DEFAULT_LOCAL_BIND_PORT + len(local_bind_ports_in_use)
        _ = TunneledSSHConnection(**connection_kwargs)
        log_debug.assert_called_with(
            level=log_levels.MODULE_DEBUG, msg=f"Tunnel status: active, local bind port: {local_bind_port}"
        )

    def test_tunnel_start_retry_successful_when_local_bind_port_in_use(self, mocker):
        connection_kwargs = {
            "ip": "192.168.0.1",
            "jump_host_ip": "10.10.10.10",
            "username": "root",
            "password": "root",
            "jump_host_username": "user",
            "jump_host_password": "pass",
            "local_bind_port": 10022,
        }
        if not local_bind_ports_in_use:
            local_bind_ports_in_use.append(10022)

        expected_local_bind = local_bind_ports_in_use[-1] + 2

        expected_calls = [
            mocker.call(
                level=log_levels.MODULE_DEBUG,
                msg=f'Cannot start tunnel to {connection_kwargs["ip"]}:22 via {connection_kwargs["jump_host_ip"]}:22 '
                f"using local bind port {expected_local_bind - 1}, "
                f"retrying with {expected_local_bind}",
            ),
            mocker.call(
                level=log_levels.MODULE_DEBUG,
                msg=f"Tunnel status: active, local bind port: {expected_local_bind}",
            ),
        ]

        log_debug = mocker.patch("mfd_connect.tunneled_ssh.logger.log")
        mocker.patch.object(SSHConnection, "__init__", return_value=None)
        mocker.patch.object(sshtunnel.SSHTunnelForwarder, "__init__", return_value=None)
        mocker.patch.object(sshtunnel.SSHTunnelForwarder, "__del__", return_value=None)
        mocker.patch.object(
            sshtunnel.SSHTunnelForwarder, "start", side_effect=[sshtunnel.HandlerSSHTunnelForwarderError, None]
        )
        mocker.patch("mfd_connect.sshtunnel.SSHTunnelForwarder.is_active", return_value=[False, True])

        _ = TunneledSSHConnection(**connection_kwargs)
        assert sshtunnel.SSHTunnelForwarder.start.call_count == 2
        log_debug.assert_has_calls(expected_calls)

    def test_tunnel_start_fail(self, mocker):
        connection_kwargs = {
            "ip": "192.168.0.1",
            "jump_host_ip": "10.10.10.10",
            "username": "root",
            "password": "root",
            "jump_host_username": "user",
            "jump_host_password": "pass",
        }

        mocker.patch.object(SSHConnection, "__init__", return_value=None)
        mocker.patch.object(sshtunnel.SSHTunnelForwarder, "__init__", return_value=None)
        mocker.patch.object(sshtunnel.SSHTunnelForwarder, "__del__", return_value=None)
        mocker.patch.object(sshtunnel.SSHTunnelForwarder, "start", side_effect=sshtunnel.HandlerSSHTunnelForwarderError)

        with pytest.raises(
            SSHTunnelException,
            match=f'Cannot start tunnel to {connection_kwargs["ip"]}:22 via {connection_kwargs["jump_host_ip"]}:22.'
            f" Make sure that local bind ports are not in use.",
        ):
            _ = TunneledSSHConnection(**connection_kwargs)
        assert sshtunnel.SSHTunnelForwarder.start.call_count == 10

    def test_reconnect_tunnel_if_not_available_inactive(self, ssh, mocker):
        def change_tunnel_to_active():
            ssh._tunnel.is_active = True

        log_debug = mocker.patch("mfd_connect.tunneled_ssh.logger.log")
        ssh._tunnel.is_active = False
        ssh._tunnel.restart.side_effect = change_tunnel_to_active

        ssh._reconnect_tunnel_if_not_available()

        log_debug.assert_any_call(level=log_levels.MODULE_DEBUG, msg="Tunnel is not active, trying to restart...")
        log_debug.assert_any_call(level=log_levels.MODULE_DEBUG, msg="Tunnel reconnected successfully.")
        ssh._tunnel.restart.assert_called_once()

    def test_reconnect_tunnel_if_not_available_active(self, ssh, mocker):
        ssh._tunnel.is_active = True
        log_debug = mocker.patch("mfd_connect.tunneled_ssh.logger.log")

        ssh._reconnect_tunnel_if_not_available()

        log_debug.assert_not_called()
        ssh._tunnel.restart.assert_not_called()

    def test_reconnect_tunnel_if_not_available_exception(self, ssh, mocker):
        ssh._tunnel.is_active = False
        log_debug = mocker.patch("mfd_connect.tunneled_ssh.logger.log")

        with pytest.raises(SSHTunnelException, match="Tunnel is not active and failed to restart"):
            ssh._reconnect_tunnel_if_not_available()

        log_debug.assert_called_with(level=log_levels.MODULE_DEBUG, msg="Tunnel is not active, trying to restart...")
        ssh._tunnel.restart.assert_called_once()

    def test_disconnect_stop_tunnel(self, ssh, mocker):
        mocker.patch.object(SSHConnection, "disconnect")
        ssh.disconnect()

        ssh._tunnel.stop.assert_called_once()

    def test_execute_command_reconnect_tunnel_if_not_available(self, ssh, mocker):
        ssh._reconnect_tunnel_if_not_available = mocker.create_autospec(ssh._reconnect_tunnel_if_not_available)
        mocker.patch.object(SSHConnection, "execute_command")
        ssh.execute_command("command")

        ssh._reconnect_tunnel_if_not_available.assert_called_once()

    def test_start_process_reconnect_tunnel_if_not_available(self, ssh, mocker):
        ssh._reconnect_tunnel_if_not_available = mocker.create_autospec(ssh._reconnect_tunnel_if_not_available)
        mocker.patch.object(SSHConnection, "start_process")
        ssh.start_process("command")

        ssh._reconnect_tunnel_if_not_available.assert_called_once()

    def test__reconnect_reconnect_tunnel_if_not_available(self, ssh, mocker):
        ssh._reconnect_tunnel_if_not_available = mocker.create_autospec(ssh._reconnect_tunnel_if_not_available)
        mocker.patch.object(SSHConnection, "_reconnect")
        ssh._reconnect()

        ssh._reconnect_tunnel_if_not_available.assert_called_once()

    def test_str_function(self, ssh):
        assert str(ssh) == "tunneled_ssh"

    def test_ip_property(self, ssh):
        assert ssh.ip == "192.168.0.1"

    def test_init_with_model(self, mocker):
        mocker.patch("paramiko.SSHClient", return_value=mocker.Mock())
        mocker.patch(
            "mfd_connect.SSHConnection._connect",
        )
        mocker.patch(
            "mfd_connect.SSHConnection.log_connected_host_info",
        )
        mocker.patch(
            "mfd_connect.TunneledSSHConnection._set_ssh_address_or_host",
        )
        mocker.patch(
            "mfd_connect.sshtunnel.SSHTunnelForwarder",
        )
        model = mocker.Mock()
        obj = TunneledSSHConnection(
            model=model,
            ip="10.10.10.10",
            jump_host_ip="10.10.10.10",
            username="",
            password="",
            jump_host_username="",
            jump_host_password="",
        )
        assert obj.model == model
        obj = TunneledSSHConnection(
            ip="10.10.10.10",
            jump_host_ip="10.10.10.10",
            username="",
            password="",
            jump_host_username="",
            jump_host_password="",
        )
        assert obj.model is None

    @pytest.fixture()
    def ssh_conn_with_timeout(self, mocker):
        mocker.patch.object(TunneledSSHConnection, "__init__", return_value=None)
        ssh = TunneledSSHConnection(
            username="root",
            password="***",
            ip="192.168.0.1",
            jump_host_ip="10.10.10.10",
            jump_host_username="user",
            jump_host_password="***",
        )
        ssh._connection_details = {"hostname": "127.0.0.1", "port": 10022, "username": "root", "password": "root"}
        ssh._tunnel = mocker.create_autospec(sshtunnel.SSHTunnelForwarder)
        ssh._tunnel.is_active.return_value = True
        ssh._ip = "127.0.0.1"
        ssh.cache_system_data = True
        ssh.disable_sudo()
        ssh._target_ip = "192.168.0.1"
        ssh._default_timeout = 1
        return ssh

    def test_execute_with_timeout(self, ssh_conn_with_timeout, ssh, mocker):
        ssh_conn_with_timeout._exec_command = mocker.create_autospec(
            ssh_conn_with_timeout._exec_command, return_value=(None, None, None, 0)
        )
        ssh._exec_command = mocker.create_autospec(ssh._exec_command, return_value=(None, None, None, 0))
        ssh_conn_with_timeout.execute_command("ping localhost")
        ssh.execute_command("ping localhost")

        ssh_conn_with_timeout._exec_command.assert_called_with(
            "ping localhost",
            cwd=None,
            discard_stderr=False,
            discard_stdout=False,
            environment=None,
            get_pty=False,
            input_data=None,
            stderr_to_stdout=False,
            timeout=1,
        )
        ssh._exec_command.assert_called_with(
            "ping localhost",
            cwd=None,
            discard_stderr=False,
            discard_stdout=False,
            environment=None,
            get_pty=False,
            input_data=None,
            stderr_to_stdout=False,
            timeout=None,
        )

    def test_download_file_from_url_windows_ssh_no_supported(self, ssh, mocker):
        with pytest.raises(NotImplementedError, match=re.escape("Not implemented for TunneledSSHConnection")):
            ssh.download_file_from_url("http://url.com", "something.txt", username="***", password="***")

    def test_download_file_from_url(self, ssh):
        with pytest.raises(NotImplementedError, match=re.escape("Not implemented for TunneledSSHConnection")):
            ssh.download_file_from_url("http://url.com", "sth.txt", username="***", password="***")

    def test_download_file_from_url_no_hidden_creds(self, ssh):
        with pytest.raises(NotImplementedError, match=re.escape("Not implemented for TunneledSSHConnection")):
            ssh.download_file_from_url(
                "http://url.com", "sth.txt", username="***", password="***", hide_credentials=False
            )
