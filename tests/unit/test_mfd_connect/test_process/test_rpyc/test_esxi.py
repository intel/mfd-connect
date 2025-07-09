# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
import threading
from io import TextIOWrapper
from signal import SIGINT
from subprocess import Popen

import pytest

from mfd_connect import RPyCConnection
from mfd_connect.base import ConnectionCompletedProcess
from mfd_connect.exceptions import RemoteProcessInvalidState
from mfd_connect.process.base import ESXiRemoteProcess
from mfd_connect.process.rpyc import ESXiRPyCProcess


class TestESXiRPyCProcess:
    class_under_test = ESXiRPyCProcess
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
        mocker.patch("mfd_connect.process.rpyc.esxi.ESXiRPyCProcess.running", return_value=True)
        return rpyc_process

    def test_stop(self, rpyc_process, mocker):
        rpyc_process._start_pipe_drain = mocker.create_autospec(rpyc_process._start_pipe_drain)
        rpyc_process._get_and_kill_process = mocker.create_autospec(rpyc_process._get_and_kill_process)
        rpyc_process.stop(None)
        rpyc_process._start_pipe_drain.assert_called_with()
        rpyc_process._get_and_kill_process.assert_called_once_with(with_signal=SIGINT)

    def test_stop_already_finished_process_exception(self, rpyc_process):
        rpyc_process.running = False

        with pytest.raises(RemoteProcessInvalidState, match="Process has already finished"):
            rpyc_process.stop()

    def test___get_and_kill_process(self, rpyc_process, mocker):
        rpyc_process._process.pid = 10
        rpyc_process._convert_to_signal_object = mocker.Mock(return_value=SIGINT)
        rpyc_process._owner.execute_command.return_value = ConnectionCompletedProcess(
            args="", return_code=0, stdout="ping"
        )
        rpyc_process._get_and_kill_process()
        rpyc_process._owner.modules().os.kill.assert_called_once_with(10, SIGINT)

    def test___get_and_kill_process_with_children(self, rpyc_process, mocker):
        rpyc_process._process.pid = 10
        rpyc_process._convert_to_signal_object = mocker.Mock(return_value=SIGINT)
        ESXiRemoteProcess._find_children_process = mocker.Mock(return_value=[11])
        rpyc_process._owner.execute_command.return_value = ConnectionCompletedProcess(
            args="", return_code=0, stdout="/bin/sh"
        )
        rpyc_process._get_and_kill_process()
        rpyc_process._owner.modules().os.kill.assert_has_calls(
            [mocker.call(11, SIGINT), mocker.call(10, SIGINT)], any_order=True
        )
