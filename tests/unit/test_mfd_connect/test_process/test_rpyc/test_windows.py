# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
from mfd_connect import RPyCConnection
from mfd_connect.exceptions import RemoteProcessInvalidState
from mfd_connect.process.rpyc import WindowsRPyCProcess
import threading
import pytest
from io import TextIOWrapper
from subprocess import Popen


class TestWindowsRPyCProcess:
    class_under_test = WindowsRPyCProcess
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

    def test_stop(self, rpyc_process, mocker):
        rpyc_process._start_pipe_drain = mocker.create_autospec(rpyc_process._start_pipe_drain)
        rpyc_process._get_and_kill_process = mocker.create_autospec(rpyc_process._get_and_kill_process)
        rpyc_process.stop(None)
        rpyc_process._start_pipe_drain.assert_called_with()
        rpyc_process._get_and_kill_process.assert_called_once()

    def test_stop_with_wait(self, rpyc_process, mocker):
        rpyc_process._start_pipe_drain = mocker.create_autospec(rpyc_process._start_pipe_drain)
        rpyc_process._stop_pipe_drain = mocker.create_autospec(rpyc_process._stop_pipe_drain)
        rpyc_process._get_and_kill_process = mocker.create_autospec(rpyc_process._get_and_kill_process)
        rpyc_process.wait = mocker.create_autospec(rpyc_process.wait)
        rpyc_process.stop(wait=10)
        rpyc_process._get_and_kill_process.assert_called_once_with(
            with_signal=rpyc_process._owner.modules().signal.CTRL_C_EVENT
        )
        rpyc_process.wait.assert_called_once_with(timeout=10)
        rpyc_process._stop_pipe_drain.assert_called_once_with()

    def test_kill_unsupported_signal_changes_to_sigterm(self, rpyc_process, mocker):
        super_kill = mocker.patch("mfd_connect.process.rpyc.windows.RPyCProcess.kill", autospec=True)
        rpyc_process.kill(wait=None, with_signal="SIGKILL")
        super_kill.assert_called_once_with(
            rpyc_process, wait=None, with_signal=rpyc_process._owner.modules().signal.SIGTERM
        )

    def test_kill_supported_signal(self, rpyc_process, mocker):
        super_kill = mocker.patch("mfd_connect.process.rpyc.windows.RPyCProcess.kill", autospec=True)
        rpyc_process.kill(wait=None, with_signal="CTRL_C_EVENT")
        super_kill.assert_called_once_with(rpyc_process, wait=None, with_signal="CTRL_C_EVENT")

    def test_stop_already_finished_process_exception(self, rpyc_process):
        rpyc_process.running = False

        with pytest.raises(RemoteProcessInvalidState, match="Process has already finished"):
            rpyc_process.stop()
