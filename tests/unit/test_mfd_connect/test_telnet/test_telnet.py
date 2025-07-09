# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
from logging import DEBUG
from re import Match
from subprocess import CalledProcessError
from textwrap import dedent

import pytest
from mfd_common_libs import log_levels
from unittest.mock import Mock

from mfd_connect import TelnetConnection
from mfd_connect.base import ConnectionCompletedProcess
from mfd_connect.exceptions import (
    TelnetException,
    ConnectionCalledProcessError,
    OsNotSupported,
)
from mfd_connect.telnet.telnet_console import TelnetConsole
from mfd_typing.os_values import OSBitness, OSType

telnet_output = """
[0m[30m[40m[25;27H  [01D  [0m[30m[47m[10;01H   [02D>[01CDevice Manager                                        [0m[37m[40m[23;02H [22;02H [50C                         [51D                          [23;53H                           [77D^v=Move Highlight       [22;03H                        [23;27H<Enter>=Select Entry      [0m[30m[47m[0m[37m[40m[08;31H<Standard English>[0m[30m[47m         [57D   Select Language            [0m[34m[47m[27CThis is the option
[57Cone adjusts to change
[57Cthe language for the
[57Ccurrent system
[57C
[57C
[57C
[57C
[57C
[57C
[57C
[57C
[19;80H"""  # noqa: W291,W293,E501,BLK100


