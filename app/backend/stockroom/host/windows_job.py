"""Win32 worker jobs with suspended, race-free process assignment.

Every process is assigned before its primary thread can execute. Descendants
therefore inherit the job, and closing or terminating the job cannot strand a
PyInstaller payload after its tracked bootloader process exits.
"""

from __future__ import annotations

import ctypes
import math
import os
import subprocess
import time
from collections.abc import Mapping, Sequence
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

_CREATE_SUSPENDED = 0x00000004
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
_JOB_OBJECT_BASIC_PROCESS_ID_LIST = 3
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_PROCESS_ID_LIST_BYTES = 64 * 1024
_SYNCHRONIZE = 0x00100000
_TH32CS_SNAPTHREAD = 0x00000004
_THREAD_SUSPEND_RESUME = 0x0002
_INVALID_DWORD = 0xFFFFFFFF
_WAIT_OBJECT_0 = 0


class WindowsProcessJobError(RuntimeError):
    """A worker could not be placed in or stopped through its private job."""


class _ThreadEntry32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _BasicAccountingInformation(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_longlong),
        ("TotalKernelTime", ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", ctypes.c_longlong),
        ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


class _BasicProcessIdList(ctypes.Structure):
    _fields_ = [
        ("NumberOfAssignedProcesses", wintypes.DWORD),
        ("NumberOfProcessIdsInList", wintypes.DWORD),
        ("ProcessIdList", ctypes.c_size_t * 1),
    ]


def _kernel32():
    if os.name != "nt":
        raise WindowsProcessJobError("Windows process jobs require Win32")
    library = ctypes.WinDLL("kernel32", use_last_error=True)
    library.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    library.CreateJobObjectW.restype = wintypes.HANDLE
    library.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    library.SetInformationJobObject.restype = wintypes.BOOL
    library.AssignProcessToJobObject.argtypes = [
        wintypes.HANDLE,
        wintypes.HANDLE,
    ]
    library.AssignProcessToJobObject.restype = wintypes.BOOL
    library.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    library.TerminateJobObject.restype = wintypes.BOOL
    library.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPVOID,
    ]
    library.QueryInformationJobObject.restype = wintypes.BOOL
    library.CreateToolhelp32Snapshot.argtypes = [
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    library.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    library.Thread32First.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ThreadEntry32),
    ]
    library.Thread32First.restype = wintypes.BOOL
    library.Thread32Next.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ThreadEntry32),
    ]
    library.Thread32Next.restype = wintypes.BOOL
    library.OpenThread.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    library.OpenThread.restype = wintypes.HANDLE
    library.ResumeThread.argtypes = [wintypes.HANDLE]
    library.ResumeThread.restype = wintypes.DWORD
    library.OpenProcess.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    library.OpenProcess.restype = wintypes.HANDLE
    library.WaitForSingleObject.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
    ]
    library.WaitForSingleObject.restype = wintypes.DWORD
    library.CloseHandle.argtypes = [wintypes.HANDLE]
    library.CloseHandle.restype = wintypes.BOOL
    return library


def _win32_error(message: str) -> WindowsProcessJobError:
    return WindowsProcessJobError(f"{message} (Win32 error {ctypes.get_last_error()})")


def _resume_suspended_process(process_id: int) -> None:
    kernel32 = _kernel32()
    snapshot = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
    invalid_handle = ctypes.c_void_p(-1).value
    if not snapshot or int(snapshot) == invalid_handle:
        raise _win32_error("worker thread snapshot could not be opened")
    resumed = 0
    try:
        entry = _ThreadEntry32()
        entry.dwSize = ctypes.sizeof(entry)
        available = bool(kernel32.Thread32First(snapshot, ctypes.byref(entry)))
        while available:
            if entry.th32OwnerProcessID == process_id:
                thread = kernel32.OpenThread(
                    _THREAD_SUSPEND_RESUME,
                    False,
                    entry.th32ThreadID,
                )
                if not thread:
                    raise _win32_error("worker primary thread could not be opened")
                try:
                    if kernel32.ResumeThread(thread) == _INVALID_DWORD:
                        raise _win32_error("worker primary thread could not be resumed")
                    resumed += 1
                finally:
                    kernel32.CloseHandle(thread)
            available = bool(kernel32.Thread32Next(snapshot, ctypes.byref(entry)))
    finally:
        kernel32.CloseHandle(snapshot)
    if resumed != 1:
        raise WindowsProcessJobError("suspended worker did not expose exactly one primary thread")


