# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""RPyC Server tests."""

from unittest.mock import patch
from mfd_connect.rpyc_server import rpyc_server


@patch("mfd_connect.rpyc_server.rpyc_server.ThreadedServer")
@patch("mfd_connect.rpyc_server.rpyc_server.argparse.ArgumentParser")
def test_run_without_log(mock_argparse, mock_threaded_server):
    mock_args = mock_argparse.return_value.parse_args.return_value
    mock_args.log = None
    mock_args.port = 18816
    mock_args.ipv6 = False
    mock_args.ssl_keyfile = None
    mock_args.ssl_certfile = None
    rpyc_server.run()
    mock_threaded_server.assert_called_once()


@patch("mfd_connect.rpyc_server.rpyc_server.ThreadedServer")
@patch("mfd_connect.rpyc_server.rpyc_server.argparse.ArgumentParser")
def test_run_with_log(mock_argparse, mock_threaded_server):
    mock_args = mock_argparse.return_value.parse_args.return_value
    mock_args.log = "log.txt"
    mock_args.port = 18816
    mock_args.ipv6 = False
    mock_args.ssl_keyfile = None
    mock_args.ssl_certfile = None
    rpyc_server.run()
    mock_threaded_server.assert_called_once()


@patch("mfd_connect.rpyc_server.rpyc_server.ThreadedServer")
@patch("mfd_connect.rpyc_server.rpyc_server.argparse.ArgumentParser")
def test_run_with_ipv6(mock_argparse, mock_threaded_server):
    mock_args = mock_argparse.return_value.parse_args.return_value
    mock_args.log = None
    mock_args.ipv6 = True
    mock_args.port = 18812
    mock_args.ssl_keyfile = None
    mock_args.ssl_certfile = None
    rpyc_server.run()
    mock_threaded_server.assert_called_once()
    call_kwargs = mock_threaded_server.call_args[1]
    assert call_kwargs["ipv6"] is True

