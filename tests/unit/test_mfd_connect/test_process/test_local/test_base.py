# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
import threading
from io import TextIOWrapper
from subprocess import Popen

import pytest

from mfd_connect import util
from mfd_connect.exceptions import RemoteProcessStreamNotAvailable, RemoteProcessTimeoutExpired
from mfd_connect.process.local import LocalProcess


class TestLocalProcess:
    class_under_test = LocalProcess

    @pytest.fixture
    def local_process(self, mocker):
        local_process = self.class_under_test.__new__(self.class_under_test)
        local_process._process = mocker.create_autospec(
            Popen,
            instance=True,
            stdin=mocker.create_autospec(TextIOWrapper),
            stdout=mocker.create_autospec(TextIOWrapper),
            stderr=mocker.create_autospec(TextIOWrapper),
            pid=mocker.sentinel.pid,
            returncode=mocker.sentinel.returncode,
        )
        local_process._stdout_queue_cache_lock = mocker.create_autospec(threading.Lock(), spec_set=True)
        local_process._stdout_iter_cache_lock = mocker.create_autospec(threading.Lock(), spec_set=True)
        local_process._stderr_queue_cache_lock = mocker.create_autospec(threading.Lock(), spec_set=True)
        local_process._stderr_iter_cache_lock = mocker.create_autospec(threading.Lock(), spec_set=True)
        return local_process

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
        return mocker.patch("mfd_connect.process.local.base.sleep", autospec=True, spec_set=True)

    def test__stdout_queue_not_cached(self, local_process, mocker):
        stdout_stream_mock = mocker.patch.object(
            self.class_under_test, "stdout_stream", new_callable=mocker.PropertyMock
        )
        local_process._get_process_io_queue = mocker.create_autospec(local_process._get_process_io_queue, spec_set=True)
        local_process._cached_stdout_queue = None

        assert local_process._stdout_queue == local_process._get_process_io_queue.return_value
        local_process._get_process_io_queue.assert_called_once_with(stdout_stream_mock.return_value)
        local_process._stdout_queue_cache_lock.__enter__.assert_called()
        local_process._stdout_queue_cache_lock.__exit__.assert_called()

    def test__stdout_queue_cached(self, local_process, mocker):
        local_process._cached_stdout_queue = mocker.sentinel.cached
        local_process._get_process_io_queue = mocker.create_autospec(local_process._get_process_io_queue, spec_set=True)
        assert local_process._stdout_queue == mocker.sentinel.cached
        local_process._get_process_io_queue.assert_not_called()
        local_process._stdout_queue_cache_lock.__enter__.assert_called()
        local_process._stdout_queue_cache_lock.__exit__.assert_called()

    def test__stderr_queue_not_cached(self, local_process, mocker):
        stderr_stream_mock = mocker.patch.object(
            self.class_under_test, "stderr_stream", new_callable=mocker.PropertyMock
        )
        local_process._get_process_io_queue = mocker.create_autospec(local_process._get_process_io_queue, spec_set=True)
        local_process._cached_stderr_queue = None
        assert local_process._stderr_queue == local_process._get_process_io_queue.return_value
        local_process._get_process_io_queue.assert_called_once_with(stderr_stream_mock.return_value)
        local_process._stderr_queue_cache_lock.__enter__.assert_called()
        local_process._stderr_queue_cache_lock.__exit__.assert_called()

    def test__stderr_queue_cached(self, local_process, mocker):
        local_process._cached_stderr_queue = mocker.sentinel.cached
        local_process._get_process_io_queue = mocker.create_autospec(local_process._get_process_io_queue, spec_set=True)
        assert local_process._stderr_queue == mocker.sentinel.cached
        local_process._get_process_io_queue.assert_not_called()
        local_process._stderr_queue_cache_lock.__enter__.assert_called()
        local_process._stderr_queue_cache_lock.__exit__.assert_called()

    def test__iterate_non_blocking_queue(self, local_process, sleep_mock, mocker):
        q = mocker.create_autospec(util.BatchQueue(), spec_set=True)
        q.get_many.side_effect = [[mocker.sentinel.line1, mocker.sentinel.line2], [], [mocker.sentinel.line3, None]]

        assert all(
            [
                expect == actual
                for expect, actual in zip(
                    [mocker.sentinel.line1, mocker.sentinel.line2, mocker.sentinel.line3],
                    local_process._iterate_non_blocking_queue(q),
                )
            ]
        )

        sleep_mock.assert_called_once_with(local_process.POOL_INTERVAL)

    def test_running_when_poll_is_none(self, local_process):
        local_process._process.poll.return_value = None
        assert local_process.running

    def test_runinng_when_poll_is_not_none(self, local_process, mocker):
        local_process._process.poll.return_value = mocker.sentinel.not_none
        assert not local_process.running

    def test_stdin_stream_available(self, local_process):
        assert local_process.stdin_stream == local_process._process.stdin

    def test_stdin_stream_raises_if_not_available(self, local_process):
        local_process._process.stdin = None
        with pytest.raises(RemoteProcessStreamNotAvailable):
            _ = local_process.stdin_stream

    def test_stdout_stream_available(self, local_process):
        assert local_process.stdout_stream, local_process._process.stdout

    def test_kill_no_wait(self, local_process, mocker):
        local_process._start_pipe_drain = mocker.create_autospec(local_process._start_pipe_drain)
        local_process.wait = mocker.create_autospec(local_process.wait)
        local_process.kill(wait=None)
        local_process._process.kill.assert_called_once_with()
        local_process._start_pipe_drain.assert_called_once_with()
        local_process.wait.assert_not_called()

    def test_stdout_stream_raises_if_not_available(self, local_process):
        local_process._process.stdout = None
        with pytest.raises(RemoteProcessStreamNotAvailable):
            _ = local_process.stdout_stream

    def test_stderr_stream_available(self, local_process):
        assert local_process.stderr_stream == local_process._process.stderr

    def test_stderr_stream_raises_if_not_available(self, local_process):
        local_process._process.stderr = None
        with pytest.raises(RemoteProcessStreamNotAvailable):
            _ = local_process.stderr_stream

    def test_get_stdout_iter_not_cached(self, local_process, _stdout_queue_mock, mocker):
        expected_return = [mocker.sentinel.line1, mocker.sentinel.line2]
        local_process._cached_stdout_iter = None
        local_process._iterate_non_blocking_queue = mocker.create_autospec(
            local_process._iterate_non_blocking_queue, spec_set=True
        )
        local_process._iterate_non_blocking_queue.return_value = mocker.MagicMock()
        local_process._iterate_non_blocking_queue.return_value.__iter__.return_value = expected_return

        assert all([expect == actual for expect, actual in zip(expected_return, local_process.get_stdout_iter())])

        local_process._iterate_non_blocking_queue.assert_called_once_with(_stdout_queue_mock.return_value)
        assert local_process._cached_stdout_iter is not None
        local_process._stdout_iter_cache_lock.__enter__.assert_called()
        local_process._stdout_iter_cache_lock.__exit__.assert_called()

    def test_get_stdout_iter_cached(self, local_process, _stdout_queue_mock, mocker):
        expected_return = [mocker.sentinel.line1, mocker.sentinel.line2]
        local_process._cached_stdout_iter = mocker.MagicMock()
        local_process._cached_stdout_iter.__iter__.return_value = expected_return
        local_process._iterate_non_blocking_queue = mocker.create_autospec(
            local_process._iterate_non_blocking_queue, spec_set=True
        )

        assert all([expect == actual for expect, actual in zip(expected_return, local_process.get_stdout_iter())])

        local_process._iterate_non_blocking_queue.assert_not_called()
        local_process._stdout_iter_cache_lock.__enter__.assert_called()
        local_process._stdout_iter_cache_lock.__exit__.assert_called()

    def test_get_stderr_iter_not_cached(self, local_process, _stderr_queue_mock, mocker):
        expected_return = [mocker.sentinel.line1, mocker.sentinel.line2]
        local_process._cached_stderr_iter = None
        local_process._iterate_non_blocking_queue = mocker.create_autospec(
            local_process._iterate_non_blocking_queue, spec_set=True
        )
        local_process._iterate_non_blocking_queue.return_value = mocker.MagicMock()
        local_process._iterate_non_blocking_queue.return_value.__iter__.return_value = expected_return

        assert all([expect == actual for expect, actual in zip(expected_return, local_process.get_stderr_iter())])

        local_process._iterate_non_blocking_queue.assert_called_once_with(_stderr_queue_mock.return_value)
        assert local_process._cached_stderr_iter is not None
        local_process._stderr_iter_cache_lock.__enter__.assert_called()
        local_process._stderr_iter_cache_lock.__exit__.assert_called()

    def test_get_stderr_iter_cached(self, local_process, _stderr_queue_mock, mocker):
        expected_return = [mocker.sentinel.line1, mocker.sentinel.line2]
        local_process._cached_stderr_iter = mocker.MagicMock()
        local_process._cached_stderr_iter.__iter__.return_value = expected_return
        local_process._iterate_non_blocking_queue = mocker.create_autospec(
            local_process._iterate_non_blocking_queue, spec_set=True
        )

        assert all([expect == actual for expect, actual in zip(expected_return, local_process.get_stderr_iter())])

        local_process._iterate_non_blocking_queue.assert_not_called()
        local_process._stderr_iter_cache_lock.__enter__.assert_called()
        local_process._stderr_iter_cache_lock.__exit__.assert_called()

    def test_stdout_text(self, local_process, running_mock, mocker):
        running_mock.return_value = False
        local_process.get_stdout_iter = mocker.create_autospec(local_process.get_stdout_iter)
        local_process.get_stdout_iter.return_value.__iter__.return_value = ["foo", "bar", "baz"]

        assert local_process.stdout_text == "foobarbaz"

    def test_stderr_text(self, local_process, running_mock, mocker):
        running_mock.return_value = False
        local_process.get_stderr_iter = mocker.create_autospec(local_process.get_stderr_iter)
        local_process.get_stderr_iter.return_value.__iter__.return_value = ["foo", "bar", "baz"]

        assert local_process.stderr_text == "foobarbaz"

    def test_return_code(self, local_process, running_mock):
        running_mock.return_value = False
        assert local_process.return_code == local_process._process.returncode

    def test_wait_no_timeout(self, local_process, sleep_mock, running_mock, mocker):
        running_mock.side_effect = [True, False]
        return_code_mock = mocker.patch.object(self.class_under_test, "return_code", new_callable=mocker.PropertyMock)
        return_code_mock.return_value = mocker.sentinel.return_code
        local_process._start_pipe_drain = mocker.create_autospec(local_process._start_pipe_drain)

        assert local_process.wait() == mocker.sentinel.return_code

        sleep_mock.assert_called_once_with(local_process.POOL_INTERVAL)
        local_process._start_pipe_drain.assert_called_once_with()

    def test_wait_timeout_happened(self, local_process, sleep_mock, running_mock, mocker):
        running_mock.return_value = True
        timeout_counter_class_mock = mocker.patch(
            "mfd_connect.process.local.base.TimeoutCounter", autospec=True, spec_set=True
        )
        timeout_counter_class_mock.return_value.__bool__.side_effect = [False, True]
        local_process._start_pipe_drain = mocker.create_autospec(local_process._start_pipe_drain)

        with pytest.raises(RemoteProcessTimeoutExpired):
            local_process.wait(timeout=10)

        timeout_counter_class_mock.assert_called_once_with(timeout=10)
        sleep_mock.assert_called_once_with(local_process.POOL_INTERVAL)
        local_process._start_pipe_drain.assert_called_once_with()

    def test_kill_wait(self, local_process, mocker):
        local_process._start_pipe_drain = mocker.create_autospec(local_process._start_pipe_drain)
        local_process.wait = mocker.create_autospec(local_process.wait)
        local_process.kill(wait=10)
        local_process._process.kill.assert_called_once_with()
        local_process._start_pipe_drain.assert_called_once_with()
        local_process.wait.assert_called_once_with(timeout=10)

    def test_stop(self, local_process, mocker):
        local_process._start_pipe_drain = mocker.create_autospec(local_process._start_pipe_drain)
        local_process.stop()
        local_process._start_pipe_drain.assert_called_once_with()

    def test__start_pipe_drain_no_error(self, local_process, _stdout_queue_mock, _stderr_queue_mock):
        local_process._start_pipe_drain()
        _stdout_queue_mock.assert_called_once()
        _stderr_queue_mock.assert_called_once()

    def test__start_pipe_drain_suppresses_stream_not_available(
        self, local_process, _stdout_queue_mock, _stderr_queue_mock
    ):
        _stdout_queue_mock.side_effect = RemoteProcessStreamNotAvailable
        _stderr_queue_mock.side_effect = RemoteProcessStreamNotAvailable

        local_process._start_pipe_drain()

        _stdout_queue_mock.assert_called_once()
        _stderr_queue_mock.assert_called_once()

    def test__start_pipe_drain_propagates_unexpected_errors(
        self, local_process, _stdout_queue_mock, _stderr_queue_mock
    ):
        _stdout_queue_mock.side_effect = Exception()
        with pytest.raises(Exception):
            local_process._start_pipe_drain()

    def test___init__when_os_type_is_none(self, local_process):
        with pytest.raises(AssertionError):
            local_process.__init__(process=local_process._process)

    def test_pid(self, local_process, mocker):
        check = mocker.sentinel.pid
        assert local_process.pid == check
