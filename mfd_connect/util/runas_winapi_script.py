# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: MIT
"""Run command as another Windows user using CreateProcessWithLogonW."""

import base64
import ctypes
import ctypes.wintypes as wintypes
import json
import sys
from typing import Any

LOGON_WITH_PROFILE = 0x00000001
CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_NO_WINDOW = 0x08000000
WAIT_TIMEOUT = 0x00000102
INFINITE = 0xFFFFFFFF

# Window Station / Desktop ACL constants
WINSTA_ALL_ACCESS = 0x000F037F
DESKTOP_ALL_ACCESS = 0x001F01FF
DACL_SECURITY_INFORMATION = 0x4
SE_KERNEL_OBJECT = 6
ACL_REVISION = 2
CONTAINER_INHERIT_ACE = 0x2
INHERIT_ONLY_ACE = 0x8
NO_PROPAGATE_INHERIT_ACE = 0x4


def _get_user_sid(username: str, domain: str | None) -> bytes | None:
    """
    Resolve account SID.

    :param username: Account user name.
    :param domain: Account domain name or ``None`` for local lookup.
    :return: Raw SID bytes if account was resolved, otherwise ``None``.
    """
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    name = f"{domain}\\{username}" if domain and domain not in (".", "") else username
    sid_size = wintypes.DWORD(0)
    dom_size = wintypes.DWORD(0)
    sid_use = wintypes.DWORD(0)
    # First call: retrieve required buffer sizes
    advapi32.LookupAccountNameW(
        None, name, None, ctypes.byref(sid_size), None, ctypes.byref(dom_size), ctypes.byref(sid_use)
    )
    if not sid_size.value:
        return None
    sid_buf = ctypes.create_string_buffer(sid_size.value)
    dom_buf = ctypes.create_unicode_buffer(dom_size.value)
    if not advapi32.LookupAccountNameW(
        None, name, sid_buf, ctypes.byref(sid_size), dom_buf, ctypes.byref(dom_size), ctypes.byref(sid_use)
    ):
        return None
    return bytes(sid_buf)


def _add_ace_to_object(handle: int, se_object_type: int, sid: bytes, access_mask: int, ace_flags: int) -> None:
    """
    Append an allow ACE to the DACL of a kernel object.

    :param handle: Handle to the kernel object.
    :param se_object_type: Security object type used by ``GetSecurityInfo``.
    :param sid: Account SID in raw bytes.
    :param access_mask: Access rights mask for the ACE.
    :param ace_flags: ACE inheritance/propagation flags.
    :return: ``None``
    """
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # Retrieve current DACL + security descriptor
    p_old_dacl = ctypes.c_void_p()
    p_sd = ctypes.c_void_p()
    rc = advapi32.GetSecurityInfo(
        handle,
        se_object_type,
        DACL_SECURITY_INFORMATION,
        None,
        None,
        ctypes.byref(p_old_dacl),
        None,
        ctypes.byref(p_sd),
    )
    if rc != 0:
        return

    try:
        # How many bytes is the old DACL?
        class _AclSizeInfo(ctypes.Structure):
            """ACL size information returned by ``GetAclInformation``."""

            _fields_ = [
                ("AceCount", wintypes.DWORD),
                ("AclBytesInUse", wintypes.DWORD),
                ("AclBytesFree", wintypes.DWORD),
            ]

        old_info = _AclSizeInfo()
        if p_old_dacl:
            advapi32.GetAclInformation(p_old_dacl, ctypes.byref(old_info), ctypes.sizeof(old_info), 2)
        bytes_used = old_info.AclBytesInUse or 8  # 8 = empty ACL header

        # Allocate a new ACL: existing bytes + one new ACE (header 8 + SID length)
        new_acl_size = bytes_used + 8 + len(sid)
        new_acl = ctypes.create_string_buffer(new_acl_size)
        if not advapi32.InitializeAcl(new_acl, new_acl_size, ACL_REVISION):
            return

        # Copy existing ACEs into the new ACL
        for i in range(old_info.AceCount):
            p_ace = ctypes.c_void_p()
            if advapi32.GetAce(p_old_dacl, i, ctypes.byref(p_ace)):
                # ACE layout: BYTE AceType, BYTE AceFlags, WORD AceSize …
                ace_size = ctypes.cast(p_ace, ctypes.POINTER(ctypes.c_ushort * 4))[0][1]
                advapi32.AddAce(new_acl, ACL_REVISION, 0xFFFFFFFF, p_ace, ace_size)

        # Append the new access-allowed ACE
        advapi32.AddAccessAllowedAceEx(new_acl, ACL_REVISION, ace_flags, access_mask, sid)

        # Write the updated DACL back to the object
        advapi32.SetSecurityInfo(handle, se_object_type, DACL_SECURITY_INFORMATION, None, None, new_acl, None)
    finally:
        kernel32.LocalFree(p_sd)


