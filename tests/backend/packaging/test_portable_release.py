from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from packaging.portable_release import PortableReleaseError, build_portable_release


def _msix(path: Path, *, unsafe: bool = False) -> None:
    members = {
        "WindowHost/Stockroom.WindowHost.exe": b"MZhost",
        "WindowHost/Stockroom.WindowHost.dll": b"host-dll",
        "WindowHost/runtime.dll": b"runtime",
        "Update/Update%20Feed.json": b"{}",
        "Update/Initial%20Release/release-1/Backend/Stockroom%20Worker.exe": b"MZworker",
        "Assets/StoreLogo.png": b"ignored",
        "AppxManifest.xml": b"ignored",
    }
    if unsafe:
        members["WindowHost/../escaped.txt"] = b"bad"
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)


def test_portable_release_is_deterministic_and_opens_with_stockroom_exe(tmp_path: Path) -> None:
    package = tmp_path / "Stockroom.msix"
    first = tmp_path / "First.zip"
    second = tmp_path / "Second.zip"
    _msix(package)

    evidence = build_portable_release(package, first)
    build_portable_release(package, second)

    assert first.read_bytes() == second.read_bytes()
    assert evidence["schema"] == "stockroom-portable-release/1"
    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == sorted(archive.namelist())
        assert archive.read("Stockroom.exe") == b"MZhost"
        assert "Stockroom.WindowHost.exe" not in archive.namelist()
        assert "Update/Update Feed.json" in archive.namelist()
        assert "Update/Initial Release/release-1/Backend/Stockroom Worker.exe" in archive.namelist()
        assert all(not name.startswith("Assets/") for name in archive.namelist())


def test_portable_release_rejects_unsafe_package_members(tmp_path: Path) -> None:
    package = tmp_path / "Unsafe.msix"
    _msix(package, unsafe=True)

    with pytest.raises(PortableReleaseError, match="unsafe"):
        build_portable_release(package, tmp_path / "Portable.zip")
