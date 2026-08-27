# Copyright (C) 2025-2026 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for RPyC-specific RPyCProcess implementation."""

import itertools
import typing
from abc import abstractmethod
from contextlib import suppress
from signal import Signals, SIGTERM
from threading import Event, Lock
from time import sleep
from typing import IO, Any, Optional, Iterator, Callable, ClassVar


from mfd_common_libs import TimeoutCounter, log_levels
from mfd_typing.os_values import OSType, OSName

from mfd_connect.exceptions import (
    RemoteProcessTimeoutExpired,
    RemoteProcessStreamNotAvailable,
    RemoteProcessInvalidState,
)
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
    PIPE_DRAIN_TIMEOUT = 30
    """Seconds without new output after which a not-yet-EOF watcher is treated as stuck and stopped."""
    PIPE_DRAIN_MAX_TIMEOUT = 600
    """Absolute cap (seconds) on draining a single stream, so a child streaming output forever can't hang stop()."""
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
        self._cached_stdout_stop_event = None
        self._cached_stdout_done_event = None

        self._cached_stdout_iter = None
        self._stdout_iter_cache_lock = Lock()

        self._cached_stderr_queue = None
        self._stderr_queue_cache_lock = Lock()
        self._cached_stderr_stop_event = None
        self._cached_stderr_done_event = None

        self._cached_stderr_iter = None
        self._stderr_iter_cache_lock = Lock()

    @staticmethod
    def _get_process_io_queue(process_io: IO) -> "tuple[Any, Event, Event]":
        """
        Wrap process' IO stream in a remote-side, batch-drainable buffer.

        A watcher thread and the buffer are created on the *remote* side (this method is teleported), so
        reading the process' stream and buffering its lines happens locally on the remote host - no RPyC
        traffic per line. The returned drainer exposes ``drain()``, which pops all currently buffered text
        and returns it as a single string together with an EOF flag; because a ``(str, bool)`` tuple is
        passed by value, the whole backlog crosses the connection in a single round-trip instead of one
        round-trip per line. This is what keeps stopping large-output processes fast (the previous
        line-by-line callback design cost one RPyC round-trip per output line).

        Two events are also created on the remote side:
        - ``done_event`` is set once the watcher reaches stream EOF (all output buffered).
        - ``stop_event`` can be set (via :meth:`_stop_pipe_drain`) to make the watcher stop reading, so it
          can't keep a detached child's pipe drained forever and grow the remote buffer without bound.

        :param process_io: IO object to wrap around (stdout or stderr).
        :return: Tuple of (remote drainer, remote stop event, remote done event).
        """
        import threading

        buffer = []
        buffer_lock = threading.Lock()
        produced = [0]
        finished = [False]
        stop_event = threading.Event()
        done_event = threading.Event()

        class _RemoteDrainer:
            """Remote-side buffer whose drain() returns all buffered text at once (bulk, by value)."""

            def drain(self) -> "tuple[str, bool]":
                with buffer_lock:
                    text = "".join(buffer)
                    buffer.clear()
                    return text, finished[0]

            def progress(self) -> int:
                return produced[0]

        def _watcher() -> None:
            try:
                with process_io:
                    for line in process_io:
                        with buffer_lock:
                            buffer.append(line)
                            produced[0] += 1
                        if stop_event.is_set():
                            break
            except Exception:
                if not stop_event.is_set():
                    with buffer_lock:
                        buffer.append(
                            "<internal>: Error occurred during io processing. Check responder log for details."
                        )
                        produced[0] += 1
                    raise
            finally:
                with buffer_lock:
                    finished[0] = True
                done_event.set()

        stdout_watcher = threading.Thread(target=_watcher, daemon=True)
        stdout_watcher.start()

        return _RemoteDrainer(), stop_event, done_event

    @property
    def _remote_get_process_io_queue(self) -> Callable:
        """Teleported _get_process_io_queue method."""
        with self._remote_get_process_io_queue_cache_lock:
            if self._cached_remote_get_process_io_queue is None:
                self._cached_remote_get_process_io_queue = self._owner.teleport_function(self._get_process_io_queue)
        return self._cached_remote_get_process_io_queue

    @property
    def _stdout_queue(self) -> Any:
        """Remote-side stdout drainer (see :meth:`_get_process_io_queue`)."""
        with self._stdout_queue_cache_lock:
            if self._cached_stdout_queue is None:
                (
                    self._cached_stdout_queue,
                    self._cached_stdout_stop_event,
                    self._cached_stdout_done_event,
                ) = self._remote_get_process_io_queue(self.stdout_stream)
        return self._cached_stdout_queue

    @property
    def _stderr_queue(self) -> Any:
        """Remote-side stderr drainer (see :meth:`_get_process_io_queue`)."""
        with self._stderr_queue_cache_lock:
            if self._cached_stderr_queue is None:
                (
                    self._cached_stderr_queue,
                    self._cached_stderr_stop_event,
                    self._cached_stderr_done_event,
                ) = self._remote_get_process_io_queue(self.stderr_stream)
        return self._cached_stderr_queue

    @property
    def pid(self) -> int:
        """
        Field for Process ID.

        :return: PID
        """
        return self._process.pid

    def _iterate_non_blocking_queue(self, drainer: Any) -> Iterator[str]:
        """
        Get a polling line iterator over a remote drainer.

        Pulls buffered text from the remote side in bulk (one round-trip per poll, not per line) and
        splits it back into lines locally, so the iterator does not block the RPyC connection.

        :param drainer: Remote drainer returned by :meth:`_get_process_io_queue`.
        :return: Resulting line iterator.
        """
        partial = ""
        while True:
            text, done = drainer.drain()

            if text:
                partial += text
                chunks = partial.split("\n")
                partial = chunks.pop()  # trailing text after the last newline (incomplete line)
                for chunk in chunks:
                    yield chunk + "\n"
            elif done:
                # EOF reached and nothing left buffered - emit any trailing partial line and stop.
                if partial:
                    yield partial
                return
            else:
                # No output readily available
                sleep(self.POOL_INTERVAL)

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
            self._stop_pipe_drain()

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

    def _stop_pipe_drain(self, idle_timeout: Optional[float] = None, max_timeout: Optional[float] = None) -> None:
        """
        Stop stdout/stderr pipe-drain watcher threads started by :meth:`_start_pipe_drain`.

        Waits for each watcher to reach stream EOF (all buffered output drained), so any output the
        process emits after the stop signal - e.g. a traffic summary at the end of a large backlog - is
        fully captured, matching the behaviour of the SSH connection. The wait is bounded by output
        *inactivity*: as long as new lines keep arriving the drain keeps waiting, no matter how big the
        backlog or how small the caller's ``wait`` was. A stream is only given up on when either it
        produces no new output for ``idle_timeout`` seconds without reaching EOF (typically a detached
        child keeping the pipe open), or the absolute ``max_timeout`` cap is hit (a detached child that
        streams output forever) - in both cases the watcher is signalled to stop so it can't linger and
        congest the shared RPyC connection, nor hang ``stop``/``kill`` indefinitely.

        Should be called once the process has been confirmed finished (e.g. after a successful ``wait``).

        :param idle_timeout: Seconds of no new output after which a not-yet-EOF watcher is stopped.
                             Defaults to :attr:`PIPE_DRAIN_TIMEOUT`.
        :param max_timeout: Absolute cap in seconds on draining a single stream, regardless of activity.
                            Defaults to :attr:`PIPE_DRAIN_MAX_TIMEOUT`.
        """
        if idle_timeout is None:
            idle_timeout = self.PIPE_DRAIN_TIMEOUT
        if max_timeout is None:
            max_timeout = self.PIPE_DRAIN_MAX_TIMEOUT

        for queue_attr, stop_attr, done_attr in (
            ("_cached_stdout_queue", "_cached_stdout_stop_event", "_cached_stdout_done_event"),
            ("_cached_stderr_queue", "_cached_stderr_stop_event", "_cached_stderr_done_event"),
        ):
            drainer = getattr(self, queue_attr)
            stop_event = getattr(self, stop_attr)
            done_event = getattr(self, done_attr)
            if drainer is None or stop_event is None or done_event is None:
                continue
            with suppress(Exception):
                last_progress = None
                idle = TimeoutCounter(idle_timeout)
                hard_cap = TimeoutCounter(max_timeout)
                while not done_event.is_set():
                    progress = drainer.progress()
                    if progress != last_progress:
                        # Output is still being buffered - keep waiting and reset the inactivity timer.
                        last_progress = progress
                        idle = TimeoutCounter(idle_timeout)
                    if idle or hard_cap:
                        # No new output for idle_timeout seconds (detached child keeping the pipe open),
                        # or the absolute cap was hit (child streaming output forever) - stop the watcher
                        # to avoid an unbounded remote buffer and an unbounded wait.
                        stop_event.set()
                        break
                    sleep(self.POOL_INTERVAL)

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
