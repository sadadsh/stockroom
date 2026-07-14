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
# Target prerequisites: git on PATH (a git-native app). uv is BUNDLED into the exe below, so
# the target machine does NOT need uv installed (uv also provisions Python + the app env).
import os
import shutil

# Bundle the uv binary beside the launcher so a Windows box without uv still runs (the WinError 2
# fix). Resolved from the build machine's PATH (the CI installs uv via astral-sh/setup-uv); fail
# the build loudly rather than silently ship an exe that dies at first `uv sync`.
_uv = shutil.which("uv") or shutil.which("uv.exe")
if not _uv:
    raise SystemExit("packaging/stockroom.spec: uv not found at build time; cannot bundle it")

_datas = [(_uv, ".")]  # uv -> sys._MEIPASS/uv(.exe); resolved at runtime by launcher._uv_bin

# Portable git (MinGit), fetched into packaging/mingit by the release CI, bundled so a bare
# Windows box needs NO system git (clone + the in-app self-update use it via launcher._git_bin,
# and the host's git ops resolve it through launcher._child_env's PATH prepend). Optional on a
# local/dev build: absent, git from PATH is used instead. -> sys._MEIPASS/mingit/cmd/git.exe.
_mingit = os.path.join(SPECPATH, "mingit")  # noqa: F821 (SPECPATH is injected)
if os.path.isdir(_mingit):
    _datas.append((_mingit, "mingit"))

# The WebView2 Evergreen Bootstrapper (~2 MB, fetched into packaging/webview2 by the release
# CI), bundled so a bare Windows box with no WebView2 runtime can install it silently before the
# host opens its window (launcher.ensure_webview2). Optional on a local/dev build.
_wv2 = os.path.join(SPECPATH, "webview2", "MicrosoftEdgeWebview2Setup.exe")  # noqa: F821
if os.path.isfile(_wv2):
    _datas.append((_wv2, "webview2"))  # -> sys._MEIPASS/webview2/MicrosoftEdgeWebview2Setup.exe

a = Analysis(
    ["stockroom_launcher.py"],
    pathex=[os.path.join(SPECPATH, "..", "app", "backend")],  # noqa: F821 (SPECPATH is injected)
    binaries=[],
    datas=_datas,
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
    upx=False,  # an unsigned UPX-packed onefile bundling git.exe is a classic AV false positive
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # windowed: no console flash when the user double-clicks it
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
