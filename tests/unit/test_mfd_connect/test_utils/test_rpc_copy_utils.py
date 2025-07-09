# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
from ipaddress import IPv4Address
from pathlib import Path, PurePath
from unittest.mock import patch, call, Mock

import pytest
import os
from mfd_common_libs import log_levels
from mfd_typing import OSName, OSType

from mfd_connect import (
    SolConnection,
    RPyCConnection,
    SSHConnection,
    SerialConnection,
    LocalConnection,
    TunneledSSHConnection,
)
from mfd_connect.base import ConnectionCompletedProcess, Connection
from mfd_connect.exceptions import ModuleFrameworkDesignError, CopyException, ConnectionCalledProcessError
from mfd_connect.util.rpc_copy_utils import (
    _copy_file_pythonic_rpyc,
    copy,
    _copy_local_ssh,
    _copy_remote_ssh,
    _check_paths,
    _copy_file_ftp_rpyc,
    copy_file_ftp_normal_mode,
    copy_file_ftp_reverse_mode,
    _remove_ip_from_known_host,
    _get_hostname,
    _copy_rpyc_wildcard_files,
    _assign_direct_and_tunneled_connection,
    _check_if_ip_is_reachable,
    _ssh_copy_via_tunnel,
    add_known_host,
)


class TestRPCCopyUtils:
    @pytest.fixture()
    def rpyc(self, mocker):
        m = mocker.patch.object(RPyCConnection, "__init__", return_value=None)
        conn = RPyCConnection(ip="10.10.10.10")
        m.stop()
        conn._ip = "10.10.10.10"
        conn._create_connection = mocker.Mock()
        conn._connection = mocker.Mock()
        conn.get_os_name = mocker.Mock(return_value=OSName.LINUX)
        conn._enable_bg_serving_thread = True
        return conn

    @pytest.fixture()
    def second_rpyc(self, mocker):
        m = mocker.patch.object(RPyCConnection, "__init__", return_value=None)
        conn = RPyCConnection(ip="10.10.10.11")
        m.stop()
        conn._ip = "10.10.10.11"
        conn._create_connection = mocker.Mock()
        conn._connection = mocker.Mock()
        conn.get_os_name = mocker.Mock(return_value=OSName.LINUX)
        conn._enable_bg_serving_thread = True
        return conn

    @pytest.fixture()
    def ssh_posix(self, mocker):
        conn = mocker.create_autospec(SSHConnection)
        conn._connection_details = {"hostname": "10.10.10.10", "port": 22, "username": "root", "password": "root"}
        conn.ip = "10.10.10.10"
        conn._os_type = OSType.POSIX
        return conn

    @pytest.fixture()
    def ssh_windows(self, mocker):
        conn = mocker.create_autospec(SSHConnection)
        conn._connection_details = {"hostname": "10.10.10.20", "port": 22, "username": "root", "password": "root"}
        conn.ip = "10.10.10.20"
        conn._os_type = OSType.WINDOWS
        return conn

    @pytest.mark.parametrize(
        "exists, mkdir", [(True, False), (False, True)], ids=["ftp_already_exists", "created_ftp_directory"]
    )
    def test_copy_file_ftp_normal_mode(self, mocker, rpyc, second_rpyc, exists, mkdir, caplog):
        mocker.patch("time.sleep")
        caplog.set_level(log_levels.MODULE_DEBUG)
        second_rpyc.modules, rpyc.modules = mocker.Mock(), mocker.Mock()
        source, target = mocker.create_autospec(Path), mocker.create_autospec(Path)
        source.__str__ = mocker.Mock(return_value="file.txt")
        source.name = "file.txt"
        target.__str__ = mocker.Mock(return_value="file.txt")
        ftp_file_path_mock = mocker.create_autospec(Path)
        ftp_file_path_mock.__str__ = mocker.Mock(return_value="ftp_server_path/file.txt")
        ftp_server_path_mock = mocker.create_autospec(Path)
        ftp_server_path_mock.__str__ = mocker.Mock(return_value="ftp_server_path")
        ftp_server_path_mock.__truediv__.return_value = ftp_file_path_mock
        ftp_server_path_mock.exists.return_value = exists
        source.parent.__truediv__.return_value = ftp_server_path_mock
        copy_file_ftp_normal_mode(rpyc, second_rpyc, source, target, timeout=10)
        server_mock = rpyc.modules.return_value.mfd_ftp.ftp_server.start_server_as_process
        server_mock.assert_called_with(
            IPv4Address("0.0.0.0"),
            18810,
            "ftp_server_path",
            username="ftp",
            password="***",
        )
        client_mock = second_rpyc.modules.return_value.mfd_ftp.ftp_client.Client
        client_mock.assert_called_with(
            IPv4Address("10.10.10.10"),
            18810,
            task="receive",
            source="file.txt",
            destination="file.txt",
            timeout=10,
            username="ftp",
            password="***",
        )
        client_mock.return_value.run.assert_called_once()
        server_mock.return_value.kill.assert_called_once()
        rpyc.modules.return_value.shutil.rmtree.assert_called_once_with(ftp_server_path_mock)
        if mkdir:
            ftp_server_path_mock.mkdir.assert_called_once()
        else:
            ftp_server_path_mock.mkdir.assert_not_called()
        assert (
            "10.10.10.10 -> Copying temp file from file.txt to ftp_server_path/file.txt required by FTP server"
            in caplog.text
        )

    @pytest.mark.parametrize(
        "exists, mkdir", [(True, False), (False, True)], ids=["ftp_already_exists", "created_ftp_directory"]
    )
    def test_copy_file_ftp_reverse_mode(self, mocker, rpyc, second_rpyc, exists, mkdir, caplog):
        caplog.set_level(log_levels.MODULE_DEBUG)
        mocker.patch("time.sleep")
        second_rpyc.modules, rpyc.modules = mocker.Mock(), mocker.Mock()
        source, target = mocker.create_autospec(Path), mocker.create_autospec(Path)
        source.__str__ = mocker.Mock(return_value="file.txt")
        target.name = "file.txt"
        target.__str__ = mocker.Mock(return_value="file.txt")
        ftp_file_path_mock = mocker.create_autospec(Path)
        ftp_file_path_mock.__str__ = mocker.Mock(return_value="ftp_server_path/file.txt")
        ftp_server_path_mock = mocker.create_autospec(Path)
        ftp_server_path_mock.__str__ = mocker.Mock(return_value="ftp_server_path")
        ftp_server_path_mock.__truediv__.return_value = ftp_file_path_mock
        ftp_server_path_mock.exists.return_value = exists
        target.parent.__truediv__.return_value = ftp_server_path_mock
        copy_file_ftp_reverse_mode(rpyc, second_rpyc, source, target, timeout=10)
        server_mock = second_rpyc.modules.return_value.mfd_ftp.ftp_server.start_server_as_process
        server_mock.assert_called_with(
            IPv4Address("0.0.0.0"),
            18810,
            "ftp_server_path",
            username="ftp",
            password="***",
        )
        client_mock = rpyc.modules.return_value.mfd_ftp.ftp_client.Client
        client_mock.assert_called_with(
            IPv4Address("10.10.10.11"),
            18810,
            task="send",
            source="file.txt",
            destination="file.txt",
            timeout=10,
            username="ftp",
            password="***",
        )
        client_mock.return_value.run.assert_called_once()
        server_mock.return_value.kill.assert_called_once()
        second_rpyc.modules.return_value.shutil.rmtree.assert_called_once_with(ftp_server_path_mock)
        if mkdir:
            ftp_server_path_mock.mkdir.assert_called_once()
        else:
            ftp_server_path_mock.mkdir.assert_not_called()
        assert (
            "10.10.10.11 -> Copying file from ftp_server_path/file.txt to file.txt after FTP operations." in caplog.text
        )

    def test___copy_file_ftp_rpyc(self, mocker):
        mocker.patch.object(RPyCConnection, "__init__", return_value=None)
        copy_file_ftp_reverse_mode_mock = mocker.patch("mfd_connect.util.rpc_copy_utils.copy_file_ftp_reverse_mode")
        copy_file_ftp_normal_mode_mock = mocker.patch("mfd_connect.util.rpc_copy_utils.copy_file_ftp_normal_mode")
        src = mocker.create_autospec(RPyCConnection)
        dst = mocker.create_autospec(RPyCConnection)
        src.ip = "127.0.0.1"
        _copy_file_ftp_rpyc(src, dst, mocker.Mock(), mocker.Mock(), 1)
        copy_file_ftp_reverse_mode_mock.assert_called_once()
        copy_file_ftp_normal_mode_mock.assert_not_called()
        copy_file_ftp_reverse_mode_mock.reset_mock()
        copy_file_ftp_normal_mode_mock.reset_mock()
        src.ip = "10.0.0.1"
        _copy_file_ftp_rpyc(src, dst, mocker.Mock(), mocker.Mock(), 1)
        copy_file_ftp_normal_mode_mock.assert_called_once()
        copy_file_ftp_reverse_mode_mock.assert_not_called()

    def test__copy_file_pythonic_rpyc(self, tmp_path, mocker, caplog):
        mocker.patch("mfd_connect.util.rpc_copy_utils.CHUNK_SIZE", 1)
        caplog.set_level(log_levels.MODULE_DEBUG)
        source_file = tmp_path / "source.file"
        target_file = tmp_path / "target.file"
        tested_content = "sample_text"
        number_of_chunks = len(tested_content) + 1  # +1 for extra lof after ending copying
        source_file.write_text(tested_content)
        _copy_file_pythonic_rpyc(source_file, target_file)
        assert target_file.read_text() == tested_content
        assert len(caplog.text.splitlines()) == number_of_chunks

    def test_unsupported_connection(self, mocker):
        rpyc_conn = mocker.create_autospec(RPyCConnection)
        sol_conn = mocker.create_autospec(SolConnection)
        err = "Connection type not supported."
        with pytest.raises(Exception, match=err):
            copy(src_conn=rpyc_conn, dst_conn=sol_conn, source="", target="")

    def test_different_connections_serial_serial(self, mocker):
        serial_conn1 = mocker.create_autospec(SerialConnection)
        serial_conn2 = mocker.create_autospec(SerialConnection)
        err = f"Other copying from/to {str(SerialConnection)} than local/rpyc is not permitted."
        with pytest.raises(Exception, match=err):
            copy(src_conn=serial_conn1, dst_conn=serial_conn2, source="", target="")

    def test_different_connections_serial_local(self, mocker):
        rpyc_conn = mocker.create_autospec(RPyCConnection)
        rpyc_conn._ip = "10.10.10.10"
        serial_conn1 = mocker.create_autospec(SerialConnection)
        serial_conn1._remote_host = rpyc_conn
        serial_conn1._ip = "serial"
        local_conn = mocker.create_autospec(LocalConnection)
        local_conn._ip = "localhost"
        mocker.patch("mfd_connect.util.rpc_copy_utils._copy_from_serial_to_target", mocker.Mock())
        copy(src_conn=serial_conn1, dst_conn=local_conn, source="", target="")

    def test_connections_rpyc_rpyc_wildcard(self, mocker):
        rpyc_conn1 = mocker.create_autospec(RPyCConnection)
        rpyc_conn2 = mocker.create_autospec(RPyCConnection)
        mock_copy_files = mocker.patch("mfd_connect.util.rpc_copy_utils._copy_rpyc_wildcard_files", mocker.Mock())
        mocker.patch("mfd_connect.util.rpc_copy_utils._copy_remote", mocker.Mock())
        rpyc_conn1.path.side_effect = [
            Path(os.path.normpath("/path/to/source/*.pkg")),
        ]
        rpyc_conn2.path.side_effect = [
            Path(os.path.normpath("/path/to/destination/")),
        ]
        mocker.patch("mfd_connect.util.rpc_copy_utils._get_hostname", side_effect=["hostname1", "hostname2"])
        copy(src_conn=rpyc_conn1, dst_conn=rpyc_conn2, source="/path/to/source/*.pkg", target="/path/to/destination/")
        mock_copy_files.assert_called_once_with(
            rpyc_conn1,
            rpyc_conn2,
            Path(os.path.normpath("/path/to/source/*.pkg")),
            Path(os.path.normpath("/path/to/destination/")),
            "hostname1",
            "hostname2",
            600,
        )

    def test__copy_rpyc_wildcard_files(self, mocker, rpyc):
        rpyc_conn1 = mocker.create_autospec(RPyCConnection)
        rpyc_conn2 = mocker.create_autospec(RPyCConnection)
        rpyc_conn1.modules.return_value.glob.glob.return_value = [
            os.path.normpath("/path/to/source/file1.pkg"),
            os.path.normpath("/path/to/source/file2.pkg"),
        ]

        rpyc_conn1.path.side_effect = [
            Path(os.path.normpath("/path/to/source/file1.pkg")),
            Path(os.path.normpath("/path/to/source/file2.pkg")),
        ]
        rpyc_conn2.path.side_effect = [
            Path(os.path.normpath("/path/to/destination/file1.pkg")),
            Path(os.path.normpath("/path/to/destination/file1.pkg")),
            Path(os.path.normpath("/path/to/destination/file2.pkg")),
            Path(os.path.normpath("/path/to/destination/file2.pkg")),
        ]

        mock_copy_remote = mocker.patch("mfd_connect.util.rpc_copy_utils._copy_remote", side_effect=[None, None])

        _copy_rpyc_wildcard_files(
            src_conn=rpyc_conn1,
            dst_conn=rpyc_conn2,
            source=os.path.normpath("/path/to/source/*.pkg"),
            target=os.path.normpath("/path/to/destination/"),
            src_hostname="hostname1",
            dst_hostname="hostname2",
            timeout=600,
        )
        rpyc_conn1.modules().glob.glob.assert_called_once_with(os.path.normpath("/path/to/source/*.pkg"))
        assert mock_copy_remote.call_count == 2
        calls = [
            call(
                src_conn=rpyc_conn1,
                dst_conn=rpyc_conn2,
                source=Path("/path/to/source/file1.pkg"),
                target=Path("/path/to/destination/file1.pkg"),
                timeout=600,
            ),
            call(
                src_conn=rpyc_conn1,
                dst_conn=rpyc_conn2,
                source=Path("/path/to/source/file2.pkg"),
                target=Path("/path/to/destination/file2.pkg"),
                timeout=600,
            ),
        ]
        mock_copy_remote.assert_has_calls(calls, any_order=True)

    def test__copy_rpyc_wildcard_files_same_hostname(self, mocker):
        rpyc_conn1 = mocker.create_autospec(RPyCConnection)
        rpyc_conn2 = mocker.create_autospec(RPyCConnection)
        source = "/path/to/source/*.pkg"
        target = "/path/to/target/"
        rpyc_conn1.modules.return_value.glob.glob.return_value = [
            "/path/to/source/file1.pkg",
            "/path/to/source/file2.pkg",
        ]
        mock_shutil = Mock()
        rpyc_conn1.modules.return_value.shutil = mock_shutil

        _copy_rpyc_wildcard_files(
            src_conn=rpyc_conn1,
            dst_conn=rpyc_conn2,
            source=source,
            target=target,
            src_hostname="hostname1",
            dst_hostname="hostname1",
            timeout=600,
        )
        expected_calls = [
            call("/path/to/source/file1.pkg", "/path/to/target/"),
            call("/path/to/source/file2.pkg", "/path/to/target/"),
        ]
        mock_shutil.copy.assert_has_calls(expected_calls, any_order=True)
        assert mock_shutil.copy.call_count == 2

    def test_copy_local_ssh_posix(self, mocker):
        src_conn = mocker.create_autospec(SSHConnection)
        src_conn._os_type = OSType.POSIX
        source = "/root/file.txt"
        target = "/root/copied_file.txt"
        _copy_local_ssh(src_conn=src_conn, source=source, target=target)
        command = f"cp -rP {source} {target}"
        src_conn.execute_command.assert_called_with(command=command, cwd="/")

    def test_copy_local_ssh_windows(self, mocker, caplog):
        caplog.set_level(log_levels.MODULE_DEBUG)
        src_conn = mocker.create_autospec(SSHConnection)
        src_conn._os_type = OSType.WINDOWS
        source = Path(r"C:\test")
        target = Path(r"C:\copied_test")

        with patch.object(Path, "is_file") as mock_isdir:
            mock_isdir.return_value = True
            _copy_local_ssh(src_conn=src_conn, source=source, target=target)
        command = r"copy C:\test C:\copied_test"
        src_conn.execute_command.assert_called_with(command=command)

        with patch.object(Path, "is_dir") as mock_isdir:
            mock_isdir.return_value = True
            _copy_local_ssh(src_conn=src_conn, source=source, target=target)
        command = r"xcopy /E /I C:\test C:\copied_test"
        src_conn.execute_command.assert_called_with(command=command)
        assert "Successfully copied" in caplog.text

    def test_copy_remote_ssh_windows(self, mocker):
        src_conn = dst_conn = mocker.create_autospec(SSHConnection)
        src_conn._os_type = dst_conn._os_type = OSType.WINDOWS
        dst_conn._connection_details = {"username": "user", "password": "pass"}
        dst_conn._ip = "10.10.10.20"
        dst_conn.ip = dst_conn._ip
        source = Path(r"C:\test_dir")
        target = Path(r"C:\copied_test_dir")
        _copy_remote_ssh(src_conn=src_conn, dst_conn=dst_conn, source=source, target=target)
        source = source.as_posix() if dst_conn._os_type == OSType.WINDOWS else source
        command = rf"echo y | pscp -r -scp -pw pass {source} user@10.10.10.20:C:\copied_test_dir"
        src_conn.execute_command.assert_called_with(command=command, shell=True)

    def test_copy_remote_ssh_windows_dst(self, mocker):
        src_conn = mocker.create_autospec(SSHConnection)
        dst_conn = mocker.create_autospec(LocalConnection)
        mocker.patch("mfd_connect.util.rpc_copy_utils._check_if_ip_is_reachable", return_value=True)
        src_conn._os_type = OSType.POSIX
        dst_conn._os_type = OSType.WINDOWS
        src_conn._connection_details = {"username": "user", "password": "pass"}
        src_conn._ip = "10.10.10.20"
        src_conn.ip = src_conn._ip
        source = PurePath("/root/test_dir")
        target = PurePath(r"C:\copied_test_dir")
        _copy_remote_ssh(src_conn=src_conn, dst_conn=dst_conn, source=source, target=target)
        command = f"echo y | pscp -r -scp -pw pass user@10.10.10.20:{source} {target.as_posix()}"
        dst_conn.execute_command.assert_called_with(command=command, shell=True)

    def test_copy_remote_ssh_posix(self, mocker):
        src_conn = dst_conn = mocker.create_autospec(SSHConnection)
        src_conn._os_type = dst_conn._os_type = OSType.POSIX
        dst_conn._connection_details = {"username": "user", "password": "pass"}
        dst_conn._ip = "10.10.10.20"
        dst_conn.ip = dst_conn._ip
        source = "/root/test"
        target = "/root/copied_test"
        _copy_remote_ssh(src_conn=src_conn, dst_conn=dst_conn, source=source, target=target)

        calls = [
            call(command="ping -n 1 10.10.10.20", shell=True),
            call(r"ssh-keyscan -p 22 10.10.10.20 >> ~/.ssh/known_hosts", cwd="/", shell=True),
            call(
                r'sshpass -p "pass" scp -o StrictHostKeyChecking=no -r '
                r"/root/test user@10.10.10.20:/root/copied_test",
                cwd="/",
                shell=True,
            ),
            call("sed -i '/10.10.10.20/d' ~/.ssh/known_hosts", shell=True),
        ]
        src_conn.execute_command.assert_has_calls(calls)

    def test_source_not_exist(self, mocker):
        ssh_conn = mocker.create_autospec(SSHConnection)
        source = Path(r"C:\test_dir")
        target = Path(r"C:\copied_test_dir")

        with patch.object(Path, "exists") as mock_exists:
            with pytest.raises(Exception) as err:
                mock_exists.return_value = False
                _check_paths(dst_conn=ssh_conn, source=source, target=target)
            assert str(err.value) == r"'C:\test_dir' does not exist on source machine!"

    def test_target_exist(self, mocker, caplog):
        caplog.set_level(log_levels.MODULE_DEBUG)
        ssh_conn = mocker.create_autospec(SSHConnection)
        source = Path(r"C:\test_dir")
        target = Path(r"C:\copied_test_dir")

        with patch.object(Path, "exists") as mock_exists:
            mock_exists.return_value = True
            with patch.object(Path, "is_file") as mock_is_file:
                mock_is_file.return_value = True
                _check_paths(dst_conn=ssh_conn, source=source, target=target)
        assert r"'C:\copied_test_dir' already exists on target machine - file will be override" in caplog.text

    def test_remove_ip_from_known_host(self, ssh_posix):
        _remove_ip_from_known_host(ssh_posix, "10.10.10.20")
        ssh_posix.execute_command.assert_called_once_with("sed -i '/10.10.10.20/d' ~/.ssh/known_hosts", shell=True)

    def test_remove_ip_from_known_host_called_posix_src(self, ssh_posix, ssh_windows):
        copy(ssh_posix, ssh_windows, "test.txt", "test.txt")
        ssh_posix.execute_command.assert_called_with("sed -i '/10.10.10.20/d' ~/.ssh/known_hosts", shell=True)

    def test_remove_ip_from_known_host_called_windows_src(self, ssh_posix, ssh_windows):
        copy(ssh_windows, ssh_posix, "test.txt", "test.txt")
        ssh_posix.execute_command.assert_called_with("sed -i '/10.10.10.20/d' ~/.ssh/known_hosts", shell=True)

    def test__get_hostname(self, ssh_posix):
        ssh_posix.execute_command.side_effect = [
            ConnectionCompletedProcess(args="", return_code=1),
            ConnectionCompletedProcess(args="", return_code=0, stdout="hostname1"),
        ]
        hostname = _get_hostname(ssh_posix)
        assert hostname == "hostname1"

    def test__get_hostname_unavailable(self, ssh_posix):
        ssh_posix.execute_command.side_effect = [
            ConnectionCompletedProcess(args="", return_code=1),
            ConnectionCompletedProcess(args="", return_code=1),
        ]
        with pytest.raises(Exception):
            _get_hostname(ssh_posix)

    def test__remove_ip_from_known_host(self, mocker):
        conn = mocker.create_autospec(SSHConnection)
        ip = "10.10.10.20"
        _remove_ip_from_known_host(conn, ip)
        conn.execute_command.assert_called_once_with("sed -i '/10.10.10.20/d' ~/.ssh/known_hosts", shell=True)

    def test__remove_ip_from_known_host_exception(self, mocker):
        conn = mocker.create_autospec(SSHConnection)
        conn.execute_command.side_effect = Exception
        with pytest.raises(ModuleFrameworkDesignError):
            _remove_ip_from_known_host(conn, "10.10.10.10")

    def test_define_direct_and_tunnel_connection(self, mocker):
        direct_conn = mocker.create_autospec(SSHConnection)
        tunneled_conn = mocker.create_autospec(TunneledSSHConnection)

        # Test when src_conn is tunneled
        result = _assign_direct_and_tunneled_connection(tunneled_conn, direct_conn)
        assert result == (direct_conn, tunneled_conn)

        # Test when dst_conn is tunneled
        result = _assign_direct_and_tunneled_connection(direct_conn, tunneled_conn)
        assert result == (direct_conn, tunneled_conn)

        # Test when neither connection is tunneled
        with pytest.raises(CopyException, match="One of connections needs to be tunneled SSH connection."):
            _assign_direct_and_tunneled_connection(direct_conn, direct_conn)

    @pytest.mark.parametrize("os_type, ping_option", [(OSType.POSIX, "-c"), (OSType.WINDOWS, "-n")])
    def test__check_if_ip_is_reachable_success(self, mocker, os_type, ping_option):
        conn = mocker.create_autospec(Connection)
        conn.get_os_type.return_value = os_type
        conn.execute_command.return_value = None  # Simulate successful command execution

        result = _check_if_ip_is_reachable(conn, "10.10.10.20")
        conn.execute_command.assert_called_once_with(command=f"ping {ping_option} 1 10.10.10.20", shell=True)
        assert result is True

    @pytest.mark.parametrize("os_type, ping_option", [(OSType.POSIX, "-c"), (OSType.WINDOWS, "-n")])
    def test__check_if_ip_is_reachable_failure(self, mocker, os_type, ping_option):
        conn = mocker.create_autospec(Connection)
        conn.get_os_type.return_value = os_type
        conn.execute_command.side_effect = ConnectionCalledProcessError(returncode=1, cmd="")
        # Simulate command failure

        result = _check_if_ip_is_reachable(conn, "10.10.10.20")
        conn.execute_command.assert_called_once_with(command=f"ping {ping_option} 1 10.10.10.20", shell=True)
        assert result is False

    def test__copy_remote_ssh_not_supported_connections(self, mocker):
        with pytest.raises(ModuleFrameworkDesignError, match="Not supported Connection type used for remote copying."):
            _copy_remote_ssh(mocker.create_autospec(SolConnection), mocker.create_autospec(SolConnection), "", "")

    def test__copy_remote_ssh_both_tunnel(self, mocker):
        with pytest.raises(ModuleFrameworkDesignError, match="Both connections can't be tunneled SSH connections."):
            _copy_remote_ssh(
                mocker.create_autospec(TunneledSSHConnection), mocker.create_autospec(TunneledSSHConnection), "", ""
            )

    def test__copy_remote_ssh_not_reachable(self, mocker):
        src_conn, dst_conn = mocker.create_autospec(SSHConnection), mocker.create_autospec(SSHConnection)
        mocker.patch("mfd_connect.util.rpc_copy_utils._check_if_ip_is_reachable", return_value=False)
        with pytest.raises(
            ModuleFrameworkDesignError, match="Source machine can't communicate " "with destination machine."
        ):
            _copy_remote_ssh(src_conn, dst_conn, "", "")

    def test__copy_remote_ssh_not_reachable_tunnel(self, mocker):
        src_conn, dst_conn = (
            mocker.create_autospec(SSHConnection),
            mocker.create_autospec(TunneledSSHConnection, _tunnel=mocker.Mock(ssh_host="1.1.1.1")),
        )
        dst_conn.ip = "10.10.10.10"
        assign_mock = mocker.patch(
            "mfd_connect.util.rpc_copy_utils._assign_direct_and_tunneled_connection", return_value=(src_conn, dst_conn)
        )
        check_ip_mock = mocker.patch("mfd_connect.util.rpc_copy_utils._check_if_ip_is_reachable", return_value=False)
        with pytest.raises(
            ModuleFrameworkDesignError, match="Source machine can't communicate " "with destination machine."
        ):
            _copy_remote_ssh(src_conn, dst_conn, "", "")
            assign_mock.assert_called_once_with(src_conn, dst_conn)
            check_ip_mock.assert_has_calls([call(src_conn, "10.10.10.10"), call(src_conn, "1.1.1.1")])

    def test__copy_remote_ssh__tunnel(self, mocker):
        src_conn, dst_conn = (
            mocker.create_autospec(SSHConnection),
            mocker.create_autospec(TunneledSSHConnection, _tunnel=mocker.Mock(ssh_host="1.1.1.1")),
        )
        copy_mock = mocker.patch("mfd_connect.util.rpc_copy_utils._ssh_copy_via_tunnel")
        dst_conn.ip = "10.10.10.10"
        assign_mock = mocker.patch(
            "mfd_connect.util.rpc_copy_utils._assign_direct_and_tunneled_connection", return_value=(src_conn, dst_conn)
        )
        check_ip_mock = mocker.patch(
            "mfd_connect.util.rpc_copy_utils._check_if_ip_is_reachable", side_effect=[False, True]
        )
        _copy_remote_ssh(src_conn, dst_conn, "", "")
        assign_mock.assert_called_once_with(src_conn, dst_conn)
        check_ip_mock.assert_has_calls([call(src_conn, "10.10.10.10"), call(src_conn, "1.1.1.1")])
        copy_mock.assert_called_once_with(src_conn, dst_conn, "", "")

    def test__ssh_copy_via_tunnel(self, mocker):
        src_conn = mocker.create_autospec(SSHConnection)
        src_conn._os_type = OSType.POSIX
        src_conn.get_os_name.return_value = OSName.LINUX
        dst_conn = mocker.create_autospec(TunneledSSHConnection, _tunnel=mocker.Mock())
        assign_mock = mocker.patch(
            "mfd_connect.util.rpc_copy_utils._assign_direct_and_tunneled_connection", return_value=(src_conn, dst_conn)
        )
        dst_conn._tunnel.ssh_username = "user"
        dst_conn._tunnel.ssh_password = "pass"
        dst_conn._connection_details = {"username": "user", "password": "pass"}
        dst_conn._tunnel.tunnel_bindings = {("1.1.1.1", 22): "a"}
        dst_conn._tunnel.ssh_port = 22
        dst_conn._tunnel.ssh_host = "1.1.1.1"
        add_known_host_mock = mocker.patch("mfd_connect.util.rpc_copy_utils.add_known_host")
        remove_ip_mock = mocker.patch("mfd_connect.util.rpc_copy_utils._remove_ip_from_known_host")
        dst_conn._os_type = OSType.POSIX

        _ssh_copy_via_tunnel(src_conn, dst_conn, PurePath("/root/a").as_posix(), PurePath("/root/b").as_posix())
        add_known_host_mock.assert_has_calls(
            [
                call(ip="1.1.1.1", port=22, connection=src_conn, shell=True),
                call(ip=IPv4Address("127.0.0.1"), port=5022, connection=src_conn, shell=True),
            ]
        )
        assign_mock.assert_called_once_with(src_conn, dst_conn)
        remove_ip_mock.assert_has_calls([call(src_conn, IPv4Address("127.0.0.1")), call(src_conn, "1.1.1.1")])
        src_conn.start_process.return_value.kill.assert_called_once_with(wait=1)
        src_conn.execute_command.assert_called_with(
            command='sshpass -p "pass" scp -o ' "StrictHostKeyChecking=no -r -P 5022 " "/root/a user@127.0.0.1:/root/b",
            cwd="/",
            shell=True,
        )

    def test__ssh_copy_via_tunnel_not_supported(self, mocker):
        src_conn = mocker.create_autospec(SSHConnection)
        src_conn._os_type = OSType.WINDOWS
        src_conn.get_os_name.return_value = OSName.LINUX
        dst_conn = mocker.create_autospec(TunneledSSHConnection, _tunnel=mocker.Mock())
        mocker.patch(
            "mfd_connect.util.rpc_copy_utils._assign_direct_and_tunneled_connection", return_value=(src_conn, dst_conn)
        )
        dst_conn._tunnel.ssh_username = "user"
        dst_conn._tunnel.ssh_password = "pass"
        dst_conn._connection_details = {"username": "user", "password": "pass"}
        dst_conn._tunnel.tunnel_bindings = {("1.1.1.1", 22): "a"}
        dst_conn._tunnel.ssh_port = 22
        dst_conn._tunnel.ssh_host = "1.1.1.1"
        dst_conn._os_type = OSType.POSIX
        with pytest.raises(
            CopyException,
            match="Not supported Connection type used for remote copying. " "One of connections needs to be Posix",
        ):
            _ssh_copy_via_tunnel(src_conn, dst_conn, PurePath("/root/a").as_posix(), PurePath("/root/b").as_posix())

    def test__ssh_copy_via_tunnel_tunnel_source(self, mocker):
        dst_conn = mocker.create_autospec(SSHConnection)
        dst_conn._os_type = OSType.POSIX
        dst_conn.get_os_name.return_value = OSName.LINUX
        src_conn = mocker.create_autospec(TunneledSSHConnection, _tunnel=mocker.Mock())
        assign_mock = mocker.patch(
            "mfd_connect.util.rpc_copy_utils._assign_direct_and_tunneled_connection", return_value=(dst_conn, src_conn)
        )
        src_conn._tunnel.ssh_username = "user"
        src_conn._tunnel.ssh_password = "pass"
        src_conn._connection_details = {"username": "user", "password": "pass"}
        src_conn._tunnel.tunnel_bindings = {("1.1.1.1", 22): "a"}
        src_conn._tunnel.ssh_port = 22
        src_conn._tunnel.ssh_host = "1.1.1.1"
        add_known_host_mock = mocker.patch("mfd_connect.util.rpc_copy_utils.add_known_host")
        remove_ip_mock = mocker.patch("mfd_connect.util.rpc_copy_utils._remove_ip_from_known_host")
        src_conn._os_type = OSType.POSIX

        _ssh_copy_via_tunnel(src_conn, dst_conn, PurePath("/root/a").as_posix(), PurePath("/root/b").as_posix())
        add_known_host_mock.assert_has_calls(
            [
                call(ip="1.1.1.1", port=22, connection=dst_conn, shell=True),
                call(ip=IPv4Address("127.0.0.1"), port=5022, connection=dst_conn, shell=True),
            ]
        )
        assign_mock.assert_called_once_with(src_conn, dst_conn)
        remove_ip_mock.assert_has_calls([call(dst_conn, IPv4Address("127.0.0.1")), call(dst_conn, "1.1.1.1")])
        dst_conn.start_process.return_value.kill.assert_called_once_with(wait=1)
        dst_conn.execute_command.assert_called_with(
            command='sshpass -p "pass" scp -o StrictHostKeyChecking=no ' "-r -P 5022 user@127.0.0.1:/root/a /root/b",
            cwd="/",
            shell=True,
        )

    def test_add_known_host(self, mocker):
        src_conn = mocker.create_autospec(SSHConnection)
        src_conn.path = mocker.Mock()
        src_conn.path.return_value.expanduser.return_value.exists.return_value = False
        add_known_host(ip="127.0.0.1", port=22, connection=src_conn, shell=True)
        src_conn.path.return_value.expanduser.return_value.mkdir.assert_called_once_with(parents=True, exist_ok=True)
        src_conn.path.assert_called_once_with("~/.ssh")
        src_conn.execute_command.assert_called_with(
            r"ssh-keyscan -p 22 127.0.0.1 >> ~/.ssh/known_hosts", cwd="/", shell=True
        )
