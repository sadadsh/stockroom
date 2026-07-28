"""Operating-system ports for Stockroom's per-user service control plane.

The coordinator core deliberately does not own a concrete named-mutex adapter
yet.  A correct Windows adapter must create a current-user-scoped named mutex,
surface ``WAIT_ABANDONED`` distinctly, and retain the kernel handle until
release.  Keeping that boundary explicit prevents an ordinary process-local
lock from being mistaken for the liveness authority during early integration.
"""

from __future__ import annotations

import csv
import ctypes
import os
import re
import subprocess
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

_WINDOWS_SID_PATTERN = re.compile(r"S-\d+(?:-\d+){2,15}", re.ASCII)
_DRIVE_FIXED = 3


def is_windows_sid(value: object) -> bool:
    """Return whether *value* is a canonical textual Windows SID."""

    return (
        type(value) is str
        and 5 <= len(value) <= 184
        and _WINDOWS_SID_PATTERN.fullmatch(value) is not None
    )


@runtime_checkable
class CurrentIdentityPort(Protocol):
    """Resolve the Windows SID of the user running this process."""

    def current_sid(self) -> str:
        """Return the current user's canonical SID."""


class WindowsCurrentIdentity:
    """Resolve the current SID with the fixed Windows ``whoami.exe`` binary."""

    def current_sid(self) -> str:
        if os.name != "nt":
            raise OSError("Windows identity resolution is unavailable")

        system_directory = ctypes.create_unicode_buffer(32_768)
        length = ctypes.windll.kernel32.GetSystemDirectoryW(  # type: ignore[attr-defined]
            system_directory,
            len(system_directory),
        )
        if length <= 0 or length >= len(system_directory):
            raise OSError("Windows system directory resolution failed")

        whoami = Path(system_directory.value) / "whoami.exe"
        completed = subprocess.run(
            [str(whoami), "/user", "/fo", "csv", "/nh"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        rows = list(csv.reader(completed.stdout.splitlines()))
        matching = [field.strip() for row in rows for field in row if is_windows_sid(field.strip())]
        if len(matching) != 1:
            raise OSError("Windows identity output was invalid")
        return matching[0]


@runtime_checkable
class StoragePolicyPort(Protocol):
    """Validate and canonicalize a control-database path without creating it."""

    def validate(self, database: Path) -> Path:
        """Return a canonical path only when it is on an allowed volume."""


class WindowsLocalNtfsStorage:
    """Require a resolved path on a fixed, local NTFS Windows volume."""

    def validate(self, database: Path) -> Path:
        if os.name != "nt":
            raise OSError("Windows local-NTFS validation is unavailable")

        resolved = database.resolve(strict=False)
        if str(resolved).startswith("\\\\"):
            raise OSError("Network paths are not valid service storage")

        probe = resolved.parent
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        if not probe.exists():
            raise OSError("No existing storage ancestor was found")

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        volume_path = ctypes.create_unicode_buffer(32_768)
        if not kernel32.GetVolumePathNameW(str(probe), volume_path, len(volume_path)):
            raise OSError("Windows volume resolution failed")
        if kernel32.GetDriveTypeW(volume_path.value) != _DRIVE_FIXED:
            raise OSError("Service storage is not on a fixed local drive")

        filesystem_name = ctypes.create_unicode_buffer(256)
        if not kernel32.GetVolumeInformationW(
            volume_path.value,
            None,
            0,
            None,
            None,
            None,
            filesystem_name,
            len(filesystem_name),
        ):
            raise OSError("Windows filesystem resolution failed")
        if filesystem_name.value.casefold() != "ntfs":
            raise OSError("Service storage is not on NTFS")
        return resolved


class MutexAcquireResult(str, Enum):
    """Outcome of one non-blocking Windows named-mutex claim."""

    CREATED = "created"
    ACQUIRED = "acquired"
    ABANDONED = "abandoned"
    BUSY = "busy"


@runtime_checkable
class NamedMutexHandlePort(Protocol):
    """One process's retained handle to the per-user coordinator mutex."""

    def try_acquire(self) -> MutexAcquireResult:
        """Attempt a non-blocking claim, preserving abandoned-owner evidence."""

    def release(self) -> None:
        """Release a claim owned by this handle."""


@runtime_checkable
class NamedMutexFactoryPort(Protocol):
    """Open the named mutex with an ACL restricted to the supplied SID."""

    def open_current_user(
        self,
        *,
        name: str,
        sid: str,
    ) -> NamedMutexHandlePort:
        """Open a non-acquiring handle for the current user's named mutex."""
