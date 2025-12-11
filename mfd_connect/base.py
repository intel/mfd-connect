# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for Connection base classes."""

import base64
import hashlib
import logging
import random
import re
import sys
from abc import ABC, abstractmethod, ABCMeta
from pathlib import Path, PurePath
from subprocess import CalledProcessError
from typing import TYPE_CHECKING, Iterable, ClassVar, Type, List, Union, Optional
from netaddr import IPAddress

from mfd_common_libs import add_logging_level, log_levels

from mfd_typing.cpu_values import CPUArchitecture
from mfd_typing.os_values import OSType, OSName, OSBitness, SystemInfo

from mfd_connect.util.rpc_system_info_utils import (
    _get_system_info_freebsd,
    _get_system_info_esxi,
    _get_system_info_windows,
    _get_system_info_linux,
)
from .api.download_utils import (
    download_file_unix,
    download_file_esxi,
    download_file_windows,
    download_file_unix_via_controller,
    _prepare_headers_powershell,
    _prepare_headers_curl,
    _generate_random_string,
    _prepare_headers_with_env_powershell,
)

from .exceptions import (
    IncorrectAffinityMaskException,
    GatheringSystemInfoError,
    UnavailableServerException,
    TransferFileError,
    OsNotSupported,
    CPUArchitectureNotSupported,
    ConnectionCalledProcessError,
)
from .util.decorators import conditional_cache

if TYPE_CHECKING:
    from .process import RemoteProcess
    from pydantic import BaseModel
    from subprocess import CompletedProcess

logger = logging.getLogger(__name__)
add_logging_level(level_name="MODULE_DEBUG", level_value=log_levels.MODULE_DEBUG)


class ConnectionCompletedProcess:
    """
    Completed Process for Connection class.

    Object of this class is returned by execute_command().

    It prevents from usages of fields which are not supported for Connection.
    Usage example:
    >>> res = ConnectionCompletedProcess(args=['echo','test'], return_code=1)
    >>> res.stdout
    NotImplementedError is raised with message "This type of Connection doesn't support stdout!"
    >>> res.return_code
    1
    """

    def __init__(
        self,
        args: list[str] | str,
        *,
        stdout: str | None = None,
        stderr: str | None = None,
        stdout_bytes: bytes | None = None,
        stderr_bytes: bytes | None = None,
        return_code: int | None = None,
    ) -> None:
        """
        Init of ConnectionCompletedProcess.

        :param args: The list or str args passed to execute_command().
        :param stdout: The standard output.
        :param stderr: The standard error.
        :param stdout_bytes: Raw bytes from standard output.
        :param stderr_bytes: Raw bytes from standard error.
        :param return_code: The return code of command.
        """
        super().__init__()
        self._args = args
        self._stdout = stdout
        self._stderr = stderr
        self._stdout_bytes = stdout_bytes
        self._stderr_bytes = stderr_bytes
        self._return_code = return_code

    def __repr__(self):
        args = [
            f"{arg_name.lstrip('_')}={arg_value!r}"
            for arg_name, arg_value in self.__dict__.items()
            if arg_value is not None
        ]
        return "{}({})".format(type(self).__name__, ", ".join(args))

    @property
    def args(self) -> Union[List[str], str]:
        """Get the list or str args passed to execute_command()."""
        return self._args

    @property
    def stdout(self) -> str:
        """
        Get the standard output.

        :raises NotImplementedError with proper message, when Connection doesn't support stdout.
        """
        if self._stdout is None:
            raise NotImplementedError("This type of Connection doesn't support stdout!")
        return self._stdout

    @property
    def stderr(self) -> str:
        """
        Get the standard error.

        :raises NotImplementedError with proper message, when Connection doesn't support stderr.
        """
        if self._stderr is None:
            raise NotImplementedError("This type of Connection doesn't support stderr!")
        return self._stderr

    @property
    def return_code(self) -> int:
        """
        Get the return code of command.

        :raises NotImplementedError with proper message, when Connection doesn't support return codes.
        """
        if self._return_code is None:
            raise NotImplementedError("This type of Connection doesn't support return_code!")
        return self._return_code

    @property
    def stdout_bytes(self) -> bytes:
        """
        Get raw bytes from standard output.

        :raises NotImplementedError with proper message, when Connection doesn't support stdout_bytes.
        """
        if self._stdout_bytes is None:
            raise NotImplementedError("This type of Connection doesn't support stdout_bytes!")
        return self._stdout_bytes

    @property
    def stderr_bytes(self) -> bytes:
        """
        Get raw bytes from standard error.

        :raises NotImplementedError with proper message, when Connection doesn't support stderr_bytes.
        """
        if self._stderr_bytes is None:
            raise NotImplementedError("This type of Connection doesn't support stderr_bytes!")
        return self._stderr_bytes


