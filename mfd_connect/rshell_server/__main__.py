# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for running rshell_server via module."""

from mfd_connect.rshell_server import rshell_server

if __name__ == "__main__":
    # execute only if run as a script
    rshell_server.run()
