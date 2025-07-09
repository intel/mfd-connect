# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
from mfd_connect import RPyCConnection
from mfd_connect.util.pathlib_utils import append_file

import logging

logging.basicConfig(level=logging.DEBUG)

conn = RPyCConnection(ip="10.10.10.10")
my_file = conn.path("some_file.txt")
append_file(conn, my_file, "some content")
