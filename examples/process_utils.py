# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT

from mfd_connect import RPyCConnection
from mfd_connect.util.process_utils import get_process_by_name, kill_process_by_name, kill_all_processes_by_name

conn = RPyCConnection("10.10.10.10")

print(get_process_by_name(conn=conn,process_name="tcpdump"))
# ['87915', '87916', '87921']

kill_process_by_name(conn=conn,process_name="tcpdump")

kill_all_processes_by_name(conn=conn,process_name="iexplore.exe")
