# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
from mfd_typing.os_values import OSType

from mfd_connect.process.local import WindowsLocalProcess


class TestWindowsLocalProcess:
    class_under_test = WindowsLocalProcess

    def test_stop_calls_kill(self, mocker):
        windows_process = self.class_under_test.__new__(self.class_under_test)
        windows_process.kill = mocker.create_autospec(windows_process.kill, spec_set=True, instance=True)
        mocker.patch("mfd_connect.process.local.windows.WindowsLocalProcess.running", return_value=True)
        super_mock = mocker.patch("mfd_connect.process.local.windows.super")
        windows_process.stop()
        super_mock.return_value.stop.assert_called_once()

        windows_process.kill.assert_called_once()

    def test_os_type_should_be_windows(self):
        assert self.class_under_test.os_type == OSType.WINDOWS
