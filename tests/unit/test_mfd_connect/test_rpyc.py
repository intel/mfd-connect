# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
import subprocess
import time
import types
from pathlib import Path
from subprocess import CompletedProcess, CalledProcessError
from unittest.mock import patch
from rpyc.core.service import ClassicService
import pytest
import rpyc as rpyc_module
from mfd_common_libs import log_levels
from mfd_typing.os_values import OSType, OSName

from mfd_connect import RPyCConnection
from mfd_connect.base import ConnectionCompletedProcess
from mfd_connect.exceptions import (
    ConnectionCalledProcessError,
    ModuleFrameworkDesignError,
    OsNotSupported,
    RPyCDeploymentException,
    RunAsUserError,
)
from mfd_connect.process.rpyc import PosixRPyCProcess, WindowsRPyCProcess, ESXiRPyCProcess


class TestRPyCConnection:
    """Tests of RPyCConnection."""

    CustomTestException = CalledProcessError

    @pytest.fixture()
    def rpyc(self, mocker):
        with patch.object(RPyCConnection, "__init__", return_value=None):
            conn = RPyCConnection(ip="10.10.10.10")
            conn._ip = "10.10.10.10"
            conn._os_type = conn._cached_os_type = OSType.POSIX
            conn._enable_bg_serving_thread = True
            conn._default_timeout = None
            conn._connection_timeout = 360
            conn.path_extension = None
            conn.cache_system_data = True
            conn._ipv6 = False
            return conn

    def test_wait_for_host(self, rpyc, mocker):
        rpyc._create_connection = mocker.Mock(side_effect=[OSError, OSError, rpyc_module.Connection])
        rpyc._connection = mocker.Mock()
        remote = mocker.patch("mfd_connect.RPyCConnection.remote", new_callable=mocker.PropertyMock)
        remote.return_value = rpyc_module.Connection
        mocker.patch("rpyc.BgServingThread", mocker.create_autospec(rpyc_module.BgServingThread))
        time.sleep = mocker.Mock(return_value=None)
        rpyc.wait_for_host(timeout=10)

    def test_wait_for_host_fail(self, rpyc, mocker):
        rpyc._create_connection = mocker.Mock(side_effect=OSError)
        time.sleep = mocker.Mock(return_value=None)
        with pytest.raises(TimeoutError):
            rpyc.wait_for_host(timeout=1)

    def test_wait_for_host_with_background_thread(self, rpyc, mocker):
        rpyc._os_type = OSType.WINDOWS
        rpyc._create_connection = mocker.Mock(side_effect=[OSError, OSError, rpyc_module.Connection])
        rpyc._connection = mocker.Mock()
        rpyc._background_serving_thread = mocker.Mock()
        remote = mocker.patch("mfd_connect.RPyCConnection.remote", new_callable=mocker.PropertyMock)
        bg_thread = mocker.patch("rpyc.BgServingThread")
        remote.return_value = rpyc_module.Connection
        time.sleep = mocker.Mock(return_value=None)
        rpyc.wait_for_host(timeout=10)
        bg_thread.assert_called_once()

    def test__send_command_and_disconnect_platform_with_drop(self, rpyc, mocker):
        time.sleep = mocker.Mock(return_value=None)
        rpyc._connection = mocker.Mock()
        rpyc.execute_command = mocker.Mock(side_effect=EOFError)
        rpyc._background_serving_thread = mocker.Mock()
        rpyc.send_command_and_disconnect_platform("")

    def test__send_command_and_disconnect_platform_fail(self, rpyc, mocker):
        time.sleep = mocker.Mock(return_value=None)
        rpyc._connection = mocker.Mock()
        e = ConnectionCalledProcessError(1, "ls")
        rpyc.execute_command = mocker.Mock(side_effect=e)
        rpyc._background_serving_thread = mocker.Mock()
        with pytest.raises(ConnectionCalledProcessError):
            rpyc.send_command_and_disconnect_platform("")

    def test__send_command_and_disconnect_platform_with_background_thread(self, rpyc, mocker):
        time.sleep = mocker.Mock(return_value=None)
        rpyc._connection = mocker.Mock()
        rpyc._background_serving_thread = mocker.Mock()
        rpyc.execute_command = mocker.Mock(side_effect=EOFError)
        rpyc.send_command_and_disconnect_platform("")
        rpyc._background_serving_thread.stop.assert_called_once()

    def test_execute_command_raise_custom_exception(self, rpyc, mocker):
        rpyc.get_os_name = mocker.create_autospec(rpyc.get_os_name)
        completed_process = CompletedProcess("cmd arg1 arg2", returncode=1)
        rpyc.modules = mocker.Mock()
        rpyc.modules().subprocess.run.return_value = completed_process
        rpyc.path_extension = None
        with pytest.raises(self.CustomTestException):
            rpyc.execute_command("cmd arg1 arg2", custom_exception=self.CustomTestException)

    def test_execute_command_not_raise_custom_exception(self, rpyc, mocker):
        rpyc.get_os_name = mocker.create_autospec(rpyc.get_os_name)
        completed_process = CompletedProcess("cmd arg1 arg2", returncode=0)
        rpyc.modules = mocker.Mock()
        rpyc.modules().subprocess.run.return_value = completed_process
        rpyc.path_extension = None
        rpyc.execute_command("cmd arg1 arg2", custom_exception=self.CustomTestException)

    def test_execute_command_input_data_provided(self, rpyc, mocker):
        rpyc.get_os_name = mocker.create_autospec(rpyc.get_os_name)
        completed_process = CompletedProcess("cmd arg1 arg2", returncode=0)
        rpyc.modules = mocker.Mock()
        rpyc.modules().subprocess.run.return_value = completed_process
        rpyc.path_extension = None
        rpyc.execute_command("cmd arg1 arg2", input_data="X\n")
        rpyc.modules().subprocess.run.assert_called_with(
            ["cmd", "arg1", "arg2"],
            input=b"X\n",
            cwd=None,
            timeout=None,
            env=None,
            shell=False,
            stdout=-1,
            stderr=-1,
            check=False,
            stdin=None,
        )

    def test_execute_command_skip_logging_provided(self, rpyc, mocker, caplog):
        caplog.set_level(0)
        cmd = "cmd arg1 arg2"
        stdout = "someout"
        stderr = "someerr"
        completed_process = CompletedProcess(
            cmd, stdout=bytes(stdout, encoding="UTF-8"), stderr=bytes(stderr, encoding="UTF-8"), returncode=0
        )
        rpyc.get_os_name = mocker.create_autospec(rpyc.get_os_name)
        rpyc.modules = mocker.Mock()
        rpyc.modules().subprocess.run.return_value = completed_process
        rpyc.path_extension = None
        rpyc.execute_command(cmd, skip_logging=True)
        assert not any(stdout in msg or stderr in msg for msg in caplog.messages)

        rpyc.execute_command(cmd, skip_logging=False)
        assert len([msg for msg in caplog.messages if stdout in msg or stderr in msg]) == 2  # stdout + stderr log

    def test_execute_with_timeout_passed_before_timeout(self, rpyc, mocker):
        posix_process = mocker.create_autospec(PosixRPyCProcess)
        type(posix_process).running = mocker.PropertyMock(return_value=False)

        rpyc.start_process = mocker.Mock(return_value=posix_process)
        rpyc._handle_execution_outcome = mocker.Mock()
        rpyc._log_execution_results = mocker.Mock()

        rpyc.execute_with_timeout(command="arg", timeout=5)

    def test_execute_with_timeout_timeout_reached(self, rpyc, mocker):
        rpyc._os_type = OSType.POSIX
        rpyc.modules = mocker.Mock()
        rpyc._resolve_process_output_arguments = mocker.create_autospec(
            rpyc._resolve_process_output_arguments, return_value=("", "")
        )
        rpyc._handle_path_extension = mocker.create_autospec(rpyc._handle_path_extension, return_value=None)
        rpyc._process_class = mocker.Mock(rpyc._process_class)
        rpyc._process_class.__call__().return_value = None
        time_mock = mocker.Mock()
        time_mock.return_value = 0
        with pytest.raises(TimeoutError):
            rpyc.execute_with_timeout(command="arg", timeout=1)

    def test_execute_with_timeout_raise_custom_exception(self, rpyc, mocker):
        posix_process = mocker.create_autospec(PosixRPyCProcess)
        type(posix_process).running = mocker.PropertyMock(return_value=False)
        type(posix_process).return_code = mocker.PropertyMock(return_value=1)
        type(posix_process).stdout_text = mocker.PropertyMock(return_value="ret")
        type(posix_process).stderr_text = mocker.PropertyMock(return_value="")

        rpyc.start_process = mocker.Mock(return_value=posix_process)
        rpyc._log_execution_results = mocker.Mock()

        with pytest.raises(self.CustomTestException):
            rpyc.execute_with_timeout(command="arg", timeout=5, custom_exception=self.CustomTestException)

    def test_execute_with_timeout_not_raise_custom_exception(self, rpyc, mocker):
        posix_process = mocker.create_autospec(PosixRPyCProcess)
        type(posix_process).running = mocker.PropertyMock(return_value=False)
        type(posix_process).return_code = mocker.PropertyMock(return_value=0)
        type(posix_process).stdout_text = mocker.PropertyMock(return_value="\nstd\nout\n")
        type(posix_process).stderr_text = mocker.PropertyMock(return_value="\nstd\nerr\n")

        rpyc.start_process = mocker.Mock(return_value=posix_process)
        rpyc._log_execution_results = mocker.Mock()

        actual = rpyc.execute_with_timeout(command="arg", timeout=5, custom_exception=self.CustomTestException)

        expected_output = ConnectionCompletedProcess(
            args="arg",
            stdout="\nstd\nout\n",
            stdout_bytes=b"\nstd\nout\n",
            stderr="\nstd\nerr\n",
            stderr_bytes=b"\nstd\nerr\n",
            return_code=0,
        )

        assert repr(actual) == repr(expected_output)

    def test_execute_powershell_raise_custom_exception(self, rpyc, mocker):
        completed_process = CompletedProcess(
            'powershell.exe -OutPutFormat Text -nologo -noninteractive "$host.UI.RawUI.BufferSize = '
            'new-object System.Management.Automation.Host.Size(512,3000);cmd arg1 arg 2"',
            returncode=1,
        )
        rpyc.get_os_name = mocker.create_autospec(rpyc.get_os_name)
        rpyc.modules = mocker.Mock()
        rpyc.modules().subprocess.run.return_value = completed_process
        rpyc.path_extension = None
        with pytest.raises(self.CustomTestException):
            rpyc.execute_powershell(
                "cmd arg1 arg 2",
                custom_exception=self.CustomTestException,
            )

    def test_execute_powershell_not_raise_custom_exception(self, rpyc, mocker):
        completed_process = CompletedProcess(
            'powershell.exe -OutPutFormat Text -nologo -noninteractive "$host.UI.RawUI.BufferSize = '
            'new-object System.Management.Automation.Host.Size(512,3000);cmd arg1 arg 2"',
            returncode=0,
        )
        rpyc.get_os_name = mocker.create_autospec(rpyc.get_os_name)
        rpyc.modules = mocker.Mock()
        rpyc.modules().subprocess.run.return_value = completed_process
        rpyc.path_extension = None
        rpyc.execute_command(
            'powershell.exe -OutPutFormat Text -nologo -noninteractive "$host.UI.RawUI.BufferSize = '
            'new-object System.Management.Automation.Host.Size(512,3000);cmd arg1 arg 2"',
            custom_exception=self.CustomTestException,
        )

    def test_execute_powershell_outcome_check(self, rpyc, mocker):
        rpyc.modules = mocker.Mock()
        rpyc.execute_command = mocker.Mock()
        rpyc.path_extension = None
        rpyc.execute_powershell("cmd arg1 arg 2", custom_exception=self.CustomTestException, expected_return_codes={0})
        rpyc.execute_command.assert_called_with(
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

    def test_ensure_remote_winapi_helper_missing_local_script(self, rpyc, mocker):
        mocker.patch("mfd_connect.rpyc.Path.exists", return_value=False)
        with pytest.raises(RunAsUserError, match="WinAPI helper script not found"):
            rpyc._ensure_remote_winapi_helper()

    def test_ensure_remote_winapi_helper_uploads_script(self, rpyc, mocker):
        mocker.patch("mfd_connect.rpyc.Path.exists", return_value=True)
        mocker.patch("mfd_connect.rpyc.Path.read_text", return_value="print('ok')")

        remote_os = mocker.Mock()
        remote_os.path.join.side_effect = lambda *parts: "\\".join(parts)
        remote_tempfile = mocker.Mock()
        remote_tempfile.gettempdir.return_value = "C:\\Temp"
        remote_tempfile.mkstemp.return_value = (11, "C:\\Temp\\mfd_connect\\runas.py")
        remote_pathlib = mocker.Mock()
        remote_modules = mocker.Mock(os=remote_os, tempfile=remote_tempfile, pathlib=remote_pathlib)
        rpyc.modules = mocker.Mock(return_value=remote_modules)

        remote_path = mocker.Mock()
        remote_pathlib.Path.return_value = remote_path

        helper_path = rpyc._ensure_remote_winapi_helper()

        assert helper_path == "C:\\Temp\\mfd_connect\\runas.py"
        remote_pathlib.Path.assert_any_call("C:\\Temp\\mfd_connect")
        remote_pathlib.Path.assert_any_call("C:\\Temp\\mfd_connect\\runas.py")
        remote_os.close.assert_called_once_with(11)
        remote_path.write_text.assert_called_once_with("print('ok')", encoding="utf-8")

    def test_execute_command_as_user_dispatch_windows(self, rpyc, mocker):
        rpyc._os_type = OSType.WINDOWS
        rpyc._execute_command_as_user_windows = mocker.Mock(return_value="done")

        result = rpyc.execute_command_as_user(command="whoami", user="john", password="pwd")

        assert result == "done"
        rpyc._execute_command_as_user_windows.assert_called_once()

    def test_execute_command_as_user_not_supported(self, rpyc):
        rpyc._os_type = OSType.POSIX
        with pytest.raises(OsNotSupported, match="Run-as-user execution is not supported"):
            rpyc.execute_command_as_user(command="whoami", user="john", password="pwd")

    def test_execute_command_as_user_windows_success_flow(self, rpyc, mocker):
        rpyc._os_type = OSType.WINDOWS
        rpyc._ip = "10.10.10.10"
        rpyc._default_timeout = 11
        rpyc._ensure_remote_winapi_helper = mocker.Mock(return_value="C:\\Temp\\runas.py")

        path_objects = {}
        file_bytes = {
            "C:\\Users\\john\\AppData\\Local\\Temp\\mfd_runas_1\\stdout.bin": b"std-out",
            "C:\\Users\\john\\AppData\\Local\\Temp\\mfd_runas_1\\stderr.bin": b"",
        }

        def _path_object(path):
            if path not in path_objects:
                obj = mocker.Mock()
                obj.write_text = mocker.Mock()
                obj.read_bytes = mocker.Mock(side_effect=lambda: file_bytes.get(path, b""))
                obj.read_text = mocker.Mock(return_value="3")
                path_objects[path] = obj
            return path_objects[path]

        remote_os = mocker.Mock()
        remote_os.path.join.side_effect = lambda *parts: "\\".join(parts)
        remote_os.path.isdir.return_value = True
        remote_os.path.exists.side_effect = lambda p: p in file_bytes
        remote_os.environ = {"SystemRoot": "C:\\Windows"}

        remote_tempfile = mocker.Mock()
        remote_tempfile.mkdtemp.return_value = "C:\\Users\\john\\AppData\\Local\\Temp\\mfd_runas_1"

        remote_pathlib = mocker.Mock()
        remote_pathlib.Path.side_effect = _path_object

        def _run_side_effect(cmd, **_kwargs):
            if isinstance(cmd, list) and cmd[0] == "python.exe":
                return CompletedProcess(args=cmd, returncode=0, stdout=b'{"ok": true, "returncode": 3}', stderr=b"")
            return CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

        remote_subprocess = mocker.Mock()
        remote_subprocess.run.side_effect = _run_side_effect

        remote_modules = types.SimpleNamespace(
            tempfile=remote_tempfile,
            os=remote_os,
            pathlib=remote_pathlib,
            subprocess=remote_subprocess,
            sys=types.SimpleNamespace(executable="python.exe"),
        )
        rpyc.modules = mocker.Mock(return_value=remote_modules)
        rpyc._handle_execution_outcome = mocker.Mock(return_value="handled")

        command = 'echo "hello world"'
        result = rpyc._execute_command_as_user_windows(
            command=command,
            user="john",
            password="secret",
            domain=".",
            env={"A": "B"},
            timeout=None,
            expected_return_codes={0, 3},
        )

        assert result == "handled"
        completed_process = rpyc._handle_execution_outcome.call_args.kwargs["completed_process"]
        assert completed_process.returncode == 3
        assert completed_process.stdout == b"std-out"
        assert completed_process.stderr == b""

        runner_bat_path = "C:\\Users\\john\\AppData\\Local\\Temp\\mfd_runas_1\\run_command_as_user.bat"
        runner_call = path_objects[runner_bat_path].write_text.call_args.args[0]
        assert command in runner_call
        assert "cmd.exe /d /s /c" not in runner_call

        helper_call = next(
            call
            for call in remote_subprocess.run.call_args_list
            if call.args and isinstance(call.args[0], list) and call.args[0][0] == "python.exe"
        )
        assert len(helper_call.args[0]) == 2
        assert "stdin" not in helper_call.kwargs
        assert isinstance(helper_call.kwargs["input"], bytes)

    def test_execute_command_as_user_windows_helper_error_falls_back_to_stderr(self, rpyc, mocker):
        rpyc._os_type = OSType.WINDOWS
        rpyc._ip = "10.10.10.10"
        rpyc._ensure_remote_winapi_helper = mocker.Mock(return_value="C:\\Temp\\runas.py")

        path_objects = {}

        def _path_object(path):
            if path not in path_objects:
                obj = mocker.Mock()
                obj.write_text = mocker.Mock()
                obj.read_bytes = mocker.Mock(return_value=b"")
                obj.read_text = mocker.Mock(return_value="not-an-int")
                path_objects[path] = obj
            return path_objects[path]

        remote_os = mocker.Mock()
        remote_os.path.join.side_effect = lambda *parts: "\\".join(parts)
        remote_os.path.isdir.return_value = False
        remote_os.path.exists.return_value = False
        remote_os.environ = {"SystemRoot": "C:\\Windows"}

        remote_tempfile = mocker.Mock()
        remote_tempfile.mkdtemp.return_value = "C:\\Windows\\Temp\\mfd_runas_2"

        remote_pathlib = mocker.Mock()
        remote_pathlib.Path.side_effect = _path_object

        def _run_side_effect(cmd, **_kwargs):
            if isinstance(cmd, list) and cmd[0] == "python.exe":
                payload = b'{"ok": false, "error": "CreateProcessWithLogonW failed"}'
                return CompletedProcess(args=cmd, returncode=0, stdout=payload, stderr=b"helper stderr")
            return CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

        remote_subprocess = mocker.Mock()
        remote_subprocess.run.side_effect = _run_side_effect

        remote_modules = types.SimpleNamespace(
            tempfile=remote_tempfile,
            os=remote_os,
            pathlib=remote_pathlib,
            subprocess=remote_subprocess,
            sys=types.SimpleNamespace(executable="python.exe"),
        )
        rpyc.modules = mocker.Mock(return_value=remote_modules)
        rpyc._handle_execution_outcome = mocker.Mock(return_value="handled")

        rpyc._execute_command_as_user_windows(
            command="echo hello",
            user="john",
            password="secret",
            timeout=1,
            expected_return_codes=None,
        )

        completed_process = rpyc._handle_execution_outcome.call_args.kwargs["completed_process"]
        assert completed_process.returncode == 1
        assert b"CreateProcessWithLogonW failed" in completed_process.stderr
        assert b"helper stderr" in completed_process.stderr

    def test_execute_command_as_user_windows_prefers_runner_return_code_file(self, rpyc, mocker):
        rpyc._os_type = OSType.WINDOWS
        rpyc._ip = "10.10.10.10"
        rpyc._default_timeout = 11
        rpyc._ensure_remote_winapi_helper = mocker.Mock(return_value="C:\\Temp\\runas.py")

        path_objects = {}

        def _path_object(path):
            if path not in path_objects:
                obj = mocker.Mock()
                obj.write_text = mocker.Mock()
                obj.read_bytes = mocker.Mock(return_value=b"Administrator privileges are needed to run application.")
                obj.read_text = mocker.Mock(return_value="1")
                path_objects[path] = obj
            return path_objects[path]

        remote_os = mocker.Mock()
        remote_os.path.join.side_effect = lambda *parts: "\\".join(parts)
        remote_os.path.isdir.return_value = True

        def _exists_side_effect(path):
            return path.endswith("stdout.bin") or path.endswith("stderr.bin") or path.endswith("return_code.txt")

        remote_os.path.exists.side_effect = _exists_side_effect
        remote_os.environ = {"SystemRoot": "C:\\Windows"}

        remote_tempfile = mocker.Mock()
        remote_tempfile.mkdtemp.return_value = "C:\\Users\\john\\AppData\\Local\\Temp\\mfd_runas_4"

        remote_pathlib = mocker.Mock()
        remote_pathlib.Path.side_effect = _path_object

        def _run_side_effect(cmd, **_kwargs):
            if isinstance(cmd, list) and cmd[0] == "python.exe":
                # Helper wrapper exits successfully but command rc persisted in file is 1.
                return CompletedProcess(args=cmd, returncode=0, stdout=b'{"ok": true, "returncode": 0}', stderr=b"")
            return CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

        remote_subprocess = mocker.Mock()
        remote_subprocess.run.side_effect = _run_side_effect

        remote_modules = types.SimpleNamespace(
            tempfile=remote_tempfile,
            os=remote_os,
            pathlib=remote_pathlib,
            subprocess=remote_subprocess,
            sys=types.SimpleNamespace(executable="python.exe"),
        )
        rpyc.modules = mocker.Mock(return_value=remote_modules)
        rpyc._handle_execution_outcome = mocker.Mock(return_value="handled")

        rpyc._execute_command_as_user_windows(
            command=r"C:\\NVMUPDATE\\Winx64\\nvmupdatew64e.exe -i -l",
            user="john",
            password="secret",
            domain=".",
            timeout=60,
            expected_return_codes={0, 1},
        )

        completed_process = rpyc._handle_execution_outcome.call_args.kwargs["completed_process"]
        assert completed_process.returncode == 1

    def test_execute_command_as_user_windows_no_timeout_keeps_helper_unbounded(self, rpyc, mocker):
        rpyc._os_type = OSType.WINDOWS
        rpyc._ip = "10.10.10.10"
        rpyc._default_timeout = None
        rpyc._ensure_remote_winapi_helper = mocker.Mock(return_value="C:\\Temp\\runas.py")

        path_objects = {}

        def _path_object(path):
            if path not in path_objects:
                obj = mocker.Mock()
                obj.write_text = mocker.Mock()
                obj.read_bytes = mocker.Mock(return_value=b"")
                obj.read_text = mocker.Mock(return_value="0")
                path_objects[path] = obj
            return path_objects[path]

        remote_os = mocker.Mock()
        remote_os.path.join.side_effect = lambda *parts: "\\".join(parts)
        remote_os.path.isdir.return_value = True
        remote_os.path.exists.return_value = False
        remote_os.environ = {"SystemRoot": "C:\\Windows"}

        remote_tempfile = mocker.Mock()
        remote_tempfile.mkdtemp.return_value = "C:\\Users\\john\\AppData\\Local\\Temp\\mfd_runas_3"

        remote_pathlib = mocker.Mock()
        remote_pathlib.Path.side_effect = _path_object

        def _run_side_effect(cmd, **_kwargs):
            if isinstance(cmd, list) and cmd[0] == "python.exe":
                return CompletedProcess(args=cmd, returncode=0, stdout=b'{"ok": true, "returncode": 0}', stderr=b"")
            return CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

        remote_subprocess = mocker.Mock()
        remote_subprocess.run.side_effect = _run_side_effect

        remote_modules = types.SimpleNamespace(
            tempfile=remote_tempfile,
            os=remote_os,
            pathlib=remote_pathlib,
            subprocess=remote_subprocess,
            sys=types.SimpleNamespace(executable="python.exe"),
        )
        rpyc.modules = mocker.Mock(return_value=remote_modules)
        rpyc._handle_execution_outcome = mocker.Mock(return_value="handled")

        rpyc._execute_command_as_user_windows(
            command="echo hello",
            user="john",
            password="secret",
            timeout=None,
            expected_return_codes={0},
        )

        helper_call = next(
            call
            for call in remote_subprocess.run.call_args_list
            if call.args and isinstance(call.args[0], list) and call.args[0][0] == "python.exe"
        )
        assert helper_call.kwargs["timeout"] is None

    def test_create_user_delegates_to_utility(self, rpyc, mocker):
        util_call = mocker.patch("mfd_connect.rpyc.create_user_util", return_value="created")

        result = rpyc.create_user("john", "pwd")

        assert result == "created"
        util_call.assert_called_once_with(
            connection=rpyc,
            username="john",
            password="pwd",
            expected_return_codes=frozenset({0}),
            custom_exception=None,
            skip_logging=False,
        )

    def test_delete_user_delegates_to_utility(self, rpyc, mocker):
        util_call = mocker.patch("mfd_connect.rpyc.delete_user_util", return_value="deleted")

        result = rpyc.delete_user("john")

        assert result == "deleted"
        util_call.assert_called_once_with(
            connection=rpyc,
            username="john",
            expected_return_codes=frozenset({0}),
            custom_exception=None,
            skip_logging=False,
        )

    @pytest.fixture()
    def prepared_rpyc(self, mocker):
        class PreparedRPyCConnection(RPyCConnection):
            pass

        mocker.patch("rpyc.BgServingThread", mocker.Mock())
        connection = mocker.create_autospec(rpyc_module.Connection)
        connection.closed = False
        PreparedRPyCConnection._create_connection = mocker.create_autospec(
            RPyCConnection._create_connection, return_value=connection
        )
        PreparedRPyCConnection.wait_for_host = mocker.create_autospec(RPyCConnection.wait_for_host)
        PreparedRPyCConnection.get_os_type = mocker.create_autospec(
            RPyCConnection.get_os_type, return_value=OSType.POSIX
        )
        PreparedRPyCConnection._os_type = OSType.POSIX
        PreparedRPyCConnection.get_os_name = mocker.create_autospec(
            RPyCConnection.get_os_name, return_value=OSName.LINUX
        )
        mocker.patch("mfd_connect.base.Connection.log_connected_host_info", mocker.Mock())
        return PreparedRPyCConnection

    def test__init__(self, prepared_rpyc):
        rpyc = prepared_rpyc("10.10.10.10")
        assert rpyc is not None
        assert rpyc._background_serving_thread is not None
        assert rpyc._process_class == PosixRPyCProcess
        assert rpyc._os_type == OSType.POSIX

    def test__init__port_selection(self, prepared_rpyc):
        rpyc = prepared_rpyc("10.10.10.10", port=12345)
        assert rpyc._port == 12345

    def test__init__port_selection_default(self, prepared_rpyc, mocker):
        mocker.patch("rpyc.__version__", "6.0.0")
        rpyc = prepared_rpyc("10.10.10.10")
        assert rpyc._port == 18816

    def test__init___with_tries(self, prepared_rpyc):
        rpyc = prepared_rpyc("10.10.10.10", retry_timeout=5, retry_time=10)
        rpyc.wait_for_host.assert_called_once_with(rpyc, timeout=5, retry_time=10)
        assert rpyc is not None
        assert rpyc._process_class == PosixRPyCProcess
        assert rpyc._os_type == OSType.POSIX

    def test_disconnect(self, prepared_rpyc, mocker):
        debug_mock = mocker.patch("mfd_connect.rpyc.logger.log", mocker.Mock())
        rpyc = prepared_rpyc("10.10.10.10")
        rpyc.remote
        rpyc.disconnect()
        rpyc._connection.close.assert_called_once()
        rpyc._background_serving_thread.stop.assert_called_once()
        debug_mock.assert_called_with(level=log_levels.MODULE_DEBUG, msg="Closing connection with 10.10.10.10")

    def test_disconnect_with_background_thread(self, prepared_rpyc, mocker):
        debug_mock = mocker.patch("mfd_connect.rpyc.logger.log", mocker.Mock())
        rpyc = prepared_rpyc("10.10.10.10")
        rpyc._background_serving_thread = mocker.Mock()
        rpyc.remote
        rpyc.disconnect()
        rpyc._connection.close.assert_called_once()
        rpyc._background_serving_thread.stop.assert_called_once()
        debug_mock.assert_called_with(level=log_levels.MODULE_DEBUG, msg="Closing connection with 10.10.10.10")

    def test_disconnect_failure_check(self, prepared_rpyc):
        rpyc = prepared_rpyc("10.10.10.10")
        rpyc.remote
        rpyc._connection.close.side_effect = Exception("Some exception")
        with pytest.raises(
            ModuleFrameworkDesignError, match="Exception occurred while closing connection: Some exception"
        ):
            rpyc.disconnect()
        rpyc._background_serving_thread.stop.assert_called_once()

    @pytest.mark.parametrize(
        "os_type, command, expected_split_command",
        [
            (OSType.POSIX, "/root/app -c -b 10", ["/root/app", "-c", "-b", "10"]),
            (OSType.WINDOWS, "c:\\tmp\\app.exe -c -b 10", ["c:\\tmp\\app.exe", "-c", "-b", "10"]),
        ],
    )
    def test_start_process_no_shell(self, rpyc, mocker, os_type, command, expected_split_command):
        rpyc._os_type = os_type
        rpyc.modules = mocker.Mock()
        rpyc._resolve_process_output_arguments = mocker.create_autospec(
            rpyc._resolve_process_output_arguments, return_value=("", "")
        )
        rpyc._handle_path_extension = mocker.create_autospec(rpyc._handle_path_extension, return_value=None)
        rpyc._process_class = mocker.Mock(rpyc._process_class)
        rpyc._process_class.__call__().return_value = None
        rpyc.start_process(command)
        rpyc.modules().subprocess.Popen.assert_called_with(
            expected_split_command,
            cwd=None,
            encoding="utf-8",
            env=None,
            errors="backslashreplace",
            shell=False,
            stderr="",
            stdin=-3,
            stdout="",
        )

    def test_start_process_affinity_posix(self, rpyc, mocker):
        rpyc._os_type = OSType.POSIX
        rpyc.modules = mocker.Mock()
        rpyc._resolve_process_output_arguments = mocker.create_autospec(
            rpyc._resolve_process_output_arguments, return_value=("", "")
        )
        rpyc._handle_path_extension = mocker.create_autospec(rpyc._handle_path_extension, return_value=None)
        rpyc._process_class = mocker.Mock(rpyc._process_class)
        rpyc._process_class.__call__().return_value = None
        rpyc.start_process("command arg1 arg2", cpu_affinity=[1, 3, 7])

        rpyc.modules().subprocess.Popen.assert_called_with(
            ["taskset", "0x8a", "command", "arg1", "arg2"],
            cwd=None,
            encoding="utf-8",
            env=None,
            errors="backslashreplace",
            shell=False,
            stderr="",
            stdin=-3,
            stdout="",
        )

    def test__run_esxi_command(self, rpyc, mocker, caplog):
        caplog.set_level(log_levels.MODULE_DEBUG)
        rpyc.get_os_name = mocker.create_autospec(rpyc.get_os_name)
        rpyc.get_os_name.return_value = OSName.ESXI
        command = "cmd arg1 arg2"
        expected_output = CompletedProcess(args=command, stdout=b"output", stderr=b"", returncode=1)
        popen_output = mocker.Mock()
        rpyc.modules = mocker.Mock()
        popen_mock = rpyc.modules().subprocess.Popen
        popen_mock.return_value = popen_output
        popen_output.returncode = "1"
        popen_output.communicate.return_value = b"output", b""
        output = rpyc._run_esxi_command(
            command, cwd="/", env={}, shell=True, stdout=1, stderr=0, timeout=15, input_data="Something"
        )
        assert repr(output) == repr(expected_output)
        popen_mock.assert_called_once_with(command, cwd="/", env={}, shell=True, stdout=1, stderr=0)
        popen_output.communicate.assert_called_once_with(timeout=15)
        assert "Input data is not supported on ESXi" in caplog.messages

    def test__run_esxi_command_empty_output(self, rpyc, mocker, caplog):
        caplog.set_level(log_levels.MODULE_DEBUG)
        rpyc.get_os_name = mocker.create_autospec(rpyc.get_os_name)
        rpyc.get_os_name.return_value = OSName.ESXI
        command = "cmd arg1 arg2"
        expected_output = CompletedProcess(args=command, stdout=b"", stderr=b"", returncode=0)
        popen_output = mocker.Mock()
        rpyc.modules = mocker.Mock()
        popen_mock = rpyc.modules().subprocess.Popen
        popen_mock.return_value = popen_output
        popen_output.returncode = "0"
        popen_output.communicate.return_value = b"", b""
        output = rpyc._run_esxi_command(
            command, cwd="/", env={}, shell=True, stdout=1, stderr=0, timeout=15, input_data=None
        )
        assert repr(output) == repr(expected_output)
        popen_mock.assert_called_once_with(command, cwd="/", env={}, shell=True, stdout=1, stderr=0)

    @pytest.mark.parametrize(
        "os_type, command, expected_split_command",
        [
            (OSType.POSIX, "/root/app -c -b 10", ["/root/app", "-c", "-b", "10"]),
            (OSType.WINDOWS, "c:\\tmp\\app.exe -c -b 10", ["c:\\tmp\\app.exe", "-c", "-b", "10"]),
        ],
    )
    def test_start_process_no_log_file(self, rpyc, mocker, os_type, command, expected_split_command):
        rpyc._os_type = os_type
        rpyc.modules = mocker.Mock()
        rpyc._resolve_process_output_arguments = mocker.create_autospec(
            rpyc._resolve_process_output_arguments, return_value=("", "")
        )
        rpyc._handle_path_extension = mocker.create_autospec(rpyc._handle_path_extension, return_value=None)
        rpyc._process_class = mocker.Mock(rpyc._process_class)
        rpyc._process_class.__call__().return_value = None
        rpyc.start_process(command)
        rpyc.modules().subprocess.Popen.assert_called_with(
            expected_split_command,
            cwd=None,
            encoding="utf-8",
            env=None,
            errors="backslashreplace",
            shell=False,
            stderr="",
            stdin=-3,
            stdout="",
        )
        rpyc._process_class.assert_has_calls(
            [mocker.call(log_file_stream=None, log_path=None, owner=rpyc, process=mocker.ANY)]
        )

    @pytest.mark.parametrize(
        "os_type, command, expected_split_command",
        [
            (OSType.POSIX, "/root/app -c -b 10", ["/root/app", "-c", "-b", "10"]),
            (OSType.WINDOWS, "c:\\tmp\\app.exe -c -b 10", ["c:\\tmp\\app.exe", "-c", "-b", "10"]),
        ],
    )
    def test_start_process_log_file(self, rpyc, mocker, os_type, command, expected_split_command):
        rpyc._os_type = os_type
        rpyc.get_os_name = mocker.Mock(return_value=OSName.LINUX)
        rpyc.modules = mocker.Mock()
        rpyc._resolve_process_output_arguments = mocker.create_autospec(
            rpyc._resolve_process_output_arguments, return_value=("", "")
        )
        rpyc._handle_path_extension = mocker.create_autospec(rpyc._handle_path_extension, return_value=None)
        rpyc._process_class = mocker.Mock(rpyc._process_class)
        rpyc._process_class.__call__().return_value = None
        path_mock = rpyc.modules.return_value.pathlib.Path = mocker.create_autospec(Path)
        file_path_mock = mocker.Mock()
        stream_mock = mocker.Mock()
        path_mock.return_value.expanduser.return_value.__truediv__.return_value = file_path_mock
        file_path_mock.open.return_value = stream_mock
        rpyc.start_process(command, log_file=True)
        rpyc.modules().subprocess.Popen.assert_called_with(
            expected_split_command,
            cwd=None,
            encoding="utf-8",
            env=None,
            errors="backslashreplace",
            shell=False,
            stderr=stream_mock,
            stdin=-3,
            stdout=stream_mock,
        )
        rpyc._process_class.assert_has_calls(
            [mocker.call(log_file_stream=stream_mock, log_path=file_path_mock, owner=rpyc, process=mocker.ANY)]
        )

    @pytest.mark.parametrize(
        "os_type, command, expected_split_command",
        [
            (OSType.POSIX, "/root/app -c -b 10", ["/root/app", "-c", "-b", "10"]),
            (OSType.WINDOWS, "c:\\tmp\\app.exe -c -b 10", ["c:\\tmp\\app.exe", "-c", "-b", "10"]),
        ],
    )
    def test_start_process_output_file(self, rpyc, mocker, os_type, command, expected_split_command):
        rpyc._os_type = os_type
        rpyc.modules = mocker.Mock()
        rpyc._resolve_process_output_arguments = mocker.create_autospec(
            rpyc._resolve_process_output_arguments, return_value=("", "")
        )
        rpyc._handle_path_extension = mocker.create_autospec(rpyc._handle_path_extension, return_value=None)
        rpyc._process_class = mocker.Mock(rpyc._process_class)
        rpyc._process_class.__call__().return_value = None
        file_path_mock = mocker.Mock()
        file_path_mock.parents = [mocker.Mock()]
        stream_mock = mocker.Mock()
        file_path_mock.open.return_value = stream_mock
        rpyc.start_process(command, output_file=file_path_mock)
        rpyc.modules().subprocess.Popen.assert_called_with(
            expected_split_command,
            cwd=None,
            encoding="utf-8",
            env=None,
            errors="backslashreplace",
            shell=False,
            stderr=stream_mock,
            stdin=-3,
            stdout=stream_mock,
        )
        rpyc._process_class.assert_has_calls(
            [mocker.call(log_file_stream=stream_mock, log_path=file_path_mock, owner=rpyc, process=mocker.ANY)]
        )

    def test_str_function(self, rpyc):
        assert str(rpyc) == "rpyc"

    @pytest.mark.parametrize(
        "os_name,os_type, expected_class",
        [
            (OSName.LINUX, OSType.POSIX, PosixRPyCProcess),
            (OSName.FREEBSD, OSType.POSIX, PosixRPyCProcess),
            (OSName.WINDOWS, OSType.WINDOWS, WindowsRPyCProcess),
            (OSName.ESXI, OSType.POSIX, ESXiRPyCProcess),
        ],
    )
    def test__set_process_class(self, rpyc, mocker, os_name, os_type, expected_class):
        rpyc.get_os_name = mocker.create_autospec(rpyc.get_os_name)
        rpyc._os_type = os_type
        rpyc.get_os_name.return_value = os_name
        rpyc._set_process_class()
        assert rpyc._process_class == expected_class

    def test_start_process_by_start_tool(self, rpyc, mocker):
        rpyc._os_type = OSType.EFISHELL
        with pytest.raises(ConnectionCalledProcessError):
            rpyc.start_process_by_start_tool("notepad")
        rpyc._os_type = OSType.WINDOWS
        rpyc.modules = mocker.Mock()
        path_mock = mocker.MagicMock()
        path_mock.__str__.return_value = "/path/log.txt"
        rpyc._prepare_log_file = mocker.create_autospec(rpyc._prepare_log_file, return_value=path_mock)
        proc = rpyc.start_process_by_start_tool("notepad")
        rpyc.modules().subprocess.Popen.assert_called_with(
            "start /WAIT /B notepad > /path/log.txt 2>&1",
            cwd=None,
            encoding="utf-8",
            errors="backslashreplace",
            shell=True,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
        )
        assert proc.log_path == path_mock

    def test_start_process_by_start_tool_with_parameters(self, rpyc, mocker):
        rpyc._os_type = OSType.WINDOWS
        rpyc.modules = mocker.Mock()
        rpyc._prepare_log_file = mocker.create_autospec(rpyc._prepare_log_file, return_value=None)
        rpyc.start_process_by_start_tool("notepad", discard_stdout=True, cwd="c:\\", numa_node=1, cpu_affinity=1)
        rpyc.modules().subprocess.Popen.assert_called_with(
            "start /WAIT /B /D c:\\ /NODE 1 /AFFINITY 2 notepad",
            cwd="c:\\",
            encoding="utf-8",
            errors="backslashreplace",
            shell=True,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
        )

    def test_ip_property(self, rpyc):
        assert rpyc.ip == "10.10.10.10"

    def test_init_with_model(self, mocker):
        mocker.patch("mfd_connect.RPyCConnection._set_process_class")
        mocker.patch("mfd_connect.RPyCConnection._set_bg_serving_thread")
        mocker.patch("mfd_connect.RPyCConnection.log_connected_host_info")
        model = mocker.Mock()
        obj = RPyCConnection(ip="10.10.10.10", model=model)
        assert obj.model == model
        obj = RPyCConnection(ip="10.10.10.10")
        assert obj.model is None

    def test_get_requirements_version_pass(self, rpyc, mocker):
        python_sha = "6d5c4178278aca48b6b365b3042eb5676b071a63d54913f6c718bc608324a4e3"
        rpyc.modules = mocker.Mock()
        mockk = rpyc.modules.return_value.pathlib.Path.return_value.parent.__truediv__ = mocker.Mock()
        mockk.return_value.read_text.return_value = python_sha
        mockk.return_value.exists.return_value = True
        rpyc.modules.return_value.sys.executable = ""
        assert rpyc.get_requirements_version() == python_sha

    def test_get_requirements_version_none(self, rpyc, mocker):
        rpyc.modules = mocker.Mock()
        rpyc.modules.return_value.pathlib.Path.return_value.parent.__truediv__ = mocker.Mock()
        rpyc.modules.return_value.sys.executable = ""
        rpyc.modules.return_value.pathlib.Path.exists.return_value = False
        assert rpyc.get_requirements_version() is None

    def test__establish_connection_no_deployment(self, rpyc, mocker):
        rpyc.enable_deploy = False
        setup_mock = mocker.patch("mfd_connect.util.deployment.SetupPythonForResponder")
        rpyc._RPyCConnection__establish_connection = mocker.create_autospec(rpyc._RPyCConnection__establish_connection)
        rpyc._establish_connection(retry_timeout=1, retry_time=1)
        rpyc._RPyCConnection__establish_connection.assert_called_once()
        setup_mock.assert_not_called()

    def test__establish_connection(self, rpyc, mocker):
        """Test full deployment."""
        rpyc.enable_deploy = True
        rpyc.deploy_username = "a"
        rpyc.deploy_password = "a"
        rpyc.share_username = "a"
        rpyc.share_password = "a"
        rpyc.share_url = "a"
        setup_mock = mocker.patch("mfd_connect.util.deployment.SetupPythonForResponder")
        rpyc._RPyCConnection__establish_connection = mocker.create_autospec(rpyc._RPyCConnection__establish_connection)
        rpyc._RPyCConnection__establish_connection.side_effect = [
            RPyCDeploymentException,
            RPyCDeploymentException,
            None,
        ]
        rpyc._establish_connection(retry_timeout=1, retry_time=1)
        assert rpyc._RPyCConnection__establish_connection.call_count == 3
        setup_mock.assert_called_once()

    def test__establish_connection_deployed_already_running(self, rpyc, mocker):
        """Test where deployed rpyc is running."""
        rpyc.enable_deploy = True
        rpyc.deploy_username = "a"
        rpyc.deploy_password = "a"
        rpyc.share_username = "a"
        rpyc.share_password = "a"
        rpyc.share_url = "a"
        setup_mock = mocker.patch("mfd_connect.util.deployment.SetupPythonForResponder")
        rpyc._RPyCConnection__establish_connection = mocker.create_autospec(rpyc._RPyCConnection__establish_connection)
        rpyc._RPyCConnection__establish_connection.side_effect = [
            RPyCDeploymentException,
            None,
        ]
        rpyc._establish_connection(retry_timeout=1, retry_time=1)
        assert rpyc._RPyCConnection__establish_connection.call_count == 2
        setup_mock.assert_not_called()

    @pytest.fixture()
    def rpyc_conn_with_timeout(self):
        with patch.object(RPyCConnection, "__init__", return_value=None):
            conn = RPyCConnection(ip="10.10.10.10")
            conn._ip = "10.10.10.10"
            conn._os_type = conn._cached_os_type = OSType.POSIX
            conn._enable_bg_serving_thread = True
            conn._default_timeout = 1
            conn._connection_timeout = 360
            conn.path_extension = None
            conn.cache_system_data = True
            conn._ipv6 = False
            return conn

    def test_execute_with_timeout(self, rpyc_conn_with_timeout, rpyc, mocker):
        rpyc._connection = mocker.Mock()
        rpyc_conn_with_timeout._connection = mocker.Mock()
        rpyc.get_os_name = mocker.create_autospec(rpyc.get_os_name, return_value=OSName.LINUX)
        rpyc_conn_with_timeout.get_os_name = mocker.create_autospec(
            rpyc_conn_with_timeout.get_os_name, return_value=OSName.LINUX
        )
        rpyc_conn_with_timeout._run_command = mocker.create_autospec(
            rpyc_conn_with_timeout._run_command, return_value=CompletedProcess("ping localhost", returncode=0)
        )
        rpyc._run_command = mocker.create_autospec(
            rpyc._run_command, return_value=CompletedProcess("ping localhost", returncode=0)
        )
        rpyc_conn_with_timeout.execute_command("ping localhost")
        rpyc.execute_command("ping localhost")

        rpyc_conn_with_timeout._run_command.assert_called_with(
            ["ping", "localhost"], None, None, None, False, -1, -1, 1
        )
        rpyc._run_command.assert_called_with(["ping", "localhost"], None, None, None, False, -1, -1, None)

    def test_handle_env_extension_with_custom_env(self, rpyc, mocker):
        rpyc.modules = mocker.Mock()
        rpyc.modules().os.environ.copy.return_value = {"PATH": "some path"}

        # Running the test
        result = rpyc._handle_env_extension({"my_env": "my_value"})

        # Assertions
        assert result == {"my_env": "my_value", "PATH": "some path"}
        rpyc.modules().os.environ.copy.assert_called_once()

    def test_handle_env_extension_with_none_env(self, rpyc, mocker):
        rpyc.modules = mocker.Mock()
        rpyc.modules().os.environ.copy.return_value = {"PATH": "some path"}

        # Running the test
        result = rpyc._handle_env_extension(None)

        # Assertions
        assert result is None
        rpyc.modules().os.environ.copy.assert_not_called()

    def test_handle_env_extension_with_empty_env(self, rpyc, mocker):
        rpyc.modules = mocker.Mock()
        rpyc.modules().os.environ.copy.return_value = {"PATH": "some path"}

        # Running the test
        result = rpyc._handle_env_extension({})

        # Assertions
        assert result == {"PATH": "some path"}
        rpyc.modules().os.environ.copy.assert_called_once()

    def test_handle_env_extension_with_duplicated_value(self, rpyc, mocker):
        rpyc.modules = mocker.Mock()
        rpyc.modules().os.environ.copy.return_value = {"PATH": "some path"}

        # Running the test
        result = rpyc._handle_env_extension({"PATH": "other path"})

        # Assertions
        assert result == {"PATH": "other path"}
        rpyc.modules().os.environ.copy.assert_called_once()

    def test_restart_platform(self, rpyc, mocker):
        rpyc.get_os_type = mocker.Mock(return_value=OSType.WINDOWS)
        rpyc.get_os_name = mocker.Mock(return_value=OSName.WINDOWS)
        rpyc.send_command_and_disconnect_platform = mocker.Mock()
        rpyc.restart_platform()
        rpyc.send_command_and_disconnect_platform.assert_called_once_with("shutdown /r /f -t 0")

    def test_shutdown_platform(self, rpyc, mocker):
        rpyc.get_os_type = mocker.Mock(return_value=OSType.WINDOWS)
        rpyc.get_os_name = mocker.Mock(return_value=OSName.WINDOWS)
        rpyc.send_command_and_disconnect_platform = mocker.Mock()
        rpyc.shutdown_platform()
        rpyc.send_command_and_disconnect_platform.assert_called_once_with("shutdown /s /f -t 0")

    def test__create_connection_success(self, rpyc, mocker):
        # Simulate successful connection on first try
        mock_conn = mocker.Mock()
        rpyc.modules = mocker.Mock()
        mocker.patch("rpyc.connect", return_value=mock_conn)
        # Patch any required attributes/methods used in _create_connection
        rpyc._ip = "10.10.10.10"
        rpyc._port = 18812
        rpyc._ssl_keyfile = None
        rpyc._ssl_certfile = None
        rpyc._connection_timeout = 10
        result = RPyCConnection._create_connection(rpyc)
        assert result == mock_conn

    def test__create_connection_retry_then_success(self, rpyc, mocker):
        # Simulate OSError on first two tries, then success
        mock_conn = mocker.Mock()
        rpyc.modules = mocker.Mock()
        connect_mock = mocker.patch("rpyc.connect", side_effect=[OSError, OSError, mock_conn])
        rpyc._ip = "10.10.10.10"
        rpyc._port = 18812
        rpyc._ssl_keyfile = None
        rpyc._ssl_certfile = None
        rpyc._connection_timeout = 10
        result = RPyCConnection._create_connection(rpyc)
        assert result == mock_conn
        assert connect_mock.call_count == 3

    def test__create_connection_all_fail(self, rpyc, mocker):
        # Simulate OSError on all retries
        rpyc.modules = mocker.Mock()
        connect_mock = mocker.patch("rpyc.connect", side_effect=OSError)
        rpyc._ip = "10.10.10.10"
        rpyc._port = 18812
        rpyc._ssl_keyfile = None
        rpyc._ssl_certfile = None
        rpyc._connection_timeout = 10
        with pytest.raises(OSError):
            RPyCConnection._create_connection(rpyc)
        assert connect_mock.call_count == 5

    def test__create_connection_with_ssl(self, rpyc, mocker):
        # Simulate successful connection with SSL keyfile and certfile
        mock_conn = mocker.Mock()
        rpyc.modules = mocker.Mock()
        connect_mock = mocker.patch("rpyc.ssl_connect", return_value=mock_conn)
        rpyc._ip = "10.10.10.10"
        rpyc._port = 18812
        rpyc._ssl_keyfile = "key.pem"
        rpyc._ssl_certfile = "cert.pem"
        rpyc._connection_timeout = 10
        result = RPyCConnection._create_connection(rpyc)
        assert result == mock_conn
        connect_mock.assert_called_once_with(
            str(rpyc._ip),
            port=rpyc._port,
            service=ClassicService,
            keepalive=True,
            config={"sync_request_timeout": rpyc._connection_timeout},
            keyfile=rpyc._ssl_keyfile,
            certfile=rpyc._ssl_certfile,
            ipv6=False,
        )

    def test__create_connection_with_ipv6(self, rpyc, mocker):
        # Simulate successful connection with ipv6=True
        mock_conn = mocker.Mock()
        rpyc.modules = mocker.Mock()
        connect_mock = mocker.patch("rpyc.connect", return_value=mock_conn)
        rpyc._ip = "::1"
        rpyc._port = 18812
        rpyc._ssl_keyfile = None
        rpyc._ssl_certfile = None
        rpyc._connection_timeout = 10
        rpyc._ipv6 = True
        result = RPyCConnection._create_connection(rpyc)
        assert result == mock_conn
        connect_mock.assert_called_once_with(
            str(rpyc._ip),
            port=rpyc._port,
            ipv6=True,
            service=ClassicService,
            keepalive=True,
            config={"sync_request_timeout": rpyc._connection_timeout},
        )

    def test__create_connection_with_ssl_and_ipv6(self, rpyc, mocker):
        # Simulate successful SSL connection with ipv6=True
        mock_conn = mocker.Mock()
        rpyc.modules = mocker.Mock()
        connect_mock = mocker.patch("rpyc.ssl_connect", return_value=mock_conn)
        rpyc._ip = "::1"
        rpyc._port = 18812
        rpyc._ssl_keyfile = "key.pem"
        rpyc._ssl_certfile = "cert.pem"
        rpyc._connection_timeout = 10
        rpyc._ipv6 = True
        result = RPyCConnection._create_connection(rpyc)
        assert result == mock_conn
        connect_mock.assert_called_once_with(
            str(rpyc._ip),
            port=rpyc._port,
            ipv6=True,
            service=ClassicService,
            keepalive=True,
            config={"sync_request_timeout": rpyc._connection_timeout},
            keyfile=rpyc._ssl_keyfile,
            certfile=rpyc._ssl_certfile,
        )
