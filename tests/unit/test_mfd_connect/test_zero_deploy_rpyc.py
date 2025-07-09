# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
import time

import pytest
import rpyc as rpyc_module
from mfd_common_libs import log_levels
from paramiko import AuthenticationException
from paramiko.ssh_exception import NoValidConnectionsError, SSHException
from plumbum import ProcessExecutionError, CommandNotFound
from plumbum.machines import RemoteCommand
from plumbum.machines.paramiko_machine import ParamikoMachine, ParamikoPopen
from rpyc.utils.zerodeploy import DeployedServer

from mfd_connect import RPyCZeroDeployConnection
from mfd_connect.exceptions import RPyCZeroDeployException


class TestRPyCZeroDeployConnection:
    @pytest.fixture()
    def patches(self, mocker):
        pm = mocker.patch("mfd_connect.rpyc_zero_deploy.ParamikoMachine")
        ds = mocker.patch("mfd_connect.rpyc_zero_deploy.DeployedServer")
        rpyc = mocker.patch("mfd_connect.rpyc.RPyCConnection.__init__")
        return pm, ds, rpyc

    @pytest.fixture()
    def zero_rpyc(self, mocker):
        with mocker.patch.object(RPyCZeroDeployConnection, "__init__", return_value=None):
            rpyc = RPyCZeroDeployConnection(ip="10.10.10.10", username="root", password="***")
            rpyc._server = mocker.create_autospec(DeployedServer)
            rpyc._mach = mocker.create_autospec(ParamikoMachine)
            rpyc._ip = "10.10.10.10"
            rpyc._username = "username"
            rpyc._password = "password"
            rpyc._keyfile = "keyfile"
            rpyc._connection_timeout = 360
            rpyc._python_executable = "python_executable"
            return rpyc

    def test_init(self, patches, mocker):
        paramiko, deploy, rpyc_init = patches
        policy = mocker.patch("mfd_connect.rpyc_zero_deploy.WarningPolicy")
        RPyCZeroDeployConnection(
            ip="10.10.10.10", username="root", password="***", python_executable="/usr/local/py37-tool/bin/python3.7"
        )
        paramiko.assert_called_once_with(
            host="10.10.10.10",
            user="root",
            password="***",
            keyfile=None,
            missing_host_policy=policy(),
            connect_timeout=360,
        )
        deploy.assert_called_once_with(
            remote_machine=paramiko(), python_executable="/usr/local/py37-tool/bin/python3.7"
        )
        rpyc_init.assert_called_once()

    def test_init_missing_auth(self, patches):
        with pytest.raises(RPyCZeroDeployException, match="Missing authentication argument password/keyfile ssh"):
            RPyCZeroDeployConnection(
                ip="10.10.10.10", username="root", python_executable="/usr/local/py37-tool/bin/python3.7"
            )

    @pytest.mark.parametrize(
        "exception", [TimeoutError, AuthenticationException, NoValidConnectionsError({"error": None})]
    )
    def test__prepare_connection_auth_problem(self, patches, exception, zero_rpyc):
        machine_path, _, _ = patches
        machine_path.side_effect = exception
        with pytest.raises(RPyCZeroDeployException, match="Problem with establishing connection via SSH."):
            zero_rpyc._prepare_connection(
                ip="10.10.10.10",
                username="root",
                password="***",
                keyfile=None,
                connection_timeout=360,
                python_executable="/usr/local/py37-tool/bin/python3.7",
            )

    def test__prepare_connection_paramiko_gen_problem(self, patches, zero_rpyc):
        machine_path, _, _ = patches
        machine_path.side_effect = Exception
        with pytest.raises(RPyCZeroDeployException, match="Unexpected exception during connection via SSH."):
            zero_rpyc._prepare_connection(
                ip="10.10.10.10",
                username="root",
                password="***",
                keyfile=None,
                connection_timeout=360,
                python_executable="/usr/local/py37-tool/bin/python3.7",
            )

    def test__prepare_connection_deploy_problem(self, patches, zero_rpyc):
        paramiko, server, _ = patches
        server.side_effect = ProcessExecutionError("", 1, "", "")
        with pytest.raises(RPyCZeroDeployException, match="Problem during deploying RPyC server via SSH."):
            zero_rpyc._prepare_connection(
                ip="10.10.10.10",
                username="root",
                password="***",
                keyfile=None,
                connection_timeout=360,
                python_executable="/usr/local/py37-tool/bin/python3.7",
            )

    def test__prepare_connection_deploy_gen_problem(self, patches, zero_rpyc):
        _, server, _ = patches
        server.side_effect = Exception
        with pytest.raises(RPyCZeroDeployException, match="Unexpected exception during deploying RPyC server via SSH."):
            zero_rpyc._prepare_connection(
                ip="10.10.10.10",
                username="root",
                password="***",
                keyfile=None,
                connection_timeout=360,
                python_executable="/usr/local/py37-tool/bin/python3.7",
            )

    def test__create_connection(self, zero_rpyc, patches):
        _, server, _ = patches
        zero_rpyc._create_connection()
        zero_rpyc._server.classic_connect.assert_called_once()

    def test__close(self, zero_rpyc, patches, mocker):
        zero_rpyc.disconnect = mocker.create_autospec(zero_rpyc.disconnect)
        zero_rpyc.close()
        zero_rpyc._server.close.assert_called_once()
        zero_rpyc._mach.close.assert_called_once()
        zero_rpyc.disconnect.assert_called_once()

    def test_wait_for_host(self, zero_rpyc, mocker):
        zero_rpyc._prepare_connection = mocker.Mock(
            side_effect=[RPyCZeroDeployException, RPyCZeroDeployException, None, None]
        )
        zero_rpyc._create_connection = mocker.Mock(side_effect=[OSError, rpyc_module.Connection])
        zero_rpyc._connection = mocker.Mock()
        remote = mocker.patch("mfd_connect.RPyCZeroDeployConnection.remote", new_callable=mocker.PropertyMock)
        remote.return_value = rpyc_module.Connection
        mocker.patch("rpyc.BgServingThread", mocker.create_autospec(rpyc_module.BgServingThread))
        time.sleep = mocker.Mock(return_value=None)
        zero_rpyc.wait_for_host(timeout=10)

    def test_wait_for_host_fail(self, zero_rpyc, mocker):
        timeout_mocker = mocker.patch("mfd_connect.rpyc_zero_deploy.TimeoutCounter")
        timeout_mocker.return_value.__bool__.return_value = True
        zero_rpyc._prepare_connection = mocker.Mock(return_value=None)
        zero_rpyc._create_connection = mocker.Mock(side_effect=OSError)
        time.sleep = mocker.Mock(return_value=None)
        with pytest.raises(TimeoutError):
            zero_rpyc.wait_for_host(timeout=1)

    @pytest.mark.parametrize("command", ["shutdown", "shutdown -r now"])
    def test__send_command_and_disconnect_platform_with_drop(self, patches, zero_rpyc, mocker, command, caplog):
        caplog.set_level(log_levels.MODULE_DEBUG)
        time.sleep = mocker.Mock(return_value=None)
        zero_rpyc._connection = mocker.Mock()
        zero_rpyc._mach.which.side_effect = ["/user/shutdown", SSHException]
        remote_command_mock = mocker.create_autospec(RemoteCommand)
        remote_command_mock.popen.return_value = mocker.create_autospec(ParamikoPopen, stdout=None, stderr=None)
        zero_rpyc._mach.__getitem__.return_value = remote_command_mock
        zero_rpyc._background_serving_thread = mocker.Mock()
        zero_rpyc.send_command_and_disconnect_platform(command)
        zero_rpyc._server.close.assert_called_once()
        zero_rpyc._connection.close.assert_called_once()
        assert "Dropped connection via SSH, expected" in caplog.text

    def test__send_command_and_disconnect_platform_popen_fail(self, patches, zero_rpyc, mocker):
        time.sleep = mocker.Mock(return_value=None)
        zero_rpyc._connection = mocker.Mock()
        zero_rpyc._mach.which.side_effect = ["/user/shutdown", "/user/shutdown"]
        remote_command_mock = mocker.create_autospec(RemoteCommand)
        remote_command_mock.popen.return_value = mocker.create_autospec(ParamikoPopen, stdout=None, stderr=None)
        zero_rpyc._mach.__getitem__.return_value = remote_command_mock
        zero_rpyc._background_serving_thread = mocker.Mock()
        with pytest.raises(
            RPyCZeroDeployException, match="Platform doesn't disconnect after executed command: /user/shutdown"
        ):
            zero_rpyc.send_command_and_disconnect_platform("command")
        zero_rpyc._server.close.assert_called_once()
        zero_rpyc._connection.close.assert_called_once()

    def test__send_command_and_disconnect_platform_command_not_found(self, patches, zero_rpyc, mocker):
        time.sleep = mocker.Mock(return_value=None)
        zero_rpyc._connection = mocker.Mock()
        zero_rpyc._mach.which.side_effect = CommandNotFound("command", [])
        zero_rpyc._background_serving_thread = mocker.Mock()
        with pytest.raises(RPyCZeroDeployException, match="Not found command in system"):
            zero_rpyc.send_command_and_disconnect_platform("command")
        zero_rpyc._server.close.assert_called_once()
        zero_rpyc._connection.close.assert_called_once()

    def test__send_command_and_disconnect_platform_fail(self, patches, zero_rpyc, mocker):
        time.sleep = mocker.Mock(return_value=None)
        zero_rpyc._connection = mocker.Mock()
        zero_rpyc._mach.which.return_value = "/user/shutdown"
        zero_rpyc._background_serving_thread = mocker.Mock()
        with pytest.raises(RPyCZeroDeployException):
            zero_rpyc.send_command_and_disconnect_platform("command")

    def test_ip_property(self, zero_rpyc):
        assert zero_rpyc.ip == "10.10.10.10"

    def test_init_with_model(self, mocker):
        mocker.patch("mfd_connect.RPyCConnection._set_process_class")
        mocker.patch("mfd_connect.RPyCConnection._set_bg_serving_thread")
        mocker.patch("mfd_connect.RPyCConnection.log_connected_host_info")
        mocker.patch("mfd_connect.RPyCZeroDeployConnection._prepare_connection")
        model = mocker.Mock()
        obj = RPyCZeroDeployConnection(ip="10.10.10.10", model=model, username="", password="*")
        assert obj.model == model
        obj = RPyCZeroDeployConnection(ip="10.10.10.10", username="", password="*")
        assert obj.model is None
