import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "kicad"


def _browser_available() -> bool:
    """Launch-free check that the render browsers are provisioned. LAUNCHING a browser is what
    hangs on a headless Windows CI runner (the release gate provisions Chromium/Camoufox on Linux
    only), so this only inspects the installed binaries and never starts one. Camoufox is probed
    first (a pure version lookup) so a machine with no browsers short-circuits before any Playwright
    driver process starts."""
    try:
        from camoufox.pkgman import installed_verstr

        if not installed_verstr():
            return False
    except Exception:
        return False
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            exe = p.chromium.executable_path
        return bool(exe and Path(exe).exists())
    except Exception:
        return False


_HAS_BROWSER = _browser_available()

# The `requires_browser` marker finally MEANS something: a test that launches a real render browser
# is skipped when the browsers are not provisioned, instead of hanging (Windows) or erroring. The
# marker was registered but carried no skip logic, so browser tests only self-skipped via ad-hoc
# per-file probes. This makes it uniform and is what the marker's description already promises.
requires_browser = pytest.mark.skipif(
    not _HAS_BROWSER, reason="render browsers (Playwright Chromium / Camoufox) not provisioned"
)


def pytest_collection_modifyitems(config, items):
    """Honestly SKIP every `windows_only` test in automated pytest — on EVERY platform,
    Windows CI included. These are manual Windows acceptance steps (WebView2, real KiCad
    config surgery) with placeholder bodies; letting them run their no-op `...` bodies on
    the windows-latest release gate would fabricate a green the owner forbids. The real
    acceptance is the owner running each task's acceptance bar by hand and recording it in
    the ledger, not an auto-passed empty test.

    Also skip `requires_browser` tests when the render browsers are not provisioned (the Windows
    release gate), so a real browser launch never hangs the gate. The render path is exercised on
    the Linux job where Chromium/Camoufox are installed."""
    skip_win = pytest.mark.skip(
        reason="windows_only: manual Windows acceptance step (WebView2 / real KiCad "
        "config) — run by hand per the task acceptance bar, never auto-passed in pytest"
    )
    skip_browser = pytest.mark.skip(
        reason="render browsers (Playwright Chromium / Camoufox) not provisioned on this runner"
    )
    for item in items:
        if "windows_only" in item.keywords:
            item.add_marker(skip_win)
        if not _HAS_BROWSER and "requires_browser" in item.keywords:
            item.add_marker(skip_browser)


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def tmp_fixture(tmp_path):
    """Copy a named fixture into a temp dir and return its path (for edit tests)."""

    def _copy(name: str) -> Path:
        dst = tmp_path / name
        shutil.copyfile(FIXTURES / name, dst)
        return dst

    return _copy


def _has_kicad_cli() -> bool:
    return shutil.which("kicad-cli") is not None


requires_kicad_cli = pytest.mark.skipif(
    not _has_kicad_cli(), reason="kicad-cli not installed"
)


def _has_glb_tooling() -> bool:
    """trimesh (plus cascadio for STEP) drives the 3D model → GLB preview (M6d).
    Optional tooling: an absent stack surfaces as an honest 502, so its real-model
    integration test skips rather than fabricating a pass."""
    try:
        import trimesh  # noqa: F401
    except Exception:
        return False
    return True


requires_glb_tooling = pytest.mark.skipif(
    not _has_glb_tooling(), reason="trimesh/cascadio (3D GLB tooling) not installed"
)
