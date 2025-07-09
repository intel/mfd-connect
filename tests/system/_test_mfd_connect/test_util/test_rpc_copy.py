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
from mfd_connect.util.rpc_copy_utils import copy

logging.basicConfig(level=logging.DEBUG)


def test_dir() -> str:
    return f"/tmp/testos/{uuid.uuid4().hex[:16]}/"


TEST_DIR = test_dir()


class TestRPCCopy:
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
    def ssh_lnx_src(self):
        conn = SSHConnection(ip="10.10.10.10", username="***", password="***", skip_key_verification=True)
        yield conn
        conn.disconnect()

    @pytest.fixture(scope="class")
    def ssh_lnx_dst(self):
        conn = SSHConnection(ip="10.10.10.11", username="***", password="***", skip_key_verification=True)
        yield conn
        conn.disconnect()

    @pytest.fixture(scope="class")
    def rpyc_linux(self):
        conn = RPyCConnection(ip="10.10.10.10")
        yield conn
        conn.disconnect()

    @pytest.mark.parametrize("conn", ["rpyc", "local"])
    def test_copy_local_python_dir(self, conn, request):
        conn = request.getfixturevalue(conn)
        logging.debug(f"System: {sys.platform}")
        dir1 = conn.path(f"{TEST_DIR}dir/a_dir/b_dir/")
        dir1.mkdir(parents=True, exist_ok=True)
        file1 = conn.path(f"{TEST_DIR}dir/a_dir/b_dir/file1.txt")
        file1.touch()
        dir2 = conn.path(f"{TEST_DIR}dir/a_dir/b_dir/c_dir")
        dir2.mkdir(parents=True, exist_ok=True)

        copy(src_conn=conn, dst_conn=conn, source=dir1, target=dir2)

        assert conn.path(f"{TEST_DIR}dir/a_dir/b_dir/c_dir/b_dir/file1.txt").exists()

    @pytest.mark.parametrize("conn", ["rpyc", "local"])
    def test_copy_multiple_python_dirs(self, conn, request):
        conn = request.getfixturevalue(conn)
        logging.debug(f"System: {sys.platform}")
        for letter in range(ord("b"), ord("b") + 5):
            _path = conn.path(f"{TEST_DIR}dir/a_dir/{chr(letter)}_dir")
            _path.mkdir(parents=True, exist_ok=True)
            for i in range(3):
                _file = _path / f"file{i}.txt"
                _file.touch()
            copy(src_conn=conn, dst_conn=conn, source=_path, target=f"{TEST_DIR}dir/a_dir/out")

        # Same loop, but can't join them together to be sure old files are not removed by new copy call
        for letter in range(ord("b"), ord("b") + 5):
            for i in range(3):
                assert conn.path(f"{TEST_DIR}dir/a_dir/out/{chr(letter)}_dir/file{i}.txt").exists()

    @pytest.mark.parametrize("conn", ["rpyc", "local"])
    def test_copy_local_python_asteriks(self, conn, request):
        conn = request.getfixturevalue(conn)
        logging.debug(f"System: {sys.platform}")
        dir1 = conn.path(f"{TEST_DIR}dir/a_dir/b_dir/")
        dir1.mkdir(parents=True, exist_ok=True)
        file1 = conn.path(f"{TEST_DIR}dir/a_dir/b_dir/file1.txt")
        file1.touch()
        dir2 = conn.path(f"{TEST_DIR}dir/a_dir/b_dir/c_dir")
        dir2.mkdir(parents=True, exist_ok=True)

        copy(src_conn=conn, dst_conn=conn, source=f"{dir1}/*", target=dir2)

        assert conn.path(f"{TEST_DIR}dir/a_dir/b_dir/c_dir/file1.txt").exists() is True

    @pytest.mark.parametrize("conn", ["rpyc"])
    def test_copy_extension_rpyc(self, conn, request):
        conn = request.getfixturevalue(conn)
        logging.debug(f"System: {sys.platform}")
        dir1 = conn.path(f"{TEST_DIR}dir/a_dir/b_dir/")
        dir1.mkdir(parents=True, exist_ok=True)
        file1 = conn.path(f"{TEST_DIR}dir/a_dir/b_dir/file1.txt")
        file1.touch()
        file2 = conn.path(f"{TEST_DIR}dir/a_dir/b_dir/file2.txt")
        file2.touch()
        dir2 = conn.path(f"{TEST_DIR}dir/a_dir/b_dir/c_dir")
        dir2.mkdir(parents=True, exist_ok=True)

        copy(src_conn=conn, dst_conn=conn, source=f"{dir1}/*", target=dir2)

        assert conn.path(f"{TEST_DIR}dir/a_dir/b_dir/c_dir/file1.txt").exists() is True
        assert conn.path(f"{TEST_DIR}dir/a_dir/b_dir/c_dir/file2.txt").exists() is True

    def test_copy_asteriks_ssh_ssh_linux(self, ssh_lnx_src, ssh_lnx_dst):
        logging.debug(f"System: {sys.platform}")
        dir_to_copy = ssh_lnx_src.path(f"{TEST_DIR}dir/a_dir/b_dir/")
        dir_to_copy.mkdir(parents=True, exist_ok=True)
        copy_me = ssh_lnx_src.path(f"{TEST_DIR}dir/a_dir/b_dir/copy_me.txt")
        copy_me.touch()
        copy(src_conn=ssh_lnx_src, dst_conn=ssh_lnx_dst, source=f"{dir_to_copy}/*", target=TEST_DIR)

        assert ssh_lnx_dst.path(f"{TEST_DIR}copy_me.txt").exists() is True

        ssh_lnx_src.path(TEST_DIR).rmdir()
        ssh_lnx_dst.path(TEST_DIR).rmdir()

    def test_copy_directory_ssh_ssh_linux(self, ssh_lnx_src, ssh_lnx_dst):
        logging.debug(f"System: {sys.platform}")
        dir_to_copy = ssh_lnx_src.path(f"{TEST_DIR}dir/a_dir/b_dir/")
        dir_to_copy.mkdir(parents=True, exist_ok=True)
        copy(src_conn=ssh_lnx_src, dst_conn=ssh_lnx_dst, source=dir_to_copy, target=f"{TEST_DIR}target_dir")

        assert ssh_lnx_dst.path(f"{TEST_DIR}target_dir/b_dir").exists() is True

        ssh_lnx_src.path(TEST_DIR).rmdir()
        ssh_lnx_dst.path(TEST_DIR).rmdir()

    def test_copy_asteriks_rpyc_ssh(self, rpyc_linux, ssh_lnx_dst):
        logging.debug(f"System: {sys.platform}")
        dir_to_copy = rpyc_linux.path(f"{TEST_DIR}dir/a_dir/b_dir/")
        dir_to_copy.mkdir(parents=True, exist_ok=True)
        copy_me = rpyc_linux.path(f"{TEST_DIR}dir/a_dir/b_dir/copy_me.txt")
        copy_me.touch()
        copy_me2 = rpyc_linux.path(f"{TEST_DIR}dir/a_dir/b_dir/copy_me2.txt")
        copy_me2.touch()
        copy(src_conn=rpyc_linux, dst_conn=ssh_lnx_dst, source=f"{dir_to_copy}/*", target=TEST_DIR)

        assert ssh_lnx_dst.path(f"{TEST_DIR}copy_me.txt").exists() is True
        assert ssh_lnx_dst.path(f"{TEST_DIR}copy_me2.txt").exists() is True

        rpyc_linux.path(f"{TEST_DIR}dir/a_dir/b_dir/copy_me.txt").unlink()
        rpyc_linux.path(f"{TEST_DIR}dir/a_dir/b_dir/copy_me2.txt").unlink()
        rpyc_linux.path(f"{TEST_DIR}dir/a_dir/b_dir/").rmdir()
        rpyc_linux.path(f"{TEST_DIR}dir/a_dir/").rmdir()
        rpyc_linux.path(f"{TEST_DIR}dir/").rmdir()
        rpyc_linux.path(TEST_DIR).rmdir()

        ssh_lnx_dst.path(f"{TEST_DIR}copy_me.txt").unlink()
        ssh_lnx_dst.path(TEST_DIR).rmdir()
