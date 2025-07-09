# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
import threading
from collections import namedtuple

import pytest
from mfd_typing import OSName
from paramiko import ChannelStdinFile, ChannelFile, ChannelStderrFile
from textwrap import dedent

from mfd_connect.base import ConnectionCompletedProcess
from mfd_connect.exceptions import SSHRemoteProcessEndException, RemoteProcessInvalidState
from mfd_connect.process.ssh.windows import WindowsSSHProcess

from mfd_connect import SSHConnection


class TestWindowsSSHProcess:
    class_under_test = WindowsSSHProcess
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
        ssh_process._os_name = OSName.WINDOWS
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
        mocker.patch("mfd_connect.process.ssh.windows.WindowsSSHProcess.running", return_value=True)
        return ssh_process

    def test_stop(self, ssh_process):
        with pytest.raises(NotImplementedError):
            ssh_process.stop()

    def test_kill_no_wait(self, ssh_process, mocker):
        ssh_process._start_pipe_drain = mocker.create_autospec(ssh_process._start_pipe_drain)
        ssh_process.wait = mocker.create_autospec(ssh_process.wait)
        ssh_process._kill = mocker.create_autospec(ssh_process._kill)
        ssh_process.kill(wait=None)
        ssh_process._kill.assert_called_once_with(123)
        ssh_process._start_pipe_drain.assert_called_once_with()
        ssh_process.wait.assert_not_called()

    def test_kill_wait(self, ssh_process, mocker):
        ssh_process._start_pipe_drain = mocker.create_autospec(ssh_process._start_pipe_drain)
        ssh_process.wait = mocker.create_autospec(ssh_process.wait)
        ssh_process._kill = mocker.create_autospec(ssh_process._kill)
        ssh_process.kill(wait=10)
        ssh_process._kill.assert_called_once_with(123)
        ssh_process._start_pipe_drain.assert_called_once_with()
        ssh_process.wait.assert_called_once_with(timeout=10)

    def test__kill(self, ssh_process):
        ssh_process._connection_handle.execute_command.return_value = ConnectionCompletedProcess("kill", return_code=0)
        ssh_process._kill(pid=1)
        ssh_process._connection_handle.execute_command.assert_called_once_with(
            "taskkill /F /PID 1", expected_return_codes=None
        )

    def test__kill_failure(self, ssh_process):
        ssh_process._connection_handle.execute_command.return_value = ConnectionCompletedProcess("kill", return_code=1)
        with pytest.raises(SSHRemoteProcessEndException, match="Cannot kill process pid:1"):
            ssh_process._kill(pid=1)

    def test_kill_already_finished_process_exception(self, ssh_process):
        ssh_process.running = False

        with pytest.raises(RemoteProcessInvalidState, match="Process has already finished"):
            ssh_process.kill()

    def test__find_pids_single_found(self, ssh_process):
        command = (
            'powershell -command "Get-CimInstance Win32_Process '
            "| Where-Object -Match -Property CommandLine -Value .*\/c\s\Dtitle\s0.123123123.* "  # noqa: W605
            '| Select-Object  -ExpandProperty ProcessId"'
        )
        ssh_process._connection_handle.execute_command.return_value = ConnectionCompletedProcess(
            command, return_code=0, stdout="1231"
        )
        assert ssh_process._find_pids(ssh_process._connection_handle, "0.123123123") == [1231]
        ssh_process._connection_handle.execute_command.assert_called_once_with(command=command)

    def test__find_pids_multiple_found(self, ssh_process):
        command = (
            'powershell -command "Get-CimInstance Win32_Process '
            "| Where-Object -Match -Property CommandLine -Value .*\/c\s\Dtitle\s0.123123123.* "  # noqa: W605
            '| Select-Object  -ExpandProperty ProcessId"'
        )
        pids_found = [1231, 1232, 1233]
        get_ciminstance_output = dedent(
            """\
            1231
            1232
            1233
            """
        )
        ssh_process._connection_handle.execute_command.return_value = ConnectionCompletedProcess(
            command, return_code=0, stdout=get_ciminstance_output
        )
        assert ssh_process._find_pids(ssh_process._connection_handle, "0.123123123") == pids_found
        ssh_process._connection_handle.execute_command.assert_called_once_with(command=command)

    def test__find_pids_not_found(self, ssh_process):
        command = (
            'powershell -command "Get-CimInstance Win32_Process '
            "| Where-Object -Match -Property CommandLine -Value .*\/c\s\Dtitle\s0.123123123.* "  # noqa: W605
            '| Select-Object  -ExpandProperty ProcessId"'
        )
        ssh_process._connection_handle.execute_command.return_value = ConnectionCompletedProcess(
            command, return_code=0, stdout=""
        )
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
