# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Stockroom's immutable packaged backend worker.
# BUILD ON WINDOWS through packaging/Build-Windows-Package.ps1 so the hash seed,
# PE timestamp, version resource, immutable release inputs, and output paths are
# explicit and reproducible.
#
# The native WPF executable is the sole product entry point. This on-disk
# PyInstaller runtime is never launched directly by the user; the native host
# supervises it with --port. COLLECT deliberately avoids one-file _MEI extraction.
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules


def _required_file(environment_name, fallback=None):
    candidate = os.environ.get(environment_name) or fallback
    if not candidate or not os.path.isfile(candidate):
        raise SystemExit(
            f"packaging/stockroom.spec: {environment_name} must name an existing file"
        )
    return os.path.abspath(candidate)


_frontend = os.path.abspath(
    os.path.join(SPECPATH, "..", "app", "frontend-dist")  # noqa: F821
)
if not os.path.isfile(os.path.join(_frontend, "index.html")):
    raise SystemExit(
        "packaging/stockroom.spec: committed app/frontend-dist is missing"
    )
_assets = os.path.abspath(
    os.path.join(
        SPECPATH,  # noqa: F821
        "..",
        "app",
        "backend",
        "stockroom",
        "host",
        "assets",
    )
)
if not os.path.isdir(_assets):
    raise SystemExit("packaging/stockroom.spec: host assets are missing")

_datas = [
    (_frontend, "app/frontend-dist"),
    (_assets, "stockroom/host/assets"),
]
_build_identity = _required_file("STOCKROOM_BUILD_IDENTITY")
_datas.append((_build_identity, "."))

# The release manifest carries one exact native CAD converter under Tools/.
# Do not duplicate that self-contained runtime inside the Python worker.

# Router factories, provider adapters, and the release worker are intentionally
# imported lazily by the host.  Freeze the whole first-party package so a new
# registered implementation cannot disappear merely because startup has not
# imported it yet.
_hiddenimports = collect_submodules("stockroom")

_version_file = os.environ.get("STOCKROOM_VERSION_FILE")
if _version_file:
    _version_file = _required_file("STOCKROOM_VERSION_FILE")
_icon = os.path.join(
    SPECPATH,  # noqa: F821 (SPECPATH is injected)
    "..",
    "app",
    "backend",
    "stockroom",
    "host",
    "assets",
    "stockroom.ico",
)

a = Analysis(
    ["stockroom_launcher.py"],
    pathex=[os.path.join(SPECPATH, "..", "app", "backend")],  # noqa: F821 (SPECPATH is injected)
    binaries=[],
    datas=_datas,
    hiddenimports=_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Stockroom's Windows host is WebView2/WinForms.  Exclude unrelated GUI
    # backends so optional packages on the build runner cannot alter the payload.
    excludes=[
        "_tkinter",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "gtk",
        "qtpy",
        "tkinter",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    contents_directory="Runtime",
    name="Stockroom Worker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon=_icon,
    version=_version_file,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Stockroom Worker",
)
