# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""RPC utils for copying.

• The document contains a Python script for copying files and directories between different types of connections,
including RPyC, SSH, Local, Serial, and Tunneled connections.
• The script provides functions to copy files/directories locally or remotely, depending on the source and
destination connection types.
• It handles various scenarios, such as copying files/directories between the same or different machines,
copying large files using FTP or Python operations, and copying to/from serial connections.
• The script includes error handling and logging mechanisms to track the progress and report any issues during
the copying process.
• It supports different operating systems (POSIX and Windows) and handles file path conversions based on the connection
 type.
• The script offers options to specify timeouts, chunk sizes, and control sum checks for file integrity verification
after copying.
• It utilizes various Python modules and libraries, such as shutil, pathlib, subprocess, and custom modules like
mfd_ftp and mfd_tftp for FTP and TFTP operations.
• The script provides detailed logging and debugging messages to assist in troubleshooting and monitoring the copying
process.
• It includes utility functions for tasks like getting hostnames, checking file paths, and removing IP addresses from
known_hosts files for SSH connections.
"""

import base64
import io
import logging
import time
from functools import partial
from ipaddress import IPv4Address
from pathlib import Path
from typing import TYPE_CHECKING, Union, Optional

from mfd_common_libs import log_levels, DisableLogger


from mfd_connect.tunneled_rpyc import TunneledRPyCConnection
from mfd_typing.os_values import OSType, OSName

from mfd_connect import RPyCConnection, SSHConnection, LocalConnection, SerialConnection, TunneledSSHConnection
from mfd_connect.exceptions import (
    PathNotExistsError,
    ConnectionCalledProcessError,
    TransferFileError,
    ModuleFrameworkDesignError,
    CopyException,
)
from mfd_connect.util.pathlib_utils import convert_separators

if TYPE_CHECKING:
    from mfd_connect import Connection, PythonConnection
    from subprocess import Popen
    from mfd_ftp.client.ftp_client import Client
    from mfd_connect.pathlib.path import CustomPath

logger = logging.getLogger(__name__)

CHUNK_SIZE = 654000  # (654KB) size of chunk buffer in bytes for copying large files over RPyC
MAX_PYTHONIC_COPY_SIZE = 512000000  # 512MB, max size to remote copy using python operations, otherwise 'll use FTP


def _convert_separators(conn: "Connection", path: str) -> str:
    """Convert path of file or directory separators to connection specific (slashes or backslashes).

    :param conn: Connection object
    :param path: path to file or directory
    :return: converted path to connection specifics
    """
    return convert_separators(conn=conn, path=path)


def copy(
    src_conn: "Connection",
    dst_conn: "Connection",
    source: "str | Path | CustomPath",
    target: "str | Path | CustomPath",
    timeout: int = 600,
) -> None:
    """
    Copy file/directory to the target.

    :param src_conn: Source connection object
    :param dst_conn: Destination connection object
    :param source: Path to file either directory or directory with '*' to be copied
    :param target: Path to where file or directory should be copied.
    :param timeout: Timeout to wait for copying (used in rpyc remote only)
    """
    supported_connections = (RPyCConnection, SSHConnection, LocalConnection, SerialConnection)
    if not isinstance(src_conn, supported_connections) or not isinstance(dst_conn, supported_connections):
        raise Exception("Connection type not supported.")

    if (
        isinstance(src_conn, SerialConnection)
        and (not isinstance(dst_conn, RPyCConnection) or not isinstance(dst_conn, LocalConnection))
    ) and (
        isinstance(dst_conn, SerialConnection)
        and (not isinstance(src_conn, RPyCConnection) or not isinstance(src_conn, LocalConnection))
    ):
        raise Exception(f"Other copying from/to {str(SerialConnection)} than local/rpyc is not permitted.")

    logger.log(
        level=log_levels.MODULE_DEBUG,
        msg=f"\nPassed source connection: {src_conn}@{src_conn.ip}\nPassed destination connection: "
        f"{dst_conn}@{dst_conn.ip}\n"
        f"Passed source: {source}\nPassed destination: {target}",
    )
    if isinstance(src_conn, SerialConnection):
        return _copy_from_serial_to_target(src_conn=src_conn, dst_conn=dst_conn, source=source, target=target)

    elif isinstance(dst_conn, SerialConnection):
        return _copy_from_source_to_serial(src_conn=src_conn, dst_conn=dst_conn, source=source, target=target)

    source = src_conn.path(_convert_separators(conn=src_conn, path=str(source)))
    target = dst_conn.path(_convert_separators(conn=dst_conn, path=str(target)))

    logger.log(level=log_levels.MODULE_DEBUG, msg="Check hostnames to determine copy method.")

    src_hostname = _get_hostname(src_conn)
    dst_hostname = _get_hostname(dst_conn)

    _dest_conn = dst_conn
    # In case of local copying, use the same connection with the same permissions for both paths creation
    if src_hostname == dst_hostname:
        _dest_conn, target = src_conn, src_conn.path(_convert_separators(conn=dst_conn, path=str(target)))
    if "*" in source.name and source.suffix != "" and isinstance(src_conn, RPyCConnection):
        return _copy_rpyc_wildcard_files(src_conn, dst_conn, source, target, src_hostname, dst_hostname, timeout)
    else:
        _check_paths(dst_conn=_dest_conn, source=source, target=target)

    if src_hostname is None or dst_hostname is None:
        raise Exception(
            f"Cannot decide about way of copying (local or remote) due to missing hostname: source@{src_hostname}, "
            f"target@{dst_hostname}."
        )

    if src_hostname == dst_hostname:
        logger.log(
            level=log_levels.MODULE_DEBUG,
            msg="Source and destination are the same machine, an internal copy will be performed between them",
        )
        _copy_local(src_conn=src_conn, source=source, target=target, timeout=timeout)
    else:
        logger.log(level=log_levels.MODULE_DEBUG, msg="All hostnames are different.")
        _copy_remote(src_conn=src_conn, dst_conn=dst_conn, source=source, target=target, timeout=timeout)


def _copy_rpyc_wildcard_files(
    src_conn: RPyCConnection,
    dst_conn: "Connection",
    source: str | Path,
    target: str | Path,
    src_hostname: str,
    dst_hostname: str,
    timeout: int = 600,
) -> None:
    target_name = target
    files = src_conn.modules().glob.glob(str(source))
    for file in files:
        if src_hostname == dst_hostname:
            src_conn.modules().shutil.copy(file, target)
        else:
            source = src_conn.path(_convert_separators(conn=src_conn, path=str(file)))
            if isinstance(dst_conn, RPyCConnection):
                target = dst_conn.path(target_name, source.name)
                target = dst_conn.path(_convert_separators(conn=dst_conn, path=str(target)))
            _copy_remote(src_conn=src_conn, dst_conn=dst_conn, source=source, target=target, timeout=timeout)


def _get_host_name_alternative_command(connection: "Connection") -> str:
    """
    Get hostname from /proc/sys/kernel/hostname.

    :param connection: Connection object.
    :return: Hostname
    """
    command = "cat /proc/sys/kernel/hostname"
    logger.log(level=log_levels.MODULE_DEBUG, msg=f"Checking hostname using: {command}")
    output = connection.execute_command(command=command).stdout
    hostname = output.rstrip()
    logger.log(level=log_levels.MODULE_DEBUG, msg=f"Hostname: {hostname}")
    return hostname


def _get_hostname(conn: "Connection") -> str:
    """Get machine hostname.

    :param conn: Connection object to machine
    :return: Machine hostname
    :raises: Exception when couldn't read hostname
    """
    hostname = None
    if isinstance(conn, RPyCConnection) or isinstance(conn, LocalConnection):
        hostname = conn.modules().socket.gethostname().rstrip()
    elif isinstance(conn, SSHConnection):
        try:
            hostname = (conn.execute_command(command="hostname", cwd="/")).stdout.rstrip()
        except Exception as e:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg="hostname unavailable, trying to get it alternative way.",
            )
            hostname = _get_host_name_alternative_command(conn)
            if not hostname:
                raise Exception(f"Couldn't read hostname. Unexpected behavior: {e}")
    return hostname


def _check_paths(dst_conn: "Connection", source: Path, target: Path) -> None:
    """Check if file/ directory exist on source and if target already exists. Create target subdirectory if needed.

    :param dst_conn: Destination connection object
    :param source: Path to file or directory to be copied
    :param target: Path to where file or directory should be copied.
    :raises: PathNotExistsError if source not exist
    :raises: PathExistsError if target already exists
    """
    _source = source.parent if source.name == "*" else source
    if not _source.exists():
        raise PathNotExistsError(f"'{_source}' does not exist on source machine!")

    _target = target / source.name if source.is_dir() or source.name == "*" else target
    _target = dst_conn.path(_target)
    if not _target.exists():
        target_parent_dir = dst_conn.path(_target.parent)
        if not target_parent_dir.exists():
            target_parent_dir.mkdir(parents=True)
        return

    if target.is_file():
        logger.log(
            level=log_levels.MODULE_DEBUG, msg=f"'{target}' already exists on target machine - file will be override."
        )
        return

    _supported_python_connections = (RPyCConnection, LocalConnection)
    if isinstance(dst_conn, _supported_python_connections):
        logger.log(
            level=log_levels.MODULE_DEBUG,
            msg=f"'{_target}' is directory and already exists on target machine! Need to delete it!",
        )
        dst_conn.modules().shutil.rmtree(_target)
    elif isinstance(dst_conn, SSHConnection):
        logger.log(
            level=log_levels.MODULE_DEBUG,
            msg=f"'{_target}' is directory and already exists on target machine - try to overwrite it.",
        )


def _copy_local(src_conn: "Connection", source: "Path", target: "Path", timeout: int) -> None:
    """Make local copy of file/ directory depends on connection type.

    :param src_conn: Source connection object
    :param source: Path to directory to be copied
    :param target: Path to where directory should be copied.
    """
    if isinstance(src_conn, RPyCConnection) or isinstance(src_conn, LocalConnection):
        if source.name == "*":
            _copy_dir_pythonic(
                src_conn=src_conn,
                dst_conn=src_conn,
                source=source.parent,
                target=target,
                extract_dir=target,
                timeout=timeout,
            )
        elif source.is_file():
            _copy_file_local_pythonic(src_conn=src_conn, source=source, target=target)
        elif source.is_dir():
            extract_dir = src_conn.modules().os.path.join(target, source.name)
            _copy_dir_pythonic(
                src_conn=src_conn,
                dst_conn=src_conn,
                source=source,
                target=target,
                extract_dir=extract_dir,
                timeout=timeout,
            )

    elif isinstance(src_conn, SSHConnection):
        _copy_local_ssh(src_conn=src_conn, source=source, target=target)

    else:
        raise Exception("Not supported Connection type used for local copying.")


def _copy_file_local_pythonic(src_conn: Union["RPyCConnection", "LocalConnection"], source: Path, target: Path) -> None:
    """Copy file locally using RPyC/Local connection.

    :param src_conn: Source connection object
    :param source: Path to file to be copied
    :param target: Path to where file should be copied.
    """
    if not target.suffix:
        logger.log(
            level=log_levels.MODULE_DEBUG,
            msg=f"There is no extension provided for destination file: '{target}'. "
            f"Make sure that the name of 'file' was set as target. "
            f"Copying file to directory is not supported!",
        )
    logger.log(level=log_levels.MODULE_DEBUG, msg=f"Copying file from '{source}' to '{target}'")
    src_conn.modules().shutil.copy2(source, target, follow_symlinks=False)
    logger.log(level=log_levels.MODULE_DEBUG, msg="File successfully copied locally.")


def _copy_local_ssh(src_conn: "SSHConnection", source: Path, target: Path) -> None:
    """Copy file or directory locally using SSH connection.

    :param src_conn: Source connection object
    :param source: Path to file or directory to be copied
    :param target: Path to where file or directory should be copied.
    """
    logger.log(level=log_levels.MODULE_DEBUG, msg=f"Copying from '{source}' to '{target}'")
    if src_conn._os_type == OSType.POSIX:
        src_conn.execute_command(command=f"cp -rP {source} {target}", cwd="/")
    elif src_conn._os_type == OSType.WINDOWS:
        if source.is_file():
            src_conn.execute_command(command=f"copy {source} {target}")
        elif source.is_dir():
            src_conn.execute_command(command=f"xcopy /E /I {source} {target}")
    logger.log(level=log_levels.MODULE_DEBUG, msg="Successfully copied locally via system command.")


def _copy_remote(src_conn: "Connection", dst_conn: "Connection", source: Path, target: Path, timeout: int) -> None:
    """Make remote copy of file/ directory depends on connection type.

    :param src_conn: Source connection object
    :param dst_conn: Destination connection object
    :param source: Path to directory to be copied
    :param target: Path to where directory should be copied.
    :param timeout: Timeout to wait for copying
    """
    supported_python_conn = (RPyCConnection, LocalConnection, TunneledRPyCConnection)
    supported_ssh_conn = (SSHConnection, LocalConnection, TunneledSSHConnection)
    if isinstance(src_conn, supported_python_conn) and isinstance(dst_conn, supported_python_conn):
        if source.name == "*":
            _copy_dir_pythonic(
                src_conn=src_conn,
                dst_conn=dst_conn,
                source=source.parent,
                target=target,
                extract_dir=target,
                timeout=timeout,
            )
        elif source.is_file():
            _copy_file_remote_rpyc(
                src_conn=src_conn,
                dst_conn=dst_conn,
                source=source,
                target=target,
                timeout=timeout,
            )
        elif source.is_dir():
            extract_dir = dst_conn.modules().os.path.join(target, source.name)
            _copy_dir_pythonic(
                src_conn=src_conn,
                dst_conn=dst_conn,
                source=source,
                target=target,
                extract_dir=extract_dir,
                timeout=timeout,
            )
    elif isinstance(src_conn, supported_ssh_conn) or isinstance(dst_conn, supported_ssh_conn):
        _copy_remote_ssh(src_conn=src_conn, dst_conn=dst_conn, source=source, target=target)
    else:
        raise Exception("Not supported Connection type used for remote copying.")


def _copy_file_remote_rpyc(
    src_conn: "RPyCConnection", dst_conn: "RPyCConnection", source: "Path", target: "Path", timeout: int
) -> None:
    """
    Copy file remotely using RPyC connection.

    If file size is bigger than 512MB, file will be copied via FTP (if mfd_ftp is available on the remote host,
    pythonic method otherwise).

    :param source: Path to file to be copied
    :param target: Path to where file should be copied.
    """
    if not target.suffix:
        logger.log(
            level=log_levels.MODULE_DEBUG,
            msg=f"There is no extension provided for destination file: '{target}'. "
            f"Make sure that the name of 'file' was set as target. "
            f"Copying file to directory is not supported! You can use asteriks option instead.",
        )
    logger.log(level=log_levels.MODULE_DEBUG, msg=f"Copying file from {src_conn.ip}:{source} to {dst_conn.ip}:{target}")
    if source.stat().st_size > MAX_PYTHONIC_COPY_SIZE:
        logger.log(
            level=log_levels.MODULE_DEBUG, msg=f"{source} file is too large to copy using RPyC, going to use FTP"
        )
        try:
            _copy_file_ftp_rpyc(src_conn, dst_conn, source, target, timeout)
        except ModuleNotFoundError as e:
            if e.name == "mfd_ftp":
                logger.log(
                    level=log_levels.MODULE_DEBUG,
                    msg="mfd_ftp module not found on the remote host. Falling back to pythonic method.",
                )
                _copy_file_pythonic_rpyc(source, target)
            else:
                raise e
    else:
        _copy_file_pythonic_rpyc(source, target)
    logger.log(level=log_levels.MODULE_DEBUG, msg="File successfully copied remotely.")


def _copy_file_pythonic_rpyc(source: "Path", target: "Path") -> None:
    """
    Copy file using python operations on pathlib Paths.

    Method reports 10 times status of copy as percentage of total size and copied size.

    :param source: Path to file to be copied
    :param target: Path to where file should be copied.
    """
    with source.open(mode="rb") as source_file:
        with target.open(mode="wb") as target_file:
            file_size = source.stat().st_size
            one_tenth_amount_of_parts = max(1, int(file_size / CHUNK_SIZE * 0.1))
            # 10% calculate amount of parts
            # max is when file is smaller than chunk
            already_copied_size = 0
            for part_number, chunk in enumerate(iter(partial(source_file.read, CHUNK_SIZE), b""), start=1):
                copied_size = target_file.write(chunk)
                already_copied_size += copied_size
                if part_number % one_tenth_amount_of_parts == 0:  # every near 10% of part will log actual copied size
                    logger.log(
                        level=log_levels.MODULE_DEBUG, msg=f"Copied {already_copied_size / file_size * 100:.2f} %"
                    )
    logger.log(level=log_levels.MODULE_DEBUG, msg="File successfully copied in pythonic way.")


def _copy_file_tftp_rpyc(
    src_conn: "RPyCConnection", dst_conn: "RPyCConnection", source: "Path", target: "Path", timeout: int
) -> None:
    """
    Copy file using TFTP connection.

    :param src_conn: Source connection object
    :param dst_conn: Destination connection object
    :param source: Path to file to be copied
    :param target: Path to where file should be copied.
    :param timeout: Timeout to wait for copying
    """
    tftp_server_path = source.parent / "tftp"
    if not tftp_server_path.exists():
        tftp_server_path.mkdir(parents=True)
    tftp_file_path = tftp_server_path / source.name
    logger.log(
        level=log_levels.MODULE_DEBUG,
        msg=f"{src_conn._ip} -> Copying temp file from {source} to {tftp_file_path} required by TFTP server",
    )
    src_conn.modules().shutil.copy2(source, tftp_file_path, follow_symlinks=False)
    logger.log(level=log_levels.MODULE_DEBUG, msg="Starting server and client for TFTP")
    tftp_server: "Popen" = src_conn.modules().mfd_tftp.tftp_server.start_server_as_process(
        IPv4Address("0.0.0.0"), 18810, str(tftp_server_path)
    )
    client: "Client" = dst_conn.modules().mfd_tftp.tftp_client.Client(
        IPv4Address(src_conn._ip),
        18810,
        task="receive",
        source=str(tftp_file_path),
        destination=str(target),
        blocksize=65000,
        timeout=1000,
    )
    logger.log(level=log_levels.MODULE_DEBUG, msg="Starting transfer via TFTP")
    logger.log(level=log_levels.MODULE_DEBUG, msg=client.run())
    tftp_server.kill()
    logger.log(level=log_levels.MODULE_DEBUG, msg="Removing temporary file required for TFTP server")
    try:
        src_conn.modules().shutil.rmtree(tftp_server_path)
    except Exception:
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Cannot remove temporary directory {tftp_server_path}")

    logger.log(level=log_levels.MODULE_DEBUG, msg="File successfully copied via TFTP.")


def _copy_file_ftp_rpyc(
    src_conn: "RPyCConnection", dst_conn: "RPyCConnection", source: "Path", target: "Path", timeout: int
) -> None:
    """
    Copy file using FTP connection.

    Uses temporary RPyC connection with extended connection timeout.

    In case of a localhost IP address for source (test controller), the destination machine (ftp client)
    won't be able to connect to the ftp server on the source machine. That's why reverse mode is implemented
    (ftp server is on destination machine and ftp client on the source machine, ftp client will send file
    instead of receive, like normal usage)

    Normal mode: ftp server on source machine, ftp client and receive task on destination machine.
    Reverse mode: ftp server on destination machine, ftp client and send task on source machine.

    :param src_conn: Source connection object
    :param dst_conn: Destination connection object
    :param source: Path to file to be copied
    :param target: Path to where file should be copied.
    :param timeout: Timeout to wait for copying
    """
    logger.log(level=log_levels.MODULE_DEBUG, msg="Establishing temporary connections for source and destination.")
    temp_src_conn = RPyCConnection(src_conn.ip, connection_timeout=timeout)
    temp_dst_conn = RPyCConnection(dst_conn.ip, connection_timeout=timeout)
    logger.log(level=log_levels.MODULE_DEBUG, msg="Established temporary connections for source and destination.")

    if str(src_conn.ip) == "127.0.0.1":
        copy_file_ftp_reverse_mode(temp_src_conn, temp_dst_conn, source, target, timeout)
    else:
        copy_file_ftp_normal_mode(temp_src_conn, temp_dst_conn, source, target, timeout)


def copy_file_ftp_normal_mode(
    src_conn: Union["RPyCConnection", "LocalConnection"],
    dst_conn: Union["RPyCConnection", "LocalConnection"],
    source: "Path",
    target: "Path",
    timeout: int,
) -> None:
    """
    Copy file from ftp server using client receive task.

    :param src_conn: Source connection object
    :param dst_conn: Destination connection object
    :param source: Path to file to be copied
    :param target: Path to where file should be copied.
    :param timeout: Timeout to wait for copying
    """
    ftp_server_port = 18810
    logger.log(level=log_levels.MODULE_DEBUG, msg="Copying file using ftp client receive mode.")
    ftp_server: Optional["Popen"] = None
    try:
        ftp_server_path = source.parent / "ftp"
        if not ftp_server_path.exists():
            ftp_server_path.mkdir(parents=True)
        ftp_file_path = ftp_server_path / source.name
        logger.log(
            level=log_levels.MODULE_DEBUG,
            msg=f"{src_conn.ip} -> Copying temp file from {source} to {ftp_file_path} required by FTP server",
        )
        src_conn.modules().shutil.copy2(source, ftp_file_path, follow_symlinks=False)
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Starting server for FTP in {ftp_server_path} directory")
        ftp_server = src_conn.modules().mfd_ftp.ftp_server.start_server_as_process(
            IPv4Address("0.0.0.0"), ftp_server_port, str(ftp_server_path), username="ftp", password="***"
        )
        time.sleep(5)  # for server readiness
        logger.log(
            level=log_levels.MODULE_DEBUG,
            msg=f"Starting ftp client connection with parameters: ip={IPv4Address(dst_conn.ip)}, port={ftp_server_port}"
            f", source={str(source)}, destination={str(target.name)}",
        )
        client: "Client" = dst_conn.modules().mfd_ftp.ftp_client.Client(
            IPv4Address(src_conn.ip),
            ftp_server_port,
            username="ftp",
            password="***",
            task="receive",
            source=str(source.name),
            destination=str(target),
            timeout=timeout,
        )
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Starting transfer via FTP with timeout {timeout}s")
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Copy statistics: {client.run()}")
        ftp_server.kill()
        logger.log(level=log_levels.MODULE_DEBUG, msg="Removing temporary file required for FTP server")
        try:
            src_conn.modules().shutil.rmtree(ftp_server_path)
        except Exception:
            logger.log(level=log_levels.MODULE_DEBUG, msg=f"Cannot remove temporary directory {ftp_server_path}")

        if not target.exists():
            raise FileNotFoundError(f"{target} not found after copying.")
        logger.log(level=log_levels.MODULE_DEBUG, msg="File successfully copied via FTP.")
    except Exception:
        if ftp_server and ftp_server.poll() is None:
            ftp_server.kill()
        raise
    finally:
        src_conn.disconnect()
        dst_conn.disconnect()


def copy_file_ftp_reverse_mode(
    src_conn: Union["RPyCConnection", "LocalConnection"],
    dst_conn: Union["RPyCConnection", "LocalConnection"],
    source: "Path",
    target: "Path",
    timeout: int,
) -> None:
    """
    Copy file to ftp server using client send task.

    :param src_conn: Source connection object
    :param dst_conn: Destination connection object
    :param source: Path to file to be copied
    :param target: Path to where file should be copied.
    :param timeout: Timeout to wait for copying
    """
    ftp_server_port = 18810
    logger.log(level=log_levels.MODULE_DEBUG, msg="Copying file using ftp client send mode.")
    ftp_server: Optional["Popen"] = None
    try:
        ftp_server_path = target.parent / "ftp"
        if not ftp_server_path.exists():
            ftp_server_path.mkdir(parents=True)
        ftp_file_path = ftp_server_path / source.name
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Starting server for FTP in {ftp_server_path} directory")
        ftp_server = dst_conn.modules().mfd_ftp.ftp_server.start_server_as_process(
            IPv4Address("0.0.0.0"), ftp_server_port, str(ftp_server_path), username="ftp", password="***"
        )
        time.sleep(5)  # for server readiness
        logger.log(
            level=log_levels.MODULE_DEBUG,
            msg=f"Starting ftp client connection with parameters: ip={IPv4Address(dst_conn.ip)}, "
            f"port={ftp_server_port}, source={str(source)}, destination={str(target.name)}",
        )
        client: "Client" = src_conn.modules().mfd_ftp.ftp_client.Client(
            IPv4Address(dst_conn.ip),
            ftp_server_port,
            username="ftp",
            password="***",
            task="send",
            source=str(source),
            destination=str(target.name),
            timeout=timeout,
        )
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Starting transfer via FTP with timeout {timeout}s")
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Copy statistics: {client.run()}")
        ftp_server.kill()
        logger.log(
            level=log_levels.MODULE_DEBUG,
            msg=f"{dst_conn.ip} -> Copying file from {ftp_file_path} to {target} after FTP operations.",
        )
        dst_conn.modules().shutil.copy2(ftp_file_path, target, follow_symlinks=False)
        logger.log(level=log_levels.MODULE_DEBUG, msg="Removing temporary file required for FTP server")
        try:
            dst_conn.modules().shutil.rmtree(ftp_server_path)
        except Exception:
            logger.log(level=log_levels.MODULE_DEBUG, msg=f"Cannot remove temporary directory {ftp_server_path}")

        if not target.exists():
            raise FileNotFoundError(f"{target} not found after copying.")
        logger.log(level=log_levels.MODULE_DEBUG, msg="File successfully copied via FTP.")

    except Exception:
        if ftp_server and ftp_server.poll() is None:
            ftp_server.kill()
        raise
    finally:
        src_conn.disconnect()
        dst_conn.disconnect()


def _copy_dir_pythonic(
    src_conn: Union["RPyCConnection", "LocalConnection"],
    dst_conn: Union["RPyCConnection", "LocalConnection"],
    source: "Path",
    target: "Path",
    timeout: int,
    extract_dir: Optional["Path"] = None,
) -> None:
    """Copy directory using Python modules: locally or remotely.

    :param src_conn: Source connection object
    :param dst_conn: Destination connection object
    :param source: Path to directory to be copied
    :param target: Path to where directory should be copied.
    :param timeout: Timeout to wait for copying
    """
    logger.log(
        level=log_levels.MODULE_DEBUG, msg=f"Copying directory from {src_conn.ip}:{source} to {dst_conn.ip}:{target}"
    )
    try:
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Make archive from given directory: {source}")
        archived_source = src_conn.modules().shutil.make_archive(source, "tar", root_dir=source)
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Created archive from given directory: {archived_source}")
        archived_source = src_conn.path(archived_source)
        if not target.exists():
            target.mkdir(parents=True)
        archived_target = dst_conn.path(target, archived_source.name)

        logger.log(level=log_levels.MODULE_DEBUG, msg="Copied archive, extract created archive on target side")
        if isinstance(src_conn, LocalConnection) and isinstance(dst_conn, LocalConnection):
            _copy_file_local_pythonic(src_conn, archived_source, archived_target)
        else:
            _copy_file_remote_rpyc(src_conn, dst_conn, archived_source, archived_target, timeout)
        dst_conn.modules().shutil.unpack_archive(filename=archived_target, extract_dir=extract_dir, format="tar")

        logger.log(level=log_levels.MODULE_DEBUG, msg="Delete archive files on both machines")
        archived_source.unlink()
        archived_target.unlink()

        logger.log(level=log_levels.MODULE_DEBUG, msg="Directory successfully copied remotely.")
    except src_conn.modules().shutil.Error as err:
        if not err.errno and src_conn.modules().platform.system() == "VMkernel":
            return
        raise Exception(f"Problem occur during transferring directory: {err}.")


def _check_if_ip_is_reachable(conn: "Connection", dst_ip: IPv4Address | str) -> bool:
    """
    Check if machine can ping provided IP address.

    :param conn: Connection object
    :param dst_ip: Destination IP address
    :return: True if machines are accessible, False otherwise
    """
    try:
        conn.execute_command(
            command=f"ping {'-c' if conn.get_os_type() == OSType.POSIX else '-n'} 1 {dst_ip}", shell=True
        )
        return True
    except ConnectionCalledProcessError:
        return False


def _ssh_copy_via_tunnel(
    src_conn: "SSHConnection | TunneledSSHConnection | PythonConnection",
    dst_conn: "SSHConnection | TunneledSSHConnection | PythonConnection",
    source: Path,
    target: Path,
) -> None:
    """
    Copy file remotely using SSH connection via tunnel.

    :param src_conn: Source connection object
    :param dst_conn: Destination connection object
    :param source: Path to file to be copied
    :param target: Path to where file should be copied.
    """
    direct_connection, tunneled_connection = _assign_direct_and_tunneled_connection(src_conn, dst_conn)
    tunnel_port = 5022
    localhost = IPv4Address("127.0.0.1")
    jump_host_username = tunneled_connection._tunnel.ssh_username
    jump_host_password = tunneled_connection._tunnel.ssh_password
    dst_user = tunneled_connection._connection_details.get("username")
    dst_password = tunneled_connection._connection_details.get("password")
    _, dst_port = list(tunneled_connection._tunnel.tunnel_bindings.keys())[0]
    jump_host_port = tunneled_connection._tunnel.ssh_port
    jump_host_ip = tunneled_connection._tunnel.ssh_host

    if direct_connection._os_type is OSType.POSIX:
        shell = False if direct_connection.get_os_name() == OSName.FREEBSD else True
        add_known_host(ip=jump_host_ip, port=jump_host_port, connection=direct_connection, shell=shell)
        tunnel_proc = direct_connection.start_process(
            f'sshpass -p "{jump_host_password}" ssh -L {tunnel_port}:{tunneled_connection.ip}:{dst_port} '
            f"-p {jump_host_port} {jump_host_username}@{jump_host_ip}",
            shell=shell,
            enable_input=True,
        )

        add_known_host(ip=localhost, port=tunnel_port, connection=direct_connection, shell=shell)

        target = target.as_posix() if dst_conn._os_type == OSType.WINDOWS else target
        copy_command_with_password = f'sshpass -p "{dst_password}" scp -o StrictHostKeyChecking=no -r -P {tunnel_port}'

        if src_conn is direct_connection:
            command = rf"{copy_command_with_password} {source} {dst_user}@{localhost}:{target}"
        else:
            command = rf"{copy_command_with_password} {dst_user}@{localhost}:{source} {target}"

        direct_connection.execute_command(command=command, cwd="/", shell=shell)

        _remove_ip_from_known_host(direct_connection, localhost)
        _remove_ip_from_known_host(direct_connection, jump_host_ip)
        tunnel_proc.kill(wait=1)

    else:
        raise CopyException(
            "Not supported Connection type used for remote copying. One of connections needs to be Posix"
        )


def add_known_host(*, ip: IPv4Address | str, port: int, connection: "Connection", shell: bool) -> None:
    """
    Add a host to the known hosts file.

    :param ip: IP address of the host
    :param port: Port number of the host
    :param connection: Connection object to execute the command
    :param shell: Whether to use a shell to execute the command
    """
    ssh_dir = connection.path("~/.ssh").expanduser()
    if not ssh_dir.exists():
        ssh_dir.mkdir(parents=True, exist_ok=True)
    connection.execute_command(command=rf"ssh-keyscan -p {port} {ip} >> ~/.ssh/known_hosts", cwd="/", shell=shell)


def _copy_remote_ssh(
    src_conn: "SSHConnection | TunneledSSHConnection | LocalConnection",
    dst_conn: "SSHConnection | TunneledSSHConnection | LocalConnection",
    source: Path,
    target: Path,
) -> None:
    """
    Copy file remotely using SSH connection.

    :param src_conn: Source connection object
    :param dst_conn: Destination connection object
    :param source: Path to file to be copied
    :param target: Path to where file should be copied.
    :raises: ModuleFrameworkDesignError if any error occurs during removing ip from known_hosts
    :raises CopyException: If both connections are tunneled SSH connections
    """
    logger.log(level=log_levels.MODULE_DEBUG, msg=f"Copying from {src_conn.ip}:{source} to {dst_conn.ip}{target}")
    dst_connections = (SSHConnection, TunneledSSHConnection)
    if not isinstance(dst_conn, dst_connections) and not isinstance(src_conn, dst_connections):
        raise CopyException("Not supported Connection type used for remote copying.")
    # supported connections are one ssh and one tunneled ssh, if both are tunneled ssh, raise an exception
    if isinstance(dst_conn, TunneledSSHConnection) and isinstance(src_conn, TunneledSSHConnection):
        raise CopyException("Both connections can't be tunneled SSH connections.")
    if any(isinstance(conn, TunneledSSHConnection) for conn in (src_conn, dst_conn)):
        normal_connection, tunneled_connection = _assign_direct_and_tunneled_connection(src_conn, dst_conn)
        are_accessible = _check_if_ip_is_reachable(normal_connection, tunneled_connection.ip)
    else:
        are_accessible = _check_if_ip_is_reachable(src_conn, dst_conn.ip)
        if not are_accessible:
            raise CopyException("Source machine can't communicate with destination machine.")
    if not are_accessible:
        jump_host_ip = tunneled_connection._tunnel.ssh_host
        are_accessible = _check_if_ip_is_reachable(normal_connection, jump_host_ip)
        if not are_accessible:
            raise CopyException("Source machine can't communicate with destination machine or jump host.")
        _ssh_copy_via_tunnel(src_conn, dst_conn, source, target)
    else:
        _ssh_copy_locally(dst_conn, dst_connections, source, src_conn, target)

    logger.log(level=log_levels.MODULE_DEBUG, msg="Successfully copied remotely via SSH.")


def _assign_direct_and_tunneled_connection(
    src_conn: "SSHConnection | TunneledSSHConnection | PythonConnection",
    dst_conn: "SSHConnection | TunneledSSHConnection | PythonConnection",
) -> tuple["SSHConnection", "TunneledSSHConnection"]:
    """
    Assign direct and tunneled connection.

    :param src_conn: Source connection object
    :param dst_conn: Destination connection object
    :return: Tuple with normal and tunneled connection
    :raises CopyException: If both connections are tunneled SSH connections
    """
    if isinstance(src_conn, TunneledSSHConnection):
        tunneled_connection, direct_connection = src_conn, dst_conn
    elif isinstance(dst_conn, TunneledSSHConnection):
        tunneled_connection, direct_connection = dst_conn, src_conn
    else:
        raise CopyException("One of connections needs to be tunneled SSH connection.")
    return direct_connection, tunneled_connection


def _ssh_copy_locally(
    dst_conn: "SSHConnection | TunneledSSHConnection",
    dst_connections: tuple,
    source: Path,
    src_conn: "Connection",
    target: Path,
) -> None:
    """
    Copy file locally using SSH connection.

    :param dst_conn: Destination connection object
    :param dst_connections: Tuple with supported destination connections
    :param source: Path to file to be copied
    :param src_conn: Source connection object
    :param target: Path to where file should be copied.
    """
    if src_conn._os_type == OSType.POSIX and isinstance(dst_conn, dst_connections):
        user = dst_conn._connection_details.get("username")
        password = dst_conn._connection_details.get("password")

        shell = False if src_conn.get_os_name() == OSName.FREEBSD else True
        add_known_host(ip=dst_conn.ip, port=22, connection=src_conn, shell=shell)

        target = target.as_posix() if dst_conn._os_type == OSType.WINDOWS else target
        command = rf'sshpass -p "{password}" scp -o StrictHostKeyChecking=no -r {source} {user}@{dst_conn.ip}:{target}'
        src_conn.execute_command(command=command, cwd="/", shell=shell)

        _remove_ip_from_known_host(src_conn, dst_conn.ip)

    elif dst_conn._os_type == OSType.POSIX and isinstance(src_conn, dst_connections):
        user = src_conn._connection_details.get("username")
        password = src_conn._connection_details.get("password")
        shell = False if src_conn.get_os_name() == OSName.FREEBSD else True
        add_known_host(ip=src_conn.ip, port=22, connection=dst_conn, shell=shell)

        source = source.as_posix() if dst_conn._os_type != OSType.WINDOWS else source
        command = rf'sshpass -p "{password}" scp -o StrictHostKeyChecking=no -r {user}@{src_conn.ip}:{source} {target}'
        dst_conn.execute_command(command=command, cwd="/", shell=shell)

        _remove_ip_from_known_host(dst_conn, src_conn.ip)

    elif src_conn._os_type == OSType.WINDOWS and isinstance(dst_conn, dst_connections):
        user = dst_conn._connection_details.get("username")
        password = dst_conn._connection_details.get("password")
        source = source.as_posix() if src_conn._os_type == OSType.WINDOWS else source
        command = rf"echo y | pscp -r -scp -pw {password} {source} {user}@{dst_conn.ip}:{target}"
        src_conn.execute_command(command=command, shell=True)

    elif dst_conn._os_type == OSType.WINDOWS and isinstance(src_conn, dst_connections):
        user = src_conn._connection_details.get("username")
        password = src_conn._connection_details.get("password")
        target = target.as_posix() if dst_conn._os_type == OSType.WINDOWS else target
        command = rf"echo y | pscp -r -scp -pw {password} {user}@{src_conn.ip}:{source} {target}"
        dst_conn.execute_command(command=command, shell=True)


def _remove_ip_from_known_host(conn: "Connection", ip: IPv4Address | str) -> None:
    """
    Remove ip from Known_host file.

    :param conn: connection on which ip should be removed
    :param ip: IP Address to be removed from known_hosts
    :raises: ModuleFrameworkDesignError If any error appears during execute_command (ie. known_hosts doesn't exist)
    """
    try:
        conn.execute_command(f"sed -i '/{ip}/d' ~/.ssh/known_hosts", shell=True)
    except Exception as err:
        raise ModuleFrameworkDesignError(f"SSH key removal failed with error: {err}")


def _copy_from_source_to_serial(
    src_conn: Union["RPyCConnection", "LocalConnection"],
    dst_conn: "SerialConnection",
    source: Union[str, Path],
    target: Union[str, Path],
    *,
    chunk_size: int = None,
    check_control_sum: bool = True,
) -> None:
    """
    Copy file or directory from Source connection to Target Serial Connection.

    :param src_conn: Source connection object
    :param dst_conn: Destination connection object
    :param source: Path to file or directory to be copied
    :param target: Path to where file or directory should be copied.
    :param chunk_size: Sizes of file chunks to be passed at each command execution
    :param check_control_sum: Compare control sums of local and remote files after copying

    :raises TransferFileError: when problem with transferring file occurs
    """
    if chunk_size is None:
        chunk_size = 256 if dst_conn._is_veloce else 16384

    if not isinstance(source, Path):
        source = src_conn.path(source)
    try:
        source_content = source.read_bytes()
    except FileNotFoundError:
        raise TransferFileError(f"No such file on local machine: {source}.")

    source_content_encoded = base64.b64encode(source_content)  # encode file to base64
    src_b64_io = io.BytesIO(source_content_encoded)  # convert to bytes stream
    chunk = src_b64_io.read(chunk_size)  # read chunk from source
    encoded_remote_path = f"{target}.b64"  # path for encoded file on destination machine

    try:
        dst_conn._telnet_connection.execute_command(
            f"rm -f {encoded_remote_path}"
        )  # delete encoded file if already exists

        logger.debug("Transmitting file chunks, some logs will be disabled.")
        while chunk:
            chunk = chunk.decode("utf-8")  # decode chunk using utf-8
            with DisableLogger():
                dst_conn._telnet_connection.execute_command(f'echo "{chunk}" >> {encoded_remote_path}')  # write to file
            chunk = src_b64_io.read(chunk_size)  # read another chunk from source
        logger.debug("File chunks transmitted, full logging restored.")

        dst_conn._telnet_connection.execute_command(
            f"base64 -d < {encoded_remote_path} > {target}"
        )  # decode encoded file using base64
        dst_conn._telnet_connection.execute_command(f"rm -f {encoded_remote_path}")  # delete encoded file
    except ConnectionCalledProcessError as e:
        raise TransferFileError("Error while copying file.") from e

    if check_control_sum:
        dst_conn._check_control_sum(local_path=source, remote_path=target)


def _copy_from_serial_to_target(
    src_conn: "SerialConnection",
    dst_conn: Union["RPyCConnection", "LocalConnection"],
    source: Union[str, Path],
    target: Union[str, Path],
    *,
    lines_split_size: int = 20,
    check_control_sum: bool = True,
) -> None:
    """
    Copy file or directory to Destination Connection from Target Serial Connection.

    :param src_conn: Source connection object
    :param dst_conn: Destination connection object
    :param source: Path to file/directory on Source Connection, in case of file - extension is needed
    :param target: Path to file/directory on Destination Connection, in case of file - extension is needed
    :param lines_split_size: Number of lines in each chunk after splitting source file
    :param check_control_sum: Compare control sums of local and remote files after copying

    :raises TransferFileError: when problem with transferring file occurs
    """
    encoded_remote_path = f"{source}.b64"
    remote_path_split_conv_file = f"{encoded_remote_path}_"

    if not isinstance(target, Path):
        target = dst_conn.path(target)

    try:
        src_conn._telnet_connection.execute_command(f"test -f {source}")
    except ConnectionCalledProcessError as e:
        raise TransferFileError(f"File does not exist under remote path: {source}") from e

    src_conn._telnet_connection.execute_command(
        f"base64 < {source} > {encoded_remote_path}"
    )  # convert file with base64

    src_conn._telnet_connection.execute_command(  # divide file into smaller files
        f"split -dl {lines_split_size} {encoded_remote_path} {remote_path_split_conv_file}"
    )

    get_files_cmd = f"ls -1 {remote_path_split_conv_file}*"
    get_files_output = src_conn._telnet_connection.execute_command(get_files_cmd).stdout
    files_to_fetch = get_files_output.split()
    logger.log(level=log_levels.MODULE_DEBUG, msg=f"Files to fetch: {files_to_fetch}")

    if files_to_fetch:
        file_content_b64 = ""
        logger.debug("Transmitting file chunks, some logs will be disabled")
        for remote_path_to_copy in files_to_fetch:
            with DisableLogger():
                file_content_b64 += src_conn._telnet_connection.execute_command(
                    f"cat {remote_path_to_copy}"
                ).stdout  # "copy" each small file
        logger.debug("File chunks transmitted, full logging restored")

        file_content = base64.b64decode(file_content_b64)  # decoding
        src_conn._telnet_connection.execute_command(f"rm -f {encoded_remote_path}*")  # remove temporary files

        target.write_bytes(file_content)

        if check_control_sum:
            src_conn._check_control_sum(local_path=target, remote_path=source)
