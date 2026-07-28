"""Credential-store port and deterministic test backend.

Production Stockroom is Windows-only, so its default backend is Windows
Credential Manager.  The in-memory backend exists for isolated tests and never
writes a secret to disk.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from threading import RLock
from typing import Protocol


class CredentialStoreError(RuntimeError):
    """A credential operation failed without exposing the credential value."""


class CredentialStore(Protocol):
    """Minimal secret-store contract used by machine configuration."""

    def get(self, name: str) -> str | None: ...

    def set(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...


_MEMORY_VALUES: dict[tuple[str, str], str] = {}
_MEMORY_LOCK = RLock()


class MemoryCredentialStore:
    """Process-local backend for tests and non-production fixtures."""

    def __init__(self, namespace: str):
        self._namespace = _validate_namespace(namespace)

    def get(self, name: str) -> str | None:
        key = (self._namespace, _validate_name(name))
        with _MEMORY_LOCK:
            return _MEMORY_VALUES.get(key)

    def set(self, name: str, value: str) -> None:
        key = (self._namespace, _validate_name(name))
        value = _validate_value(value)
        with _MEMORY_LOCK:
            _MEMORY_VALUES[key] = value

    def delete(self, name: str) -> None:
        key = (self._namespace, _validate_name(name))
        with _MEMORY_LOCK:
            _MEMORY_VALUES.pop(key, None)


def _validate_namespace(value: str) -> str:
    value = str(value)
    if not value or len(value) > 128 or "\x00" in value:
        raise ValueError("credential namespace is invalid")
    return value


def _validate_name(value: str) -> str:
    value = str(value)
    if not value or len(value) > 128 or "\x00" in value:
        raise ValueError("credential name is invalid")
    return value


def _validate_value(value: str) -> str:
    value = str(value)
    if not value or "\x00" in value:
        raise ValueError("credential value must be non-empty and contain no NUL")
    if len(value.encode("utf-8")) > 2_560:
        raise ValueError("credential value exceeds the Windows generic-credential limit")
    return value


def credential_namespace(config_path: Path) -> str:
    """Return a stable, non-secret namespace for one machine-config location."""

    resolved = str(Path(config_path).resolve(strict=False)).casefold()
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:24]
    return f"config-{digest}"


def default_credential_store(config_path: Path) -> CredentialStore:
    """Resolve the configured backend without silently using plaintext storage."""

    namespace = credential_namespace(config_path)
    backend = os.environ.get("STOCKROOM_CREDENTIALS_BACKEND", "windows").strip().casefold()
    if backend == "memory":
        return MemoryCredentialStore(namespace)
    if backend != "windows":
        raise CredentialStoreError(f"unsupported credential backend: {backend}")
    if os.name != "nt":
        raise CredentialStoreError("Windows Credential Manager is unavailable on this platform")

    from .windows import WindowsCredentialStore

    return WindowsCredentialStore(namespace)
