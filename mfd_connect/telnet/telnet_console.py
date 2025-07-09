# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for TelnetConsole class."""

import logging
import time
import telnetlib
from netaddr import IPAddress
from typing import Union, List, Pattern, Tuple, Match

from mfd_common_libs import add_logging_level, log_levels
from ..exceptions import TelnetException

logger = logging.getLogger(__name__)
add_logging_level(level_name="MODULE_DEBUG", level_value=log_levels.MODULE_DEBUG)
add_logging_level(level_name="CMD", level_value=log_levels.CMD)
add_logging_level(level_name="OUT", level_value=log_levels.OUT)


class TelnetConsole:
    """Class representing console for Telnet protocol."""

    def __init__(self, ip: Union[str, IPAddress], port: int):
        """
        Initialise TelnetConsole class.

        :param ip: IP address of host
        :param port: Port for telnet connection
        """
        logger.log(level=log_levels.MODULE_DEBUG, msg=f"Trying to connect to {ip} on {port}")
        self.telnet = telnetlib.Telnet(str(ip), port)
        if not self.is_connected():
            raise TelnetException(f"Failed to connect to {ip} on {port}")

        logger.log(level=log_levels.MODULE_DEBUG, msg="Connected successfully")

    def is_connected(self) -> bool:
        """Check if telnet connection is active."""
        return self.telnet is not None and self.telnet.sock is not None

    def write(self, buffer: Union[str, bytes] = b"", *, end: Union[str, bytes] = b"\n") -> None:
        """Write buffer to console and add endline character."""
        buffer = self._prepare_buffer(buffer) + self._prepare_buffer(end)
        self.telnet.write(buffer)

    def read(self) -> bytes:
        """Read everything that's possible without blocking in I/O (eager).

        Raise EOFError if connection closed and no cooked data
        available.  Return b'' if no cooked data available otherwise.
        Don't block unless in the midst of an IAC sequence.

        """
        return self.telnet.read_very_eager()

    def flush_buffers(self, *, timeout: float = None) -> None:
        """
        Flush buffers and wait for prompt.

        :param timeout: Time to wait before reading from telnet
        """
        if timeout:
            time.sleep(timeout)
        self.telnet.read_very_eager()

    def expect(
        self, pattern_list: Union[List[Pattern[str]], List[bytes]], timeout: float = 1
    ) -> Tuple[int, Match, bytes]:
        """
        Wait for patterns to appear on the console.

        :param pattern_list: Patterns that should appear on the console
        :param timeout: Waiting time
        :return: Tuple -
                    int - index of pattern found
                    Match - matched object
                    bytes - characters read from console
        :raises EOFError: if EOF found and no bytes were read
        """
        return self.telnet.expect(pattern_list, timeout)

    def _prepare_buffer(self, buffer: Union[str, bytes]) -> bytes:
        """
        Prepare buffer for telnet communication - if type str, then encode to bytes.

        :param buffer: Buffer to prepare
        :return: Processed buffer
        :raises TypeError: when invalid type of buffer passed
        """
        if isinstance(buffer, str):
            buffer = buffer.encode()
        if isinstance(buffer, bytes):
            return buffer
        raise TypeError("Invalid buffer type - should be: str, bytes")
