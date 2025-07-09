# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
import threading
from collections import namedtuple
from signal import SIGTERM
from textwrap import dedent

import pytest
from mfd_typing import OSName
from paramiko import ChannelStdinFile, ChannelFile, ChannelStderrFile

from mfd_connect import SSHConnection
from mfd_connect.base import ConnectionCompletedProcess
from mfd_connect.exceptions import SSHRemoteProcessEndException, RemoteProcessInvalidState
from mfd_connect.process.ssh.posix import PosixSSHProcess


class TestPosixSSHProcess:
    class_under_test = PosixSSHProcess
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
        ssh_process._pid = 123
        mocker.patch("mfd_connect.process.ssh.posix.PosixSSHProcess.running", return_value=True)
        return ssh_process

    def test_stop(self, ssh_process, mocker):
        ssh_process._start_pipe_drain = mocker.create_autospec(ssh_process._start_pipe_drain)

        ssh_process._connection_handle.execute_command.return_value = ConnectionCompletedProcess(
            "kill -2", return_code=0
        )
        ssh_process.stop()
        ssh_process._connection_handle.execute_command.assert_called_once_with(
            command="kill -2 123", expected_return_codes=None
        )

    def test_stop_failure(self, ssh_process, mocker):
        ssh_process._start_pipe_drain = mocker.create_autospec(ssh_process._start_pipe_drain)
        ssh_process._connection_handle.execute_command.return_value = ConnectionCompletedProcess(
            "kill -2", return_code=123
        )
        with pytest.raises(SSHRemoteProcessEndException, match="Cannot stop process pid:123"):
            ssh_process.stop()

    def test_stop_already_finished_process_exception(self, ssh_process):
        ssh_process.running = False

        with pytest.raises(RemoteProcessInvalidState, match="Process has already finished"):
            ssh_process.stop()

    def test_kill_no_wait(self, ssh_process, mocker):
        ssh_process._start_pipe_drain = mocker.create_autospec(ssh_process._start_pipe_drain)
        ssh_process.wait = mocker.create_autospec(ssh_process.wait)
        ssh_process._kill = mocker.create_autospec(ssh_process._kill)
        ssh_process.kill(wait=None)
        ssh_process._kill.assert_called_once_with(123, with_signal=SIGTERM)
        ssh_process._start_pipe_drain.assert_called_once_with()
        ssh_process.wait.assert_not_called()

    def test_kill_wait(self, ssh_process, mocker):
        ssh_process._start_pipe_drain = mocker.create_autospec(ssh_process._start_pipe_drain)
        ssh_process.wait = mocker.create_autospec(ssh_process.wait)
        ssh_process._kill = mocker.create_autospec(ssh_process._kill)
        ssh_process.kill(wait=10)
        ssh_process._kill.assert_called_once_with(123, with_signal=SIGTERM)
        ssh_process._start_pipe_drain.assert_called_once_with()
        ssh_process.wait.assert_called_once_with(timeout=10)

    def test__kill(self, ssh_process):
        ssh_process._connection_handle.execute_command.return_value = ConnectionCompletedProcess("kill", return_code=0)
        ssh_process._kill(pid=1, with_signal=SIGTERM)
        ssh_process._connection_handle.execute_command.assert_called_once_with("kill -15 1", expected_return_codes=None)

    def test__kill_failure(self, ssh_process):
        ssh_process._connection_handle.execute_command.return_value = ConnectionCompletedProcess("kill", return_code=1)
        with pytest.raises(SSHRemoteProcessEndException, match="Cannot kill process pid:1"):
            ssh_process._kill(pid=1, with_signal=SIGTERM)

    def test_kill_already_finished_process_exception(self, ssh_process):
        ssh_process.running = False

        with pytest.raises(RemoteProcessInvalidState, match="Process has already finished"):
            ssh_process.kill()

    def test__find_pids_single_found(self, ssh_process, mocker):
        parent_pid_command = "ps aux | grep 'true 0.123123123' | grep -v grep | awk '{print $2}'"
        pid_command = "pgrep -P 1232"
        ssh_process._connection_handle.execute_command.side_effect = [
            ConnectionCompletedProcess(parent_pid_command, return_code=0, stdout="1232\n"),
            ConnectionCompletedProcess(pid_command, return_code=0, stdout="1231\n"),
        ]
        assert ssh_process._find_pids(ssh_process._connection_handle, "0.123123123") == [1231]
        calls = [mocker.call(command=parent_pid_command), mocker.call(command=pid_command, expected_return_codes=None)]
        assert ssh_process._connection_handle.execute_command.mock_calls == calls

    def test__find_pids_multiple_found(self, ssh_process, mocker):
        parent_pid_command = "ps aux | grep 'true 0.123123123' | grep -v grep | awk '{print $2}'"
        pid_command = "pgrep -P 1232"
        pids_found = [1233, 1234, 1235]
        pgrep_output = dedent(
            """\
            1233
            1234
            1235
            """
        )
        ssh_process._connection_handle.execute_command.side_effect = [
            ConnectionCompletedProcess(parent_pid_command, return_code=0, stdout="1232\n"),
            ConnectionCompletedProcess(pid_command, return_code=0, stdout=pgrep_output),
        ]
        assert ssh_process._find_pids(ssh_process._connection_handle, "0.123123123") == pids_found
        calls = [mocker.call(command=parent_pid_command), mocker.call(command=pid_command, expected_return_codes=None)]
        assert ssh_process._connection_handle.execute_command.mock_calls == calls

    def test__find_parent_pid_not_found(self, ssh_process):
        ssh_process._connection_handle.execute_command.return_value = ConnectionCompletedProcess(
            "", return_code=0, stdout=""
        )
        with pytest.raises(RemoteProcessInvalidState, match="Process is finished, cannot find PID"):
            ssh_process._find_pids(ssh_process._connection_handle, "0.123123123")

    def test__find_pids_not_found(self, ssh_process):
        ssh_process._connection_handle.execute_command.side_effect = [
            ConnectionCompletedProcess("", return_code=0, stdout=""),
            ConnectionCompletedProcess("", return_code=1, stdout=""),
        ]
        with pytest.raises(RemoteProcessInvalidState, match="Process is finished, cannot find PID"):
            ssh_process._find_pids(ssh_process._connection_handle, "0.123123123")

    def test_pid(self, ssh_process, mocker):
        ssh_process._pid = None
        ssh_process._find_pids = mocker.create_autospec(ssh_process._find_pids, return_value=[1])
        _ = ssh_process.pid
        ssh_process._find_pids.assert_called_once()

    def test_pid_exists(self, ssh_process, mocker):
        ssh_process._find_pids = mocker.create_autospec(ssh_process._find_pids, return_value=[1])
        _ = ssh_process.pid
        ssh_process._find_pids.assert_not_called()
