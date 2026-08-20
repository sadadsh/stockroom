from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BUILD_SCRIPT = REPOSITORY_ROOT / "packaging/Build-Windows-Package.ps1"
STORE_PUBLISHER = "CN=6586C41B-410B-4C94-8631-F025DB362E47"


def run_store_input_check(tmp_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(BUILD_SCRIPT),
            "-Mode",
            "Store",
            "-Version",
            "1.0.42.0",
            "-OutputRoot",
            str(tmp_path / "Output"),
            *arguments,
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (
            ("-Publisher", "CN=Stockroom Development"),
            "exact Partner Center publisher",
        ),
        (
            ("-FeedBaseUri", "https://sadadsh.github.io/stockroom/windows/x64"),
            "refuses direct-feed",
        ),
        (
            ("-SigningCertificatePath", "missing.pfx"),
            "refuses direct-feed",
        ),
    ],
)
def test_store_build_refuses_mixed_distribution_inputs(
    tmp_path: Path,
    arguments: tuple[str, ...],
    message: str,
) -> None:
    result = run_store_input_check(tmp_path, *arguments)

    assert result.returncode != 0
    assert message in f"{result.stdout}\n{result.stderr}"
    assert not (tmp_path / "Output").exists()


def test_store_build_reserves_the_fourth_version_component(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(BUILD_SCRIPT),
            "-Mode",
            "Store",
            "-Version",
            "1.0.42.1",
            "-OutputRoot",
            str(tmp_path / "Output"),
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "fourth component must be zero" in f"{result.stdout}\n{result.stderr}"
    assert not (tmp_path / "Output").exists()
