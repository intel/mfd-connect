# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Tests of rpc_system_info_utils functions."""

from textwrap import dedent
import pytest
from mfd_typing.os_values import OSName, SystemInfo, OSBitness


from mfd_connect import RPyCConnection
from mfd_connect.base import ConnectionCompletedProcess
from mfd_connect.exceptions import ConnectionCalledProcessError
from mfd_connect.util.rpc_system_info_utils import (
    _get_system_info_windows,
    _get_hostname_linux,
    _get_os_name_linux,
    _get_os_version_linux,
    get_kernel_version_linux,
    _get_system_boot_time_linux,
    _get_system_manufacturer_and_model_linux,
    _get_system_manufacturer_and_model_esxi,
    _get_bios_version_linux,
    _get_total_memory_linux,
    _get_system_info_linux,
    _get_os_name_freebsd,
    _get_total_memory_freebsd,
    _get_total_memory_esxi,
    _get_system_info_freebsd,
    _get_system_info_esxi,
    _get_bios_version_esxi,
    is_current_kernel_version_equal_or_higher,
    get_os_version_mellanox,
)


class TestRPCSystemInfoUtils:
    @pytest.fixture()
    def conn(self, mocker):
        with mocker.patch.object(RPyCConnection, "__init__", return_value=None):
            conn = RPyCConnection(ip="10.10.10.10")
            conn._ip = "10.10.10.10"
            conn._os_name = OSName.LINUX
            conn._enable_bg_serving_thread = True
            return conn

    def test__get_system_info_windows(self, conn, mocker):
        mock_output = dedent(
            """

                        Host Name:                 WINDOWS-2019
                        OS Name:                   Microsoft Windows Server 2019 Standard
                        OS Version:                10.0.17763 N/A Build 17763
                        OS Manufacturer:           Microsoft Corporation
                        OS Configuration:          Standalone Server
                        OS Build Type:             Multiprocessor Free
                        Registered Owner:
                        Registered Organization:   Intel
                        Product ID:                XXXXX-70000-00000-XXXXXX
                        Original Install Date:     3/11/2023, 10:53:05 AM
                        System Boot Time:          4/4/2023, 2:40:55 PM
                        System Manufacturer:       Intel Corporation
                        System Model:              S2600BPB
                        System Type:               x64-based PC
                        Processor(s):              2 Processor(s) Installed.
                                                   [01]: Intel64 Family 6 Model 85 Stepping 7 GenuineIntel ~2394 Mhz
                                                   [02]: Intel64 Family 6 Model 85 Stepping 7 GenuineIntel ~2394 Mhz
                        BIOS Version:              Intel Corporation SE5C620.86B.02.01.0012.070720200218, 7/7/2020
                        Windows Directory:         C:\\Windows
                        System Directory:          C:\\Windows\\system32
                        Boot Device:               \\Device\\HarddiskVolume2
                        System Locale:             en-us;English (United States)
                        Input Locale:              en-us;English (United States)
                        Time Zone:                 (UTC+01:00) Sarajevo, Skopje, Warsaw, Zagreb
                        Total Physical Memory:     130,771 MB
                        Available Physical Memory: 121,267 MB
                        Virtual Memory: Max Size:  131,795 MB
                        Virtual Memory: Available: 122,787 MB
                        Virtual Memory: In Use:    9,008 MB
                        Page File Location(s):     C:\\pagefile.sys
                        Domain:                    DOMAIN_NAME
                        Logon Server:              N/A
                        Hotfix(s):                 7 Hotfix(s) Installed.
                                                   [01]: KB5022511
                                                   [02]: KB4589208
                                                   [03]: KB5005112
                                                   [04]: KB5012170
                                                   [05]: KB5025229
                                                   [06]: KB5020374
                                                   [07]: KB5023789
                        Network Card(s):           6 NIC(s) Installed.
                                                   [01]: Intel(R) Ethernet Controller X550
                                                         Connection Name: Ethernet 2
                                                         Status:          Media disconnected
                                                   [02]: Intel(R) Ethernet Controller X550
                                                         Connection Name: Ethernet 3
                                                         DHCP Enabled:    Yes
                                                         DHCP Server:     N/A
                                                         IP address(es)
                                                   [03]: Intel(R) Ethernet Network Adapter E810-C-Q2
                                                         Connection Name: Ethernet 4
                                                         Status:          Media disconnected
                                                   [04]: Intel(R) Ethernet Network Adapter E810-C-Q2
                                                         Connection Name: Ethernet 5
                                                         DHCP Enabled:    No
                                                         IP address(es)
                                                   [05]: Hyper-V Virtual Ethernet Adapter
                                                         Connection Name: vEthernet (managementvSwitch)
                                                         DHCP Enabled:    Yes
                                                         DHCP Server:     10.100.100.100
                                                         IP address(es)
                                                         [01]: 10.10.10.10
                                                         [02]: fe80::eda6:dead:beef:beef
                                                   [06]: Hyper-V Virtual Ethernet Adapter
                                                         Connection Name: vEthernet (TEST_SWITCH5)
                                                         DHCP Enabled:    No
                                                         IP address(es)
                                                         [01]: 1.1.1.1
                                                         [02]: fe80::2b4f:beef:dead:dead
                        Hyper-V Requirements:      A hypervisor has been detected. Features required for Hyper-V will
                        not be displayed.


                        """
        )
        expected_info = SystemInfo(
            host_name="WINDOWS-2019",
            os_name="Microsoft Windows Server 2019 Standard",
            os_version="10.0.17763 N/A Build 17763",
            kernel_version="17763",
            system_boot_time="4/4/2023, 2:40:55 PM",
            system_manufacturer="Intel Corporation",
            system_model="S2600BPB",
            system_bitness=OSBitness.OS_64BIT,
            bios_version="Intel Corporation SE5C620.86B.02.01.0012.070720200218, 7/7/2020",
            total_memory="130,771 MB",
            architecture_info="x86_64",
        )

        exec_command_mock = mocker.Mock()
        exec_command_mock.return_value = ConnectionCompletedProcess(args="args", return_code=0, stdout=mock_output)
        conn.execute_command = exec_command_mock

        mocker.patch("mfd_connect.util.rpc_system_info_utils._get_architecture_info_windows", return_value="x86_64")

        assert _get_system_info_windows(connection=conn) == expected_info

    # Linux
    def test__get_hostname_linux(self, conn, mocker):
        expected_hostname = "Stormtrooper"
        exec_command_mock = mocker.Mock()
        exec_command_mock.return_value = ConnectionCompletedProcess(
            args="args", return_code=0, stdout=expected_hostname
        )
        conn.execute_command = exec_command_mock

        assert _get_hostname_linux(connection=conn) == expected_hostname

    def test__get_os_name_linux(self, conn, mocker):
        expected_os_name = "Red Hat Enterprise Linux Server"
        mock_output = dedent(
            """
            NAME="Red Hat Enterprise Linux Server"
            VERSION="7.9 (Maipo)"
            ID="rhel"
            ID_LIKE="fedora"
            VARIANT="Server"
            VARIANT_ID="server"
            VERSION_ID="7.9"
            PRETTY_NAME="Red Hat Enterprise Linux Server 7.9 (Maipo)"
            ANSI_COLOR="0;31"
            CPE_NAME="cpe:/o:redhat:enterprise_linux:7.9:GA:server"
            HOME_URL="https://www.redhat.com/"
            BUG_REPORT_URL="https://bugzilla.redhat.com/"

            REDHAT_BUGZILLA_PRODUCT="Red Hat Enterprise Linux 7"
            REDHAT_BUGZILLA_PRODUCT_VERSION=7.9
            REDHAT_SUPPORT_PRODUCT="Red Hat Enterprise Linux"
            REDHAT_SUPPORT_PRODUCT_VERSION="7.9"
        """
        )
        exec_command_mock = mocker.Mock()
        exec_command_mock.return_value = ConnectionCompletedProcess(args="args", return_code=0, stdout=mock_output)
        conn.execute_command = exec_command_mock

        assert _get_os_name_linux(connection=conn) == expected_os_name

    def test__get_os_version_linux(self, conn, mocker):
        expected_os_version = "#1 SMP Tue Jul 26 14:15:37 UTC 2022"
        mock_output = "#1 SMP Tue Jul 26 14:15:37 UTC 2022  "
        exec_command_mock = mocker.Mock()
        exec_command_mock.return_value = ConnectionCompletedProcess(args="args", return_code=0, stdout=mock_output)
        conn.execute_command = exec_command_mock

        assert _get_os_version_linux(connection=conn) == expected_os_version

    def test_get_kernel_version_linux(self, conn, mocker):
        kernel_version = "3.10.0-1160.76.1.el7.x86_64"
        mock_output = "3.10.0-1160.76.1.el7.x86_64  "
        exec_command_mock = mocker.Mock()
        exec_command_mock.return_value = ConnectionCompletedProcess(args="args", return_code=0, stdout=mock_output)
        conn.execute_command = exec_command_mock

        assert get_kernel_version_linux(connection=conn) == kernel_version

    def test_get_os_version_mellanox(self, conn, mocker):
        system_version = "3.6.3200"
        mock_output = dedent("""\
        Product name:      MLNX-OS
        Product release:   3.6.3200
        Build ID:          #1-dev
        Build date:        2017-03-09 17:55:58
        Target arch:       x86_64
        Target hw:         x86_64
        Built by:          jenkins@e3f42965d5ee
        Version summary:   X86_64 3.6.3200 2017-03-09 17:55:58 x86_64""")
        exec_command_mock = mocker.Mock()
        exec_command_mock.return_value = ConnectionCompletedProcess(args="args", return_code=0, stdout=mock_output)
        conn.execute_command = exec_command_mock

        assert get_os_version_mellanox(connection=conn) == system_version

    def test__get_system_boot_time_linux(self, conn, mocker):
        expected_boot_time = "14:49:49 up 138 days"
        mock_output = " 14:49:49 up 138 days, 20:39,  1 user,  load average: 0.10, 0.11, 0.12"
        exec_command_mock = mocker.Mock()
        exec_command_mock.return_value = ConnectionCompletedProcess(args="args", return_code=0, stdout=mock_output)
        conn.execute_command = exec_command_mock

        assert _get_system_boot_time_linux(connection=conn) == expected_boot_time

    def test__get_system_manufacturer_and_model_linux(self, conn, mocker):
        expected_system_manufacturer = "Intel Corporation"
        expected_system_model = "S2600BPB"
        mock_output = dedent(
            """# dmidecode 3.5
                # SMBIOS entry point at 0x67f2a000
                Found SMBIOS entry point in EFI, reading table from /dev/mem.
                SMBIOS 2.8 present.

                Handle 0x0025, DMI type 1, 27 bytes
                System Information
                        Manufacturer: Intel Corporation
                        Product Name: S2600BPB
                        Version: ....................
                        Serial Number: WO223344L11S336-B
                        UUID: bb316164-dddd-eeee-aaaa-a4bf0aaaa78a
                        Wake-up Type: Power Switch
                        SKU Number: SKU Number
                        Family: Family

                Handle 0x0032, DMI type 32, 11 bytes
                System Boot Information
                        Status: No errors detected


                        """
        )
        exec_command_mock = mocker.Mock()
        exec_command_mock.return_value = ConnectionCompletedProcess(args="args", return_code=0, stdout=mock_output)
        conn.execute_command = exec_command_mock

        assert _get_system_manufacturer_and_model_linux(connection=conn) == (
            expected_system_manufacturer,
            expected_system_model,
        )

    def test__get_system_manufacturer_and_model_esxi(self, conn, mocker):
        expected_system_manufacturer = "Intel Corporation"
        expected_system_model = "S2600GZ"
        output_mock = dedent(
            """Platform Information
           UUID: 0x6 0x4d 0x15 0x53 0x6a 0xf0 0xe1 0x11 0xa6 0xcf 0x0 0x1e 0x67 0x62 0xca 0xa
           Product Name: S2600GZ
           Vendor Name: Intel Corporation
           Serial Number: ............
           Enclosure Serial Number: ..................
           BIOS Asset Tag: ....................
           IPMI Supported: true

                """
        )
        exec_command_mock = mocker.Mock()
        exec_command_mock.return_value = ConnectionCompletedProcess(args="args", return_code=0, stdout=output_mock)
        conn.execute_command = exec_command_mock

        assert _get_system_manufacturer_and_model_esxi(connection=conn) == (
            expected_system_manufacturer,
            expected_system_model,
        )

    def test__get_bios_version_linux(self, conn, mocker):
        expected_bios_version = "SE5C620.86B.02.01.0012.070720200218"
        mock_output = dedent(
            """# dmidecode 3.5
                # SMBIOS entry point at 0x67f2a000
                Found SMBIOS entry point in EFI, reading table from /dev/mem.
                SMBIOS 2.8 present.

                Handle 0x0024, DMI type 0, 24 bytes
                BIOS Information
                        Vendor: Intel Corporation
                        Version: SE5C620.86B.02.01.0012.070720200218
                        Release Date: 07/07/2020
                        Address: 0xF0000
                        Runtime Size: 64 kB
                        ROM Size: 4 MB
                        Characteristics:
                                PCI is supported
                                PNP is supported
                                BIOS is upgradeable
                                BIOS shadowing is allowed
                                Boot from CD is supported
                                Selectable boot is supported
                                EDD is supported
                                5.25"/1.2 MB floppy services are supported (int 13h)
                                3.5"/720 kB floppy services are supported (int 13h)
                                3.5"/2.88 MB floppy services are supported (int 13h)
                                Print screen service is supported (int 5h)
                                8042 keyboard services are supported (int 9h)
                                Serial services are supported (int 14h)
                                Printer services are supported (int 17h)
                                CGA/mono video services are supported (int 10h)
                                ACPI is supported
                                USB legacy is supported
                                LS-120 boot is supported
                                ATAPI Zip drive boot is supported
                                BIOS boot specification is supported
                                Function key-initiated network boot is supported
                                Targeted content distribution is supported
                                UEFI is supported
                        BIOS Revision: 0.0
                        Firmware Revision: 0.0

                """
        )
        exec_command_mock = mocker.Mock()
        exec_command_mock.return_value = ConnectionCompletedProcess(args="args", return_code=0, stdout=mock_output)
        conn.execute_command = exec_command_mock

        assert _get_bios_version_linux(connection=conn) == expected_bios_version

    def test__get_bios_version_esxi(self, conn, mocker):
        mock_output = dedent(
            """

            biosVersion  =  "SE5C600.86B.02.06.0007.082420181029" ,


        """
        )

        expected_version = "SE5C600.86B.02.06.0007.082420181029"
        exec_command_mocker = mocker.Mock()
        exec_command_mocker.return_value = ConnectionCompletedProcess(args="args", return_code=0, stdout=mock_output)
        conn.execute_command = exec_command_mocker

        assert _get_bios_version_esxi(connection=conn) == expected_version

    def test__get_total_memory_linux(self, conn, mocker):
        expected_total_mem = "131749136 kB"
        mock_output = dedent(
            """MemTotal:       131749136 kB
                    MemFree:        107485660 kB
                    MemAvailable:   124748136 kB
                    Buffers:               0 kB
                    Cached:         14404164 kB
                    SwapCached:            0 kB
                    Active:         12268232 kB
                    Inactive:        2327328 kB
                    Active(anon):    2696416 kB
                    Inactive(anon):  1667548 kB
                    Active(file):    9571816 kB
                    Inactive(file):   659780 kB
                    Unevictable:           0 kB
                    Mlocked:               0 kB
                    SwapTotal:             0 kB
                    SwapFree:              0 kB
                    Dirty:                28 kB
                    Writeback:           128 kB
                    AnonPages:        192148 kB
                    Mapped:           104184 kB
                    Shmem:           4172524 kB
                    Slab:            8022544 kB
                    SReclaimable:    7656912 kB
                    SUnreclaim:       365632 kB
                    KernelStack:       19504 kB
                    PageTables:        10048 kB
                    NFS_Unstable:         28 kB
                    Bounce:                0 kB
                    WritebackTmp:          0 kB
                    CommitLimit:    65874568 kB
                    Committed_AS:    5160540 kB
                    VmallocTotal:   34359738367 kB
                    VmallocUsed:      648080 kB
                    VmallocChunk:   34291812348 kB
                    Percpu:           103680 kB
                    HardwareCorrupted:     0 kB
                    AnonHugePages:     55296 kB
                    CmaTotal:              0 kB
                    CmaFree:               0 kB
                    HugePages_Total:       0
                    HugePages_Free:        0
                    HugePages_Rsvd:        0
                    HugePages_Surp:        0
                    Hugepagesize:       2048 kB
                    DirectMap4k:      297940 kB
                    DirectMap2M:     6733824 kB
                    DirectMap1G:    128974848 kB

                            """
        )
        exec_command_mock = mocker.Mock()
        exec_command_mock.return_value = ConnectionCompletedProcess(args="args", return_code=0, stdout=mock_output)
        conn.execute_command = exec_command_mock

        assert _get_total_memory_linux(connection=conn) == expected_total_mem

    def test__get_os_name_freebsd(self, conn, mocker):
        expected_hostname = "Stormtrooper"
        command_mock = "  Stormtrooper  "
        exec_command_mock = mocker.Mock()
        exec_command_mock.return_value = ConnectionCompletedProcess(args="args", return_code=0, stdout=command_mock)
        conn.execute_command = exec_command_mock

        assert _get_os_name_freebsd(connection=conn) == expected_hostname

    def test__get_total_memory_freebsd(self, conn, mocker):
        expected_memory = "137084030976"
        command_mock = " hw.physmem: 137084030976 "
        exec_command_mock = mocker.Mock()
        exec_command_mock.return_value = ConnectionCompletedProcess(args="args", return_code=0, stdout=command_mock)
        conn.execute_command = exec_command_mock

        assert _get_total_memory_freebsd(connection=conn) == expected_memory

    def test__get_total_memory_esxi(self, conn, mocker):
        expected_memory = "137355427840 Bytes"
        command_mock = dedent(
            """   Physical Memory: 137355427840 Bytes
                                       Reliable Memory: 0 Bytes
                                       NUMA Node Count: 2

        """
        )
        exec_command_mock = mocker.Mock()
        exec_command_mock.return_value = ConnectionCompletedProcess(args="args", return_code=0, stdout=command_mock)
        conn.execute_command = exec_command_mock

        assert _get_total_memory_esxi(connection=conn) == expected_memory

    def test__get_system_info_freebsd(self, conn, mocker):
        mocker.patch("mfd_connect.util.rpc_system_info_utils._get_hostname_linux", return_value="Five")
        mocker.patch("mfd_connect.util.rpc_system_info_utils._get_os_name_freebsd", return_value="little")
        mocker.patch("mfd_connect.util.rpc_system_info_utils._get_os_version_linux", return_value="ducks")
        mocker.patch("mfd_connect.util.rpc_system_info_utils.get_kernel_version_linux", return_value="went")
        mocker.patch("mfd_connect.util.rpc_system_info_utils._get_system_boot_time_linux", return_value="out")
        mocker.patch(
            "mfd_connect.util.rpc_system_info_utils._get_system_manufacturer_and_model_linux",
            return_value=("one", "day"),
        )
        mocker.patch("mfd_connect.util.rpc_system_info_utils._get_bios_version_linux", return_value="the")
        mocker.patch("mfd_connect.util.rpc_system_info_utils._get_total_memory_freebsd", return_value="hills")
        mocker.patch("mfd_connect.util.rpc_system_info_utils._get_architecture_info_posix", return_value="and")

        conn.get_os_bitness = mocker.Mock(return_value="Over")
        expected_system = SystemInfo(
            host_name="Five",
            os_name="little",
            os_version="ducks",
            kernel_version="went",
            system_boot_time="out",
            system_manufacturer="one",
            system_model="day",
            system_bitness="Over",
            bios_version="the",
            total_memory="hills",
            architecture_info="and",
        )
        assert _get_system_info_freebsd(connection=conn) == expected_system

    def test__get_system_info_esxi(self, conn, mocker):
        mocker.patch("mfd_connect.util.rpc_system_info_utils._get_hostname_linux", return_value="Five")
        mocker.patch("mfd_connect.util.rpc_system_info_utils._get_os_name_freebsd", return_value="little")
        mocker.patch("mfd_connect.util.rpc_system_info_utils._get_os_version_linux", return_value="ducks")
        mocker.patch("mfd_connect.util.rpc_system_info_utils.get_kernel_version_linux", return_value="went")
        mocker.patch("mfd_connect.util.rpc_system_info_utils._get_system_boot_time_linux", return_value="out")
        mocker.patch(
            "mfd_connect.util.rpc_system_info_utils._get_system_manufacturer_and_model_esxi",
            return_value=("one", "day"),
        )
        mocker.patch("mfd_connect.util.rpc_system_info_utils._get_bios_version_esxi", return_value="the")
        mocker.patch("mfd_connect.util.rpc_system_info_utils._get_total_memory_esxi", return_value="hills")
        mocker.patch("mfd_connect.util.rpc_system_info_utils._get_architecture_info_posix", return_value="and")
        conn.get_os_bitness = mocker.Mock(return_value="Over")
        expected_system = SystemInfo(
            host_name="Five",
            os_name="little",
            os_version="ducks",
            kernel_version="went",
            system_boot_time="out",
            system_manufacturer="one",
            system_model="day",
            system_bitness="Over",
            bios_version="the",
            total_memory="hills",
            architecture_info="and",
        )

        assert _get_system_info_esxi(connection=conn) == expected_system

    def test__get_system_info_linux(self, conn, mocker):
        mocker.patch("mfd_connect.util.rpc_system_info_utils._get_hostname_linux", return_value="Eeny")
        mocker.patch("mfd_connect.util.rpc_system_info_utils._get_os_name_linux", return_value="meeny")
        mocker.patch("mfd_connect.util.rpc_system_info_utils._get_os_version_linux", return_value="miny")
        mocker.patch("mfd_connect.util.rpc_system_info_utils.get_kernel_version_linux", return_value="moe")
        mocker.patch("mfd_connect.util.rpc_system_info_utils._get_system_boot_time_linux", return_value="catch")
        mocker.patch(
            "mfd_connect.util.rpc_system_info_utils._get_system_manufacturer_and_model_linux",
            return_value=("a", "tiger"),
        )
        mocker.patch("mfd_connect.util.rpc_system_info_utils._get_bios_version_linux", return_value="the")
        mocker.patch("mfd_connect.util.rpc_system_info_utils._get_total_memory_linux", return_value="toe")
        mocker.patch("mfd_connect.util.rpc_system_info_utils._get_architecture_info_posix", return_value="!")
        conn.get_os_bitness = mocker.Mock(return_value="by")
        expected_system = SystemInfo(
            host_name="Eeny",
            os_name="meeny",
            os_version="miny",
            kernel_version="moe",
            system_boot_time="catch",
            system_manufacturer="a",
            system_model="tiger",
            system_bitness="by",
            bios_version="the",
            total_memory="toe",
            architecture_info="!",
        )

        assert _get_system_info_linux(connection=conn) == expected_system

    def test__get_system_info_linux_yocto(self, conn, mocker):
        mocker.patch("mfd_connect.util.rpc_system_info_utils._get_hostname_linux", return_value="Eeny")
        mocker.patch(
            "mfd_connect.util.rpc_system_info_utils._get_os_name_linux",
            side_effect=ConnectionCalledProcessError(cmd="", returncode=1),
        )
        mocker.patch("mfd_connect.util.rpc_system_info_utils._get_os_version_linux", return_value="miny")
        mocker.patch("mfd_connect.util.rpc_system_info_utils.get_kernel_version_linux", return_value="moe")
        mocker.patch("mfd_connect.util.rpc_system_info_utils._get_system_boot_time_linux", return_value="catch")
        mocker.patch(
            "mfd_connect.util.rpc_system_info_utils._get_system_manufacturer_and_model_linux",
            side_effect=ConnectionCalledProcessError(cmd="", returncode=1),
        )
        mocker.patch(
            "mfd_connect.util.rpc_system_info_utils._get_bios_version_linux",
            side_effect=ConnectionCalledProcessError(cmd="", returncode=1),
        )
        mocker.patch("mfd_connect.util.rpc_system_info_utils._get_total_memory_linux", return_value="toe")
        mocker.patch("mfd_connect.util.rpc_system_info_utils._get_architecture_info_posix", return_value="!")
        conn.get_os_bitness = mocker.Mock(return_value="by")
        expected_system = SystemInfo(
            host_name="Eeny",
            os_name="N/A",
            os_version="miny",
            kernel_version="moe",
            system_boot_time="catch",
            system_manufacturer="N/A",
            system_model="N/A",
            system_bitness="by",
            bios_version="N/A",
            total_memory="toe",
            architecture_info="!",
        )

        assert _get_system_info_linux(connection=conn) == expected_system

    def test_is_current_kernel_version_equal_or_higher_equal(self, conn, mocker):
        mock_get_kernel_version_linux = mocker.patch("mfd_connect.util.rpc_system_info_utils.get_kernel_version_linux")
        mock_get_kernel_version_linux.return_value = "5.10.0-8-amd64"
        assert is_current_kernel_version_equal_or_higher(connection=conn, version="5.9.0-8-amd64")

    def test_is_current_kernel_version_equal_or_higher_lower(self, conn, mocker):
        mock_get_kernel_version_linux = mocker.patch("mfd_connect.util.rpc_system_info_utils.get_kernel_version_linux")
        mock_get_kernel_version_linux.return_value = "5.10.0-8-amd64"
        assert is_current_kernel_version_equal_or_higher(connection=conn, version="5.9.0-8-amd64")

    def test_is_current_kernel_version_equal_or_higher_higher(self, conn, mocker):
        mock_get_kernel_version_linux = mocker.patch("mfd_connect.util.rpc_system_info_utils.get_kernel_version_linux")
        mock_get_kernel_version_linux.return_value = "4.18.0-513.9.1.el8_9.x86_64"
        assert not is_current_kernel_version_equal_or_higher(connection=conn, version="4.19.0-513.9.1.el8_9.x86_64")

    def test_is_current_kernel_version_equal_or_higher_short_version(self, conn, mocker):
        mock_get_kernel_version_linux = mocker.patch("mfd_connect.util.rpc_system_info_utils.get_kernel_version_linux")
        mock_get_kernel_version_linux.return_value = "4.18.0-513.9.1.el8_9.x86_64"
        assert not is_current_kernel_version_equal_or_higher(connection=conn, version="4.19")
