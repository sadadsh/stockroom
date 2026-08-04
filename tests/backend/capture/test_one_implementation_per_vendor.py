"""Provider acquisition has one production browser owner.

The API-owned capture package hosts provider pages in ``PlaywrightCaptureBrowser``. The native
pywebview shell must never grow a second provider window, download watcher, injected driver, or
frontend callback bridge.
"""

from __future__ import annotations

from pathlib import Path

from stockroom.capture.vendors import all_adapters

_ROOT = Path(__file__).resolve().parents[3]
_HOST = _ROOT / "app" / "backend" / "stockroom" / "host"
_FRONTEND = _ROOT / "app" / "frontend"
_FRONTEND_DIST = _ROOT / "app" / "frontend-dist"

_RETIRED_HOST_PATHS = (
    _HOST / "win_live_capture.py",
    _HOST / "win_run_capture.py",
    _HOST / "download_capture.py",
    _HOST / "overlay.py",
    _HOST / "vendor_drivers",
)
_RETIRED_CONTRACTS = (
    "open_cad_download",
    "__STOCKROOM_CAD_DOWNLOAD__",
    "_CAD_WINDOW",
    "_install_cad_download_intercept",
    "DownloadsWatch",
    "build_overlay_js",
    "build_driver_js",
)


def test_retired_native_provider_browser_does_not_exist():
    found = [str(path.relative_to(_ROOT)) for path in _RETIRED_HOST_PATHS if path.exists()]
    assert found == [], f"retired pywebview provider implementation returned: {found}"


def test_native_shell_has_no_provider_capture_dependency_or_bridge():
    source = (_HOST / "window.py").read_text(encoding="utf-8")
    found = [contract for contract in _RETIRED_CONTRACTS if contract in source]
    assert "stockroom.capture" not in source
    assert found == [], f"native shell still owns provider capture contracts: {found}"


def test_frontend_implementation_and_built_bundle_have_no_native_capture_bridge():
    implementation_paths = (
        _FRONTEND / "src" / "lib" / "runtime.ts",
        _FRONTEND / "src" / "lib" / "capture.tsx",
        _FRONTEND / "src" / "components" / "AppShell.tsx",
    )
    built_paths = tuple(_FRONTEND_DIST.glob("assets/*.js"))
    assert built_paths, "committed frontend bundle has no JavaScript assets"
    forbidden = (
        "open_cad_download",
        "__STOCKROOM_CAD_DOWNLOAD__",
        "__STOCKROOM_NATIVE_DROP__",
        "pywebview.api",
    )
    found: list[str] = []
    for path in (*implementation_paths, *built_paths):
        source = path.read_text(encoding="utf-8")
        for contract in forbidden:
            if contract in source:
                found.append(f"{path.relative_to(_ROOT)}:{contract}")
    assert found == [], f"frontend still carries a native capture bridge: {found}"


def test_every_adapter_names_an_exact_export_for_every_tool_it_claims():
    """Every claimed tool names the exact visible export the PERSON has to take.

    A wrong version pick downloads a file that fails much later, far from the cause, so the
    choice is declared data rather than left to whoever is looking at the page.
    """

    adapters = all_adapters()
    assert adapters, "the Python provider adapter registry is empty"
    for adapter in adapters:
        capability = adapter.capability
        for tool in capability.tools:
            assert capability.user_format_labels.get(tool), (
                f"{capability.key} claims to serve {tool} but names no exact export"
            )
