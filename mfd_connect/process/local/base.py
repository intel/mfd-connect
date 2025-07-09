# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for LocalProcess class."""

import itertools
import typing
from contextlib import suppress
from signal import SIGTERM, Signals
from threading import Lock, Thread
from time import sleep
from typing import Optional, TYPE_CHECKING, Iterator, IO, ClassVar

from mfd_typing.os_values import OSType
from mfd_common_libs import TimeoutCounter

from ..base import RemoteProcess
from ...exceptions import RemoteProcessStreamNotAvailable, RemoteProcessTimeoutExpired
from ...util import BatchQueue

if TYPE_CHECKING:
    from subprocess import Popen


class LocalProcess(RemoteProcess):
    """
    RemoteProcess implementation for local usage.

    This class is a wrapper around subprocess.Popen object to standardize output from Connection start_process().
    """

    POOL_INTERVAL = 0.1
    """Interval for polling operations."""

    os_type: ClassVar[OSType] = None

    def __init__(self, *, process: "Popen") -> None:
        """
        Init of LocalProcess.

        :param process: Process Popen object.
        """
        super().__init__()
        assert self.os_type is not None, "os_type attribute must be defined in every subclass"

        self._process = process

        self.log_path = None  # compatibility with RPyC
        self.log_file_stream = None  # compatibility with RPyC

        self._cached_stdout_queue = None
        self._stdout_queue_cache_lock = Lock()

        self._cached_stdout_iter = None
        self._stdout_iter_cache_lock = Lock()

        self._cached_stderr_queue = None
        self._stderr_queue_cache_lock = Lock()

        self._cached_stderr_iter = None
        self._stderr_iter_cache_lock = Lock()

    @staticmethod
    def _get_process_io_queue(process_io: IO) -> BatchQueue:
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
    def running(self) -> bool:  # noqa: D102
        _ = super().running
        return self._process.poll() is None

    @property
    def stdin_stream(self) -> IO:  # noqa: D102
        _ = super().stdin_stream
        stdin = self._process.stdin
        if stdin is None:
            raise RemoteProcessStreamNotAvailable("stdin stream is not available")
        return stdin

    @property
    def stdout_stream(self) -> IO:  # noqa: D102
        _ = super().stdout_stream
        stdout = self._process.stdout
        if stdout is None:
            raise RemoteProcessStreamNotAvailable("stdout stream is not available")
        return self._process.stdout

    @property
    def stderr_stream(self) -> IO:  # noqa: D102
        _ = super().stderr_stream
        stderr = self._process.stderr
        if stderr is None:
            raise RemoteProcessStreamNotAvailable("stderr stream is not available")
        return self._process.stderr

    @property
    def stdout_text(self) -> str:  # noqa: D102
        _ = super().stdout_text
        return "".join(self.get_stdout_iter())

    @property
    def stderr_text(self) -> str:  # noqa: D102
        _ = super().stderr_text
        return "".join(self.get_stderr_iter())

    def get_stdout_iter(self) -> Iterator[str]:  # noqa: D102
        with self._stdout_iter_cache_lock:
            super().get_stdout_iter()
            if self._cached_stdout_iter is None:
                self._cached_stdout_iter = self._iterate_non_blocking_queue(self._stdout_queue)

            self._cached_stdout_iter, result = itertools.tee(self._cached_stdout_iter)
        return result

    def get_stderr_iter(self) -> Iterator[str]:  # noqa: D102
        with self._stderr_iter_cache_lock:
            super().get_stderr_iter()
            if self._cached_stderr_iter is None:
                self._cached_stderr_iter = self._iterate_non_blocking_queue(self._stderr_queue)

            self._cached_stderr_iter, result = itertools.tee(self._cached_stderr_iter)
        return result

    @property
    def return_code(self) -> Optional[int]:  # noqa: D102
        _ = super().return_code
        return self._process.returncode

    def wait(self, timeout: int = 60) -> int:  # noqa: D102
        super().wait(timeout)
        self._start_pipe_drain()

        timeout = TimeoutCounter(timeout)
        while not timeout:
            if not self.running:
                return self.return_code
            sleep(self.POOL_INTERVAL)
        else:
            raise RemoteProcessTimeoutExpired()

    def stop(self, wait: Optional[int] = 60) -> None:  # noqa: D102
        super().stop()
        self._start_pipe_drain()

    def kill(self, wait: Optional[int] = 60, with_signal: typing.Union[Signals, str, int] = SIGTERM) -> None:  # noqa: D102
        super().kill()
        self._start_pipe_drain()
        self._process.kill()

        if wait is not None:
            self.wait(timeout=wait)

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
