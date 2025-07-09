# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Serial utils."""

from enum import Enum


class SerialKeyCode(Enum):
    """Serial codes of keys."""

    down_arrow = "\x1b\x5b\x42"
    up_arrow = "\x1b\x5b\x41"
    left_arrow = "\x1b\x5b\x44"
    right_arrow = "\x1b\x5b\x43"
    enter = "\r"
    space = " "
    tab = "\x09"
    delete = "\x7f"
    backspace = "\x08"
    escape = "\x1b"
    F1 = "\x1b\x4f\x50"
    F2 = "\x1b\x4f\x51"
    F4 = "\x1b\x4f\x53"
    F8 = "\x1b\x38"
    F10 = "\x1b\x30"
    F11 = "\x1b\x21"
    F12 = "\x1b\x40"


EFI_SHELL_PROMPT_REGEX = r"(\>|Shell>) \x1b\[0m\x1b\[37m\x1b\[40m"
UNIX_PROMPT_REGEX = r"[#\$](?:\033\[0m \S*)?\s*$"
MEV_IMC_SERIAL_BAUDRATE = 115200
