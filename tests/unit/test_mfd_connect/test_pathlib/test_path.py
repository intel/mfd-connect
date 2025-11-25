# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
import sys
from textwrap import dedent

import pytest
from mfd_typing.os_values import OSName, OSType

from mfd_connect.base import ConnectionCompletedProcess
from mfd_connect.exceptions import ModuleFrameworkDesignError
from mfd_connect.pathlib.path import (
    CustomWindowsPath,
    CustomPath,
    CustomPosixPath,
    CustomEFIShellPath,
    custom_path_factory,
)


class TestCustomPath:
    @pytest.fixture
    def custom_path_instance(self, mocker):
        obj = object.__new__(CustomPath)
        obj._owner = mocker.Mock()
        return obj

    @pytest.mark.skipif(sys.version_info > (3, 10), reason="requires python3.10")
    @pytest.mark.parametrize(
        "os_type, os_name,expected_class",
        [
            (OSType.WINDOWS, OSName.WINDOWS, CustomWindowsPath),
            (OSType.POSIX, OSName.LINUX, CustomPosixPath),
            (OSType.POSIX, OSName.EFISHELL, CustomEFIShellPath),
        ],
    )
    def test_correct_class_factory(self, mocker, os_type, os_name, expected_class):
        mock_conn = mocker.Mock()
        mock_conn.get_os_type.return_value = os_type
        mock_conn.get_os_name.return_value = os_name
        path = CustomPath("a", owner=mock_conn)
        assert isinstance(path, expected_class)

    @pytest.mark.parametrize("expected_class", [CustomWindowsPath, CustomPosixPath, CustomEFIShellPath])
    def test_correct_class_direct(self, mocker, expected_class):
        mock_conn = mocker.Mock()
        path = expected_class("a", owner=mock_conn)
        assert isinstance(path, expected_class)

    def test_from_parsed_parts_py3_12_sets_attrs_and_returns(self, monkeypatch, custom_path_instance, mocker):
        # Simulate Python >= 3.12
        monkeypatch.setattr(sys, "version_info", (3, 13, 0))
        drv, root, tail = "C:", "\\", ("folder", "file.txt")
        formatted = "C:\\folder\\file.txt"

        # Patch _format_parsed_parts to return a known value
        custom_path_instance._format_parsed_parts = mocker.Mock(return_value=formatted)

        # Patch custom_path_factory to return a mock path object
        path_mock = mocker.Mock()
        cpf = mocker.patch("mfd_connect.pathlib.path.custom_path_factory", return_value=path_mock)
        result = CustomPath._from_parsed_parts_py3_12(custom_path_instance, drv, root, tail)
        cpf.assert_called_once_with(formatted, owner=custom_path_instance._owner)
        assert path_mock._drv == drv
        assert path_mock._root == root
        assert path_mock._tail_cached == tail
        assert result is path_mock

    @pytest.mark.skipif(sys.version_info > (3, 12), reason="requires python3.11 or lower")
    def test_parent_pre312_root_returns_self(self, custom_path_instance):
        custom_path_instance._drv = "C:"
        custom_path_instance._root = "\\"
        custom_path_instance._parts = ("C:\\",)
        assert custom_path_instance.parent is custom_path_instance

    @pytest.mark.skipif(sys.version_info > (3, 12), reason="requires python3.11 or lower")
    def test_parent_pre312_nonroot_calls_from_parsed_parts(self, custom_path_instance, mocker):
        custom_path_instance._drv = "C:"
        custom_path_instance._root = "\\"
        custom_path_instance._parts = ("C:\\", "folder", "file.txt")
        fpp = mocker.patch.object(CustomPath, "_from_parsed_parts", return_value="parent_path")
        result = custom_path_instance.parent
        fpp.assert_called_once_with("C:", "\\", ("C:\\", "folder"), custom_path_instance._owner)
        assert result == "parent_path"

    @pytest.mark.skipif(sys.version_info < (3, 12), reason="requires python3.12 or higher")
    def test_parent_312_tail_empty_returns_self(self, mocker):
        mock_conn = mocker.Mock()
        custom_path = CustomPosixPath("/", owner=mock_conn)
        custom_path._drv = ""
        custom_path._root = "/"
        assert custom_path.parent is custom_path

    @pytest.mark.skipif(sys.version_info < (3, 12), reason="requires python3.12 or higher")
    def test_parent_312_tail_not_empty_calls_from_parsed_parts_py3_12(self, mocker):
        mock_conn = mocker.Mock()
        custom_path = CustomPosixPath("/home/user/dir", owner=mock_conn)
        fpp = mocker.patch.object(CustomPath, "_from_parsed_parts_py3_12", return_value="parent_path")
        result = custom_path.parent
        fpp.assert_called_once_with("", "/", ["home", "user"])
        assert result == "parent_path"