class ConnectMeta(ABC, type):
    """Metaclass for Connect classes."""

    def __call__(cls, *args, **kwargs):
        """Call method of Connections' MetaClass."""
        conn: "Connection" = type.__call__(cls, *args, **kwargs)
        conn.collect_data(conn)
        return conn


class ConnectABCMeta(ConnectMeta, ABCMeta):
    """Metaclass for Connect classes."""


class Connection(ABC, metaclass=ConnectABCMeta):
    """
    Base class for synchronous Connection.

    It can execute only one command at a time.
    """

    def collect_data(self, conn: "Connection") -> None:
        """
        Collect data from connection.

        It can be overwritten in separated module, like telemery to collect data.
        """
        pass

    def __init__(
        self, model: "BaseModel | None" = None, default_timeout: int | None = None, cache_system_data: bool = True
    ):
        """
        Initialize the class - set the model attribute.

        :param model: pydantic model of connection
        :param default_timeout: Timeout value for executing timeout for entire class.
        :param cache_system_data: Flag to cache system data like self._os_type, OS name, OS bitness and CPU architecture
        """
        self.model = model
        self.cache_system_data = cache_system_data
        self._default_timeout = default_timeout
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Cache system data set to {str(cache_system_data).upper()}")

    @abstractmethod
    def execute_command(
        self,
        command: str,
        *,
        input_data: str = None,
        cwd: str = None,
        timeout: int = None,
        env: dict = None,
        stderr_to_stdout: bool = False,
        discard_stdout: bool = False,
        discard_stderr: bool = False,
        skip_logging: bool = False,
        expected_return_codes: Iterable | None = frozenset({0}),
        shell: bool = False,
        custom_exception: Type[CalledProcessError] = None,
    ) -> "ConnectionCompletedProcess":
        """
        Run program and wait for it's completion.

        :param command: Command to execute, with all necessary arguments
        :param input_data: Data to pass to program on the standard input
        :param cwd: Directory to start program execution in
        :param timeout: Program execution timeout, in seconds
        :param env: Environment to execute the program in
        :param stderr_to_stdout: Redirect stderr to stdout, ignored if discard_stderr is set to True
        :param discard_stdout: Don't capture stdout stream
        :param discard_stderr: Don't capture stderr stream
        :param skip_logging: Skip logging of stdout/stderr if captured
        :param expected_return_codes: Return codes to be considered acceptable.
                                      If None - any return code is considered acceptable
        :param shell: Start process in a shell. Allows usage of shell constructions like pipes etc.
        :param custom_exception: Enable us to raise our exception if program exits with an unexpected return code.
        custom_exception must inherit from CalledProcessError to use its fields like returncode, cmd, output, stderr

        :return: ConnectionCompletedProcess object
        :raises TimeoutExpired: if program doesn't conclude before timeout is reached
        :raises ConnectionCalledProcessError: if program exits with an unexpected return code
        """
        pass

    def execute_powershell(
        self,
        command: str,
        *,
        input_data: Optional[str] = None,
        cwd: Optional[str] = None,
        timeout: int = None,
        env: Optional[dict] = None,
        stderr_to_stdout: bool = False,
        discard_stdout: bool = False,
        discard_stderr: bool = False,
        skip_logging: bool = False,
        expected_return_codes: Optional[Iterable] = frozenset({0}),
        shell: bool = False,
        custom_exception: Type[CalledProcessError] = None,
    ) -> "ConnectionCompletedProcess":
        """
        Run program and wait for it is completion.

        :param command: Command to execute, with all necessary arguments
        :param input_data: Data to pass to program on the standard input
        :param cwd: Directory to start program execution in
        :param timeout: Program execution timeout, in seconds
        :param env: Environment to execute the program in
        :param stderr_to_stdout: Redirect stderr to stdout, ignored if discard_stderr is set to True
        :param discard_stdout: Don't capture stdout stream
        :param discard_stderr: Don't capture stderr stream
        :param skip_logging: Skip logging of stdout/stderr if captured
        :param expected_return_codes: Return codes to be considered acceptable.
                                      If None - any return code is considered acceptable
        :param shell: Start process in a shell. Allows usage of shell constructions like pipes etc.
        :param custom_exception: Enable us to raise our exception if program exits with an unexpected return code.
        custom_exception must inherit from CalledProcessError to use its fields like returncode, cmd, output, stderr

        :return: ConnectionCompletedProcess object
        :raises TimeoutExpired: if program doesn't conclude before timeout is reached
        :raises ConnectionCalledProcessError: if program exits with an unexpected return code
        """
        pass

    def get_system_info(self) -> SystemInfo:
        """Get SystemInfo."""
        os_name = self.get_os_name()

        if os_name == OSName.EFISHELL:
            raise OSError("Can't retrieve system info on EFI Shell-booted platform.")

        try:
            if os_name == OSName.WINDOWS:
                return _get_system_info_windows(connection=self)
            elif os_name == OSName.LINUX:
                return _get_system_info_linux(connection=self)
            elif os_name == OSName.FREEBSD:
                return _get_system_info_freebsd(connection=self)
            elif os_name == OSName.ESXI:
                return _get_system_info_esxi(connection=self)
        except Exception as exc:
            raise GatheringSystemInfoError(exc)

    @abstractmethod
    def get_os_type(self) -> OSType:
        """Get type of client os."""
        pass

    @abstractmethod
    def get_os_name(self) -> OSName:
        """Get name of client os."""
        pass

    @abstractmethod
    def get_os_bitness(self) -> OSBitness:
        """Get bitness of client os."""
        pass

    @abstractmethod
    def get_cpu_architecture(self) -> CPUArchitecture:
        """Get CPU architecture of Host."""
        pass

    @abstractmethod
    def restart_platform(self) -> None:
        """Reboot host."""
        pass

    @abstractmethod
    def shutdown_platform(self) -> None:
        """Shutdown host."""
        pass

    @abstractmethod
    def wait_for_host(self, timeout: int = 60) -> None:
        """
        Wait for host availability.

        :param timeout: Time to check until fail
        :raises TimeoutError: when timeout is expired
        """
        pass

    @property
    @abstractmethod
    def path(self) -> Path:
        """
        Path represents a filesystem path.

        :return: Path object for Connection
        """
        pass

    @property
    def ip(self) -> IPAddress:
        """IP address to which the connection is established."""
        return self._ip

    @property
    def default_timeout(self) -> int | None:
        """Access default timeout for execute_command."""
        return self._default_timeout

    @default_timeout.setter
    def default_timeout(self, timeout: int) -> None:
        """Set default timeout value."""
        self._default_timeout = timeout
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Default timeout for execute_command set to {timeout}")

    @default_timeout.deleter
    def default_timeout(self) -> None:
        """Delete default timeout value."""
        self._default_timeout = None
        logger.log(level=log_levels.MODULE_DEBUG, msg="Default timeout deleted")

    @property
    def cache_system_data(self) -> None | bool:
        """Flag to cache system data like _os_type, name of OS, OS bitness or CPU architecture."""
        return self._cache_system_data

    @cache_system_data.setter
    def cache_system_data(self, value: bool) -> None:
        """Set cache system data flag.

        :param value: Flag to cache system data like _os_type, name of OS, OS bitness or CPU architecture.
        """
        self._cache_system_data = value
        if not value:
            self._cached_methods = {}

    def log_connected_host_info(self) -> None:
        """Log information about connected host."""
        if logging.root.level <= log_levels.MODULE_DEBUG:
            if hasattr(self, "_os_type"):
                os_type = self._os_type
            else:
                os_type = self.get_os_type()
            if hasattr(self, "_os_name"):
                os_name = self._os_name
            else:
                os_name = self.get_os_name()
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg=f"{self.__class__.__name__} established with:"
                f" {os_type},"
                f" {os_name},"
                f" {self.get_os_bitness()},"
                f" {getattr(self, '_ip', 'N/A')}",
            )

    @abstractmethod
    def disconnect(self) -> None:
        """Close connection with host."""
        pass

    def _apply_cpu_affinity_win(self, *, pid: int, affinity_mask: int) -> None:
        """
        Apply calculated affinity_mask to given process ID under Windows OS using Windows API wrapper.

        :param pid: ID of the process to be assigned the affinity mask.
        :param affinity_mask: Value represeting the numbers of CPUs that the process will be assigned to.
        """
        win32con = self.modules().win32con
        flags = win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_SET_INFORMATION
        phandle = self.modules().win32api.OpenProcess(flags, 0, pid)
        logger.log(
            level=log_levels.MODULE_DEBUG, msg=f"Setting the affinity mask {hex(affinity_mask)} for process {pid}"
        )
        self.modules().win32process.SetProcessAffinityMask(phandle, affinity_mask)

    @staticmethod
    def _create_affinity_mask(cpu: Union[int, List[int], str]) -> int:
        """
        Create an integer CPU affinity mask based on the user-specified input value.

        :param cpu: Processor numbers the process will run on in a format chosen by the user. Acceptable formats are:
                    cpu=1, cpu=[1, 2, 3, 6], cpu="1, 4, 5", cpu="1-7", cpu="0, 2-6"
        :raises IncorrectAffinityMaskException: if cpu given in incorrect format/type
        :return: Calculated CPU mask converted to int format
        """
        if isinstance(cpu, int):
            return Connection._create_affinity_mask_from_int(cpu)
        elif isinstance(cpu, list):
            return Connection._create_affinity_mask_from_list(cpu)
        elif isinstance(cpu, str):
            return Connection._create_affinity_mask_from_string(cpu)
        else:
            raise IncorrectAffinityMaskException(
                f"Incorrect format of affinity mask: {cpu} - should be int, list or string"
            )

    @staticmethod
    def _create_affinity_mask_from_int(cpu: int) -> int:
        """
        Create an integer CPU affinity mask based on the user-specified input value.

        :param cpu: Processor number the process will run on.
        :return: Calculated CPU mask converted to int format
        """
        return 1 << cpu

    @staticmethod
    def _create_affinity_mask_from_list(cpu: List[int]) -> int:
        """
        Create an integer CPU affinity mask based on the user-specified input value.

        :param cpu: List of processor numbers the process will run on.
        :raises IncorrectAffinityMaskException: if cpu given in incorrect format
        :return: Calculated CPU mask converted to int format
        """
        mask = 0
        for i in cpu:
            if isinstance(i, int):
                mask |= 1 << i
            else:
                raise IncorrectAffinityMaskException("Affinity list can contain only integer values!")
        return mask

    @staticmethod
    def _create_affinity_mask_from_string(cpu: str) -> int:
        """
        Create an integer CPU affinity mask based on the user-specified input value.

        :param cpu: String with processor numbers, ranges of processor numbers, or both the process will run on.
                    Acceptable formats are: cpu="1, 4, 5", cpu="1-7", cpu="0, 2-6"
        :raises IncorrectAffinityMaskException: if cpu given in incorrect format
        :return: Calculated CPU mask converted to int format
        """
        mask = 0
        for i in cpu.replace(" ", "").split(","):
            if i.isnumeric():
                mask |= 1 << int(i)
            elif "-" in i:
                cpu_start, cpu_stop = i.split("-")
                if cpu_start.isnumeric() and cpu_stop.isnumeric():
                    for j in range(int(cpu_start), int(cpu_stop) + 1):
                        mask |= 1 << j
                else:
                    raise IncorrectAffinityMaskException("Incorrect format of CPUs range: {i} in affinity mask")
            else:
                raise IncorrectAffinityMaskException(f"Incorrect format of affinity mask string: {i}")
        return mask


