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


def _default_lister() -> str:
    cmd = ["tasklist"] if os.name == "nt" else ["ps", "-A", "-o", "comm"]
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    return proc.stdout


def detect_running_kicad(lister=None) -> bool:
    """Best-effort: is a KiCad editor running (so lib-table changes need a
    restart)? Never raises; on any failure returns False."""
    try:
        text = (lister or _default_lister)().lower()
    except Exception:
        return False
    return any(tok in text for tok in _EDITOR_TOKENS)
