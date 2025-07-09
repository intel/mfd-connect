# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""RPyC Connection implementation."""

import codecs
import logging
import shlex
import time
import typing
from warnings import warn
from pathlib import Path
from subprocess import PIPE, STDOUT, DEVNULL, CalledProcessError, CompletedProcess
from typing import Iterable, Optional, Dict, Any, Tuple, Callable, Type, Union, List

import rpyc
from funcy import retry
from mfd_common_libs import TimeoutCounter, add_logging_level, log_levels
from mfd_typing.os_values import OSName, OSType
from rpyc.core.service import ClassicService, ModuleNamespace

from mfd_connect.util.rpc_system_info_utils import DEFAULT_RPYC_6_0_0_RESPONDER_PORT
from mfd_connect import LocalConnection
from mfd_connect.base import PythonConnection, ConnectionCompletedProcess, Connection
from mfd_connect.exceptions import (
    ConnectionCalledProcessError,
    OsNotSupported,
    ModuleFrameworkDesignError,
    RPyCDeploymentException,
)
from .process.rpyc import RPyCProcess, WindowsRPyCProcess, PosixRPyCProcess, ESXiRPyCProcess, WindowsRPyCProcessByStart
from .util.decorators import clear_system_data_cache

if typing.TYPE_CHECKING:
    from io import TextIOWrapper
    from pydantic import BaseModel  # from pytest_mfd_config.models.topology import ConnectionModel
    from netaddr import IPAddress

logger = logging.getLogger(__name__)
add_logging_level(level_name="MODULE_DEBUG", level_value=log_levels.MODULE_DEBUG)
add_logging_level(level_name="CMD", level_value=log_levels.CMD)
add_logging_level(level_name="OUT", level_value=log_levels.OUT)


