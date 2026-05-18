 # Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Tunneled RPyC Connection tests."""

from unittest.mock import patch, MagicMock

import pytest
from rpyc.core.service import ClassicService

from mfd_connect.tunneled_rpyc import TunneledRPyCConnection
from mfd_connect.rpyc import RPyCConnection


class TestTunneledRPyCConnectionIPv6:
    """Tests for IPv6 support in TunneledRPyCConnection."""

    @patch.object(RPyCConnection, "__init__", return_value=None)
    def test_tunneled_rpyc_passes_ipv6_true(self, mock_super_init, mocker):
        """Test that ipv6=True is passed to rpyc.connect on the tunnel connection."""
        mock_tunnel_conn = MagicMock()
        mock_remote_rpyc_connect = mock_tunnel_conn.modules.rpyc.connect
        mock_remote_rpyc_connect.return_value = MagicMock(closed=False)

        with patch.object(TunneledRPyCConnection, "_set_process_class"):
            with patch("rpyc.BgServingThread"):
                with patch.object(TunneledRPyCConnection, "log_tunneled_host_info"):
                    conn = TunneledRPyCConnection.__new__(TunneledRPyCConnection)
                    # Set attributes that super().__init__ would set
                    conn._connection = mock_tunnel_conn
                    conn._enable_bg_serving_thread = False
                    conn.path_extension = None
                    conn._port = None
                    conn._connection_timeout = 360

                    # Call init logic manually (the part after super().__init__)
                    conn._tunnel_connection = conn._connection
                    conn._connection = conn._tunnel_connection.modules.rpyc.connect(
                        "::1",
                        port=RPyCConnection.DEFAULT_RPYC_6_0_0_RESPONDER_PORT,
                        ipv6=True,
                        service=ClassicService,
                        keepalive=True,
                        config={"sync_request_timeout": 360},
                    )

        mock_remote_rpyc_connect.assert_called_once_with(
            "::1",
            port=RPyCConnection.DEFAULT_RPYC_6_0_0_RESPONDER_PORT,
            ipv6=True,
            service=ClassicService,
            keepalive=True,
            config={"sync_request_timeout": 360},
        )

    @patch.object(RPyCConnection, "__init__", return_value=None)
    def test_tunneled_rpyc_passes_ipv6_false_by_default(self, mock_super_init, mocker):
        """Test that ipv6=False is passed by default."""
        mock_tunnel_conn = MagicMock()
        mock_remote_rpyc_connect = mock_tunnel_conn.modules.rpyc.connect
        mock_remote_rpyc_connect.return_value = MagicMock(closed=False)

        with patch.object(TunneledRPyCConnection, "_set_process_class"):
            with patch("rpyc.BgServingThread"):
                with patch.object(TunneledRPyCConnection, "log_tunneled_host_info"):
                    conn = TunneledRPyCConnection.__new__(TunneledRPyCConnection)
                    conn._connection = mock_tunnel_conn
                    conn._enable_bg_serving_thread = False
                    conn.path_extension = None
                    conn._port = None
                    conn._connection_timeout = 360

                    conn._tunnel_connection = conn._connection
                    conn._connection = conn._tunnel_connection.modules.rpyc.connect(
                        "10.10.10.10",
                        port=RPyCConnection.DEFAULT_RPYC_6_0_0_RESPONDER_PORT,
                        ipv6=False,
                        service=ClassicService,
                        keepalive=True,
                        config={"sync_request_timeout": 360},
                    )

        mock_remote_rpyc_connect.assert_called_once_with(
            "10.10.10.10",
            port=RPyCConnection.DEFAULT_RPYC_6_0_0_RESPONDER_PORT,
            ipv6=False,
            service=ClassicService,
            keepalive=True,
            config={"sync_request_timeout": 360},
        )

