# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Stockroom's stable Windows bootstrap payload.
# BUILD ON WINDOWS through packaging/Build-Windows-Package.ps1 so the hash seed,
# PE timestamp, version resource, immutable release inputs, and output paths are
# explicit and reproducible.
#
# The frozen executable is both the stable broker/window host and, when invoked
# with --port, the immutable release worker.  It contains the complete backend
# and committed frontend rather than provisioning a mutable Git checkout.
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
_uv = _required_file("STOCKROOM_UV_EXECUTABLE")
_datas.append((_uv, "."))
_datas += collect_data_files("webview")

# Owner Dev Mode builds the source-backed frontend before committing it. Carry
# a pinned portable Node/npm runtime so that action works on a clean Windows PC
# without a machine-wide Node installation.
_node = os.environ.get("STOCKROOM_NODE_ROOT")
if _node:
    _node = os.path.abspath(_node)
    if not os.path.isfile(os.path.join(_node, "node.exe")) or not os.path.isfile(
        os.path.join(_node, "npm.cmd")
    ):
        raise SystemExit(
            "packaging/stockroom.spec: STOCKROOM_NODE_ROOT must contain node.exe and npm.cmd"
        )
    _datas.append((_node, "node"))

# The continuously updated source host cannot build the native P-CAD converter
# on a user's machine.  Carry the exact self-contained publish in the stable
# launcher so first launch can provision it under LocalAppData before capture
# starts.  This is required in every distributable build, including unsigned
# owner fixtures; putting it only in the sibling MSIX release tree left the
# standalone EXE unable to publish Ultra Librarian `.lia` packages.
_cad_converter = os.environ.get("STOCKROOM_CAD_CONVERTER_ROOT")
if not _cad_converter:
    raise SystemExit(
        "packaging/stockroom.spec: STOCKROOM_CAD_CONVERTER_ROOT must name the native converter publish"
    )
_cad_converter = os.path.abspath(_cad_converter)
if not os.path.isfile(os.path.join(_cad_converter, "Stockroom.CadConverter.exe")):
    raise SystemExit(
        "packaging/stockroom.spec: STOCKROOM_CAD_CONVERTER_ROOT has no Stockroom.CadConverter.exe"
    )
_datas.append((_cad_converter, "cad-converter"))

# Git is a product dependency for the user's library repository, independent
# of application delivery.  Production carries a pinned MinGit so a clean
# Windows machine never depends on PATH.  WebView2's Evergreen bootstrapper is
# retained for machines whose runtime is absent.
_mingit = os.environ.get("STOCKROOM_MINGIT_ROOT")
if _mingit:
    _mingit = os.path.abspath(_mingit)
    if not os.path.isfile(os.path.join(_mingit, "cmd", "git.exe")):
        raise SystemExit(
            "packaging/stockroom.spec: STOCKROOM_MINGIT_ROOT has no cmd/git.exe"
        )
    _datas.append((_mingit, "mingit"))

_wv2 = os.environ.get("STOCKROOM_WEBVIEW2_BOOTSTRAPPER")
if _wv2:
    _wv2 = _required_file("STOCKROOM_WEBVIEW2_BOOTSTRAPPER")
    _datas.append((_wv2, "webview2"))

# Router factories, provider adapters, and the release worker are intentionally
# imported lazily by the host.  Freeze the whole first-party package so a new
# registered implementation cannot disappear merely because startup has not
# imported it yet.
_hiddenimports = collect_submodules("stockroom")
_hiddenimports += collect_submodules("webview")

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
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "gtk",
        "qtpy",
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
    icon=_icon,
    version=_version_file,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