def _get_current_desktop_str() -> str | None:
    r"""
    Return current window station and desktop name.

    :return: ``WinStaName\\DesktopName`` for current process/thread, or ``None``.
    """
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    UOI_NAME = 2

    hwinsta = user32.GetProcessWindowStation()
    if not hwinsta:
        return None
    buf = ctypes.create_unicode_buffer(512)
    length = wintypes.DWORD(0)
    user32.GetUserObjectInformationW(hwinsta, UOI_NAME, buf, ctypes.sizeof(buf), ctypes.byref(length))
    winsta_name = buf.value

    hdesktop = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
    if not hdesktop:
        return winsta_name
    user32.GetUserObjectInformationW(hdesktop, UOI_NAME, buf, ctypes.sizeof(buf), ctypes.byref(length))
    desktop_name = buf.value

    return f"{winsta_name}\\{desktop_name}" if desktop_name else winsta_name


def _grant_winsta_desktop(username: str, domain: str | None) -> list[str]:
    """
    Grant account access to current window station and desktop.

    Uses ``GetProcessWindowStation()``/``GetThreadDesktop()`` (no access check)
    rather than ``OpenWindowStationW("WinSta0", ...)`` which fails with
    ERROR_ACCESS_DENIED when the caller runs in a non-interactive session.

    Without this grant, child processes spawned by cmd.exe (running as *user*
    via ``CreateProcessWithLogonW``) crash with STATUS_DLL_INIT_FAILED
    (0xC0000142) because user32.dll cannot attach to the window station.

    :param username: Target account user name.
    :param domain: Target account domain or ``None`` for local account.
    :return: Diagnostic messages describing performed steps and failures.
    """
    diag: list[str] = []
    sid = _get_user_sid(username, domain)
    if not sid:
        error_code = ctypes.get_last_error()
        diag.append(f"_get_user_sid failed: winerror={error_code}")
        return diag
    diag.append(f"got SID, len={len(sid)}")

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # GetProcessWindowStation returns a pseudo-handle; no permission check needed.
    hwinsta = user32.GetProcessWindowStation()
    if hwinsta:
        UOI_NAME = 2
        buf = ctypes.create_unicode_buffer(512)
        user32.GetUserObjectInformationW(hwinsta, UOI_NAME, buf, ctypes.sizeof(buf), None)
        diag.append(f"current WinSta: '{buf.value}'")
        _add_ace_to_object(hwinsta, SE_KERNEL_OBJECT, sid, WINSTA_ALL_ACCESS, CONTAINER_INHERIT_ACE | INHERIT_ONLY_ACE)
        _add_ace_to_object(hwinsta, SE_KERNEL_OBJECT, sid, WINSTA_ALL_ACCESS, NO_PROPAGATE_INHERIT_ACE)
        diag.append("WinSta ACEs added")
    else:
        diag.append(f"GetProcessWindowStation failed: winerror={ctypes.get_last_error()}")

    hdesktop = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
    if hdesktop:
        buf2 = ctypes.create_unicode_buffer(512)
        user32.GetUserObjectInformationW(hdesktop, 2, buf2, ctypes.sizeof(buf2), None)
        diag.append(f"current Desktop: '{buf2.value}'")
        _add_ace_to_object(hdesktop, SE_KERNEL_OBJECT, sid, DESKTOP_ALL_ACCESS, 0)
        diag.append("Desktop ACE added")
    else:
        diag.append(f"GetThreadDesktop failed: winerror={ctypes.get_last_error()}")

    return diag


class STARTUPINFOW(ctypes.Structure):
    """ctypes mapping of WinAPI ``STARTUPINFOW`` structure."""

    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_ubyte)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    """ctypes mapping of WinAPI ``PROCESS_INFORMATION`` structure."""

    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


def _last_error_payload(prefix: str) -> dict[str, Any]:
    """
    Build JSON-serializable error payload from ``GetLastError``.

    :param prefix: Error context prefix.
    :return: Payload containing ``ok``, ``winerror`` and ``error`` keys.
    """
    error_code = ctypes.get_last_error()
    try:
        error_text = ctypes.WinError(error_code).strerror
    except Exception:
        error_text = "unknown error"
    return {"ok": False, "winerror": int(error_code), "error": f"{prefix}: [{error_code}] {error_text}"}


