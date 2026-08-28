# Copyright (C) 2025-2026 Intel Corporation
# SPDX-License-Identifier: MIT
import sys
from subprocess import CalledProcessError
from textwrap import dedent

import pexpect
import pytest
from mfd_typing.os_values import OSBitness, OSType, OSName
from pytest import raises, fixture

from mfd_connect import SolConnection
from mfd_connect.base import ConnectionCompletedProcess
from mfd_connect.exceptions import OsNotSupported, SolException
from mfd_connect.util.serial_utils import SerialKeyCode


class TestSolConnection:
    """Tests of SolConnection."""

    CustomTestException = CalledProcessError

    @fixture
    def sol(self, mocker) -> SolConnection:
        sol = SolConnection.__new__(SolConnection)
        sol.__init__ = mocker.create_autospec(sol.__init__, return_value=None)
        sol._prompt = ""
        sol._ip = "10.10.10.10"
        sol.cache_system_data = True
        return sol

    def test_get_os_bitness_os_not_supported(self, sol, mocker):
        sol.execute_command = mocker.create_autospec(
            sol.execute_command,
            return_value=ConnectionCompletedProcess(
                return_code=0, args="command", stdout="random stuff", stderr="stderr"
            ),
        )
        with raises(OsNotSupported):
            print(sol.get_os_bitness())

    def test_get_os_bitness_os_supported(self, sol, mocker):
        real_correct_output = "Dell Custom UEFI Shell v2.2\nDell Build 2.6.1\nUEFI v2.70 (Dell Inc., 0x0A030201)"
        sol.execute_command = mocker.create_autospec(
            sol.execute_command,
            return_value=ConnectionCompletedProcess(
                return_code=0, args="command", stdout=real_correct_output, stderr="stderr"
            ),
        )
        assert sol.get_os_bitness() == OSBitness.OS_64BIT

    def test_get_cwd(self, sol, mocker):
        sol.execute_command = mocker.create_autospec(
            sol.execute_command,
            return_value=ConnectionCompletedProcess(
                return_code=0,
                args="command",
                stdout=r"uefiversion = 27.0\nscriptargc = 0\n    cwd = FS0:\569000",
                stderr="stderr",
            ),
        )
        assert sol.get_cwd() == r"FS0:\569000"

    def test_get_cwd_failure(self, sol, mocker):
        sol.execute_command = mocker.create_autospec(
            sol.execute_command,
            return_value=ConnectionCompletedProcess(
                return_code=0, args="command", stdout=r"uefiversion = 27.0\nscriptargc = 0\n", stderr="stderr"
            ),
        )
        with pytest.raises(SolException):
            sol.get_cwd()

    def test_execute_command_raise_custom_exception(self, sol, mocker):
        sol._send_to_shell = mocker.Mock()
        sol.wait_for_string = mocker.Mock()
        sol._clear_buffer = mocker.Mock()
        sol._get_return_code = mocker.Mock(return_value=1)
        with pytest.raises(self.CustomTestException):
            sol.execute_command(
                "cmd arg1 arg2",
                discard_stdout=True,
                expected_return_codes=[0],
                custom_exception=self.CustomTestException,
            )

    def test_execute_command_not_raise_custom_exception(self, sol, mocker):
        sol._send_to_shell = mocker.Mock()
        sol.wait_for_string = mocker.Mock()
        sol._clear_buffer = mocker.Mock()
        sol._get_return_code = mocker.Mock(return_value=0)
        sol.execute_command(
            "cmd arg1 arg2", discard_stdout=True, expected_return_codes=[0], custom_exception=self.CustomTestException
        )

    def test_clear_buffer_with_pending_output(self, sol, mocker):
        sol._connection_handle = mocker.Mock(before=b"pending output")

        sol._clear_buffer()

        sol._connection_handle.expect.assert_called_once()

    def test_wait_for_string_success(self, sol, mocker):
        sol._connection_handle = mocker.Mock()
        sol._connection_handle.expect.return_value = 0

        assert sol.wait_for_string(["ready"], expect_timeout=True, timeout=1) == 0
        sol._connection_handle.expect.assert_called_once()

    def test_get_output_after_user_action(self, sol, mocker):
        sol._connection_handle = mocker.Mock(before=b"raw console output")
        sol.wait_for_string = mocker.Mock()
        parse_output = mocker.patch.object(sol, "_parse_output", return_value="parsed output")

        assert sol.get_output_after_user_action(selected_option=True) == "parsed output"
        parse_output.assert_called_once_with("raw console output", True)

    def test_send_key_sends_requested_times(self, sol, mocker):
        sol._connection_handle = mocker.Mock()
        sleep = mocker.patch("mfd_connect.sol.time.sleep")

        sol.send_key(SerialKeyCode.enter, count=2, sleeptime=0)

        assert sol._connection_handle.send.call_count == 2
        sleep.assert_called()

    def test_init_raises_on_windows(self, mocker):
        mocker.patch("mfd_connect.sol.platform.system", return_value="Windows")

        with pytest.raises(SolException, match="Windows is not supported as test controller, yet"):
            SolConnection(username="admin", password="secret", ip="10.10.10.10")

    def test_init_raises_when_ipmiutil_missing(self, mocker):
        mocker.patch("mfd_connect.sol.platform.system", return_value="Linux")
        mocker.patch("mfd_connect.sol.pexpect.popen_spawn.PopenSpawn", side_effect=FileNotFoundError("ipmiutil"))

        with pytest.raises(SolException):
            SolConnection(username="admin", password="secret", ip="10.10.10.10")

    def test_establish_connection_retries_once(self, sol, mocker):
        first_child = mocker.Mock()
        first_child.expect.return_value = 1
        second_child = mocker.Mock()
        second_child.expect.return_value = 0

        sol._ipmi_tool_name = "ipmiutil"
        sol._ipmi_parameters = "-F lan2 -U admin -P secret -N 10.10.10.10 -V 4"
        mocker.patch.object(sol, "_deactivate_sol_session")
        spawn = mocker.patch("mfd_connect.sol.pexpect.spawn", create=True, side_effect=[first_child, second_child])

        result = sol._establish_connection(retry_count=1)

        assert spawn.call_count == 2
        assert result is second_child

    def test_deactivate_sol_session_success_first_attempt(self, sol, mocker):
        sol._ipmi_tool_name = "ipmiutil"
        sol._ipmi_parameters = "-F lan2 -U admin -P secret -N 10.10.10.10 -V 4"
        child = mocker.Mock()
        child.expect.return_value = 0
        popen_spawn = mocker.patch("mfd_connect.sol.pexpect.popen_spawn.PopenSpawn", return_value=child)
        kill_mock = mocker.patch.object(sol, "_kill_defunct_ipmiutil_processes")

        sol._deactivate_sol_session()

        popen_spawn.assert_called_once()
        kill_mock.assert_not_called()

    def test_deactivate_sol_session_retries_after_timeout_then_succeeds(self, sol, mocker):
        sol._ipmi_tool_name = "ipmiutil"
        sol._ipmi_parameters = "-F lan2 -U admin -P secret -N 10.10.10.10 -V 4"
        first_child = mocker.Mock()
        first_child.expect.side_effect = pexpect.TIMEOUT("timed out")
        second_child = mocker.Mock()
        second_child.expect.return_value = 0
        popen_spawn = mocker.patch(
            "mfd_connect.sol.pexpect.popen_spawn.PopenSpawn", side_effect=[first_child, second_child]
        )
        kill_mock = mocker.patch.object(sol, "_kill_defunct_ipmiutil_processes")

        sol._deactivate_sol_session()

        assert popen_spawn.call_count == 2
        kill_mock.assert_not_called()

    def test_deactivate_sol_session_falls_back_to_kill_after_repeated_failures(self, sol, mocker):
        """Both attempts raise pexpect exceptions (defunct process) - the whole run must not crash."""
        sol._ipmi_tool_name = "ipmiutil"
        sol._ipmi_parameters = "-F lan2 -U admin -P secret -N 10.10.10.10 -V 4"
        first_child = mocker.Mock()
        first_child.expect.side_effect = pexpect.TIMEOUT("timed out")
        second_child = mocker.Mock()
        second_child.expect.side_effect = pexpect.EOF("eof")
        popen_spawn = mocker.patch(
            "mfd_connect.sol.pexpect.popen_spawn.PopenSpawn", side_effect=[first_child, second_child]
        )
        kill_mock = mocker.patch.object(sol, "_kill_defunct_ipmiutil_processes")

        sol._deactivate_sol_session()  # must not raise

        assert popen_spawn.call_count == 2
        kill_mock.assert_called_once()

    def test_kill_defunct_ipmiutil_processes_kills_found_pid(self, sol, mocker):
        sol._ipmi_tool_name = "ipmiutil"
        ps_child = mocker.Mock()
        ps_child.before = (
            b"berta     206865  0.0  0.3   9368  6700 pts/0    T    15:40   0:00 "
            b"ipmiutil sol -a -F lan2 -U      -P         -N 10.102.20.61 -V 4\n"
            b"berta     213349  0.0  0.1   6544  2392 pts/1    S+   16:00   0:00 grep --color=auto ipmiutil\n"
        )
        kill_child = mocker.Mock()
        popen_spawn = mocker.patch("mfd_connect.sol.pexpect.popen_spawn.PopenSpawn", side_effect=[ps_child, kill_child])

        sol._kill_defunct_ipmiutil_processes()

        assert popen_spawn.call_args_list[0].args[0] == "ps aux | grep ipmiutil"
        assert popen_spawn.call_args_list[1].args[0] == "sudo -n kill -KILL 206865"
        ps_child.expect.assert_called_once_with(pexpect.EOF)
        kill_child.expect.assert_called_once_with(pexpect.EOF)

    def test_kill_defunct_ipmiutil_processes_kills_multiple_pids(self, sol, mocker):
        """Mirrors real-world output: two stopped (T) ipmiutil sessions must both be killed."""
        sol._ipmi_tool_name = "ipmiutil"
        ps_child = mocker.Mock()
        ps_child.before = (
            b"berta     206865  0.0  0.3   9368  6700 pts/0    T    15:40   0:00 "
            b"ipmiutil sol -a -F lan2 -U      -P         -N 10.102.20.61 -V 4\n"
            b"berta     210671  0.0  0.3   9368  6644 pts/0    T    15:52   0:00 "
            b"ipmiutil sol -a -F lan2 -U      -P         -N 10.102.20.61 -V 4\n"
            b"berta     213349  0.0  0.1   6544  2392 pts/1    S+   16:00   0:00 grep --color=auto ipmiutil\n"
        )
        kill_child_1 = mocker.Mock()
        kill_child_2 = mocker.Mock()
        popen_spawn = mocker.patch(
            "mfd_connect.sol.pexpect.popen_spawn.PopenSpawn",
            side_effect=[ps_child, kill_child_1, kill_child_2],
        )

        sol._kill_defunct_ipmiutil_processes()

        assert popen_spawn.call_args_list[1].args[0] == "sudo -n kill -KILL 206865"
        assert popen_spawn.call_args_list[2].args[0] == "sudo -n kill -KILL 210671"

    def test_kill_defunct_ipmiutil_processes_kills_only_stopped_ones(self, sol, mocker):
        """Mix of stopped (T) and healthy (S+) processes - only the stopped one gets killed."""
        sol._ipmi_tool_name = "ipmiutil"
        ps_child = mocker.Mock()
        ps_child.before = (
            b"berta     206865  0.0  0.3   9368  6700 pts/0    T    15:40   0:00 "
            b"ipmiutil sol -a -F lan2 -U      -P         -N 10.102.20.61 -V 4\n"
            b"berta     220000  0.0  0.3   9368  6700 pts/0    S+   15:41   0:00 "
            b"ipmiutil sol -a -F lan2 -U      -P         -N 10.102.20.62 -V 4\n"
            b"berta     213349  0.0  0.1   6544  2392 pts/1    S+   16:00   0:00 grep --color=auto ipmiutil\n"
        )
        kill_child = mocker.Mock()
        popen_spawn = mocker.patch("mfd_connect.sol.pexpect.popen_spawn.PopenSpawn", side_effect=[ps_child, kill_child])

        sol._kill_defunct_ipmiutil_processes()

        assert popen_spawn.call_count == 2  # ps aux + single kill (healthy one skipped)
        assert popen_spawn.call_args_list[1].args[0] == "sudo -n kill -KILL 206865"

    def test_kill_defunct_ipmiutil_processes_raises_when_no_pid_found(self, sol, mocker):
        sol._ipmi_tool_name = "ipmiutil"
        ps_child = mocker.Mock()
        ps_child.before = b"user     3333  0.0  0.1  1  1  pts/0  S+  12:00  0:00 grep ipmiutil\n"
        mocker.patch("mfd_connect.sol.pexpect.popen_spawn.PopenSpawn", return_value=ps_child)

        with pytest.raises(SolException):
            sol._kill_defunct_ipmiutil_processes()

    def test_kill_defunct_ipmiutil_processes_raises_when_ps_times_out(self, sol, mocker):
        sol._ipmi_tool_name = "ipmiutil"
        ps_child = mocker.Mock()
        ps_child.expect.side_effect = pexpect.TIMEOUT("timed out")
        mocker.patch("mfd_connect.sol.pexpect.popen_spawn.PopenSpawn", return_value=ps_child)

        with pytest.raises(SolException):
            sol._kill_defunct_ipmiutil_processes()

    def test_kill_defunct_ipmiutil_processes_raises_when_kill_fails(self, sol, mocker):
        sol._ipmi_tool_name = "ipmiutil"
        ps_child = mocker.Mock()
        ps_child.before = (
            b"berta     206865  0.0  0.3   9368  6700 pts/0    T    15:40   0:00 "
            b"ipmiutil sol -a -F lan2 -U      -P         -N 10.102.20.61 -V 4\n"
        )
        kill_child = mocker.Mock()
        kill_child.expect.side_effect = pexpect.TIMEOUT("timed out")
        mocker.patch("mfd_connect.sol.pexpect.popen_spawn.PopenSpawn", side_effect=[ps_child, kill_child])

        with pytest.raises(SolException):
            sol._kill_defunct_ipmiutil_processes()

    def test__parse_selection_regex_fallback_blue_background(self):
        output = "\x1b[44mSelected Boot Option"

        selected = SolConnection._parse_selection_regex_fallback(False, output)

        assert selected == "Selected Boot Option"

    def test__parse_selection_regex_fallback_grey_background_legacy(self):
        output = "\x1b[47m\x1b*Legacy Boot Option"

        selected = SolConnection._parse_selection_regex_fallback(True, output)

        assert selected == "*Legacy Boot Option"

    def test__parse_output(self, sol):
        output = (
            ", use '~.' to end, '~?' for help.]\r\r\n"
            "[25;30H\r\r\n"
            "\r\r\n"
            "\r\r\n"
            "\r\r\n"
            "Intel(R) Ethernet Flash Firmware Utility\r\r\n"
            "\r\r\n"
            "BootUtil version 1.7.11.7\r\r\n"
            "\r\r\n"
            r"[25;01H[1m[33m[40mFS0:\560559"
        )
        expected_output = dedent(
            """\
        Intel(R) Ethernet Flash Firmware Utility
        BootUtil version 1.7.11.7"""
        )
        assert sol._parse_output(output) == expected_output

    def test__parse_selection_windows_boot_manager(self, sol):
        output = (
            "\x1b[7;2H \x1b[7;6HWin2022_wRelease30.1.2RefDrv"
            "\x1b[6;2H \x1b[0m\x1b[30;47m \x1b[6;6HWindows2022_Release30.2_Reference"
            "\x1b[6;72H>\x1b[0m\x1b[37;40m"
        )

        selected = sol._parse_output(output, selection=True)

        assert "Windows2022_Release30.2_Reference" in selected

    def test__parse_selection_legacy_highlight(self, sol):
        output = "\x1b[44m*Legacy Boot Option\x1b[0m"

        selected = sol._parse_output(output, selection=True, legacy=True)

        assert "*Legacy Boot Option" in selected

    def test__parse_selection_preos_continue_normal_boot(self):
        output_to_parse = (
            "\x1b[09;01H\x1b[1m\x1b[37m\x1b[40m\x1b[09;01H  "
            "\x1b[1m\x1b[37m\x1b[44mContinue Normal Boot"
            "\x1b[10;01H\x1b[1m\x1b[37m\x1b[40m\x1b[10;01H  One-shot UEFI Boot Menu"
        )

        selected = SolConnection._parse_selection(False, output_to_parse)

        assert selected == "Continue Normal Boot"

    def test__check_if_unix(self, sol, mocker):
        sol.execute_command = mocker.create_autospec(
            sol.execute_command,
            return_value=ConnectionCompletedProcess(
                return_code=0,
                args="command",
                stdout=r"Linux localhost.localdomain 5.3.15-200.fc30.x86_64 #1 SMP "
                r"Thu Dec 5 15:18:00 UTC 2019 x86_64 x86_64 x86_64 GNU/Linux",
                stderr="stderr",
            ),
        )
        assert sol._check_if_unix()

    def test__check_if_unix_failure(self, sol, mocker):
        sol.execute_command = mocker.create_autospec(
            sol.execute_command,
            return_value=ConnectionCompletedProcess(
                return_code=9009,
                args="command",
                stdout=r"\'uname\' is not recognized as an internal or external command,"
                r"\noperable program or batch file.",
                stderr="stderr",
            ),
        )
        assert not sol._check_if_unix()

    def test__check_if_efi_shell(self, sol, mocker):
        sol.execute_command = mocker.create_autospec(
            sol.execute_command,
            return_value=ConnectionCompletedProcess(
                return_code=0,
                args="command",
                stdout=r"DELL Custom UEFI Shell v2.2\nDell Build 2.6.1" r"\nUEFI v2.70 (Dell Inc., 0x0A030201)",
                stderr="stderr",
            ),
        )
        assert sol._check_if_efi_shell()

    def test__check_if_efi_shell_interactive_mode(self, sol, mocker):
        sol.execute_command = mocker.create_autospec(
            sol.execute_command,
            return_value=ConnectionCompletedProcess(
                return_code=0,
                args="command",
                stdout=r"UEFI Interactive Shell v2.2\nEDK II\nUEFI v2.70 (Dell Inc., 0x05030201)",
                stderr="stderr",
            ),
        )
        assert sol._check_if_efi_shell()

    def test__check_if_efi_shell_failure(self, sol, mocker):
        sol.execute_command = mocker.create_autospec(
            sol.execute_command,
            return_value=ConnectionCompletedProcess(
                return_code=0,
                args="command",
                stdout=r"\nMicrosoft Windows [Version 10.0.18363.1440]\n",
                stderr="stderr",
            ),
        )
        assert not sol._check_if_efi_shell()

    def test_get_os_type_unix(self, sol, mocker):
        sol.execute_command = mocker.create_autospec(
            sol.execute_command,
            return_value=ConnectionCompletedProcess(
                return_code=0,
                args="command",
                stdout=r"Linux localhost.localdomain 5.3.15-200.fc30.x86_64 #1 SMP "
                r"Thu Dec 5 15:18:00 UTC 2019 x86_64 x86_64 x86_64 GNU/Linux",
                stderr="stderr",
            ),
        )
        assert sol.get_os_type() == OSType.POSIX

    def test_get_os_type_efi_shell(self, sol, mocker):
        def return_check_output(*args, **kwargs):
            if args[0] == "uname -a":
                return ConnectionCompletedProcess(
                    return_code=14,
                    args="command",
                    stdout=r"\'uname\' is not recognized as an internal or external "
                    r"command,\noperable program, or script file.",
                    stderr="stderr",
                )
            else:
                return ConnectionCompletedProcess(
                    return_code=0,
                    args="command",
                    stdout=r"DELL Custom UEFI Shell v2.2\nDell Build 2.6.1" r"\nUEFI v2.70 (Dell Inc., 0x0A030201)",
                    stderr="stderr",
                )

        sol.execute_command = mocker.Mock(side_effect=return_check_output)
        assert sol.get_os_type() == OSType.EFISHELL

    def test_get_os_type_failure(self, sol, mocker):
        def return_check_output(*args, **kwargs):
            if args[0] == "uname -a":
                return ConnectionCompletedProcess(
                    return_code=9009,
                    args="command",
                    stdout=r"\'uname\' is not recognized as an internal or external "
                    r"command\noperable program or batch file.",
                    stderr="stderr",
                )
            else:
                return ConnectionCompletedProcess(
                    return_code=0,
                    args="command",
                    stdout=r"\nMicrosoft Windows [Version 10.0.18363.1440]\n",
                    stderr="stderr",
                )

        sol.execute_command = mocker.Mock(side_effect=return_check_output)
        with pytest.raises(OsNotSupported):
            _ = sol.get_os_type()

    def test_get_os_name_linux(self, sol, mocker):
        def return_check_output(*args, **kwargs):
            if args[0] == "uname -o":
                return ConnectionCompletedProcess(
                    return_code=0,
                    args="command",
                    stdout=r"GNU/Linux",
                    stderr="stderr",
                )
            elif args[0] == "uname -a":
                return ConnectionCompletedProcess(
                    return_code=0,
                    args="command",
                    stdout=r"Linux localhost.localdomain 5.3.15-200.fc30.x86_64 #1 SMP "
                    r"Thu Dec 5 15:18:00 UTC 2019 x86_64 x86_64 x86_64 GNU/Linux",
                    stderr="stderr",
                )
            else:
                return ConnectionCompletedProcess(
                    return_code=0,
                    args="command",
                    stdout=r"bash: ver: command not found...",
                    stderr="stderr",
                )

        sol.execute_command = mocker.Mock(side_effect=return_check_output)
        assert sol.get_os_name() == OSName.LINUX

    def test_get_os_name_freebsd(self, sol, mocker):
        def return_check_output(*args, **kwargs):
            if args[0] == "uname -o":
                return ConnectionCompletedProcess(
                    return_code=0,
                    args="command",
                    stdout=r"FreeBSD",
                    stderr="stderr",
                )
            elif args[0] == "uname -a":
                return ConnectionCompletedProcess(
                    return_code=0,
                    args="command",
                    stdout=r"Linux localhost.localdomain 5.3.15-200.fc30.x86_64 #1 SMP "
                    r"Thu Dec 5 15:18:00 UTC 2019 x86_64 x86_64 x86_64 FreeBSD",
                    stderr="stderr",
                )
            else:
                return ConnectionCompletedProcess(
                    return_code=0,
                    args="command",
                    stdout=r"bash: ver: command not found...",
                    stderr="stderr",
                )

        sol.execute_command = mocker.Mock(side_effect=return_check_output)
        assert sol.get_os_name() == OSName.FREEBSD

    def test_get_os_name_efi_shell(self, sol, mocker):
        def return_check_output(*args, **kwargs):
            if args[0] == "uname -o":
                return ConnectionCompletedProcess(
                    return_code=14,
                    args="command",
                    stdout=r"\'uname\' is not recognized as an internal or external "
                    r"command,\noperable program, or script file.",
                    stderr="stderr",
                )
            elif args[0] == "uname -a":
                return ConnectionCompletedProcess(
                    return_code=9009,
                    args="command",
                    stdout=r"\'uname\' is not recognized as an internal or external "
                    r"command\noperable program or batch file.",
                    stderr="stderr",
                )
            else:
                return ConnectionCompletedProcess(
                    return_code=0,
                    args="command",
                    stdout=r"DELL Custom UEFI Shell v2.2\nDell Build 2.6.1" r"\nUEFI v2.70 (Dell Inc., 0x0A030201)",
                    stderr="stderr",
                )

        sol.execute_command = mocker.Mock(side_effect=return_check_output)
        assert sol.get_os_name() == OSName.EFISHELL

    def test_get_os_name_failure(self, sol, mocker):
        def return_check_output(*args, **kwargs):
            if args[0] == "uname -o":
                return ConnectionCompletedProcess(
                    return_code=9009,
                    args="command",
                    stdout=r"\'uname\' is not recognized as an internal or external "
                    r"command\noperable program or batch file.",
                    stderr="stderr",
                )
            elif args[0] == "uname -a":
                return ConnectionCompletedProcess(
                    return_code=9009,
                    args="command",
                    stdout=r"\'uname\' is not recognized as an internal or external "
                    r"command\noperable program or batch file.",
                    stderr="stderr",
                )
            else:
                return ConnectionCompletedProcess(
                    return_code=0,
                    args="command",
                    stdout=r"\nMicrosoft Windows [Version 10.0.18363.1440]\n",
                    stderr="stderr",
                )

        sol.execute_command = mocker.Mock(side_effect=return_check_output)
        with pytest.raises(OsNotSupported):
            _ = sol.get_os_name()

    @pytest.mark.parametrize("command_output, os_name", [("GNU/Linux", OSName.LINUX), ("FreeBSD", OSName.FREEBSD)])
    def test_get_unix_distribution(self, sol, mocker, command_output, os_name):
        sol.execute_command = mocker.create_autospec(
            sol.execute_command,
            return_value=ConnectionCompletedProcess(
                return_code=0,
                args="command",
                stdout=command_output,
                stderr="stderr",
            ),
        )
        assert sol._get_unix_distribution() == os_name

    def test_get_unix_distribution_fail(self, sol, mocker):
        sol.execute_command = mocker.create_autospec(
            sol.execute_command,
            return_value=ConnectionCompletedProcess(
                return_code=0,
                args="command",
                stdout="GNU/NetBSD",
                stderr="stderr",
            ),
        )
        with raises(OsNotSupported):
            _ = sol._get_unix_distribution()

    def test_str_function(self, sol):
        assert str(sol) == "sol"

    def test_ip_property(self, sol):
        assert sol.ip == "10.10.10.10"

    def test_path_python_312plus(self, monkeypatch, sol, mocker):
        # Simulate Python 3.12+
        sol._clear_buffer = mocker.Mock()
        monkeypatch.setattr(sys, "version_info", (3, 13, 0))
        cpf = mocker.patch("mfd_connect.sol.custom_path_factory", return_value="custom_path")
        result = sol.path("foo", bar=1)
        assert result == "custom_path"
        cpf.assert_called_once()
        # owner should be injected as self
        assert cpf.call_args.kwargs["owner"] is sol

    def test_path_python_pre312(self, monkeypatch, sol, mocker):
        # Simulate Python < 3.12
        monkeypatch.setattr(sys, "version_info", (3, 11, 0))
        cp = mocker.patch("mfd_connect.sol.CustomPath", return_value="custom_path")
        result = sol.path("foo", bar=1)
        assert result == "custom_path"
        cp.assert_called_once()
        # owner should be injected as self
        assert cp.call_args.kwargs["owner"] is sol
