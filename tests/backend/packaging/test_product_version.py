from __future__ import annotations

import json
import re
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

import stockroom

ROOT = Path(__file__).resolve().parents[3]
PRODUCT_VERSION = "1.0.0"
WINDOWS_BASE_VERSION = "1.0.0.0"


def _editable_stockroom_version(lock: dict) -> str:
    package = next(
        item
        for item in lock["package"]
        if item["name"] == "stockroom" and item.get("source") == {"editable": "."}
    )
    return package["version"]


def _powershell_string_default(text: str, name: str) -> str:
    match = re.search(rf'\[string\]\${re.escape(name)}\s*=\s*"([^"]+)"', text)
    assert match is not None, f"missing ${name} string parameter default"
    return match.group(1)


def test_source_package_and_frontend_report_stockroom_1_0() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    frontend = json.loads((ROOT / "app/frontend/package.json").read_text(encoding="utf-8"))
    frontend_lock = json.loads(
        (ROOT / "app/frontend/package-lock.json").read_text(encoding="utf-8")
    )

    assert project["project"]["version"] == PRODUCT_VERSION
    assert _editable_stockroom_version(lock) == PRODUCT_VERSION
    assert stockroom.__version__ == PRODUCT_VERSION
    assert frontend["version"] == PRODUCT_VERSION
    assert frontend_lock["version"] == PRODUCT_VERSION
    assert frontend_lock["packages"][""]["version"] == PRODUCT_VERSION


def test_windows_and_release_defaults_share_the_1_0_base() -> None:
    project = ET.parse(ROOT / "app/desktop/Stockroom.WindowHost/Stockroom.WindowHost.csproj")
    properties = {item.tag: item.text for item in project.getroot().iter()}
    assert properties["Version"] == WINDOWS_BASE_VERSION
    assert properties["AssemblyVersion"] == WINDOWS_BASE_VERSION
    assert properties["FileVersion"] == WINDOWS_BASE_VERSION
    assert properties["InformationalVersion"] == PRODUCT_VERSION

    packager = (ROOT / "packaging/Build-Windows-Package.ps1").read_text(encoding="utf-8")
    retired_wrapper = (ROOT / "packaging/build_exe.ps1").read_text(encoding="utf-8")
    assert _powershell_string_default(packager, "Version") == WINDOWS_BASE_VERSION
    assert _powershell_string_default(packager, "MinimumHostVersion") == WINDOWS_BASE_VERSION
    assert _powershell_string_default(retired_wrapper, "Version") == WINDOWS_BASE_VERSION

    release = yaml.load(
        (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    metadata = next(
        step
        for step in release["jobs"]["build-windows-package"]["steps"]
        if step.get("name") == "Resolve And Validate Release Metadata"
    )
    assert metadata["env"]["AUTOMATIC_BASE_VERSION"] == PRODUCT_VERSION
    assert (
        '$version = "$($env:AUTOMATIC_BASE_VERSION).$($env:GITHUB_RUN_NUMBER)"'
        in metadata["run"]
    )

    ci = yaml.load(
        (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    fixture = next(
        step
        for step in ci["jobs"]["backend"]["steps"]
        if step.get("name") == "Run Windows package fixture"
    )
    assert f"-Version {WINDOWS_BASE_VERSION}" in fixture["run"]
    assert f"-MinimumHostVersion {WINDOWS_BASE_VERSION}" in fixture["run"]
