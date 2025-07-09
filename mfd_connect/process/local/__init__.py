# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Package for LocalConnection Process implementations."""

from .base import LocalProcess
from .posix import POSIXLocalProcess
from .windows import WindowsLocalProcess
