# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Stockroom frozen-once launcher (M9e). BUILD ON WINDOWS:
#   uv run --with pyinstaller pyinstaller packaging/stockroom.spec --noconfirm --clean
# Produces dist/Stockroom.exe: a portable, single-file, windowed launcher.
#
# The exe is intentionally TINY: it bundles only stockroom.launcher.* + stdlib. The app's
# heavy deps (FastAPI, uvicorn, pywebview, trimesh, ...) live in the git working copy the
# launcher clones + self-updates and runs via `uv run`, never inside this exe. That is the
# "frozen once" model (spec section 12): the exe never needs re-freezing per release.
#
# Target prerequisites: git + uv on PATH (a git-native app; uv provisions the app env).
import os

a = Analysis(
    ["stockroom_launcher.py"],
    pathex=[os.path.join(SPECPATH, "..", "app", "backend")],  # noqa: F821 (SPECPATH is injected)
    binaries=[],
    datas=[],
    hiddenimports=["stockroom.launcher.launch", "stockroom.launcher.exit_codes"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Belt-and-suspenders: the launcher never imports these, but excluding them guarantees a
    # stray transitive reference can never bloat the "tiny launcher" into the whole backend.
    excludes=[
        "fastapi", "uvicorn", "starlette", "pydantic", "pydantic_core", "sse_starlette",
        "webview", "pywebview", "PyQt5", "numpy", "trimesh", "cascadio",
        "easyeda2kicad", "curl_cffi", "pypdf", "httpx",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Stockroom",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # windowed: no console flash when the user double-clicks it
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
