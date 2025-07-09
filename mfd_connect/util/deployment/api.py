# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""API for deployment."""

import logging
from pathlib import PurePath

from mfd_common_libs import log_levels
from mfd_typing import OSName

from mfd_connect import RPyCConnection, WinRmConnection, SSHConnection
from mfd_connect.exceptions import RPyCDeploymentException

logger = logging.getLogger(__name__)


def get_esxi_datastore_path(
    connection: "SSHConnection", storage_path_pattern: str = "/vmfs/volumes/datastore_*"
) -> str:
    """Resolve ESXi datastore real location from provided pattern.

    :param connection: SSH connection to the ESXI host
    :param storage_path_pattern:
    :return: Resolved symbolic link to ESXI datastore
    """
    datastore_path = connection.execute_command(f"readlink -f {storage_path_pattern}").stdout.rstrip()
    return datastore_path


def _is_rpyc_responder_running_winrm(connection: "WinRmConnection", responder_path: str) -> bool:
    """
    Check if correct responder is running on host via WinRM.

    Kill any incorrect run responder.

    :param connection: connection to host
    :param responder_path: path to responder
    :return True if correct responder is running, False otherwise
    """
    result = connection.execute_command(
        'powershell.exe -command "Get-WmiObject Win32_Process -Filter \\"name = \'python.exe\'\\" | '
        "Select-Object CommandLine,ProcessID | "
        'Where-Object -Property CommandLine -like \\"*mfd_connect*'
        f'--port {RPyCConnection.DEFAULT_RPYC_6_0_0_RESPONDER_PORT+1}*\\" | Select -Expand ProcessID"'
    )
    if result.stdout:
        rpyc_pid = int(result.stdout)
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"RPYC responder is running with PID {rpyc_pid}")
        logger.log(level=log_levels.MODULE_DEBUG, msg="Checking if started rpyc responder is correct one.")
        result = connection.execute_command(
            'powershell.exe -command "Get-WmiObject Win32_Process | '
            f"Where-Object -Property Path -EQ '{responder_path}' | "
            'Select -Expand ProcessID"'
        )
        if result.stdout:
            pp_rpyc_pid = int(result.stdout)
            if pp_rpyc_pid == rpyc_pid:
                logger.log(level=log_levels.MODULE_DEBUG, msg=f"Correct RPYC responder is running with PID {rpyc_pid}")
                return True
        else:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg="Not expected RPYC responder is running, going to kill that one.",
            )
            connection.execute_command(f'powershell.exe -command "Stop-Process -ID {rpyc_pid} -Force"')

    logger.log(level=log_levels.MODULE_DEBUG, msg="Any deployed RPYC responder is not running.")
    return False


def _is_rpyc_responder_running_ssh(connection: "SSHConnection", responder_path: str) -> bool:
    """
    Check if correct responder is running on host via SSH.

    Kill any incorrect run responder.

    :param connection: connection to host
    :param responder_path: path to responder
    :return True if correct responder is running, False otherwise
    """
    if connection.get_os_name() == OSName.ESXI:
        command_list_all_processess = "ps -c"
    else:
        command_list_all_processess = "ps aux"

    result = connection.execute_command(
        f"{command_list_all_processess} | grep 'mfd_connect.rpyc_server --port "
        f"{RPyCConnection.DEFAULT_RPYC_6_0_0_RESPONDER_PORT+1}' |grep -v grep | "
        "awk '{print $2}'",
        shell=True,
    )
    if result.stdout:
        rpyc_pid_str = result.stdout.splitlines()[0]  # on ESxi there are 2 PIDs returned - do not know why
        rpyc_pid = int(rpyc_pid_str)
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"RPYC responder is running with PID {rpyc_pid}")
        logger.log(level=log_levels.MODULE_DEBUG, msg="Checking if started rpyc responder is correct one.")
        result = connection.execute_command(
            f"{command_list_all_processess} | grep '{responder_path}' |grep -v grep | awk '{{print $2}}'",
            shell=True,
        )
        if result.stdout:
            pp_rpyc_pid_str = result.stdout.splitlines()[0]
            pp_rpyc_pid = int(pp_rpyc_pid_str)
            if pp_rpyc_pid == rpyc_pid:
                logger.log(level=log_levels.MODULE_DEBUG, msg=f"Correct RPYC responder is running with PID {rpyc_pid}")
                return True
        else:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg="Not expected RPYC responder is running, going to kill that one.",
            )
            connection.execute_command(f"kill -9 {rpyc_pid}")

    logger.log(level=log_levels.MODULE_DEBUG, msg="Any RPYC responder is not running.")
    return False


def extract_to_directory(connection: "WinRmConnection", zip_path: "PurePath", destination_path: "PurePath") -> None:
    """
    Unpack files with .net method ExtractToDirectory via PowerShell. Should be supported with PowerShell 4+.

    :param connection: connection to machine
    :param zip_path: path to zipped files
    :param destination_path: destination
    :raise RPyCDeploymentException: When error occurs
    """
    result = connection.execute_command(
        "powershell.exe Add-Type -Assembly System.IO.Compression.Filesystem; "
        f'[System.IO.Compression.ZipFile]::ExtractToDirectory(\\"{zip_path}\\", \\"{destination_path}\\")'
    )
    if result.stderr:
        connection.execute_command(f"del /F {destination_path}")
        raise RPyCDeploymentException(f"Error during unpacking files {zip_path} to {destination_path}: {result.stderr}")
