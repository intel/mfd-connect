# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for running rpyc_server via module."""

from mfd_connect.rpyc_server import rpyc_server

if __name__ == "__main__":
    # execute only if run as a script
    rpyc_server.run()
