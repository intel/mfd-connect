# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Example for connection utils."""

from mfd_connect import SSHConnection, LocalConnection
from mfd_connect.util.connection_utils import check_ssh_active_and_return_conn

# Existing connection is SSH
conn = SSHConnection(ip="10.10.10.10", username="user", password="")

check_ssh_active_and_return_conn(conn=conn)

# Existing connection is not SSH

conn = LocalConnection()
check_ssh_active_and_return_conn(conn=conn, ssh_ip="1.1.1.1", ssh_user="user", ssh_pwd="")

# Existing connection is not specified

check_ssh_active_and_return_conn(ssh_ip="1.1.1.1", ssh_user="user", ssh_pwd="")
