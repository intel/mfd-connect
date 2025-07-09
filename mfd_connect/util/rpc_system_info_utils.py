# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""RPC System Info Helper Methods."""

import re
from typing import TYPE_CHECKING
from typing import Tuple, Dict, Callable

from mfd_typing.os_values import SystemInfo, OSBitness, OSName

from mfd_connect.exceptions import ConnectionCalledProcessError
from mfd_connect.util.powershell_utils import parse_powershell_list

if TYPE_CHECKING:
    from mfd_connect import Connection


DEFAULT_RPYC_6_0_0_RESPONDER_PORT = 18816  # used for rpyc ver. 6+


def _get_architecture_info_windows(connection: "Connection") -> str:
    """
    Get architecture info on Windows.

    :param connection: Connection to host
    :return: Architecture of machine, like amd64 or x86_64
    """
    return connection.execute_command("echo %PROCESSOR_ARCHITECTURE%", shell=True).stdout.strip()


def _get_system_info_windows(connection: "Connection") -> SystemInfo:
    """Get SystemInfo for Windows Host.

    :param connection: RPC Connection to host
    :return: SystemInfo structure
    """
    res = connection.execute_command(command="systeminfo", expected_return_codes={0})

    host_name_regex = r"^Host Name:\s*(?P<host_name>.+)"
    os_name_regex = r"^OS Name:\s*(?P<os_name>.+)"
    os_version_regex = r"^OS Version:\s*(?P<os_version>.+)"
    kernel_version_regex = r"^OS Version:\s*\d+.\d+.(?P<kernel_version>\d+)"
    system_boot_time_regex: str = r"^System Boot Time:\s*(?P<system_boot_time>.+)"  # 4/4/2023, 2:40:55 PM
    system_manufacturer_regex: str = r"^System Manufacturer:\s*(?P<system_manufacturer>.+)"  # Intel Corporation
    system_model_regex: str = r"^System Model:\s*(?P<system_model>.+)"  # S2600BPB
    system_bitness_regex: str = r"^System Type:\s*(?P<system_bitness>.+)"  # x64-based PC -> convert to OSBitness
    bios_version_regex: str = (
        r"^BIOS Version:\s*(?P<bios_version>.+)"  # Intel Corporation SE5C620.86B.02.01.0012.070720200218, 7/7/2020
    )
    total_memory_regex: str = r"^Total Physical Memory:\s*(?P<total_memory>.+)"  # 130,771 MB

    patterns = [
        host_name_regex,
        os_name_regex,
        os_version_regex,
        kernel_version_regex,
        system_boot_time_regex,
        system_manufacturer_regex,
        system_model_regex,
        system_bitness_regex,
        bios_version_regex,
        total_memory_regex,
    ]

    matches = {}

    for pattern in patterns:
        m = re.search(pattern=pattern, string=res.stdout, flags=re.MULTILINE)
        if m:
            matches.update(m.groupdict())

    system_bitness = matches.get("system_bitness", None)

    if not system_bitness:
        raise OSError("Can't parse OS Bitness")
    system_bitness = OSBitness.OS_64BIT if "64" in system_bitness else OSBitness.OS_32BIT
    matches["system_bitness"] = system_bitness
    matches["architecture_info"] = _get_architecture_info_windows(connection)
    return SystemInfo(**matches)


def _get_hostname_linux(connection: "Connection") -> str:
    """Get hostname of Linux Host (uname -n).

    :param connection: RPC Connection to host
    :return: Hostname of remote Host
    """
    return connection.execute_command("uname -n").stdout.strip()


def _get_os_name_linux(connection: "Connection") -> str:
    """Get user-friendly OS name of remote Linux Host (cat /etc/os-release).

    :param connection: RPC Connection to host
    :return: User-friendly OS Name of remote Host
    """
    os_name_pattern = r"NAME\=\"(?P<os_name>.*)\"$"

    res = connection.execute_command("cat /etc/os-release")
    return re.search(pattern=os_name_pattern, string=res.stdout, flags=re.MULTILINE).group("os_name")


def _get_os_name_freebsd(connection: "Connection") -> str:
    """Get user-friendly OS name of remote FreeBSD Host (uname -o).

    :param connection: RPC Connection to host
    :return: User-friendly OS Name of remote Host
    """
    return connection.execute_command("uname -o").stdout.strip()


