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


def kicad_config_dir(version: str = "10.0", override: str = "") -> Path:
    if override:
        return Path(override)
    if _os_name() == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "kicad" / version
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(xdg) / "kicad" / version


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
