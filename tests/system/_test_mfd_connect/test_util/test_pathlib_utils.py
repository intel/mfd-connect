# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""System tests for RPC copy."""

import logging
import subprocess
import sys
import uuid
from time import sleep

import pytest

from mfd_connect import RPyCConnection, LocalConnection, SSHConnection
from mfd_connect.util.pathlib_utils import append_file

logging.basicConfig(level=logging.DEBUG)


def dir_unique_name() -> str:
    return f"/tmp/testos/{uuid.uuid4().hex[:16]}/"


TEST_DIR = dir_unique_name()


class TestPathlibUtils:
    @pytest.fixture(scope="class")
    def rpyc(self):
        command = [sys.executable, "-m", "mfd_connect.rpyc_server"]
        p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        sleep(5)
        conn = RPyCConnection(ip="127.0.0.1")
        yield conn
        if conn.path(TEST_DIR).exists():
            conn.modules().shutil.rmtree(TEST_DIR)
        conn.disconnect()
        p.kill()

    @pytest.fixture(scope="class")
    def local(self):
        conn = LocalConnection()
        yield conn
        if conn.path(TEST_DIR).exists():
            conn.modules().shutil.rmtree(TEST_DIR)

    @pytest.fixture(scope="class")
    def ssh_lnx(self):
        conn = SSHConnection(ip="10.10.10.10", username="***", password="***", skip_key_verification=True)
        yield conn
        if conn.path(TEST_DIR).exists():
            conn.path(TEST_DIR).rmdir()
        conn.disconnect()

    @pytest.mark.parametrize("conn", ["rpyc", "local", "ssh_lnx"])
    def test_append_file(self, conn, request):
        conn = request.getfixturevalue(conn)
        logging.debug(f"System: {sys.platform}")
        test_dir_path = conn.path("~", TEST_DIR).expanduser()
        test_dir_path.mkdir(parents=True, exist_ok=True)
        actual_file = conn.path(test_dir_path, "test_file.txt")
        actual_file.write_text("some content")
        append_file(conn, actual_file, "second_content")

        assert actual_file.read_text().rstrip() == "some contentsecond_content"
