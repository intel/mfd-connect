# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Example of how to pass stdin to existing SSH process."""

from mfd_connect import SSHConnection

conn = SSHConnection(ip="10.10.10.10", username="***", password="***")
proc = conn.start_process(command="ping 127.0.0.1 -c 100")
proc.stdin_stream.write("hello world\n")