class AsyncConnection(Connection, ABC):
    """
    Base class for asynchronous Connection.

    It can:
        - execute one command at a time,
        - start parallel processes.
    """

    _process_class: ClassVar[Type["RemoteProcess"]] = None

    def __init__(
        self,
        ip: "IPAddress | str",
        model: "BaseModel | None" = None,
        default_timeout: int | None = None,
        cache_system_data: bool = True,
    ) -> None:
        """
        Initialize the class - set the ip address attribute.

        :param ip: IP address to which the connection is established.
        :param model: pydantic model of connection
        :param default_timeout: Timeout value for executing timeout for entire class.
        :param cache_system_data: Flag to cache system data like self._os_type, OS name, OS bitness and CPU architecture
        """
        super().__init__(model, default_timeout, cache_system_data)
        self._ip = IPAddress(ip)
        self._cached_os_type = None

    @property
    def cache_system_data(self) -> None | bool:
        """Flag to cache system data like _os_type, name of OS, OS bitness or CPU architecture."""
        return super().cache_system_data

    @cache_system_data.setter
    def cache_system_data(self, value: bool) -> None:
        """Set cache system data flag.

        :param value: Flag to cache system data like _os_type, name of OS, OS bitness or CPU architecture.
        """
        self._cache_system_data = value
        if not value:
            self._cached_os_type = None
            self._cached_methods = {}

    @property
    def _os_type(self) -> OSType:
        """Property for cached os type."""
        if self.cache_system_data and self._cached_os_type is not None:
            return self._cached_os_type
        os_type = self.get_os_type()
        if self.cache_system_data:
            self._cached_os_type = os_type
        return os_type

    @_os_type.setter
    def _os_type(self, value: OSType) -> None:
        """
        Setter for cached os type.

        :param value: Value to set
        """
        self._cached_os_type = value

    def _prepare_log_file(
        self, command: str, log_file: bool, output_file: Optional[Union[str, "Path"]]
    ) -> Optional["Path"]:
        """
        Prepare log file.

        Method calculate sha from command line and returns Path object to file or create output_file on system.

        :param command: command string
        :param log_file: Switch to prepare log file if required
        :param output_file: File path to use as redirection, interchangeably with log_file
        :return: Path object to file or create output_file on system
        """
        log_path = None
        if output_file is not None:
            log_path = output_file if not isinstance(output_file, str) else self.path(output_file)
            log_directory = log_path.parents[0]
            if not log_directory.exists():
                log_directory.mkdir(parents=True)
            log_path.touch()
        elif log_file is True:
            log_filename = f"{hashlib.shake_256((command+str(random.getrandbits(128))).encode()).hexdigest(6)}.log"
            logs_directory = None
            if self.get_os_name() == OSName.ESXI:
                datastore_pattern = "/vmfs/volumes/datastore*"
                datastore_paths = self.modules().glob.glob(datastore_pattern)
                if datastore_paths:
                    # Take the first datastore found
                    logs_directory = self.path(datastore_paths[0], "execution_logs").expanduser()
            if not logs_directory:
                logs_directory = self.path("~", "execution_logs").expanduser()
            log_path = logs_directory / log_filename
            if not logs_directory.exists():
                logs_directory.mkdir(parents=True, exist_ok=True)
            log_path.touch()
        return log_path

    @abstractmethod
    def start_process(
        self,
        command: str,
        *,
        cwd: str = None,
        env: dict = None,
        stderr_to_stdout: bool = False,
        discard_stdout: bool = False,
        discard_stderr: bool = False,
        cpu_affinity: Optional[Union[int, List[int], str]] = None,
        shell: bool = False,
        enable_input: bool = False,
        log_file: bool = False,
        output_file: Optional[str] = None,
    ) -> "RemoteProcess":
        """
        Start process.

        :param command: Command to execute, with all necessary arguments
        :param cwd: Directory to start program execution in
        :param env: Environment to execute the program in
        :param stderr_to_stdout: Redirect stderr to stdout, ignored if discard_stderr is set to True
        :param discard_stdout: Don't capture stdout stream
        :param discard_stderr: Don't capture stderr stream
        :param cpu_affinity: Processor numbers the process will run on in a format chosen by the user.
                             Acceptable formats are: cpu=1, cpu=[1, 2, 3, 6], cpu="1, 4, 5", cpu="1-7", cpu="0, 2-6"
        :param shell: Start process in a shell. Allows usage of shell constructions like pipes etc.
        :param enable_input: Whether or not allow writing to process' stdin
        :param log_file: Switch to enable redirection to generated by method log file
        :param output_file: Path to file as redirection of command output, interchangeably with log_file param.
        :return: Running process, RemoteProcess object
        """
        pass

    @abstractmethod
    def start_processes(
        self,
        command: str,
        *,
        cwd: str = None,
        env: dict = None,
        stderr_to_stdout: bool = False,
        discard_stdout: bool = False,
        discard_stderr: bool = False,
        cpu_affinity: Optional[Union[int, List[int], str]] = None,
        shell: bool = False,
        enable_input: bool = False,
        log_file: bool = False,
        output_file: Optional[str] = None,
    ) -> List["RemoteProcess"]:
        """
        Start processes.

        Use start_processes if you need to execute cmd which will trigger more than one process,
        and you want to receive list of new processes.

        :param command: Command to execute, with all necessary arguments
        :param cwd: Directory to start program execution in
        :param env: Environment to execute the program in
        :param stderr_to_stdout: Redirect stderr to stdout, ignored if discard_stderr is set to True
        :param discard_stdout: Don't capture stdout stream
        :param discard_stderr: Don't capture stderr stream
        :param cpu_affinity: Processor numbers the process will run on in a format chosen by the user.
                             Acceptable formats are: cpu=1, cpu=[1, 2, 3, 6], cpu="1, 4, 5", cpu="1-7", cpu="0, 2-6"
        :param shell: Start process in a shell. Allows usage of shell constructions like pipes etc.
        :param enable_input: Whether or not allow writing to process' stdin
        :param log_file: Switch to enable redirection to generated by method log file
        :param output_file: Path to file as redirection of command output, interchangeably with log_file param.
        :return: List of running processes, RemoteProcess objects
        """
        pass

    def _prepare_auth_for_user_pwd(self, username: str, password: str, temp_creds_env: str = "") -> str:
        """
        Prepare authentication header for username and password.

        :param username: string with username
        :param password: string with password
        :param temp_creds_env: optional name of variable in environment in full format, e.g. $env:TEMP_CREDS_123456
        :return: header part of powershell command with decoded credentials
        """
        credentials = f"{username}:{password}"
        base64_bytes = base64.b64encode(credentials.encode("ascii"))
        if temp_creds_env:  # hide credentials in temporary environment variable if env is provided
            auth = temp_creds_env
            env = {
                temp_creds_env.split(":")[-1]: base64_bytes.decode("ascii")
            }  # get only variable name, without '$env:'
            self._manage_temporary_envs(env)  # hide credentials in temporary environment variables
        else:
            auth = base64_bytes.decode("ascii")

        return f' -Headers @{{ Authorization = "Basic {auth}"}}'

    def _hide_credentials(
        self, username: str, password: str, headers: dict[str, str]
    ) -> tuple[str, str, dict[str, str]]:
        """
        Hide credentials in temporary environment variables.

        :param username: Optional username
        :param password: Optional password
        :param headers: Optionals Headers
        :return: Tuple with authentication string, options and headers
        """
        os_name = self.get_os_name()
        auth = options = ""
        env, headers_with_env_prefix = {}, {}
        prefix = "$env:" if os_name == OSName.WINDOWS else "$"
        # create random hash as suffix for temporary environment variables
        random_hash = hashlib.sha256(_generate_random_string(8).encode()).hexdigest()[:6]
        # create temporary environment variables for hiding credentials there
        env_key, env_value = f"TEMP_KEY_{random_hash}", f"TEMP_VALUE_{random_hash}"
        if headers:
            for i, header in enumerate(headers.items()):
                key, value = header
                # assign original headers to temporary environment variables
                env[f"{env_key}_{i}"] = key
                env[f"{env_value}_{i}"] = value
                # replace original headers with values by temporary environment variables
                headers_with_env_prefix[f"{prefix}{env_key}_{i}"] = f"{prefix}{env_value}_{i}"

        if os_name == OSName.WINDOWS:
            if username and password:  # hide user-password into basic authentication header parameter
                auth = self._prepare_auth_for_user_pwd(username, password, f"{prefix}TEMP_CREDS_{random_hash}")
            elif headers:
                auth = _prepare_headers_with_env_powershell(headers_with_env_prefix)
                self._manage_temporary_envs(env)  # hide header variables in temporary environment variables
        else:
            if username and password:
                env = {env_key: username, env_value: password}
                options = f" -u {prefix}{env_key}:{prefix}{env_value} "
            elif headers:
                headers = headers_with_env_prefix
            self._manage_temporary_envs(env)  # hide variables in temporary environment variables in python way
        return auth, options, headers

    def download_file_from_url(
        self,
        url: str,
        destination_file: "PurePath",
        username: str | None = None,
        password: str | None = None,
        headers: dict[str, str] | None = None,
        hide_credentials: bool = True,
    ) -> None:
        """
        Download file from url.

        Note: For authentication use either credentials (username & password) or headers - do not combine them.

        :param url: URL of file
        :param destination_file: Path for destination of file
        :param username: Optional username
        :param password: Optional password
        :param headers: Optional headers
        :param hide_credentials: Flag to hide credentials in temporary environment variables
        :raises: UnavailableServerException, if server is not available
        :raises: TransferFileError, on failure
        """
        if headers and (username or password):
            raise AssertionError("Use either credentials or headers - do not combine them")

        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Downloading file from url: {url} into {destination_file}")

        os_name = self.get_os_name()
        auth = options = ""

        if hide_credentials:
            auth, options, headers = self._hide_credentials(username, password, headers)
        else:
            if username and password:
                if os_name == OSName.WINDOWS:
                    # add user-password into basic authentication header parameter
                    auth = self._prepare_auth_for_user_pwd(username, password)
                else:
                    options = f" -u {username}:{password} "

        if os_name == OSName.WINDOWS:
            result = download_file_windows(
                connection=self,
                url=url,
                destination_file=destination_file,
                auth=auth if auth else _prepare_headers_powershell(headers),
            )
        elif os_name == OSName.ESXI:
            result = download_file_esxi(
                connection=self,
                url=url,
                destination_file=destination_file,
                options=options,
                headers=headers,
            )
        else:
            result = download_file_unix(
                connection=self,
                url=url,
                destination_file=destination_file,
                options=options if options else _prepare_headers_curl(headers),
            )
            if any(error in result.stdout for error in ["curl: command not found", "Could not resolve host"]):
                result = download_file_unix_via_controller(
                    connection=self,
                    destination_file=destination_file,
                    options=options if options else _prepare_headers_curl(headers),
                    url=url,
                )

        if not result.return_code:
            return

        possible_errors = ["Failed to connect to", "The remote server returned an error"]

        if any(error in result.stdout for error in possible_errors):
            raise UnavailableServerException(f"Cannot communicate with {url}\n\n{result.stdout}")
        else:
            raise TransferFileError(f"Problem with downloading file from {url}\n\n{result.stdout}")


