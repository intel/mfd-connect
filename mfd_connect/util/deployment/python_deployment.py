# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Script for python deployment."""

import logging
import posixpath
import re
import typing
from mfd_typing.utils import strtobool
from pathlib import PurePosixPath, PureWindowsPath

import requests
from mfd_common_libs import log_levels
from mfd_typing import OSName, OSType
from mfd_typing.cpu_values import CPUArchitecture
from paramiko.ssh_exception import NoValidConnectionsError

from mfd_connect import SSHConnection, RPyCConnection, WinRmConnection
from mfd_connect.exceptions import (
    ModuleFrameworkDesignError,
    ConnectionCalledProcessError,
    MissingPortablePythonOnServerException,
    RPyCDeploymentException,
    WinRMException,
)
from mfd_connect.util.deployment.api import (
    extract_to_directory,
    get_esxi_datastore_path,
    _is_rpyc_responder_running_ssh,
    _is_rpyc_responder_running_winrm,
)

if typing.TYPE_CHECKING:
    from pathlib import PurePath
    from mfd_connect.process import RemoteProcess
    from mfd_connect.base import ConnectionCompletedProcess


logger = logging.getLogger(__name__)

PORTABLE_PYTHON_PATH_UNX = "/tmp/amber_portable_python"
PORTABLE_PYTHON_PATH_WIN = "c:\\amber_portable_python"


