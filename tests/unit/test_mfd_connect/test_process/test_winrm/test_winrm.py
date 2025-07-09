# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
import logging

import pytest
from winrm import Protocol
from winrm.exceptions import WinRMOperationTimeoutError

from mfd_connect import WinRmConnection
from mfd_connect.exceptions import RemoteProcessInvalidState
from mfd_connect.process.winrm.base import WinRmProcess


class TestWinRmProcess:
    @pytest.fixture
    def connection(self, mocker):
        conn = mocker.create_autospec(WinRmConnection)
        conn._shell_id = "111"
        conn._server = mocker.create_autospec(Protocol)

        return conn

    @pytest.fixture
    def process(self, connection):
        command_id = "command_id"
        process = WinRmProcess(command_id=command_id, connection=connection)
        return process

    def test_init(self, process):
        assert process.command_id == "command_id"
        assert process._stdout is None
        assert process._stderr is None
        assert process._return_code is None

    def test_running_true(self, mocker, process, caplog):
        process._running = True
        process._connection_handle._server._raw_get_command_output = mocker.MagicMock(
            return_value=(b"stdout_msg", b"stderr_msg", 0, False)
        )
        assert process.running

    def test_running_false(self, mocker, process, caplog):
        process._stdout = "stdout_msg"
        process._stderr = "stderr_msg"
        process._return_code = 0
        process._running = False
        process._connection_handle._server._raw_get_command_output = mocker.MagicMock(
            return_value=(b"stdout_msg", b"stderr_msg", 0, True)
        )
        with caplog.at_level(logging.DEBUG):
            assert not process.running

    def test_stop(self, connection, process, caplog):
        connection._server.cleanup_command.side_effect = Exception("cleanup command exception")  # Raise exception
        with pytest.raises(RemoteProcessInvalidState, match="Found problem during stop"):
            process.stop()

    def test_kill(self, mocker, connection, process, caplog):
        process.stop = mocker.Mock()
        process.kill()
        process.stop.assert_called_once_with()

    def test_pull_data_stdout(self, connection, process, caplog):
        connection._server._raw_get_command_output.return_value = (b"stdout_msg", b"", 0, True)
        with caplog.at_level(logging.DEBUG):
            process._pull_data()
            assert process._stdout == "stdout_msg"

    def test_pull_data_stderr(self, connection, process, caplog):
        connection._server._raw_get_command_output.return_value = (b"", b"stderr_msg", 0, True)
        with caplog.at_level(logging.DEBUG):
            process._pull_data()
            assert process._stderr == "stderr_msg"

    def test_pull_data_exception(self, mocker, process, caplog):
        process._connection_handle._server._raw_get_command_output = mocker.MagicMock(
            side_effect=WinRMOperationTimeoutError("Operation timed out")
        )
        assert process.running

    def test_stdout_text(self, mocker, process):
        process._stdout = "Expected stdout text"
        process._running = False
        process._connection_handle._server._raw_get_command_output = mocker.MagicMock(return_value=(b"", b"", 0, True))
        assert process.stdout_text == "Expected stdout text"

    def test_stdout_text_pull_data(self, mocker, process):
        process._connection_handle._server._raw_get_command_output = mocker.MagicMock(
            return_value=(b"stdout_msg", b"", 0, True)
        )
        assert process.stdout_text == "stdout_msg"

    def test_stderr_text(self, mocker, process):
        process._stderr = "Expected stderr text"
        process._running = False
        process._connection_handle._server._raw_get_command_output = mocker.MagicMock(return_value=(b"", b"", 0, True))
        assert process.stderr_text == "Expected stderr text"

    def test_stderr_text_pull_data(self, mocker, process):
        process._connection_handle._server._raw_get_command_output = mocker.MagicMock(
            return_value=(b"", b"stderr_msg", 0, True)
        )
        assert process.stderr_text == "stderr_msg"

    def test_return_code(self, mocker, process):
        process._return_code = 0
        process._connection_handle._server._raw_get_command_output = mocker.MagicMock(
            return_value=(b"stdout_msg", b"stderr_msg", 0, True)
        )
        assert process.return_code == 0

    def test_return_code_pull_data(self, mocker, process):
        process._connection_handle._server._raw_get_command_output = mocker.MagicMock(return_value=(b"", b"", 0, True))
        assert process.return_code == 0

    def test_running(self, mocker, process):
        process._connection_handle._server._raw_get_command_output = mocker.MagicMock(
            return_value=(b"stdout_msg", b"stderr_msg", 0, True)
        )
        process._running = False
        assert not process.running

    def test_running_pull_data(self, mocker, process):
        process._connection_handle._server._raw_get_command_output = mocker.MagicMock(return_value=(b"", b"", 0, True))
        assert not process.running