class PythonConnection(AsyncConnection, ABC):
    """
    Base class for Python Connection.

    It can
        - execute one command at a time,
        - start parallel processes,
        - use python libraries installed on machine.
    """

    @abstractmethod
    def modules(self):  # noqa:ANN201
        """
        Expose python module-space on machine.

        :return: Object which exposes python module installed on machine.
        """
        pass

    @property
    def path(self) -> Type[Path]:
        """
        Path represents a filesystem path.

        :return: Path class for Connection.
        """
        return Path

    def get_requirements_version(self) -> str | None:
        """
        Read requirements_version (Portable Python SHA) file from 'sys.executable' directory.

        :return: SHA if was found, None otherwise.
        """
        path_to_requirements_version = self.path(self.modules().sys.executable).parent / "requirements_version"
        if path_to_requirements_version.exists() is True:
            return path_to_requirements_version.read_text()

    @conditional_cache
    def get_os_type(self) -> OSType:
        """Get os type."""
        read_type = self.modules().os.name
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Detected OS type: {read_type}")
        if "nt" in read_type:
            return OSType.WINDOWS
        elif "posix" in read_type:
            return OSType.POSIX
        raise OsNotSupported("Client OS not supported")

    @conditional_cache
    def get_os_name(self) -> OSName:
        """Get os name."""
        read_system = self.modules().platform.system()
        for os in OSName:
            if os.value in read_system:
                return os
        raise OsNotSupported("Client OS not supported")

    @conditional_cache
    def get_os_bitness(self) -> OSBitness:
        """Get bitness of Host OS."""
        arch = self.modules().platform.machine()
        if arch == "aarch64":
            return OSBitness.OS_64BIT
        elif arch.endswith("64"):
            return OSBitness.OS_64BIT
        elif "32" in arch or "86" in arch:
            return OSBitness.OS_32BIT
        elif "armv7l" in arch or "arm" in arch:
            return OSBitness.OS_32BIT
        else:
            raise OsNotSupported(f"Cannot determine OS bitness of Host: {self._ip}.")

    @conditional_cache
    def get_cpu_architecture(self) -> CPUArchitecture:
        """Get CPU architecture."""
        arch = self.modules().platform.machine()
        if arch == "aarch64":
            return CPUArchitecture.ARM64
        elif arch.endswith("64"):
            return CPUArchitecture.X86_64
        elif "32" in arch or "86" in arch:
            return CPUArchitecture.X86
        elif "armv7l" in arch or "arm" in arch:
            return CPUArchitecture.ARM
        else:
            raise CPUArchitectureNotSupported(f"Cannot determine CPU Architecture of Host: {self._ip}.")

    def _manage_temporary_envs(self, env: dict[str, str | bytes]) -> None:
        """
        Add temporary environment variables to the python process.

        :param env: dictionary with environment variables and their values
        """
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Setting temporary environment variables: {env.keys()}")
        self.modules().os.environ.update(env)

    @staticmethod
    def _log_execution_results(
        command: str, completed_process: "ConnectionCompletedProcess", skip_logging: bool = False
    ) -> None:
        """
        Log command execution results.

        :param command: Command to execute
        :param completed_process: Completed Process from execution
        :param skip_logging: Skip logging of stdout/stderr if captured
        """
        logger.log(
            level=log_levels.MODULE_DEBUG,
            msg=f"Finished executing '{command}', rc={completed_process.return_code}",
        )
        if skip_logging:
            return

        stdout = completed_process.stdout
        if stdout:
            logger.log(level=log_levels.OUT, msg=f"stdout>>\n{stdout}")

        stderr = completed_process.stderr
        if stderr:
            logger.log(level=log_levels.OUT, msg=f"stderr>>\n{stderr}")

    @staticmethod
    def _handle_execution_outcome(
        completed_process: "CompletedProcess",
        expected_return_codes: Iterable | None = frozenset({0}),
        custom_exception: Type[CalledProcessError] | None = None,
        skip_logging: bool = False,
    ) -> "ConnectionCompletedProcess":
        """
        Pass command execution outcome or raise exception based on not expected RCs.

        :param completed_process: Completed Process from execution
        :param expected_return_codes: set of expected Return Codes from the command execution
        :param custom_exception: exception provided to command execution
        :param skip_logging: Skip logging of stdout/stderr if captured
        :return: ConnectionCompletedProcess
        :raises custom_exception or ConnectionCalledProcessError
        """
        if custom_exception and not expected_return_codes:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg=f"Return codes are ignored, passed exception: {custom_exception} will be not raised.",
            )

        new_line_pattern = b"(\r\n|\r)"
        decoded_stdout = decoded_stderr = ""

        if completed_process.stdout:
            completed_process.stdout = re.sub(new_line_pattern, b"\n", completed_process.stdout)
            decoded_stdout = completed_process.stdout.decode("utf-8", "backslashreplace")

        if completed_process.stderr:
            completed_process.stderr = re.sub(new_line_pattern, b"\n", completed_process.stderr)
            decoded_stderr = completed_process.stderr.decode("utf-8", "backslashreplace")

        mfd_completed_process = ConnectionCompletedProcess(
            args=completed_process.args,
            stdout=decoded_stdout,
            stderr=decoded_stderr,
            stdout_bytes=completed_process.stdout,
            stderr_bytes=completed_process.stderr,
            return_code=completed_process.returncode,
        )
        PythonConnection._log_execution_results(
            command=completed_process.args, completed_process=mfd_completed_process, skip_logging=skip_logging
        )

        if not expected_return_codes or completed_process.returncode in expected_return_codes:
            return mfd_completed_process
        else:
            if custom_exception:
                raise custom_exception(
                    returncode=completed_process.returncode,
                    cmd=completed_process.args,
                    output=decoded_stdout,
                    stderr=decoded_stderr,
                )
            raise ConnectionCalledProcessError(
                returncode=completed_process.returncode,
                cmd=completed_process.args,
                output=decoded_stdout,
                stderr=decoded_stderr,
            )

    def is_same_python_version(self) -> bool:
        """
        Check if the version of Python on the host is the same as the one used in this module.

        :return: True if the version of Python on the host is the same as the one used in this module.
        """
        return self.modules().sys.version_info[0:2] == sys.version_info[0:2]  # compare only major and minor version