def _get_os_version_linux(connection: "Connection") -> str:
    """Get OS version of remote Linux Host (uname -v).

    :param connection: RPC Connection to host
    :return: OS version of remote Host
    """
    return connection.execute_command("uname -v").stdout.strip()


def get_kernel_version_linux(connection: "Connection") -> str:
    """Get Kernel version of remote Linux Host (uname -r).

    :param connection: RPC Connection to host
    :return: OS version of remote Host
    """
    return connection.execute_command("uname -r").stdout.strip()


def get_os_version_mellanox(connection: "Connection") -> str:
    """Get OS version of remote Mellanox switch Host (show version).

    :param connection: RPC Connection to host
    :return: OS version of remote Host
    """
    version_pattern = r"Product release:\s+(?P<version>.+)"
    system_details = connection.execute_command("show version").stdout.strip()
    return re.search(pattern=version_pattern, string=system_details, flags=re.MULTILINE).group("version")


def _get_system_boot_time_linux(connection: "Connection") -> str:
    """Get system boot time of remote Linux Host (uptime).

    :param connection: RPC Connection to host
    :return: Uptime of remote Host
    """
    return connection.execute_command("uptime").stdout.strip().split(",")[0]


def _get_system_manufacturer_and_model_linux(connection: "Connection") -> Tuple[str, str]:
    """Get System Manufacturer and Model of remote Linux Host (dmidecode -t system).

    :param connection: RPC Connection to host
    :return: Tuple of system manufacturer & system model
    """
    system_manufacturer_pattern = r"Manufacturer:\s+(?P<system_manufacturer>.+)"
    system_model_pattern = r"Product Name:\s+(?P<system_model>.+)"

    system_details = connection.execute_command("dmidecode -t system").stdout.strip()
    system_manufacturer = re.search(
        pattern=system_manufacturer_pattern, string=system_details, flags=re.MULTILINE
    ).group("system_manufacturer")
    system_model = re.search(pattern=system_model_pattern, string=system_details, flags=re.MULTILINE).group(
        "system_model"
    )
    return system_manufacturer, system_model


def _get_system_manufacturer_and_model_esxi(connection: "Connection") -> Tuple[str, str]:
    """Get System Manufacturer and Model of remote ESXi Host (esxcli hardware platform get).

    :param connection: RPC Connection to host
    :return: Tuple of system manufacturer & system model
    """
    system_manufacturer_pattern = r"Vendor Name:\s+(?P<system_manufacturer>.+)"
    system_model_pattern = r"Product Name:\s+(?P<system_model>.+)"

    system_details = connection.execute_command("esxcli hardware platform get").stdout.strip()
    system_manufacturer = re.search(
        pattern=system_manufacturer_pattern, string=system_details, flags=re.MULTILINE
    ).group("system_manufacturer")
    system_model = re.search(pattern=system_model_pattern, string=system_details, flags=re.MULTILINE).group(
        "system_model"
    )
    return system_manufacturer, system_model


def _get_bios_version_linux(connection: "Connection") -> str:
    """Get BIOS version of remote Linux Host (dmidecode -t bios).

    :param connection: RPC Connection to host
    :return: BIOS version of remote host
    """
    bios_version_pattern = r"Version:\s+(?P<bios_version>.+)"
    bios_details = connection.execute_command("dmidecode -t bios").stdout.strip()
    return re.search(pattern=bios_version_pattern, string=bios_details, flags=re.MULTILINE).group("bios_version")


def _get_bios_version_esxi(connection: "Connection") -> str:
    """Get BIOS version of remote ESXi Host (vim-cmd hostsvc/hosthardware).

    :param connection: RPC Connection to host
    :return: BIOS version of remote host
    """
    bios_version_pattern = r"biosVersion\s+=\s+\"(?P<bios_version>.+)\""
    bios_details = connection.execute_command(
        "vim-cmd hostsvc/hosthardware | grep biosVersion", shell=True
    ).stdout.strip()
    return re.search(pattern=bios_version_pattern, string=bios_details, flags=re.MULTILINE).group("bios_version")


def _get_total_memory_linux(connection: "Connection") -> str:
    """Get physical total memory of remote Linux Host (cat /proc/meminfo).

    :param connection: RPC Connection to host
    :return: Total memory of remote host
    """
    total_memory_pattern = r"MemTotal:\s+(?P<total_memory>.+)"

    memory_details = connection.execute_command("cat /proc/meminfo").stdout.strip()
    return re.search(pattern=total_memory_pattern, string=memory_details, flags=re.MULTILINE).group("total_memory")


