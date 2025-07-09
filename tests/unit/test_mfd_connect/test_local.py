# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
from subprocess import CompletedProcess, PIPE, DEVNULL, STDOUT, CalledProcessError
from types import ModuleType

from netaddr import IPAddress

import pytest
from mfd_typing.os_values import OSType, OSName


import mfd_connect
from mfd_connect.exceptions import ConnectionCalledProcessError, OsNotSupported
from mfd_connect.local import LocalConnection, LocalProcess, POSIXLocalProcess


class TestLocalConnection:
    class_under_test = LocalConnection
    CustomTestException = CalledProcessError

    @pytest.fixture
    def local_conn(self):
        local_conn = self.class_under_test.__new__(self.class_under_test)
        local_conn._ip = IPAddress("127.0.0.1")
        local_conn._os_name = OSName.WINDOWS
        local_conn._default_timeout = None
        local_conn._cache_system_data = True
        local_conn._cached_os_type = None
        local_conn._LocalConnection__use_sudo = False
        yield local_conn

    @pytest.fixture
    def local_conn_with_process_cls(self, local_conn):
        local_conn._os_type = local_conn._cached_os_type = OSType.POSIX
        local_conn._process_class = POSIXLocalProcess
        yield local_conn

    @pytest.fixture
    def subprocess_run(self, mocker):
        return mocker.patch.object(mfd_connect.local, "run")

    @pytest.fixture
    def subprocess_popen(self, mocker):
        return mocker.patch.object(mfd_connect.local, "Popen")

    def test_execute_command_should_raise_when_returned_unexpected_exit_status_default(
        self, local_conn, subprocess_run, mocker
    ):
        mocker.patch.object(local_conn, "get_os_name", return_value="os_name")
        subprocess_run.return_value = CompletedProcess("cmd arg1 arg2", returncode=1)
        with pytest.raises(ConnectionCalledProcessError):
            _ = local_conn.execute_command(command="cmd arg1 arg2")

    def test_execute_command_should_raise_when_returned_unexpected_exit_status_custom(
        self, local_conn, subprocess_run, mocker
    ):
        mocker.patch.object(local_conn, "get_os_name", return_value="os_name")
        subprocess_run.return_value = CompletedProcess("cmd arg1 arg2", returncode=0)
        with pytest.raises(ConnectionCalledProcessError):
            _ = local_conn.execute_command(command="cmd arg1 arg2", expected_return_codes={1, 2})

    def test_execute_command_should_not_raise_when_returned_expected_exit_status_default(
        self, local_conn, subprocess_run, mocker
    ):
        mocker.patch.object(local_conn, "get_os_name", return_value="os_name")
        completed_process = CompletedProcess("cmd arg1 arg2", returncode=0)
        subprocess_run.return_value = completed_process
        try:
            _ = local_conn.execute_command("cmd arg1 arg2")
        except ConnectionCalledProcessError:
            pytest.fail("Unexpected ConnectionCalledProcessError has been raised.")

    def test_execute_command_should_not_raise_when_returned_expected_exit_status_custom(
        self, local_conn, subprocess_run, mocker
    ):
        mocker.patch.object(local_conn, "get_os_name", return_value="os_name")
        completed_process = CompletedProcess("cmd arg1 arg2", returncode=1)
        subprocess_run.return_value = completed_process
        try:
            _ = local_conn.execute_command("cmd arg1 arg2", expected_return_codes={1})
        except ConnectionCalledProcessError:
            pytest.fail("Unexpected ConnectionCalledProcessError has been raised.")

    def test_execute_command_skip_logging_provided(self, local_conn, subprocess_run, mocker, caplog):
        caplog.set_level(0)
        mocker.patch.object(local_conn, "get_os_name", return_value="os_name")
        cmd = "cmd arg1 arg2"
        stdout = "someout"
        stderr = "someerr"
        completed_process = CompletedProcess(
            cmd, stdout=bytes(stdout, encoding="UTF-8"), stderr=bytes(stderr, encoding="UTF-8"), returncode=0
        )
        subprocess_run.return_value = completed_process
        local_conn.execute_command(cmd, skip_logging=True)
        assert not any(stdout in msg or stderr in msg for msg in caplog.messages)

        local_conn.execute_command(cmd, skip_logging=False)
        assert len([msg for msg in caplog.messages if stdout in msg or stderr in msg]) == 2  # stdout + stderr log

    def test_start_process_default(self, local_conn_with_process_cls, subprocess_popen):
        lprocess = local_conn_with_process_cls.start_process("command arg1 arg2")

        subprocess_popen.assert_called_once_with(
            ["command", "arg1", "arg2"],
            stdout=PIPE,
            stderr=PIPE,
            stdin=DEVNULL,
            encoding="utf-8",
            shell=False,
            errors="backslashreplace",
            cwd=None,
            env=None,
        )
        assert isinstance(lprocess, LocalProcess)

    def test_start_process_shell(self, local_conn_with_process_cls, subprocess_popen, mocker):
        lprocess = local_conn_with_process_cls.start_process("command arg1 arg2", shell=mocker.sentinel.shell)

        subprocess_popen.assert_called_once_with(
            "command arg1 arg2",
            stdout=PIPE,
            stderr=PIPE,
            stdin=DEVNULL,
            encoding="utf-8",
            shell=mocker.sentinel.shell,
            errors="backslashreplace",
            cwd=None,
            env=None,
        )
        assert isinstance(lprocess, LocalProcess)

    def test_start_process_env(self, local_conn_with_process_cls, subprocess_popen, mocker):
        lprocess = local_conn_with_process_cls.start_process("command arg1 arg2", env=mocker.sentinel.altered_env)

        subprocess_popen.assert_called_once_with(
            ["command", "arg1", "arg2"],
            stdout=PIPE,
            stderr=PIPE,
            stdin=DEVNULL,
            encoding="utf-8",
            shell=False,
            errors="backslashreplace",
            cwd=None,
            env=mocker.sentinel.altered_env,
        )
        assert isinstance(lprocess, LocalProcess)

    def test_start_process_stdin(self, local_conn_with_process_cls, subprocess_popen, mocker):
        lprocess = local_conn_with_process_cls.start_process(
            "command arg1 arg2", cwd=mocker.sentinel.cwd, env=mocker.sentinel.env, enable_input=True
        )

        subprocess_popen.assert_called_once_with(
            ["command", "arg1", "arg2"],
            cwd=mocker.sentinel.cwd,
            env=mocker.sentinel.env,
            stdout=PIPE,
            stderr=PIPE,
            stdin=PIPE,
            encoding="utf-8",
            shell=False,
            errors="backslashreplace",
        )
        assert isinstance(lprocess, LocalProcess)

    def test_start_process_affinity_posix(self, local_conn_with_process_cls, subprocess_popen):
        local_conn_with_process_cls._os_type = OSType.POSIX
        lprocess = local_conn_with_process_cls.start_process("command arg1 arg2", cpu_affinity=[1, 3, 7])

        subprocess_popen.assert_called_once_with(
            ["taskset", "0x8a", "command", "arg1", "arg2"],
            stdout=PIPE,
            stderr=PIPE,
            stdin=DEVNULL,
            encoding="utf-8",
            shell=False,
            errors="backslashreplace",
            cwd=None,
            env=None,
        )
        assert isinstance(lprocess, LocalProcess)

    @pytest.mark.parametrize(
        "io_arguments,expected_result",
        [
            (dict(stderr_to_stdout=True, discard_stdout=True, discard_stderr=True), (DEVNULL, DEVNULL)),
            (dict(stderr_to_stdout=True, discard_stdout=True, discard_stderr=False), (DEVNULL, STDOUT)),
            (dict(stderr_to_stdout=True, discard_stdout=False, discard_stderr=True), (PIPE, DEVNULL)),
            (dict(stderr_to_stdout=True, discard_stdout=False, discard_stderr=False), (PIPE, STDOUT)),
            (dict(stderr_to_stdout=False, discard_stdout=True, discard_stderr=True), (DEVNULL, DEVNULL)),
            (dict(stderr_to_stdout=False, discard_stdout=True, discard_stderr=False), (DEVNULL, PIPE)),
            (dict(stderr_to_stdout=False, discard_stdout=False, discard_stderr=True), (PIPE, DEVNULL)),
            (dict(stderr_to_stdout=False, discard_stdout=False, discard_stderr=False), (PIPE, PIPE)),
        ],
    )
    def test__resolve_process_output_arguments(self, local_conn, io_arguments, expected_result):
        assert local_conn._resolve_process_output_arguments(**io_arguments), expected_result

    def test_modules___getitem__(self, local_conn):
        assert isinstance(local_conn.modules()["os"], ModuleType)

    def test_modules___getattr__(self, local_conn):
        assert isinstance(local_conn.modules().os, ModuleType)

    def test_modules_no_module_installed___getitem__(self, local_conn):
        with pytest.raises(ModuleNotFoundError):
            local_conn.modules().not_existing_module

    def test_modules_no_module_installed___getattr__(self, local_conn):
        with pytest.raises(ModuleNotFoundError):
            local_conn.modules()["not_existing_module"]

    def test___init__assign_process_class(self, local_conn, mocker):
        local_conn.get_os_type = mocker.Mock(return_value=OSType.POSIX)
        local_conn.__init__()
        assert local_conn._process_class == POSIXLocalProcess

    def test___init__assign_process_class_when_os_type_not_listed_in_any_process_class(self, local_conn, mocker):
        local_conn.get_os_type = mocker.Mock(return_value="Different OS type")
        with pytest.raises(OsNotSupported):
            local_conn.__init__()

    def test_execute_command_raise_custom_exception(self, local_conn, subprocess_run):
        completed_process = CompletedProcess("cmd arg1 arg2", returncode=1)
        subprocess_run.return_value = completed_process
        with pytest.raises(self.CustomTestException):
            local_conn.execute_command("cmd arg1 arg2", custom_exception=self.CustomTestException)

    def test_execute_command_not_raise_custom_exception(self, local_conn, subprocess_run):
        completed_process = CompletedProcess("cmd arg1 arg2", returncode=0)
        subprocess_run.return_value = completed_process
        local_conn.execute_command("cmd arg1 arg2", custom_exception=self.CustomTestException)

    @pytest.mark.parametrize(
        "os_type, command, expected_split_command",
        [
            (OSType.POSIX, "/root/app -c -b 10", ["/root/app", "-c", "-b", "10"]),
            (OSType.WINDOWS, "c:\\tmp\\app.exe -c -b 10", ["c:\\tmp\\app.exe", "-c", "-b", "10"]),
        ],
    )
    def test_start_process_no_shell(self, local_conn, mocker, os_type, command, expected_split_command):
        popen_mock = mocker.patch("mfd_connect.local.Popen", mocker.Mock())
        local_conn._os_type = os_type
        local_conn._process_class = mocker.Mock(local_conn._process_class)
        local_conn._process_class.__call__().return_value = None
        local_conn.start_process(command)
        popen_mock.assert_called_with(
            expected_split_command,
            cwd=None,
            encoding="utf-8",
            env=None,
            errors="backslashreplace",
            shell=False,
            stderr=-1,
            stdin=-3,
            stdout=-1,
        )

    @pytest.mark.parametrize(
        "os_type, command, expected_split_command",
        [
            (OSType.POSIX, "/root/app -c -b 10", ["/root/app", "-c", "-b", "10"]),
            (OSType.WINDOWS, "c:\\tmp\\app.exe -c -b 10", ["c:\\tmp\\app.exe", "-c", "-b", "10"]),
        ],
    )
    def test_execute_command_no_shell(self, local_conn, mocker, os_type, command, expected_split_command):
        run_mock = mocker.patch(
            "mfd_connect.local.run", mocker.Mock(return_value=CompletedProcess(expected_split_command, returncode=0))
        )
        local_conn._os_type = os_type
        local_conn._process_class = mocker.Mock(local_conn._process_class)
        local_conn._process_class.__call__().return_value = None
        local_conn.execute_command(command)
        run_mock.assert_called_with(
            expected_split_command,
            input=None,
            cwd=None,
            timeout=None,
            env=None,
            shell=False,
            stdout=-1,
            stderr=-1,
            check=False,
        )

    def test_str_function(self, local_conn):
        assert str(local_conn) == "local"

    def test_ip_property(self, local_conn):
        assert local_conn.ip == IPAddress("127.0.0.1")

    def test_init_with_model(self):
        model = "mocker.Mock()"
        obj = LocalConnection(model=model)
        assert obj.model == model
        obj = self.class_under_test()
        assert obj.model is None

    def test__get_commands(self, local_conn):
        cmd = "ping -t 127.0.0.1 | tee k_log.txt"
        assert local_conn._get_commands(cmd) == ["ping -t 127.0.0.1", "tee k_log.txt"]

    def test__get_commands_or_operator(self, local_conn):
        cmd = "ping -t 127.0.0.1 || tee k_log.txt"
        assert local_conn._get_commands(cmd) == ["ping -t 127.0.0.1 || tee k_log.txt"]

    def test_start_processes_returned_processes(self, local_conn_with_process_cls, subprocess_popen):
        processes = local_conn_with_process_cls.start_processes("ping -t 127.0.0.1 | tee k_log.txt", shell=True)

        assert isinstance(processes[0], LocalProcess)
        assert isinstance(processes[1], LocalProcess)

    def test_start_processes_stdout_stdin_pipes(self, local_conn_with_process_cls, subprocess_popen):
        processes = local_conn_with_process_cls.start_processes("ping -t 127.0.0.1 | tee k_log.txt", shell=True)

        assert processes[0].stdout_stream == processes[1].stdout_stream
        assert processes[0].stdin_stream == processes[1].stdin_stream

    def test_start_processes_popen_call_count(self, local_conn_with_process_cls, subprocess_popen):
        local_conn_with_process_cls.start_processes("ping -t 127.0.0.1 | tee k_log.txt", shell=True)

        assert subprocess_popen.call_count == 2

    def test_execute_powershell_raise_custom_exception(self, local_conn, subprocess_run):
        completed_process = CompletedProcess(
            'powershell.exe -OutPutFormat Text -nologo -noninteractive "$host.UI.RawUI.BufferSize = '
            'new-object System.Management.Automation.Host.Size(512,3000);cmd arg1 arg 2"',
            returncode=1,
        )
        subprocess_run.return_value = completed_process
        local_conn.path_extension = None
        with pytest.raises(self.CustomTestException):
            local_conn.execute_powershell(
                "cmd arg1 arg 2",
                custom_exception=self.CustomTestException,
            )

    def test_execute_powershell_not_raise_custom_exception(self, local_conn, subprocess_run):
        completed_process = CompletedProcess(
            'powershell.exe -OutPutFormat Text -nologo -noninteractive "$host.UI.RawUI.BufferSize = '
            'new-object System.Management.Automation.Host.Size(512,3000);cmd arg1 arg 2"',
            returncode=0,
        )
        subprocess_run.return_value = completed_process
        local_conn.path_extension = None
        local_conn.execute_powershell(
            "cmd arg1 arg 2",
            custom_exception=self.CustomTestException,
        )

    def test_execute_powershell_outcome_check(self, local_conn, mocker):
        local_conn.modules = mocker.Mock()
        local_conn.execute_command = mocker.Mock()
        local_conn.path_extension = None
        local_conn.execute_powershell(
            "cmd arg1 arg 2", custom_exception=self.CustomTestException, expected_return_codes={0}
        )
        local_conn.execute_command.assert_called_with(
            command='powershell.exe -OutPutFormat Text -nologo -noninteractive "$host.UI.RawUI.BufferSize = '
            'new-object System.Management.Automation.Host.Size(512,3000);cmd arg1 arg 2"',
            custom_exception=self.CustomTestException,
            cwd=None,
            discard_stderr=False,
            discard_stdout=False,
            skip_logging=False,
            env=None,
            expected_return_codes={0},
            input_data=None,
            shell=False,
            stderr_to_stdout=False,
            timeout=None,
        )

    @pytest.fixture()
    def local_conn_with_timeout(self):
        local_conn = self.class_under_test.__new__(self.class_under_test)
        local_conn._ip = IPAddress("127.0.0.1")
        local_conn._os_name = OSName.WINDOWS
        local_conn.default_timeout = 1
        local_conn._cache_system_data = True
        local_conn._cached_os_type = None
        local_conn._LocalConnection__use_sudo = False
        yield local_conn

    def test_execute_with_timeout(self, local_conn_with_timeout, local_conn, mocker):
        local_conn_with_timeout._run_command = mocker.create_autospec(
            local_conn_with_timeout._run_command, return_value=CompletedProcess("ping localhost", returncode=0)
        )
        local_conn._run_command = mocker.create_autospec(
            local_conn._run_command, return_value=CompletedProcess("ping localhost", returncode=0)
        )
        local_conn_with_timeout.execute_command("ping localhost")
        local_conn.execute_command("ping localhost")

        local_conn_with_timeout._run_command.assert_called_with(
            ["ping", "localhost"], None, None, None, False, -1, -1, 1
        )
        local_conn._run_command.assert_called_with(["ping", "localhost"], None, None, None, False, -1, -1, None)

    def test__adjust_command(self, local_conn_with_process_cls):
        command = "command arg1 arg2"
        echo_command = "echo arg1"
        command_with_sudo = "sudo command arg1 arg2"
        echo_command_with_sudo = 'sudo sh -c "echo arg1"'
        assert local_conn_with_process_cls._adjust_command(command) == command
        local_conn_with_process_cls.enable_sudo()
        assert local_conn_with_process_cls._adjust_command(command) == command_with_sudo
        assert local_conn_with_process_cls._adjust_command(echo_command) == echo_command_with_sudo
        local_conn_with_process_cls.disable_sudo()

    def test_enable_sudo_posix(self, local_conn_with_process_cls, mocker):
        local_conn_with_process_cls._os_type = OSType.POSIX
        logger_mock = mocker.patch("mfd_connect.local.logger.log")
        local_conn_with_process_cls.enable_sudo()
        assert local_conn_with_process_cls._LocalConnection__use_sudo is True
        logger_mock.assert_called_once_with(
            level=mfd_connect.local.log_levels.MODULE_DEBUG, msg="Enabled sudo for command execution."
        )
        local_conn_with_process_cls.disable_sudo()

    def test_enable_sudo_non_posix(self, local_conn_with_process_cls):
        local_conn_with_process_cls._os_type = OSType.WINDOWS
        with pytest.raises(OsNotSupported):
            local_conn_with_process_cls.enable_sudo()

    def test_disable_sudo(self, local_conn_with_process_cls, mocker):
        local_conn_with_process_cls._LocalConnection__use_sudo = True
        logger_mock = mocker.patch("mfd_connect.local.logger.log")
        local_conn_with_process_cls.disable_sudo()
        assert local_conn_with_process_cls._LocalConnection__use_sudo is False
        logger_mock.assert_called_once_with(
            level=mfd_connect.local.log_levels.MODULE_DEBUG, msg="Disabled sudo for command execution."
        )
