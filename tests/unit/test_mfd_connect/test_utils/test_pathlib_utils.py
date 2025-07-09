# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Unit Test Module for Process utils."""

from pathlib import Path

import pytest
from mfd_typing.os_values import OSName

from mfd_connect import (
    SSHConnection,
    RPyCConnection,
)
from mfd_connect.util.pathlib_utils import append_file, _append_file_python, _append_file_system


class TestPathlibUtils:
    @pytest.fixture()
    def ssh(self, mocker):
        conn = mocker.create_autospec(SSHConnection)
        conn.get_os_name = mocker.Mock(return_value=OSName.LINUX)
        return conn

    @pytest.fixture()
    def rpyc(self, mocker):
        conn = mocker.create_autospec(RPyCConnection)
        conn.get_os_name = mocker.Mock(return_value=OSName.LINUX)
        return conn

    @pytest.fixture()
    def path(self, mocker):
        yield mocker.create_autospec(Path)

    def test_append_file_ssh(self, ssh, mocker):
        append_file_mock = mocker.patch("mfd_connect.util.pathlib_utils._append_file_system")
        append_file_python_mock = mocker.patch("mfd_connect.util.pathlib_utils._append_file_python")
        append_file(ssh, "/path/to", "some text")
        append_file_mock.assert_called_once()
        append_file_python_mock.assert_not_called()

    def test_append_file_rpyc(self, rpyc, mocker):
        append_file_mock = mocker.patch("mfd_connect.util.pathlib_utils._append_file_system")
        append_file_python_mock = mocker.patch("mfd_connect.util.pathlib_utils._append_file_python")
        append_file(rpyc, "/path/to", "some text")
        append_file_mock.assert_not_called()
        append_file_python_mock.assert_called_once()

    def test__append_file_system(self, path):
        path.read_text.return_value = "first content\n"
        _append_file_system(path, "some content")
        path.touch.assert_called_once()
        path.write_text.assert_called_once_with("first contentsome content")

    def test__append_file_python(self, path):
        _append_file_python(path, "some content")
        path.open.return_value.__enter__.assert_called_once()
        path.open.return_value.__enter__.return_value.write.assert_called_once_with("some content")