def _get_total_memory_freebsd(connection: "Connection") -> str:
    """Get physical total memory of remote FreeBSD Host (sysctl hw.physmem).

    :param connection: RPC Connection to host
    :return: Total memory of remote host
    """
    return connection.execute_command("sysctl hw.physmem").stdout.strip().split(":")[1].strip()


def _get_total_memory_esxi(connection: "Connection") -> str:
    """Get physical total memory of remote ESXi Host (esxcli hardware memory get).

    :param connection: RPC Connection to host
    :return: Total memory of remote host
    """
    total_memory_pattern = r"Physical Memory:\s+(?P<total_memory>.+)"

    memory_details = connection.execute_command("esxcli hardware memory get").stdout.strip()
    return re.search(pattern=total_memory_pattern, string=memory_details, flags=re.MULTILINE).group("total_memory")


def _get_architecture_info_posix(connection: "Connection") -> str:
    """
    Get architecture info on Posix.

    :param connection: Connection to host
    :return: Architecture of machine, like amd64 or x86_64
    """
    return connection.execute_command("uname -m").stdout.strip()


def _get_system_info_linux(connection: "Connection") -> SystemInfo:
    """Get SystemInfo for Linux Host.

    :param connection: RPC Connection to host
    :return: SystemInfo dataclass
    """
    host_name = _get_hostname_linux(connection)
    # Try/except blocks are for case OS does not support used commands like Yocto
    try:
        os_name = _get_os_name_linux(connection)
    except ConnectionCalledProcessError:
        os_name = "N/A"
    os_version = _get_os_version_linux(connection)
    kernel_version = get_kernel_version_linux(connection)
    system_boot_time = _get_system_boot_time_linux(connection)
    try:
        system_manufacturer, system_model = _get_system_manufacturer_and_model_linux(connection)
    except ConnectionCalledProcessError:
        system_manufacturer = system_model = "N/A"
    system_bitness = connection.get_os_bitness()
    try:
        bios_version = _get_bios_version_linux(connection)
    except ConnectionCalledProcessError:
        bios_version = "N/A"
    total_memory = _get_total_memory_linux(connection)
    architecture_info = _get_architecture_info_posix(connection)
    return SystemInfo(
        host_name=host_name,
        os_name=os_name,
        os_version=os_version,
        kernel_version=kernel_version,
        system_boot_time=system_boot_time,
        system_manufacturer=system_manufacturer,
        system_model=system_model,
        system_bitness=system_bitness,
        bios_version=bios_version,
        total_memory=total_memory,
        architecture_info=architecture_info,
    )


def _get_system_info_freebsd(connection: "Connection") -> SystemInfo:
    """Get SystemInfo for FreeBSD Host.

    :param connection: RPC Connection to host
    :return: SystemInfo dataclass
    """
    host_name = _get_hostname_linux(connection)  # uname -n # Marilyn-243-154
    os_name = _get_os_name_freebsd(connection)  # uname -o # FreeBSD
    os_version = _get_os_version_linux(connection)  # uname -v # FreeBSD 13.1-RELEASE VALIDATION
    kernel_version = get_kernel_version_linux(connection)  # uname -r  # 13.1-RELEASE
    system_boot_time = _get_system_boot_time_linux(
        connection
    )  # uptime # 11:15AM  up  1:02, 1 user, load averages: 0.00, 0.00, 0.00
    system_manufacturer, system_model = _get_system_manufacturer_and_model_linux(
        connection
    )  # dmidecode -t system # Manufacturer: Intel Corporation
    system_bitness = connection.get_os_bitness()
    bios_version = _get_bios_version_linux(
        connection
    )  # dmidecode -t bios   # Version: SE5C620.86B.02.01.0012.070720200218
    total_memory = _get_total_memory_freebsd(connection)  # sysctl hw.physmem  # hw.physmem: 137084030976
    architecture_info = _get_architecture_info_posix(connection)  # uname -m

    return SystemInfo(
        host_name=host_name,
        os_name=os_name,
        os_version=os_version,
        kernel_version=kernel_version,
        system_boot_time=system_boot_time,
        system_manufacturer=system_manufacturer,
        system_model=system_model,
        system_bitness=system_bitness,
        bios_version=bios_version,
        total_memory=total_memory,
        architecture_info=architecture_info,
    )