class TestTelnetConnection:
    """Tests of TelnetConnection."""

    correct_raw_output = dedent(
        """\
    ls -la
    total 78
    drwx------  6 userb userb  11 Aug  3 13:44 .
    drwxr-xr-x  4 root  root    5 Jun 28 12:35 ..
    -rw-r--r--  1 root  root    1 May 25 20:50 .bash_history
    -rw-r--r--  1 userb userb  18 Dec  4  2020 .bash_logout
    -rw-r--r--  1 userb userb 376 Dec  4  2020 .bashrc
    drwxr-xr-x 10 userb userb 160 Aug  3 17:04 userb
    drwx------ 11 userb userb  12 Jul  9 15:12 .cache
    drwx------ 11 userb userb  15 Jun 30 10:43 .config
    -rw-------  1 userb userb  16 Jul 26 13:32 .esd_auth
    -rw-------  1 userb userb 310 Jun 30 10:43 .ICEauthority
    drwxr-xr-x  5 userb userb   5 Jul 30 08:19 .local
    [userb@Mickey-10-010 ~]$"""
    )

    @pytest.fixture()
    def telnet(self, mocker):
        mocker.patch.object(TelnetConnection, "_establish_telnet_connection", return_value=None)
        conn = TelnetConnection(ip="10.10.10.10", port=10, username="***", password="***")
        conn._ip = "10.10.10.10"
        conn.console = mocker.create_autospec(TelnetConsole)
        conn._login_timeout = 1
        conn._username = "user"
        conn._password = "pass"
        mocker.stopall()
        return conn

    @pytest.fixture()
    def connect_mock(self, telnet, mocker):
        return mocker.patch.object(telnet, "_connect", return_value=None)

    def test_establish_telnet_connection(self, telnet, mocker, connect_mock):
        telnet.console.is_connected.return_value = True
        login_mock = mocker.patch.object(telnet, "_login", return_value=None)
        telnet._establish_telnet_connection()
        connect_mock.assert_called_once()
        login_mock.assert_called_once()

    def test_establish_telnet_connection_once_retry(self, telnet, mocker, caplog, connect_mock):
        caplog.set_level(log_levels.MODULE_DEBUG)
        telnet.console.is_connected.return_value = True
        connect_mock.side_effect = [TelnetConnection._TELNET_BROKE_ERRORS[0], None]
        login_mock = mocker.patch.object(telnet, "_login", return_value=None)
        telnet._establish_telnet_connection()
        assert connect_mock.call_count == 2
        login_mock.assert_called_once()
        assert "Telnet connection is broken - reconnecting and retrying to login" in caplog.text

    def test_establish_telnet_connection_fail(self, telnet, caplog, connect_mock):
        caplog.set_level(log_levels.MODULE_DEBUG)
        telnet.console.is_connected.return_value = True
        connect_mock.side_effect = TelnetConnection._TELNET_BROKE_ERRORS[0]
        with pytest.raises(TelnetException, match="Could not establish telnet connection to target after 2 retries"):
            telnet._establish_telnet_connection()
        assert connect_mock.call_count == 2
        assert "Telnet connection is broken - reconnecting and retrying to login" in caplog.text

    def test__connect(self, telnet, mocker):
        console_mock = mocker.patch("mfd_connect.telnet.telnet.TelnetConsole")
        telnet._connect()
        console_mock.assert_called_once_with(ip="10.10.10.10", port=10)

    def test__connect_raised_refused(self, telnet, mocker, caplog):
        caplog.set_level(log_levels.MODULE_DEBUG)
        console_mock = mocker.patch("mfd_connect.telnet.telnet.TelnetConsole", side_effect=ConnectionRefusedError)
        telnet._connect()
        console_mock.assert_called_once_with(ip="10.10.10.10", port=10)
        assert "Telnet connection is refused - already connected?" in caplog.text

    def test__login(self, telnet, mocker):
        credentials_mock = mocker.patch.object(telnet, "_enter_credentials", return_value=None)
        telnet._login()
        credentials_mock.assert_called_once()

    def test__login_once_retry(self, telnet, mocker, caplog, connect_mock):
        caplog.set_level(log_levels.MODULE_DEBUG)
        credentials_mock = mocker.patch.object(
            telnet, "_enter_credentials", side_effect=[TelnetConnection._TELNET_BROKE_ERRORS[0], None]
        )
        telnet._login()
        connect_mock.assert_called_once()
        assert credentials_mock.call_count == 2
        assert (
            "Telnet connection is broken - reconnecting and retrying to login (exception type: <class 'EOFError'>)"
            in caplog.text
        )

    def test__login_fail(self, telnet, mocker, caplog, connect_mock):
        caplog.set_level(log_levels.MODULE_DEBUG)
        credentials_mock = mocker.patch.object(
            telnet, "_enter_credentials", side_effect=TelnetConnection._TELNET_BROKE_ERRORS[0]
        )
        with pytest.raises(TelnetException, match="Could not login to console after 2 retries"):
            telnet._login()
        assert credentials_mock.call_count == 2
        assert connect_mock.call_count == 2
        assert (
            "Telnet connection is broken - reconnecting and retrying to login (exception type: <class 'EOFError'>)"
            in caplog.text
        )

    def test__enter_credentials_already_logged(self, telnet, mocker, caplog):
        caplog.set_level(log_levels.MODULE_DEBUG)
        mocker.patch("time.sleep", return_value=None)
        telnet.console.is_connected.return_value = True
        telnet.console.write.return_value = None
        telnet.console.expect.side_effect = [(1, mocker.create_autospec(Match), "")]
        telnet._enter_credentials()
        telnet.console.expect.assert_has_calls(
            [mocker.call([telnet._login_prompt.encode(), telnet._prompt.encode()], 1)]
        )
        assert r"Found b'[#\\$](?:\\033\\[0m \\S*)?\\s*$' pattern, read from console:" in caplog.text
        assert r"Waiting for login prompt, [b'login: ', b'[#\\$](?:\\033\\[0m \\S*)?\\s*$']" in caplog.text

    def test__enter_credentials_missing_login_prompt(self, telnet, mocker, caplog):
        caplog.set_level(log_levels.MODULE_DEBUG)
        mocker.patch("time.sleep", return_value=None)
        telnet.console.is_connected.return_value = True
        telnet.console.write.return_value = None
        telnet.console.expect.side_effect = [(-1, mocker.create_autospec(Match), "")]
        with pytest.raises(ConnectionResetError, match="Login prompt not found"):
            telnet._enter_credentials()
        telnet.console.expect.assert_has_calls(
            [mocker.call([telnet._login_prompt.encode(), telnet._prompt.encode()], 1)]
        )

    def test__enter_credentials_without_password(self, telnet, mocker, caplog):
        telnet._password = None
        caplog.set_level(log_levels.MODULE_DEBUG)
        mocker.patch("time.sleep", return_value=None)
        telnet.console.is_connected.return_value = True
        telnet.console.write.return_value = None
        telnet.console.expect.side_effect = [
            (0, mocker.create_autospec(Match), ""),
            (0, mocker.create_autospec(Match), ""),
        ]
        telnet._enter_credentials()
        telnet.console.write.assert_has_calls([mocker.call("user")])
        assert r"Found b'login: ' pattern, read from console:" in caplog.text
        assert r"Waiting for login prompt, [b'login: ', b'[#\\$](?:\\033\\[0m \\S*)?\\s*$']" in caplog.text
        assert r"Waiting for prompt" in caplog.text
        assert r"Writing username to prompt" in caplog.text
        assert r"Prompt found" in caplog.text
        first_prompt_find = mocker.call([telnet._login_prompt.encode(), telnet._prompt.encode()], 1)
        prompt_find = mocker.call([telnet._prompt.encode()], 1)
        telnet.console.expect.assert_has_calls([first_prompt_find, prompt_find])

    def test__enter_credentials_with_password_and_required(self, telnet, mocker, caplog):
        caplog.set_level(log_levels.MODULE_DEBUG)
        mocker.patch("time.sleep", return_value=None)
        telnet.console.is_connected.return_value = True
        telnet.console.write.return_value = None
        telnet.console.expect.side_effect = [
            (0, mocker.create_autospec(Match), ""),
            (0, mocker.create_autospec(Match), ""),
            (0, mocker.create_autospec(Match), ""),
        ]
        telnet._enter_credentials()
        telnet.console.write.assert_has_calls([mocker.call("user"), mocker.call("pass")])
        assert r"Found b'login: ' pattern, read from console:" in caplog.text
        assert r"Waiting for login prompt, [b'login: ', b'[#\\$](?:\\033\\[0m \\S*)?\\s*$']" in caplog.text
        assert r"Waiting for prompt" in caplog.text
        assert r"Writing username to prompt" in caplog.text
        assert r"Prompt found" in caplog.text
        assert r"Writing password to prompt" in caplog.text
        assert r"Waiting for password prompt" in caplog.text
        first_prompt_find = mocker.call([telnet._login_prompt.encode(), telnet._prompt.encode()], 1)
        prompt_find = mocker.call([telnet._prompt.encode()], 1)
        password_prompt_find = mocker.call([telnet._password_prompt.encode()], 1)
        telnet.console.expect.assert_has_calls([first_prompt_find, password_prompt_find, prompt_find])

    def test__enter_credentials_with_password_and_not_required(self, telnet, mocker, caplog):
        caplog.set_level(log_levels.MODULE_DEBUG)
        mocker.patch("time.sleep", return_value=None)
        telnet.console.is_connected.return_value = True
        telnet.console.write.return_value = None
        telnet.console.expect.side_effect = [
            (0, mocker.create_autospec(Match), ""),
            (-1, mocker.create_autospec(Match), ""),
            (0, mocker.create_autospec(Match), ""),
        ]
        telnet._enter_credentials()
        telnet.console.write.assert_has_calls([mocker.call("user"), mocker.call(b"\n")])
        assert r"Found b'login: ' pattern, read from console:" in caplog.text
        assert r"Waiting for login prompt, [b'login: ', b'[#\\$](?:\\033\\[0m \\S*)?\\s*$']" in caplog.text
        assert r"Waiting for prompt" in caplog.text
        assert r"Writing username to prompt" in caplog.text
        assert r"Prompt found" in caplog.text
        assert r"Password prompt not found, expecting command prompt" in caplog.text
        assert r"Waiting for password prompt" in caplog.text
        first_prompt_find = mocker.call([telnet._login_prompt.encode(), telnet._prompt.encode()], 1)
        prompt_find = mocker.call([telnet._prompt.encode()], 1)
        password_prompt_find = mocker.call([telnet._password_prompt.encode()], 1)
        telnet.console.expect.assert_has_calls([first_prompt_find, password_prompt_find, prompt_find])

    def test__enter_credentials_missing_prompt(self, telnet, mocker, caplog):
        telnet._password = None
        caplog.set_level(log_levels.MODULE_DEBUG)
        mocker.patch("time.sleep", return_value=None)
        telnet.console.is_connected.return_value = True
        telnet.console.write.return_value = None
        telnet.console.expect.side_effect = [
            (0, mocker.create_autospec(Match), ""),
            (-1, mocker.create_autospec(Match), ""),
        ]
        with pytest.raises(ConnectionResetError, match="Prompt not found after entering credentials"):
            telnet._enter_credentials()
        telnet.console.write.assert_has_calls([mocker.call("user")])
        assert r"Found b'login: ' pattern, read from console:" in caplog.text
        assert r"Waiting for login prompt, [b'login: ', b'[#\\$](?:\\033\\[0m \\S*)?\\s*$']" in caplog.text
        assert r"Waiting for prompt" in caplog.text
        assert r"Writing username to prompt" in caplog.text
        first_prompt_find = mocker.call([telnet._login_prompt.encode(), telnet._prompt.encode()], 1)
        prompt_find = mocker.call([telnet._prompt.encode()], 1)
        telnet.console.expect.assert_has_calls([first_prompt_find, prompt_find])

    def test__clear_cmdline(self, telnet, mocker):
        telnet.console.write.return_value = None
        telnet.console.flush_buffers.return_value = None
        telnet._clear_cmdline()
        telnet.console.write.assert_has_calls([mocker.call("\x03"), mocker.call("\x15"), mocker.call("\x0c")])
        telnet.console.flush_buffers.assert_called_once_with(timeout=0.5)

    def test__prepare_cmdline(self, telnet, mocker):
        credentials_mock = mocker.patch.object(telnet, "_clear_cmdline", return_value=None)
        telnet._prepare_cmdline()
        credentials_mock.assert_called_once()

    def test__prepare_cmdline_once_retry(self, telnet, mocker, caplog, connect_mock):
        caplog.set_level(log_levels.MODULE_DEBUG)
        clear_cmdline_mock = mocker.patch.object(
            telnet, "_clear_cmdline", side_effect=[TelnetConnection._TELNET_BROKE_ERRORS[0], None]
        )
        telnet._prepare_cmdline()
        connect_mock.assert_called_once()
        assert clear_cmdline_mock.call_count == 2
        assert "Telnet broke while clearing cmdline - 1 reconnection tries left" in caplog.text

    def test__prepare_cmdline_fail(self, telnet, mocker, caplog, connect_mock):
        caplog.set_level(log_levels.MODULE_DEBUG)
        clear_cmdline_mock = mocker.patch.object(
            telnet, "_clear_cmdline", side_effect=TelnetConnection._TELNET_BROKE_ERRORS[0]
        )
        with pytest.raises(
            TelnetException, match="Reached retries count for clearing commandline, telnet connection is breaking"
        ):
            telnet._prepare_cmdline()
        assert clear_cmdline_mock.call_count == 2
        assert connect_mock.call_count == 2
        assert "Telnet broke while clearing cmdline - 1 reconnection tries left" in caplog.text

    def test__write_to_console(self, telnet, mocker):
        time_sleep_mock = mocker.patch("time.sleep", return_value=None)
        mocker.patch.object(telnet, "_connect", return_value=None)
        telnet.console.write.return_value = None
        telnet.console.expect.return_value = (0, mocker.create_autospec(Match), b"my_output")
        assert telnet._write_to_console("test command", timeout=1, execution_retries=1) == "my_output"
        telnet.console.write.assert_called_once_with(buffer=b"test command", end=b"\n")
        time_sleep_mock.assert_called_once_with(0.5)
        prompt_find = mocker.call([telnet._prompt.encode()], 1)
        telnet.console.expect.assert_has_calls([prompt_find])

    def test__write_to_console_once_retry(self, telnet, mocker, caplog, connect_mock):
        caplog.set_level(log_levels.MODULE_DEBUG)
        time_sleep_mock = mocker.patch("time.sleep", return_value=None)
        telnet.console.write.side_effect = [EOFError, None]
        telnet.console.expect.return_value = (0, mocker.create_autospec(Match), b"my_output")
        assert telnet._write_to_console("test command", timeout=1, execution_retries=1) == "my_output"
        telnet.console.write.assert_has_calls(
            [mocker.call(buffer=b"test command", end=b"\n"), mocker.call(buffer=b"test command", end=b"\n")]
        )
        time_sleep_mock.assert_called_once_with(0.5)
        assert connect_mock.call_count == 1
        assert "Telnet broke - <class 'EOFError'> - 1 reconnection tries left" in caplog.text
        prompt_find = mocker.call([telnet._prompt.encode()], 1)
        telnet.console.expect.assert_has_calls([prompt_find])

    def test__write_to_console_fail(self, telnet, mocker):
        mocker.patch.object(telnet, "_connect", return_value=None)
        telnet.console.write.side_effect = [EOFError, None]
        telnet.console.expect.return_value = (0, mocker.create_autospec(Match), b"my_output")
        with pytest.raises(TelnetException, match="Reached retries count, command was not executed"):
            telnet._write_to_console("test command", timeout=1, execution_retries=0)
        telnet.console.write.assert_called_once_with(buffer=b"test command", end=b"\n")

    def test__write_to_console_fire_and_forget(self, telnet, mocker):
        time_sleep_mock = mocker.patch("time.sleep", return_value=None)
        mocker.patch.object(telnet, "_connect", return_value=None)
        telnet.console.write.return_value = None
        assert telnet._write_to_console("test command", timeout=1, execution_retries=1, fire_and_forget=True) is None
        telnet.console.write.assert_called_once_with(buffer=b"test command", end=b"\n")
        time_sleep_mock.assert_called_once_with(0.5)
        telnet.console.expect.assert_not_called()

    def test__get_return_code_simple_positive_int(self, telnet, mocker, caplog):
        caplog.set_level(log_levels.MODULE_DEBUG)
        rc_output = dedent(
            """\
        echo $?
        0
        [userb@Mickey-10-010~]$
        """
        )
        write_mock = mocker.patch.object(telnet, "_write_to_console", return_value=rc_output)
        assert telnet._get_return_code() == 0
        assert "Retrieving last return code" in caplog.text
        write_mock.assert_called_once_with("echo $?", timeout=20)

    def test__get_return_code_whitespace_chars(self, telnet, mocker, caplog):
        caplog.set_level(log_levels.MODULE_DEBUG)
        rc_output = """ echo $?
     0
     root@mev-imc:/usr/bin/cplane# """

        write_mock = mocker.patch.object(telnet, "_write_to_console", return_value=rc_output)
        assert telnet._get_return_code() == 0
        assert "Retrieving last return code" in caplog.text
        write_mock.assert_called_once_with("echo $?", timeout=20)

    def test__get_return_code_more_lines_negative_int(self, telnet, mocker, caplog):
        caplog.set_level(log_levels.MODULE_DEBUG)
        rc_output = dedent(
            """\
        echo $?
        garbage
        garbage
        -123
        garbage456
        [userb@Mickey-10-010 ~]$
        """
        )
        write_mock = mocker.patch.object(telnet, "_write_to_console", return_value=rc_output)
        assert telnet._get_return_code() == -123
        assert "Retrieving last return code" in caplog.text
        write_mock.assert_called_once_with("echo $?", timeout=20)

    def test__get_return_code_retry_once(self, telnet, mocker, caplog):
        time_sleep_mock = mocker.patch("time.sleep", return_value=None)
        caplog.set_level(log_levels.OUT)
        rc_output = dedent(
            """\
        echo $?
        -123
        [userb@Mickey-10-010 ~]$
        """
        )
        write_mock = mocker.patch.object(
            telnet, "_write_to_console", side_effect=["echo\nnot_int\nsomething", rc_output]
        )
        assert telnet._get_return_code() == -123
        assert "Retrieving last return code" in caplog.text
        assert write_mock.call_count == 2
        time_sleep_mock.assert_called_once_with(2)
        assert "Output from return code command: echo\nnot_int\nsomething" in caplog.text
        assert "Failed to retrieve last failed return code - 1 tries left" in caplog.text

    def test__get_return_code_empty_output(self, telnet, mocker, caplog):
        mocker.patch("time.sleep", return_value=None)
        caplog.set_level(log_levels.MODULE_DEBUG)
        write_mock = mocker.patch.object(telnet, "_write_to_console", return_value="")
        with pytest.raises(
            TelnetException,
            match="Missing output - check if there is any established connection to serial "
            "device e.g. through `minicom` or `screen`",
        ):
            telnet._get_return_code()
        assert "Retrieving last return code" in caplog.text
        write_mock.assert_called_with("echo $?", timeout=20)

    def test__get_return_code_failure(self, telnet, mocker, caplog):
        time_sleep_mock = mocker.patch("time.sleep", return_value=None)
        caplog.set_level(log_levels.OUT)
        write_mock = mocker.patch.object(telnet, "_write_to_console", return_value="echo\nnot_int\nsomething")
        with pytest.raises(TelnetException, match="Could not retrieve return code"):
            telnet._get_return_code()
        assert "Retrieving last return code" in caplog.text
        assert write_mock.call_count == 3
        assert time_sleep_mock.call_count == 3
        assert "Output from return code command: echo\nnot_int\nsomething" in caplog.text
        assert "Failed to retrieve last failed return code - 1 tries left" in caplog.text

    def test_execute_command(self, telnet, mocker, caplog):
        expected_output = dedent(
            """\
        total 78
        drwx------  6 userb userb  11 Aug  3 13:44 .
        drwxr-xr-x  4 root  root    5 Jun 28 12:35 ..
        -rw-r--r--  1 root  root    1 May 25 20:50 .bash_history
        -rw-r--r--  1 userb userb  18 Dec  4  2020 .bash_logout
        -rw-r--r--  1 userb userb 376 Dec  4  2020 .bashrc
        drwxr-xr-x 10 userb userb 160 Aug  3 17:04 userb
        drwx------ 11 userb userb  12 Jul  9 15:12 .cache
        drwx------ 11 userb userb  15 Jun 30 10:43 .config
        -rw-------  1 userb userb  16 Jul 26 13:32 .esd_auth
        -rw-------  1 userb userb 310 Jun 30 10:43 .ICEauthority
        drwxr-xr-x  5 userb userb   5 Jul 30 08:19 .local"""
        )
        expected_process = ConnectionCompletedProcess(args="my_command", stdout=expected_output, return_code=0)
        caplog.set_level(DEBUG)
        prepare_cmdline_mock = mocker.patch.object(telnet, "_prepare_cmdline")
        write_mock = mocker.patch.object(telnet, "_write_to_console", return_value=self.correct_raw_output)
        rc_mock = mocker.patch.object(telnet, "_get_return_code", return_value=0)
        output_process = telnet.execute_command("my_command")
        assert output_process.stdout == expected_process.stdout
        assert output_process.return_code == expected_process.return_code
        assert output_process.args == expected_process.args
        prepare_cmdline_mock.assert_called_once()
        write_mock.assert_called_once_with("my_command", timeout=30)
        rc_mock.assert_called_once_with(timeout=30)
        assert "Executing >10.10.10.10> 'my_command', cwd: None" in caplog.text
        assert "Finished executing 'my_command', rc=0" in caplog.text
        assert f"output>>\n{expected_output}" in caplog.text

    def test_execute_command_discard_output_ignore_custom_exception(self, telnet, mocker, caplog):
        expected_process = ConnectionCompletedProcess(args="my_command", stdout="", return_code=0)
        caplog.set_level(DEBUG)
        prepare_cmdline_mock = mocker.patch.object(telnet, "_prepare_cmdline")
        write_mock = mocker.patch.object(telnet, "_write_to_console", return_value=self.correct_raw_output)
        rc_mock = mocker.patch.object(telnet, "_get_return_code", return_value=0)
        output_process = telnet.execute_command(
            "my_command", discard_stdout=True, expected_return_codes=None, custom_exception=CalledProcessError
        )
        assert output_process.stdout == expected_process.stdout
        assert output_process.return_code == expected_process.return_code
        assert output_process.args == expected_process.args
        prepare_cmdline_mock.assert_called_once()
        write_mock.assert_called_once_with("my_command", timeout=30)
        rc_mock.assert_called_once_with(timeout=30)
        assert (
            "Return codes are ignored, passed exception: <class 'subprocess.CalledProcessError'> will be not raised."
            in caplog.text
        )

    def test_execute_command_failure(self, telnet, mocker):
        prepare_cmdline_mock = mocker.patch.object(telnet, "_prepare_cmdline")
        write_mock = mocker.patch.object(telnet, "_write_to_console", return_value=self.correct_raw_output)
        rc_mock = mocker.patch.object(telnet, "_get_return_code", return_value=0)
        with pytest.raises(ConnectionCalledProcessError):
            telnet.execute_command("my_command", discard_stdout=True, expected_return_codes=[1])
        prepare_cmdline_mock.assert_called_once()
        write_mock.assert_called_once_with("my_command", timeout=30)
        rc_mock.assert_called_once_with(timeout=30)

    def test_fire_and_forget(self, telnet, mocker, caplog):
        caplog.set_level(DEBUG)
        prepare_cmdline_mock = mocker.patch.object(telnet, "_prepare_cmdline")
        write_mock = mocker.patch.object(telnet, "_write_to_console")
        telnet.fire_and_forget("my_command")
        prepare_cmdline_mock.assert_called_once()
        write_mock.assert_called_once_with("my_command", timeout=0, fire_and_forget=True)
        assert "Executing 'my_command'" in caplog.text
        assert "Command 'my_command' executed in fire-and-forget mode" in caplog.text

    def test_not_implemented(self, telnet):
        with pytest.raises(NotImplementedError, match="Not implemented in Telnet"):
            telnet.restart_platform()
        with pytest.raises(NotImplementedError, match="Not implemented in Telnet"):
            telnet.shutdown_platform()
        with pytest.raises(NotImplementedError, match="Not implemented in Telnet"):
            telnet.wait_for_host()

    def test_disconnect(self, telnet, caplog):
        caplog.set_level(log_levels.MODULE_DEBUG)
        telnet.disconnect()
        assert "Disconnect is not required for Telnet connection." in caplog.text

    def test_get_output_after_user_action_selected_found(self, telnet):
        telnet.console.read.return_value.decode.return_value = telnet_output
        output = telnet.get_output_after_user_action(selected_option=True)
        assert output == "<Standard English>"

    def test_wait_for_string(self, telnet, mocker):
        found_index = 1
        telnet.console.expect.return_value = found_index, mocker.ANY, ""
        assert telnet.wait_for_string(string_list=["string"], expect_timeout=False) == found_index

    @pytest.mark.parametrize("buffer", ["some text", None])
    def test_wait_for_string_not_found(self, telnet, mocker, caplog, buffer):
        caplog.set_level(log_levels.MODULE_DEBUG)
        found_index = -1
        telnet.console.expect.return_value = found_index, mocker.ANY, buffer
        with pytest.raises(TelnetException):
            telnet.wait_for_string(string_list=["string"], expect_timeout=False)
            assert "Timeout exceeded" in caplog.text
            if buffer:
                assert f"Raw data: {buffer}" in caplog.text
        assert telnet.wait_for_string(string_list=["string"], expect_timeout=True) == -1

    @pytest.mark.parametrize("type_options", [None, OSType.EFISHELL])
    def test_get_os_bitness_os_not_supported(self, telnet, type_options, mocker):
        telnet.get_os_type = mocker.create_autospec(telnet.get_os_type, return_value=type_options)
        with pytest.raises(OsNotSupported):
            telnet.get_os_bitness()

    @pytest.mark.parametrize("type_options", [OSType.WINDOWS, OSType.POSIX])
    @pytest.mark.parametrize("architecture_options", ["dunno"])
    def test_get_os_bitness_os_arch_not_supported(self, telnet, type_options, architecture_options, mocker):
        telnet.get_os_type = mocker.create_autospec(telnet.get_os_type, return_value=type_options)
        telnet.execute_command = Mock(
            return_value=ConnectionCompletedProcess(
                return_code=0, args="command", stdout=architecture_options, stderr="stderr"
            )
        )
        with pytest.raises(OsNotSupported):
            telnet.get_os_bitness()

    @pytest.mark.parametrize("type_options", [OSType.WINDOWS, OSType.POSIX])
    @pytest.mark.parametrize("architecture_options", ["amd64", "ia64", "x86_64"])
    def test_get_os_bitness_os_supported_64bit(self, telnet, type_options, architecture_options, mocker):
        telnet.get_os_type = mocker.create_autospec(telnet.get_os_type, return_value=type_options)
        telnet.execute_command = Mock(
            return_value=ConnectionCompletedProcess(
                return_code=0, args="command", stdout=architecture_options, stderr="stderr"
            )
        )
        assert telnet.get_os_bitness() == OSBitness.OS_64BIT

    @pytest.mark.parametrize("type_options", [OSType.WINDOWS, OSType.POSIX])
    @pytest.mark.parametrize("architecture_options", ["i386", "i586", "x86", "ia32", "armv7l", "arm"])
    def test_get_os_bitness_os_supported_32bit(self, telnet, type_options, architecture_options, mocker):
        telnet.get_os_type = mocker.create_autospec(telnet.get_os_type, return_value=type_options)
        telnet.execute_command = Mock(
            return_value=ConnectionCompletedProcess(
                return_code=0, args="command", stdout=architecture_options, stderr="stderr"
            )
        )
        assert telnet.get_os_bitness() == OSBitness.OS_32BIT

    @pytest.mark.parametrize("type_options", [OSType.WINDOWS, OSType.POSIX])
    def test_get_os_bitness_os_supported_aarch64(self, telnet, type_options, mocker):
        telnet.get_os_type = mocker.create_autospec(telnet.get_os_type, return_value=type_options)
        telnet.execute_command = Mock(
            return_value=ConnectionCompletedProcess(return_code=0, args="command", stdout="aarch64", stderr="stderr")
        )
        assert telnet.get_os_bitness() == OSBitness.OS_64BIT

    @pytest.mark.parametrize("type_options", [OSType.WINDOWS, OSType.POSIX])
    def test_get_os_bitness_os_supported_non_expected_bitness(self, telnet, type_options, mocker):
        telnet.get_os_type = mocker.create_autospec(telnet.get_os_type, return_value=type_options)
        telnet.execute_command = Mock(
            return_value=ConnectionCompletedProcess(return_code=0, args="command", stdout="2-bit", stderr="stderr")
        )
        with pytest.raises(OsNotSupported):
            telnet.get_os_bitness()

    cwd_test_params = {"random_name": "1231", "command_to_send": "ls", "cwd_folder": "folder"}
