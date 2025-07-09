# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for pathlib utilities."""

import logging
from typing import TYPE_CHECKING

from mfd_common_libs import add_logging_level, log_levels
from mfd_typing import OSName

from mfd_connect import PythonConnection, SerialConnection, SolConnection
from mfd_connect.exceptions import ModuleFrameworkDesignError, PathException

if TYPE_CHECKING:
    from mfd_connect import Connection
    from pathlib import Path
    from mfd_connect.pathlib.path import CustomPath


logger = logging.getLogger(__name__)
add_logging_level(level_name="MODULE_DEBUG", level_value=log_levels.MODULE_DEBUG)


def append_file(connection: "Connection", file_path: "Path | CustomPath | str", content: str) -> None:
    """
    Append content to the file.

    :param connection: Connection to the machine.
    :param file_path: Path object or path to the file
    :param content: Content to be added to file
    """
    logger.log(level=log_levels.MODULE_DEBUG, msg=f"Adding content to file: {file_path}")
    file = connection.path(file_path) if isinstance(file_path, str) else file_path
    if isinstance(connection, PythonConnection):
        _append_file_python(file, content)
    else:
        _append_file_system(file, content)


def _append_file_python(file_path: "Path", content: str) -> None:
    """
    Append content to the file by writing with appended mode.

    :param file_path: Path object
    :param content: Content to be added to file
    """
    with file_path.open("a+") as file:
        file.write(content)


def _append_file_system(file_path: "Path", content: str) -> None:
    """
    Append content to file by reading and writing with addition.

    :param file_path: Path object
    :param content: Content to be added to file
    """
    file_path.touch(exist_ok=True)
    file_content = file_path.read_text().rstrip()  # skip tailing newline
    file_path.write_text(f"{file_content}{content}")


def remove_all_from_path(connection: "Connection", path: "Path | CustomPath | str") -> None:
    """
    Remove all files/directories together with provided path.

    :param connection: Connection to the machine.
    :param path: The path to be deleted.
    :raises ModuleFrameworkDesignError: on an error operation.
    """
    logger.log(
        level=log_levels.MODULE_DEBUG,
        msg=f"\nPassed connection: {connection}@{connection.ip}\nPassed path: {path}",
    )
    if isinstance(connection, SerialConnection) or isinstance(connection, SolConnection):
        raise ModuleFrameworkDesignError(
            f"Not supported connection type: {type(connection)} for remove_all_from_path()."
        )
    if isinstance(path, str):
        path = connection.path(path)
    if connection.get_os_name() == OSName.WINDOWS:
        _remove_all_from_path_windows(connection, path)
    else:
        _remove_all_from_path_unix(connection, path)


def convert_separators(conn: "Connection", path: str) -> str:
    """Convert path of file or directory separators to connection specific (slashes or backslashes).

    :param conn: Connection object
    :param path: path to file or directory
    :return: converted path to connection specifics
    """
    if conn.get_os_name() == OSName.WINDOWS:
        path = path.replace("/", "\\").replace("//", "\\")
    else:
        path = path.replace("\\", "/").replace("''", "/")
        path = path.split(":")[1] if ":" in path else path
    return path


def _remove_all_from_path_windows(connection: "Connection", path: "Path | CustomPath") -> None:
    """
    Remove all files/directories together with provided path.

    :param connection: Connection object
    :param path: path to file or directory
    :return: True if path exists, False otherwise.
    :raises WinPathException if path for removing doesn't exist.
    """
    if not path.exists():
        raise PathException(f"{path} does not exist.")
    if path.is_dir():
        path_win = convert_separators(connection, path=str(path))
        connection.execute_command(f"rmdir /q /s {path_win}", shell=True, expected_return_codes=None)
    else:
        path.unlink()


def _remove_all_from_path_unix(connection: "Connection", path: "Path | CustomPath") -> None:
    """
    Remove all files/directories together with provided path.

    :param connection: Connection object
    :param path: path to file or directory
    :return: True if path exists, False otherwise.
    """
    if not path.exists():
        raise PathException(f"{path} does not exist.")
    path_unix = convert_separators(connection, path=str(path))
    err = connection.execute_command(f"rm -rf {path_unix}", expected_return_codes=None).stderr
    if "permission denied" in err.casefold():
        raise ModuleFrameworkDesignError(f"Error occurred in CustomPosixPath.rmdir():\n{err}")
