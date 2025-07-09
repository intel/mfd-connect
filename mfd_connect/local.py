# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for LocalConnection class."""

import logging
import re
import shlex
import typing
from importlib import import_module
from pathlib import Path
from subprocess import PIPE, DEVNULL, STDOUT, run, Popen, CalledProcessError, CompletedProcess
from typing import Iterable, Tuple, Type, Union, Optional, List, Dict

from mfd_common_libs import add_logging_level, log_levels
from mfd_typing.os_values import OSName, OSType

from .base import PythonConnection, ConnectionCompletedProcess
from .exceptions import OsNotSupported
from .process.local import LocalProcess, POSIXLocalProcess, WindowsLocalProcess

if typing.TYPE_CHECKING:
    from pydantic import BaseModel  # from pytest_mfd_config.models.topology import ConnectionModel

logger = logging.getLogger(__name__)
add_logging_level(level_name="MODULE_DEBUG", level_value=log_levels.MODULE_DEBUG)
add_logging_level(level_name="CMD", level_value=log_levels.CMD)
add_logging_level(level_name="OUT", level_value=log_levels.OUT)


class _DynamicModuleImporter:
    """
    Class responsible for exposing python modules space installed on machine.

    Used internally only.

    Usage example:
    >>> mod = _DynamicModuleImporter()
    >>> mod.os.listdir()
    List of the directories will be return.
    """

    def __getattr__(self, item: str):
        return import_module(item)

    def __getitem__(self, item: str):
        return getattr(self, item)