def _setup_winapi() -> tuple[Any, Any]:
    """
    Configure required WinAPI function signatures.

    :return: Tuple ``(kernel32, advapi32)`` DLL handles with configured prototypes.
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

    advapi32.CreateProcessWithLogonW.argtypes = [
        wintypes.LPCWSTR,  # lpUsername
        wintypes.LPCWSTR,  # lpDomain
        wintypes.LPCWSTR,  # lpPassword
        wintypes.DWORD,  # dwLogonFlags
        wintypes.LPCWSTR,  # lpApplicationName
        wintypes.LPWSTR,  # lpCommandLine (mutable)
        wintypes.DWORD,  # dwCreationFlags
        wintypes.LPVOID,  # lpEnvironment
        wintypes.LPCWSTR,  # lpCurrentDirectory
        ctypes.POINTER(STARTUPINFOW),  # lpStartupInfo
        ctypes.POINTER(PROCESS_INFORMATION),  # lpProcessInformation
    ]
    advapi32.CreateProcessWithLogonW.restype = wintypes.BOOL

    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD

    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL

    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL

    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    return kernel32, advapi32


def main() -> int:
    """
    Execute payload-driven process creation flow.

    :return: Process exit code for the helper wrapper.
    """
    stdin_payload = sys.stdin.read().strip()
    argv_payload = sys.argv[1].strip() if len(sys.argv) == 2 else ""
    encoded_payload = stdin_payload or argv_payload

    if not encoded_payload:
        print(json.dumps({"ok": False, "error": "Expected base64 payload via stdin or argv"}))
        return 2

    try:
        payload = json.loads(base64.b64decode(encoded_payload).decode("utf-8"))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"Failed to decode payload: {exc}"}))
        return 2

    username: str = payload["user"]
    password: str = payload["password"]
    domain: str | None = payload.get("domain")
    cwd: str | None = payload.get("cwd")
    timeout = payload.get("timeout")
    runner_bat_path: str = payload["runner_bat_path"]

    # command_line must be a mutable LPWSTR buffer - Windows may modify it in place.
    # Redirections are already inside runner_bat_path; just run the bat directly.
    command_line_str = f'cmd.exe /c "{runner_bat_path}"'
    command_line_buf = ctypes.create_unicode_buffer(command_line_str)

    startup_info = STARTUPINFOW()
    startup_info.cb = ctypes.sizeof(STARTUPINFOW)
    process_info = PROCESS_INFORMATION()

    kernel32, advapi32 = _setup_winapi()

    # Use None for domain when caller passed "." to mean local machine
    effective_domain = None if domain in (".", "") else domain

    # Grant the target user access to the caller's Window Station and Desktop.
    # Without this, child processes crash with STATUS_DLL_INIT_FAILED (0xC0000142).
    # Uses GetProcessWindowStation (no ACL check) rather than OpenWindowStationW.
    winsta_diag = _grant_winsta_desktop(username, effective_domain)

    # Use the caller's actual desktop so the target user uses the same station
    # that we just granted them access to.
    current_desktop = _get_current_desktop_str()
    if current_desktop:
        startup_info.lpDesktop = current_desktop
        winsta_diag.append(f"lpDesktop={current_desktop}")

    created = advapi32.CreateProcessWithLogonW(
        username,
        effective_domain,
        password,
        LOGON_WITH_PROFILE,
        None,  # lpApplicationName - None, full path in command_line
        command_line_buf,  # lpCommandLine - mutable buffer
        CREATE_UNICODE_ENVIRONMENT | CREATE_NO_WINDOW,
        None,  # inherit current environment
        cwd,
        ctypes.byref(startup_info),
        ctypes.byref(process_info),
    )

    if not created:
        result = _last_error_payload("CreateProcessWithLogonW failed")
        result["debug"] = {
            "username": username,
            "domain": effective_domain,
            "command_line": command_line_str,
            "cwd": cwd,
        }
        print(json.dumps(result))
        return 0

    try:
        timeout_ms = INFINITE if timeout is None else int(timeout * 1000)
        wait_result = kernel32.WaitForSingleObject(process_info.hProcess, timeout_ms)
        if wait_result == WAIT_TIMEOUT:
            kernel32.TerminateProcess(process_info.hProcess, 124)
            print(json.dumps({"ok": False, "timeout": True, "returncode": 124}))
            return 0

        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(process_info.hProcess, ctypes.byref(exit_code)):
            print(json.dumps(_last_error_payload("GetExitCodeProcess failed")))
            return 0

        print(json.dumps({"ok": True, "returncode": int(exit_code.value)}))
        return 0
    finally:
        kernel32.CloseHandle(process_info.hThread)
        kernel32.CloseHandle(process_info.hProcess)


if __name__ == "__main__":
    raise SystemExit(main())
