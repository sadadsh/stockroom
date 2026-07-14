"""Frozen launcher entry point (M9e). PyInstaller freezes THIS tiny script into the portable
Stockroom.exe: it clones / self-updates the app repo working copy and runs the WebView2 host
from it via `uv`, so the heavy backend deps live in that checkout, never inside the exe.

Intentionally imports only stockroom.launcher.* (leaf, stdlib-only) so the frozen exe stays
small and never drags FastAPI / pywebview into itself.
"""

from __future__ import annotations

import sys

if not getattr(sys, "frozen", False):
    # Running from source (not the frozen exe): make the in-repo stockroom package importable.
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "backend"))

from stockroom.launcher.launch import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
