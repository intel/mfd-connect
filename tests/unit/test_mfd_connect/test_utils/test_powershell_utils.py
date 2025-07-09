# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
from mfd_connect.util.powershell_utils import parse_powershell_list, ps_to_dict


class TestPowershellUtils:
    def test_parse_powershell_list(self):
        inputs = [
            "",
            """Name                       : vEthernet (managementvSwitch)
            InterfaceDescription       : Hyper-V Virtual Ethernet Adapter
            InterfaceIndex             : 23
            MacAddress                 : A4-BF-AA-BB-CC-DD
            MediaType                  : 802.3
            PhysicalMediaType          : Unspecified
            InterfaceOperationalStatus : Up
            AdminStatus                : Up
            LinkSpeed(Gbps)            : 1
            MediaConnectionState       : Connected
            ConnectorPresent           : False
            DriverInformation          : Driver Date 2006-06-21 Version 10.0.20348.1""",
            """Name                       : vEthernet (managementvSwitch)
            InterfaceDescription       : Hyper-V Virtual Ethernet Adapter
            InterfaceIndex             : 23
            MacAddress                 : A4-BF-AA-BB-CC-DE
            MediaType                  : 802.3
            PhysicalMediaType          : Unspecified
            InterfaceOperationalStatus : Up
            AdminStatus                : Up
            LinkSpeed(Gbps)            : 1
            MediaConnectionState       : Connected
            ConnectorPresent           : False
            DriverInformation          : Driver Date 2006-06-21 Version 10.0.20348.1

            Name                       : Ethernet 2
            InterfaceDescription       : Intel(R) Ethernet Controller X550
            InterfaceIndex             : 21
            MacAddress                 : A4-BF-AA-BB-CC-DF
            MediaType                  : 802.3
            PhysicalMediaType          : 802.3
            InterfaceOperationalStatus : Down
            AdminStatus                : Up
            LinkSpeed(Mbps)            : 0
            MediaConnectionState       : Disconnected
            ConnectorPresent           : True
            DriverInformation          : Driver Date 2019-06-27 Version 4.1.143.1 NDIS 6.60""",
        ]

        outputs = [
            [],
            [
                {
                    "Name": "vEthernet (managementvSwitch)",
                    "InterfaceDescription": "Hyper-V Virtual Ethernet Adapter",
                    "InterfaceIndex": "23",
                    "MacAddress": "A4-BF-AA-BB-CC-DD",
                    "MediaType": "802.3",
                    "PhysicalMediaType": "Unspecified",
                    "InterfaceOperationalStatus": "Up",
                    "AdminStatus": "Up",
                    "LinkSpeed(Gbps)": "1",
                    "MediaConnectionState": "Connected",
                    "ConnectorPresent": "False",
                    "DriverInformation": "Driver Date 2006-06-21 Version 10.0.20348.1",
                },
                {
                    "Name": "Ethernet 2",
                    "InterfaceDescription": "Intel(R) Ethernet Controller X550",
                    "InterfaceIndex": "21",
                    "MacAddress": "A4-BF-AA-BB-CC-DF",
                    "MediaType": "802.3",
                    "PhysicalMediaType": "802.3",
                    "InterfaceOperationalStatus": "Down",
                    "AdminStatus": "Up",
                    "LinkSpeed(Gbps)": "0",
                    "MediaConnectionState": "Disconnected",
                    "ConnectorPresent": "True",
                    "DriverInformation": "Driver Date 2019-06-27 Version 4.1.143.1 NDIS 6.60",
                },
            ],
        ]

        assert parse_powershell_list(inputs[0]) == []

        for inpt, output in zip(inputs[1:], outputs[1:]):
            results = parse_powershell_list(inpt)
            for i, result in enumerate(results):
                items_present = [output[i][k] == v for k, v in result.items()]
                assert all(items_present)

    def test_ps_to_dict(self):
        inputs = [
            """Name                       : vEthernet (managementvSwitch)
            InterfaceDescription       : Hyper-V Virtual Ethernet Adapter
            InterfaceIndex             : 23"""
        ]

        outputs = [
            {
                "Name": "vEthernet (managementvSwitch)",
                "InterfaceDescription": "Hyper-V Virtual Ethernet Adapter",
                "InterfaceIndex": "23",
            }
        ]

        assert ps_to_dict("") == {}

        for inpt, output in zip(inputs, outputs):
            result = ps_to_dict(inpt)
            items_present = [output[k] == v for k, v in result.items()]
            assert all(items_present)
