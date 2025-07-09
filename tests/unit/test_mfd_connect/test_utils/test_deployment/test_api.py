# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
import re
from pathlib import PureWindowsPath

import pytest
from mfd_typing import OSName

from mfd_connect import WinRmConnection, SSHConnection, RPyCConnection
from mfd_connect.base import ConnectionCompletedProcess
from mfd_connect.exceptions import RPyCDeploymentException
from mfd_connect.util.deployment import extract_to_directory
from mfd_connect.util.deployment.api import (
    _is_rpyc_responder_running_ssh,
    _is_rpyc_responder_running_winrm,
    get_esxi_datastore_path,
)


class TestDeploymentAPI:
    @pytest.fixture()
    def winrm_connection(self, mocker):
        yield mocker.create_autospec(WinRmConnection)

    @pytest.fixture()
    def ssh_connection(self, mocker):
        yield mocker.create_autospec(SSHConnection)

    def test_extract_to_directory(self, winrm_connection):
        winrm_connection.execute_command.return_value = ConnectionCompletedProcess(args="", stdout="done", stderr="")
        extract_to_directory(winrm_connection, PureWindowsPath("c:\\pp.zip"), PureWindowsPath("c:\\pp\\"))
        winrm_connection.execute_command.assert_called_once_with(
            "powershell.exe Add-Type -Assembly System.IO.Compression.Filesystem; "
            '[System.IO.Compression.ZipFile]::ExtractToDirectory(\\"c:\\pp.zip\\", '
            '\\"c:\\pp\\")'
        )

    def test_extract_to_directory_error(self, winrm_connection):
        winrm_connection.execute_command.return_value = ConnectionCompletedProcess(
            args="", stdout="", stderr="some error"
        )
        with pytest.raises(
            RPyCDeploymentException, match=re.escape(r"Error during unpacking files c:\pp.zip to c:\pp: some error")
        ):
            extract_to_directory(winrm_connection, PureWindowsPath("c:\\pp.zip"), PureWindowsPath("c:\\pp\\"))
            winrm_connection.execute_command.assert_called_once_with('del /F \\"c:\\pp\\"')

    def test__is_rpyc_responder_running_ssh_not_running(self, ssh_connection):
        ssh_connection.get_os_name.return_value = OSName.LINUX
        ssh_connection.execute_command.return_value = ConnectionCompletedProcess(args="", stdout="", stderr="")
        assert _is_rpyc_responder_running_ssh(ssh_connection, "/home/pp/bin/python") is False

    def test__is_rpyc_responder_running_ssh_running_correct(self, ssh_connection, mocker):
        ssh_connection.get_os_name.return_value = OSName.LINUX
        ssh_connection.execute_command.side_effect = [
            ConnectionCompletedProcess(args="", stdout="1111", stderr=""),
            ConnectionCompletedProcess(args="", stdout="1111", stderr=""),
        ]
        assert _is_rpyc_responder_running_ssh(ssh_connection, "/home/pp/bin/python") is True
        calls = [
            mocker.call(
                "ps aux | grep 'mfd_connect.rpyc_server --port "
                f"{RPyCConnection.DEFAULT_RPYC_6_0_0_RESPONDER_PORT+1}' |grep -v grep | "
                "awk '{print $2}'",
                shell=True,
            ),
            mocker.call(
                "ps aux | grep '/home/pp/bin/python' |grep -v grep | awk '{print $2}'",
                shell=True,
            ),
        ]
        ssh_connection.execute_command.assert_has_calls(calls)

    def test__is_rpyc_responder_running_ssh_running_incorrect(self, ssh_connection, mocker):
        ssh_connection.get_os_name.return_value = OSName.LINUX
        ssh_connection.execute_command.side_effect = [
            ConnectionCompletedProcess(args="", stdout="1211", stderr=""),
            ConnectionCompletedProcess(args="", stdout="", stderr=""),
            ConnectionCompletedProcess(args="", stdout="", stderr=""),
        ]
        assert _is_rpyc_responder_running_ssh(ssh_connection, "/home/pp/bin/python") is False
        calls = [
            mocker.call(
                "ps aux | grep 'mfd_connect.rpyc_server --port "
                f"{RPyCConnection.DEFAULT_RPYC_6_0_0_RESPONDER_PORT+1}' |grep -v grep | "
                "awk '{print $2}'",
                shell=True,
            ),
            mocker.call(
                "ps aux | grep '/home/pp/bin/python' |grep -v grep | awk '{print $2}'",
                shell=True,
            ),
            mocker.call("kill -9 1211"),
        ]
        ssh_connection.execute_command.assert_has_calls(calls)

    def test__is_rpyc_responder_running_winrm(self, mocker, winrm_connection):
        winrm_connection.execute_command.return_value = ConnectionCompletedProcess(args="", stdout="", stderr="")
        assert _is_rpyc_responder_running_winrm(winrm_connection, "c:\\pp\\python.exe") is False
        winrm_connection.execute_command.assert_called_once_with(
            'powershell.exe -command "Get-WmiObject Win32_Process -Filter \\"name = \'python.exe\'\\" | '
            "Select-Object CommandLine,ProcessID | Where-Object -Property CommandLine "
            '-like \\"*mfd_connect*--port 18817*\\" | Select -Expand ProcessID"'
        )

    def test__is_rpyc_responder_running_winrm_running_valid(self, mocker, winrm_connection):
        winrm_connection.execute_command.side_effect = [
            ConnectionCompletedProcess(args="", stdout="1111", stderr=""),
            ConnectionCompletedProcess(args="", stdout="1111", stderr=""),
        ]
        assert _is_rpyc_responder_running_winrm(winrm_connection, "c:\\pp\\python.exe") is True
        calls = [
            mocker.call(
                'powershell.exe -command "Get-WmiObject Win32_Process -Filter \\"name = \'python.exe\'\\" | '
                "Select-Object CommandLine,ProcessID | Where-Object -Property CommandLine "
                '-like \\"*mfd_connect*--port 18817*\\" | Select -Expand ProcessID"'
            ),
            mocker.call(
                'powershell.exe -command "Get-WmiObject Win32_Process | '
                "Where-Object -Property Path -EQ 'c:\\pp\\python.exe' | "
                'Select -Expand ProcessID"'
            ),
        ]
        winrm_connection.execute_command.assert_has_calls(calls)

    def test__is_rpyc_responder_running_winrm_running_invalid(self, mocker, winrm_connection):
        winrm_connection.execute_command.side_effect = [
            ConnectionCompletedProcess(args="", stdout="1111", stderr=""),
            ConnectionCompletedProcess(args="", stdout="", stderr=""),
            ConnectionCompletedProcess(args="", stdout="", stderr=""),
        ]
        assert _is_rpyc_responder_running_winrm(winrm_connection, "c:\\pp\\python.exe") is False
        calls = [
            mocker.call(
                'powershell.exe -command "Get-WmiObject Win32_Process -Filter \\"name = \'python.exe\'\\" | '
                "Select-Object CommandLine,ProcessID | Where-Object -Property CommandLine "
                '-like \\"*mfd_connect*--port 18817*\\" | Select -Expand ProcessID"'
            ),
            mocker.call(
                'powershell.exe -command "Get-WmiObject Win32_Process | '
                "Where-Object -Property Path -EQ 'c:\\pp\\python.exe' | "
                'Select -Expand ProcessID"'
            ),
            mocker.call('powershell.exe -command "Stop-Process -ID 1111 -Force"'),
        ]
        winrm_connection.execute_command.assert_has_calls(calls)

    def test_get_esxi_datastore_path(self, ssh_connection):
        ssh_connection.execute_command.return_value = ConnectionCompletedProcess(
            args="", stderr="", stdout="/vmfs/volumes/5bc9d125-9c015531-f0d4-001e6762ca0a"
        )
        assert get_esxi_datastore_path(ssh_connection) == "/vmfs/volumes/5bc9d125-9c015531-f0d4-001e6762ca0a"
