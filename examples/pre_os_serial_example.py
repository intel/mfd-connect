# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT

import logging
from time import sleep
from mfd_connect import SerialConnection, SSHConnection
from mfd_connect.util import EFI_SHELL_PROMPT_REGEX, MEV_IMC_SERIAL_BAUDRATE, SerialKeyCode
from mfd_common_libs import log_levels, add_logging_level

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
add_logging_level(level_name="MODULE_DEBUG", level_value=log_levels.MODULE_DEBUG)
add_logging_level(level_name="CMD", level_value=log_levels.CMD)
add_logging_level(level_name="OUT", level_value=log_levels.OUT)


host_info = dict(ip="10.10.10.10", username="root", password="")
host_conn = SSHConnection(ip=host_info["ip"], username=host_info["username"], password=host_info["password"])


# 1: From UEFI Shell through BIOS Boot Menu to UEFI Shell [x]

conn = SerialConnection(
    connection=host_conn,
    telnet_port=1240,
    serial_device="/dev/ttyUSB1",
    username="root",
    password="",
    prompt_regex=EFI_SHELL_PROMPT_REGEX,
    baudrate=MEV_IMC_SERIAL_BAUDRATE,
    is_veloce=False,
    execution_retries=1,
    with_redirection=True,
)
# make sure you are in efi shell
res = conn.execute_command("ver")
assert "UEFI Interactive Shell" in res.stdout
# enter Boot Menu
conn.fire_and_forget(command="exit")

# go to BOOT Menu
sleep(10)
conn.send_key(key=SerialKeyCode.escape)
sleep(10)
conn.go_to_option_on_screen(option="Boot manager", send_enter=True)
sleep(10)
conn.go_to_option_on_screen(option="Internal UEFI Shell", send_enter=True)
sleep(10)
conn.wait_for_string(string_list=["Shell>"], expect_timeout=False, timeout=30)

# 2: Start in EFI Shell, send 'drivers',  'help', print output [x]

res = conn.execute_command("drivers")
print(res.stdout)

"""
            T   D
D           Y C I
R           P F A
V  VERSION  E G G #D #C DRIVER NAME                         IMAGE NAME
== ======== = = = == == =================================== ==========
4C 0000000A B - -  1  8 PCI Bus Driver                      PciBusDxe
4E 0000000A ? - -  -  - Sata Controller Init Driver         SataController
4F 00000010 ? - -  -  - NVM Express Driver                  NvmExpressDxe
50 0000000A ? - -  -  - SCSI Bus Driver                     ScsiBus
51 0000000A ? - -  -  - Scsi Disk Driver                    ScsiDisk
52 0000000A B - -  1  1 Serial Terminal Driver              TerminalDxe
53 0000000A ? - -  -  - <null string>                       
54 0000000A ? - -  -  - FAT File System Driver              Fat
55 0000000A ? - -  -  - Generic Disk I/O Driver             DiskIoDxe
56 0000000B ? - -  -  - Partition Driver(MBR/GPT/El Torito) PartitionDxe
59 00000000 ? - -  -  - KernelLoaderDriver                  KernelLoaderDriver
5B 00010400 ? - X  -  - Intel(R) Ethernet APF Driver 0.1.04 MevUefiUndi
5C 0000000A ? - -  -  - Simple Network Protocol Driver      SnpDxe
5D 0000000A ? - -  -  - VLAN Configuration Driver           VlanConfigDxe
5E 0000000A ? - -  -  - MNP Network Service Driver          MnpDxe
5F 0000000A ? - -  -  - ARP Network Service Driver          ArpDxe
60 0000000A ? - -  -  - DHCP Protocol Driver                Dhcp4Dxe
61 0000000A ? - -  -  - IP4 Network Service Driver          Ip4Dxe
62 0000000A ? - -  -  - UDP Network Service Driver          Udp4Dxe
63 0000000A ? - -  -  - MTFTP4 Network Service              Mtftp4Dxe
64 0000000A ? - -  -  - DHCP6 Protocol Driver               Dhcp6Dxe
65 0000000A ? - -  -  - IP6 Network Service Driver          Ip6Dxe
66 0000000A ? - -  -  - UDP6 Network Service Driver         Udp6Dxe
67 0000000A ? - -  -  - MTFTP6 Network Service Driver       Mtftp6Dxe
68 0000000A ? - -  -  - TCP Network Service Driver          TcpDxe
69 0000000A ? - -  -  - TCP Network Service Driver          TcpDxe
6A 0000000A ? - -  -  - UEFI PXE Base Code Driver           UefiPxeBcDxe
6B 0000000A ? - -  -  - UEFI PXE Base Code Driver           UefiPxeBcDxe
6E 00000000 ? - -  -  - DNS Network Service Driver          DnsDxe
6F 00000000 ? - -  -  - DNS Network Service Driver          DnsDxe
70 0000000A ? - -  -  - HttpDxe                             HttpDxe
71 0000000A ? - -  -  - HttpDxe                             HttpDxe
72 0000000A ? - -  -  - UEFI HTTP Boot Driver               HttpBootDxe
73 0000000A ? - -  -  - UEFI HTTP Boot Driver               HttpBootDxe
74 0000000A ? - -  -  - iSCSI Driver                        IScsiDxe
75 0000000A ? - -  -  - iSCSI Driver                        IScsiDxe

Process finished with exit code 0
"""

