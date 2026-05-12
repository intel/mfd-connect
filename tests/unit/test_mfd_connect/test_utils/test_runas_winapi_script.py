# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: MIT

import base64
import json

from mfd_connect.util import runas_winapi_script as script


def _encode_payload(payload):
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


class _FakeFunction:
    def __init__(self, return_value=True, side_effect=None):
        self.return_value = return_value
        self.side_effect = side_effect
        self.argtypes = None
        self.restype = None
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.side_effect is not None:
            return self.side_effect(*args, **kwargs)
        return self.return_value


class _FakeKernel32:
    def __init__(self, wait_result=0, exit_code=0):
        self.WaitForSingleObject = _FakeFunction(return_value=wait_result)
        self.TerminateProcess = _FakeFunction(return_value=True)
        self.CloseHandle = _FakeFunction(return_value=True)
        self._exit_code = exit_code

        def _get_exit_code(_process, ptr):
            ptr._obj.value = self._exit_code
            return True

        self.GetExitCodeProcess = _FakeFunction(side_effect=_get_exit_code)


class _FakeAdvapi32:
    def __init__(self, created=True):
        self.CreateProcessWithLogonW = _FakeFunction(return_value=created)


class TestRunAsWinapiScript:
    def test_last_error_payload(self, monkeypatch):
        monkeypatch.setattr(script.ctypes, "get_last_error", lambda: 5, raising=False)

        class _FakeWinError:
            def __init__(self, _code):
                self.strerror = "Access is denied"

        monkeypatch.setattr(script.ctypes, "WinError", _FakeWinError, raising=False)

        result = script._last_error_payload("prefix")

        assert result["ok"] is False
        assert result["winerror"] == 5
        assert "prefix" in result["error"]

    def test_last_error_payload_when_winerror_raises(self, monkeypatch):
        monkeypatch.setattr(script.ctypes, "get_last_error", lambda: 77, raising=False)

        def _raise_winerror(_code):
            raise RuntimeError("boom")

        monkeypatch.setattr(script.ctypes, "WinError", _raise_winerror, raising=False)

        result = script._last_error_payload("prefix")

        assert result["ok"] is False
        assert result["winerror"] == 77
        assert "unknown error" in result["error"]

    def test_get_user_sid_returns_none_when_lookup_size_missing(self, monkeypatch):
        class _Advapi32:
            def LookupAccountNameW(self, *_args):
                return False

        monkeypatch.setattr(script.ctypes, "WinDLL", lambda *_args, **_kwargs: _Advapi32(), raising=False)

        assert script._get_user_sid("john", None) is None

    def test_get_user_sid_returns_sid_bytes(self, monkeypatch):
        class _Advapi32:
            def __init__(self):
                self.calls = 0

            def LookupAccountNameW(self, _sys, _name, sid, sid_size, _dom, dom_size, _sid_use):
                self.calls += 1
                if self.calls == 1:
                    sid_size._obj.value = 4
                    dom_size._obj.value = 4
                    return False
                sid.raw = b"ABCD"
                return True

        monkeypatch.setattr(script.ctypes, "WinDLL", lambda *_args, **_kwargs: _Advapi32(), raising=False)

        assert script._get_user_sid("john", ".") == b"ABCD"

    def test_grant_winsta_desktop_with_missing_sid(self, monkeypatch):
        monkeypatch.setattr(script, "_get_user_sid", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(script.ctypes, "get_last_error", lambda: 123, raising=False)

        diag = script._grant_winsta_desktop("john", None)

        assert diag == ["_get_user_sid failed: winerror=123"]

    def test_get_current_desktop_str_returns_none_without_winsta(self, monkeypatch):
        class _User32:
            def GetProcessWindowStation(self):
                return 0

        class _Kernel32:
            def GetCurrentThreadId(self):
                return 1

        def _fake_windll(name, **_kwargs):
            if name == "user32":
                return _User32()
            if name == "kernel32":
                return _Kernel32()
            raise AssertionError(name)

        monkeypatch.setattr(script.ctypes, "WinDLL", _fake_windll, raising=False)

        assert script._get_current_desktop_str() is None

    def test_get_current_desktop_str_returns_station_name(self, monkeypatch):
        class _User32:
            def GetProcessWindowStation(self):
                return 1

            def GetUserObjectInformationW(self, handle, _idx, buf, _size, _length):
                if handle == 1:
                    buf.value = "WinSta0"
                elif handle == 0:
                    buf.value = ""
                return True

            def GetThreadDesktop(self, _thread_id):
                return 0

        class _Kernel32:
            def GetCurrentThreadId(self):
                return 1

        def _fake_windll(name, **_kwargs):
            if name == "user32":
                return _User32()
            if name == "kernel32":
                return _Kernel32()
            raise AssertionError(name)

        monkeypatch.setattr(script.ctypes, "WinDLL", _fake_windll, raising=False)

        assert script._get_current_desktop_str() == "WinSta0"

    def test_add_ace_to_object_returns_on_get_security_info_error(self, monkeypatch):
        class _Advapi32:
            def GetSecurityInfo(self, *_args):
                return 1

        class _Kernel32:
            def LocalFree(self, *_args):
                return 0

        def _fake_windll(name, **_kwargs):
            if name == "advapi32":
                return _Advapi32()
            if name == "kernel32":
                return _Kernel32()
            raise AssertionError(name)

        monkeypatch.setattr(script.ctypes, "WinDLL", _fake_windll, raising=False)

        script._add_ace_to_object(
            handle=1, se_object_type=script.SE_KERNEL_OBJECT, sid=b"SID", access_mask=1, ace_flags=0
        )

    def test_grant_winsta_desktop_success(self, monkeypatch):
        monkeypatch.setattr(script, "_get_user_sid", lambda *_args, **_kwargs: b"SID")
        add_ace_calls = []
        monkeypatch.setattr(
            script,
            "_add_ace_to_object",
            lambda *args, **kwargs: add_ace_calls.append((args, kwargs)),
        )

        class _User32:
            def GetProcessWindowStation(self):
                return 11

            def GetUserObjectInformationW(self, handle, _idx, buf, _size, _length):
                if handle == 11:
                    buf.value = "WinSta0"
                else:
                    buf.value = "Default"
                return True

            def GetThreadDesktop(self, _thread_id):
                return 22

        class _Kernel32:
            def GetCurrentThreadId(self):
                return 7

        def _fake_windll(name, **_kwargs):
            if name == "user32":
                return _User32()
            if name == "kernel32":
                return _Kernel32()
            raise AssertionError(name)

        monkeypatch.setattr(script.ctypes, "WinDLL", _fake_windll, raising=False)

        diag = script._grant_winsta_desktop("john", None)

        assert "got SID, len=3" in diag
        assert "current WinSta: 'WinSta0'" in diag
        assert "current Desktop: 'Default'" in diag
        assert "WinSta ACEs added" in diag
        assert "Desktop ACE added" in diag
        assert len(add_ace_calls) == 3

    def test_setup_winapi_configures_prototypes(self, monkeypatch):
        kernel32 = _FakeKernel32()
        advapi32 = _FakeAdvapi32()

        def _fake_windll(name, use_last_error=True):
            if name == "kernel32":
                return kernel32
            if name == "advapi32":
                return advapi32
            raise AssertionError(f"unexpected dll: {name}")

        monkeypatch.setattr(script.ctypes, "WinDLL", _fake_windll, raising=False)

        out_kernel32, out_advapi32 = script._setup_winapi()

        assert out_kernel32 is kernel32
        assert out_advapi32 is advapi32
        assert advapi32.CreateProcessWithLogonW.argtypes is not None
        assert kernel32.WaitForSingleObject.argtypes is not None

    def test_main_requires_single_payload_argument(self, monkeypatch, capsys):
        monkeypatch.setattr(script.sys, "argv", ["runas_winapi_script.py"])
        monkeypatch.setattr(script.sys.stdin, "read", lambda: "")

        rc = script.main()

        out = json.loads(capsys.readouterr().out.strip())
        assert rc == 2
        assert out["ok"] is False

    def test_main_with_invalid_payload(self, monkeypatch, capsys):
        monkeypatch.setattr(script.sys, "argv", ["runas_winapi_script.py"])
        monkeypatch.setattr(script.sys.stdin, "read", lambda: "not-base64")

        rc = script.main()

        out = json.loads(capsys.readouterr().out.strip())
        assert rc == 2
        assert out["ok"] is False
        assert "Failed to decode payload" in out["error"]

    def test_main_create_process_failure(self, monkeypatch, capsys):
        payload = {
            "user": "john",
            "password": "secret",
            "domain": ".",
            "cwd": "C:/Temp",
            "timeout": 5,
            "runner_bat_path": "C:/Temp/run.bat",
        }
        monkeypatch.setattr(script.sys, "argv", ["runas_winapi_script.py"])
        monkeypatch.setattr(script.sys.stdin, "read", lambda: _encode_payload(payload))

        kernel32 = _FakeKernel32(wait_result=0, exit_code=0)
        advapi32 = _FakeAdvapi32(created=False)
        monkeypatch.setattr(script, "_setup_winapi", lambda: (kernel32, advapi32))
        monkeypatch.setattr(script, "_grant_winsta_desktop", lambda *_args, **_kwargs: [])
        monkeypatch.setattr(script, "_get_current_desktop_str", lambda: None)
        monkeypatch.setattr(script, "_last_error_payload", lambda _prefix: {"ok": False, "error": "failure"})

        rc = script.main()

        out = json.loads(capsys.readouterr().out.strip())
        assert rc == 0
        assert out["ok"] is False
        assert out["error"] == "failure"

    def test_main_timeout(self, monkeypatch, capsys):
        payload = {
            "user": "john",
            "password": "secret",
            "domain": None,
            "cwd": "C:/Temp",
            "timeout": 5,
            "runner_bat_path": "C:/Temp/run.bat",
        }
        monkeypatch.setattr(script.sys, "argv", ["runas_winapi_script.py"])
        monkeypatch.setattr(script.sys.stdin, "read", lambda: _encode_payload(payload))

        kernel32 = _FakeKernel32(wait_result=script.WAIT_TIMEOUT, exit_code=0)
        advapi32 = _FakeAdvapi32(created=True)
        monkeypatch.setattr(script, "_setup_winapi", lambda: (kernel32, advapi32))
        monkeypatch.setattr(script, "_grant_winsta_desktop", lambda *_args, **_kwargs: [])
        monkeypatch.setattr(script, "_get_current_desktop_str", lambda: None)

        rc = script.main()

        out = json.loads(capsys.readouterr().out.strip())
        assert rc == 0
        assert out == {"ok": False, "timeout": True, "returncode": 124}

    def test_main_success(self, monkeypatch, capsys):
        payload = {
            "user": "john",
            "password": "secret",
            "domain": None,
            "cwd": "C:/Temp",
            "timeout": None,
            "runner_bat_path": "C:/Temp/run.bat",
        }
        monkeypatch.setattr(script.sys, "argv", ["runas_winapi_script.py"])
        monkeypatch.setattr(script.sys.stdin, "read", lambda: _encode_payload(payload))

        kernel32 = _FakeKernel32(wait_result=0, exit_code=7)
        advapi32 = _FakeAdvapi32(created=True)
        monkeypatch.setattr(script, "_setup_winapi", lambda: (kernel32, advapi32))
        monkeypatch.setattr(script, "_grant_winsta_desktop", lambda *_args, **_kwargs: [])
        monkeypatch.setattr(script, "_get_current_desktop_str", lambda: "WinSta0\\Default")

        rc = script.main()

        out = json.loads(capsys.readouterr().out.strip())
        assert rc == 0
        assert out == {"ok": True, "returncode": 7}

    def test_main_payload_from_argv_fallback(self, monkeypatch, capsys):
        payload = {
            "user": "john",
            "password": "secret",
            "domain": None,
            "cwd": "C:/Temp",
            "timeout": None,
            "runner_bat_path": "C:/Temp/run.bat",
        }
        monkeypatch.setattr(script.sys, "argv", ["runas_winapi_script.py", _encode_payload(payload)])
        monkeypatch.setattr(script.sys.stdin, "read", lambda: "")

        kernel32 = _FakeKernel32(wait_result=0, exit_code=0)
        advapi32 = _FakeAdvapi32(created=True)
        monkeypatch.setattr(script, "_setup_winapi", lambda: (kernel32, advapi32))
        monkeypatch.setattr(script, "_grant_winsta_desktop", lambda *_args, **_kwargs: [])
        monkeypatch.setattr(script, "_get_current_desktop_str", lambda: None)

        rc = script.main()

        out = json.loads(capsys.readouterr().out.strip())
        assert rc == 0
        assert out == {"ok": True, "returncode": 0}
