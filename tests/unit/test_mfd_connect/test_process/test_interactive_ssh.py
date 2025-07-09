# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
import pytest

from mfd_connect.exceptions import RemoteProcessTimeoutExpired, SSHRemoteProcessEndException, RemoteProcessInvalidState
from mfd_connect.interactive_ssh import InteractiveSSHConnection
from mfd_connect.process.interactive_ssh.base import InteractiveSSHProcess


class TestInteractiveSSHProcess:
    @pytest.fixture
    def ssh_process(self, mocker):
        connection = mocker.create_autospec(InteractiveSSHConnection)
        connection.prompt = "switch>"
        ssh_process = InteractiveSSHProcess(stdout="output", connection=connection, command="ls")
        ssh_process._command = "ls"
        ssh_process._stdout = "output"
        ssh_process._interactive_connection = connection
        ssh_process._running = None
        yield ssh_process

    def test_get_stdout_iter_returns_correct_iterator(self, ssh_process, mocker):
        ssh_process._stdout = "line1\nline2\nline3"
        ssh_process._running = False
        ssh_process._read_channel = mocker.create_autospec(ssh_process._read_channel)
        result = ssh_process.get_stdout_iter()
        assert list(result) == ["line1", "line2", "line3"]

    def test_stdin_stream_raises_not_implemented_error(self, ssh_process):
        with pytest.raises(NotImplementedError):
            _ = ssh_process.stdin_stream

    def test_stdout_stream_raises_not_implemented_error(self, ssh_process):
        with pytest.raises(NotImplementedError):
            _ = ssh_process.stdout_stream

    def test_stderr_stream_raises_not_implemented_error(self, ssh_process):
        with pytest.raises(NotImplementedError):
            _ = ssh_process.stderr_stream

    def test_stderr_text_raises_not_implemented_error(self, ssh_process):
        with pytest.raises(NotImplementedError):
            _ = ssh_process.stderr_text

    def test_get_stderr_iter_raises_not_implemented_error(self, ssh_process):
        with pytest.raises(NotImplementedError):
            _ = ssh_process.get_stderr_iter()

    def test_return_code_calls_get_return_code(self, ssh_process, mocker):
        mocker.patch.object(ssh_process._interactive_connection, "_get_return_code", return_value=0)
        assert ssh_process.return_code == 0
        ssh_process._interactive_connection._get_return_code.assert_called_once_with(ssh_process._command)

    def test_init_sets_correct_attributes(self, ssh_process, mocker):
        connection = mocker.Mock()
        ssh_process = InteractiveSSHProcess(stdout="output", connection=connection, command="ls")
        assert ssh_process._command == "ls"
        assert ssh_process._stdout == "output"
        assert ssh_process._interactive_connection == connection

    def test_stdout_text_reads_channel_and_returns_stdout(self, ssh_process, mocker):
        ssh_process._running = False
        mocker.patch.object(ssh_process, "_read_channel", return_value="output")
        assert ssh_process.stdout_text == "output"
        ssh_process._read_channel.assert_called_once()

    def test_running_checks_if_process_is_running(self, ssh_process, mocker):
        ssh_process._read_channel = mocker.create_autospec(ssh_process._read_channel, return_value="output\nswitch>")
        assert ssh_process.running is False
        ssh_process._read_channel.assert_called_once()

    def test_running_is_running(self, ssh_process, mocker):
        mocker.patch.object(ssh_process, "_read_channel", return_value="output")
        assert ssh_process.running is True
        ssh_process._read_channel.assert_called_once()

    def test_read_channel_reads_channel_and_updates_stdout(self, ssh_process, mocker):
        mocker.patch.object(ssh_process._interactive_connection, "read_channel", return_value="output")
        mocker.patch.object(ssh_process._interactive_connection, "cleanup_stdout", return_value="clean_output")
        assert ssh_process._read_channel() == "output"
        assert ssh_process._stdout == "outputclean_output"

    def test_wait_waits_for_process_to_finish(self, ssh_process, mocker):
        ssh_process._running = False
        ssh_process._interactive_connection._get_return_code.return_value = 0
        assert ssh_process.wait() == 0

    def test_wait_raises_timeout_expired_if_process_does_not_finish(self, ssh_process, mocker):
        # mocker.patch.object(ssh_process, "running", return_value=True)
        # mocker.patch("mfd_connect.process.interactive_ssh.base.sleep")
        mocker.patch("mfd_connect.process.interactive_ssh.base.TimeoutCounter", return_value=True)
        with pytest.raises(RemoteProcessTimeoutExpired):
            ssh_process.wait()

    def test_stop_stops_running_process(self, ssh_process, mocker):
        type(ssh_process).running = mocker.PropertyMock(return_value=True)
        mocker.patch("mfd_connect.process.interactive_ssh.base.sleep")
        mocker.patch.object(ssh_process._interactive_connection, "write_to_channel")
        mocker.patch.object(ssh_process, "_read_channel", return_value="switch>")
        ssh_process.stop()

    def test_stop_cannot_stop(self, ssh_process, mocker):
        type(ssh_process).running = mocker.PropertyMock(return_value=True)
        mocker.patch("mfd_connect.process.interactive_ssh.base.sleep")
        mocker.patch.object(ssh_process._interactive_connection, "write_to_channel")
        mocker.patch.object(ssh_process, "_read_channel", return_value="prompt")
        with pytest.raises(SSHRemoteProcessEndException):
            ssh_process.stop()
        ssh_process._interactive_connection.write_to_channel.assert_called_once_with("\x03", False)

    def test_stop_already_stopped(self, ssh_process, mocker):
        type(ssh_process).running = mocker.PropertyMock(return_value=False)
        with pytest.raises(RemoteProcessInvalidState):
            ssh_process.stop()

    def test_kill_already_stopped(self, ssh_process, mocker):
        type(ssh_process).running = mocker.PropertyMock(return_value=False)
        with pytest.raises(RemoteProcessInvalidState):
            ssh_process.kill()

    def test_kill_running_process(self, ssh_process, mocker):
        type(ssh_process).running = mocker.PropertyMock(return_value=True)
        mocker.patch("mfd_connect.process.interactive_ssh.base.sleep")
        mocker.patch.object(ssh_process._interactive_connection, "write_to_channel")
        mocker.patch.object(ssh_process, "_read_channel", return_value="switch>")
        ssh_process.kill()
        ssh_process._interactive_connection.write_to_channel.assert_called_with("\x03", False)