@dataclass(slots=True)
class WindowsProcessJob:
    """One non-inheritable job handle that owns a complete worker tree."""

    _handle: int | None

    def _active_process_count(self) -> int:
        if self._handle is None:
            return 0
        kernel32 = _kernel32()
        accounting = _BasicAccountingInformation()
        if not kernel32.QueryInformationJobObject(
            self._handle,
            _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
            ctypes.byref(accounting),
            ctypes.sizeof(accounting),
            None,
        ):
            raise _win32_error("worker job state could not be queried")
        return int(accounting.ActiveProcesses)

    def _active_process_handles(self) -> list[int]:
        if self._handle is None:
            return []
        kernel32 = _kernel32()
        buffer = ctypes.create_string_buffer(_PROCESS_ID_LIST_BYTES)
        if not kernel32.QueryInformationJobObject(
            self._handle,
            _JOB_OBJECT_BASIC_PROCESS_ID_LIST,
            buffer,
            len(buffer),
            None,
        ):
            raise _win32_error("worker job process list could not be queried")
        header = _BasicProcessIdList.from_buffer(buffer)
        count = int(header.NumberOfProcessIdsInList)
        capacity = (len(buffer) - _BasicProcessIdList.ProcessIdList.offset) // ctypes.sizeof(
            ctypes.c_size_t
        )
        if count > capacity:
            raise WindowsProcessJobError("worker job process list exceeded its bounded buffer")
        process_ids = (ctypes.c_size_t * count).from_buffer(
            buffer,
            _BasicProcessIdList.ProcessIdList.offset,
        )
        handles: list[int] = []
        try:
            for process_id in process_ids:
                handle = kernel32.OpenProcess(
                    _SYNCHRONIZE,
                    False,
                    int(process_id),
                )
                if not handle:
                    raise _win32_error("worker job member could not be opened for shutdown")
                handles.append(int(handle))
        except BaseException:
            for handle in handles:
                kernel32.CloseHandle(handle)
            raise
        return handles

    def terminate_all(self, *, timeout: float) -> None:
        """Terminate the job and wait until Windows reports zero live members."""

        if self._handle is None:
            return
        kernel32 = _kernel32()
        handle = self._handle
        failure: BaseException | None = None
        process_handles: list[int] = []
        try:
            process_handles = self._active_process_handles()
            if not kernel32.TerminateJobObject(handle, 1):
                raise _win32_error("worker job could not be terminated")
            deadline = time.monotonic() + timeout
            for process_handle in process_handles:
                remaining_ms = max(
                    0,
                    math.ceil((deadline - time.monotonic()) * 1000),
                )
                if (
                    kernel32.WaitForSingleObject(
                        process_handle,
                        remaining_ms,
                    )
                    != _WAIT_OBJECT_0
                ):
                    raise WindowsProcessJobError(
                        "worker job member did not stop before the deadline"
                    )
            while self._active_process_count() != 0:
                if time.monotonic() >= deadline:
                    raise WindowsProcessJobError("worker job did not reach zero live processes")
                time.sleep(0.01)
        except BaseException as exc:
            failure = exc
        finally:
            for process_handle in process_handles:
                kernel32.CloseHandle(process_handle)
            self._handle = None
            if not kernel32.CloseHandle(handle) and failure is None:
                failure = _win32_error("worker job handle could not be closed")
        if failure is not None:
            raise failure


def launch_in_windows_job(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    creationflags: int,
) -> tuple[subprocess.Popen[bytes], WindowsProcessJob]:
    """Launch suspended, assign the exact root to a kill-on-close job, then resume."""

    if os.name != "nt":
        raise WindowsProcessJobError("Windows process jobs require Win32")
    process = subprocess.Popen(
        list(command),
        cwd=str(cwd),
        env=dict(environment),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags | _CREATE_SUSPENDED,
    )
    kernel32 = _kernel32()
    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        process.kill()
        process.wait()
        raise _win32_error("worker job could not be created")
    job = WindowsProcessJob(int(handle))
    try:
        limits = _ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            raise _win32_error("worker job limits could not be installed")
        process_handle = wintypes.HANDLE(int(getattr(process, "_handle")))
        if not kernel32.AssignProcessToJobObject(handle, process_handle):
            raise _win32_error("worker could not be assigned to its job")
        _resume_suspended_process(process.pid)
    except BaseException:
        try:
            job.terminate_all(timeout=5.0)
        finally:
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5.0)
        raise
    return process, job


__all__ = [
    "WindowsProcessJob",
    "WindowsProcessJobError",
    "launch_in_windows_job",
]
