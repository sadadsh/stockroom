"""Frozen launcher entry point (M9e). PyInstaller freezes THIS tiny script into the portable
Stockroom.exe: it clones / self-updates the app repo working copy and runs the WebView2 host
from it via `uv`, so the heavy backend deps live in that checkout, never inside the exe.

Intentionally imports only stockroom.launcher.* (leaf, stdlib-only) so the frozen exe stays
small and never drags FastAPI / pywebview into itself. A fatal error becomes a clean native
message box, never a raw PyInstaller traceback dialog (the exe is windowed, console=False).
"""

from __future__ import annotations

import ctypes
import sys

if not getattr(sys, "frozen", False):
    # Running from source (not the frozen exe): make the in-repo stockroom package importable.
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "backend"))

from stockroom.launcher.launch import main  # noqa: E402


def _fatal(message: str) -> None:
    """Show a clean native error dialog on Windows; fall back to stderr elsewhere."""
    try:
        ctypes.windll.user32.MessageBoxW(None, message, "Stockroom could not start", 0x10)
    except Exception:  # noqa: BLE001 - non-Windows / no user32: fall back to stderr
        sys.stderr.write(message + "\n")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - top-level: a clean dialog, never a raw traceback
        _fatal(
            "Stockroom needs internet on first launch to download its app files and set up its "
            "environment. If you are online and this keeps happening, the details below may help.\n\n"
            + str(exc)
        )
        raise SystemExit(1)
