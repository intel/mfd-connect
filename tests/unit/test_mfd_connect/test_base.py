# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
import logging
import sys
from pathlib import Path
import platform
from subprocess import CompletedProcess, CalledProcessError
from unittest import mock
from unittest.mock import patch

import pytest
from mfd_common_libs import log_levels
from mfd_typing import OSName, OSType, OSBitness
from mfd_typing.cpu_values import CPUArchitecture
from netaddr.ip import IPAddress

from mfd_connect import RPyCConnection, LocalConnection
from mfd_connect.base import ConnectionCompletedProcess, Connection
from mfd_connect.exceptions import (
    IncorrectAffinityMaskException,
    GatheringSystemInfoError,
    TransferFileError,
    UnavailableServerException,
    OsNotSupported,
    CPUArchitectureNotSupported,
)


class TestConnectionCompletedProcess:
    @pytest.fixture()
    def conn(self):
        with patch.object(RPyCConnection, "__init__", return_value=None):
            conn = RPyCConnection(ip="10.10.10.10")
            conn._ip = "10.10.10.10"
            conn._os_name = OSName.LINUX
            conn._enable_bg_serving_thread = True
            conn.cache_system_data = True
            return conn

    def test___repr___all_params(self):
        completed_process = ConnectionCompletedProcess(
            args="test",
            stdout="Success",
            stderr="Error",
            stdout_bytes=b"Success",
            stderr_bytes=b"Error",
            return_code=0,
        )
        str_to_check = (
            "ConnectionCompletedProcess(args='test', stdout='Success', stderr='Error', "
            "stdout_bytes=b'Success', stderr_bytes=b'Error', return_code=0)"
        )
        assert str_to_check == completed_process.__repr__()

    def test___repr___without_stdout(self):
        completed_process = ConnectionCompletedProcess(
            args="test", stderr="Error", stderr_bytes=b"Error", return_code=0
        )
        str_to_check = "ConnectionCompletedProcess(args='test', stderr='Error', stderr_bytes=b'Error', return_code=0)"
        assert str_to_check == completed_process.__repr__()

    def test_args_string(self):
        completed_process = ConnectionCompletedProcess(args="test")
        assert isinstance(completed_process.args, str)

    def test_args_list(self):
        completed_process = ConnectionCompletedProcess(args=["test", "param1", "param2"])
        assert isinstance(completed_process.args, list)

    def test_stdout(self):
        completed_process = ConnectionCompletedProcess(args="test", stdout="Success")
        assert "Success" == completed_process.stdout

    def test_stdout_unsupported(self):
        completed_process = ConnectionCompletedProcess(args="test")
        with pytest.raises(NotImplementedError):
            _ = completed_process.stdout

    def test_stderr(self):
        completed_process = ConnectionCompletedProcess(args="test", stderr="Error")
        assert "Error" == completed_process.stderr

    def test_stderr_unsupported(self):
        completed_process = ConnectionCompletedProcess(args="test")
        with pytest.raises(NotImplementedError):
            _ = completed_process.stderr

    def test_return_code(self):
        completed_process = ConnectionCompletedProcess(args="test", return_code=0)
        assert 0 == completed_process.return_code

    def test_return_code_unsupported(self):
        completed_process = ConnectionCompletedProcess(args="test")
        with pytest.raises(NotImplementedError):
            _ = completed_process.return_code

    @pytest.mark.parametrize(
        "cpu_affinity,calculated_mask", [(1, 2), ([1, 3, 4], 26), ("0, 7, 8", 385), ("0-7", 255), ("1, 3-6", 122)]
    )
    def test__create_affinity_mask_valid(self, cpu_affinity, calculated_mask):
        assert Connection._create_affinity_mask(cpu_affinity) == calculated_mask

    @pytest.mark.parametrize("cpu_affinity", [None, "abc", "1-a", {1: 1}, [1, "A"]])
    def test__create_affinity_mask_invalid(self, cpu_affinity):
        with pytest.raises(IncorrectAffinityMaskException):
            Connection._create_affinity_mask(cpu_affinity)

    def test_get_system_info_pass(self, conn):
        conn.get_os_name = mock.Mock(return_value=OSName.WINDOWS)

        with patch("mfd_connect.base._get_system_info_windows", return_value="Foo"):
            assert conn.get_system_info() == "Foo"

    def test_get_system_info_fail_on_efi_shell(self, conn):
        conn.get_os_name = mock.Mock(return_value=OSName.EFISHELL)
        with pytest.raises(OSError):
            conn.get_system_info()

    def test_get_system_info_fail_on_gathering(self, conn):
        conn.get_os_name = mock.Mock(return_value=OSName.WINDOWS)

        with patch("mfd_connect.base._get_system_info_windows", side_effect=ValueError):
            with pytest.raises(GatheringSystemInfoError):
                conn.get_system_info()


