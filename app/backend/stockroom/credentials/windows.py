"""Small ctypes binding to Windows Credential Manager.

Only generic credentials scoped to the current Windows user are used.  Target
names contain a stable Stockroom namespace and field name, never a secret.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from .store import (
    CredentialStoreError,
    _validate_name,
    _validate_namespace,
    _validate_value,
)

_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_ERROR_NOT_FOUND = 1168


class _CREDENTIAL_ATTRIBUTEW(ctypes.Structure):
    _fields_ = [
        ("Keyword", wintypes.LPWSTR),
        ("Flags", wintypes.DWORD),
        ("ValueSize", wintypes.DWORD),
        ("Value", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.POINTER(_CREDENTIAL_ATTRIBUTEW)),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class _WindowsCredentialApi:
    def __init__(self) -> None:
        try:
            library = ctypes.WinDLL("advapi32", use_last_error=True)
        except (AttributeError, OSError) as exc:
            raise CredentialStoreError("Windows Credential Manager could not be loaded") from exc

        library.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_CREDENTIALW)),
        ]
        library.CredReadW.restype = wintypes.BOOL
        library.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
        library.CredWriteW.restype = wintypes.BOOL
        library.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        library.CredDeleteW.restype = wintypes.BOOL
        library.CredFree.argtypes = [wintypes.LPVOID]
        library.CredFree.restype = None
        self._library = library

    def read(self, target: str) -> str | None:
        pointer = ctypes.POINTER(_CREDENTIALW)()
        if not self._library.CredReadW(
            target,
            _CRED_TYPE_GENERIC,
            0,
            ctypes.byref(pointer),
        ):
            error = ctypes.get_last_error()
            if error == _ERROR_NOT_FOUND:
                return None
            raise _win_error("read", error)
        try:
            credential = pointer.contents
            if not credential.CredentialBlobSize:
                return ""
            raw = ctypes.string_at(
                credential.CredentialBlob,
                credential.CredentialBlobSize,
            )
            try:
                return raw.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise CredentialStoreError("stored credential is not valid UTF-8") from exc
        finally:
            self._library.CredFree(pointer)

    def write(self, target: str, value: str) -> None:
        raw = value.encode("utf-8")
        blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
        credential = _CREDENTIALW(
            Flags=0,
            Type=_CRED_TYPE_GENERIC,
            TargetName=target,
            Comment="Stockroom machine credential",
            CredentialBlobSize=len(raw),
            CredentialBlob=ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte)),
            Persist=_CRED_PERSIST_LOCAL_MACHINE,
            AttributeCount=0,
            Attributes=None,
            TargetAlias=None,
            UserName="Stockroom",
        )
        try:
            if not self._library.CredWriteW(ctypes.byref(credential), 0):
                raise _win_error("write", ctypes.get_last_error())
        finally:
            ctypes.memset(blob, 0, len(raw))

    def delete(self, target: str) -> None:
        if self._library.CredDeleteW(target, _CRED_TYPE_GENERIC, 0):
            return
        error = ctypes.get_last_error()
        if error != _ERROR_NOT_FOUND:
            raise _win_error("delete", error)


def _win_error(operation: str, error: int) -> CredentialStoreError:
    detail = ctypes.FormatError(error).strip() or f"Windows error {error}"
    return CredentialStoreError(f"credential {operation} failed: {detail}")


class WindowsCredentialStore:
    """Namespaced Windows Credential Manager generic-credential store."""

    def __init__(self, namespace: str, *, api: _WindowsCredentialApi | None = None):
        self._namespace = _validate_namespace(namespace)
        self._api = api or _WindowsCredentialApi()

    def _target(self, name: str) -> str:
        return f"Stockroom/{self._namespace}/{_validate_name(name)}"

    def get(self, name: str) -> str | None:
        return self._api.read(self._target(name))

    def set(self, name: str, value: str) -> None:
        value = _validate_value(value)
        target = self._target(name)
        self._api.write(target, value)
        if self._api.read(target) != value:
            raise CredentialStoreError("credential write verification failed")

    def delete(self, name: str) -> None:
        target = self._target(name)
        self._api.delete(target)
        if self._api.read(target) is not None:
            raise CredentialStoreError("credential deletion verification failed")
