# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Unit Test Module for Process utils."""

import pytest
from unittest.mock import patch

from mfd_connect import (
    SSHConnection,
    LocalConnection,
)
from mfd_connect.ssh import SSHClient
from mfd_connect.util.connection_utils import check_ssh_active_and_return_conn


class TestProcessUtils:
    @pytest.fixture()
    def ssh_conn(self, mocker):
        conn = mocker.create_autospec(SSHConnection)
        return conn

    @pytest.fixture()
    def local_conn(self, mocker):
        conn = mocker.create_autospec(LocalConnection)
        return conn

    @pytest.mark.parametrize("active", [True, False])
    def test_check_ssh_active_and_return_existing_ssh_conn(self, mocker, ssh_conn, active):
        ssh_conn._connection = mocker.create_autospec(SSHClient)
        ssh_conn._connection.get_transport = mocker.Mock(
            return_value=mocker.Mock(is_active=mocker.Mock(return_value=active))
        )
        ssh_active, ssh_handle = check_ssh_active_and_return_conn(conn=ssh_conn)
        if active:
            assert ssh_active
            assert isinstance(ssh_handle, SSHConnection)
        else:
            assert not ssh_active
            assert ssh_handle is None

    @pytest.mark.parametrize("conn", [local_conn, None])
    def test_check_ssh_active_and_return_conn_existing_not_ssh_or_not_specified_with_error(self, conn):
        with pytest.raises(
            AttributeError,
            match="SSH credentials: ssh_ip, ssh_user, ssh_pwd needed to spawn a new SSH Connection",
        ):
            check_ssh_active_and_return_conn(conn=conn)

    @pytest.mark.parametrize("conn", [local_conn, None])
    def test_check_ssh_active_and_return_conn_on_platform_existing_not_ssh_or_not_specified(self, conn):
        with patch.object(SSHConnection, "_connect", autospec=True) as new_ssh:
            ssh_active, ssh_handle = check_ssh_active_and_return_conn(
                conn=conn, ssh_ip="1.1.1.1", ssh_user="user", ssh_pwd=""
            )
            new_ssh.assert_called_once()
            assert ssh_active
            assert isinstance(ssh_handle, SSHConnection)

    @pytest.mark.parametrize("conn", [local_conn, None])
    def test_check_ssh_active_and_return_conn_on_platform_existing_not_ssh_or_not_specified_exception(self, conn):
        with patch.object(SSHConnection, "_connect", side_effect=TimeoutError):
            ssh_active, ssh_handle = check_ssh_active_and_return_conn(
                conn=conn, ssh_ip="10.10.10.10", ssh_user="user", ssh_pwd=""
            )
            assert not ssh_active
            assert ssh_handle is None
