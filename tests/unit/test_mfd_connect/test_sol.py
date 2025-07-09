# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
import sys
from subprocess import CalledProcessError
from textwrap import dedent

import pytest
from mfd_typing.os_values import OSBitness, OSType, OSName
from pytest import raises, fixture

from mfd_connect import SolConnection
from mfd_connect.base import ConnectionCompletedProcess
from mfd_connect.exceptions import OsNotSupported, SolException


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
