# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Tunneled RPyC Connection tests."""

from unittest.mock import patch, MagicMock

from rpyc.core.service import ClassicService

from mfd_connect.tunneled_rpyc import TunneledRPyCConnection
from mfd_connect.rpyc import RPyCConnection


class TestTunneledRPyCConnectionIPv6:
    """Tests for IPv6 support in TunneledRPyCConnection."""

    @patch("rpyc.BgServingThread")
    @patch.object(TunneledRPyCConnection, "log_tunneled_host_info")
    @patch.object(TunneledRPyCConnection, "_set_process_class")
    @patch.object(RPyCConnection, "__init__", autospec=True, return_value=None)
    def test_tunneled_rpyc_passes_ipv6_true(self, mock_super_init, _mock_set_proc, _mock_log, _mock_bg):
        """Test that ipv6=True is passed to rpyc.connect on the tunnel connection."""
        mock_tunnel_conn = MagicMock()
        mock_remote_rpyc_connect = mock_tunnel_conn.modules.rpyc.connect
        mock_remote_rpyc_connect.return_value = MagicMock(closed=False)

        def fake_super_init(self_inner, *args, **kwargs):
            self_inner._connection = mock_tunnel_conn
            self_inner._enable_bg_serving_thread = False
            self_inner.path_extension = None

        mock_super_init.side_effect = fake_super_init

        TunneledRPyCConnection(
            ip="::1",
            jump_host_ip="10.10.10.1",
            ipv6=True,
        )

        mock_remote_rpyc_connect.assert_called_once_with(
            "::1",
            port=RPyCConnection.DEFAULT_RPYC_6_0_0_RESPONDER_PORT,
            ipv6=True,
            service=ClassicService,
            keepalive=True,
            config={"sync_request_timeout": 360},
        )

    @patch("rpyc.BgServingThread")
    @patch.object(TunneledRPyCConnection, "log_tunneled_host_info")
    @patch.object(TunneledRPyCConnection, "_set_process_class")
    @patch.object(RPyCConnection, "__init__", autospec=True, return_value=None)
    def test_tunneled_rpyc_passes_ipv6_false_by_default(self, mock_super_init, _mock_set_proc, _mock_log, _mock_bg):
        """Test that ipv6=False is passed by default."""
        mock_tunnel_conn = MagicMock()
        mock_remote_rpyc_connect = mock_tunnel_conn.modules.rpyc.connect
        mock_remote_rpyc_connect.return_value = MagicMock(closed=False)

        def fake_super_init(self_inner, *args, **kwargs):
            self_inner._connection = mock_tunnel_conn
            self_inner._enable_bg_serving_thread = False
            self_inner.path_extension = None

        mock_super_init.side_effect = fake_super_init

        TunneledRPyCConnection(
            ip="10.10.10.10",
            jump_host_ip="10.10.10.1",
        )

        mock_remote_rpyc_connect.assert_called_once_with(
            "10.10.10.10",
            port=RPyCConnection.DEFAULT_RPYC_6_0_0_RESPONDER_PORT,
            ipv6=False,
            service=ClassicService,
            keepalive=True,
            config={"sync_request_timeout": 360},
        )
