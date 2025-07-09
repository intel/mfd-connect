# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
from pathlib import PurePath, PurePosixPath, Path

import pytest
import requests
from mfd_typing import OSName, OSType
from mfd_typing.cpu_values import CPUArchitecture
from requests import Response

from mfd_connect import WinRmConnection, SSHConnection
from mfd_connect.base import ConnectionCompletedProcess
from mfd_connect.exceptions import (
    RPyCDeploymentException,
    WinRMException,
    ModuleFrameworkDesignError,
    ConnectionCalledProcessError,
    MissingPortablePythonOnServerException,
)
from mfd_connect.util.deployment import SetupPythonForResponder


class TestPythonDeployment:
    @pytest.fixture()
    def winrm_connection(self, mocker):
        yield mocker.create_autospec(WinRmConnection)

    @pytest.fixture()
    def ssh_connection(self, mocker):
        yield mocker.create_autospec(SSHConnection)

    @pytest.fixture()
    def tool(self, mocker):
        with mocker.patch.object(SetupPythonForResponder, "__init__", return_value=None):
            setup = SetupPythonForResponder(
                "10.10.10.10",
                "a",
                "a",
                "https://artifactory-server/artifactory/repo_name/"
                "tool/tool_main_3.10/main_v5.12.0-dev-28-62ca6cd9_py3.10/",
            )
            setup.artifactory_url = (
                "https://artifactory-server/artifactory/repo_name/"
                "tool/tool_main_3.10/main_v5.12.0-dev-28-62ca6cd9_py3.10/"
            )
            setup.is_posix = None
            setup.is_esxi = None
            setup.esxi_storage_path = None
            setup.ip = "10.10.10.10"
            setup.username = "a"
            setup.password = "***"
            setup.certificate = None
            yield setup

    def test__find_pp_from_url_for_os_windows(self, tool, mocker):
        tool._get_name_of_pp_zip = mocker.create_autospec(tool._get_name_of_pp_zip)
        tool._get_name_of_pp_zip.return_value = "PP_Windows_90419df35b7ba347.zip"
        assert tool._find_pp_from_url_for_os(OSName.WINDOWS, CPUArchitecture.X86_64, bsd_release=None) == (
            (
                "https://artifactory-server/artifactory/repo_name/tool/tool_main_3.10/"
                "main_v5.12.0-dev-28-62ca6cd9_py3.10/wrapper_interpreter/Windows"
            ),
            "PP_Windows_90419df35b7ba347.zip",
        )
        tool._get_name_of_pp_zip.assert_called_once_with(
            "https://artifactory-server/artifactory/repo_name/tool/tool_main_3.10/"
            "main_v5.12.0-dev-28-62ca6cd9_py3.10/wrapper_interpreter/Windows"
        )

    def test__find_pp_from_url_for_os_esxi(self, tool, mocker):
        tool._get_name_of_pp_zip = mocker.create_autospec(tool._get_name_of_pp_zip)
        tool._get_name_of_pp_zip.return_value = "PP_ESXi_90419df35b7ba347.zip"
        assert tool._find_pp_from_url_for_os(OSName.ESXI, CPUArchitecture.X86_64, bsd_release=None) == (
            (
                "https://artifactory-server/artifactory/repo_name/tool/tool_main_3.10/"
                "main_v5.12.0-dev-28-62ca6cd9_py3.10/light_interpreter/ESXi"
            ),
            "PP_ESXi_90419df35b7ba347.zip",
        )
        tool._get_name_of_pp_zip.assert_called_once_with(
            "https://artifactory-server/artifactory/repo_name/tool/tool_main_3.10/"
            "main_v5.12.0-dev-28-62ca6cd9_py3.10/light_interpreter/ESXi"
        )

    def test__find_pp_from_url_for_os_freebsd(self, tool, mocker):
        tool._get_name_of_pp_zip = mocker.create_autospec(tool._get_name_of_pp_zip)
        tool._get_name_of_pp_zip.return_value = "PP_FreeBSD_13_90419df35b7ba347.zip"
        assert tool._find_pp_from_url_for_os(OSName.FREEBSD, CPUArchitecture.X86_64, bsd_release="13") == (
            (
                "https://artifactory-server/artifactory/repo_name/tool/tool_main_3.10/"
                "main_v5.12.0-dev-28-62ca6cd9_py3.10/wrapper_interpreter/FreeBSD/13"
            ),
            "PP_FreeBSD_13_90419df35b7ba347.zip",
        )
        tool._get_name_of_pp_zip.assert_called_once_with(
            "https://artifactory-server/artifactory/repo_name/tool/"
            "tool_main_3.10/main_v5.12.0-dev-28-62ca6cd9_py3.10/wrapper_interpreter/FreeBSD/13"
        )

    def test__find_pp_from_url_for_os_linux(self, tool, mocker):
        tool._get_name_of_pp_zip = mocker.create_autospec(tool._get_name_of_pp_zip)
        tool._get_name_of_pp_zip.return_value = "PP_Linux_90419df35b7ba347.zip"
        tool._map_arch_value_with_share_directory = mocker.create_autospec(tool._map_arch_value_with_share_directory)
        tool._map_arch_value_with_share_directory.return_value = "x86_64"
        tool._get_correct_pp_directory_url = mocker.create_autospec(tool._get_correct_pp_directory_url)
        tool._get_correct_pp_directory_url.return_value = (
            "https://artifactory-server/artifactory/repo_name/tool/tool_main_3.10/"
            "main_v5.12.0-dev-28-62ca6cd9_py3.10/wrapper_interpreter/Linux"
        )
        assert tool._find_pp_from_url_for_os(OSName.LINUX, CPUArchitecture.X86_64, bsd_release=None) == (
            (
                "https://artifactory-server/artifactory/repo_name/tool/tool_main_3.10/"
                "main_v5.12.0-dev-28-62ca6cd9_py3.10/wrapper_interpreter/Linux"
            ),
            "PP_Linux_90419df35b7ba347.zip",
        )
        tool._map_arch_value_with_share_directory.assert_called_once_with(CPUArchitecture.X86_64)

    def test__find_pp_from_url_for_os(self, tool, mocker):
        response = mocker.create_autospec(Response)
        mocker.patch.object(requests, "get", return_value=response)
        response.text = '<a href="PP_Linux_90419df35b7ba347.zip">   15-Dec-2023 10:09  67.85 MB'
        assert tool._find_pp_from_url_for_os(OSName.LINUX, CPUArchitecture.X86_64, bsd_release=None) == (
            (
                "https://artifactory-server/artifactory/repo_name/tool/tool_main_3.10/"
                "main_v5.12.0-dev-28-62ca6cd9_py3.10/wrapper_interpreter/Linux"
            ),
            "PP_Linux_90419df35b7ba347.zip",
        )

    def test__get_name_of_pp_zip(self, tool, mocker):
        response = mocker.create_autospec(Response)
        get_mock = mocker.patch.object(requests, "get", return_value=response)
        response.text = '<a href="PP_Linux_90419df35b7ba347.zip">   15-Dec-2023 10:09  67.85 MB'
        assert (
            tool._get_name_of_pp_zip(
                "https://artifactory-server/artifactory/repo_name/tool/tool_main_3.10/"
                "main_v5.12.0-dev-28-62ca6cd9_py3.10/wrapper_interpreter/Linux"
            )
            == "PP_Linux_90419df35b7ba347.zip"
        )
        get_mock.assert_called_once_with(
            "https://artifactory-server/artifactory/repo_name/tool/tool_main_3.10/"
            "main_v5.12.0-dev-28-62ca6cd9_py3.10/wrapper_interpreter/Linux",
            cert=tool.certificate,
        )

    def test__find_pp_from_url_for_os_not_found(self, tool, mocker):
        response = mocker.create_autospec(Response)
        mocker.patch.object(requests, "get", return_value=response)
        response.text = "15-Dec-2023 10:09  67.85 MB"
        with pytest.raises(
            MissingPortablePythonOnServerException, match="Could not found correct PP zip in artifactory"
        ):
            tool._find_pp_from_url_for_os(OSName.LINUX, CPUArchitecture.X86_64, bsd_release=None)

    def test__get_future_responder_path(self, tool):
        tool.is_posix = False
        tool.is_esxi = False
        assert (
            tool._get_future_responder_path("c:\\amber_portable_python\\PP_Windows_90419df35b7ba347.zip")
            == "c:\\amber_portable_python\\PP_Windows_90419df35b7ba347\\python.exe"
        )
        tool.is_posix = True
        tool.is_esxi = False
        assert (
            tool._get_future_responder_path("/tmp/amber_portable_python/PP_Linux_90419df35b7ba347.zip")
            == "/tmp/amber_portable_python/PP_Linux_90419df35b7ba347/bin/python"
        )
        tool.is_esxi = True
        tool.esxi_storage_path = "/vmfs/volumes/5bc9d125-9c015531-f0d4-001e6762ca0a"
        assert (
            tool._get_future_responder_path(
                "/vmfs/volumes/5bc9d125-9c015531-f0d4-001e6762ca0a/PP_ESXi_90419df35b7ba347.zip"
            )
            == "/vmfs/volumes/5bc9d125-9c015531-f0d4-001e6762ca0a/PP_ESXi_90419df35b7ba347/bin/python"
        )

    def test__unzip_pp_windows(self, tool, winrm_connection):
        winrm_connection.execute_command.return_value = ConnectionCompletedProcess(args="", stdout="False", stderr="")
        assert (
            tool._unzip_pp_windows(winrm_connection, "c:\\amber_portable_python\\" "PP_Windows_90419df35b7ba347.zip")
            == "c:\\amber_portable_python\\PP_Windows_90419df35b7ba347\\python.exe"
        )

    def test__unzip_pp_windows_already_exist(self, tool, winrm_connection, mocker):
        winrm_connection.execute_command.return_value = ConnectionCompletedProcess(args="", stdout="True", stderr="")
        assert (
            tool._unzip_pp_windows(winrm_connection, "c:\\amber_portable_python\\" "PP_Windows_90419df35b7ba347.zip")
            == "c:\\amber_portable_python\\PP_Windows_90419df35b7ba347\\python.exe"
        )
        calls = [
            mocker.call('powershell.exe Test-Path -Path \\"c:\\amber_portable_python\\PP_Windows_90419df35b7ba347\\"'),
            mocker.call(
                'powershell.exe Remove-Item \\"c:\\amber_portable_python\\PP_Windows_90419df35b7ba347\\" -Recurse '
                "-Force"
            ),
        ]
        winrm_connection.execute_command.assert_has_calls(calls)

    def test__unzip_pp_posix(self, tool, ssh_connection, mocker):
        tool.is_esxi = False
        ssh_connection.execute_command.return_value = ConnectionCompletedProcess(args="", stdout="False", stderr="")
        assert (
            tool._unzip_pp_posix(ssh_connection, "/tmp/amber_portable_python/PP_Linux_90419df35b7ba347.zip")
            == "/tmp/amber_portable_python/PP_Linux_90419df35b7ba347/bin/python"
        )
        calls = [
            mocker.call(
                "unzip -q -n /tmp/amber_portable_python/PP_Linux_90419df35b7ba347.zip "
                "-d /tmp/amber_portable_python/PP_Linux_90419df35b7ba347"
            ),
        ]
        ssh_connection.execute_command.assert_has_calls(calls)

    def test__unzip_pp_posix_esxi(self, tool, ssh_connection, mocker):
        tool.is_esxi = True
        tool.esxi_storage_path = "/vmfs/volumes/5bc9d125-9c015531-f0d4-001e6762ca0a"
        ssh_connection.execute_command.return_value = ConnectionCompletedProcess(args="", stdout="False", stderr="")
        assert (
            tool._unzip_pp_posix(
                ssh_connection, "/vmfs/volumes/5bc9d125-9c015531-f0d4-001e6762ca0a/PP_ESXi_90419df35b7ba347.zip"
            )
            == "/vmfs/volumes/5bc9d125-9c015531-f0d4-001e6762ca0a/PP_ESXi_90419df35b7ba347/bin/python"
        )
        calls = [
            mocker.call(
                "unzip -q -n /vmfs/volumes/5bc9d125-9c015531-f0d4-001e6762ca0a/PP_ESXi_90419df35b7ba347.zip "
                "-d /vmfs/volumes/5bc9d125-9c015531-f0d4-001e6762ca0a/PP_ESXi_90419df35b7ba347"
            ),
        ]
        ssh_connection.execute_command.assert_has_calls(calls)
        ssh_connection.path.return_value.mkdir.assert_called_once_with(parents=True, exist_ok=True)

    def test__check_parameters(self, tool):
        tool.username = "a"
        tool.password = "***"
        tool.artifactory_url = "a"
        tool._check_parameters()

    def test__check_parameters_missing(self, tool):
        tool.username = None
        tool.password = None
        tool.artifactory_url = None
        with pytest.raises(RPyCDeploymentException):
            tool._check_parameters()

    def test__unzip_portable_python_linux(self, tool, ssh_connection, mocker):
        zip_path = PurePath("/tmp/test.zip")
        tool.is_posix = True
        tool._unzip_pp_posix = mocker.create_autospec(tool._unzip_pp_posix)
        tool._unzip_pp_windows = mocker.create_autospec(tool._unzip_pp_windows)
        tool._unzip_portable_python(ssh_connection, zip_path)
        tool._unzip_pp_posix.assert_called_once()
        tool._unzip_pp_windows.assert_not_called()

    def test__unzip_portable_python_windows(self, tool, ssh_connection, mocker):
        zip_path = PurePath("/tmp/test.zip")
        tool.is_posix = False
        tool._unzip_pp_posix = mocker.create_autospec(tool._unzip_pp_posix)
        tool._unzip_pp_windows = mocker.create_autospec(tool._unzip_pp_windows)
        tool._unzip_portable_python(ssh_connection, zip_path)
        tool._unzip_pp_windows.assert_called_once()
        tool._unzip_pp_posix.assert_not_called()

    def test__connect_via_alternative_connection_ssh(self, tool, mocker, ssh_connection):
        ssh_connection._os_type = OSType.POSIX
        mocker.patch("mfd_connect.util.deployment.python_deployment.SSHConnection", return_value=ssh_connection)
        assert isinstance(tool._connect_via_alternative_connection(), SSHConnection)

    def test__connect_via_alternative_connection_winrm(self, tool, mocker, ssh_connection, winrm_connection):
        ssh_connection._os_type = OSType.WINDOWS
        mocker.patch("mfd_connect.util.deployment.python_deployment.SSHConnection", return_value=ssh_connection)
        mocker.patch("mfd_connect.util.deployment.python_deployment.WinRmConnection", return_value=winrm_connection)
        assert isinstance(tool._connect_via_alternative_connection(), WinRmConnection)

    def test__connect_via_alternative_connection_exception(self, tool, mocker, ssh_connection):
        ssh_connection._os_type = OSType.WINDOWS
        mocker.patch(
            "mfd_connect.util.deployment.python_deployment.SSHConnection", side_effect=ModuleFrameworkDesignError
        )
        mocker.patch("mfd_connect.util.deployment.python_deployment.WinRmConnection", side_effect=WinRMException)
        with pytest.raises(RPyCDeploymentException):
            tool._connect_via_alternative_connection()

    def test__start_rpyc_responder(self, tool, mocker, ssh_connection):
        tool._SetupPythonForResponder__start_rpyc_responder = mocker.create_autospec(
            tool._SetupPythonForResponder__start_rpyc_responder
        )
        tool._start_rpyc_responder(ssh_connection, "responder_path")
        tool._SetupPythonForResponder__start_rpyc_responder.assert_called_once_with(ssh_connection, "responder_path")

    def test__start_rpyc_responder_exception(self, tool, mocker, ssh_connection):
        tool._SetupPythonForResponder__start_rpyc_responder = mocker.create_autospec(
            tool._SetupPythonForResponder__start_rpyc_responder
        )
        tool._SetupPythonForResponder__start_rpyc_responder.side_effect = ConnectionCalledProcessError(1, "")
        with pytest.raises(
            RPyCDeploymentException,
            match="Cannot copy portable python from share: "
            "Command '' returned unexpected exit status 1.\n\nstdout: None",
        ):
            tool._start_rpyc_responder(ssh_connection, "responder_path")

    def test__start_rpyc_responder_ssh(self, tool, ssh_connection, mocker):
        responder_path = "/tmp/responder_path"
        log_file = mocker.create_autospec(PurePosixPath)
        path_mock = mocker.create_autospec(Path)
        path_mock.parent.return_value = log_file
        path_mock.touch.return_value = None
        ssh_connection.path.return_value = path_mock
        tool._SetupPythonForResponder__start_rpyc_responder(ssh_connection, responder_path)
        ssh_connection.execute_command.assert_called_once_with(
            "nohup /tmp/responder_path -m mfd_connect.rpyc_server "
            "--port 18817 -l /tmp/amber_portable_python/rpyc_responder.log &",
            discard_stderr=True,
            discard_stdout=True,
            shell=True,
        )

    def test__start_rpyc_responder_winrm(self, tool, winrm_connection, mocker):
        responder_path = "c:\\responder_path"
        log_file = mocker.create_autospec(PurePosixPath)
        path_mock = mocker.create_autospec(Path)
        path_mock.parent.return_value = log_file
        path_mock.touch.return_value = None
        winrm_connection.path.return_value = path_mock
        tool._SetupPythonForResponder__start_rpyc_responder(winrm_connection, responder_path)
        winrm_connection.start_process.assert_called_once_with(
            "c:\\responder_path -m mfd_connect.rpyc_server "
            "--port 18817 > c:\\amber_portable_python\\rpyc_responder.log 2>&1"
        )

    def test__is_rpyc_responder_running_ssh(self, tool, ssh_connection, mocker):
        responder_path = "/tmp/responder_path"
        _is_rpyc_responder_running_ssh = mocker.patch(
            "mfd_connect.util.deployment.python_deployment._is_rpyc_responder_running_ssh"
        )
        tool._is_rpyc_responder_running(ssh_connection, responder_path)
        _is_rpyc_responder_running_ssh.assert_called_once()

    def test__is_rpyc_responder_running_winrm(self, tool, winrm_connection, mocker):
        responder_path = "c:\\responder_path"
        _is_rpyc_responder_running_winrm = mocker.patch(
            "mfd_connect.util.deployment.python_deployment._is_rpyc_responder_running_winrm"
        )
        tool._is_rpyc_responder_running(winrm_connection, responder_path)
        _is_rpyc_responder_running_winrm.assert_called_once()

    def test_prepare_ssh(self, tool, ssh_connection, mocker):
        tool._connect_via_alternative_connection = mocker.create_autospec(
            tool._connect_via_alternative_connection, return_value=ssh_connection
        )
        ssh_connection.get_os_name.return_value = OSName.LINUX
        tool._find_pp_from_url_for_os = mocker.create_autospec(
            tool._find_pp_from_url_for_os, return_value=("url", "filename")
        )
        tool._get_future_responder_path = mocker.create_autospec(
            tool._get_future_responder_path, return_value="/tmp/responder_path"
        )
        tool._is_rpyc_responder_running = mocker.create_autospec(tool._is_rpyc_responder_running, return_value=False)
        ssh_connection.path.return_value.exists.return_value = False
        tool._unzip_portable_python = mocker.create_autospec(tool._unzip_portable_python)
        tool._start_rpyc_responder = mocker.create_autospec(tool._start_rpyc_responder)
        tool.prepare()
        ssh_connection.execute_command.assert_called()
        ssh_connection.download_file_from_url.assert_called()
        tool._unzip_portable_python.assert_called()
        tool._start_rpyc_responder.assert_called()
        ssh_connection.disconnect.assert_called()

    def test_prepare_winrm(self, tool, winrm_connection, mocker):
        tool._connect_via_alternative_connection = mocker.create_autospec(
            tool._connect_via_alternative_connection, return_value=winrm_connection
        )
        winrm_connection.get_os_name.return_value = OSName.WINDOWS
        tool._find_pp_from_url_for_os = mocker.create_autospec(
            tool._find_pp_from_url_for_os, return_value=("url", "filename")
        )
        tool._get_future_responder_path = mocker.create_autospec(
            tool._get_future_responder_path, return_value="c:\\responder_path"
        )
        tool._is_rpyc_responder_running = mocker.create_autospec(tool._is_rpyc_responder_running, return_value=False)
        winrm_connection.path.return_value.exists.return_value = False
        tool._unzip_portable_python = mocker.create_autospec(tool._unzip_portable_python)
        tool._start_rpyc_responder = mocker.create_autospec(tool._start_rpyc_responder)
        tool.prepare()
        winrm_connection.execute_command.assert_called()
        winrm_connection.download_file_from_url.assert_called()
        tool._unzip_portable_python.assert_called()
        tool._start_rpyc_responder.assert_called()
        winrm_connection.disconnect.assert_called()

    def test__map_bitness_value_with_share_directory_aarch64(self, tool):
        assert tool._map_arch_value_with_share_directory(CPUArchitecture.ARM64) == "aarch64"

    def test__map_bitness_value_with_share_directory_os_64bit(self, tool):
        assert tool._map_arch_value_with_share_directory(CPUArchitecture.X86_64) == "x86_64"

    def test__map_bitness_value_with_share_directory_not_supported(self, tool):
        with pytest.raises(MissingPortablePythonOnServerException):
            tool._map_arch_value_with_share_directory(CPUArchitecture.X86)

    def test__get_correct_pp_directory_url_bitness_directory_exists(self, tool, mocker):
        response = mocker.create_autospec(Response)
        response.text = ""
        mocker.patch.object(requests, "get", return_value=response)
        assert (
            tool._get_correct_pp_directory_url(
                "x86_64",
                "https://artifactory-server/artifactory/repo_name/tool/tool_main_3.10/",
            )
            == "https://artifactory-server/artifactory/repo_name/tool/tool_main_3.10/x86_64"
        )

    def test__get_correct_pp_directory_url_bitness_directory_not_exists(self, tool, mocker):
        response = mocker.create_autospec(Response)
        response.text = '<a href="PP_Linux_90419df35b7ba347.zip">   15-Dec-2023 10:09  67.85 MB'
        mocker.patch.object(requests, "get", return_value=response)
        assert (
            tool._get_correct_pp_directory_url(
                "x86_64",
                "https://artifactory-server/artifactory/repo_name/tool/tool_main_3.10/",
            )
            == "https://artifactory-server/artifactory/repo_name/tool/tool_main_3.10/"
        )

    def test__init(self, mocker):
        """Test SetupPythonForResponder initialization."""
        mocker.patch.object(SetupPythonForResponder, "_check_parameters", return_value=None)
        mocker.patch.object(SetupPythonForResponder, "prepare", return_value=None)
        setup = SetupPythonForResponder(
            ip="192.168.1.1",
            username="user",
            password="***",
            artifactory_url="https://example.com/artifactory",
        )
        assert setup.ip == "192.168.1.1"
        assert setup.username == "user"
        assert setup.password == "***"
        assert setup.artifactory_url == "https://example.com/artifactory"
        assert setup.certificate is None
        assert setup.artifactory_username is None
        assert setup.artifactory_password is None
        assert setup.is_posix is None
        assert setup.is_esxi is None
