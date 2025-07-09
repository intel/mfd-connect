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
    rpyc_server.run()
    mock_threaded_server.assert_called_once()


@patch("mfd_connect.rpyc_server.rpyc_server.ThreadedServer")
@patch("mfd_connect.rpyc_server.rpyc_server.argparse.ArgumentParser")
def test_run_with_log(mock_argparse, mock_threaded_server):
    mock_args = mock_argparse.return_value.parse_args.return_value
    mock_args.log = "log.txt"
    rpyc_server.run()
    mock_threaded_server.assert_called_once()
