# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
import threading
from collections import namedtuple

import pytest
from mfd_typing import OSName
from paramiko import ChannelFile, ChannelStdinFile, ChannelStderrFile, Channel

from mfd_connect import SSHConnection
from mfd_connect.exceptions import (
    RemoteProcessStreamNotAvailable,
    RemoteProcessInvalidState,
    RemoteProcessTimeoutExpired,
    SSHPIDException,
)
from mfd_connect.process.ssh.base import SSHProcess
from mfd_connect.util import BatchQueue


class TestBaseSSHProcess:
    class_under_test = SSHProcess
    connection_handle = SSHConnection
    Process = namedtuple("SSHProcess", ["stdin", "stdout", "stderr"])

    @pytest.fixture
    def ssh_process(self, mocker):
        if hasattr(self.class_under_test, "__abstractmethods__"):
            # Remove abstract methods, if any so the class can be instantiated
            self.class_under_test.__abstractmethods__ = []
        ssh_process = self.class_under_test.__new__(self.class_under_test)
        ssh_connection_handle = mocker.create_autospec(self.connection_handle, spec_set=True)
        ssh_process._connection_handle = ssh_connection_handle
        ssh_process._os_name = OSName.LINUX
        ssh_process._unique_name = "0.123213123"
        ssh_process._process = mocker.create_autospec(
            self.Process,
            stdin=mocker.create_autospec(ChannelStdinFile),
            stdout=mocker.create_autospec(ChannelFile),
            stderr=mocker.create_autospec(ChannelStderrFile),
        )
        ssh_process._stdout_queue_cache_lock = mocker.create_autospec(threading.Lock(), spec_set=True)
        ssh_process._stdout_iter_cache_lock = mocker.create_autospec(threading.Lock(), spec_set=True)
        ssh_process._stderr_queue_cache_lock = mocker.create_autospec(threading.Lock(), spec_set=True)
        ssh_process._stderr_iter_cache_lock = mocker.create_autospec(threading.Lock(), spec_set=True)
        ssh_process._pid = 0
        return ssh_process

    @pytest.fixture
    def _stdout_queue_mock(self, mocker):
        return mocker.patch.object(self.class_under_test, "_stdout_queue", new_callable=mocker.PropertyMock)

    @pytest.fixture
    def _stderr_queue_mock(self, mocker):
        return mocker.patch.object(self.class_under_test, "_stderr_queue", new_callable=mocker.PropertyMock)

    @pytest.fixture
    def sleep_mock(self, mocker):
        return mocker.patch("mfd_connect.process.ssh.base.sleep", autospec=True, spec_set=True)

    @pytest.fixture
    def running_mock(self, mocker):
        return mocker.patch.object(self.class_under_test, "running", new_callable=mocker.PropertyMock)

    def test_stdin_stream_available(self, ssh_process):
        assert ssh_process.stdin_stream == ssh_process._process.stdin

    def test_stdin_stream_raises_if_not_available(self, ssh_process):
        ssh_process._process.stdin = None
        with pytest.raises(RemoteProcessStreamNotAvailable):
            _ = ssh_process.stdin_stream

    def test_stdout_stream_available(self, ssh_process):
        assert ssh_process.stdout_stream, ssh_process._process.stdout

    def test_stdout_stream_raises_if_not_available(self, ssh_process):
        ssh_process._process.stdout = None
        with pytest.raises(RemoteProcessStreamNotAvailable):
            _ = ssh_process.stdout_stream

    def test_stderr_stream_available(self, ssh_process):
        assert ssh_process.stderr_stream == ssh_process._process.stderr

    def test_stderr_stream_raises_if_not_available(self, ssh_process):
        ssh_process._process.stderr = None
        with pytest.raises(RemoteProcessStreamNotAvailable):
            _ = ssh_process.stderr_stream

    def test__iterate_non_blocking_queue(self, ssh_process, sleep_mock, mocker):
        q = mocker.create_autospec(BatchQueue(), spec_set=True)
        q.get_many.side_effect = [[mocker.sentinel.line1, mocker.sentinel.line2], [], [mocker.sentinel.line3, None]]

        assert all(
            [
                expect == actual
                for expect, actual in zip(
                    [mocker.sentinel.line1, mocker.sentinel.line2, mocker.sentinel.line3],
                    ssh_process._iterate_non_blocking_queue(q),
                )
            ]
        )

    def test__stdout_queue_cached(self, ssh_process, mocker):
        ssh_process._cached_stdout_queue = mocker.sentinel.cached
        ssh_process._cached_get_process_io_queue = mocker.sentinel.cached
        ssh_process._get_process_io_queue = mocker.create_autospec(ssh_process._get_process_io_queue, spec_set=True)
        assert ssh_process._stdout_queue == mocker.sentinel.cached

        ssh_process._stdout_queue_cache_lock.__enter__.assert_called()
        ssh_process._stdout_queue_cache_lock.__exit__.assert_called()

    def test__stderr_queue_not_cached(self, ssh_process, mocker):
        stderr_stream_mock = mocker.patch.object(
            self.class_under_test, "stderr_stream", new_callable=mocker.PropertyMock
        )
        ssh_process._get_process_io_queue = mocker.create_autospec(ssh_process._get_process_io_queue, spec_set=True)
        ssh_process._cached_get_process_io_queue = None
        ssh_process._cached_stderr_queue = None
        assert ssh_process._stderr_queue == ssh_process._get_process_io_queue.return_value
        ssh_process._get_process_io_queue.assert_called_once_with(stderr_stream_mock.return_value)
        ssh_process._stderr_queue_cache_lock.__enter__.assert_called()
        ssh_process._stderr_queue_cache_lock.__exit__.assert_called()

    def test__stderr_queue_cached(self, ssh_process, mocker):
        ssh_process._cached_stderr_queue = mocker.sentinel.cached
        ssh_process._remote_get_process_io_queue_cache_lock = mocker.sentinel.cached
        ssh_process._get_process_io_queue = mocker.create_autospec(ssh_process._get_process_io_queue, spec_set=True)
        assert ssh_process._stderr_queue == mocker.sentinel.cached
        ssh_process._stderr_queue_cache_lock.__enter__.assert_called()
        ssh_process._stderr_queue_cache_lock.__exit__.assert_called()

    def test_get_stdout_iter_not_cached(self, ssh_process, _stdout_queue_mock, mocker):
        expected_return = [mocker.sentinel.line1, mocker.sentinel.line2]
        ssh_process._cached_stdout_iter = None
        ssh_process._iterate_non_blocking_queue = mocker.create_autospec(
            ssh_process._iterate_non_blocking_queue, spec_set=True
        )
        ssh_process._iterate_non_blocking_queue.return_value = mocker.MagicMock()
        ssh_process._iterate_non_blocking_queue.return_value.__iter__.return_value = expected_return

        assert all([expect == actual for expect, actual in zip(expected_return, ssh_process.get_stdout_iter())])

        ssh_process._iterate_non_blocking_queue.assert_called_once_with(_stdout_queue_mock.return_value)
        assert ssh_process._cached_stdout_iter is not None
        ssh_process._stdout_iter_cache_lock.__enter__.assert_called()
        ssh_process._stdout_iter_cache_lock.__exit__.assert_called()

    def test_get_stdout_iter_cached(self, ssh_process, _stdout_queue_mock, mocker):
        expected_return = [mocker.sentinel.line1, mocker.sentinel.line2]
        ssh_process._cached_stdout_iter = mocker.MagicMock()
        ssh_process._cached_stdout_iter.__iter__.return_value = expected_return
        ssh_process._iterate_non_blocking_queue = mocker.create_autospec(
            ssh_process._iterate_non_blocking_queue, spec_set=True
        )

        assert all([expect == actual for expect, actual in zip(expected_return, ssh_process.get_stdout_iter())])

        ssh_process._iterate_non_blocking_queue.assert_not_called()
        ssh_process._stdout_iter_cache_lock.__enter__.assert_called()
        ssh_process._stdout_iter_cache_lock.__exit__.assert_called()

    def test_get_stderr_iter_not_cached(self, ssh_process, _stderr_queue_mock, mocker):
        expected_return = [mocker.sentinel.line1, mocker.sentinel.line2]
        ssh_process._cached_stderr_iter = None
        ssh_process._iterate_non_blocking_queue = mocker.create_autospec(
            ssh_process._iterate_non_blocking_queue, spec_set=True
        )
        ssh_process._iterate_non_blocking_queue.return_value = mocker.MagicMock()
        ssh_process._iterate_non_blocking_queue.return_value.__iter__.return_value = expected_return

        assert all([expect == actual for expect, actual in zip(expected_return, ssh_process.get_stderr_iter())])

        ssh_process._iterate_non_blocking_queue.assert_called_once_with(_stderr_queue_mock.return_value)
        assert ssh_process._cached_stderr_iter is not None
        ssh_process._stderr_iter_cache_lock.__enter__.assert_called()
        ssh_process._stderr_iter_cache_lock.__exit__.assert_called()

    def test_get_stderr_iter_cached(self, ssh_process, _stderr_queue_mock, mocker):
        expected_return = [mocker.sentinel.line1, mocker.sentinel.line2]
        ssh_process._cached_stderr_iter = mocker.MagicMock()
        ssh_process._cached_stderr_iter.__iter__.return_value = expected_return
        ssh_process._iterate_non_blocking_queue = mocker.create_autospec(
            ssh_process._iterate_non_blocking_queue, spec_set=True
        )

        assert all([expect == actual for expect, actual in zip(expected_return, ssh_process.get_stderr_iter())])

        ssh_process._iterate_non_blocking_queue.assert_not_called()
        ssh_process._stderr_iter_cache_lock.__enter__.assert_called()
        ssh_process._stderr_iter_cache_lock.__exit__.assert_called()

    def test_stdout_text(self, ssh_process, running_mock, mocker):
        running_mock.return_value = False
        ssh_process.get_stdout_iter = mocker.create_autospec(ssh_process.get_stdout_iter)
        ssh_process.get_stdout_iter.return_value.__iter__.return_value = ["foo", "bar", "baz"]

        assert ssh_process.stdout_text == "foobarbaz"

    def test_stderr_text(self, ssh_process, running_mock, mocker):
        running_mock.return_value = False
        ssh_process.get_stderr_iter = mocker.create_autospec(ssh_process.get_stderr_iter)
        ssh_process.get_stderr_iter.return_value.__iter__.return_value = ["foo", "bar", "baz"]

        assert ssh_process.stderr_text == "foobarbaz"

    def test__start_pipe_drain_no_error(self, ssh_process, _stdout_queue_mock, _stderr_queue_mock):
        ssh_process._start_pipe_drain()
        _stdout_queue_mock.assert_called_once()
        _stderr_queue_mock.assert_called_once()

    def test__start_pipe_drain_suppresses_stream_not_available(
        self, ssh_process, _stdout_queue_mock, _stderr_queue_mock
    ):
        _stdout_queue_mock.side_effect = RemoteProcessStreamNotAvailable
        _stderr_queue_mock.side_effect = RemoteProcessStreamNotAvailable

        ssh_process._start_pipe_drain()

        _stdout_queue_mock.assert_called_once()
        _stderr_queue_mock.assert_called_once()

    def test__start_pipe_drain_propagates_unexpected_errors(self, ssh_process, _stdout_queue_mock, _stderr_queue_mock):
        _stdout_queue_mock.side_effect = Exception()
        with pytest.raises(Exception):
            ssh_process._start_pipe_drain()

    def test_running(self, ssh_process, mocker):
        ssh_process._find_pids = mocker.Mock(return_value=[0, 1, 2])
        assert ssh_process.running is True
        ssh_process._find_pids = mocker.Mock(return_value=[3, 4, 5])
        assert ssh_process.running is False  # pid == 0

    def test_running_os_check(self, ssh_process, mocker):
        ssh_process._find_pids = mocker.create_autospec(ssh_process._find_pids, side_effect=RemoteProcessInvalidState)
        assert ssh_process.running is False

    def test_running_is_running(self, ssh_process, mocker):
        ssh_process._find_pids = mocker.create_autospec(ssh_process._find_pids, return_value=[1])
        ssh_process._pid = 1
        assert ssh_process.running is True

    def test_wait_no_timeout(self, ssh_process, sleep_mock, running_mock, mocker):
        ssh_process._channel = mocker.create_autospec(Channel)
        ssh_process._channel.recv_exit_status.return_value = False
        running_mock.side_effect = [True, False]
        return_code_mock = mocker.patch.object(self.class_under_test, "return_code", new_callable=mocker.PropertyMock)
        return_code_mock.return_value = mocker.sentinel.return_code
        ssh_process._start_pipe_drain = mocker.create_autospec(ssh_process._start_pipe_drain)

        assert ssh_process.wait() == mocker.sentinel.return_code

        sleep_mock.assert_called_once_with(ssh_process.POOL_INTERVAL)
        ssh_process._start_pipe_drain.assert_called_once_with()

    def test_wait_timeout_happened(self, ssh_process, sleep_mock, running_mock, mocker):
        ssh_process._channel = mocker.create_autospec(Channel)
        ssh_process._channel.recv_exit_status.return_value = False

        running_mock.return_value = True
        timeout_counter_class_mock = mocker.patch(
            "mfd_connect.process.ssh.base.TimeoutCounter", autospec=True, spec_set=True
        )
        timeout_counter_class_mock.return_value.__bool__.side_effect = [False, True]
        ssh_process._start_pipe_drain = mocker.create_autospec(ssh_process._start_pipe_drain)

        with pytest.raises(RemoteProcessTimeoutExpired):
            ssh_process.wait(timeout=10)

        timeout_counter_class_mock.assert_called_once_with(timeout=10)
        sleep_mock.assert_called_once_with(ssh_process.POOL_INTERVAL)
        ssh_process._start_pipe_drain.assert_called_once_with()

    def test_pid_more_than_one_found(self, ssh_process, mocker):
        ssh_process._pid = None
        ssh_process._find_pids = mocker.create_autospec(ssh_process._find_pids, return_value=[1, 2, 3])
        with pytest.raises(SSHPIDException):
            ssh_process.pid

    def test_log_path_is_set_in_init(self, mocker):
        # Remove abstract methods to instantiate
        if hasattr(self.class_under_test, "__abstractmethods__"):
            self.class_under_test.__abstractmethods__ = set()
        dummy_log_path = mocker.sentinel.log_path
        ssh_process = self.class_under_test.__new__(self.class_under_test)
        ssh_process._os_name = {OSName.LINUX}
        ssh_process._unique_name = "unique"
        ssh_process._pid = 123
        ssh_process._connection_handle = mocker.Mock()
        ssh_process._process = self.Process(stdin=None, stdout=None, stderr=None)
        # Call __init__ with log_path
        self.class_under_test.__init__(
            ssh_process,
            stdin=None,
            stdout=None,
            stderr=None,
            unique_name="unique",
            pid=123,
            connection=ssh_process._connection_handle,
            channel=None,
            log_path=dummy_log_path,
        )
        assert ssh_process.log_path == dummy_log_path
