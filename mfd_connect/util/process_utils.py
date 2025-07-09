# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for Process utils."""

import logging
from typing import List, TYPE_CHECKING
from mfd_common_libs import add_logging_level, log_levels
from mfd_connect.exceptions import ProcessNotRunning
from mfd_typing.os_values import OSName

if TYPE_CHECKING:
    from mfd_connect import Connection


logger = logging.getLogger(__name__)
add_logging_level(level_name="MODULE_DEBUG", level_value=log_levels.MODULE_DEBUG)

linux_kill_signal = "SIGINT"


def get_process_by_name(conn: "Connection", process_name: str) -> List[str]:
    """
    Get Process ids of running processes with given name.

    :param conn: Connection object
    :param process_name: Name of process to search process ID for
    :return: list of process ID
    :raises NotImplementedError when connection obj is of OS other than LINUX, WINDOWS, FREEBSD, ESXI
    """
    os_name = conn.get_os_name()
    if os_name == OSName.LINUX:
        return _get_process_by_name_linux(conn=conn, process_name=process_name)
    if os_name == OSName.WINDOWS:
        return _get_process_by_name_windows(conn=conn, process_name=process_name)
    if os_name == OSName.FREEBSD:
        return _get_process_by_name_freebsd(conn=conn, process_name=process_name)
    if os_name == OSName.ESXI:
        return _get_process_by_name_esxi(conn=conn, process_name=process_name)
    raise NotImplementedError(f"Not Implemented for {os_name} OS")


def kill_process_by_name(conn: "Connection", process_name: str) -> None:
    """
    Fetch running Process ID with given name then kill.

    :param conn: Connection object
    :param process_name: name of process to kill
    :raises NotImplementedError when connection obj is of OS other than LINUX, WINDOWS, FREEBSD, ESXI
    """
    os_name = conn.get_os_name()
    if os_name == OSName.LINUX:
        return _kill_process_by_name_linux(conn=conn, process_name=process_name)
    if os_name == OSName.WINDOWS:
        return _kill_process_by_name_windows(conn=conn, process_name=process_name)
    if os_name == OSName.FREEBSD:
        return _kill_process_by_name_freebsd(conn=conn, process_name=process_name)
    if os_name == OSName.ESXI:
        return _kill_process_by_name_esxi(conn=conn, process_name=process_name)
    raise NotImplementedError(f"Not Implemented for {os_name} OS")


def kill_all_processes_by_name(conn: "Connection", process_name: str) -> None:
    """
    Kill all the instance of an application using the image name for Windows OS.

    :param conn: Connection object
    :param process_name: image name of process to kill. Example: wireshark.exe, iexplore.exe
    :raises NotImplementedError when connection obj is of OS other than WINDOWS
    """
    if conn.get_os_name() == OSName.WINDOWS:
        return _kill_all_processes_by_name_windows(conn=conn, process_name=process_name)
    raise NotImplementedError(f"Not Implemented for {conn.get_os_name()} OS")


def _get_process_by_name_esxi(conn: "Connection", process_name: str) -> List[str]:
    """
    Get Process ids of running processes with given name.

    :param conn: Connection object
    :param process_name: Name of process to search process ID for
    :return: list of process ID
    :raises ProcessNotRunning when the process not running
    """
    cmd = f"ps | grep {process_name}"
    res = conn.execute_command(cmd, expected_return_codes={0, 1}, shell=True)
    if res.return_code == 1:
        raise ProcessNotRunning(f"Process {process_name} not running!")
    return [line.split()[0] for line in res.stdout.splitlines() if line.split()[2] == process_name]


def _kill_process_by_name_esxi(conn: "Connection", process_name: str) -> None:
    """
    Fetch running Process ID with given name then kill.

    :param conn: Connection object
    :param process_name: name of process to kill
    """
    for pid in _get_process_by_name_esxi(conn=conn, process_name=process_name):
        command = f"kill {pid}"
        conn.execute_command(command, shell=True)