class TestAsyncConnection:
    @pytest.fixture()
    def conn(self):
        with patch.object(RPyCConnection, "__init__", return_value=None):
            conn = RPyCConnection(ip="10.10.10.10")
            conn._ip = "10.10.10.10"
            conn._os_name = OSName.LINUX
            conn._enable_bg_serving_thread = True
            return conn

    @pytest.fixture()
    def mock_os_environ(self, conn, mocker):
        class MockOS:
            os: str = "os"

        class MockEnviron(MockOS):
            environ: dict = {"PATH": "/usr/bin"}

        return mocker.Mock(return_value=MockEnviron)

    def test__prepare_log_file_do_nothing(self, conn):
        command = "iperf3 -s -B 198.108.8.1 -p 5201 --format M"
        assert conn._prepare_log_file(command, log_file=False, output_file=None) is None

    def test__prepare_log_file_log_file(self, conn, mocker):
        conn._os_type = OSType.POSIX
        conn.get_os_name = mock.Mock(return_value=OSName.LINUX)
        command = "iperf3 -s -B 198.108.8.1 -p 5201 --format M"
        path_mock = mocker.patch("mfd_connect.RPyCConnection.path", return_value=mocker.create_autospec(Path))
        directory_mock = path_mock.return_value.expanduser.return_value = mocker.create_autospec(Path)
        log_filename = directory_mock.__truediv__.return_value = mocker.create_autospec(Path)
        assert conn._prepare_log_file(command, log_file=True, output_file=None)
        directory_mock.exists.assert_called_once()
        log_filename.touch.assert_called_once()
        # check if next logfile from the same command has different SHA
        conn._prepare_log_file(command, log_file=True, output_file=None)
        assert len(directory_mock.__truediv__.call_args_list) == 2
        log_path_creation_calls = directory_mock.__truediv__.call_args_list
        # check if path was created with different log_filename, path creation is done by truediv '/'
        assert log_path_creation_calls[0] != log_path_creation_calls[1]

    def test__prepare_log_file_log_file_directory_not_exists(self, conn, mocker):
        conn._os_type = OSType.POSIX
        conn.get_os_name = mock.Mock(return_value=OSName.LINUX)
        command = "iperf3 -s -B 198.108.8.1 -p 5201 --format M"
        path_mock = mocker.patch("mfd_connect.RPyCConnection.path", return_value=mocker.create_autospec(Path))
        directory_mock = path_mock.return_value.expanduser.return_value = mocker.create_autospec(Path)
        directory_mock.exists.return_value = False
        log_filename = directory_mock.__truediv__.return_value = mocker.create_autospec(Path)
        assert conn._prepare_log_file(command, log_file=True, output_file=None)
        directory_mock.exists.assert_called_once()
        directory_mock.mkdir.assert_called_once()
        log_filename.touch.assert_called_once()

    def test__prepare_log_file_log_file_esxi(self, conn, mocker):
        conn._os_type = OSType.POSIX
        conn.get_os_name = mock.Mock(return_value=OSName.ESXI)
        command = "iperf3 -s -B 198.108.8.1 -p 5201 --format M"
        path_mock = mocker.patch("mfd_connect.RPyCConnection.path", return_value=mocker.create_autospec(Path))
        directory_mock = path_mock.return_value.expanduser.return_value = mocker.create_autospec(Path)
        modules_mock = mocker.Mock()
        glob_mock = mocker.Mock()
        glob_mock.glob.return_value = ["vmfs/volumes/datastore12"]
        modules_mock.glob = glob_mock
        conn.modules = mocker.Mock(return_value=modules_mock)
        log_filename = directory_mock.__truediv__.return_value = mocker.create_autospec(Path)
        assert conn._prepare_log_file(command, log_file=True, output_file=None)
        directory_mock.exists.assert_called_once()
        log_filename.touch.assert_called_once()
        # check if next logfile from the same command has different SHA
        conn._prepare_log_file(command, log_file=True, output_file=None)
        assert len(directory_mock.__truediv__.call_args_list) == 2
        log_path_creation_calls = directory_mock.__truediv__.call_args_list
        # check if path was created with different log_filename, path creation is done by truediv '/'
        assert log_path_creation_calls[0] != log_path_creation_calls[1]

    def test__prepare_log_file_log_file_directory_not_exists_esxi(self, conn, mocker):
        conn._os_type = OSType.POSIX
        conn.get_os_name = mock.Mock(return_value=OSName.ESXI)
        command = "iperf3 -s -B 198.108.8.1 -p 5202 --format M"
        path_mock = mocker.patch("mfd_connect.RPyCConnection.path", return_value=mocker.create_autospec(Path))
        directory_mock = path_mock.return_value.expanduser.return_value = mocker.create_autospec(Path)
        directory_mock.exists.return_value = False
        modules_mock = mocker.Mock()
        glob_mock = mocker.Mock()
        glob_mock.glob.return_value = ["vmfs/volumes/datastore1"]
        modules_mock.glob = glob_mock
        conn.modules = mocker.Mock(return_value=modules_mock)
        log_filename = directory_mock.__truediv__.return_value = mocker.create_autospec(Path)
        assert conn._prepare_log_file(command, log_file=True, output_file=None)
        directory_mock.exists.assert_called_once()
        directory_mock.mkdir.assert_called_once()
        log_filename.touch.assert_called_once()

    def test__prepare_log_file_log_file_directory_and_datastore_not_exist_esxi(self, conn, mocker):
        conn._os_type = OSType.POSIX
        conn.get_os_name = mock.Mock(return_value=OSName.ESXI)
        command = "iperf3 -s -B 198.108.8.1 -p 5201 --format M"
        path_mock = mocker.patch("mfd_connect.RPyCConnection.path", return_value=mocker.create_autospec(Path))
        directory_mock = path_mock.return_value.expanduser.return_value = mocker.create_autospec(Path)
        directory_mock.exists.return_value = False
        modules_mock = mocker.Mock()
        glob_mock = mocker.Mock()
        glob_mock.glob.return_value = []
        modules_mock.glob = glob_mock
        conn.modules = mocker.Mock(return_value=modules_mock)
        log_filename = directory_mock.__truediv__.return_value = mocker.create_autospec(Path)
        assert conn._prepare_log_file(command, log_file=True, output_file=None)
        directory_mock.exists.assert_called_once()
        directory_mock.mkdir.assert_called_once()
        log_filename.touch.assert_called_once()

    def test__prepare_log_file_output_file(self, conn, mocker):
        conn._os_type = OSType.POSIX
        command = "iperf3 -s -B 198.108.8.1 -p 5201 --format M"
        mocker.patch("mfd_connect.RPyCConnection.path", return_value=mocker.create_autospec(Path))
        output_file_mock = mocker.create_autospec(Path)
        parent_file_mock = mocker.create_autospec(Path)
        output_file_mock.parents = [parent_file_mock]
        assert conn._prepare_log_file(command, log_file=False, output_file=output_file_mock) == output_file_mock
        parent_file_mock.exists.assert_called_once()
        output_file_mock.touch.assert_called_once()

    def test__prepare_log_file_output_file_parent_not_exists(self, conn, mocker):
        conn._os_type = OSType.POSIX
        command = "iperf3 -s -B 198.108.8.1 -p 5201 --format M"
        mocker.patch("mfd_connect.RPyCConnection.path", return_value=mocker.create_autospec(Path))
        output_file_mock = mocker.create_autospec(Path)
        parent_file_mock = mocker.create_autospec(Path)
        parent_file_mock.exists.return_value = False
        output_file_mock.parents = [parent_file_mock]
        assert conn._prepare_log_file(command, log_file=False, output_file=output_file_mock) == output_file_mock
        parent_file_mock.exists.assert_called_once()
        parent_file_mock.mkdir.assert_called_once()
        output_file_mock.touch.assert_called_once()

    @pytest.mark.parametrize(
        "os_name, download_func",
        [
            (OSName.WINDOWS, "mfd_connect.base.download_file_windows"),
            (OSName.ESXI, "mfd_connect.base.download_file_esxi"),
            (OSName.LINUX, "mfd_connect.base.download_file_unix"),
        ],
    )
    def test_download_file_from_url_success(self, conn, os_name, download_func, mocker, mock_os_environ):
        conn.get_os_name = mock.Mock(return_value=os_name)
        conn.modules = mocker.Mock(return_value=mock_os_environ)
        mock_download_func = mocker.patch(download_func, return_value=mock.Mock(return_code=0, stdout=""))

        conn.download_file_from_url("http://example.com", Path("/path/to/destination"))

        mock_download_func.assert_called_once()

    @pytest.mark.parametrize(
        "os_name, download_func",
        [
            (OSName.WINDOWS, "mfd_connect.base.download_file_windows"),
            (OSName.ESXI, "mfd_connect.base.download_file_esxi"),
            (OSName.LINUX, "mfd_connect.base.download_file_unix"),
        ],
    )
    def test_download_file_from_url_failure(self, conn, os_name, download_func, mocker, mock_os_environ):
        conn.get_os_name = mock.Mock(return_value=os_name)
        conn.modules = mocker.Mock(return_value=mock_os_environ)
        mock_download_func = mocker.patch(
            download_func, return_value=mock.Mock(return_code=1, stdout="Failed to connect to")
        )

        with pytest.raises(UnavailableServerException, match="Cannot communicate with http://example.com"):
            conn.download_file_from_url("http://example.com", Path("/path/to/destination"))

        mock_download_func.assert_called_once()

    def test_download_file_from_url_assert_raised(self, conn, mocker):
        conn.get_os_name = mock.Mock(return_value=OSName.LINUX)
        with pytest.raises(AssertionError):
            conn.download_file_from_url(
                "http://example.com", Path("/path/to/destination"), headers={"aa: bb"}, username="user", password="**"
            )

    def test_download_file_from_url_unknown_error(self, conn, mocker, mock_os_environ):
        conn.get_os_name = mock.Mock(return_value=OSName.LINUX)
        conn.modules = mocker.Mock(return_value=mock_os_environ)
        mock_download_func = mocker.patch(
            "mfd_connect.base.download_file_unix", return_value=mock.Mock(return_code=1, stdout="Unknown error")
        )

        with pytest.raises(
            TransferFileError, match="Problem with downloading file from http://example.com\n\nUnknown error"
        ):
            conn.download_file_from_url("http://example.com", Path("/path/to/destination"))

        mock_download_func.assert_called_once()

    def test_download_file_from_url_with_credentials(self, conn, mocker):
        conn.get_os_name = mock.Mock(return_value=OSName.WINDOWS)
        mock_download_func = mocker.patch(
            "mfd_connect.base.download_file_windows", return_value=mock.Mock(return_code=0, stdout="")
        )
        conn._manage_temporary_envs = mocker.Mock()
        mocker.patch("mfd_connect.base._generate_random_string", return_value="9yDOrm4D")
        path = Path("/path/to/destination")
        conn.download_file_from_url("http://example.com", path, username="user", password="***")

        mock_download_func.assert_called_once_with(
            connection=conn,
            url="http://example.com",
            destination_file=path,
            auth=' -Headers @{ Authorization = "Basic $env:TEMP_CREDS_42ad67"}',
        )

    def test_download_file_from_url_fallback_to_controller(self, conn, mocker, caplog, mock_os_environ):
        caplog.set_level(log_levels.MODULE_DEBUG)
        conn.get_os_name = mock.Mock(return_value=OSName.LINUX)
        conn.modules = mocker.Mock(return_value=mock_os_environ)
        mock_download_func = mocker.patch(
            "mfd_connect.base.download_file_unix",
            return_value=mock.Mock(return_code=1, stdout="curl: command not found"),
        )
        mock_download_func_via_controller = mocker.patch(
            "mfd_connect.base.download_file_unix_via_controller", return_value=mock.Mock(return_code=0)
        )

        conn.download_file_from_url("http://example.com", Path("/path/to/destination"))

        mock_download_func.assert_called_once()
        mock_download_func_via_controller.assert_called_once()
        assert "Setting temporary environment variables:" in caplog.text

    def test_download_file_from_url_unix_case(self, conn, mocker, mock_os_environ):
        conn.get_os_name = mocker.Mock(return_value=OSName.LINUX)
        conn.modules = mocker.Mock(return_value=mock_os_environ)
        mocker.patch("mfd_connect.base._generate_random_string", return_value="4d6304")
        conn.execute_command = mocker.Mock(
            return_value=ConnectionCompletedProcess(args="", stdout="", stderr="", return_code=0)
        )
        path = Path("/path/to/destination")
        conn.download_file_from_url("http://example.com", path, username="user", password="***")

        conn.execute_command.assert_called_once_with(
            f"curl  -u $TEMP_KEY_441a25:$TEMP_VALUE_441a25  --create-dirs -o {path} http://example.com",
            expected_return_codes=None,
            stderr_to_stdout=True,
            shell=True,
        )

    def test_download_file_from_url_with_header(self, conn, mocker):
        conn.get_os_name = mock.Mock(return_value=OSName.WINDOWS)
        mock_download_func = mocker.patch(
            "mfd_connect.base.download_file_windows", return_value=mock.Mock(return_code=0, stdout="")
        )
        conn._manage_temporary_envs = mocker.Mock()
        mocker.patch("mfd_connect.base._generate_random_string", return_value="9yDOrm4D")
        path = Path("/path/to/destination")
        conn.download_file_from_url("http://example.com", path, headers={"user": "pass"})

        mock_download_func.assert_called_once_with(
            connection=conn,
            url="http://example.com",
            destination_file=path,
            auth="-Headers @{$env:TEMP_KEY_42ad67_0= $env:TEMP_VALUE_42ad67_0;}",
        )


