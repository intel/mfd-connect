# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for SerialConnection tests."""

import pytest
from netaddr import IPAddress

from mfd_connect import Connection, AsyncConnection, SerialConnection, TelnetConnection, RPyCConnection
from mfd_connect.base import ConnectionCompletedProcess
from mfd_connect.exceptions import (
    SerialException,
    TelnetException,
    TransferFileError,
    ConnectionCalledProcessError,
    OsNotSupported,
)
from mfd_connect.process import RemoteProcess
from mfd_common_libs import log_levels
from mfd_typing import OSType, OSName, OSBitness

file_content = b"""Lorem ipsum dolor sit amet, consectetur adipiscing elit."""
# noqa: W291,W293,E501
serial_output = """\
[0m[30m[40m[25;27H  [01D  [0m[30m[47m[06;01H   Current Secure Boot State  Disabled                   [0m[37m[40m[23;02H [22;02H [50CF10=Save                 [51DF9=Reset to Defaults      [23;53HEsc=Exit                   [77D^v=Move Highlight       [22;03H                        [23;27H<Enter>=Select Entry      [0m[30m[47m[0m[37m[40m[08;31H<Standard Mode>[0m[30m[47m            [57D   Secure Boot Mode           [0m[34m[47m[05;58HSecure Boot Mode:      
[57CCustom Mode or         
[57CStandard Mode          
[57C                       
[57C                       
[57C                       
[19;80H[0m[30m[40m[25;27H  [01D  [0m[30m[47m[08;31H<Standard Mode>            [57D   Secure Boot Mode           [0m[37m[40m[23;02H [22;02H [50CF10=Save                 [51DF9=Reset to Defaults      [23;53HEsc=Exit                   [77D^v=Move Highlight                                 [22;03H                        [0m[30m[47m[06;01H   [0m[37m[40mCurrent Secure Boot State[0m[30m[47m  Disabled                   [0m[34m[47m[05;58HCurrent Secure Boot    
[57Cstate: enabled or      
[57Cdisabled.              
[57C                       
[57C                       
[57C                                     
[57C                       
[57C                       
[57C                       
[19;80H"""  # noqa: W291,W293,E501,BLK100

expected_serial_output = """\
                                                                                
                                                                                
                                                                                
                                                                                
                                                         Current Secure Boot    
   Current Secure Boot State  Disabled                                          
                                                         state: enabled or      
   Secure Boot Mode           <Standard Mode>                                   
                                                         disabled.              
                                                                                
                                                                                
                                                                                
                                                                                
                                                                                
                                                                                
                                                                                
                                                                                
                                                                                
                                                                                
                                                                                
                                                                                
                          F9=Reset to Defaults      F10=Save                    
  ^v=Move Highlight                                 Esc=Exit                    
                                                                                
                                                                                
                                                                                
                                                                                
                                                                                
                                                                                
                                                                                """  # noqa: W291,W293,E501


