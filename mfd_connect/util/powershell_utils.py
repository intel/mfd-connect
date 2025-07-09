# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Utils for powershell cmdlet output."""

from typing import Dict, List


def ps_to_dict(output: str) -> Dict[str, str]:
    """Transform ps output to dictionary.

    :param output: single block of 'key: value' powershell lines
    :return: Dictionary with key-values according to output
    """
    ret_dict = {}
    key = None
    for line in output.strip().splitlines():
        if ":" in line:
            key = line.split(":")[0].strip()
            value = line.split(":", 1)[1].strip()
        elif key:
            value += line.strip()
        else:
            continue
        ret_dict[key] = value.strip()
    return ret_dict


def parse_powershell_list(output: str) -> List[Dict[str, str]]:
    """Parse the full output of a powershell command into a list of dicts, e.g.

    ServiceName      : tunnel
    MACAddress       :
    AdapterType      : Tunnel
    DeviceID         : 13
    Name             : Microsoft ISATAP Adapter #2
    NetworkAddresses :
    Speed            : 100000

    ServiceName      : VBoxNetFlt
    MACAddress       : A0:48:1C:9F:67:7B
    AdapterType      : Ethernet 802.3
    DeviceID         : 14
    Name             : VirtualBox Bridged Networking Driver Miniport
    NetworkAddresses :
    Speed            :

    :return: parsed entities
    """
    item_list = []
    for blk in output.strip().split("\n\n"):
        if blk:
            tmp = ps_to_dict(blk)
            item_list.append(tmp)

    return item_list
