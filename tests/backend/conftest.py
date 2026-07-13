import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "kicad"


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
