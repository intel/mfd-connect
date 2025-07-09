# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Download utilities."""

import logging
import random
import string
import typing
from mfd_common_libs import log_levels

if typing.TYPE_CHECKING:
    from pathlib import PurePath
    from mfd_connect import Connection
    from mfd_connect.base import ConnectionCompletedProcess

logger = logging.getLogger(__name__)


def download_file_unix(
    connection: "Connection", url: str, destination_file: "PurePath", options: str
) -> "ConnectionCompletedProcess":
    """
    Download file on Unix.

    :param connection: Connection to Unix system
    :param url: URL of file
    :param destination_file: Path for destination of file
    :param options: Credentials for download authorization
    :return: ConnectionCompletedProcess
    """
    command = f"curl {options} --create-dirs -o {destination_file} {url}"
    return connection.execute_command(command, expected_return_codes=None, stderr_to_stdout=True, shell=True)


def download_file_windows(
    connection: "Connection", url: str, destination_file: "PurePath", auth: str
) -> "ConnectionCompletedProcess":
    """
    Download file on Windows.

    Note: For authentication use either auth or headers -  - do not combine them.

    :param connection: Connection to Windows system
    :param url: URL of file
    :param destination_file: Path for destination of file
    :param auth: Credentials for download authorization (Username/Password or Headers with token)
    :return: ConnectionCompletedProcess
    """
    command = f"Invoke-WebRequest '{url}' -UseBasicParsing -OutFile '{destination_file}' {auth}"
    return connection.execute_powershell(command, expected_return_codes=None, stderr_to_stdout=True)


def _download_file_esxi(
    connection: "Connection", url: str, destination_file: "PurePath", options: str
) -> "ConnectionCompletedProcess":
    """
    Download file on ESXi via wget.

    :param connection: Connection to ESXi system.
    :param url: URL of file
    :param destination_file: Path for destination of file.
    :param options: Credentials for download authorization
    :return: ConnectionCompletedProcess
    """
    command = f"wget {url} -O {destination_file} {options} --no-check-certificate"
    return connection.execute_command(command, expected_return_codes=None, stderr_to_stdout=True)


def _prepare_headers_with_env_powershell(headers: dict[str, str] | None) -> str:
    """
    Prepare headers with environment variables for Windows (to be used in powershell - InvokeWebRequest cmdlet).

    :param headers: Headers for download authorization
    :return: Powershell-friendly headers string
    """
    if not headers:
        return ""
    return "-Headers @{" + ";".join([f"{key}= {value}" for key, value in headers.items()]) + ";}"


def _prepare_headers_powershell(headers: dict[str, str] | None) -> str:
    """
    Prepare headers for Windows (to be used in powershell - InvokeWebRequest cmdlet).

    :param headers: Headers for download authorization
    :return: Powershell-friendly headers string
    """
    if not headers:
        return ""
    return "-Headers @{" + ";".join([f"'{key}'= '{value}'" for key, value in headers.items()]) + ";}"


def _prepare_headers_wget(headers: dict[str, str] | None) -> str:
    """
    Prepare headers for wget tool.

    :param headers: Headers for download authorization
    :return: wget-friendly string with headers
    """
    return " ".join(f'--header="{key}: {value}"' for key, value in headers.items()) if headers else ""


def _prepare_headers_curl(headers: dict[str, str] | None) -> str:
    """
    Prepare headers for curl.

    :param headers: Headers for download authorization
    :return: curl-friendly string with headers
    """
    return " ".join(f'-H "{key}: {value}"' for key, value in headers.items()) if headers else ""


def download_file_esxi(
    connection: "Connection",
    url: str,
    destination_file: "PurePath",
    options: str = None,
    headers: dict[str, str] | None = None,
) -> "ConnectionCompletedProcess":
    """
    Download file on ESXi.

    :param connection: Connection to ESXi system.
    :param url: URL of file
    :param destination_file: Path for destination of file.
        This path will be used for both controller and target host ESXi
    :param options: Credentials for download authorization
    :param headers: Headers for download authorization
    :return: ConnectionCompletedProcess
    """
    logger.log(level=log_levels.MODULE_DEBUG, msg="Preparing ESXi Host parameters ..")
    if options and headers:
        raise ValueError("Use either options or headers - do not combine them.")

    if options is None and headers is None:
        options = ""
    else:
        options = options if options else _prepare_headers_wget(headers)

    is_wget_available = connection.execute_command("test wget", expected_return_codes=[0, 1]).return_code == 0
    if is_wget_available:
        return _download_file_esxi(
            connection,
            url,
            destination_file,
            options,
        )
    else:
        return download_file_unix_via_controller(
            connection,
            destination_file,
            options if options else _prepare_headers_curl(headers),
            url,
        )


def download_file_unix_via_controller(
    connection: "Connection",
    destination_file: "PurePath",
    options: str,
    url: str,
) -> "ConnectionCompletedProcess":
    """
    Download file on Unix using controller.

    :param connection: Connection to client system.
    :param url: URL of file
    :param destination_file: Path for destination of file.
        This path will be used for both controller and target host
    :param options: Credentials for download authorization
    :return: ConnectionCompletedProcess
    """
    # 1 copy to controller
    from mfd_connect import LocalConnection

    local_conn = LocalConnection()
    logger.log(
        level=log_levels.MODULE_DEBUG,
        msg=f"Copying file from: {url} to test controller's path: {destination_file}",
    )
    controller_destination = local_conn.path("/tmp", destination_file.name)
    download_file_unix(connection=local_conn, url=url, destination_file=controller_destination, options=options)

    # 2 copy to host
    logger.log(
        level=log_levels.MODULE_DEBUG,
        msg=f"Copying {destination_file} from Controller to Target Host",
    )
    logger.log(
        level=log_levels.MODULE_DEBUG,
        msg=f"Source: {destination_file}, Dest: {destination_file}, cwd: {local_conn.path.cwd()}",
    )

    from mfd_connect.util.rpc_copy_utils import copy

    copy(local_conn, connection, controller_destination, destination_file)
    controller_destination.unlink()

    from mfd_connect.base import ConnectionCompletedProcess

    return ConnectionCompletedProcess(args="", stdout="", return_code=0)


def _generate_random_string(length: int = 8) -> str:
    """
    Generate random string.

    :param length: length of random string
    :return: generated string
    """
    return "".join(random.choice("".join([string.ascii_letters, string.digits])) for i in range(length))