def _get_system_info_esxi(connection: "Connection") -> SystemInfo:
    """Get SystemInfo for ESXi Host.

    :param connection: RPC Connection to host
    :return: SystemInfo dataclass
    """
    host_name = _get_hostname_linux(connection)  # uname -n
    os_name = _get_os_name_freebsd(connection)  # uname -o # ESXi
    os_version = _get_os_version_linux(connection)  # uname -v # #1 SMP Release build-16850804 Sep  4 2020 11:20:43
    kernel_version = get_kernel_version_linux(connection)  # uname -r  # 7.0.1
    system_boot_time = _get_system_boot_time_linux(
        connection
    )  # uptime # 11:11:13 up 6 days, 19:40:32, load average: 0.05, 0.04, 0.05
    system_manufacturer, system_model = _get_system_manufacturer_and_model_esxi(
        connection
    )  # esxcli hardware platform get
    system_bitness = connection.get_os_bitness()
    bios_version = _get_bios_version_esxi(connection)
    total_memory = _get_total_memory_esxi(
        connection
    )  # esxcli hardware memory get    #   Physical Memory: 137355427840 Bytes
    architecture_info = _get_architecture_info_posix(connection)  # uname -m

    return SystemInfo(
        host_name=host_name,
        os_name=os_name,
        os_version=os_version,
        kernel_version=kernel_version,
        system_boot_time=system_boot_time,
        system_manufacturer=system_manufacturer,
        system_model=system_model,
        system_bitness=system_bitness,
        bios_version=bios_version,
        total_memory=total_memory,
        architecture_info=architecture_info,
    )


def _get_os_version_windows(connection: "Connection") -> str:
    """Get version."""
    # return connection.execute_command("cmd 'exit'").stdout.splitlines()[0]  # on LocalConnection hangs, to be checked
    extend_buffer_size_command = (
        "$host.UI.RawUI.BufferSize = new-object System.Management.Automation.Host.Size(512,3000);"
    )
    command = r"Get-ItemProperty -path \"HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\" | fl"
    command = f'powershell.exe -OutPutFormat Text -nologo -noninteractive "{extend_buffer_size_command}{command}"'
    os_data = parse_powershell_list(connection.execute_command(command).stdout)[0]
    return f"{os_data.get('CurrentBuild', 'N/A')} ({os_data.get('DisplayVersion', 'N/A')})"


def _get_os_version_linux_etc_os_release(connection: "Connection") -> str:
    """Get version."""
    version_pattern = r"VERSION_ID=(?P<version>.+)"
    distro_pattern = r"NAME=(?P<distro>.+)"
    output = connection.execute_command("cat /etc/os-release", shell=True).stdout
    version = re.search(version_pattern, output).group("version").strip('"')
    distro = re.search(distro_pattern, output).group("distro").strip('"')
    return f"{distro} {version}"


def get_os_name_version(connection: "Connection") -> (str, str):
    """Get OS name and version."""
    os_method: Dict[OSName, Callable] = {
        OSName.WINDOWS: _get_os_version_windows,
        OSName.LINUX: _get_os_version_linux_etc_os_release,
        OSName.FREEBSD: get_kernel_version_linux,
        OSName.ESXI: get_kernel_version_linux,
        OSName.MELLANOX: get_os_version_mellanox,
    }
    os_name = connection.get_os_name()
    try:
        return os_name.value, os_method.get(os_name)(connection)
    except Exception:
        return os_name.value, "N/A"


def is_current_kernel_version_equal_or_higher(connection: "Connection", version: str) -> bool:
    """
    Check whether current kernel version is higher than provided one.

    :param connection: RPC Connection to host
    :param version: version to compare with
    :return: True if current kernel version is equal or higher
             False if current kernel version is lower
    """
    kernel_version = get_kernel_version_linux(connection=connection)
    version = list(map(int, version.split("-")[0].split(".")))
    for kernel_separator in ["-", "_"]:
        try:
            current_kernel_version = list(map(int, kernel_version.split(kernel_separator)[0].split(".")))
            break
        except ValueError:
            pass
    else:
        raise RuntimeError(f"Wrong kernel version: {kernel_version}")

    return current_kernel_version >= version