class TestCustomPosixPath:
    @pytest.fixture()
    def custom_posix_path(self, mocker):
        mock_conn = mocker.Mock()
        return CustomPosixPath("a", owner=mock_conn)

    def test_exists(self, custom_posix_path):
        custom_posix_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=0, args="command", stdout="stdout", stderr="stderr"
        )
        assert custom_posix_path.exists() is True

    def test_exists_failure(self, custom_posix_path):
        custom_posix_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=127, args="command", stdout="stdout", stderr="stderr"
        )
        assert custom_posix_path.exists() is False

    def test_exists_failure_in_stderr(self, custom_posix_path):
        custom_posix_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=1, args="command", stdout="stdout", stderr="permission denied"
        )
        with pytest.raises(ModuleFrameworkDesignError):
            custom_posix_path.exists()

    def test_exists_failure_in_stdout(self, custom_posix_path):
        custom_posix_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=1, args="command", stdout="permission denied"
        )
        with pytest.raises(ModuleFrameworkDesignError):
            custom_posix_path.exists()

    @pytest.mark.skipif(sys.version_info > (3, 12), reason="requires python3.11 or lower")
    def test_expanduser_pre312(self, mocker):
        mock_conn = mocker.Mock()
        mock_conn.execute_command.return_value = ConnectionCompletedProcess(
            return_code=0, args="command", stdout="/home/test", stderr="stderr"
        )
        path = CustomPosixPath("~/a", owner=mock_conn)
        assert path.expanduser() == CustomPosixPath("/home/test/a", owner=mock_conn)

    @pytest.mark.skipif(sys.version_info < (3, 12), reason="requires python3.12 or higher")
    def test_expanduser_post312(self, mocker):
        mock_conn = mocker.Mock()
        mock_conn.execute_command.return_value = ConnectionCompletedProcess(
            return_code=0, args="command", stdout="/home/test", stderr="stderr"
        )
        path = CustomPosixPath("~/a", owner=mock_conn)
        assert path.expanduser() == CustomPosixPath("/home/test/a", owner=mock_conn)

    def test_expanduser_no_tilde(self, mocker):
        mock_conn = mocker.Mock()
        mock_conn.execute_command.return_value = ConnectionCompletedProcess(
            return_code=0, args="command", stdout="/home/test", stderr="stderr"
        )
        path = CustomPosixPath("/a", owner=mock_conn)
        assert path.expanduser() == path

    def test_is_file(self, custom_posix_path):
        custom_posix_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=0, args="command", stdout="-rwx------. 1 root root 2655 Aug 13 05:01 id_rsa", stderr="stderr"
        )
        assert custom_posix_path.is_file() is True

    def test_is_file_no_exists(self, custom_posix_path):
        custom_posix_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=127,
            args="command",
            stdout="ls: cannot access 'id_rsaa': No such file or directory",
            stderr="stderr",
        )
        assert custom_posix_path.is_file() is False

    def test_is_dir_exists_but_not_dir(self, custom_posix_path):
        custom_posix_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=0,
            args="command",
            stdout="-rwxr-xr-x. 13 root root 225 Oct  1 06:27 tests.txt",
            stderr="stderr",
        )
        assert custom_posix_path.is_dir() is False

    def test_is_dir_no_exists(self, custom_posix_path):
        custom_posix_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=127,
            args="command",
            stdout="ls: cannot access 'tests': No such file or directory",
            stderr="stderr",
        )
        assert custom_posix_path.is_file() is False

    def test_is_dir(self, custom_posix_path):
        custom_posix_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=0, args="command", stdout="drwxr-xr-x. 13 root root 225 Oct  1 06:27 tests", stderr="stderr"
        )
        assert custom_posix_path.is_dir() is True

    def test_chmod(self, custom_posix_path, mocker):
        custom_posix_path._owner.execute_command = mocker.Mock()
        custom_posix_path.chmod(0o775)
        custom_posix_path._owner.execute_command.assert_called_once_with("chmod 775 a", expected_return_codes=None)

    def test_mkdir_exists(self, custom_posix_path, mocker):
        custom_posix_path.exists = mocker.Mock(return_value=True)
        with pytest.raises(FileExistsError):
            custom_posix_path.mkdir()

    def test_mkdir_exists_no_check_posix(self, custom_posix_path, mocker):
        custom_posix_path.exists = mocker.Mock(return_value=True)
        custom_posix_path._owner.execute_command = mocker.Mock(return_value=mocker.Mock(stderr=""))
        custom_posix_path.mkdir(exist_ok=True)
        custom_posix_path._owner.execute_command.assert_has_calls(
            [
                mocker.call("mkdir a", expected_return_codes=None),
                mocker.call("chmod 777 a", expected_return_codes=None),
            ],
        )
        assert custom_posix_path._owner.execute_command.call_count == 2

    def test_mkdir(self, custom_posix_path, mocker):
        custom_posix_path.exists = mocker.Mock(return_value=False)
        custom_posix_path._owner.execute_command = mocker.Mock(return_value=mocker.Mock(stderr=""))
        custom_posix_path.mkdir()
        custom_posix_path._owner.execute_command.assert_has_calls(
            [
                mocker.call("mkdir a", expected_return_codes=None),
                mocker.call("chmod 777 a", expected_return_codes=None),
            ],
        )
        assert custom_posix_path._owner.execute_command.call_count == 2

    def test_mkdir_failure_in_stderr(self, custom_posix_path, mocker):
        custom_posix_path.exists = mocker.Mock(return_value=False)
        custom_posix_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=1, args="command", stdout="stdout", stderr="cannot create directory"
        )
        with pytest.raises(ModuleFrameworkDesignError):
            custom_posix_path.mkdir()

    def test_mkdir_failure_in_stdout(self, custom_posix_path, mocker):
        custom_posix_path.exists = mocker.Mock(return_value=False)
        custom_posix_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=1, args="command", stdout="cannot create directory"
        )
        with pytest.raises(ModuleFrameworkDesignError):
            custom_posix_path.mkdir()

    def test_mkdir_parents(self, custom_posix_path, mocker):
        custom_posix_path.exists = mocker.Mock(return_value=False)
        custom_posix_path._owner.execute_command = mocker.Mock(return_value=mocker.Mock(stderr=""))
        custom_posix_path.mkdir(parents=True)
        custom_posix_path._owner.execute_command.assert_has_calls(
            [
                mocker.call("mkdir a -p", expected_return_codes=None),
                mocker.call("chmod 777 a", expected_return_codes=None),
            ],
        )
        assert custom_posix_path._owner.execute_command.call_count == 2

    def test_rename(self, custom_posix_path, mocker):
        expected_path = CustomPosixPath("c", owner=mocker.Mock())
        expected_path.exists = mocker.Mock()
        expected_path.exists.return_value = False
        custom_posix_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=0, args="command", stdout="", stderr="stderr"
        )
        assert custom_posix_path.rename(expected_path) == expected_path
        custom_posix_path._owner.execute_command.assert_called_once_with("mv a c", expected_return_codes=None)

    def test_rename_exists(self, custom_posix_path, mocker):
        expected_path = CustomPosixPath("c", owner=mocker.Mock())
        expected_path.exists = mocker.Mock()
        expected_path.exists.return_value = True
        with pytest.raises(FileExistsError):
            custom_posix_path.rename(expected_path)

    def test_samefile(self, custom_posix_path, mocker):
        expected_path = CustomPosixPath("a", owner=mocker.Mock())
        custom_posix_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=0, args="command", stdout="", stderr="stderr"
        )
        assert custom_posix_path.samefile(expected_path) is True
        custom_posix_path._owner.execute_command.assert_called_once_with(
            "diff a a", expected_return_codes=None, discard_stdout=True
        )

    def test_samefile_different(self, custom_posix_path, mocker):
        expected_path = CustomPosixPath("c", owner=mocker.Mock())
        custom_posix_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=1, args="command", stdout="", stderr="stderr"
        )
        assert custom_posix_path.samefile(expected_path) is False
        custom_posix_path._owner.execute_command.assert_called_once_with(
            "diff a c", expected_return_codes=None, discard_stdout=True
        )

    def test_read_text(self, custom_posix_path, mocker):
        mock_process = mocker.MagicMock()
        mock_process.get_stdout_iter.return_value = iter(["content ", "of ", "file"])
        custom_posix_path._owner.start_process.return_value = mock_process
        result = custom_posix_path.read_text()
        assert result == "content of file"
        custom_posix_path._owner.start_process.assert_called_once_with("cat a")

    def test_write_text(self, custom_posix_path):
        text_to_write = "some text\nsome data"
        assert custom_posix_path.write_text(text_to_write) == 19
        custom_posix_path._owner.execute_command.assert_called_once_with(
            'echo -e "some text\nsome data" > a', shell=True
        )

    def test_write_text_encoding(self, custom_posix_path):
        text_to_write = "some text\nsome data"
        assert custom_posix_path.write_text(text_to_write, encoding="UTF-8") == 19
        custom_posix_path._owner.execute_command.assert_called_once_with(
            'echo -e "some text\nsome data" | iconv --to-code=UTF-8 > a', shell=True
        )

    def test_new_object_contains_correct_connection_after_with_suffix(self, custom_posix_path):
        assert custom_posix_path.with_suffix(".suffix")._owner == custom_posix_path._owner

    def test_rmdir_success(self, custom_posix_path):
        custom_posix_path._owner.execute_command.side_effect = [
            ConnectionCompletedProcess(
                args="",
                stdout="",
                return_code=0,
                stderr="",
            ),
            ConnectionCompletedProcess(
                args=f"rm -rf {str(custom_posix_path)}",
                stdout="",
                return_code=0,
                stderr="",
            ),
        ]
        custom_posix_path.rmdir()
        custom_posix_path._owner.execute_command.assert_called_with(
            f"rm -rf {str(custom_posix_path)}", expected_return_codes=None
        )

    def test_rmdir_error(self, custom_posix_path):
        custom_posix_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            args="",
            stdout="Something",
            return_code=0,
            stderr="permission denied occurred",
        )
        with pytest.raises(ModuleFrameworkDesignError):
            custom_posix_path.rmdir()

    def test_rmdir_error_in_stdout(self, custom_posix_path):
        custom_posix_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            args="",
            stdout="permission denied occurred",
            return_code=0,
        )
        with pytest.raises(ModuleFrameworkDesignError):
            custom_posix_path.rmdir()

    @pytest.mark.skipif(sys.version_info > (3, 12), reason="requires python3.11 or lower")
    def test_expanduser_pre312_without_tilde(self, custom_posix_path):
        custom_posix_path._drv = ""
        custom_posix_path._root = ""
        custom_posix_path._parts = ("folder",)
        result = CustomPosixPath.expanduser(custom_posix_path)
        assert result is custom_posix_path


