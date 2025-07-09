# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT

import logging
from mfd_connect import RPyCConnection, SSHConnection
from mfd_connect.util.rpc_copy_utils import copy

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def rpc_copy_files_example():
    source_conn = RPyCConnection(ip="10.10.10.10")
    destination_conn = RPyCConnection(ip="10.10.10.11")
    source = r"/root/intelcloud_uat.yml"
    target = r"/root/new_intelcloud_uat.yml"
    copy(src_conn=source_conn, dst_conn=destination_conn, source=source, target=target)

    source_conn = SSHConnection(username="user", password="***", ip="10.10.10.20")
    destination_conn = SSHConnection(username="user", password="***", ip="10.10.10.21")
    source = r"C:\new\test_dir"
    target = r"C:\new\copied_test_dir"
    copy(src_conn=source_conn, dst_conn=destination_conn, source=source, target=target)


def rpc_copy_wildcard_extensions_example():
    source_conn = RPyCConnection(ip="10.10.10.10")
    destination_conn = RPyCConnection(ip="10.10.10.11")
    source = "/home/tmp/*.pkg"
    target = "/home/"
    copy(src_conn=source_conn, dst_conn=destination_conn, source=source, target=target)


rpc_copy_example()
rpc_copy_wildcard_extensions_example()
