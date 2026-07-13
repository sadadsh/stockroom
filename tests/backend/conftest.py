import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "kicad"


def pytest_collection_modifyitems(config, items):
    """Honestly SKIP every `windows_only` test in automated pytest — on EVERY platform,
    Windows CI included. These are manual Windows acceptance steps (WebView2, real KiCad
    config surgery) with placeholder bodies; letting them run their no-op `...` bodies on
    the windows-latest release gate would fabricate a green the owner forbids. The real
    acceptance is the owner running each task's acceptance bar by hand and recording it in
    the ledger, not an auto-passed empty test."""
    skip_win = pytest.mark.skip(
        reason="windows_only: manual Windows acceptance step (WebView2 / real KiCad "
        "config) — run by hand per the task acceptance bar, never auto-passed in pytest"
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
