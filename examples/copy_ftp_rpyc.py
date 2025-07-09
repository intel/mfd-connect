# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
from mfd_connect import RPyCConnection
import logging

# only for debug purpose, public API is `copy(...)`
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(message)s", datefmt="%I:%M:%S")
from mfd_connect.util.rpc_copy_utils import _copy_file_ftp_rpyc

src = RPyCConnection(ip="127.0.0.1")

dst = RPyCConnection(ip="10.10.10.10")  # linux
_copy_file_ftp_rpyc(
    src, dst, src.path(r"C:\Users\admin\Downloads\file.zip"), dst.path("/home/file.zip"), timeout=1000
)
dst.path("/home/file.zip").unlink()

dst = RPyCConnection(ip="10.10.10.11")  # windows
_copy_file_ftp_rpyc(src, dst, src.path(r"C:\Users\admin\Downloads\file.zip"), dst.path(r"C:\file.zip"), timeout=1000)
dst.path(r"C:\file.zip").unlink()