class RPyCConnection(PythonConnection):
    """RPyC Connection class."""

    DEFAULT_RPYC_6_0_0_RESPONDER_PORT = DEFAULT_RPYC_6_0_0_RESPONDER_PORT  # used for rpyc ver. 6+
    _system_name: Optional[str] = None  # Must be defined by subclasses
    _process_classes = {PosixRPyCProcess, WindowsRPyCProcess, ESXiRPyCProcess}

    def __init__(
        self,
        ip: "IPAddress | str",
        *,
        port: int | None = None,
        path_extension: str | None = None,
        connection_timeout: int = 360,
        default_timeout: int | None = None,
        retry_timeout: int | None = None,
        retry_time: int = 5,
        enable_bg_serving_thread: bool = True,
        model: "BaseModel | None" = None,
        enable_deploy: bool = False,
        deploy_username: str | None = None,
        deploy_password: str | None = None,
        share_url: str | None = None,
        share_username: str | None = None,
        share_password: str | None = None,
        cache_system_data: bool = True,
        ssl_keyfile: str | None = None,
        ssl_certfile: str | None = None,
        **kwargs,
    ) -> None:  # noqa: D200
        """
        Initialise RPyCConnection class.

        :param ip: Host identifier - IP address
        :param path_extension: PATH environment variable extension for calling commands.
        :param port: TCP port to use while connecting to host's responder.
        :param connection_timeout: Timeout value, if timeout last without response from server,
        client raises AsyncResultTimeout
        :param default_timeout: Timeout value for executing timeout for entire class.
        :param retry_timeout: Time for try of connection, in secs
        :param retry_time: Time between next try of connection, in secs
        :param enable_bg_serving_thread: Set to True if background serving thread must be activated, otherwise False
        :param model: pydantic model of connection
        :param enable_deploy: Decide whether to check SHA of remote PP and deploy responder if needed
        :param deploy_username: Username used for deployment of PP onto remote host
        :param deploy_password: Password used for deployment of PP onto remote host
        :param share_url: Location of PP tarball on fileserver
        :param share_username: Username used for downloading PP tarball from fileserver
        :param share_password: Password used for downloading PP tarball from fileserver
        :param cache_system_data: Flag to cache system data like self._os_type, OS name, OS bitness and CPU architecture
        :param ssl_keyfile: Path to SSL key file.
        :param ssl_certfile: Path to SSL certificate file.
        """
        super().__init__(ip, model, default_timeout, cache_system_data)
        self.path_extension = path_extension

        self._port = port or RPyCConnection.DEFAULT_RPYC_6_0_0_RESPONDER_PORT
        self._connection = None
        self._connection_timeout = connection_timeout
        self._enable_bg_serving_thread = enable_bg_serving_thread
        self.share_url: str = share_url
        self.enable_deploy: bool = enable_deploy
        self.deploy_username: str = deploy_username
        self.deploy_password: str = deploy_password
        self.share_username: str = share_username
        self.share_password: str = share_password
        self._ssl_keyfile: str | None = ssl_keyfile
        self._ssl_certfile: str | None = ssl_certfile
        self._establish_connection(retry_timeout=retry_timeout, retry_time=retry_time)

    def _establish_connection(self, *, retry_timeout: Optional[int], retry_time: int) -> None:
        """
        Establish a connection to the machine.

        If enable deploy is True, try to connect via deployment port,
        if it is not working, start deployment and establish connection again.

        :param retry_timeout: Time for try of connection, in secs
        :param retry_time: Time between next try of connection, in secs
        :raises RPyCDeploymentException, rpyc exception: on failure
        """
        try:
            self.__establish_connection(retry_timeout=retry_timeout, retry_time=retry_time)
        except Exception as e:
            if not isinstance(e, RPyCDeploymentException):
                logger.log(level=log_levels.MODULE_DEBUG, msg=f"Found exception while establishing connection\n{e}")
            if not self.enable_deploy:
                raise e
            self._port = self.DEFAULT_RPYC_6_0_0_RESPONDER_PORT + 1

            try:
                logger.log(level=log_levels.MODULE_DEBUG, msg=f"Trying to connect on deployed port {self._port}.")

                self.__establish_connection(retry_timeout=retry_timeout, retry_time=retry_time)
                return
            except Exception as e:
                if not isinstance(e, RPyCDeploymentException):
                    logger.log(level=log_levels.MODULE_DEBUG, msg=f"Found exception while establishing connection\n{e}")
            from .util.deployment import SetupPythonForResponder

            SetupPythonForResponder(
                ip=str(self.ip),
                username=self.deploy_username,
                password=self.deploy_password,
                artifactory_url=self.share_url,
                artifactory_username=self.share_username,
                artifactory_password=self.share_password,
            )
            self.__establish_connection(retry_timeout=retry_timeout, retry_time=retry_time)

    def __establish_connection(self, *, retry_timeout: Optional[int], retry_time: int) -> None:
        # flow for tries of connecting
        if retry_timeout:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg=f"Trying connect to with host with {retry_timeout} seconds of timeout"
                f" and {retry_time} seconds of wait for next try",
            )
            self.wait_for_host(timeout=retry_timeout, retry_time=retry_time)

        self._set_process_class()
        self._set_bg_serving_thread()

        self.log_connected_host_info()

    def __str__(self):
        return "rpyc"

    @clear_system_data_cache
    def _reconnect(self) -> None:
        """
        Reconnect to the host.

        Automatically establishes the connection on the first call.
        Re-establishes the connection after a drop.

        :raises RPyCDeploymentException: if remote sha is different from local, when enable_deploy is True
        """
        self._connection = self._create_connection()
        if self.enable_deploy:
            self.check_sha_correctness()
        if hasattr(self, "_background_serving_thread") and not self._background_serving_thread._active:
            self._background_serving_thread = rpyc.BgServingThread(self._connection)
            time.sleep(0.1)

    @property
    def remote(self) -> rpyc.Connection:  # noqa D403
        """
        RPyC connection to the represented host.

        Automatically establishes the connection on the first call.
        Re-establishes the connection after a drop.

        :raises RPyCDeploymentException: if remote sha is different from local, when enable_deploy is True
        """
        if self._connection is not None and self._connection.closed:  # Connection existed, but has been dropped
            logger.log(level=log_levels.MODULE_DEBUG, msg="Connection lost, reconnecting")

        if self._connection is None or self._connection.closed:  # Connection is dead
            self._reconnect()
        return self._connection

    @Connection.default_timeout.setter
    def default_timeout(self, timeout: int) -> None:  # noqa D401
        """Set Default timeout value."""
        if timeout > self._connection_timeout:
            warn(
                "Default timeout will have no effect as it's "
                f"bigger than connection timeout {self._connection_timeout}.",
                stacklevel=2,
            )
        else:
            Connection.default_timeout.fset(self, timeout)  # call parent property setter

    def check_sha_correctness(self) -> None:
        """
        Check if local and remote python are the same.

        If not, disconnect and raise exception.

        :raises RPyCDeploymentException: if sha are different
        """
        sha = self.get_requirements_version()  # remote
        local_connection = LocalConnection()  # local
        local_sha = local_connection.get_requirements_version()
        if sha != local_sha:
            logger.log(level=log_levels.MODULE_DEBUG, msg="Remote Portable Python SHA is different than local one.")
            self.disconnect()
            raise RPyCDeploymentException("Remote Portable Python SHA is different than local one.")

    def modules(self) -> "ModuleNamespace":
        """
        Expose python module-space on machine.

        :return: Object which exposes python module installed on machine.
        """
        return self.remote.modules

    @retry(5, errors=OSError)
    def _create_connection(self) -> rpyc.Connection:
        """
        Create RPyC connection to the represented host.

        :return: RPyC connection object.
        """
        if self._ssl_keyfile and self._ssl_certfile:
            return rpyc.ssl_connect(
                str(self._ip),
                port=self._port,
                service=ClassicService,
                keepalive=True,
                config={"sync_request_timeout": self._connection_timeout},
                keyfile=self._ssl_keyfile,
                certfile=self._ssl_certfile,
            )
        return rpyc.connect(
            str(self._ip),
            port=self._port,
            service=ClassicService,
            keepalive=True,
            config={"sync_request_timeout": self._connection_timeout},
        )

    def execute_command(
        self,
        command: str,
        *,
        input_data: str | None = None,
        cwd: str | None = None,
        timeout: int | None = None,
        env: dict[str, str] | None = None,
        stderr_to_stdout: bool = False,
        discard_stdout: bool = False,
        discard_stderr: bool = False,
        skip_logging: bool = False,
        expected_return_codes: Iterable | None = frozenset({0}),
        shell: bool = False,
        custom_exception: Type[CalledProcessError] | None = None,
    ) -> "ConnectionCompletedProcess":
        """
        Run program and wait for it's completion.

        :param command: Command to execute, with all necessary arguments
        :param input_data: Data to pass to program on the standard input
        :param cwd: Directory to start program execution in
        :param timeout: Program execution timeout, in seconds
        :param env: Environment to execute the program in,
            it will extend and/or override the current environment variables, e.g. "param" is in the env,
            and the same "param" is in the current environment, the value from the env will be used.
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
        timeout = self.default_timeout if timeout is None else timeout
        super().execute_command(
            command,
            input_data=input_data,
            cwd=cwd,
            timeout=timeout,
            env=env,
            stderr_to_stdout=stderr_to_stdout,
            discard_stdout=discard_stdout,
            discard_stderr=discard_stderr,
            skip_logging=skip_logging,
            expected_return_codes=expected_return_codes,
            shell=shell,
        )

        stdout, stderr = self._resolve_process_output_arguments(
            stderr_to_stdout=stderr_to_stdout, discard_stdout=discard_stdout, discard_stderr=discard_stderr
        )
        timeout_string = " " if timeout is None else f" with timeout {timeout} seconds"
        logger.log(level=log_levels.CMD, msg=f"Executing >{self._ip}> '{command}', cwd: {cwd}{timeout_string}")

        powershell_called = bool("powershell" in command)
        if self._os_type == OSType.WINDOWS:
            if powershell_called:
                # For more complicated queries Windows has issue with correct escaping special signs in powershell,
                # so forcing NON-SHELL mode
                shell = False
            elif cwd:
                logger.log(
                    level=log_levels.MODULE_DEBUG,
                    msg="Windows doesn't support non-shell and cwd in terminal, so forcing SHELL mode.",
                )
                shell = True

        if not shell and not powershell_called:
            command = shlex.split(command, posix=self._os_type == OSType.POSIX)

        env = self._handle_path_extension(env)
        env = self._handle_env_extension(env)

        input_data = codecs.encode(input_data) if input_data is not None else input_data

        if self.get_os_name() == OSName.ESXI and not self.is_same_python_version():
            completed_process = self._run_esxi_command(command, cwd, env, input_data, shell, stderr, stdout, timeout)
        else:
            completed_process = self._run_command(command, cwd, env, input_data, shell, stderr, stdout, timeout)

        conn_completed_proc = self._handle_execution_outcome(
            completed_process=completed_process,
            expected_return_codes=expected_return_codes,
            custom_exception=custom_exception,
            skip_logging=skip_logging,
        )
        return conn_completed_proc

    def execute_with_timeout(
        self,
        command: str,
        *,
        timeout: int,
        cwd: str | None = None,
        stderr_to_stdout: bool = False,
        discard_stdout: bool = False,
        discard_stderr: bool = False,
        skip_logging: bool = False,
        shell: bool = False,
        expected_return_codes: Iterable | None = frozenset({0}),
        custom_exception: Type[CalledProcessError] | None = None,
    ) -> "ConnectionCompletedProcess":
        """
        Execute command with timeout independent of connection timeout.

        :param command: Command to execute, with all necessary arguments
        :param timeout: Program execution timeout, in seconds
        :param cwd: Directory to start program execution in
        :param stderr_to_stdout: Redirect stderr to stdout, ignored if discard_stderr is set to True
        :param discard_stdout: Don't capture stdout stream
        :param discard_stderr: Don't capture stderr stream
        :param skip_logging: Skip logging of stdout/stderr if captured
        :param shell: Start process in a shell. Allows usage of shell constructions like pipes etc.
        :param expected_return_codes: Return codes to be considered acceptable.
                                      If None - any return code is considered acceptable
        :param custom_exception: Enable us to raise our exception if program exits with an unexpected return code.
        custom_exception must inherit from CalledProcessError to use its fields like returncode, cmd, output, stderr

        :return: ConnectionCompletedProcess object
        :raises TimeoutExpired: if program doesn't conclude before timeout is reached
        :raises ConnectionCalledProcessError: if program exits with an unexpected return code
        """
        logger.log(level=log_levels.CMD, msg=f"Executing >{self._ip}> '{command}', cwd: {cwd}, timeout: {timeout}")
        process = self.start_process(
            command=command,
            cwd=cwd,
            stderr_to_stdout=stderr_to_stdout,
            discard_stdout=discard_stdout,
            discard_stderr=discard_stderr,
            shell=shell,
        )
        counter = TimeoutCounter(timeout)

        while not counter:
            if not process.running:
                break
        else:
            process.kill()
            raise TimeoutError(f"{command} encountered a timeout limit")

        conn_completed_process = self._handle_execution_outcome(
            CompletedProcess(
                args=command,
                stdout=process.stdout_text.encode(encoding="utf-8", errors="backslashreplace"),
                stderr=process.stderr_text.encode(encoding="utf-8", errors="backslashreplace"),
                returncode=process.return_code,
            ),
            expected_return_codes=expected_return_codes,
            custom_exception=custom_exception,
        )
        self._log_execution_results(
            command=command, completed_process=conn_completed_process, skip_logging=skip_logging
        )
        return conn_completed_process

    def _run_command(
        self,
        command: str,
        cwd: Optional[str],
        env: Optional[Dict],
        input_data: Optional[str],
        shell: bool,
        stderr: int,
        stdout: int,
        timeout: Optional[int],
    ) -> "CompletedProcess":
        completed_process: "CompletedProcess" = self.modules().subprocess.run(
            command,
            input=input_data,
            cwd=cwd,
            timeout=timeout,
            env=env,
            shell=shell,
            stdout=stdout,
            stderr=stderr,
            check=False,
            stdin=PIPE if not input_data else None,
        )
        return completed_process

    def _run_esxi_command(
        self,
        command: str,
        cwd: Optional[str],
        env: Optional[Dict],
        input_data: Optional[str],
        shell: bool,
        stderr: int,
        stdout: int,
        timeout: Optional[int],
    ) -> "CompletedProcess":
        if input_data is not None:
            logger.log(level=log_levels.MODULE_DEBUG, msg="Input data is not supported on ESXi")
        proc = self.modules().subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            shell=shell,
            stdout=stdout,
            stderr=stderr,
        )
        output, errors = proc.communicate(timeout=timeout)
        output = output if output else b""
        errors = errors if errors else b""
        rc = int(proc.returncode)
        return CompletedProcess(args=command, stdout=output, stderr=errors, returncode=rc)

    def send_command_and_disconnect_platform(self, command: str) -> None:
        """
        Send to host command and disconnect rpyc.

        Closing rpyc connection
        If send command failed, return code != 0 and raise ConnectionCalledProcessError
        Handle EOFError, which has been raised when dropped connection
        If command send correct, sleep 'sleep_time' for start rebooting and end responder

        :param command: Command to send
        """
        sleep_time = 10
        if hasattr(self, "_background_serving_thread"):
            self._background_serving_thread.stop()
        try:
            self.execute_command(command)
        except EOFError:  # EOFError: [Errno 104] Connection reset by peer (dropped connection)
            logger.log(level=log_levels.MODULE_DEBUG, msg="Dropped connection via RPyC, expected")
        finally:
            self._connection.close()
        time.sleep(sleep_time)

    def execute_powershell(  # noqa D102
        self,
        command: str,
        *,
        input_data: Optional[str] = None,
        cwd: Optional[str] = None,
        timeout: Optional[int] = None,
        env: Optional[Dict[str, str]] = None,
        stderr_to_stdout: bool = False,
        discard_stdout: bool = False,
        discard_stderr: bool = False,
        skip_logging: bool = False,
        expected_return_codes: Optional[Iterable] = frozenset({0}),
        shell: bool = False,
        custom_exception: Optional[Type[CalledProcessError]] = None,
    ) -> "ConnectionCompletedProcess":
        extend_buffer_size_command = (
            "$host.UI.RawUI.BufferSize = new-object System.Management.Automation.Host.Size(512,3000);"
        )
        if '"' in command:
            command = command.replace('"', '\\"')
        command = f'powershell.exe -OutPutFormat Text -nologo -noninteractive "{extend_buffer_size_command}{command}"'
        cwd = self.modules().os.path.normpath(path=cwd) if cwd else cwd

        return self.execute_command(
            command=command,
            input_data=input_data,
            cwd=cwd,
            timeout=timeout,
            env=env,
            discard_stdout=discard_stdout,
            discard_stderr=discard_stderr,
            skip_logging=skip_logging,
            stderr_to_stdout=stderr_to_stdout,
            expected_return_codes=expected_return_codes,
            shell=shell,
            custom_exception=custom_exception,
        )

    def restart_platform(self) -> None:
        """
        Reboot host.

        Internal dict of reboot platform commands
        """
        restart_commands = {
            OSType.WINDOWS: "shutdown /r /f -t 0",
            OSType.POSIX: "shutdown -r now",
            OSName.ESXI: "reboot -f -n",
        }
        try:
            command = restart_commands[self.get_os_name()]
        except KeyError:
            command = restart_commands[self.get_os_type()]
        self.send_command_and_disconnect_platform(command)

    def shutdown_platform(self) -> None:
        """
        Shutdown host.

        Internal dict of shutdown platform commands
        """
        shutdown_commands = {
            OSType.WINDOWS: "shutdown /s /f -t 0",
            OSType.POSIX: "shutdown -h now",
            OSName.ESXI: "poweroff -f -n",
        }
        try:
            command = shutdown_commands[self.get_os_name()]
        except KeyError:
            command = shutdown_commands[self.get_os_type()]
        self.send_command_and_disconnect_platform(command)

    def wait_for_host(self, *, timeout: int = 60, retry_time: int = 5) -> None:
        """
        Wait for host availability.

        Trying connect via rpyc,

        :param timeout: Time to check until fail
        :param retry_time: Time for next check
        :raises TimeoutError: when timeout is expired
        """
        last_exception = None
        timeout_counter = TimeoutCounter(timeout)
        while not timeout_counter:
            try:
                logger.log(level=log_levels.MODULE_DEBUG, msg="Reconnecting...")
                self._connection = self._create_connection()
                if self._connection:
                    logger.log(level=log_levels.MODULE_DEBUG, msg="Connected via RPyC")
                    if self._enable_bg_serving_thread:
                        self._background_serving_thread = rpyc.BgServingThread(self.remote)
                        time.sleep(0.1)
                    return
            except OSError as e:
                last_exception = e
                logger.log(
                    level=log_levels.MODULE_DEBUG,
                    msg=f"Connection does not established, waiting {retry_time} seconds and trying again",
                )
                time.sleep(retry_time)
        else:
            raise TimeoutError(f"Host does not wake up in {timeout} seconds") from last_exception

    def start_process_by_start_tool(
        self,
        command: str,
        *,
        cwd: str = None,
        discard_stdout: bool = False,
        cpu_affinity: Optional[Union[int, List[int], str]] = None,
        output_file: Optional[str] = None,
        numa_node: Optional[int] = None,
        **kwargs,  # noqa
    ) -> "WindowsRPyCProcessByStart":
        """
        Start process using start command on Windows.

        :param command: Command to execute, with all necessary arguments
        :param cwd: Directory to start program execution in
        :param discard_stdout: Don't capture stdout stream
        :param cpu_affinity: Processor numbers the process will run on in a format chosen by the user.
                             Acceptable formats are: cpu=1, cpu=[1, 2, 3, 6], cpu="1, 4, 5", cpu="1-7", cpu="0, 2-6"
        :param output_file: Path to file as redirection of command output, interchangeably with log_file param.
        :param numa_node: Specifies the preferred Non-Uniform Memory Architecture (NUMA) node as a decimal integer.
        :return: Running process, WindowsRPyCProcessByStart object
        """
        if self._os_type != OSType.WINDOWS:
            raise ConnectionCalledProcessError(returncode=-1, cmd=command, stderr="API is available for Windows only.")
        stdout, stderr = self._resolve_process_output_arguments(
            stderr_to_stdout=True, discard_stdout=discard_stdout, discard_stderr=False
        )
        logger.log(level=log_levels.CMD, msg=f"Starting process >{self._ip}> '{command}', cwd: {cwd}")
        log_path = self._prepare_log_file(command, not discard_stdout, output_file)
        command_list = ["start", "/WAIT", "/B"]
        if cwd is not None:
            command_list.append(f"/D {cwd}")
        if numa_node is not None:
            command_list.append(f"/NODE {numa_node}")
        if cpu_affinity is not None:
            cpus = self._create_affinity_mask(cpu_affinity)
            command_list.append(f"/AFFINITY {cpus}")
        command_list.append(command)
        if discard_stdout is False:
            command_list.append(f"> {log_path} 2>&1")
        command = " ".join(command_list)
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Command to start: '{command}'")

        popen = self.modules().subprocess.Popen(
            command,
            cwd=cwd,
            shell=True,
            stdin=DEVNULL,
            stdout=stdout,
            stderr=stderr,
            encoding="utf-8",
            errors="backslashreplace",
        )
        return WindowsRPyCProcessByStart(owner=self, process=popen, log_path=log_path, log_file_stream=None)

    def start_process(
        self,
        command: str,
        *,
        cwd: str | None = None,
        env: dict | None = None,
        stderr_to_stdout: bool = False,
        discard_stdout: bool = False,
        discard_stderr: bool = False,
        cpu_affinity: int | list[int] | str | None = None,
        shell: bool = False,
        enable_input: bool = False,
        log_file: bool = False,
        output_file: str | None = None,
    ) -> "RPyCProcess":
        """
        Start process.

        :param command: Command to execute, with all necessary arguments
        :param cwd: Directory to start program execution in
        :param env: Environment to execute the program in,
            it will extend and/or override the current environment variables, e.g. "param" is in the env,
            and the same "param" is in the current environment, the value from the env will be used.
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
        super().start_process(
            command,
            cwd=cwd,
            env=env,
            stderr_to_stdout=stderr_to_stdout,
            discard_stdout=discard_stdout,
            discard_stderr=discard_stderr,
            shell=shell,
            enable_input=enable_input,
        )
        stdout, stderr = self._resolve_process_output_arguments(
            stderr_to_stdout=stderr_to_stdout, discard_stdout=discard_stdout, discard_stderr=discard_stderr
        )
        logger.log(level=log_levels.CMD, msg=f"Starting process >{self._ip}> '{command}', cwd: {cwd}")

        if cwd:
            if self._os_type == OSType.WINDOWS:
                logger.log(
                    level=log_levels.MODULE_DEBUG,
                    msg="Windows doesn't support non-shell and cwd, so forcing SHELL mode.",
                )
                shell = True

        if cpu_affinity is not None:
            cpus = self._create_affinity_mask(cpu_affinity)
            if self._os_type == OSType.POSIX:
                command = f"taskset {hex(cpus)} {command}"

        log_path = self._prepare_log_file(command, log_file, output_file)
        if log_path is not None:
            log_file = True
        if not shell:
            command = shlex.split(command, posix=self._os_type == OSType.POSIX)

        env = self._handle_path_extension(env)
        env = self._handle_env_extension(env)

        if enable_input:
            stdin = PIPE
        else:
            stdin = DEVNULL

        log_file_stream, stderr, stdout = self._prepare_log_file_stream(log_file, log_path, stdout, stderr)

        popen = self.modules().subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            shell=shell,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            encoding="utf-8",
            errors="backslashreplace",
        )

        if cpu_affinity is not None and self._os_type == OSType.WINDOWS:
            self._apply_cpu_affinity_win(pid=popen.pid, affinity_mask=cpus)

        return self._process_class(owner=self, process=popen, log_path=log_path, log_file_stream=log_file_stream)

    def start_processes(  # noqa D102
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
    ) -> List["RPyCProcess"]:
        raise NotImplementedError("start_processes not yet implemented for rpyc connection.")

    def _prepare_log_file_stream(
        self, log_file: bool, log_path: Path, stdout: int, stderr: int
    ) -> Tuple[Optional["TextIOWrapper"], Union[int, "TextIOWrapper"], Union[int, "TextIOWrapper"]]:
        """
        Prepare stream for log file.

        :param log_file: State if we will use log file.
        :param log_path: Path for log file
        :param stdout: Stdout setting for Popen
        :param stderr: Stderr setting for Popen
        :return Opened filestream if required, configured stderr and stdout
        """
        log_file_stream = None
        if log_file is True:  # redirect output to log_path (change stdout and stderr to log_file_stream)
            logger.log(level=log_levels.CMD, msg=f"Using {log_path} log file")
            log_file_stream = stdout = stderr = log_path.open(mode="r+")
        return log_file_stream, stderr, stdout

    @staticmethod
    def _resolve_process_output_arguments(
        *, stderr_to_stdout: bool, discard_stdout: bool, discard_stderr: bool
    ) -> Tuple[int, int]:
        """
        Translate output-related arguments of execute_command and start_process into subprocess-friendly ones.

        Translates stderr_to_stdout, discard_stdout, discard_stderr values into stdout and stderr arguments for
        subprocess.run() and subprocess.Popen(), which can be one of PIPE, STDOUT, and DEVNULL

        :return: stdout, stderr values for run() or Popen()
        """
        if discard_stdout:
            stdout = DEVNULL
        else:
            stdout = PIPE

        if discard_stderr:
            stderr = DEVNULL
        else:
            if stderr_to_stdout:
                stderr = STDOUT
            else:
                stderr = PIPE

        return stdout, stderr

    def _handle_path_extension(self, env: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Extend PATH in the environment if self.path_extension is defined.

        :param env: Environment dictionary
        :return: Environment, in which PATH is extended, if necessary
        """
        if self.path_extension:
            env = env or self.modules().os.environ.copy()
            current_path = env.get("PATH")
            if current_path:
                path_sep = self.modules().os.pathsep
                new_path = path_sep.join((current_path, self.path_extension))
            else:
                new_path = self.path_extension
            env["PATH"] = new_path
        return env

    def _handle_env_extension(self, _env: dict[str, Any] | None) -> dict[str, Any] | None:
        """
        Extend/override the environment if env parameter is defined.

        :param _env: Environment dictionary
        :return: Environment, in which custom env is extended, if necessary
        """
        if _env is not None:
            env = self.modules().os.environ.copy()
            return dict(env, **_env)
        return _env

    def teleport_function(self, func: Callable) -> Callable:
        """
        Teleport function onto the remote machine.

        When the teleported function is run - it's code is executed on the remote machine.
        To avoid problems with external dependencies - put all the import statements inside the teleported function.

        For more information visit
        http://rpyc.readthedocs.io/en/latest/api/utils_classic.html#rpyc.utils.classic.teleport_function

        :param func: Function to teleport.
        :return: Teleported function.
        """
        return rpyc.classic.teleport_function(self.remote, func)

    @property
    def path(self) -> Type["Path"]:
        """
        Path represents a filesystem path.

        :return: Path class for Connection.
        """
        return self.modules().pathlib.Path

    def disconnect(self) -> None:
        """Close connection with host."""
        if self._connection:
            try:
                logger.log(level=log_levels.MODULE_DEBUG, msg=f"Closing connection with {self._ip}")
                if hasattr(self, "_background_serving_thread"):
                    self._background_serving_thread.stop()
                self._connection.close()
            except Exception as e:
                raise ModuleFrameworkDesignError(f"Exception occurred while closing connection: {e}") from e

    def _set_process_class(self) -> None:
        _os_name = self.get_os_name()
        for process_cls in self._process_classes:
            if process_cls._os_type == self._os_type:
                # Assign proper RPyC subclass
                if process_cls._os_names is not None and _os_name not in process_cls._os_names:
                    continue
                self._process_class = process_cls
                break

        else:
            raise OsNotSupported("There is no RPyCProcess subclass for this type of OS.")

    def _set_bg_serving_thread(self) -> None:
        if self._enable_bg_serving_thread:
            self._background_serving_thread = rpyc.BgServingThread(self.remote)
            time.sleep(0.1)
