# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
from pathlib import PurePosixPath, PureWindowsPath

import pytest

from mfd_connect import Connection
from mfd_connect.api.download_utils import (
    download_file_windows,
    _download_file_esxi,
    download_file_esxi,
    _prepare_headers_powershell,
    _prepare_headers_wget,
    _prepare_headers_curl,
    download_file_unix_via_controller,
    _prepare_headers_with_env_powershell,
    download_file_unix,
)
from mfd_connect.base import ConnectionCompletedProcess


class TestDownloader:
    @pytest.fixture
    def connection(self, mocker):
        yield mocker.create_autospec(Connection)

    def test_download_file_unix(self, connection):
        download_file_unix(
            connection,
            "http://arti/a.zip",
            destination_file=PurePosixPath("/home/mydir/a.zip"),
            options="-u 3141",
        )
        connection.execute_command.assert_called_once_with(
            "curl -u 3141 --create-dirs -o /home/mydir/a.zip http://arti/a.zip",
            expected_return_codes=None,
            stderr_to_stdout=True,
            shell=True,
        )

    def test_download_file_unix_with_env(self, connection):
        download_file_unix(
            connection,
            "http://arti/a.zip",
            destination_file=PurePosixPath("/home/mydir/a.zip"),
            options="-u 3141",
        )
        connection.execute_command.assert_called_once_with(
            "curl -u 3141 --create-dirs -o /home/mydir/a.zip http://arti/a.zip",
            expected_return_codes=None,
            stderr_to_stdout=True,
            shell=True,
        )

    def test_download_file_windows(self, connection, mocker):
        mocker.patch("mfd_connect.api.download_utils.open")
        download_file_windows(
            connection,
            "http://arti/a.zip",
            destination_file=PureWindowsPath("c:\\mydir\\a.zip"),
            auth="-u 3141",
        )
        connection.execute_powershell.assert_called_once_with(
            "Invoke-WebRequest 'http://arti/a.zip' -UseBasicParsing -OutFile 'c:\\mydir\\a.zip' -u 3141",
            expected_return_codes=None,
            stderr_to_stdout=True,
        )

    def test__download_file_esxi(self, connection):
        _download_file_esxi(
            connection,
            "http://arti/a.zip",
            destination_file=PurePosixPath("/home/mydir/a.zip"),
            options="-u 3141",
        )
        connection.execute_command.assert_called_once_with(
            "wget http://arti/a.zip -O /home/mydir/a.zip -u 3141 --no-check-certificate",
            expected_return_codes=None,
            stderr_to_stdout=True,
        )

    def test_download_file_esxi_normally(self, connection, mocker):
        connection.execute_command.return_value = ConnectionCompletedProcess(
            args="", stdout="", stderr="", return_code=0
        )
        mock = mocker.patch("mfd_connect.api.download_utils._download_file_esxi")
        mock_controller = mocker.patch("mfd_connect.api.download_utils.download_file_unix_via_controller")
        download_file_esxi(
            connection,
            "http://arti/a.zip",
            PurePosixPath("/home/mydir/a.zip"),
            "-u 3141",
        )
        mock.assert_called_once_with(
            connection,
            "http://arti/a.zip",
            PurePosixPath("/home/mydir/a.zip"),
            "-u 3141",
        )
        mock_controller.assert_not_called()

    def test_download_file_esxi_no_options(self, connection, mocker):
        connection.execute_command.return_value = ConnectionCompletedProcess(
            args="", stdout="", stderr="", return_code=0
        )
        mock = mocker.patch("mfd_connect.api.download_utils._download_file_esxi")
        mock_controller = mocker.patch("mfd_connect.api.download_utils.download_file_unix_via_controller")
        download_file_esxi(
            connection,
            "http://arti/a.zip",
            PurePosixPath("/home/mydir/a.zip"),
        )
        mock.assert_called_once_with(
            connection,
            "http://arti/a.zip",
            PurePosixPath("/home/mydir/a.zip"),
            "",
        )
        mock_controller.assert_not_called()

    def test_download_file_esxi_too_many_credentials(self, connection):
        with pytest.raises(ValueError):
            download_file_esxi(
                connection,
                "http://arti/a.zip",
                PurePosixPath("/home/mydir/a.zip"),
                options="-u 3141 -p 1234",
                headers={"X-JFrog-Art-Api": "fake_token"},
            )

    def test_download_file_esxi_via_controller(self, connection, mocker):
        connection.execute_command.return_value = ConnectionCompletedProcess(
            args="", stdout="", stderr="", return_code=1
        )
        mock = mocker.patch("mfd_connect.api.download_utils._download_file_esxi")
        mock_controller = mocker.patch("mfd_connect.api.download_utils.download_file_unix_via_controller")
        download_file_esxi(
            connection,
            "http://arti/a.zip",
            destination_file=PurePosixPath("/home/mydir/a.zip"),
            options="-u 3141",
        )
        mock.assert_not_called()
        mock_controller.assert_called_once_with(
            connection,
            PurePosixPath("/home/mydir/a.zip"),
            "-u 3141",
            "http://arti/a.zip",
        )

    def test_download_file_unix_via_controller(self, connection, mocker):
        connection.execute_command = mocker.Mock(
            return_value=ConnectionCompletedProcess(args="", stdout="", stderr="", return_code=0)
        )
        mocker.patch("mfd_connect.LocalConnection", return_value=mocker.Mock())
        mocker.patch("mfd_connect.util.rpc_copy_utils.copy")
        res = download_file_unix_via_controller(
            connection,
            url="http://arti/a.zip",
            destination_file=PurePosixPath("/home/mydir/a.zip"),
            options="-u 3141",
        )
        assert isinstance(res, ConnectionCompletedProcess)

    def test__prepare_headers_windows(self):
        assert (
            _prepare_headers_powershell({"X-JFrog-Art-Api": "fake_token"})
            == "-Headers @{'X-JFrog-Art-Api'= 'fake_token';}"
        )

    def test__prepare_headers_windows_empty(self):
        assert _prepare_headers_powershell({}) == ""

    def test__prepare_headers_windows_none(self):
        assert _prepare_headers_powershell(None) == ""

    def test__prepare_headers_windows_multiple(self):
        assert (
            _prepare_headers_powershell({"X-JFrog-Art-Api": "fake_token", "X-Other-Header": "other_value"})
            == "-Headers @{'X-JFrog-Art-Api'= 'fake_token';'X-Other-Header'= 'other_value';}"
        )

    def test__prepare_headers_with_env_powershell_windows(self):
        assert (
            _prepare_headers_with_env_powershell({"$env:TEMP_KEY_123456_0": "$env:TEMP_VALUE_123456_0"})
            == "-Headers @{$env:TEMP_KEY_123456_0= $env:TEMP_VALUE_123456_0;}"
        )

    def test__prepare_headers_with_env_powershell_windows_empty(self):
        assert _prepare_headers_with_env_powershell({}) == ""

    def test__prepare_headers_with_env_powershell_windows_none(self):
        assert _prepare_headers_with_env_powershell(None) == ""

    def test__prepare_headers_with_env_powershell_windows_multiple(self):
        assert (
            _prepare_headers_with_env_powershell(
                {
                    "$env:TEMP_KEY_123456_0": "$env:TEMP_VALUE_123456_0",
                    "$env:TEMP_KEY_123456_1": "$env:TEMP_VALUE_123456_1",
                }
            )
            == "-Headers @{$env:TEMP_KEY_123456_0= $env:TEMP_VALUE_123456_0;"
            "$env:TEMP_KEY_123456_1= $env:TEMP_VALUE_123456_1;}"
        )

    def test__prepare_headers_wget(self):
        assert _prepare_headers_wget({"X-JFrog-Art-Api": "fake_token"}) == '--header="X-JFrog-Art-Api: fake_token"'

    def test__prepare_headers_wget_empty(self):
        assert _prepare_headers_wget({}) == ""

    def test__prepare_headers_wget_none(self):
        assert _prepare_headers_wget(None) == ""

    def test__prepare_headers_wget_multiple(self):
        assert (
            _prepare_headers_wget({"X-JFrog-Art-Api": "fake_token", "X-Other-Header": "other_value"})
            == '--header="X-JFrog-Art-Api: fake_token" --header="X-Other-Header: other_value"'
        )

    def test__prepare_headers_curl(self):
        assert _prepare_headers_curl({"X-JFrog-Art-Api": "fake_token"}) == '-H "X-JFrog-Art-Api: fake_token"'

    def test__prepare_headers_curl_empty(self):
        assert _prepare_headers_curl({}) == ""

    def test__prepare_headers_curl_none(self):
        assert _prepare_headers_curl(None) == ""

    def test__prepare_headers_curl_multiple(self):
        assert (
            _prepare_headers_curl({"X-JFrog-Art-Api": "fake_token", "X-Other-Header": "other_value"})
            == '-H "X-JFrog-Art-Api: fake_token" -H "X-Other-Header: other_value"'
        )
