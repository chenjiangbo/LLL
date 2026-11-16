"""Windows process liveness and creation identity, with no filesystem access."""
from __future__ import annotations

import ctypes
import os
from datetime import datetime, timedelta, timezone
from ctypes import wintypes


class ProcessIdentityError(RuntimeError):
    pass


def process_started_at(pid: int) -> str:
    if os.name != 'nt':
        raise ProcessIdentityError('Windows process verification requires Windows')
    if isinstance(pid, bool) or not isinstance(pid, int) or not 1 <= pid <= 0xFFFFFFFF:
        raise ProcessIdentityError('invalid process ID')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME)]
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    # SYNCHRONIZE permits an unambiguous signalled/exited check even if a
    # process intentionally returns the numeric STILL_ACTIVE exit code.
    handle = kernel.OpenProcess(0x00100000 | 0x1000, False, pid)
    if not handle:
        raise ProcessIdentityError('process unavailable or access denied')
    try:
        creation, exit_time, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(kernel_time), ctypes.byref(user_time)):
            raise ProcessIdentityError('cannot read process creation time')
        if kernel.WaitForSingleObject(handle, 0) != 0x102:  # WAIT_TIMEOUT means still running
            raise ProcessIdentityError('process exited or liveness check failed')
        ticks = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        return (datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=ticks // 10)).isoformat()
    finally:
        kernel.CloseHandle(handle)


def verify_process(pid: int, started_at: str) -> bool:
    if not isinstance(started_at, str) or not started_at:
        return False
    try:
        return process_started_at(pid) == started_at
    except ProcessIdentityError:
        return False
