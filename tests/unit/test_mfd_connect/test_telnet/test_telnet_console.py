# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
from socket import socket
import telnetlib

import pytest

from mfd_connect.telnet.telnet_console import TelnetConsole


class TestTelnetConsole:
    @pytest.fixture()
    def telnet_console(self, mocker):
        mocker.patch("telnetlib.Telnet", return_value=mocker.create_autospec(telnetlib.Telnet))
        mocker.patch.object(TelnetConsole, "is_connected", return_value=True)
        telnet_console = TelnetConsole("10.10.10.10", 10)
        telnet_console.telnet.sock = mocker.create_autospec(socket)
        mocker.stopall()
        return telnet_console

    def test_is_connected(self, telnet_console):
        assert telnet_console.is_connected() is True

    def test_is_connected_missing_sock(self, telnet_console):
        telnet_console.telnet.sock = None
        assert telnet_console.is_connected() is False

    def test_is_connected_missing_telnet(self, telnet_console):
        telnet_console.telnet = None
        assert telnet_console.is_connected() is False

    def test_write_string(self, telnet_console):
        buffer = "to send"
        buffer_to_check = b"to send\n"
        telnet_console.write(buffer)
        telnet_console.telnet.write.assert_called_once_with(buffer_to_check)

    def test_write_bytes(self, telnet_console):
        buffer = b"to send"
        buffer_to_check = b"to send\r"
        telnet_console.write(buffer, end="\r")
        telnet_console.telnet.write.assert_called_once_with(buffer_to_check)

    def test_flush_buffers(self, telnet_console, mocker):
        timeout = 10.0
        sleep_mock = mocker.patch("time.sleep")
        telnet_console.flush_buffers(timeout=timeout)
        telnet_console.telnet.read_very_eager.assert_called_once()
        sleep_mock.assert_called_once_with(timeout)

    def test_expect(self, telnet_console):
        pattern_list = ["a".encode(), "b".encode()]
        telnet_console.expect(pattern_list)
        telnet_console.telnet.expect.assert_called_once_with(pattern_list, 1)

    def test_expect_with_timeout(self, telnet_console):
        pattern_list = ["a".encode(), "b".encode()]
        telnet_console.expect(pattern_list, 2)
        telnet_console.telnet.expect.assert_called_once_with(pattern_list, 2)
