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
        rpyc_process._cached_stdout_stop_event = None
        rpyc_process._cached_stdout_done_event = None
        rpyc_process._owner.teleport_function.return_value.return_value = (
            mocker.sentinel.queue,
            mocker.sentinel.stop_event,
            mocker.sentinel.done_event,
        )
        assert rpyc_process._stdout_queue == mocker.sentinel.queue
        assert rpyc_process._cached_stdout_stop_event == mocker.sentinel.stop_event
        assert rpyc_process._cached_stdout_done_event == mocker.sentinel.done_event
        rpyc_process._remote_get_process_io_queue.assert_called_once_with(stdout_stream_mock.return_value)
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
        rpyc_process._cached_stderr_stop_event = None
        rpyc_process._cached_stderr_done_event = None
        rpyc_process._owner.teleport_function.return_value.return_value = (
            mocker.sentinel.queue,
            mocker.sentinel.stop_event,
            mocker.sentinel.done_event,
        )
        assert rpyc_process._stderr_queue == mocker.sentinel.queue
        assert rpyc_process._cached_stderr_stop_event == mocker.sentinel.stop_event
        assert rpyc_process._cached_stderr_done_event == mocker.sentinel.done_event
        rpyc_process._remote_get_process_io_queue.assert_called_once_with(stderr_stream_mock.return_value)
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
        drainer = mocker.Mock()
        drainer.drain.side_effect = [
            ("line1\nline2\n", False),
            ("", False),
            ("line3\n", True),
            ("", True),
        ]

        result = list(rpyc_process._iterate_non_blocking_queue(drainer))

        assert result == ["line1\n", "line2\n", "line3\n"]
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
        rpyc_process._stop_pipe_drain = mocker.create_autospec(rpyc_process._stop_pipe_drain)
        rpyc_process._get_and_kill_process = mocker.create_autospec(rpyc_process._get_and_kill_process)
        rpyc_process.wait = mocker.create_autospec(rpyc_process.wait)
        rpyc_process.kill(wait=None)
        rpyc_process._get_and_kill_process.assert_called_once_with(with_signal=SIGTERM)
        rpyc_process._start_pipe_drain.assert_called_once_with()
        rpyc_process.wait.assert_not_called()
        rpyc_process._stop_pipe_drain.assert_not_called()

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
        rpyc_process._stop_pipe_drain = mocker.create_autospec(rpyc_process._stop_pipe_drain)
        rpyc_process._get_and_kill_process = mocker.create_autospec(rpyc_process._get_and_kill_process)
        rpyc_process.wait = mocker.create_autospec(rpyc_process.wait)
        rpyc_process.kill(wait=10)
        rpyc_process._get_and_kill_process.assert_called_once_with(with_signal=SIGTERM)
        rpyc_process._start_pipe_drain.assert_called_once_with()
        rpyc_process.wait.assert_called_once_with(timeout=10)
        rpyc_process._stop_pipe_drain.assert_called_once_with()

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

    def test__stop_pipe_drain_skips_stop_when_drained(self, rpyc_process, mocker):
        # Watchers already finished (done/EOF) - trailing output fully captured, do not force stop.
        stdout_done = mocker.Mock()
        stdout_done.is_set.return_value = True
        stderr_done = mocker.Mock()
        stderr_done.is_set.return_value = True
        rpyc_process._cached_stdout_queue = mocker.Mock()
        rpyc_process._cached_stderr_queue = mocker.Mock()
        rpyc_process._cached_stdout_stop_event = mocker.Mock()
        rpyc_process._cached_stderr_stop_event = mocker.Mock()
        rpyc_process._cached_stdout_done_event = stdout_done
        rpyc_process._cached_stderr_done_event = stderr_done

        rpyc_process._stop_pipe_drain(idle_timeout=1)

        rpyc_process._cached_stdout_stop_event.set.assert_not_called()
        rpyc_process._cached_stderr_stop_event.set.assert_not_called()

    def test__stop_pipe_drain_sets_stop_when_idle(self, rpyc_process, sleep_mock, mocker):
        # Stream produces no new output (constant progress) and never reaches EOF - force stop after idle.
        timeout_mock = mocker.patch("mfd_connect.process.rpyc.base.TimeoutCounter")
        timeout_mock.return_value.__bool__.return_value = True  # idle window already elapsed
        done_event = mocker.Mock()
        done_event.is_set.return_value = False
        drainer = mocker.Mock()
        drainer.progress.return_value = 5  # constant -> no progress
        rpyc_process._cached_stdout_queue = drainer
        rpyc_process._cached_stdout_stop_event = mocker.Mock()
        rpyc_process._cached_stdout_done_event = done_event
        rpyc_process._cached_stderr_queue = None
        rpyc_process._cached_stderr_stop_event = None
        rpyc_process._cached_stderr_done_event = None

        rpyc_process._stop_pipe_drain()

        rpyc_process._cached_stdout_stop_event.set.assert_called_once_with()

    def test__stop_pipe_drain_sets_stop_when_max_timeout_exceeded(self, rpyc_process, sleep_mock, mocker):
        # Output keeps flowing (idle never fires) but the absolute cap is hit - force stop to avoid a hang.
        idle_counter = mocker.MagicMock()
        idle_counter.__bool__.return_value = False
        hard_counter = mocker.MagicMock()
        hard_counter.__bool__.return_value = True

        def _make_counter(value):
            return hard_counter if value == 1 else idle_counter

        mocker.patch("mfd_connect.process.rpyc.base.TimeoutCounter", side_effect=_make_counter)
        done_event = mocker.Mock()
        done_event.is_set.return_value = False
        drainer = mocker.Mock()
        drainer.progress.return_value = 1  # progress on first check resets idle, but hard cap still fires
        rpyc_process._cached_stdout_queue = drainer
        rpyc_process._cached_stdout_stop_event = mocker.Mock()
        rpyc_process._cached_stdout_done_event = done_event
        rpyc_process._cached_stderr_queue = None
        rpyc_process._cached_stderr_stop_event = None
        rpyc_process._cached_stderr_done_event = None

        rpyc_process._stop_pipe_drain(idle_timeout=30, max_timeout=1)

        rpyc_process._cached_stdout_stop_event.set.assert_called_once_with()

    def test__stop_pipe_drain_waits_while_output_flows(self, rpyc_process, sleep_mock, mocker):
        # progress keeps growing (backlog still buffering), then EOF - never force stop, no truncation.
        done_event = mocker.Mock()
        done_event.is_set.side_effect = [False, False, True]
        drainer = mocker.Mock()
        drainer.progress.side_effect = [1, 2]
        rpyc_process._cached_stdout_queue = drainer
        rpyc_process._cached_stdout_stop_event = mocker.Mock()
        rpyc_process._cached_stdout_done_event = done_event
        rpyc_process._cached_stderr_queue = None
        rpyc_process._cached_stderr_stop_event = None
        rpyc_process._cached_stderr_done_event = None

        rpyc_process._stop_pipe_drain(idle_timeout=30)

        rpyc_process._cached_stdout_stop_event.set.assert_not_called()

    def test__stop_pipe_drain_no_events(self, rpyc_process):
        rpyc_process._cached_stdout_queue = None
        rpyc_process._cached_stderr_queue = None
        rpyc_process._cached_stdout_stop_event = None
        rpyc_process._cached_stderr_stop_event = None
        rpyc_process._cached_stdout_done_event = None
        rpyc_process._cached_stderr_done_event = None

        # Should not raise when drain was never started.
        rpyc_process._stop_pipe_drain()

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

    def test__iterate_non_blocking_queue_flushes_trailing_partial(self, rpyc_process, sleep_mock, mocker):
        # A final line without a trailing newline must still be yielded once EOF is reached.
        drainer = mocker.Mock()
        drainer.drain.side_effect = [("last line no newline", True), ("", True)]

        result = list(rpyc_process._iterate_non_blocking_queue(drainer))

        assert result == ["last line no newline"]

    def test_pid(self, rpyc_process, mocker):
        check = mocker.sentinel.pid
        assert rpyc_process.pid == check

    def test___init__(self, mocker):
        self.class_under_test.__abstractmethods__ = frozenset()
        owner = mocker.sentinel.owner
        process = mocker.sentinel.process
        log_path = mocker.sentinel.log_path
        log_file_stream = mocker.sentinel.log_file_stream

        proc = self.class_under_test(owner=owner, process=process, log_path=log_path, log_file_stream=log_file_stream)

        assert proc._owner is owner
        assert proc._process is process
        assert proc.log_path is log_path
        assert proc.log_file_stream is log_file_stream
        assert proc._cached_remote_get_process_io_queue is None
        assert proc._cached_stdout_queue is None
        assert proc._cached_stdout_stop_event is None
        assert proc._cached_stdout_done_event is None
        assert proc._cached_stdout_iter is None
        assert proc._cached_stderr_queue is None
        assert proc._cached_stderr_stop_event is None
        assert proc._cached_stderr_done_event is None
        assert proc._cached_stderr_iter is None

    def test__get_process_io_queue_reads_lines(self):
        import io

        stream = io.StringIO("line1\nline2\n")
        drainer, stop_event, done_event = RPyCProcess._get_process_io_queue(stream)

        assert done_event.wait(5)
        assert drainer.progress() == 2
        text, done = drainer.drain()

        assert text == "line1\nline2\n"
        assert done is True
        assert isinstance(stop_event, threading.Event)
        assert not stop_event.is_set()

    def test__get_process_io_queue_breaks_when_stop_event_set(self):
        gate = threading.Event()

        class _Stream:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def __iter__(self):
                return self

            def __next__(self):
                gate.wait(5)  # block until the test requests a stop
                return "line\n"

        drainer, stop_event, done_event = RPyCProcess._get_process_io_queue(_Stream())

        stop_event.set()  # request stop while the watcher is blocked in __next__
        gate.set()  # let __next__ return a line - watcher captures it, then breaks

        assert done_event.wait(5)
        text, done = drainer.drain()

        # The already-read line must be captured, then the watcher stops (no infinite loop).
        assert text == "line\n"
        assert done is True

    def test__get_process_io_queue_puts_error_on_exception(self, mocker):
        # Silence the expected re-raised exception reported by the watcher daemon thread.
        mocker.patch.object(threading, "excepthook", lambda args: None)

        class _Stream:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def __iter__(self):
                return self

            def __next__(self):
                raise RuntimeError("boom")

        drainer, _, done_event = RPyCProcess._get_process_io_queue(_Stream())

        assert done_event.wait(5)
        text, done = drainer.drain()

        assert "<internal>: Error occurred during io processing. Check responder log for details." in text
        assert done is True

    def test__get_and_kill_process(self, rpyc_process, mocker):
        psutil_process = mocker.Mock()
        child1 = mocker.Mock()
        child2 = mocker.Mock()
        rpyc_process._get_psutil_process = mocker.create_autospec(
            rpyc_process._get_psutil_process, return_value=psutil_process
        )
        rpyc_process._get_children_processes = mocker.create_autospec(
            rpyc_process._get_children_processes, return_value=[child1, child2]
        )
        rpyc_process._kill_process = mocker.create_autospec(rpyc_process._kill_process)
        rpyc_process._owner.modules().psutil.wait_procs.return_value = ([child1], [child2])

        rpyc_process._get_and_kill_process(with_signal=SIGTERM)

        rpyc_process._kill_process.assert_any_call(child1, SIGTERM, is_child=True)
        rpyc_process._kill_process.assert_any_call(child2, SIGTERM, is_child=True)
        rpyc_process._kill_process.assert_any_call(psutil_process, SIGTERM)
        rpyc_process._owner.modules().psutil.wait_procs.assert_called_once_with([child1, child2], timeout=5)
        psutil_process.wait.assert_called_once_with(5)

    def test__get_children_processes(self, rpyc_process, mocker):
        process = mocker.Mock()
        result = rpyc_process._get_children_processes(process=process)
        process.children.assert_called_once_with(recursive=True)
        assert result == process.children.return_value

    def test__get_psutil_process(self, rpyc_process):
        result = rpyc_process._get_psutil_process()
        rpyc_process._owner.modules().psutil.Process.assert_called_with(rpyc_process._process.pid)
        assert result == rpyc_process._owner.modules().psutil.Process.return_value

    def test__get_psutil_process_raises_when_psutil_missing(self, rpyc_process, caplog):
        caplog.set_level(log_levels.MODULE_DEBUG)
        rpyc_process._owner.modules().psutil.Process.side_effect = ModuleNotFoundError

        with pytest.raises(ModuleNotFoundError):
            rpyc_process._get_psutil_process()

        assert "Psutil module on remote machine is missing" in caplog.text
