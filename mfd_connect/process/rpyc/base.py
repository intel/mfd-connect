# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for RPyC-specific RPyCProcess implementation."""

import itertools
import typing
from abc import abstractmethod
from contextlib import suppress
from signal import Signals, SIGTERM
from threading import Lock
from time import sleep
from typing import IO, Optional, Iterator, Callable, Type, ClassVar


from mfd_common_libs import TimeoutCounter, log_levels
from mfd_typing.os_values import OSType, OSName

from mfd_connect.exceptions import (
    RemoteProcessTimeoutExpired,
    RemoteProcessStreamNotAvailable,
    RemoteProcessInvalidState,
)
from mfd_connect.util import BatchQueue
from ..base import RemoteProcess


if typing.TYPE_CHECKING:
    from pathlib import Path
    from io import TextIOBase
    from psutil import Process
    from ... import RPyCConnection
    from subprocess import Popen

import logging

logger = logging.getLogger(__name__)


class RPyCProcess(RemoteProcess):
    """
    RPyC-specific RPyCProcess implementation.

    This class is a wrapper around subprocess.Popen object, obtained through the Connection connection.
    """

    POOL_INTERVAL = 0.1
    """Interval for polling operations."""
    _os_type: ClassVar[OSType] = None
    _os_names: ClassVar[typing.List[OSName]] = None

    def __init__(
        self,
        *,
        owner: "RPyCConnection",
        process: "Popen",
        log_path: Optional["Path"],
        log_file_stream: Optional["TextIOBase"],
    ) -> None:  # noqa D205
        """
        Initialize RPyCProcess.

        :param owner: Owner host of the process.
        :param process: Process' Popen object.
        :param log_path: Path to log file.
        :param log_file_stream: Stream for log file.
        """
        super().__init__()
        self._owner = owner
        self._process = process
        self.log_path = log_path
        self.log_file_stream = log_file_stream

        self._cached_remote_get_process_io_queue = None
        self._remote_get_process_io_queue_cache_lock = Lock()

        self._cached_stdout_queue = None
        self._stdout_queue_cache_lock = Lock()

        self._cached_stdout_iter = None
        self._stdout_iter_cache_lock = Lock()

        self._cached_stderr_queue = None
        self._stderr_queue_cache_lock = Lock()

        self._cached_stderr_iter = None
        self._stderr_iter_cache_lock = Lock()

    @staticmethod
    def _get_process_io_queue(process_io: IO, bq: Type[BatchQueue]) -> BatchQueue:
        """
        Wrap process' IO stream in a line-by-line queue.

        Unlike IO stream - resulting queue can be used to peek if new output lines are available.
        This gives the ability to periodically poll the queue for new results, not blocking the RPyC connection.

        This method is teleported to the remote machine before usage, resulting the queue to be created on the
        remote side of the connection as well.

        :param bq: BatchQueue class
        :param process_io: IO object to wrap around (stdout or stderr).
        :return: Queue wrapped around stdout.readline() call.
        """
        import threading

        q = bq()

        def _watcher() -> None:
            try:
                with process_io:
                    for line in process_io:
                        q.put(line)
            except Exception:
                q.put("<internal>: Error occurred during io processing. Check responder log for details.")
                raise
            finally:
                q.put(None)

        stdout_watcher = threading.Thread(target=_watcher, daemon=True)
        stdout_watcher.start()

        return q

    @property
    def _remote_get_process_io_queue(self) -> Callable:
        """Teleported _get_process_io_queue method."""
        with self._remote_get_process_io_queue_cache_lock:
            if self._cached_remote_get_process_io_queue is None:
                self._cached_remote_get_process_io_queue = self._owner.teleport_function(self._get_process_io_queue)
        return self._cached_remote_get_process_io_queue

    @property
    def _stdout_queue(self) -> BatchQueue:
        """Stdout line-by-line queue."""
        with self._stdout_queue_cache_lock:
            if self._cached_stdout_queue is None:
                self._cached_stdout_queue = self._remote_get_process_io_queue(self.stdout_stream, BatchQueue)
        return self._cached_stdout_queue

    @property
    def _stderr_queue(self) -> BatchQueue:
        """Stderr line-by-line queue."""
        with self._stderr_queue_cache_lock:
            if self._cached_stderr_queue is None:
                self._cached_stderr_queue = self._remote_get_process_io_queue(self.stderr_stream, BatchQueue)
        return self._cached_stderr_queue

    @property
    def pid(self) -> int:
        """
        Field for Process ID.

        :return: PID
        """
        return self._process.pid

    def _iterate_non_blocking_queue(self, q: BatchQueue) -> Iterator[str]:
        """
        Get polling iterator over a non-blocking queue.

        Used to get a line-by-line iterator for process' IO streams which doesn't block the connection.
        :param q: BatchQueue to iterate over.
        :return: Resulting iterator.
        """
        while True:
            lines = q.get_many()

            if len(lines) == 0:
                # No lines readily available
                sleep(self.POOL_INTERVAL)
                continue

            for line in lines:
                if line is None:
                    # None is the last item in a queue, terminating iterator
                    return
                yield line

    @property
    def running(self) -> bool:  # noqa D102
        _ = super().running  # noqa F841
        return self._process.poll() is None

    @property
    def stdin_stream(self) -> IO:  # noqa D102
        _ = super().stdin_stream  # noqa F841
        stdin = self._process.stdin
        if stdin is None:
            raise RemoteProcessStreamNotAvailable("stdin stream is not available")
        return stdin

    @property
    def stdout_stream(self) -> IO:  # noqa D102
        _ = super().stdout_stream  # noqa F841
        stdout = self._process.stdout
        if stdout is None:
            raise RemoteProcessStreamNotAvailable("stdout stream is not available")
        return self._process.stdout

    @property
    def stderr_stream(self) -> IO:  # noqa D102
        _ = super().stderr_stream  # noqa F841
        stderr = self._process.stderr
        if stderr is None:
            raise RemoteProcessStreamNotAvailable("stderr stream is not available")
        return self._process.stderr

    def get_stdout_iter(self) -> Iterator[str]:  # noqa D102
        with self._stdout_iter_cache_lock:
            super().get_stdout_iter()
            if self._cached_stdout_iter is None:
                self._cached_stdout_iter = self._iterate_non_blocking_queue(self._stdout_queue)

            self._cached_stdout_iter, result = itertools.tee(self._cached_stdout_iter)
        return result

    def get_stderr_iter(self) -> Iterator[str]:  # noqa D102
        with self._stderr_iter_cache_lock:
            super().get_stderr_iter()
            if self._cached_stderr_iter is None:
                self._cached_stderr_iter = self._iterate_non_blocking_queue(self._stderr_queue)

            self._cached_stderr_iter, result = itertools.tee(self._cached_stderr_iter)
        return result

    @property
    def stdout_text(self) -> str:  # noqa D102
        _ = super().stdout_text  # noqa F841
        return "".join(self.get_stdout_iter())

    @property
    def stderr_text(self) -> str:  # noqa D102
        _ = super().stderr_text  # noqa F841
        return "".join(self.get_stderr_iter())

    @property
    def return_code(self) -> Optional[int]:  # noqa D102
        _ = super().return_code  # noqa F841
        return self._process.returncode

    def wait(self, timeout: int = 60) -> int:  # noqa D102
        super().wait(timeout)
        self._start_pipe_drain()

        timeout = TimeoutCounter(timeout)
        while not timeout:
            if not self.running:
                return self.return_code
            sleep(self.POOL_INTERVAL)
        else:
            raise RemoteProcessTimeoutExpired()

    def kill(self, wait: Optional[int] = 60, with_signal: typing.Union[Signals, str, int] = SIGTERM) -> None:  # noqa D102
        super().kill()
        self._start_pipe_drain()
        self._get_and_kill_process(with_signal=with_signal)

        if wait is not None:
            self.wait(timeout=wait)

    @abstractmethod
    def stop(self, wait: Optional[int] = 60) -> None:  # noqa D102
        super().stop()
        self._start_pipe_drain()

    def _start_pipe_drain(self) -> None:
        """
        Start stdout/stderr pipe drain.

        This method should be called before waiting for process completion to avoid deadlock.

        The OS pipes have a certain size, so if they're not read from - they fill up and the OS prevent process
        from dying. To avoid that we need to make sure pipe-consuming threads are started on the remote host before
        waiting on process to close itself.

        More information: https://docs.python.org/3/library/subprocess.html#subprocess.Popen.wait
        """
        with suppress(RemoteProcessStreamNotAvailable):
            _ = self._stdout_queue  # noqa F841

        with suppress(RemoteProcessStreamNotAvailable):
            _ = self._stderr_queue  # noqa F841

    def _get_and_kill_process(self, with_signal: Optional[typing.Union[Signals, str, int]] = None) -> None:
        """
        Kill process and all of its children processes.

        :param with_signal: Signal used for killing processes - be aware it must be signal from remote connection
        :raises ModuleNotFoundError: when psutil is not available
        """
        psutil_process = self._get_psutil_process()
        children = self._get_children_processes(process=psutil_process)
        for child in children:
            self._kill_process(child, with_signal, is_child=True)

        gone, still_alive = self._owner.modules().psutil.wait_procs(children, timeout=5)
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"gone: {gone}, still_alive: {still_alive}")
        self._kill_process(psutil_process, with_signal)
        psutil_process.wait(5)

    def _get_children_processes(self, process: "Process") -> typing.List["Process"]:
        """
        Get children processes using psutil.

        :param process: Psutil process
        :return: List of children
        """
        return process.children(recursive=True)

    def _get_psutil_process(self) -> "Process":
        """
        Get process using psutil by PID.

        :return: Object of psutil process
        :raises ModuleNotFoundException: when psutil is not available
        """
        try:
            psutil_process: "Process" = self._owner.modules().psutil.Process(self._process.pid)
        except ModuleNotFoundError as e:
            logger.log(
                level=log_levels.MODULE_DEBUG,
                msg="Psutil module on remote machine is missing, verify your packages in python",
            )
            raise e
        return psutil_process

    def _kill_process(
        self, process: "Process", with_signal: Optional[typing.Union[Signals, str, int]] = None, is_child: bool = False
    ) -> None:
        """
        Kill/stop process by sending signal/kill command to psutil process.

        :param process: Process object to be killed
        :param with_signal: Optional signal type to be sent, otherwise process will be killed
        :param is_child: Information if it's child or not process
        """
        from psutil import NoSuchProcess

        process_string = "child process" if is_child else "process"
        try:
            if with_signal:
                with_signal = self._convert_to_signal_object(with_signal)
                logger.log(
                    level=log_levels.MODULE_DEBUG,
                    msg=f"Sending signal '{with_signal.name}' to {process_string} {process.pid}",
                )
                process.send_signal(with_signal)
                logger.log(
                    level=log_levels.MODULE_DEBUG,
                    msg=f"Sent signal '{with_signal.name}' to {process_string} {process.pid}",
                )
            else:
                logger.log(level=log_levels.MODULE_DEBUG, msg=f"Killing {process_string} {process.pid}")
                process.kill()
                logger.log(level=log_levels.MODULE_DEBUG, msg=f"Killed {process_string} {process.pid}")
        except NoSuchProcess as e:
            logger.log(level=log_levels.MODULE_DEBUG, msg=f"got exception during killing: {e}")
            if "process no longer exists" not in e.msg:
                raise RemoteProcessInvalidState("Found exception during killing") from e
            logger.log(level=log_levels.MODULE_DEBUG, msg=f"{process_string.title()} has been killed")

    def _convert_to_signal_object(self, with_signal: typing.Union[Signals, str, int]) -> Signals:
        """
        Change type of signal into signal object.

        :param with_signal: Value of signal to convert.
        :return: Signal object.
        """
        if isinstance(with_signal, str):
            return self._owner.modules().signal.Signals[with_signal.upper()]
        elif isinstance(with_signal, Signals):
            return getattr(self._owner.modules().signal.Signals, with_signal.name)
        elif isinstance(with_signal, int):
            return self._owner.modules().signal.Signals(with_signal)
