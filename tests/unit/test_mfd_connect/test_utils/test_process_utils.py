# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Unit Test Module for Process utils."""

import pytest
from textwrap import dedent
from unittest.mock import call

from mfd_common_libs import log_levels

from mfd_connect import (
    SSHConnection,
    LocalConnection,
)
from mfd_connect.base import ConnectionCompletedProcess
from mfd_connect.exceptions import ProcessNotRunning
from mfd_typing.os_values import OSName
from mfd_connect.util.process_utils import (
    get_process_by_name,
    kill_process_by_name,
    kill_all_processes_by_name,
    stop_process_by_name,
)


class TestProcessUtils:
    @pytest.fixture()
    def ssh_linux(self, mocker):
        conn = mocker.create_autospec(SSHConnection)
        conn.get_os_name = mocker.Mock(return_value=OSName.LINUX)
        return conn

    @pytest.fixture()
    def ssh_windows(self, mocker):
        conn = mocker.create_autospec(LocalConnection)
        conn.get_os_name = mocker.Mock(return_value=OSName.WINDOWS)
        return conn

    @pytest.fixture()
    def ssh_esxi(self, mocker):
        conn = mocker.create_autospec(LocalConnection)
        conn.get_os_name = mocker.Mock(return_value=OSName.ESXI)
        return conn

    @pytest.fixture()
    def ssh_freebsd(self, mocker):
        conn = mocker.create_autospec(LocalConnection)
        conn.get_os_name = mocker.Mock(return_value=OSName.FREEBSD)
        return conn

    @pytest.fixture()
    def ssh_efishell(self, mocker):
        conn = mocker.create_autospec(SSHConnection)
        conn.get_os_name = mocker.Mock(return_value=OSName.EFISHELL)
        return conn

    def test_get_process_by_name_process_linux(self, ssh_linux):
        pidof_out = dedent(
            """\
                1108863 1108849 1108831
            """
        )
        ssh_linux.execute_command.return_value = ConnectionCompletedProcess(args="", stdout=pidof_out, return_code=0)
        assert get_process_by_name(conn=ssh_linux, process_name="tcpdump") == ["1108863", "1108849", "1108831"]
        ssh_linux.execute_command.assert_called_once_with("pidof tcpdump", expected_return_codes={0, 1}, shell=True)

    def test_get_process_by_name_process_not_running_error_linux(self, ssh_linux, mocker):
        ssh_linux.execute_command.return_value = ConnectionCompletedProcess(args="", stdout="", return_code=1)
        with pytest.raises(ProcessNotRunning, match="Process tcpdump not running!"):
            get_process_by_name(conn=ssh_linux, process_name="tcpdump")

    def test_kill_process_by_name_linux(self, ssh_linux):
        ssh_linux.execute_command.side_effect = [
            ConnectionCompletedProcess(return_code=0, args="", stdout="", stderr=""),
        ]
        kill_process_by_name(conn=ssh_linux, process_name="tcpdump")
        ssh_linux.execute_command.assert_called_once_with(
            "pkill tcpdump --signal SIGINT", expected_return_codes={0, 1}, shell=True
        )

    def test_kill_process_by_name_using_kill_linux(self, ssh_linux):
        ssh_linux.execute_command.return_value = ConnectionCompletedProcess(args="", stdout="", return_code=1)
        with pytest.raises(ProcessNotRunning, match="Process tcpdump not running!"):
            kill_process_by_name(conn=ssh_linux, process_name="tcpdump")

    def test_get_process_by_name_windows(self, ssh_windows):
        get_process_out = dedent(
            """"
               Id
               --
             6372
             8308
            10468
            11176
            """
        )
        ssh_windows.execute_powershell.return_value = ConnectionCompletedProcess(
            args="", stdout=get_process_out, return_code=0
        )
        assert get_process_by_name(conn=ssh_windows, process_name="iexplore") == ["6372", "8308", "10468", "11176"]
        ssh_windows.execute_powershell.assert_called_once_with(
            "Get-Process iexplore | Select-Object Id", expected_return_codes={0, 1}
        )

    def test_get_process_by_name_not_running_error_windows(self, ssh_windows):
        ssh_windows.execute_powershell.return_value = ConnectionCompletedProcess(args="", stdout="", return_code=1)
        with pytest.raises(ProcessNotRunning, match="Process iexplore not running!"):
            get_process_by_name(conn=ssh_windows, process_name="iexplore")

    def test_kill_process_by_name_windows(self, ssh_windows):
        get_process_out = dedent(
            """"
               Id
               --
              668
             6276
             8740
            10476


            """
        )
        ssh_windows.execute_powershell.side_effect = [
            ConnectionCompletedProcess(return_code=0, args="", stdout=get_process_out, stderr=""),
            ConnectionCompletedProcess(return_code=0, args="", stdout="", stderr=""),
            ConnectionCompletedProcess(return_code=0, args="", stdout="", stderr=""),
            ConnectionCompletedProcess(return_code=0, args="", stdout="", stderr=""),
            ConnectionCompletedProcess(return_code=0, args="", stdout="", stderr=""),
        ]
        kill_process_by_name(conn=ssh_windows, process_name="iexplore")
        ssh_windows.execute_powershell.assert_has_calls(
            [
                call("Get-Process iexplore | Select-Object Id", expected_return_codes={0, 1}),
                call("taskkill /f /t /pid 668", expected_return_codes={0, 1}),
                call("taskkill /f /t /pid 6276", expected_return_codes={0, 1}),
                call("taskkill /f /t /pid 8740", expected_return_codes={0, 1}),
                call("taskkill /f /t /pid 10476", expected_return_codes={0, 1}),
            ]
        )

    def test_kill_all_processes_by_name_windows(self, ssh_windows):
        ssh_windows.execute_powershell.return_value = ConnectionCompletedProcess(args="", stdout="", return_code=0)
        kill_all_processes_by_name(conn=ssh_windows, process_name="explorer.exe")
        ssh_windows.execute_powershell.assert_called_once_with("taskkill /f /im explorer.exe")

    def test_get_process_by_name_esxi(self, ssh_esxi):
        ps_output = dedent(
            """\
            4752211  4752211  ping
            4752359  4752359  ping
            """
        )
        ssh_esxi.execute_command.return_value = ConnectionCompletedProcess(args="", stdout=ps_output, return_code=0)
        assert get_process_by_name(conn=ssh_esxi, process_name="ping") == ["4752211", "4752359"]

    def test_get_process_by_name_process_not_running_error_esxi(self, ssh_esxi, mocker):
        ssh_esxi.execute_command.return_value = ConnectionCompletedProcess(args="", stdout="", return_code=1)
        with pytest.raises(ProcessNotRunning, match="Process tcpdump not running!"):
            get_process_by_name(conn=ssh_esxi, process_name="tcpdump")

    def test_kill_process_by_name_esxi(self, ssh_esxi):
        ps_out = dedent(
            """\
            4752211  4752211  ping
            4752359  4752359  ping
            """
        )
        ssh_esxi.execute_command.side_effect = [
            ConnectionCompletedProcess(return_code=0, args="", stdout=ps_out, stderr=""),
            ConnectionCompletedProcess(return_code=0, args="", stdout=ps_out, stderr=""),
            ConnectionCompletedProcess(return_code=0, args="", stdout="", stderr=""),
        ]
        kill_process_by_name(conn=ssh_esxi, process_name="ping")
        ssh_esxi.execute_command.assert_has_calls(
            [
                call("ps | grep ping", expected_return_codes={0, 1}, shell=True),
                call("kill 4752211", shell=True),
                call("kill 4752359", shell=True),
            ]
        )

    def test_get_process_by_name_freebsd(self, ssh_freebsd):
        ps_output = dedent(
            """\
                44697  1  S+   0:00.00 grep tcpdump
                44680  2  SC+  0:00.02 tcpdump
                44692  3  SC+  0:00.02 tcpdump
                """
        )
        ssh_freebsd.execute_command.return_value = ConnectionCompletedProcess(args="", stdout=ps_output, return_code=0)
        assert get_process_by_name(conn=ssh_freebsd, process_name="tcpdump") == ["44680", "44692"]

    def test_get_process_by_name_process_not_running_error_freebsd(self, ssh_freebsd, mocker):
        ssh_freebsd.execute_command.return_value = ConnectionCompletedProcess(args="", stdout="", return_code=1)
        with pytest.raises(ProcessNotRunning, match="Process tcpdump not running!"):
            get_process_by_name(conn=ssh_freebsd, process_name="tcpdump")

    def test_kill_process_by_name_freebsd(self, ssh_freebsd):
        ps_out = dedent(
            """\
            44697  1  S+   0:00.00 grep tcpdump
            44680  2  SC+  0:00.02 tcpdump
            44692  3  SC+  0:00.02 tcpdump
            """
        )
        ssh_freebsd.execute_command.side_effect = [
            ConnectionCompletedProcess(return_code=0, args="", stdout=ps_out, stderr=""),
            ConnectionCompletedProcess(return_code=0, args="", stdout=ps_out, stderr=""),
            ConnectionCompletedProcess(return_code=0, args="", stdout="", stderr=""),
        ]
        kill_process_by_name(conn=ssh_freebsd, process_name="tcpdump")
        ssh_freebsd.execute_command.assert_has_calls(
            [
                call("ps | grep tcpdump", expected_return_codes={0, 1}),
                call("kill 44680"),
                call("kill 44692"),
            ]
        )

    def test_get_process_by_name_process_efi(self, ssh_efishell, mocker):
        with pytest.raises(NotImplementedError, match=f"Not Implemented for {ssh_efishell.get_os_name()} OS"):
            get_process_by_name(conn=ssh_efishell, process_name="tcpdump")

    def test_stop_process_not_running(self, mocker, ssh_linux, caplog):
        caplog.set_level(log_levels.MODULE_DEBUG)
        mocker.patch("mfd_connect.util.process_utils.get_process_by_name", side_effect=ProcessNotRunning)
        stop_process_by_name(ssh_linux, "irqbalance")
        assert "The irqbalance was not running." in caplog.text

    def test_stop_process_running(self, mocker, ssh_linux, caplog):
        caplog.set_level(log_levels.MODULE_DEBUG)
        mocker.patch("mfd_connect.util.process_utils.get_process_by_name", side_effect=[True, ProcessNotRunning])
        mocker.patch("mfd_connect.util.process_utils.kill_process_by_name")
        stop_process_by_name(ssh_linux, "irqbalance")
        assert "irqbalance process killed" in caplog.text

    def test_stop_process_error(self, mocker, ssh_linux):
        mocker.patch("mfd_connect.util.process_utils.get_process_by_name", return_value=True)
        mocker.patch("mfd_connect.util.process_utils.kill_process_by_name")
        with pytest.raises(Exception, match="Unknown error killing irqbalance"):
            stop_process_by_name(ssh_linux, "irqbalance")
