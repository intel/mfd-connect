# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
from pathlib import Path

import pytest
from mfd_typing import OSName

from mfd_connect import RPyCConnection, TelnetConnection, SSHConnection
from mfd_connect.util.rpc_permission_utils import change_mode, change_owner


class TestRPCPermissionsUtils:
    @pytest.fixture(params=[SSHConnection, RPyCConnection])
    def conn(self, mocker, request):
        conn_type = request.param
        mocker.patch.object(conn_type, "__init__", return_value=None)
        if conn_type is RPyCConnection:
            conn = RPyCConnection(ip="10.10.10.10")
            conn._create_connection = mocker.Mock()
            conn.execute_command = mocker.Mock()
            conn._connection = mocker.Mock()
            conn.path_extension = mocker.Mock()
            conn._os_name = OSName.LINUX
        else:
            conn = mocker.create_autospec(conn_type)
        if isinstance(conn_type, SSHConnection):
            conn._connection_details = {"hostname": "10.10.10.10", "port": 22, "username": "root", "password": "***"}
        conn._ip = "10.10.10.10"
        conn.get_os_name = mocker.Mock(return_value=OSName.LINUX)
        conn._enable_bg_serving_thread = True
        conn.modules = mocker.Mock()
        return conn

    @pytest.fixture()
    def wrong_conn(self, mocker):
        mocker.patch.object(TelnetConnection, "_establish_telnet_connection", return_value=None)
        conn = mocker.create_autospec(TelnetConnection)
        conn.get_os_name = mocker.Mock("conn.get_os_name", return_value=OSName.ESXI)
        return conn

    def test_change_mode(self, conn, mocker):
        conn.path.exists = mocker.Mock(return_value=True)
        change_mode(conn, "a", 0o777)
        conn.path().chmod.assert_called_once_with(0o777)

    def test_change_mode_wrong_connection(self, wrong_conn):
        with pytest.raises(Exception, match="Connection type not supported"):
            change_mode(wrong_conn, "a", 0o777)

    def test_change_mode_wrong_os(self, conn, mocker):
        conn.get_os_name = mocker.Mock()
        conn.get_os_name.return_value = OSName.WINDOWS
        with pytest.raises(NotImplementedError, match="Chmod is not supported on this system"):
            change_mode(conn, "a", 0o777)

    def test_change_mode_path_not_exist(self, conn):
        mocked_path = conn.path("a")
        mocked_path.exists.side_effect = [False, False, False, False]
        mocked_path.exists.return_value = False

        with pytest.raises(Exception, match="not found"):
            change_mode(conn, mocked_path, 0o777)

    def test_change_owner(self, conn, mocker):
        conn.path().exists = mocker.Mock(return_value=True)
        conn._handle_path_extension = mocker.Mock()
        change_owner(conn, "a", user="user", group="group")
        conn.execute_command.assert_called_once_with("chown user:group a")

    def test_change_owner_wrong_connection(self, wrong_conn):
        with pytest.raises(Exception, match="Connection type not supported"):
            change_owner(wrong_conn, "a", user="user")

    def test_change_owner_wrong_os(self, conn, mocker):
        conn.get_os_name = mocker.Mock()
        conn.get_os_name.return_value = OSName.WINDOWS
        with pytest.raises(NotImplementedError, match="Chown is not supported on this system"):
            change_owner(conn, "a", user="user")

    def test_change_owner_path_not_exist(self, conn, mocker):
        test_path = Path("a")
        conn.path(test_path).exists = mocker.Mock(return_value=False)

        with pytest.raises(Exception, match="not found"):
            change_owner(conn, test_path, user="")
