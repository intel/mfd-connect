# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
import pytest

from mfd_connect.exceptions import RemoteProcessInvalidState
from mfd_connect.process import RemoteProcess


class TestRemoteProcess:
    @pytest.fixture(scope="class")
    def remote_process(self):
        class_under_test = RemoteProcess
        if hasattr(class_under_test, "__abstractmethods__"):
            # Remove abstract methods, if any so the class can be instantiated
            class_under_test.__abstractmethods__ = []
        return class_under_test.__new__(class_under_test)

    @pytest.fixture
    def running_mock(self, mocker):
        return mocker.patch.object(RemoteProcess, "running", new_callable=mocker.PropertyMock)

    def test_stdout_text_unavailable_while_running(self, remote_process, running_mock):
        running_mock.return_value = True
        with pytest.raises(RemoteProcessInvalidState):
            _ = remote_process.stdout_text

    def test_stderr_text_unavailable_while_running(self, remote_process, running_mock):
        running_mock.return_value = True
        with pytest.raises(RemoteProcessInvalidState):
            _ = remote_process.stderr_text

    def test_return_code_unavailable_while_running(self, remote_process, running_mock):
        running_mock.return_value = True
        with pytest.raises(RemoteProcessInvalidState):
            _ = remote_process.return_code

    @pytest.mark.parametrize("timeout,exception", [(None, TypeError), (-1, AssertionError), (0, AssertionError)])
    def test_wait_checks_timeout(self, remote_process, timeout, exception):
        with pytest.raises(exception):
            remote_process.wait(timeout=timeout)

    @pytest.mark.parametrize("wait", [0, -1])
    def test_stop_checks_wait(self, remote_process, wait):
        with pytest.raises(AssertionError):
            remote_process.stop(wait=wait)

    def test_stop_checks_none(self, remote_process):
        try:
            remote_process.stop(wait=None)
        except (TypeError, AssertionError):
            pytest.fail("'stop' method must accept wait=None parameter")

    @pytest.mark.parametrize("wait", [0, -1])
    def test_kill_checks_wait(self, remote_process, wait):
        with pytest.raises(AssertionError):
            remote_process.kill(wait=wait)

    def test_kill_checks_none(self, remote_process):
        try:
            remote_process.kill(wait=None)
        except (TypeError, AssertionError):
            pytest.fail("'kill' method must accept wait=None parameter")
