# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
import subprocess
import sys
import time

import pytest
from rpyc.lib.compat import TimeoutError as AsyncResultTimeout

from mfd_connect import RPyCConnection


class TestRPYCServerCLI:
    """System tests for RPyC Server CLI."""

    def test_cli_modules(self):
        command = [sys.executable, "-m", "mfd_connect.rpyc_server"]
        p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(5)
        conn = RPyCConnection("127.0.0.1")
        assert conn.modules().sys.path is not None
        p.kill()

    def test_cli_execute_command(self):
        command = [sys.executable, "-m", "mfd_connect.rpyc_server"]
        p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(5)
        conn = RPyCConnection("127.0.0.1")
        assert conn.execute_command("echo test", shell=True) is not None
        p.kill()

    def test_cli_timeout_raises(self):
        command = [sys.executable, "-m", "mfd_connect.rpyc_server"]
        p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(5)
        conn = RPyCConnection("127.0.0.1", connection_timeout=1)
        with pytest.raises(AsyncResultTimeout):
            conn.modules().time.sleep(2)
        p.kill()

    def test_cli_timeout(self):
        command = [sys.executable, "-m", "mfd_connect.rpyc_server"]
        p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(5)
        conn = RPyCConnection("127.0.0.1", connection_timeout=10)
        conn.modules().time.sleep(9)
        assert conn.execute_command("echo test", shell=True) is not None
        p.kill()