def _get_process_by_name_freebsd(conn: "Connection", process_name: str) -> List[str]:
    """
    Get Process ids of running processes with given name.

    :param conn: Connection object
    :param process_name: Name of process to search process ID for
    :return: list of process ID
    :raises ProcessNotRunning when the process not running
    """
    cmd = f"ps | grep {process_name}"
    res = conn.execute_command(cmd, expected_return_codes={0, 1})
    if res.return_code == 1:
        raise ProcessNotRunning(f"Process {process_name} not running!")
    return [line.split()[0] for line in res.stdout.splitlines() if line.split()[4] == process_name]


def _kill_process_by_name_freebsd(conn: "Connection", process_name: str) -> None:
    """
    Fetch running Process ID with given name then kill.

    :param conn: Connection object
    :param process_name: name of process to kill
    """
    for pid in _get_process_by_name_freebsd(conn=conn, process_name=process_name):
        command = f"kill {pid}"
        conn.execute_command(command)


def _get_process_by_name_linux(conn: "Connection", process_name: str) -> List[str]:
    """
    Get Process ids of running processes with given name.

    :param conn: Connection object
    :param process_name: Name of process to search process ID for
    :return: list of process ID
    :raises ProcessNotRunning when the process not running
    """
    res = conn.execute_command(f"pidof {process_name}", expected_return_codes={0, 1}, shell=True)
    if res.return_code == 1:
        raise ProcessNotRunning(f"Process {process_name} not running!")
    return res.stdout.split()


def _kill_process_by_name_linux(conn: "Connection", process_name: str) -> None:
    """
    Fetch running Process ID with given name then kill.

    :param conn: Connection object
    :param process_name: name of process to kill
    """
    res = conn.execute_command(
        f"pkill {process_name} --signal {linux_kill_signal}", expected_return_codes={0, 1}, shell=True
    )
    if res.return_code == 0:
        return
    elif res.return_code == 1:
        raise ProcessNotRunning(f"Process {process_name} not running!")


def _get_process_by_name_windows(conn: "Connection", process_name: str) -> List[str]:
    """
    Get Process ids of running processes with given name.

    :param conn: Connection object
    :param process_name: Name of process to search process ID for
    :return: list of process ID
    :raises ProcessNotRunning when the process not running
    """
    cmd = f"Get-Process {process_name} | Select-Object Id"
    res = conn.execute_powershell(cmd, expected_return_codes={0, 1})
    if res.return_code:
        raise ProcessNotRunning(f"Process {process_name} not running!")
    return [line.strip() for line in res.stdout.splitlines()[3:] if line.strip()]


def _kill_process_by_name_windows(conn: "Connection", process_name: str) -> None:
    """
    Fetch running Process ID with given name then kill.

    :param conn: Connection object
    :param process_name: name of process to kill
    """
    for proc in _get_process_by_name_windows(conn=conn, process_name=process_name):
        out = conn.execute_powershell(
            f"taskkill /f /t /pid {proc.strip()}",
            expected_return_codes={0, 1},
        )
        if out.return_code == 1:
            if "not found" in out.stderr:
                logger.log(
                    level=log_levels.MODULE_DEBUG,
                    msg=out.stderr,
                )
            else:
                raise Exception(f"Error occurred while killing the process, {out.stderr}")


def _kill_all_processes_by_name_windows(conn: "Connection", process_name: str) -> None:
    """
    Kill all the instance of an application using the image name.

    :param conn: Connection object
    :param process_name: image name of process to kill. Example: wireshark.exe, iexplore.exe
    """
    conn.execute_powershell(f"taskkill /f /im {process_name}")


def stop_process_by_name(conn: "Connection", process_name: str) -> None:
    """
    Stop process with SIGINT, if it is running.

    :param conn: Connection object
    :param process_name: Name of process to stop.
    :raises Exception: In case of failure
    """
    try:
        get_process_by_name(conn, process_name)
        kill_process_by_name(conn, process_name)
        try:
            get_process_by_name(conn, process_name)
        except ProcessNotRunning:
            logger.log(level=log_levels.MODULE_DEBUG, msg=f"{process_name} process killed")
        else:
            raise Exception(f"Unknown error killing {process_name}")
    except ProcessNotRunning:
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"The {process_name} was not running.")
