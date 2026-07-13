import shutil
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "kicad"


def pytest_collection_modifyitems(config, items):
    """Honestly SKIP `windows_only` tests off Windows instead of letting a no-op
    placeholder body report a misleading green: a real Windows machine (WebView2,
    KiCad config surgery) is required, so on any other platform the test is skipped,
    not silently passed."""
    if sys.platform.startswith("win"):
        return
    skip_win = pytest.mark.skip(
        reason="windows_only: needs a real Windows machine (WebView2, KiCad config surgery)"
    )
    for item in items:
        if "windows_only" in item.keywords:
            item.add_marker(skip_win)


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
