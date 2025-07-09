# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
from signal import SIGTERM

import psutil
from mfd_common_libs import log_levels
from psutil import NoSuchProcess

from mfd_connect.exceptions import (
    RemoteProcessStreamNotAvailable,
    RemoteProcessTimeoutExpired,
    RemoteProcessInvalidState,
)
from mfd_connect.process.rpyc import RPyCProcess
from mfd_connect import RPyCConnection
import threading
import pytest
from io import TextIOWrapper
from subprocess import Popen
from mfd_connect.util import BatchQueue


class TestRPyCProcess:
    class_under_test = RPyCProcess
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
        return rpyc_process

    @pytest.fixture
    def _stdout_queue_mock(self, mocker):
        return mocker.patch.object(self.class_under_test, "_stdout_queue", new_callable=mocker.PropertyMock)

    @pytest.fixture
    def _stderr_queue_mock(self, mocker):
        return mocker.patch.object(self.class_under_test, "_stderr_queue", new_callable=mocker.PropertyMock)

    @pytest.fixture
    def running_mock(self, mocker):
        return mocker.patch.object(self.class_under_test, "running", new_callable=mocker.PropertyMock)

    @pytest.fixture
    def sleep_mock(self, mocker):
        return mocker.patch("mfd_connect.process.rpyc.base.sleep", autospec=True, spec_set=True)

    def test__stdout_queue_not_cached(self, rpyc_process, mocker):
        stdout_stream_mock = mocker.patch.object(
            self.class_under_test, "stdout_stream", new_callable=mocker.PropertyMock
        )
        rpyc_process._get_process_io_queue = mocker.create_autospec(rpyc_process._get_process_io_queue, spec_set=True)
        rpyc_process._cached_remote_get_process_io_queue = None
        rpyc_process._cached_stdout_queue = None
        assert rpyc_process._stdout_queue == rpyc_process._remote_get_process_io_queue.return_value
        print(rpyc_process._remote_get_process_io_queue)
        rpyc_process._remote_get_process_io_queue.assert_called_once_with(stdout_stream_mock.return_value, BatchQueue)
        rpyc_process._stdout_queue_cache_lock.__enter__.assert_called()
        rpyc_process._stdout_queue_cache_lock.__exit__.assert_called()

    def test__stdout_queue_cached(self, rpyc_process, mocker):
        rpyc_process._cached_stdout_queue = mocker.sentinel.cached
        rpyc_process._cached_remote_get_process_io_queue = mocker.sentinel.cached
        rpyc_process._get_process_io_queue = mocker.create_autospec(rpyc_process._get_process_io_queue, spec_set=True)
        assert rpyc_process._stdout_queue == mocker.sentinel.cached
        rpyc_process._owner.teleport_function.assert_not_called()

        rpyc_process._stdout_queue_cache_lock.__enter__.assert_called()
        rpyc_process._stdout_queue_cache_lock.__exit__.assert_called()

    def test__stderr_queue_not_cached(self, rpyc_process, mocker):
        stderr_stream_mock = mocker.patch.object(
            self.class_under_test, "stderr_stream", new_callable=mocker.PropertyMock
        )
        rpyc_process._get_process_io_queue = mocker.create_autospec(rpyc_process._get_process_io_queue, spec_set=True)
        rpyc_process._cached_remote_get_process_io_queue = None
        rpyc_process._cached_stderr_queue = None
        assert rpyc_process._stderr_queue == rpyc_process._remote_get_process_io_queue.return_value
        rpyc_process._remote_get_process_io_queue.assert_called_once_with(stderr_stream_mock.return_value, BatchQueue)
        rpyc_process._stderr_queue_cache_lock.__enter__.assert_called()
        rpyc_process._stderr_queue_cache_lock.__exit__.assert_called()

    def test__stderr_queue_cached(self, rpyc_process, mocker):
        rpyc_process._cached_stderr_queue = mocker.sentinel.cached
        rpyc_process._remote_get_process_io_queue_cache_lock = mocker.sentinel.cached
        rpyc_process._get_process_io_queue = mocker.create_autospec(rpyc_process._get_process_io_queue, spec_set=True)
        assert rpyc_process._stderr_queue == mocker.sentinel.cached
        rpyc_process._owner.teleport_function.assert_not_called()
        rpyc_process._stderr_queue_cache_lock.__enter__.assert_called()
        rpyc_process._stderr_queue_cache_lock.__exit__.assert_called()

    def test__iterate_non_blocking_queue(self, rpyc_process, sleep_mock, mocker):
        q = mocker.create_autospec(BatchQueue(), spec_set=True)
        q.get_many.side_effect = [[mocker.sentinel.line1, mocker.sentinel.line2], [], [mocker.sentinel.line3, None]]

        assert all(
            [
                expect == actual
                for expect, actual in zip(
                    [mocker.sentinel.line1, mocker.sentinel.line2, mocker.sentinel.line3],
                    rpyc_process._iterate_non_blocking_queue(q),
                )
            ]
        )

        sleep_mock.assert_called_once_with(rpyc_process.POOL_INTERVAL)

    def test_running_when_poll_is_none(self, rpyc_process):
        rpyc_process._process.poll.return_value = None
        assert rpyc_process.running

    def test_runinng_when_poll_is_not_none(self, rpyc_process, mocker):
        rpyc_process._process.poll.return_value = mocker.sentinel.not_none
        assert not rpyc_process.running

    def test_stdin_stream_available(self, rpyc_process):
        assert rpyc_process.stdin_stream == rpyc_process._process.stdin

    def test_stdin_stream_raises_if_not_available(self, rpyc_process):
        rpyc_process._process.stdin = None
        with pytest.raises(RemoteProcessStreamNotAvailable):
            _ = rpyc_process.stdin_stream

    def test_stdout_stream_available(self, rpyc_process):
        assert rpyc_process.stdout_stream, rpyc_process._process.stdout

    def test_kill_no_wait(self, rpyc_process, mocker):
        rpyc_process._start_pipe_drain = mocker.create_autospec(rpyc_process._start_pipe_drain)
        rpyc_process._get_and_kill_process = mocker.create_autospec(rpyc_process._get_and_kill_process)
        rpyc_process.wait = mocker.create_autospec(rpyc_process.wait)
        rpyc_process.kill(wait=None)
        rpyc_process._get_and_kill_process.assert_called_once_with(with_signal=SIGTERM)
        rpyc_process._start_pipe_drain.assert_called_once_with()
        rpyc_process.wait.assert_not_called()

    def test_stdout_stream_raises_if_not_available(self, rpyc_process):
        rpyc_process._process.stdout = None
        with pytest.raises(RemoteProcessStreamNotAvailable):
            _ = rpyc_process.stdout_stream

    def test_stderr_stream_available(self, rpyc_process):
        assert rpyc_process.stderr_stream == rpyc_process._process.stderr

    def test_stderr_stream_raises_if_not_available(self, rpyc_process):
        rpyc_process._process.stderr = None
        with pytest.raises(RemoteProcessStreamNotAvailable):
            _ = rpyc_process.stderr_stream

    def test_get_stdout_iter_not_cached(self, rpyc_process, _stdout_queue_mock, mocker):
        expected_return = [mocker.sentinel.line1, mocker.sentinel.line2]
        rpyc_process._cached_stdout_iter = None
        rpyc_process._iterate_non_blocking_queue = mocker.create_autospec(
            rpyc_process._iterate_non_blocking_queue, spec_set=True
        )
        rpyc_process._iterate_non_blocking_queue.return_value = mocker.MagicMock()
        rpyc_process._iterate_non_blocking_queue.return_value.__iter__.return_value = expected_return

        assert all([expect == actual for expect, actual in zip(expected_return, rpyc_process.get_stdout_iter())])

        rpyc_process._iterate_non_blocking_queue.assert_called_once_with(_stdout_queue_mock.return_value)
        assert rpyc_process._cached_stdout_iter is not None
        rpyc_process._stdout_iter_cache_lock.__enter__.assert_called()
        rpyc_process._stdout_iter_cache_lock.__exit__.assert_called()

    def test_get_stdout_iter_cached(self, rpyc_process, _stdout_queue_mock, mocker):
        expected_return = [mocker.sentinel.line1, mocker.sentinel.line2]
        rpyc_process._cached_stdout_iter = mocker.MagicMock()
        rpyc_process._cached_stdout_iter.__iter__.return_value = expected_return
        rpyc_process._iterate_non_blocking_queue = mocker.create_autospec(
            rpyc_process._iterate_non_blocking_queue, spec_set=True
        )

        assert all([expect == actual for expect, actual in zip(expected_return, rpyc_process.get_stdout_iter())])

        rpyc_process._iterate_non_blocking_queue.assert_not_called()
        rpyc_process._stdout_iter_cache_lock.__enter__.assert_called()
        rpyc_process._stdout_iter_cache_lock.__exit__.assert_called()

    def test_get_stderr_iter_not_cached(self, rpyc_process, _stderr_queue_mock, mocker):
        expected_return = [mocker.sentinel.line1, mocker.sentinel.line2]
        rpyc_process._cached_stderr_iter = None
        rpyc_process._iterate_non_blocking_queue = mocker.create_autospec(
            rpyc_process._iterate_non_blocking_queue, spec_set=True
        )
        rpyc_process._iterate_non_blocking_queue.return_value = mocker.MagicMock()
        rpyc_process._iterate_non_blocking_queue.return_value.__iter__.return_value = expected_return

        assert all([expect == actual for expect, actual in zip(expected_return, rpyc_process.get_stderr_iter())])

        rpyc_process._iterate_non_blocking_queue.assert_called_once_with(_stderr_queue_mock.return_value)
        assert rpyc_process._cached_stderr_iter is not None
        rpyc_process._stderr_iter_cache_lock.__enter__.assert_called()
        rpyc_process._stderr_iter_cache_lock.__exit__.assert_called()

    def test_get_stderr_iter_cached(self, rpyc_process, _stderr_queue_mock, mocker):
        expected_return = [mocker.sentinel.line1, mocker.sentinel.line2]
        rpyc_process._cached_stderr_iter = mocker.MagicMock()
        rpyc_process._cached_stderr_iter.__iter__.return_value = expected_return
        rpyc_process._iterate_non_blocking_queue = mocker.create_autospec(
            rpyc_process._iterate_non_blocking_queue, spec_set=True
        )

        assert all([expect == actual for expect, actual in zip(expected_return, rpyc_process.get_stderr_iter())])

        rpyc_process._iterate_non_blocking_queue.assert_not_called()
        rpyc_process._stderr_iter_cache_lock.__enter__.assert_called()
        rpyc_process._stderr_iter_cache_lock.__exit__.assert_called()

    def test_stdout_text(self, rpyc_process, running_mock, mocker):
        running_mock.return_value = False
        rpyc_process.get_stdout_iter = mocker.create_autospec(rpyc_process.get_stdout_iter)
        rpyc_process.get_stdout_iter.return_value.__iter__.return_value = ["foo", "bar", "baz"]

        assert rpyc_process.stdout_text == "foobarbaz"

    def test_stderr_text(self, rpyc_process, running_mock, mocker):
        running_mock.return_value = False
        rpyc_process.get_stderr_iter = mocker.create_autospec(rpyc_process.get_stderr_iter)
        rpyc_process.get_stderr_iter.return_value.__iter__.return_value = ["foo", "bar", "baz"]

        assert rpyc_process.stderr_text == "foobarbaz"

    def test_return_code(self, rpyc_process, running_mock):
        running_mock.return_value = False
        assert rpyc_process.return_code == rpyc_process._process.returncode

    def test_wait_no_timeout(self, rpyc_process, sleep_mock, running_mock, mocker):
        running_mock.side_effect = [True, False]
        return_code_mock = mocker.patch.object(self.class_under_test, "return_code", new_callable=mocker.PropertyMock)
        return_code_mock.return_value = mocker.sentinel.return_code
        rpyc_process._start_pipe_drain = mocker.create_autospec(rpyc_process._start_pipe_drain)

        assert rpyc_process.wait() == mocker.sentinel.return_code

        sleep_mock.assert_called_once_with(rpyc_process.POOL_INTERVAL)
        rpyc_process._start_pipe_drain.assert_called_once_with()

    def test_wait_timeout_happened(self, rpyc_process, sleep_mock, running_mock, mocker):
        running_mock.return_value = True
        timeout_counter_class_mock = mocker.patch(
            "mfd_connect.process.rpyc.base.TimeoutCounter", autospec=True, spec_set=True
        )
        timeout_counter_class_mock.return_value.__bool__.side_effect = [False, True]
        rpyc_process._start_pipe_drain = mocker.create_autospec(rpyc_process._start_pipe_drain)

        with pytest.raises(RemoteProcessTimeoutExpired):
            rpyc_process.wait(timeout=10)

        timeout_counter_class_mock.assert_called_once_with(timeout=10)
        sleep_mock.assert_called_once_with(rpyc_process.POOL_INTERVAL)
        rpyc_process._start_pipe_drain.assert_called_once_with()

    def test_kill_wait(self, rpyc_process, mocker):
        rpyc_process._start_pipe_drain = mocker.create_autospec(rpyc_process._start_pipe_drain)
        rpyc_process._get_and_kill_process = mocker.create_autospec(rpyc_process._get_and_kill_process)
        rpyc_process.wait = mocker.create_autospec(rpyc_process.wait)
        rpyc_process.kill(wait=10)
        rpyc_process._get_and_kill_process.assert_called_once_with(with_signal=SIGTERM)
        rpyc_process._start_pipe_drain.assert_called_once_with()
        rpyc_process.wait.assert_called_once_with(timeout=10)

    def test_stop(self, rpyc_process, mocker):
        rpyc_process._start_pipe_drain = mocker.create_autospec(rpyc_process._start_pipe_drain)
        rpyc_process.stop()
        rpyc_process._start_pipe_drain.assert_called_once_with()

    def test__start_pipe_drain_no_error(self, rpyc_process, _stdout_queue_mock, _stderr_queue_mock):
        rpyc_process._start_pipe_drain()
        _stdout_queue_mock.assert_called_once()
        _stderr_queue_mock.assert_called_once()

    def test__start_pipe_drain_suppresses_stream_not_available(
        self, rpyc_process, _stdout_queue_mock, _stderr_queue_mock
    ):
        _stdout_queue_mock.side_effect = RemoteProcessStreamNotAvailable
        _stderr_queue_mock.side_effect = RemoteProcessStreamNotAvailable

        rpyc_process._start_pipe_drain()

        _stdout_queue_mock.assert_called_once()
        _stderr_queue_mock.assert_called_once()

    def test__start_pipe_drain_propagates_unexpected_errors(self, rpyc_process, _stdout_queue_mock, _stderr_queue_mock):
        _stdout_queue_mock.side_effect = Exception()
        with pytest.raises(Exception):
            rpyc_process._start_pipe_drain()

    def test__kill_process(self, rpyc_process, mocker, caplog):
        caplog.set_level(log_levels.MODULE_DEBUG)
        psutil_process = mocker.create_autospec(psutil.Process)
        psutil_process.pid = 123
        rpyc_process._kill_process(psutil_process)
        psutil_process.kill.assert_called_once()
        assert "Killing process 123" in caplog.text
        assert "Killed process 123" in caplog.text
        caplog.clear()
        sigterm_mock = mocker.Mock()
        sigterm_mock.name = "SIGTERM"
        rpyc_process._convert_to_signal_object = mocker.create_autospec(
            rpyc_process._convert_to_signal_object, return_value=sigterm_mock
        )
        rpyc_process._kill_process(psutil_process, with_signal=SIGTERM)
        psutil_process.send_signal.assert_called_once_with(sigterm_mock)
        assert "Sending signal 'SIGTERM' to process 123" in caplog.text
        assert "Sent signal 'SIGTERM' to process 123" in caplog.text

    def test__kill_process_child(self, rpyc_process, mocker, caplog):
        caplog.set_level(log_levels.MODULE_DEBUG)
        sigterm_mock = mocker.Mock()
        sigterm_mock.name = "SIGTERM"
        rpyc_process._convert_to_signal_object = mocker.create_autospec(
            rpyc_process._convert_to_signal_object, return_value=sigterm_mock
        )
        psutil_process = mocker.create_autospec(psutil.Process)
        psutil_process.pid = 123
        rpyc_process._kill_process(psutil_process, is_child=True)
        psutil_process.kill.assert_called_once()
        assert "Killing child process 123" in caplog.text
        assert "Killed child process 123" in caplog.text
        caplog.clear()
        rpyc_process._kill_process(psutil_process, with_signal=SIGTERM, is_child=True)
        psutil_process.send_signal.assert_called_once_with(sigterm_mock)
        assert "Sending signal 'SIGTERM' to child process 123" in caplog.text
        assert "Sent signal 'SIGTERM' to child process 123" in caplog.text

    def test__kill_process_with_windows_exception(self, rpyc_process, mocker, caplog):
        caplog.set_level(log_levels.MODULE_DEBUG)
        psutil_process = mocker.create_autospec(psutil.Process)
        psutil_process.pid = 123
        psutil_process.kill.side_effect = NoSuchProcess(pid=123, msg="process no longer exists")
        rpyc_process._kill_process(psutil_process)
        psutil_process.kill.assert_called_once()
        assert "Killing process 123" in caplog.text
        assert "got exception during killing: process no longer exists (pid=123)" in caplog.text
        assert "Process has been killed" in caplog.text

    def test__kill_process_with_exception(self, rpyc_process, mocker, caplog):
        caplog.set_level(log_levels.MODULE_DEBUG)
        psutil_process = mocker.create_autospec(psutil.Process)
        psutil_process.pid = 123
        psutil_process.kill.side_effect = NoSuchProcess(pid=123, msg="process no exists")
        with pytest.raises(RemoteProcessInvalidState):
            rpyc_process._kill_process(psutil_process)
        psutil_process.kill.assert_called_once()
        assert "Killing process 123" in caplog.text
        assert "got exception during killing: process no exists (pid=123)" in caplog.text

    def test__convert_to_signal_object(self, rpyc_process):
        rpyc_process._owner.modules().signal.Signals.__getitem__.return_value = (
            rpyc_process._owner.modules().signal.SIGTERM
        )
        with_signal = "sigterm"
        converted_signal = rpyc_process._convert_to_signal_object(with_signal)
        assert converted_signal == rpyc_process._owner.modules().signal.SIGTERM
        rpyc_process._owner.modules().signal.Signals.__getitem__.assert_called_with("SIGTERM")
        rpyc_process._owner.modules().signal.Signals.return_value = rpyc_process._owner.modules().signal.SIGTERM
        with_signal = 15
        converted_signal = rpyc_process._convert_to_signal_object(with_signal)
        assert converted_signal == rpyc_process._owner.modules().signal.SIGTERM
        with_signal = SIGTERM
        converted_signal = rpyc_process._convert_to_signal_object(with_signal)
        assert converted_signal == rpyc_process._owner.modules().signal.Signals.SIGTERM

    def test_pid(self, rpyc_process, mocker):
        check = mocker.sentinel.pid
        assert rpyc_process.pid == check