class TestPythonConnections:
    """Tests of PythonConnection."""

    # CustomTestException = CalledProcessError

    @pytest.fixture()
    def rpyc(self):
        with patch.object(RPyCConnection, "__init__", return_value=None):
            conn = RPyCConnection(ip="10.10.10.10")
            conn._ip = "10.10.10.10"
            conn._os_name = OSName.LINUX
            conn._enable_bg_serving_thread = True
            conn._default_timeout = None
            conn._connection_timeout = 360
            conn.path_extension = None
            conn.cache_system_data = False
            return conn

    @pytest.fixture
    def local_conn(self):
        local_conn = LocalConnection()
        local_conn._ip = IPAddress("127.0.0.1")
        local_conn._default_timeout = None
        local_conn.cache_system_data = True
        local_conn._os_type = local_conn._cached_os_type = OSType.POSIX
        yield local_conn

    @pytest.fixture
    def platform_system(self, mocker):
        return mocker.patch.object(platform, "system")

    @pytest.fixture
    def platform_machine(self, mocker):
        return mocker.patch.object(platform, "machine")

    def test_get_os_type_os_not_supported_local(self, local_conn, mocker):
        local_conn.modules = mocker.Mock()
        local_conn.modules.return_value.os.name = "arch32"
        local_conn.cache_system_data = False
        with pytest.raises(OsNotSupported):
            local_conn.get_os_type()

    def test_get_os_type_os_supported_windows_local(self, local_conn, mocker):
        local_conn.modules = mocker.Mock()
        local_conn.modules.return_value.os.name = "nt"
        local_conn.cache_system_data = False
        assert local_conn.get_os_type() == OSType.WINDOWS

    def test_get_os_name_os_not_supported_local(self, local_conn, platform_system):
        platform_system.return_value = "arch32"
        local_conn.cache_system_data = False
        with pytest.raises(OsNotSupported):
            local_conn.get_os_name()

    def test_get_os_name_os_not_supported_unix_local(self, local_conn, platform_system):
        platform_system.return_value = "Mac OS"
        local_conn.cache_system_data = False
        with pytest.raises(OsNotSupported):
            local_conn.get_os_name()

    def test_get_os_bitness_os_not_supported_rpyc(self, rpyc, mocker):
        rpyc.modules = mocker.Mock()
        rpyc.modules().platform.machine.return_value = "dunno"
        with pytest.raises(OsNotSupported):
            rpyc.get_os_bitness()

    @pytest.mark.parametrize("architecture_options", ["amd64", "ia64", "x86_64"])
    def test_get_os_bitness_os_supported_64bit_rpyc(self, rpyc, architecture_options, mocker):
        rpyc.modules = mocker.Mock()
        rpyc.modules().platform.machine.return_value = architecture_options
        assert rpyc.get_os_bitness() == OSBitness.OS_64BIT

    def test_get_os_bitness_os_supported_aarch64_rpyc(self, rpyc, mocker):
        rpyc.modules = mocker.Mock()
        rpyc.modules().platform.machine.return_value = "aarch64"
        assert rpyc.get_os_bitness() == OSBitness.OS_64BIT

    @pytest.mark.parametrize("architecture_options", ["i386", "i586", "x86", "ia32", "armv7l", "arm"])
    def test_get_os_bitness_os_supported_32bit_rpyc(self, rpyc, architecture_options, mocker):
        rpyc.modules = mocker.Mock()
        rpyc.modules().platform.machine.return_value = architecture_options

        assert rpyc.get_os_bitness() == OSBitness.OS_32BIT

    def test_get_os_bitness_os_64bit_local(self, local_conn, platform_machine):
        platform_machine.return_value = "amd64"
        assert local_conn.get_os_bitness() == OSBitness.OS_64BIT

    def test_get_os_bitness_os_32bit_local(self, local_conn, platform_machine):
        platform_machine.return_value = "x86"
        assert local_conn.get_os_bitness() == OSBitness.OS_32BIT

    def test_get_os_bitness_os_aarch64_local(self, local_conn, platform_machine):
        platform_machine.return_value = "aarch64"
        assert local_conn.get_os_bitness() == OSBitness.OS_64BIT

    def test_get_os_name_os_supported_windows_local(self, local_conn, platform_system):
        platform_system.return_value = "Windows"
        assert local_conn.get_os_name() == OSName.WINDOWS

    def test_get_os_name_os_supported_posix_local(self, local_conn, platform_system):
        local_conn.cache_system_data = False
        local_conn._os_name = None
        platform_system.return_value = "Linux"
        assert local_conn.get_os_name() == OSName.LINUX

    def test_get_cpu_architecture_64_bit_local(self, local_conn, platform_machine):
        platform_machine.return_value = "amd64"
        assert local_conn.get_cpu_architecture() == CPUArchitecture.X86_64

    def test_get_cpu_architecture_32_bit_local(self, local_conn, platform_machine):
        platform_machine.return_value = "x86"
        assert local_conn.get_cpu_architecture() == CPUArchitecture.X86

    def test_get_cpu_architecture_aarch64_local(self, local_conn, platform_machine):
        platform_machine.return_value = "aarch64"
        assert local_conn.get_cpu_architecture() == CPUArchitecture.ARM64

    def test_get_cpu_architecture_arm_local(self, local_conn, platform_machine):
        platform_machine.return_value = "armv7l"
        assert local_conn.get_cpu_architecture() == CPUArchitecture.ARM

    def test_get_cpu_architecture_not_supported_local(self, local_conn, platform_machine):
        platform_machine.return_value = "dunno"
        with pytest.raises(CPUArchitectureNotSupported):
            local_conn.get_cpu_architecture()

    @pytest.mark.parametrize("architecture_options", ["armv7l", "arm"])
    def test_get_cpu_architecture_arm_rpyc(self, rpyc, architecture_options, mocker):
        rpyc.modules = mocker.Mock()
        rpyc.modules().platform.machine.return_value = architecture_options

        assert rpyc.get_cpu_architecture() == CPUArchitecture.ARM

    @pytest.mark.parametrize("architecture_options", ["aarch64"])
    def test_get_cpu_architecture_arm64_rpyc(self, rpyc, architecture_options, mocker):
        rpyc.modules = mocker.Mock()
        rpyc.modules().platform.machine.return_value = architecture_options

        assert rpyc.get_cpu_architecture() == CPUArchitecture.ARM64

    @pytest.mark.parametrize("architecture_options", ["i386", "i586", "x86", "ia32"])
    def test_get_cpu_architecture_x86_rpyc(self, rpyc, architecture_options, mocker):
        rpyc.modules = mocker.Mock()
        rpyc.modules().platform.machine.return_value = architecture_options

        assert rpyc.get_cpu_architecture() == CPUArchitecture.X86

    @pytest.mark.parametrize("architecture_options", ["amd64", "ia64", "x86_64"])
    def test_get_cpu_architecture_x64_rpyc(self, rpyc, architecture_options, mocker):
        rpyc.modules = mocker.Mock()
        rpyc.modules().platform.machine.return_value = architecture_options

        assert rpyc.get_cpu_architecture() == CPUArchitecture.X86_64

    def test_get_cpu_architecture_not_supported_rpyc(self, rpyc, mocker):
        rpyc.modules = mocker.Mock()
        rpyc.modules().platform.machine.return_value = "dunno"
        with pytest.raises(CPUArchitectureNotSupported):
            rpyc.get_cpu_architecture()

    def test__handle_execution_outcome(self, rpyc):
        example_input = CompletedProcess(args="args", stdout=b"\r\nstd\nout\r", stderr=b"\r\nstd\nerr\r", returncode=0)
        expected_output = ConnectionCompletedProcess(
            args="args",
            stdout="\nstd\nout\n",
            stdout_bytes=b"\nstd\nout\n",
            stderr="\nstd\nerr\n",
            stderr_bytes=b"\nstd\nerr\n",
            return_code=0,
        )
        assert repr(rpyc._handle_execution_outcome(example_input)) == repr(expected_output)

    def test__handle_execution_outcome_skip_exception(self, rpyc, caplog):
        caplog.set_level(0)
        example_input = CompletedProcess(args="args", stdout=b"\r\nstd\nout\r", stderr=b"\r\nstd\nerr\r", returncode=0)
        rpyc._handle_execution_outcome(example_input, custom_exception=CalledProcessError, expected_return_codes=None)
        assert (
            "Return codes are ignored, passed exception: <class 'subprocess.CalledProcessError'> will be not raised."
            in caplog.text
        )

    def test_log_execution_results_success(self, caplog):
        from mfd_connect.base import PythonConnection

        caplog.set_level(logging.DEBUG)
        command = "echo test"
        completed_process = ConnectionCompletedProcess(
            args=command,
            stdout="test output",
            stderr="",
            return_code=0,
        )

        PythonConnection._log_execution_results(command, completed_process)

        assert f"Finished executing '{command}', rc=0" in caplog.text
        assert "stdout>>\ntest output" in caplog.text
        assert "stderr>>" not in caplog.text

    def test_log_execution_results_with_stderr(self, caplog):
        from mfd_connect.base import PythonConnection

        caplog.set_level(logging.DEBUG)
        command = "echo test"
        completed_process = ConnectionCompletedProcess(
            args=command,
            stdout="",
            stderr="test error",
            return_code=1,
        )

        PythonConnection._log_execution_results(command, completed_process)

        assert f"Finished executing '{command}', rc=1" in caplog.text
        assert "stdout>>" not in caplog.text
        assert "stderr>>\ntest error" in caplog.text

    def test_log_execution_results_skip_logging(self, caplog):
        from mfd_connect.base import PythonConnection

        caplog.set_level(logging.DEBUG)
        command = "echo test"
        completed_process = ConnectionCompletedProcess(
            args=command,
            stdout="test output",
            stderr="test error",
            return_code=0,
        )

        PythonConnection._log_execution_results(command, completed_process, skip_logging=True)

        assert f"Finished executing '{command}', rc=0" in caplog.text
        assert "stdout>>" not in caplog.text
        assert "stderr>>" not in caplog.text

    def test_is_same_python_version_match(self, rpyc):
        # Mock the sys.version_info to match the current Python version
        rpyc.modules = mock.Mock()
        rpyc.modules().sys.version_info = sys.version_info
        assert rpyc.is_same_python_version() is True

    def test_is_same_python_version_mismatch(self, rpyc):
        # Mock the sys.version_info to simulate a different Python version
        rpyc.modules = mock.Mock()
        rpyc.modules().sys.version_info = (sys.version_info[0], sys.version_info[1] + 1)
        assert rpyc.is_same_python_version() is False
