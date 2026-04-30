# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Serial utils."""

import re
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


# Shell prompt patterns
EFI_SHELL_PROMPT_REGEX = r"(\>|Shell>) \x1b\[0m\x1b\[37m\x1b\[40m"
UNIX_PROMPT_REGEX = r"[#\$](?:\033\[0m \S*)?\s*$"

# ANSI/VT terminal escape sequence handling
ANSI_TERMINAL_ESCAPE_REGEX = rb"(?:\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-_])"
ANSI_TERMINAL_ESCAPE_REGEX_STR = re.compile(r"(?:\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-_])")
ANSI_SHELL_PROMPT_FALLBACK_REGEX = (
    rb"(?:[^\r\n\x1b]|"
    + ANSI_TERMINAL_ESCAPE_REGEX
    + rb")*[#\$](?:[^\r\n\x1b]|"
    + ANSI_TERMINAL_ESCAPE_REGEX
    + rb")*\s*$"
)

# Cursor Position Request (CPR) handling for interactive shells
CURSOR_POSITION_REQUEST_REGEX = re.compile(rb"\x1b\[6n")
FALLBACK_CURSOR_POSITION_RESPONSE = b"\x1b[24;80R"

# Login recovery parameters
LOGIN_PROMPT_RECOVERY_RETRIES = 6
LOGIN_PROMPT_RECOVERY_TIMEOUT = 5

MEV_IMC_SERIAL_BAUDRATE = 115200