class SetupPythonForResponder:
    """Check and prepare python interpreter for deploying RPyC responder on remote host.

    Create non-RPyC connection to remote host, using SSHConnection from MFD connect module or WinRm protocol depending
    on OS type. Next, download PP from given share, unzip and start responder.
    """

    def __init__(
        self,
        ip: str,
        username: str,
        password: str,
        artifactory_url: str,
        artifactory_username: str | None = None,
        artifactory_password: str | None = None,
        certificate: str | None = None,
    ) -> None:
        """
        Initialize deployed rpyc.

        :param ip: remote host IP address
        """
        self.ip = ip
        self.username = username
        self.password = password
        self.artifactory_url = artifactory_url
        self.certificate = certificate
        self._check_parameters()
        self.artifactory_username = artifactory_username
        self.artifactory_password = artifactory_password
        self.is_posix = None
        self.is_esxi = None
        self.esxi_storage_path = None
        self.prepare()

    def _check_parameters(self) -> None:
        """
        Check if required parameters are passed.

        :raises RPyCDeploymentException: If parameters are not passed
        """
        if not all([self.username, self.password is not None, self.artifactory_url]):
            raise RPyCDeploymentException("Missing username, password or url value for python deployment")

    def prepare(self) -> None:
        """Download PP from artifactory and start server."""
        connection = self._connect_via_alternative_connection()
        os_name = connection.get_os_name()
        cpu_arch = connection.get_cpu_architecture()
        bsd_release = None
        if os_name == OSName.FREEBSD:
            bsd_release = connection.execute_command("uname -r", shell=True).stdout.split(".")[0]
        pp_directory_url, pp_filename = self._find_pp_from_url_for_os(os_name, cpu_arch, bsd_release)
        self.is_posix = os_name != OSName.WINDOWS
        self.is_esxi = os_name == OSName.ESXI

        if self.is_esxi:
            self.esxi_storage_path = get_esxi_datastore_path(connection=connection)
            pp_destination = PurePosixPath(self.esxi_storage_path, pp_filename)
            pp_directory = self.esxi_storage_path
        elif not self.is_posix:
            pp_destination = PureWindowsPath(PORTABLE_PYTHON_PATH_WIN, pp_filename)
            pp_directory = PORTABLE_PYTHON_PATH_WIN
        else:
            pp_destination = PurePosixPath(PORTABLE_PYTHON_PATH_UNX, pp_filename)
            pp_directory = PORTABLE_PYTHON_PATH_UNX
        if not connection.path(pp_directory).exists():
            if not self.is_posix:
                command = f'mkdir "{pp_directory}"'
            else:
                command = f'mkdir -p "{pp_directory}"'
            connection.execute_command(command)
        try:
            pp_url = posixpath.join(pp_directory_url, pp_filename)
            responder_path = self._get_future_responder_path(pp_destination)
            if not self._is_rpyc_responder_running(connection, responder_path):
                if not connection.path(pp_destination).exists():
                    logger.log(
                        level=log_levels.MODULE_DEBUG,
                        msg=f"PortablePython does not exist in path: {pp_destination} Starting download PP!",
                    )
                    connection.download_file_from_url(pp_url, pp_destination)
                self._unzip_portable_python(connection, pp_destination)
                self._start_rpyc_responder(connection, responder_path)
        finally:
            logger.log(level=log_levels.MODULE_DEBUG, msg="Close temporary connection")
            connection.disconnect()

    def _find_pp_from_url_for_os(
        self,
        os_name: OSName,
        cpu_arch: CPUArchitecture,
        bsd_release: str | None = None,
    ) -> tuple[str, str]:
        """For artifactory build find correct portable python zip filename and url."""
        if os_name is OSName.ESXI:
            pp_directory_url = posixpath.join(self.artifactory_url, "light_interpreter", "ESXi")
        else:
            pp_directory_url = posixpath.join(self.artifactory_url, "wrapper_interpreter", os_name.value)
            if os_name is OSName.FREEBSD:
                pp_directory_url = posixpath.join(pp_directory_url, bsd_release)
            if os_name is OSName.LINUX:  # linux can contain arm package
                arch_directory = self._map_arch_value_with_share_directory(cpu_arch)
                pp_directory_url = self._get_correct_pp_directory_url(arch_directory, pp_directory_url)

        pp_filename = self._get_name_of_pp_zip(pp_directory_url)
        return pp_directory_url, pp_filename

    def _get_name_of_pp_zip(self, pp_directory_url: str) -> str:
        """
        Get the name of zip file for portable python based on output from request.

        :param pp_directory_url: The URL of the portable python interpreter directory on share.
        :return: The name of zip file.
        :raises MissingPortablePythonOnServerException: When not found zip file on the share.
        """
        logger.log(
            level=log_levels.MODULE_DEBUG,
            msg=f"Sending request asking for {pp_directory_url} to get name of zip file",
        )
        response = requests.get(pp_directory_url, cert=self.certificate)
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Received response: {response}")
        regex = r"<a href=\"(?P<zip_file>PP_\w+_\S+\.zip)\">"
        match = re.search(regex, response.text)
        if match is None:
            raise MissingPortablePythonOnServerException("Could not found correct PP zip in artifactory")
        pp_filename = match.group("zip_file")
        return pp_filename

    def _get_correct_pp_directory_url(self, bitness_directory: str, pp_directory_url: str) -> str:
        """
        Get the URL for the PP directory based on the bitness.

        Handle case where directory for each bitness is not present (old structure)
        :param bitness_directory: Name of directory for os bitness.
        :param pp_directory_url: The URL for the directory with potential wrapper interpreter
        :return: The URL for the directory with wrapper interpreter.
        """
        logger.log(
            level=log_levels.MODULE_DEBUG,
            msg=f"Sending request asking for {pp_directory_url} to check, if bitness directories are there.",
        )
        response = requests.get(pp_directory_url)
        if ".zip" not in response.text:
            pp_directory_url = posixpath.join(pp_directory_url, bitness_directory)
        return pp_directory_url

    def _map_arch_value_with_share_directory(self, cpu_arch: CPUArchitecture) -> str:
        """
        Map CPUArchitecture value with the corresponding directory on the share.

        :param cpu_arch: CPUArchitecture value
        :return: Directory with portable python interpreter for the given CPUArchitecture
        :raises MissingPortablePythonOnServerException: if not supported architecture
        """
        if cpu_arch is CPUArchitecture.ARM64:
            arch_directory = "aarch64"
        elif cpu_arch is CPUArchitecture.X86_64:
            arch_directory = "x86_64"
        else:
            raise MissingPortablePythonOnServerException(f"Not supported architecture for PP: {cpu_arch}")
        return arch_directory

    def _get_future_responder_path(self, zip_path: "PurePath") -> str:
        """
        Get a responder path from zip file available after unpacking.

        :param zip_path: Path to downloaded/destination of zipped portable python
        :return path to unpacked python executable.
        """
        if self.is_posix:
            destination_directory_name = PurePosixPath(zip_path).stem
            dest_path = self.esxi_storage_path if self.is_esxi else PORTABLE_PYTHON_PATH_UNX
            dest = posixpath.join(dest_path, destination_directory_name)
            new_interpreter_path = f"{dest}/bin/python"
        else:
            destination_directory_name = PureWindowsPath(zip_path).stem
            dest = str(PureWindowsPath(PORTABLE_PYTHON_PATH_WIN, destination_directory_name))
            new_interpreter_path = rf"{dest}\python.exe"
        return new_interpreter_path

    def _unzip_portable_python(self, connection: SSHConnection | WinRmConnection, zip_path: "PurePath") -> str:
        """Extract portable python on remote host and get path for new interpreter.

        :return: path to copied portable python interpreter
        """
        logger.log(
            level=log_levels.MODULE_DEBUG, msg=f"Unpack portable python package and extract it on host {self.ip}"
        )
        if self.is_posix:
            new_interpreter_path = self._unzip_pp_posix(connection, zip_path)
        else:
            new_interpreter_path = self._unzip_pp_windows(connection, zip_path)

        logger.log(
            level=log_levels.MODULE_DEBUG,
            msg=f"New python interpreter: {new_interpreter_path} has been successfully set for deployed responder",
        )
        return new_interpreter_path

    def _unzip_pp_windows(self, connection: "WinRmConnection", zip_path: "PurePath") -> str:
        """
        Unzip and return python binary path.

        :param connection: Connection to the machine
        :param zip_path: Path to PP zip file.
        :return: Path for executable binary
        """
        destination_directory_name = PureWindowsPath(zip_path).stem
        dest = PureWindowsPath(PORTABLE_PYTHON_PATH_WIN, destination_directory_name)
        check_command = f'powershell.exe Test-Path -Path \\"{dest}\\"'
        result = connection.execute_command(check_command)
        if strtobool(result.stdout.strip()):  # destination exists
            delete_command = f'powershell.exe Remove-Item \\"{dest}\\" -Recurse -Force'
            result = connection.execute_command(delete_command)
            if result.stderr:
                raise RPyCDeploymentException(
                    f"Cannot remove old portable python from machine {self.ip}: {result.stderr}"
                )
        extract_to_directory(connection, zip_path, dest)
        new_interpreter_path = rf"{dest}\python.exe"
        return new_interpreter_path

    def _unzip_pp_posix(self, connection: "SSHConnection", zip_path: "PurePath") -> str:
        """
        Unzip and return python binary path.

        :param connection: Connection to the machine
        :param zip_path: Path to PP zip file.
        :return: Path for executable binary
        """
        destination_directory_name = PurePosixPath(zip_path).stem
        dest_dir = self.esxi_storage_path if self.is_esxi else PORTABLE_PYTHON_PATH_UNX
        dest = posixpath.join(dest_dir, destination_directory_name)
        if self.is_esxi:
            connection.path(dest).mkdir(parents=True, exist_ok=True)
        try:
            connection.execute_command(f"unzip -q -n {zip_path} -d {dest}")
        except ConnectionCalledProcessError as e:
            connection.path(dest).unlink()
            raise RPyCDeploymentException(f"Cannot copy portable python from share: {e}")
        new_interpreter_path = f"{dest}/bin/python"
        return new_interpreter_path

    def _connect_via_alternative_connection(self) -> SSHConnection | WinRmConnection:
        """Connect via SSH or WinRM.

        :return: SSH or WinRM connection
        """
        connection = None
        logger.log(
            level=log_levels.MODULE_DEBUG,
            msg=f"Making temporary SSH connection using one of provided credentials on host {self.ip}",
        )
        try:
            connection = SSHConnection(
                ip=self.ip, username=self.username, password=self.password, skip_key_verification=True
            )
            if connection._os_type != OSType.POSIX:  # do not use SSH for Windows
                connection = None
        except (NoValidConnectionsError, ModuleFrameworkDesignError):
            logger.log(level=log_levels.MODULE_DEBUG, msg=f"Cannot establish SSHConnection with {self.ip}")
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg=f"Making temporary WinRM connection using one of provided credentials on host {self.ip}",
            )
        if connection is None:
            try:
                connection = WinRmConnection(ip=self.ip, username=self.username, password=self.password)
            except WinRMException as e:
                raise RPyCDeploymentException(
                    f"Cannot set up temporary connection on {self.ip} with provided credentials"
                ) from e
        return connection

    def _start_rpyc_responder(
        self, connection: SSHConnection | WinRmConnection, responder_path: str
    ) -> "ConnectionCompletedProcess | RemoteProcess":
        """
        Try to start rpyc responder using SSH or WinRm connection.

        :param connection: Connection object
        :param responder_path: Path to python interpreter.
        :raises RPyCDeploymentException: on failure
        """
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Start unpacked portable python package on host {self.ip}")
        try:
            return self.__start_rpyc_responder(connection, responder_path)
        except ConnectionCalledProcessError as e:
            raise RPyCDeploymentException(f"Cannot copy portable python from share: {e}")

    def __start_rpyc_responder(
        self, connection: SSHConnection | WinRmConnection, responder_path: str
    ) -> "ConnectionCompletedProcess | RemoteProcess":
        """
        Start rpyc responder using SSH or WinRm connection.

        :param connection: Connection object
        :param responder_path: Path to python interpreter.
        """
        if isinstance(connection, SSHConnection):
            log_file = PurePosixPath(PORTABLE_PYTHON_PATH_UNX, "rpyc_responder.log")
            logger.log(level=log_levels.MODULE_DEBUG, msg="Make sure directory for storing rpyc responder logs exists")
            log_file_object = connection.path(log_file)
            log_file_object.parent.mkdir(parents=True, exist_ok=True)
            log_file_object.touch(exist_ok=True)

            command = (
                f"nohup {responder_path} -m mfd_connect.rpyc_server "
                f"--port {RPyCConnection.DEFAULT_RPYC_6_0_0_RESPONDER_PORT + 1} "
                f"-l {log_file} &"
            )
            return connection.execute_command(
                command,
                discard_stderr=True,
                discard_stdout=True,
                shell=True,
            )
        else:
            log_file = PureWindowsPath(PORTABLE_PYTHON_PATH_WIN, "rpyc_responder.log")
            return connection.start_process(
                f"{responder_path} -m mfd_connect.rpyc_server "
                f"--port {RPyCConnection.DEFAULT_RPYC_6_0_0_RESPONDER_PORT + 1} "
                f"> {log_file} 2>&1",
            )

    def _is_rpyc_responder_running(self, connection: SSHConnection | WinRmConnection, responder_path: str) -> bool:
        """
        Check if correct responder is running on host.

        Kill any incorrect run responder.

        :param connection: connection to host
        :param responder_path: path to responder
        :return True if correct responder is running, False otherwise
        """
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Checking if responder is started already on host {self.ip}")
        if isinstance(connection, SSHConnection):
            return _is_rpyc_responder_running_ssh(connection, responder_path)
        else:
            return _is_rpyc_responder_running_winrm(connection, responder_path)