class LocalConnection(PythonConnection):
    """
    Implementation of PythonConnection type for local usage.

    Operations will be performed on local machine.

    Usage example:
    >>> conn = LocalConnection()
    >>> res = conn.execute_command("echo test", shell=True)
    test
    """

    _process_classes = {POSIXLocalProcess, WindowsLocalProcess}

    def __init__(  # noqa D107
        self,
        *args,
        model: "BaseModel | None" = None,
        default_timeout: int | None = None,
        cache_system_data: bool = True,
        **kwargs,
    ) -> None:
        """
        Initialize LocalConnection object.

        :param model: pydantic model of connection
        :param default_timeout: Timeout value for executing timeout for entire class.
        :param cache_system_data: Flag to cache system data like self._os_type, OS name, OS bitness and CPU architecture
        """
        super().__init__("127.0.0.1", model, default_timeout, cache_system_data)
        self.__use_sudo = False
        for process_cls in self._process_classes:
            if process_cls.os_type == self._os_type:
                # Assign proper LocalProcess subclass
                self._process_class = process_cls
                break
        else:
            raise OsNotSupported("There is no LocalProcess subclass for this type of OS.")

        self.log_connected_host_info()

    def __str__(self):
        return "local"

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

    def execute_command(  # noqa D102
        self,
        command: str,
        *,
        input_data: Optional[str] = None,
        cwd: str = None,
        timeout: int = None,
        env: Optional[Dict[str, str]] = None,
        stderr_to_stdout: bool = False,
        discard_stdout: bool = False,
        discard_stderr: bool = False,
        skip_logging: bool = False,
        expected_return_codes: Optional[Iterable] = frozenset({0}),
        shell: bool = False,
        custom_exception: Optional[Type[CalledProcessError]] = None,
    ) -> "ConnectionCompletedProcess":
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
        logger.log(level=log_levels.CMD, msg=f"Executing >{self._ip}> '{command}', cwd: {cwd}")

        powershell_called = self._is_powershell_called(command=command)
        if self._os_type == OSType.WINDOWS:
            if powershell_called:
                logger.log(
                    level=log_levels.MODULE_DEBUG,
                    msg="For more complicated queries Windows has issue with correct escaping special signs in "
                    "powershell, so forcing NON-SHELL mode.",
                )
                shell = False
            elif cwd:
                logger.log(
                    level=log_levels.MODULE_DEBUG,
                    msg="Windows doesn't support non-shell and cwd in terminal, so forcing SHELL mode.",
                )
                shell = True

        command = self._adjust_command(command)

        if not shell and not powershell_called:
            command = shlex.split(command, posix=self._os_type == OSType.POSIX)

        if self.get_os_name() == OSName.ESXI:
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

    @staticmethod
    def _is_powershell_called(command: str) -> bool:
        return True if "powershell" in command else False

    @staticmethod
    def _run_command(
        command: str,
        cwd: Optional[str],
        env: Optional[Dict],
        input_data: Optional[str],
        shell: bool,
        stderr: int,
        stdout: int,
        timeout: Optional[int],
    ) -> "CompletedProcess":
        completed_process: "CompletedProcess" = run(
            command,
            input=input_data,
            cwd=cwd,
            timeout=timeout,
            env=env,
            shell=shell,
            stdout=stdout,
            stderr=stderr,
            check=False,
        )
        return completed_process

    @staticmethod
    def _run_esxi_command(
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
        proc = Popen(
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

    def start_process(  # noqa D102
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
    ) -> "LocalProcess":
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
        if log_file or output_file:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg="Local connection doesn't support log_file or output_file.",
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

        if not shell:
            command = shlex.split(command, posix=self._os_type == OSType.POSIX)

        if enable_input:
            stdin = PIPE
        else:
            stdin = DEVNULL

        popen = Popen(
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

        return self._process_class(process=popen)

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
    ) -> List["LocalProcess"]:
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
        if log_file or output_file:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg="Local connection doesn't support log_file or output_file.",
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

        if not shell:
            command = shlex.split(command, posix=self._os_type == OSType.POSIX)

        if enable_input:
            stdin = PIPE
        else:
            stdin = DEVNULL

        separated_commands = self._get_commands(command)

        popen = Popen(
            separated_commands[0],
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

        popen_processes = [popen]

        for cmd in separated_commands[1:]:  # skipping first command because it's already running
            popen_processes.append(
                Popen(
                    cmd,
                    cwd=cwd,
                    env=env,
                    shell=shell,
                    stdin=popen_processes[-1].stdout,  # redirect last executed command's stdout to next command's stdin
                    stdout=stdout,
                    stderr=stderr,
                    encoding="utf-8",
                    errors="backslashreplace",
                )
            )

        return [self._process_class(process=popen_process) for popen_process in popen_processes]

    def _get_commands(self, commands: str) -> List[str]:
        """
        Get atomic commands from commands with pipes.

        :param commands: Commands with pipes
        :return: List of atomic commands
        """
        split_commands = re.split(r"(?<!\|)\|(?!\|)", commands)
        return [command.strip() for command in split_commands]

    def modules(self) -> _DynamicModuleImporter:  # noqa: D102
        return _DynamicModuleImporter()

    def restart_platform(self) -> None:
        """Reboot host."""
        raise NotImplementedError("Restart is not implemented in LocalConnection")

    def shutdown_platform(self) -> None:
        """Shutdown host."""
        raise NotImplementedError("Shutdown is not implemented in LocalConnection")

    def wait_for_host(self, timeout: int = 60) -> None:
        """
        Wait for host availability.

        :param timeout: Time to check until fail
        :raises TimeoutError: when timeout is expired
        """
        raise NotImplementedError("Wait for host is not implemented in LocalConnection")

    def disconnect(self) -> None:
        """Close connection with client. Not required for LocalConnection."""
        logger.log(level=log_levels.MODULE_DEBUG, msg="Disconnect is not required for Local connection.")

    @property
    def path(self) -> Type["Path"]:
        """
        Path represents a filesystem path.

        :return: Path class for Connection.
        """
        return Path

    def enable_sudo(self) -> None:
        """
        Enable sudo for command execution.

        It will work only with execute_command.

        :raises OsNotSupported: when os_type is different from posix
        """
        if self._os_type != OSType.POSIX:
            raise OsNotSupported(f"{self._os_type} is not supported for enabling sudo!")

        logger.log(level=log_levels.MODULE_DEBUG, msg="Enabled sudo for command execution.")
        self.__use_sudo = True

    def disable_sudo(self) -> None:
        """Disable sudo for command execution."""
        logger.log(level=log_levels.MODULE_DEBUG, msg="Disabled sudo for command execution.")
        self.__use_sudo = False

    def _adjust_command(self, command: str) -> str:
        """
        Adjust command.

        :param command: command to adjust
        :return: command
        """
        if self.__use_sudo:
            return f'sudo sh -c "{command}"' if "echo" in command else f"sudo {command}"
        return command