class TestSerialConnection:
    """Tests for SerialConnection."""

    @pytest.fixture
    def host_conn(self, mocker):
        host_conn = mocker.create_autospec(AsyncConnection)
        host_conn._ip = "127.0.0.1"
        return host_conn

    @pytest.fixture
    def serial(self, mocker, host_conn):
        mocker.patch.object(SerialConnection, "__init__", return_value=None)
        serial = SerialConnection(
            connection=host_conn, username="root", password="***", telnet_port=1240, serial_device="/dev/ttyUSB1"
        )
        serial._remote_host = host_conn
        serial._telnet_port = 1240
        serial._serial_device = "/dev/ttyUSB1"
        serial._telnet_connection = mocker.create_autospec(Connection)
        serial.cache_system_data = True
        return serial

    def test_set_baudrate_if_could_not_connect_successful(self, mocker, caplog, host_conn):
        caplog.set_level(log_levels.MODULE_DEBUG)
        log_message = "Could not connect to target, setting baudrate for serial device and retrying..."
        mocker.patch.object(SerialConnection, "_run_netcat", return_value=None)
        mocker.patch.object(SerialConnection, "_set_baudrate", return_value=None)
        mocker.patch.object(TelnetConnection, "__init__", side_effect=[TelnetException, None])

        serial = SerialConnection(
            connection=host_conn, username="root", password="***", telnet_port=1240, serial_device="/dev/ttyUSB1"
        )
        assert log_message in caplog.messages
        serial._set_baudrate.assert_called_once()

    def test_set_baudrate_if_could_not_connect_failed(self, mocker, caplog, host_conn):
        caplog.set_level(log_levels.MODULE_DEBUG)
        baudrate = 460800
        log_message = "Could not connect to target, setting baudrate for serial device and retrying..."
        mocker.patch.object(SerialConnection, "_run_netcat", return_value=None)
        mocker.patch.object(SerialConnection, "_set_baudrate", return_value=None)
        mocker.patch.object(TelnetConnection, "__init__", side_effect=TelnetException)

        with pytest.raises(SerialException, match=f"Could not connect to target after setting baudrate to {baudrate}"):
            serial = SerialConnection(
                connection=host_conn,
                username="root",
                password="***",
                telnet_port=1240,
                serial_device="/dev/ttyUSB1",
                baudrate=baudrate,
            )
            assert log_message in caplog.messages
            serial._set_baudrate.assert_called_once()

    def test_run_netcat_kill_previous_connection(self, mocker, caplog, serial):
        caplog.set_level(log_levels.MODULE_DEBUG)
        log_message = "Killing old netcat connections on host"
        mocker.patch("time.sleep")
        netcat_process = mocker.create_autospec(RemoteProcess)
        netcat_process.running = True
        serial._serial_logs_path = None
        serial._remote_host.execute_command.return_value = ConnectionCompletedProcess(
            return_code=0, args=f'pkill -f "nc -k -l -4 {serial._telnet_port}"', stdout="stdout", stderr="stderr"
        )
        serial._remote_host.start_process.return_value = mocker.create_autospec(RemoteProcess)

        serial._run_netcat()
        serial._remote_host.execute_command.assert_called_once_with(
            f'pkill -f "nc -k -l -4 {serial._telnet_port}"', expected_return_codes=None
        )
        assert log_message in caplog.messages

    def test_run_netcat_start_netcat_server(self, mocker, caplog, serial):
        log_messages = [
            "Starting netcat server on host",
            "Waiting for netcat server to start...",
            "Netcat sender server is running",
        ]
        caplog.set_level(log_levels.MODULE_DEBUG)
        mocker.patch("time.sleep")

        serial._serial_logs_path = None
        serial._run_netcat()
        serial._remote_host.start_process.assert_called_once_with(
            f"nc -k -l -4 {serial._telnet_port} > {serial._serial_device} < {serial._serial_device}", shell=True
        )
        assert all(msg in caplog.messages for msg in log_messages)

    def test_run_netcat_server_not_running_exception(self, mocker, serial):
        mocker.patch("time.sleep")
        netcat_process = mocker.create_autospec(RemoteProcess)
        netcat_process.running = False
        serial._remote_host.start_process.return_value = netcat_process

        with pytest.raises(
            SerialException,
            match="Netcat server did not start properly. Make sure pppd connection is not blocking this device.",
        ):
            serial._run_netcat()

    def test_trigger_tee_serial_logging(self, mocker, caplog, serial):
        log_messages = [
            "Killing old netcat localhost process.",
            "Starting nc | tee logging...",
            "nc | tee logging processes started properly.",
        ]
        caplog.set_level(log_levels.MODULE_DEBUG)
        mocker.patch("time.sleep")

        serial._serial_logs_path = ""
        serial._trigger_tee_serial_logging(0.5)
        serial._remote_host.start_processes.assert_called_once_with(
            f"nc 127.0.0.1 {serial._telnet_port} | tee {serial._serial_logs_path}", shell=True
        )
        assert all(msg in caplog.messages for msg in log_messages)

    def test_shutdown_platform_exception(self, serial):
        with pytest.raises(NotImplementedError):
            serial.shutdown_platform()

    def test_wait_for_host_exception(self, serial):
        with pytest.raises(NotImplementedError):
            serial.wait_for_host()

    def test_restart_platform_exception(self, serial):
        with pytest.raises(NotImplementedError):
            serial.restart_platform()

    def test_get_os_type(self, serial, mocker):
        serial.execute_command = mocker.create_autospec(
            serial.execute_command,
            return_value=ConnectionCompletedProcess(
                return_code=0,
                args="uname -a",
                stdout=r"Linux localhost.localdomain 5.3.15-200.fc30.x86_64 #1 SMP "
                r"Thu Dec 5 15:18:00 UTC 2019 x86_64 x86_64 x86_64 GNU/Linux",
                stderr="stderr",
            ),
        )
        assert serial.get_os_type() == OSType.POSIX

    def test_get_os_type_exception(self, serial, mocker):
        serial.execute_command = mocker.create_autospec(
            serial.execute_command,
            return_value=ConnectionCompletedProcess(
                return_code=14,
                args="uname -a",
                stdout=r"\'uname\' is not recognized as an internal or external "
                r"command,\noperable program, or script file.",
                stderr="stderr",
            ),
        )
        with pytest.raises(OsNotSupported):
            serial.get_os_type()

    def test_get_os_name(self, serial, mocker):
        serial.execute_command = mocker.create_autospec(
            serial.execute_command,
            return_value=ConnectionCompletedProcess(
                return_code=0,
                args="uname -s",
                stdout=r"Linux",
                stderr="stderr",
            ),
        )

        assert serial.get_os_name() == OSName.LINUX

    def test_get_os_name_exception(self, serial, mocker):
        serial.execute_command = mocker.create_autospec(
            serial.execute_command,
            return_value=ConnectionCompletedProcess(
                return_code=14,
                args="uname -s",
                stdout=r"\'uname\' is not recognized as an internal or external "
                r"command,\noperable program, or script file.",
                stderr="stderr",
            ),
        )
        with pytest.raises(OsNotSupported):
            serial.get_os_name()

    def test_get_os_bitness_64(self, serial, mocker):
        serial.execute_command = mocker.create_autospec(
            serial.execute_command,
            return_value=ConnectionCompletedProcess(
                return_code=0,
                args="uname -m",
                stdout=r"64bit",
                stderr="stderr",
            ),
        )

        assert serial.get_os_bitness() == OSBitness.OS_64BIT

    def test_get_os_bitness_32(self, serial, mocker):
        serial.execute_command = mocker.create_autospec(
            serial.execute_command,
            return_value=ConnectionCompletedProcess(
                return_code=0,
                args="uname -m",
                stdout=r"32bit",
                stderr="stderr",
            ),
        )

        assert serial.get_os_bitness() == OSBitness.OS_32BIT

    def test_get_os_bitness_32_x86(self, serial, mocker):
        serial.execute_command = mocker.create_autospec(
            serial.execute_command,
            return_value=ConnectionCompletedProcess(
                return_code=0,
                args="uname -m",
                stdout=r"86",
                stderr="stderr",
            ),
        )

        assert serial.get_os_bitness() == OSBitness.OS_32BIT

    def test_get_os_bitness_32_armv71(self, serial, mocker):
        serial.execute_command = mocker.create_autospec(
            serial.execute_command,
            return_value=ConnectionCompletedProcess(
                return_code=0,
                args="uname -m",
                stdout=r"armv7l",
                stderr="stderr",
            ),
        )

        assert serial.get_os_bitness() == OSBitness.OS_32BIT

    def test_get_os_bitness_32_arm(self, serial, mocker):
        serial.execute_command = mocker.create_autospec(
            serial.execute_command,
            return_value=ConnectionCompletedProcess(
                return_code=0,
                args="uname -m",
                stdout=r"arm",
                stderr="stderr",
            ),
        )

        assert serial.get_os_bitness() == OSBitness.OS_32BIT

    def test_get_os_bitness_exception(self, serial, mocker, host_conn):
        serial.execute_command = mocker.create_autospec(
            serial.execute_command,
            return_value=ConnectionCompletedProcess(
                return_code=14,
                args="uname -m",
                stdout=r"\'uname\' is not recognized as an internal or external "
                r"command,\noperable program, or script file.",
                stderr="stderr",
            ),
        )
        serial._ip = "1.1.1.1"
        with pytest.raises(OsNotSupported):
            serial.get_os_bitness()

    def test_path_exception(self, serial):
        with pytest.raises(NotImplementedError):
            _ = serial.path

    def test_disconnect(self, mocker, serial):
        serial._server_process = mocker.create_autospec(RemoteProcess)
        serial.stop_logging = mocker.create_autospec(RemoteProcess)
        serial.disconnect()
        serial._server_process.kill.assert_called_once()
        serial._remote_host.disconnect.assert_called_once()

    def test__check_control_sum(self, mocker, serial, caplog):
        caplog.set_level(log_levels.MODULE_DEBUG)
        file_hash = "28d939c07a3c246ff39feeca72915c618526543a85d6663442ac13ebc1683e04"
        serial._telnet_connection = mocker.Mock()
        serial._telnet_connection.execute_command.return_value = ConnectionCompletedProcess(
            return_code=0, args="", stdout=f"{file_hash}  test.txt", stderr="stderr"
        )
        hexdigest_mock = mocker.Mock()
        hexdigest_mock.hexdigest.return_value = file_hash
        mocker.patch("hashlib.sha256", return_value=hexdigest_mock)
        mocker.patch("builtins.open", return_value=mocker.MagicMock())
        serial._check_control_sum(local_path="test_path.txt", remote_path="test_path.txt")
        assert f"Correct sha256sum for file, local: {file_hash}, remote: {file_hash}" in caplog.messages

    def test__check_control_sum_not_equal_exception(self, mocker, serial):
        hash_a = "28d939c07a3c246ff39feeca72915c618526543a85d6663442ac13ebc1683e04"
        hash_b = "af3ebdafaacbf284d7aef03caaf7e100511b7e3e4bcaf6cceabb3c8272f28e9f"

        serial._telnet_connection = mocker.Mock()
        serial._telnet_connection.execute_command.return_value = ConnectionCompletedProcess(
            return_code=0, args="", stdout=f"{hash_a}  test.txt", stderr="stderr"
        )
        hexdigest_mock = mocker.Mock()
        hexdigest_mock.hexdigest.return_value = hash_b
        mocker.patch("hashlib.sha256", return_value=hexdigest_mock)
        mocker.patch("builtins.open", return_value=mocker.MagicMock())
        with pytest.raises(TransferFileError, match=f"Incorrect sha256sum, local: {hash_b}, remote: {hash_a}"):
            serial._check_control_sum(local_path="test_path.txt", remote_path="test_path.txt")

    def test__check_control_sum_execute_command_exception(self, mocker, serial):
        serial._telnet_connection = mocker.Mock()
        serial._telnet_connection.execute_command.side_effect = ConnectionCalledProcessError
        with pytest.raises(TransferFileError, match="Failed to get control sums"):
            serial._check_control_sum(local_path="test_path.txt", remote_path="test_path.txt")

    def test_get_output_after_user_action(self, mocker, serial):
        connection_mock = mocker.patch.object(serial, "_telnet_connection")
        connection_mock.console.read.return_value.decode.return_value = serial_output
        output = serial.get_output_after_user_action()
        assert output == expected_serial_output

    def test_get_screen_field_value(self, mocker, serial):
        mocker.patch.object(serial, "get_output_after_user_action", return_value=expected_serial_output)
        output = serial.get_screen_field_value(r"Secure Boot Mode\s+<(?P<value>.*)>", group_name="value")
        assert output == "Standard Mode"
        output = serial.get_screen_field_value(r"Notsecured\s+<(?P<value>.*)>", group_name="value")
        assert output is None

    def test_str_function(self, serial):
        assert str(serial) == "serial"

    def test_init_with_model(self, mocker):
        mocker.patch("mfd_connect.TelnetConnection.__init__", return_value=None)
        model = mocker.Mock()
        connection = mocker.create_autospec(RPyCConnection)
        connection._ip = IPAddress("10.10.10.10")
        obj = SerialConnection(connection=connection, model=model, telnet_port=1, serial_device="")
        assert obj.model == model
        obj = SerialConnection(connection=connection, telnet_port=1, serial_device="")
        assert obj.model is None
