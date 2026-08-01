"""Locate the KiCad per-user config directory and detect a running KiCad.

Verified layout: %APPDATA%\\kicad\\10.0\\ on Windows, ~/.config/kicad/10.0/ on
Linux (spec section 4). A Settings override wins over both.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_EDITOR_TOKENS = ("kicad", "pcbnew", "eeschema", "kicad-cli")


def _os_name() -> str:
    return os.name


def _version_key(name: str) -> tuple[int, ...]:
    """Numeric sort key for version-named dirs so 10.0 ranks above 9.0 (a plain
    string sort would pick 9.0 as 'newest'). Mirrors kicad/cli.py discovery."""
    return tuple(int(p) if p.isdigit() else -1 for p in name.split("."))


def detect_kicad_version(base: Path) -> str | None:
    """The newest version-named config dir under KiCad's config base (the KiCad the
    user actually runs), or None when KiCad has never run on this machine."""
    try:
        dirs = [d for d in Path(base).iterdir() if d.is_dir() and d.name[:1].isdigit()]
    except OSError:
        return None
    if not dirs:
        return None
    return max(dirs, key=lambda d: _version_key(d.name)).name


def kicad_config_dir(version: str | None = None, override: str = "") -> Path:
    """The per-user KiCad config dir. An explicit Settings override wins; otherwise
    the newest installed version's dir under the OS base, defaulting to 10.0 when
    KiCad has never run (its first run then merges our files)."""
    if override:
        return Path(override)
    if _os_name() == "nt":
        base_str = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base_str = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    base = Path(base_str) / "kicad"
    if version is None:
        version = detect_kicad_version(base) or "10.0"
    return base / version


def _windows_process_names() -> str:
    """Every running image name, read straight from the process snapshot API.

    `tasklist` measured 6.75 s on the owner's machine, which runs ~3,600 processes: it enumerates
    them all and then FORMATS them into a table. The same snapshot through kernel32 measured
    82 ms. That difference is not cosmetic - this runs inside `GET /api/system/info`, where six
    seconds is past the client's default read timeout, so the endpoint was timing out rather than
    answering. Raises on any failure so the caller can fall back to the command.
    """

    import ctypes
    import ctypes.wintypes as wintypes

    class _ProcessEntry32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_char * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if snapshot in (0, -1, ctypes.c_void_p(-1).value):
        raise OSError("could not snapshot the process list")
    names: list[str] = []
    try:
        entry = _ProcessEntry32()
        entry.dwSize = ctypes.sizeof(_ProcessEntry32)
        if kernel32.Process32First(snapshot, ctypes.byref(entry)):
            while True:
                names.append(entry.szExeFile.decode("latin-1", "replace"))
                if not kernel32.Process32Next(snapshot, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snapshot)
    return "\n".join(names)


def _default_lister() -> str:
    if os.name == "nt":
        try:
            return _windows_process_names()
        except Exception:  # noqa: BLE001 - the command below is the portable fallback
            pass
    cmd = ["tasklist"] if os.name == "nt" else ["ps", "-A", "-o", "comm"]
    # Bounded: this is a best-effort hint, and an unbounded process enumeration behind a request
    # handler is what let a slow machine hold the endpoint open past its client's timeout.
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=10,
    )
    return proc.stdout


def detect_running_kicad(lister=None) -> bool:
    """Best-effort: is a KiCad editor running (so lib-table changes need a
    restart)? Never raises; on any failure returns False."""
    try:
        text = (lister or _default_lister)().lower()
    except Exception:
        return False
    return any(tok in text for tok in _EDITOR_TOKENS)