class TestCustomWindowsPath:
    @pytest.fixture()
    def custom_windows_path_directory(self, mocker):
        mock_conn = mocker.Mock()
        return CustomWindowsPath(r"C:\Users\Administrator\Downloads", owner=mock_conn)

    @pytest.fixture()
    def custom_windows_path(self, mocker):
        mock_conn = mocker.Mock()
        return CustomWindowsPath("a", owner=mock_conn)

    def test_exists(self, custom_windows_path):
        custom_windows_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=0, args="command", stdout="stdout", stderr="stderr"
        )
        assert custom_windows_path.exists() is True

    def test_exists_failure(self, custom_windows_path):
        custom_windows_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=127, args="command", stdout="stdout", stderr="stderr"
        )
        assert custom_windows_path.exists() is False

    def test_expanduser_no_tilde(self, mocker):
        mock_conn = mocker.Mock()
        mock_conn.execute_command.return_value = ConnectionCompletedProcess(
            return_code=0, args="command", stdout="c:\\Users\\admin\\", stderr="stderr"
        )
        path = CustomWindowsPath(r"c:\a", owner=mock_conn)
        assert path.expanduser() == path

    def test_is_dir(self, custom_windows_path_directory):
        output = r"""Volume in drive C is OSDisk
        Volume Serial Number is 006C-8EDC

        Directory of C:\Users\Administrator\Downloads

        23.09.2020  09:16    <DIR>          .
        23.09.2020  09:16    <DIR>          ..
        23.01.2020  08:57    <DIR>          Captures
               0 File(s)              0 bytes
               3 Dir(s)  109 659 615 232 bytes free"""
        custom_windows_path_directory._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=0, args="command", stdout=dedent(output), stderr="stderr"
        )
        assert custom_windows_path_directory.is_dir() is True

    def test_is_dir_with_file(self, custom_windows_path_directory):
        output = r""" Volume in drive C is OS
        Volume Serial Number is 3865-6CF4

        Directory of C:\Users\Administrator\Downloads

        03/14/2022  12:07 PM    <DIR>          .
        03/14/2022  12:07 PM    <DIR>          ..
        03/14/2022  12:07 PM    <DIR>          a
        03/14/2022  10:22 AM                 0 path_test.txt
                       1 File(s)              0 bytes
                       3 Dir(s)  43,655,008,256 bytes free
        """
        custom_windows_path_directory._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=0, args="command", stdout=dedent(output), stderr="stderr"
        )
        assert custom_windows_path_directory.is_dir() is True

    def test_is_dir_no_exists(self, custom_windows_path_directory):
        output = r"""Volume in drive C is OSDisk
        Volume Serial Number is 006C-8EDC
        Directory of C:\Users\alasota
        File Not Found"""
        custom_windows_path_directory._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=127, args="command", stdout=dedent(output), stderr="stderr"
        )
        assert custom_windows_path_directory.is_dir() is False

    def test_is_file(self, custom_windows_path):
        output = r""" Volume in drive C is OSDisk
        Volume Serial Number is 006C-8EDC
        Directory of C:\Users\alasota
        08.05.2020  12:59           202 633 isoldbg.log
               1 File(s)        202 633 bytes
               0 Dir(s)  109 660 155 904 bytes free"""
        custom_windows_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=0, args="command", stdout=dedent(output), stderr="stderr"
        )
        assert custom_windows_path.is_file() is True

    def test_is_file_directory_passed(self, custom_windows_path_directory):
        output = r"""Volume in drive C is OS
                    Volume Serial Number is 3865-6CF4

                    Directory of C:\Users\Administrator\Downloads

                    03/14/2022  10:22 AM    <DIR>          .
                    03/14/2022  10:22 AM    <DIR>          ..
                    03/14/2022  10:22 AM                 0 path_test.txt
                                   1 File(s)              0 bytes
                                   2 Dir(s)  43,656,384,512 bytes free
                    """
        custom_windows_path_directory._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=0, args="command", stdout=dedent(output), stderr="stderr"
        )
        assert custom_windows_path_directory.is_file() is False

    def test_is_file_no_exists(self, custom_windows_path):
        output = r"""Volume in drive C is OSDisk
                Volume Serial Number is 006C-8EDC

                Directory of C:\Users\alasota

                File Not Found"""
        custom_windows_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=127, args="command", stdout=dedent(output), stderr="stderr"
        )
        assert custom_windows_path.is_file() is False

    def test_mkdir_exists_no_check_win(self, custom_windows_path, mocker):
        custom_windows_path.is_file = mocker.Mock(return_value=True)
        custom_windows_path._owner.execute_command = mocker.Mock()
        custom_windows_path.mkdir(exist_ok=True)
        custom_windows_path._owner.execute_command.assert_called_once_with("mkdir a", expected_return_codes=None)

    def test_mkdir(self, custom_windows_path, mocker):
        custom_windows_path.is_file = mocker.Mock(return_value=False)
        custom_windows_path._owner.execute_command = mocker.Mock()
        custom_windows_path.mkdir()
        custom_windows_path._owner.execute_command.assert_called_once_with("mkdir a", expected_return_codes=None)

    def test_rename(self, custom_windows_path, mocker):
        expected_path = CustomWindowsPath("c", owner=mocker.Mock())
        expected_path.exists = mocker.create_autospec(custom_windows_path.exists)
        expected_path.exists.return_value = False
        custom_windows_path.exists = mocker.create_autospec(custom_windows_path.exists)
        custom_windows_path.exists.return_value = True
        custom_windows_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=0, args="command", stdout="", stderr="stderr"
        )
        assert custom_windows_path.rename(expected_path) == expected_path
        custom_windows_path._owner.execute_command.assert_called_once_with('ren "a" "c"', expected_return_codes=[0])

    def test_rename_destination_exists(self, custom_windows_path, mocker):
        expected_path = CustomWindowsPath("c", owner=mocker.Mock())
        mocker.patch("mfd_connect.pathlib.path.CustomWindowsPath.exists", return_value=True)
        with pytest.raises(FileExistsError):
            custom_windows_path.rename(expected_path)

    def test_rename_source_not_exists(self, custom_windows_path, mocker):
        expected_path = CustomWindowsPath("c", owner=mocker.Mock())
        custom_windows_path.exists = mocker.create_autospec(custom_windows_path.exists)
        custom_windows_path.exists.return_value = False
        with pytest.raises(FileNotFoundError):
            custom_windows_path.rename(expected_path)

    def test_samefile(self, custom_windows_path, mocker):
        expected_path = CustomWindowsPath("a", owner=mocker.Mock())
        custom_windows_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=0, args="command", stdout="", stderr="stderr"
        )
        assert custom_windows_path.samefile(expected_path) is True
        custom_windows_path._owner.execute_command.assert_called_once_with("fc a a >NUL", expected_return_codes=None)

    def test_samefile_different(self, custom_windows_path, mocker):
        expected_path = CustomWindowsPath("c", owner=mocker.Mock())
        custom_windows_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=1, args="command", stdout="", stderr="stderr"
        )
        assert custom_windows_path.samefile(expected_path) is False
        custom_windows_path._owner.execute_command.assert_called_once_with("fc a c >NUL", expected_return_codes=None)

    def test_read_text(self, custom_windows_path):
        custom_windows_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=0, args="command", stdout="content of file", stderr="stderr"
        )
        assert custom_windows_path.read_text() == "content of file"
        custom_windows_path._owner.execute_command.assert_called_once_with("type a", expected_return_codes=None)

    def test_write_text(self, custom_windows_path):
        text_to_write = "some text\nsome data"
        assert custom_windows_path.write_text(text_to_write) == 20
        custom_windows_path._owner.execute_command.assert_called_once_with(
            'powershell -command "\\"some text`nsome data\\" | Out-File a"', shell=True
        )

    def test_write_text_with_encoding(self, custom_windows_path):
        text_to_write = "some text\nsome data"
        assert custom_windows_path.write_text(text_to_write, encoding="utf8") == 20
        custom_windows_path._owner.execute_command.assert_called_once_with(
            'powershell -command "\\"some text`nsome data\\" | Out-File a -encoding utf8"', shell=True
        )

    def test_touch(self, custom_windows_path):
        custom_windows_path.touch(exist_ok=True)
        custom_windows_path._owner.execute_command.assert_called_once_with(
            f"type nul >> {custom_windows_path}", expected_return_codes={0}
        )

    def test_new_object_contains_correct_connection_after_with_suffix(self, custom_windows_path):
        assert custom_windows_path.with_suffix(".suffix")._owner == custom_windows_path._owner


