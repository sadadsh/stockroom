"""Secure Windows named-mutex adapter for per-user coordinator liveness.

The mutex lives in the session-local ``Local\\`` namespace.  Its name contains
only a SHA-256 digest of the verified current SID, and its protected DACL has
exactly one allow ACE: ``MUTEX_ALL_ACCESS`` for that SID.  Existing named
objects are inspected after opening, so a permissive pre-created object is
rejected rather than silently trusted.

Windows mutex ownership is thread-affine.  A handle must be released or closed
by the same thread that successfully acquired it.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import re
import secrets
import threading
from ctypes import wintypes
from types import TracebackType
from typing import Self

from .ports import (
    MutexAcquireResult,
    NamedMutexHandlePort,
    WindowsCurrentIdentity,
    is_windows_sid,
)

_PRODUCTION_PURPOSE = "Coordinator"
_PURPOSE_PATTERN = re.compile(r"[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*", re.ASCII)

_SDDL_REVISION_1 = 1
_DACL_SECURITY_INFORMATION = 0x00000004
_SE_KERNEL_OBJECT = 6
_SE_DACL_PRESENT = 0x0004
_SE_DACL_PROTECTED = 0x1000
_ACL_SIZE_INFORMATION_CLASS = 2
_ACCESS_ALLOWED_ACE_TYPE = 0
_MUTEX_ALL_ACCESS = 0x001F0001

_WAIT_OBJECT_0 = 0x00000000
_WAIT_ABANDONED = 0x00000080
_WAIT_TIMEOUT = 0x00000102
_WAIT_FAILED = 0xFFFFFFFF
_ERROR_ALREADY_EXISTS = 183


class WindowsMutexError(RuntimeError):
    """Base class for safe Windows named-mutex failures."""


class WindowsMutexSecurityError(WindowsMutexError):
    """The mutex name, identity, or kernel DACL was not trustworthy."""


class WindowsMutexStateError(WindowsMutexError):
    """The handle was closed, recursively claimed, or released incorrectly."""


class WindowsMutexWaitFailed(WindowsMutexError):
    """``WaitForSingleObject`` returned ``WAIT_FAILED``."""

    def __init__(self, winerror: int):
        super().__init__("Windows named-mutex wait failed")
        self.winerror = winerror


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


class _AclSizeInformation(ctypes.Structure):
    _fields_ = [
        ("AceCount", wintypes.DWORD),
        ("AclBytesInUse", wintypes.DWORD),
        ("AclBytesFree", wintypes.DWORD),
    ]


class _AceHeader(ctypes.Structure):
    _fields_ = [
        ("AceType", wintypes.BYTE),
        ("AceFlags", wintypes.BYTE),
        ("AceSize", wintypes.WORD),
    ]


class _AccessAllowedAce(ctypes.Structure):
    _fields_ = [
        ("Header", _AceHeader),
        ("Mask", wintypes.DWORD),
        ("SidStart", wintypes.DWORD),
    ]


class _WindowsApi:
    def __init__(self):
        if os.name != "nt":
            raise OSError("Windows named mutexes are unavailable")

        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        self.advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)  # type: ignore[attr-defined]

        self.create_mutex = self.kernel32.CreateMutexW
        self.create_mutex.argtypes = [
            ctypes.POINTER(_SecurityAttributes),
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        self.create_mutex.restype = wintypes.HANDLE

        self.wait = self.kernel32.WaitForSingleObject
        self.wait.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.wait.restype = wintypes.DWORD

        self.release_mutex = self.kernel32.ReleaseMutex
        self.release_mutex.argtypes = [wintypes.HANDLE]
        self.release_mutex.restype = wintypes.BOOL

        self.close_handle = self.kernel32.CloseHandle
        self.close_handle.argtypes = [wintypes.HANDLE]
        self.close_handle.restype = wintypes.BOOL

        self.local_free = self.kernel32.LocalFree
        self.local_free.argtypes = [ctypes.c_void_p]
        self.local_free.restype = ctypes.c_void_p

        self.string_to_sid = self.advapi32.ConvertStringSidToSidW
        self.string_to_sid.argtypes = [
            wintypes.LPCWSTR,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self.string_to_sid.restype = wintypes.BOOL

        self.string_to_security_descriptor = (
            self.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
        )
        self.string_to_security_descriptor.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.string_to_security_descriptor.restype = wintypes.BOOL

        self.get_security_info = self.advapi32.GetSecurityInfo
        self.get_security_info.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self.get_security_info.restype = wintypes.DWORD

        self.get_security_descriptor_control = self.advapi32.GetSecurityDescriptorControl
        self.get_security_descriptor_control.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.WORD),
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.get_security_descriptor_control.restype = wintypes.BOOL

        self.get_acl_information = self.advapi32.GetAclInformation
        self.get_acl_information.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        self.get_acl_information.restype = wintypes.BOOL

        self.get_ace = self.advapi32.GetAce
        self.get_ace.argtypes = [
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self.get_ace.restype = wintypes.BOOL

        self.equal_sid = self.advapi32.EqualSid
        self.equal_sid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.equal_sid.restype = wintypes.BOOL


def current_user_mutex_name(
    sid: str,
    *,
    purpose: str = _PRODUCTION_PURPOSE,
) -> str:
    """Derive a session-local mutex name without exposing the SID."""

    if not is_windows_sid(sid):
        raise WindowsMutexSecurityError("Windows named-mutex SID is invalid")
    if type(purpose) is not str or len(purpose) > 96 or _PURPOSE_PATTERN.fullmatch(purpose) is None:
        raise WindowsMutexSecurityError("Windows named-mutex purpose is invalid")
    digest = hashlib.sha256(sid.encode("ascii")).hexdigest()
    return f"Local\\Stockroom.{purpose}.{digest}"


def _local_free(api: _WindowsApi, pointer: ctypes.c_void_p) -> None:
    if pointer.value:
        api.local_free(pointer)


def _verify_current_sid_only_dacl(
    api: _WindowsApi,
    handle: int,
    expected_sid: ctypes.c_void_p,
) -> None:
    dacl = ctypes.c_void_p()
    security_descriptor = ctypes.c_void_p()
    status = api.get_security_info(
        handle,
        _SE_KERNEL_OBJECT,
        _DACL_SECURITY_INFORMATION,
        None,
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(security_descriptor),
    )
    if status != 0 or not security_descriptor.value or not dacl.value:
        _local_free(api, security_descriptor)
        raise WindowsMutexSecurityError("Windows named-mutex DACL could not be verified")

    try:
        control = wintypes.WORD()
        revision = wintypes.DWORD()
        if not api.get_security_descriptor_control(
            security_descriptor,
            ctypes.byref(control),
            ctypes.byref(revision),
        ):
            raise WindowsMutexSecurityError("Windows named-mutex DACL could not be verified")
        if control.value & _SE_DACL_PRESENT == 0 or control.value & _SE_DACL_PROTECTED == 0:
            raise WindowsMutexSecurityError("Windows named-mutex DACL is not protected")

        information = _AclSizeInformation()
        if not api.get_acl_information(
            dacl,
            ctypes.byref(information),
            ctypes.sizeof(information),
            _ACL_SIZE_INFORMATION_CLASS,
        ):
            raise WindowsMutexSecurityError("Windows named-mutex DACL could not be inspected")
        if information.AceCount != 1:
            raise WindowsMutexSecurityError("Windows named-mutex DACL grants unexpected principals")

        ace_pointer = ctypes.c_void_p()
        if not api.get_ace(dacl, 0, ctypes.byref(ace_pointer)) or not ace_pointer.value:
            raise WindowsMutexSecurityError("Windows named-mutex DACL ACE could not be inspected")
        ace = _AccessAllowedAce.from_address(ace_pointer.value)
        if (
            ace.Header.AceType != _ACCESS_ALLOWED_ACE_TYPE
            or ace.Header.AceFlags != 0
            or ace.Mask != _MUTEX_ALL_ACCESS
        ):
            raise WindowsMutexSecurityError("Windows named-mutex DACL grants unexpected access")

        ace_sid_address = ace_pointer.value + _AccessAllowedAce.SidStart.offset
        if not api.equal_sid(expected_sid, ctypes.c_void_p(ace_sid_address)):
            raise WindowsMutexSecurityError("Windows named-mutex DACL belongs to another identity")
    finally:
        _local_free(api, security_descriptor)


class WindowsNamedMutexHandle(NamedMutexHandlePort):
    """One verified Windows mutex handle with explicit ownership state."""

    def __init__(
        self,
        api: _WindowsApi,
        handle: int,
        *,
        created_new: bool,
    ):
        self._api = api
        self._handle = handle
        self._creation_evidence_available = created_new
        self._held = False
        self._owner_thread: int | None = None
        self._closed = False
        self._state_lock = threading.Lock()

    def try_acquire(self) -> MutexAcquireResult:
        with self._state_lock:
            if self._closed:
                raise WindowsMutexStateError("Windows named-mutex handle is closed")
            if self._held:
                raise WindowsMutexStateError("Windows named-mutex claims cannot be recursive")

            ctypes.set_last_error(0)
            result = int(self._api.wait(self._handle, 0))
            if result == _WAIT_TIMEOUT:
                return MutexAcquireResult.BUSY
            if result == _WAIT_OBJECT_0:
                self._held = True
                self._owner_thread = threading.get_ident()
                if self._creation_evidence_available:
                    self._creation_evidence_available = False
                    return MutexAcquireResult.CREATED
                return MutexAcquireResult.ACQUIRED
            if result == _WAIT_ABANDONED:
                self._held = True
                self._owner_thread = threading.get_ident()
                self._creation_evidence_available = False
                return MutexAcquireResult.ABANDONED
            if result == _WAIT_FAILED:
                raise WindowsMutexWaitFailed(ctypes.get_last_error())
            raise WindowsMutexError("Windows named-mutex wait returned an unknown result")

    def _release_locked(self) -> None:
        if not self._held:
            raise WindowsMutexStateError("Windows named-mutex is not held")
        if self._owner_thread != threading.get_ident():
            raise WindowsMutexStateError("Windows named-mutex must be released by its owner thread")
        ctypes.set_last_error(0)
        if not self._api.release_mutex(self._handle):
            raise WindowsMutexError("Windows named-mutex release failed")
        self._held = False
        self._owner_thread = None

    def release(self) -> None:
        with self._state_lock:
            if self._closed:
                raise WindowsMutexStateError("Windows named-mutex handle is closed")
            self._release_locked()

    def close(self) -> None:
        """Release if owned, then close the kernel handle exactly once."""

        with self._state_lock:
            if self._closed:
                return
            if self._held:
                self._release_locked()
            ctypes.set_last_error(0)
            if not self._api.close_handle(self._handle):
                raise WindowsMutexError("Windows named-mutex handle close failed")
            self._closed = True
            self._handle = 0

    def __enter__(self) -> Self:
        if self._closed:
            raise WindowsMutexStateError("Windows named-mutex handle is closed")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


class WindowsNamedMutexFactory:
    """Create and verify current-user-only named Windows mutexes."""

    def __init__(self, *, purpose: str = _PRODUCTION_PURPOSE):
        if (
            type(purpose) is not str
            or len(purpose) > 96
            or _PURPOSE_PATTERN.fullmatch(purpose) is None
        ):
            raise WindowsMutexSecurityError("Windows named-mutex purpose is invalid")
        self.purpose = purpose

    def open_current_user(
        self,
        *,
        name: str,
        sid: str,
    ) -> WindowsNamedMutexHandle:
        if os.name != "nt":
            raise WindowsMutexError("Windows named mutexes are unavailable")
        if not is_windows_sid(sid):
            raise WindowsMutexSecurityError("Windows named-mutex SID is invalid")

        actual_sid = WindowsCurrentIdentity().current_sid()
        if not secrets.compare_digest(actual_sid, sid):
            raise WindowsMutexSecurityError("Windows named-mutex SID is not the current identity")
        expected_name = current_user_mutex_name(sid, purpose=self.purpose)
        if type(name) is not str or not secrets.compare_digest(name, expected_name):
            raise WindowsMutexSecurityError("Windows named-mutex name is not current-user scoped")

        api = _WindowsApi()
        sid_pointer = ctypes.c_void_p()
        security_descriptor = ctypes.c_void_p()
        handle_value = 0
        if not api.string_to_sid(sid, ctypes.byref(sid_pointer)):
            raise WindowsMutexSecurityError("Windows named-mutex SID could not be converted")
        try:
            sddl = f"D:P(A;;0x{_MUTEX_ALL_ACCESS:08x};;;{sid})"
            descriptor_size = wintypes.DWORD()
            if not api.string_to_security_descriptor(
                sddl,
                _SDDL_REVISION_1,
                ctypes.byref(security_descriptor),
                ctypes.byref(descriptor_size),
            ):
                raise WindowsMutexSecurityError("Windows named-mutex DACL could not be created")

            attributes = _SecurityAttributes(
                nLength=ctypes.sizeof(_SecurityAttributes),
                lpSecurityDescriptor=security_descriptor,
                bInheritHandle=False,
            )
            ctypes.set_last_error(0)
            raw_handle = api.create_mutex(
                ctypes.byref(attributes),
                False,
                name,
            )
            creation_error = ctypes.get_last_error()
            handle_value = int(raw_handle or 0)
            if handle_value == 0:
                raise WindowsMutexError("Windows named-mutex creation failed")
            if creation_error not in (0, _ERROR_ALREADY_EXISTS):
                raise WindowsMutexError("Windows named-mutex creation state could not be verified")

            _verify_current_sid_only_dacl(api, handle_value, sid_pointer)
            return WindowsNamedMutexHandle(
                api,
                handle_value,
                created_new=creation_error == 0,
            )
        except BaseException:
            if handle_value:
                api.close_handle(handle_value)
            raise
        finally:
            _local_free(api, security_descriptor)
            _local_free(api, sid_pointer)


secure_windows_mutex_factory = WindowsNamedMutexFactory()

__all__ = [
    "WindowsMutexError",
    "WindowsMutexSecurityError",
    "WindowsMutexStateError",
    "WindowsMutexWaitFailed",
    "WindowsNamedMutexFactory",
    "WindowsNamedMutexHandle",
    "current_user_mutex_name",
    "secure_windows_mutex_factory",
]
