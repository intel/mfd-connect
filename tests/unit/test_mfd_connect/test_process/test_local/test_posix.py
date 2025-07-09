# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
import signal
from subprocess import Popen

import pytest
from mfd_typing.os_values import OSType

from mfd_connect.process.local import POSIXLocalProcess
from mfd_connect.exceptions import RemoteProcessInvalidState


class TestPOSIXLocalProcess:
    class_under_test = POSIXLocalProcess

    @pytest.fixture
    def posix_process(self, mocker):
        posix_process = self.class_under_test.__new__(self.class_under_test)
        posix_process._process = mocker.create_autospec(Popen, spec_set=True, instance=True)
        posix_process.wait = mocker.create_autospec(posix_process.wait)
        mocker.patch("mfd_connect.process.local.posix.POSIXLocalProcess.running", return_value=True)
        return posix_process

    @pytest.fixture
    def super_mock(self, mocker):
        return mocker.patch("mfd_connect.process.local.posix.super")

    def test_stop_sends_proper_signal(self, posix_process, super_mock):
        posix_process.stop()
        super_mock.assert_called_once()

        posix_process._process.send_signal.assert_called_once_with(signal.SIGINT)

    def test_stop_no_wait(self, posix_process, super_mock):
        posix_process.stop(wait=None)

        posix_process.wait.assert_not_called()

    def test_stop_wait(self, posix_process, super_mock):
        posix_process.stop(wait=10)

        posix_process.wait.assert_called_once_with(timeout=10)

    def test_stop_already_finished_process_exception(self, posix_process):
        posix_process.running = False

        with pytest.raises(RemoteProcessInvalidState, match="Process has already finished"):
            posix_process.stop()

    def test_os_type_should_be_posix(self):
        assert self.class_under_test.os_type == OSType.POSIX
