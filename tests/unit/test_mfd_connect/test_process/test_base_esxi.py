# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
import pytest

from mfd_connect import RPyCConnection
from mfd_connect.base import ConnectionCompletedProcess
from mfd_connect.process.base import ESXiRemoteProcess


class TestESXiRemoteProcess:
    owner = RPyCConnection

    @pytest.fixture(scope="class")
    def remote_process(self):
        class_under_test = ESXiRemoteProcess
        if hasattr(class_under_test, "__abstractmethods__"):
            # Remove abstract methods, if any so the class can be instantiated
            class_under_test.__abstractmethods__ = []
        return class_under_test.__new__(class_under_test)

    def test___find_children_process(self, remote_process, mocker):
        esxi_ps_output = b"""\x0ex\x0f \x0et\x0f\x0eq\x0f2286411  2286411  sh                    /bin/sh -c netserver 1> /vmfs/volumes/5bc9d125-9c015531-f0d4-001e6762ca0a/iperf_test.log 2>&1'
        \x0ex\x0f \x0ex\x0f \x0em\x0f\x0eq\x0f2286412  2286412  netserver             netserver'
        \x0ex\x0f \x0em\x0f\x0eq\x0f2293713  2293713  sh                    /bin/sh -c ps -c -J'
        \x0ex\x0f   \x0em\x0f\x0eq\x0f2293714  2293714  ps                    ps -c -J'
        \x0ex\x0f   \x0em\x0f\x0eq\x0f\x0et\x0f2293715  2293715  ps                    ps -c -J'
        \x0et\x0f\x0eq\x0f2100721  2100721  sh                    /bin/sh /bin/techsupport.sh'
        \x0ex\x0f \x0em\x0f\x0eq\x0f2100746  2100746  getty                 getty 38400 tty1'
        \x0et\x0f\x0eq\x0f2100722  2100722  dcui                  /bin/dcui 2'
        \x0et\x0f\x0eq\x0f2100749  2100722  dcui                  /bin/dcui 2'
        \x0et\x0f\x0eq\x0f2100750  2100715  python                python //bin/rpyc_classic.py -m threaded --host 0.0.0.0 --port 18813
        \x0et\x0f\x0eq\x0f2101081  2101081  sh                    /bin/sh /sbin/watchdog.sh -s vsanreaderd "/usr/lib/vmware/vsan/bin/vsanTraceReader" vsanExtractUrgentTraces vsanreaderd
        \x0ex\x0f \x0em\x0f\x0eq\x0f2101091  2101091  vsanreaderd           /usr/lib/vmware/vsan/bin/vsanTraceReader vsanExtractUrgentTraces vsanreaderd
        \x0et\x0f\x0eq\x0f2101101  2101101  sh                    /bin/sh /sbin/watchdog.sh -s vsantraced "/bin/chardevlogger" -o -R timestamp -S 64 -z3 -m 8 -s 20 -n vsantraced "/dev/vsanTraces" "/vsantraces/vsantraces"
        \x0ex\x0f \x0em\x0f\x0eq\x0f2101111  2101111  vsantraced            /bin/chardevlogger -o -R timestamp -S 64 -z3 -m 8 -s 20 -n vsantraced /dev/vsanTraces /vsantraces/vsantraces
        \x0et\x0f\x0eq\x0f2101121  2101121  sh                    /bin/sh /sbin/watchdog.sh -s vsantracedUrgen "/bin/chardevlogger" -o -R timestamp -S 64 -z3 -m 4 -s 10 -n vsantracedUrgen "/dev/vsanTracesUrgent" "/vsantraces/vsantracesUrgent"
        \x0ex\x0f \x0em\x0f\x0eq\x0f2101131  2101131  vsantracedUrgen       /bin/chardevlogger -o -R timestamp -S 64 -z3 -m 4 -s 10 -n vsantracedUrgen /dev/vsanTracesUrgent /vsantraces/vsantracesUrgent
        \x0et\x0f\x0eq\x0f2101141  2101141  sh                    /bin/sh /sbin/watchdog.sh -s vsantracedLSOM "/bin/chardevlogger" -o -R timestamp -S 64 -z3 -m 4 -s 2 -n vsantracedLSOM "/dev/vsanTracesLSOM" "/vsantraces/vsantracesLSOM"
        \x0ex\x0f \x0em\x0f\x0eq\x0f2101153  2101153  vsantracedLSOM        /bin/chardevlogger -o -R timestamp -S 64 -z3 -m 4 -s 2 -n vsantracedLSOM /dev/vsanTracesLSOM /vsantraces/vsantracesLSOM
        \x0et\x0f\x0eq\x0f2101159  2101159  sh                    /bin/sh /sbin/watchdog.sh -s vsantracedDOMOb "/bin/chardevlogger" -o -R timestamp -S 64 -z3 -m 4 -s 1 -n vsantracedDOMOb "/dev/vsanTracesDOMObj" "/vsantraces/vsantracesDOMObj"
        \x0ex\x0f \x0em\x0f\x0eq\x0f2101169  2101169  vsantracedDOMOb       /bin/chardevlogger -o -R timestamp -S 64 -z3 -m 4 -s 1 -n vsantracedDOMOb /dev/vsanTracesDOMObj /vsantraces/vsantracesDOMObj
        \x0em\x0f\x0eq\x0f2293710  2100715  python                python //bin/rpyc_classic.py -m threaded --host 0.0.0.0 --port 18813
        """  # noqa E501
        rpyc_owner = mocker.create_autospec(self.owner, spec_set=True)
        remote_process._owner = rpyc_owner
        remote_process._owner.execute_command.return_value = ConnectionCompletedProcess(
            args="", return_code=0, stdout="", stdout_bytes=esxi_ps_output
        )
        assert ESXiRemoteProcess._find_children_process(remote_process._owner, 2286411) == [2286412]
        esxi_ps_output2 = b"""\x0ex\x0f \x0em\x0f2293713  2293713  sh                    /bin/sh -c ps -c -J'
        \x0ex\x0f   \x0em\x0f\x0eq\x0f2293714  2293714  ps                    ps -c -J'
        \x0ex\x0f   \x0em\x0f\x0eq\x0f\x0et\x0f2293715  2293715  ps                    ps -c -J'
        """
        remote_process._owner.execute_command.return_value = ConnectionCompletedProcess(
            args="", return_code=0, stdout="", stdout_bytes=esxi_ps_output2
        )
        assert ESXiRemoteProcess._find_children_process(remote_process._owner, 2293713) == [2293714, 2293715]