class TestCustomEFIShellPath:
    @pytest.fixture()
    def custom_efishell_path(self, mocker):
        mock_conn = mocker.Mock()
        return CustomEFIShellPath("a", owner=mock_conn)

    def test_rmdir(self, custom_efishell_path, mocker):
        custom_efishell_path.exists = mocker.Mock(return_value=True)
        custom_efishell_path._owner.execute_command = mocker.Mock()
        custom_efishell_path.rmdir()
        custom_efishell_path._owner.execute_command.assert_called_once_with("rm a", expected_return_codes=None)

    def test_rmdir_path_does_not_exist(self, custom_efishell_path, mocker):
        custom_efishell_path.exists = mocker.Mock(return_value=False)
        with pytest.raises(FileNotFoundError, match="a does not exist"):
            custom_efishell_path.rmdir()

    def test_exists(self, custom_efishell_path):
        output = r"""Directory of: FS0:\efi\
                10/03/2019 15:23 <DIR> 16,384 .
                10/03/2019 15:23 <DIR> 0 ..
                10/03/2019 15:23 <DIR> 16,384 boot
                0 File(s) 0 bytes
                3 Dir(s)"""

        custom_efishell_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=0, args="command", stdout=dedent(output), stderr="stderr"
        )
        assert custom_efishell_path.exists() is True

    def test_exists_path_does_not_exist(self, custom_efishell_path):
        output = """ls: File Not Found - 'FS0:\''"""
        custom_efishell_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=14, args="command", stdout=dedent(output), stderr="stderr"
        )
        assert custom_efishell_path.exists() is False

    def test_expanduser(self, custom_efishell_path):
        with pytest.raises(NotImplementedError, match="expanduser is not supported for EFISHELL"):
            custom_efishell_path.expanduser()

    def test_rename(self, custom_efishell_path, mocker):
        new_name = mocker.create_autospec(CustomEFIShellPath)
        new_name.exists = mocker.Mock(return_value=False)
        assert custom_efishell_path.rename(new_name) == new_name

    def test_rename_new_name_already_exists(self, custom_efishell_path, mocker):
        new_name = mocker.create_autospec(CustomEFIShellPath)
        with pytest.raises(FileExistsError, match=f"{new_name} file exists"):
            custom_efishell_path.rename(new_name)

    def test_is_file(self, custom_efishell_path):
        output = """Directory of: FS0:\
        09/23/2019 11:32 4,953,056 lom_srvc.EFI
        1 File(s) 4,953,056 bytes
        0 Dir(s)"""
        custom_efishell_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=0, args="command", stdout=dedent(output), stderr="stderr"
        )
        assert custom_efishell_path.is_file() is True

    def test_is_file_no_exists(self, custom_efishell_path):
        output = """ls: File Not Found - 'FS0:\''"""
        custom_efishell_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=127, args="command", stdout=dedent(output), stderr="stderr"
        )
        assert custom_efishell_path.is_file() is False

    def test_is_dir(self, custom_efishell_path):
        output = r"""Directory of: FS0:\efi\
        10/03/2019 15:23 <DIR> 16,384 .
        10/03/2019 15:23 <DIR> 0 ..
        10/03/2019 15:23 <DIR> 16,384 boot
        0 File(s) 0 bytes
        3 Dir(s)"""
        custom_efishell_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=0, args="command", stdout=dedent(output), stderr="stderr"
        )
        assert custom_efishell_path.is_dir() is True

    def test_is_dir_no_exists(self, custom_efishell_path):
        output = """ls: File Not Found - 'FS0:\''"""
        custom_efishell_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=127, args="command", stdout=dedent(output), stderr="stderr"
        )
        assert custom_efishell_path.is_dir() is False

    def test_touch(self, custom_efishell_path):
        custom_efishell_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=0, args="command", stdout="", stderr="stderr"
        )
        custom_efishell_path.touch()
        custom_efishell_path._owner.execute_command.assert_called_once_with("echo > a", expected_return_codes=None)

    def test_touch_exists(self, custom_efishell_path, mocker):
        custom_efishell_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=0, args="command", stdout="", stderr="stderr"
        )
        custom_efishell_path.is_file = mocker.create_autospec(custom_efishell_path.is_file)
        custom_efishell_path.is_file.return_value = True
        with pytest.raises(FileExistsError):
            custom_efishell_path.touch(exist_ok=False)

    def test_samefile(self, custom_efishell_path, mocker):
        expected_path = CustomEFIShellPath("a", owner=mocker.Mock())
        custom_efishell_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=0, args="command", stdout="[no differences encountered]", stderr="stderr"
        )
        assert custom_efishell_path.samefile(expected_path) is True
        custom_efishell_path._owner.execute_command.assert_called_once_with("comp a a", expected_return_codes=None)

    def test_samefile_different(self, custom_efishell_path, mocker):
        expected_path = CustomEFIShellPath("c", owner=mocker.Mock())
        custom_efishell_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=127, args="command", stdout="[difference(s) encountered]", stderr="stderr"
        )
        assert custom_efishell_path.samefile(expected_path) is False
        custom_efishell_path._owner.execute_command.assert_called_once_with("comp a c", expected_return_codes=None)

    def test_mkdir_exists_no_check_efishell(self, custom_efishell_path, mocker):
        custom_efishell_path.is_file = mocker.Mock(return_value=True)
        custom_efishell_path._owner.execute_command = mocker.Mock()
        custom_efishell_path.mkdir(exist_ok=True)
        custom_efishell_path._owner.execute_command.assert_called_once_with("mkdir a", expected_return_codes=None)

    def test_mkdir(self, custom_efishell_path, mocker):
        custom_efishell_path.is_file = mocker.Mock(return_value=False)
        custom_efishell_path._owner.execute_command = mocker.Mock()
        custom_efishell_path.mkdir()
        custom_efishell_path._owner.execute_command.assert_called_once_with("mkdir a", expected_return_codes=None)

    def test_read_text(self, custom_efishell_path):
        custom_efishell_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=0, args="command", stdout="content of file", stderr="stderr"
        )
        assert custom_efishell_path.read_text() == "content of file"
        custom_efishell_path._owner.execute_command.assert_called_once_with("cat a", expected_return_codes=None)

    def test_read_text_with_prompt(self, custom_efishell_path):
        custom_efishell_path._owner.execute_command.return_value = ConnectionCompletedProcess(
            return_code=0, args="command", stdout="content of file\nFS0:", stderr="stderr"
        )
        assert custom_efishell_path.read_text() == "content of file"
        custom_efishell_path._owner.execute_command.assert_called_once_with("cat a", expected_return_codes=None)

    def test_write_text(self, custom_efishell_path):
        text_to_write = "some text\nsome data"
        assert custom_efishell_path.write_text(text_to_write) == 19
        custom_efishell_path._owner.execute_command.assert_called_once_with(
            'echo "some text\nsome data" > a', shell=True
        )

    def test_new_object_contains_correct_connection_after_with_suffix(self, custom_efishell_path):
        assert custom_efishell_path.with_suffix(".suffix")._owner == custom_efishell_path._owner


@pytest.mark.parametrize(
    "os_name,os_type,expected_class",
    [
        (OSName.EFISHELL, OSType.EFISHELL, CustomEFIShellPath),
        (OSName.WINDOWS, OSType.WINDOWS, CustomWindowsPath),
        (OSName.LINUX, OSType.POSIX, CustomPosixPath),
    ],
)
def test_custom_path_factory_selects_correct_class(os_name, os_type, expected_class, mocker):
    owner = mocker.Mock()
    owner.get_os_name.return_value = os_name
    owner.get_os_type.return_value = os_type

    result = custom_path_factory("some_path", owner=owner)
    assert isinstance(result, expected_class)
