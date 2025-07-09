# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module of SSH Process."""

import itertools
import logging
from abc import abstractmethod
from collections import namedtuple
from contextlib import suppress
from signal import SIGTERM, Signals
from threading import Lock, Thread
from time import sleep
from typing import Optional, Iterator, TYPE_CHECKING, Type, Set, ClassVar, List, Union

from mfd_common_libs import TimeoutCounter, add_logging_level, log_levels
from mfd_typing.os_values import OSName

from ..base import RemoteProcess
from ...exceptions import (
    RemoteProcessStreamNotAvailable,
    RemoteProcessTimeoutExpired,
    RemoteProcessInvalidState,
    SSHPIDException,
)
from ...util import BatchQueue

if TYPE_CHECKING:
    from paramiko import ChannelFile, Channel
    from mfd_connect import SSHConnection
    from pathlib import Path

logger = logging.getLogger(__name__)
add_logging_level(level_name="MODULE_DEBUG", level_value=log_levels.MODULE_DEBUG)


class SSHProcess(RemoteProcess):
    """Implementation of SSH Process."""

    POOL_INTERVAL = 0.1
    """Interval for polling operations."""

    _os_name: ClassVar[Set[Type["OSName"]]] = None

    def __init__(
        self,
        *,
        stdin: Optional["ChannelFile"],
        stdout: Optional["ChannelFile"],
        stderr: Optional["ChannelFile"],
        unique_name: str = "",
        pid: str = None,
        connection: "SSHConnection",
        channel: Optional["Channel"] = None,
        log_path: "Path | None" = None,
    ) -> None:
        """
        Init of SSHProcess.

        :param stdin: Input stream from paramiko
        :param stdout: Output stream from paramiko
        :param stderr: Error stream from paramiko
        :param unique_name: Unique name of process, helper for find and kill process
        :param pid: Process ID if available
        :param connection: Reference to connection
        :param channel: Paramiko channel, can be provided if stdout/err/in are discarded
        """
        super().__init__()

        assert self._os_name is not None, "OS name must be defined for Process"

        Process = namedtuple("SSHProcess", ["stdin", "stdout", "stderr"])

        self._process = Process(stdin=stdin, stdout=stdout, stderr=stderr)

        self.log_path = log_path
        self.log_file_stream = None  # compatibility with RPyC

        self._unique_name = unique_name
        self._pid = pid
        self._connection_handle = connection

        self._cached_stdout_queue = None
        self._stdout_queue_cache_lock = Lock()

        self._cached_stdout_iter = None
        self._stdout_iter_cache_lock = Lock()

        self._cached_stderr_queue = None
        self._stderr_queue_cache_lock = Lock()

        self._cached_stderr_iter = None
        self._stderr_iter_cache_lock = Lock()

        self._channel = (
            channel
            if channel is not None
            else next((std.channel for std in [stdout, stderr, stdin] if std is not None), None)
        )

        # read pid after start process
        if not self._pid:
            try:
                self._pid = self.pid
            except RemoteProcessInvalidState:
                self._pid = None

    @property
    def stdin_stream(self) -> "ChannelFile":
        """
        Process stdin stream.

        :raises RemoteProcessStreamNotAvailable when stdin stream will be not available.
        """
        _ = super().stdin_stream
        stdin = self._process.stdin
        if stdin is None:
            raise RemoteProcessStreamNotAvailable("stdin stream is not available")
        return stdin

    @property
    def stdout_stream(self) -> "ChannelFile":
        """
        Process stdout stream.

        Should be avoided if stdout_text or get_stdout_iter() can be used instead.

        :raises RemoteProcessStreamNotAvailable when stdout stream will be not available.
        """
        _ = super().stdout_stream
        stdout = self._process.stdout
        if stdout is None:
            raise RemoteProcessStreamNotAvailable("stdout stream is not available")
        return self._process.stdout

    @property
    def stderr_stream(self) -> "ChannelFile":
        """
        Process stderr stream.

        Should be avoided if stderr_text or get_stderr_iter() can be used instead.

        :raises RemoteProcessStreamNotAvailable when stderr stream will be not available.
        """
        _ = super().stderr_stream
        stderr = self._process.stderr
        if stderr is None:
            raise RemoteProcessStreamNotAvailable("stderr stream is not available")
        return self._process.stderr

    @property
    def stdout_text(self) -> str:
        """
        Full process stdout text.

        Not available until the process is stopped.

        :raises RemoteProcessInvalidState when process will be not completed.
        """
        _ = super().stdout_text
        return "".join(self.get_stdout_iter())

    @property
    def stderr_text(self) -> str:
        """
        Full process stderr text.

        Not available until the process is stopped.

        :raises RemoteProcessInvalidState when process will be not completed.
        """
        _ = super().stderr_text
        return "".join(self.get_stderr_iter())

    @property
    def return_code(self) -> Optional[int]:
        """
        Return code of the process.

        Negative value if the process was killed.
        Zero or positive value if the return code was retrieved.
        Not available until the process is stopped.

        :raises RemoteProcessInvalidState when process will be not completed.
        """
        _ = super().return_code
        return self._channel.recv_exit_status()

    @property
    def running(self) -> bool:
        """Whenever the process is running or not."""
        try:
            return self._pid in self._find_pids(self._connection_handle, self._unique_name)
        except RemoteProcessInvalidState:
            logger.log(log_levels.MODULE_DEBUG, msg="Not found PID in system, process is not running.")
            return False

    @staticmethod
    @abstractmethod
    def _find_pids(connection: "SSHConnection", name: str) -> List[int]:
        """
        Find PIDs by name.

        :param connection: connection
        :param name: name of process, generated in start process
        :return: List of PIDs if any PID exists
        :raises RemoteProcessInvalidState: if cannot find PID
        """
        logger.log(log_levels.MODULE_DEBUG, msg="Reading pid of process")

    @staticmethod
    def _get_process_io_queue(process_io: "ChannelFile") -> BatchQueue:
        """
        Wrap process' IO stream in a line-by-line queue.

        Unlike IO stream - resulting queue can be used to peek if new output lines are available.
        This gives the ability to periodically poll the queue for new results.

        :param process_io: IO object to wrap around (stdout or stderr).
        :return: Queue wrapped around stdout.readline() call.
        """
        q = BatchQueue()

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

        io_watcher = Thread(target=_watcher, daemon=True)
        io_watcher.start()

        return q

    @property
    def _stdout_queue(self) -> BatchQueue:
        """Stdout line-by-line queue."""
        with self._stdout_queue_cache_lock:
            if self._cached_stdout_queue is None:
                self._cached_stdout_queue = self._get_process_io_queue(self.stdout_stream)
        return self._cached_stdout_queue

    @property
    def _stderr_queue(self) -> BatchQueue:
        """Stderr line-by-line queue."""
        with self._stderr_queue_cache_lock:
            if self._cached_stderr_queue is None:
                self._cached_stderr_queue = self._get_process_io_queue(self.stderr_stream)
        return self._cached_stderr_queue

    @property
    def pid(self) -> int:
        """
        Field for Process ID.

        :return: PID
        :raises RemoteProcessInvalidState: if process is not available in system.
        """
        if not self._pid:
            all_pids = self._find_pids(self._connection_handle, self._unique_name)
            if len(all_pids) > 1:
                raise SSHPIDException("Found more than one PID. You should consider using StartProcesses method.")
            self._pid = all_pids[0]
        return self._pid

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

    def get_stdout_iter(self) -> Iterator[str]:
        """
        Get iterator over stdout lines of the process.

        Unlike stdout_text - this is available while the process is running.
        If the process is still running, but iterator has come to the end of the
        available data - next() will block until new data arrives or process concludes.
        Each call of the method will produce new iterator, starting from the beginning
        of the process output.

        :return: Iterator over stdout lines of the process.
        """
        with self._stdout_iter_cache_lock:
            super().get_stdout_iter()
            if self._cached_stdout_iter is None:
                self._cached_stdout_iter = self._iterate_non_blocking_queue(self._stdout_queue)

            self._cached_stdout_iter, result = itertools.tee(self._cached_stdout_iter)
        return result

    def get_stderr_iter(self) -> Iterator[str]:
        """
        Get iterator over stderr lines of the process.

        Unlike stderr_text - this is available while the process is running.
        If the process is still running, but iterator has come to the end of the
        available data - next() will block until new data arrives or process concludes.
        Each call of the method will produce new iterator, starting from the beginning
        of the process output.

        :return: Iterator over stderr lines of the process.
        """
        with self._stderr_iter_cache_lock:
            super().get_stderr_iter()
            if self._cached_stderr_iter is None:
                self._cached_stderr_iter = self._iterate_non_blocking_queue(self._stderr_queue)

            self._cached_stderr_iter, result = itertools.tee(self._cached_stderr_iter)
        return result

    def wait(self, timeout: int = 60) -> int:
        """
        Wait for the process to conclude on its own.

        :param timeout: Time to wait for process to conclude.
        :return: Process return code.
        :raises RemoteProcessTimeoutExpired: If the process did not conclude before the timer ran out.
        """
        super().wait(timeout)
        self._start_pipe_drain()

        timeout = TimeoutCounter(timeout)
        while not timeout:
            if not self.running:
                return self.return_code
            sleep(self.POOL_INTERVAL)
        else:
            raise RemoteProcessTimeoutExpired()

    @abstractmethod
    def stop(self, wait: Optional[int] = 60) -> None:
        """
        Signal the process to stop gracefully.

        :param wait: Time in seconds to wait for the process to finish before returning.
                     If None - no waiting is performed.
        :raises SSHRemoteProcessEndException: if cannot stop the process.
        """
        super().stop()
        self._start_pipe_drain()

    @abstractmethod
    def kill(self, wait: Optional[int] = 60, with_signal: Union[Signals, str, int] = SIGTERM) -> None:
        """
        Kill the process forcefully.

        :param wait: Time in seconds to wait for the process to finish before returning.
                     If None - no waiting is performed.
        :param with_signal: Signal to be used for killing process, e.g. signal.SIGTERM/15/'SIGTERM'
        :raises SSHRemoteProcessEndException: if cannot kill the process.
        """
        super().kill()
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
            _ = self._stdout_queue

        with suppress(RemoteProcessStreamNotAvailable):
            _ = self._stderr_queue
