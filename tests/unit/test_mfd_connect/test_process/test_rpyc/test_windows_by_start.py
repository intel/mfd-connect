# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
import threading
from io import TextIOWrapper
from pathlib import Path
from subprocess import Popen

import pytest
from mfd_common_libs.log_levels import MODULE_DEBUG

from mfd_connect import RPyCConnection
from mfd_connect.exceptions import RemoteProcessStreamNotAvailable
from mfd_connect.process.rpyc import WindowsRPyCProcessByStart


class TestWindowsRPyCProcess:
    class_under_test = WindowsRPyCProcessByStart
    owner = RPyCConnection

    @pytest.fixture
    def rpyc_process(self, mocker):
        if hasattr(self.class_under_test, "__abstractmethods__"):
            # Remove abstract methods, if any so the class can be instantiated
            self.class_under_test.__abstractmethods__ = []
        rpyc_process = self.class_under_test.__new__(self.class_under_test)
        rpyc_owner = mocker.create_autospec(self.owner, spec_set=True)
        rpyc_process._owner = rpyc_owner
        rpyc_process._process = mocker.create_autospec(
            Popen,
            instance=True,
            stdin=mocker.create_autospec(TextIOWrapper),
            stdout=mocker.create_autospec(TextIOWrapper),
            stderr=mocker.create_autospec(TextIOWrapper),
            pid=mocker.sentinel.pid,
            returncode=mocker.sentinel.returncode,
        )
        rpyc_process._remote_get_process_io_queue_cache_lock = mocker.create_autospec(threading.Lock(), spec_set=True)
        rpyc_process._stdout_queue_cache_lock = mocker.create_autospec(threading.Lock(), spec_set=True)
        rpyc_process._stdout_iter_cache_lock = mocker.create_autospec(threading.Lock(), spec_set=True)
        rpyc_process._stderr_queue_cache_lock = mocker.create_autospec(threading.Lock(), spec_set=True)
        rpyc_process._stderr_iter_cache_lock = mocker.create_autospec(threading.Lock(), spec_set=True)
        mocker.patch("mfd_connect.process.rpyc.windows.WindowsRPyCProcess.running", return_value=True)
        return rpyc_process

    def test_streams(self, rpyc_process):
        with pytest.raises(RemoteProcessStreamNotAvailable):
            _ = rpyc_process.stdin_stream
        with pytest.raises(RemoteProcessStreamNotAvailable):
            _ = rpyc_process.stdout_stream
        with pytest.raises(RemoteProcessStreamNotAvailable):
            _ = rpyc_process.stderr_stream

    def test_get_stdout_iter(self, rpyc_process, mocker, caplog):
        caplog.set_level(MODULE_DEBUG)
        mymock_open = mocker.patch("pathlib.Path.open")
        rpyc_process.log_path = None
        assert list(rpyc_process.get_stdout_iter()) == []
        assert "Discarded stdout, output is not available." in caplog.text
        opener = mocker.mock_open(read_data="some output\nnext_output")

        mymock_open.side_effect = opener.side_effect
        mymock_open.return_value = opener.return_value
        rpyc_process.log_path = Path("")

        assert list(rpyc_process.get_stdout_iter()) == ["some output\n", "next_output"]

    def test_get_stderr_iter(
        self,
        rpyc_process,
    ):
        assert list(rpyc_process.get_stderr_iter()) == []

    def test_stdout_text(self, rpyc_process, mocker):
        rpyc_process.running = False
        mocker.patch.object(rpyc_process, "get_stdout_iter", return_value=["a", "b"])
        assert rpyc_process.stdout_text == "ab"

    def test_stderr_text(self, rpyc_process, caplog):
        caplog.set_level(MODULE_DEBUG)
        rpyc_process.running = False
        assert rpyc_process.stderr_text == ""
        assert "Stderr is not supported on Windows, because it's aggregated with stdout" in caplog.text