res = conn.execute_command("help")
print(res.stdout)

"""
acpiview      - Display ACPI Table information.
alias         - Displays, creates, or deletes UEFI Shell aliases.
attrib        - Displays or modifies the attributes of files or directories.
bcfg          - Manages the boot and driver options that are stored in NVRAM.
cd            - Displays or changes the current directory.
cls           - Clears the console output and optionally changes the background 
and foreground color.
comp          - Compares the contents of two files on a byte-for-byte basis.
connect       - Binds a driver to a specific device and starts the driver.
cp            - Copies one or more files or directories to another location.
date          - Displays and sets the current date for the system.
dblk          - Displays one or more blocks from a block device.
devices       - Displays the list of devices managed by UEFI drivers.
devtree       - Displays the UEFI Driver Model compliant device tree.
dh            - Displays the device handles in the UEFI environment.
disconnect    - Disconnects one or more drivers from the specified devices.
dmem          - Displays the contents of system or device memory.
dmpstore      - Manages all UEFI variables.
drivers       - Displays the UEFI driver list.
drvcfg        - Invokes the driver configuration.
drvdiag       - Invokes the Driver Diagnostics Protocol.
echo          - Controls script file command echoing or displays a message.
edit          - Provides a full screen text editor for ASCII or UCS-2 files.
eficompress   - Compresses a file using UEFI Compression Algorithm.
efidecompress - Decompresses a file using UEFI Decompression Algorithm.
else          - Identifies the code executed when 'if' is FALSE.
endfor        - Ends a 'for' loop.
endif         - Ends the block of a script controlled by an 'if' statement.
exit          - Exits the UEFI Shell or the current script.
for           - Starts a loop based on 'for' syntax.
getmtc        - Gets the MTC from BootServices and displays it.
goto          - Moves around the point of execution in a script.
help          - Displays the UEFI Shell command list or verbose command help.
hexedit       - Provides a full screen hex editor for files, block devices, or m
emory.
if            - Executes commands in specified conditions.
ifconfig      - Modifies the default IP address of the UEFI IPv4 Network Stack.
load          - Loads a UEFI driver into memory.
loadpcirom    - Loads a PCI Option ROM.
ls            - Lists the contents of a directory or file information.
map           - Displays or defines file system mappings.
memmap        - Displays the memory map maintained by the UEFI environment.
mkdir         - Creates one or more new directories.
mm            - Displays or modifies MEM/MMIO/IO/PCI/PCIE address space.
mode          - Displays or changes the console output device mode.
mv            - Moves one or more files to a destination within or between file 
systems.
openinfo      - Displays the protocols and agents associated with a handle.
parse         - Retrieves a value from a standard format output file.
pause         - Pauses a script and waits for an operator to press a key.
pci           - Displays PCI device list or PCI function configuration space and
 PCIe extended
configuration space.
ping          - Ping the target host with an IPv4 stack.
reconnect     - Reconnects drivers to the specific device.
reset         - Resets the system.
rm            - Deletes one or more files or directories.
sermode       - Sets serial port attributes.
set           - Displays or modifies UEFI Shell environment variables.
setsize       - Adjusts the size of a file.
setvar        - Displays or modifies a UEFI variable.
shift         - Shifts in-script parameter positions.
smbiosview    - Displays SMBIOS information.
stall         - Stalls the operation for a specified number of microseconds.
time          - Displays or sets the current time for the system.
timezone      - Displays or sets time zone information.
touch         - Updates the filename timestamp with the current system date and 
time.
type          - Sends the contents of a file to the standard output device.
unload        - Unloads a driver image that was already loaded.
ver           - Displays UEFI Firmware version information.
vol           - Displays or modifies information about a disk volume.

Help usage:help [cmd|pattern|special] [-usage] [-verbose] [-section name][-b]

Process finished with exit code 0

"""


# 3: Start in EFI SHELL, power cycle and wait for [Bds]BdsWait, send ESC, boot from EFI Shell

# make sure you are in efi shell
res = conn.execute_command("ver")
assert "UEFI Interactive Shell" in res.stdout
print("Go to raritan and powercycle your setup!")
sleep(10)

conn.wait_for_string(string_list=["BdsWait"], expect_timeout=False, timeout=600)
conn.send_key(key=SerialKeyCode.escape, count=10, sleeptime=0.5)
sleep(10)
conn.go_to_option_on_screen(option="Boot manager", send_enter=True)
sleep(10)
conn.go_to_option_on_screen(option="Internal UEFI Shell", send_enter=True)
sleep(10)
conn.wait_for_string(string_list=["Shell>"], expect_timeout=False, timeout=30)

# as a next step could be:
# conn.wait_for_string(["mev-acc login:"])

# read screen text and return match from regex
value = conn.get_screen_field_value(r"Secure Boot Mode\s+<(?P<value>.*)>", group_name="value")
logger.info(value)
