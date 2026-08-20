from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

import pytest

import packaging.release_bundle as release_bundle
from packaging.package_contract import PackageConfiguration, render_contract
from packaging.release_bundle import ReleaseBundleError, build_release_bundle

ROOT = Path(__file__).resolve().parents[3]
SOURCE_ICON = ROOT / "app/backend/stockroom/host/assets/stockroom.ico"


def _write_runtime(root: Path, files: dict[str, bytes]) -> Path:
    for relative, contents in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
    return root


def _build_fixture(tmp_path: Path) -> tuple[Path, dict[str, bytes]]:
    declared = {
        "./Backend/Stockroom Worker.exe": b"MZworker",
        "./Backend/_internal/python312.dll": b"worker-python-runtime",
        "./WindowHost/Stockroom.WindowHost.exe": b"MZwindow-host",
        "./WindowHost/runtimes/win-x64/native/WebView2Loader.dll": b"webview-loader",
        "./Tools/CadConverter/Stockroom.CadConverter.exe": b"MZcad-converter",
        "./Tools/CadConverter/Stockroom.CadConverter.dll": b"cad-converter-runtime",
        "./Tools/gh.exe": b"MZgithub-cli",
    }
    worker = _write_runtime(
        tmp_path / "Worker",
        {
            "Stockroom Worker.exe": declared["./Backend/Stockroom Worker.exe"],
            "_internal/python312.dll": declared["./Backend/_internal/python312.dll"],
        },
    )
    window_host = _write_runtime(
        tmp_path / "Window Host",
        {
            "Stockroom.WindowHost.exe": declared["./WindowHost/Stockroom.WindowHost.exe"],
            "runtimes/win-x64/native/WebView2Loader.dll": declared[
                "./WindowHost/runtimes/win-x64/native/WebView2Loader.dll"
            ],
        },
    )
    cad_converter = _write_runtime(
        tmp_path / "CAD Converter",
        {
            "Stockroom.CadConverter.exe": declared[
                "./Tools/CadConverter/Stockroom.CadConverter.exe"
            ],
            "Stockroom.CadConverter.dll": declared[
                "./Tools/CadConverter/Stockroom.CadConverter.dll"
            ],
        },
    )
    github_cli = _write_runtime(
        tmp_path / "GitHub CLI",
        {
            "bin/gh.exe": declared["./Tools/gh.exe"],
            "LICENSE": b"MIT License\n",
        },
    )
    bundle = tmp_path / "Bundle"
    build_release_bundle(
        mode="Fixture",
        executable=worker,
        window_host_root=window_host,
        cad_converter_root=cad_converter,
        github_cli_root=github_cli,
        bundle_root=bundle,
        version="1.2.3.4",
        minimum_host_version="1.0.0.0",
        feed_base_uri="https://updates.example.invalid/stockroom/x64",
        source_revision="0123456789012345678901234567890123456789",
        source_date_epoch=1704067200,
        tuf_root_path=None,
    )
    return bundle / "Initial Release" / "release-1.2.3.4", declared


def _sbom(release: Path) -> dict:
    return json.loads((release / "Support/SBOM.spdx.json").read_text(encoding="ascii"))


def _package_by_name(sbom: dict, name: str) -> dict:
    return next(package for package in sbom["packages"] if package["name"] == name)


def _frontend_lock(tmp_path: Path, packages: dict[str, dict]) -> Path:
    path = tmp_path / "package-lock.json"
    path.write_text(
        json.dumps(
            {
                "name": "target-fixture",
                "version": "1.0.0",
                "lockfileVersion": 3,
                "packages": packages,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_spdx_inventory_and_verification_code_cover_every_shipped_runtime_file(
    tmp_path: Path,
) -> None:
    release, declared = _build_fixture(tmp_path)
    sbom = _sbom(release)
    files = {item["fileName"]: item for item in sbom["files"]}

    manifest = json.loads((release / "Release Manifest.json").read_text(encoding="ascii"))
    manifest_files = {f'./{member["path"]}' for member in manifest["members"]}
    sbom_file = "./Support/SBOM.spdx.json"
    window_host_files = {name for name in declared if name.startswith("./WindowHost/")}
    # The SPDX document is the sole circular exclusion. Every release-manifest member plus the
    # separately MSIX-owned WindowHost payload must otherwise be represented as an analyzed file.
    assert set(files) == (manifest_files - {sbom_file}) | window_host_files
    assert _package_by_name(sbom, "Stockroom")["packageVerificationCode"][
        "packageVerificationCodeExcludedFiles"
    ] == [sbom_file]

    expected_sha1_values: list[str] = []
    for name in files:
        contents = declared.get(name)
        if contents is None:
            contents = (release / name.removeprefix("./")).read_bytes()
        expected_sha1 = hashlib.sha1(contents, usedforsecurity=False).hexdigest()  # noqa: S324
        expected_sha1_values.append(expected_sha1)
        assert {item["algorithm"]: item["checksumValue"] for item in files[name]["checksums"]}[
            "SHA1"
        ] == expected_sha1

    expected_verification_code = hashlib.sha1(  # noqa: S324 - SPDX 2.3 algorithm
        "".join(sorted(expected_sha1_values)).encode("ascii"),
        usedforsecurity=False,
    ).hexdigest()
    assert _package_by_name(sbom, "Stockroom")["packageVerificationCode"][
        "packageVerificationCodeValue"
    ] == expected_verification_code
    assert all(
        "MSIX" in files[name]["comment"] and "TUF release-set member" in files[name]["comment"]
        for name in files
        if name.startswith("./WindowHost/")
    )


def test_spdx_dependency_graph_uses_only_locked_production_dependencies(
    tmp_path: Path,
) -> None:
    release, _ = _build_fixture(tmp_path)
    sbom = _sbom(release)
    packages = {(item["name"], item.get("versionInfo")): item for item in sbom["packages"]}

    assert ("fastapi", "0.139.0") in packages
    assert ("react", "19.0.0") in packages
    assert ("@tabler/icons", "3.46.0") in packages
    assert not {"pytest", "ruff", "pyinstaller", "vite", "vitest", "typescript"} & {
        item["name"] for item in sbom["packages"]
    }

    relationships = {
        (
            item["spdxElementId"],
            item["relationshipType"],
            item["relatedSpdxElement"],
        )
        for item in sbom["relationships"]
    }
    stockroom_id = _package_by_name(sbom, "Stockroom")["SPDXID"]
    frontend_id = _package_by_name(sbom, "stockroom-frontend")["SPDXID"]
    assert (stockroom_id, "DEPENDS_ON", packages[("fastapi", "0.139.0")]["SPDXID"]) in relationships
    assert (frontend_id, "DEPENDS_ON", packages[("react", "19.0.0")]["SPDXID"]) in relationships
    assert all(item["SPDXID"].startswith("SPDXRef-Package-") for item in sbom["packages"])


def test_frontend_spdx_keeps_only_win32_x64_optional_binaries(tmp_path: Path) -> None:
    release, _ = _build_fixture(tmp_path)
    names = {item["name"] for item in _sbom(release)["packages"]}

    assert "@napi-rs/canvas-win32-x64-msvc" in names
    assert not {
        "@napi-rs/canvas-android-arm64",
        "@napi-rs/canvas-darwin-arm64",
        "@napi-rs/canvas-darwin-x64",
        "@napi-rs/canvas-linux-arm-gnueabihf",
        "@napi-rs/canvas-linux-arm64-gnu",
        "@napi-rs/canvas-linux-arm64-musl",
        "@napi-rs/canvas-linux-riscv64-gnu",
        "@napi-rs/canvas-linux-x64-gnu",
        "@napi-rs/canvas-linux-x64-musl",
        "@napi-rs/canvas-win32-arm64-msvc",
    } & names


def test_frontend_spdx_honors_positive_and_negated_target_constraints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock = _frontend_lock(
        tmp_path,
        {
            "": {
                "name": "target-fixture",
                "version": "1.0.0",
                "dependencies": {"runtime": "1.0.0"},
            },
            "node_modules/runtime": {
                "version": "1.0.0",
                "license": "MIT",
                "dependencies": {"win-x64": "1.0.0"},
                "optionalDependencies": {
                    "blocked-by-os": "1.0.0",
                    "blocked-by-cpu": "1.0.0",
                },
            },
            "node_modules/win-x64": {
                "version": "1.0.0",
                "license": "MIT",
                "os": ["win32", "!darwin"],
                "cpu": ["x64", "!arm64"],
            },
            "node_modules/blocked-by-os": {
                "version": "1.0.0",
                "license": "MIT",
                "optional": True,
                "os": ["!win32"],
            },
            "node_modules/blocked-by-cpu": {
                "version": "1.0.0",
                "license": "MIT",
                "optional": True,
                "cpu": ["!x64"],
            },
        },
    )
    monkeypatch.setattr(release_bundle, "_FRONTEND_LOCK", lock)

    packages, relationships = release_bundle._frontend_dependency_evidence()
    names = {item["name"] for item in packages}
    assert names == {"target-fixture", "runtime", "win-x64"}
    by_id = {item["SPDXID"]: item["name"] for item in packages}
    edges = {
        (by_id[item["spdxElementId"]], by_id[item["relatedSpdxElement"]])
        for item in relationships
        if item["spdxElementId"] in by_id
    }
    assert edges == {
        ("target-fixture", "runtime"),
        ("runtime", "win-x64"),
    }


@pytest.mark.parametrize(
    "required_package",
    [
        None,
        {
            "version": "1.0.0",
            "license": "MIT",
            "os": ["!win32"],
            "cpu": ["x64"],
        },
    ],
)
def test_frontend_spdx_rejects_a_missing_or_target_inapplicable_required_edge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    required_package: dict | None,
) -> None:
    packages = {
        "": {
            "name": "target-fixture",
            "version": "1.0.0",
            "dependencies": {"required-runtime": "1.0.0"},
        }
    }
    if required_package is not None:
        packages["node_modules/required-runtime"] = required_package
    lock = _frontend_lock(tmp_path, packages)
    monkeypatch.setattr(release_bundle, "_FRONTEND_LOCK", lock)

    with pytest.raises(
        ReleaseBundleError,
        match="required frontend production dependency is unavailable for win32/x64",
    ):
        release_bundle._frontend_dependency_evidence()


def test_packaged_notices_license_and_worker_version_metadata_are_truthful(
    tmp_path: Path,
) -> None:
    release, _ = _build_fixture(tmp_path)
    notices = (release / "Support/Third Party Notices.txt").read_text(encoding="utf-8")
    assert "Tabler Outline 3.46.0" in notices
    assert "@iconify-json/tabler 1.2.38 (Tabler Icons 3.45.0)" in notices
    assert "@iconify-json/lucide 1.2.123" in notices
    assert "@iconify-json/material-symbols 1.2.88" in notices
    assert "@iconify-json/ph 1.2.2 (Phosphor 2.1.1)" in notices
    assert "@iconify-json/simple-icons 1.2.93 (Simple Icons 16.28.0)" in notices
    assert "circle-arrow-up-right-filled" not in notices

    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "All rights reserved." in license_text
    assert "No permission is granted" in license_text
    assert "Permission is hereby granted" not in license_text
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["license"] == {"file": "LICENSE"}
    assert (release / "Support/Licenses/Stockroom Proprietary.txt").read_text(
        encoding="utf-8"
    ) == license_text
    stockroom_package = _package_by_name(_sbom(release), "Stockroom")
    assert stockroom_package["licenseDeclared"] == "LicenseRef-Stockroom-Proprietary"

    package_root = tmp_path / "Package"
    version_info = tmp_path / "StockroomVersionInfo.txt"
    render_contract(
        PackageConfiguration.for_mode(
            mode="Fixture",
            publisher="CN=Stockroom Development",
            version="1.2.3.4",
            feed_base_uri="https://updates.example.invalid/stockroom/x64",
            signing_certificate_provided=False,
        ),
        template_directory=ROOT / "packaging",
        package_root=package_root,
        appinstaller_path=tmp_path / "Stockroom.Development.appinstaller",
        version_info_path=version_info,
        source_icon=SOURCE_ICON,
    )
    rendered_version = version_info.read_text(encoding="utf-8")
    assert 'StringStruct("FileDescription", "Stockroom Worker")' in rendered_version
    assert 'StringStruct("InternalName", "Stockroom Worker")' in rendered_version
    assert 'StringStruct("OriginalFilename", "Stockroom Worker.exe")' in rendered_version
    assert "bootstrap" not in rendered_version.casefold()


def test_packaged_geist_mono_font_carries_its_exact_upstream_license(
    tmp_path: Path,
) -> None:
    release, _ = _build_fixture(tmp_path)

    notices = (release / "Support/Third Party Notices.txt").read_text(encoding="utf-8")
    assert "@fontsource-variable/geist-mono 5.3.0" in notices
    assert "License: SIL Open Font License 1.1" in notices

    license_path = release / "Support/Licenses/Geist Mono OFL-1.1.txt"
    assert hashlib.sha256(license_path.read_bytes()).hexdigest() == (
        "cc815ed4fc045f0e991abb10395b7932bd028c6a067deb13316d6002105074e6"
    )
    assert license_path.read_text(encoding="utf-8").startswith(
        "Copyright 2024 The Geist Project Authors"
    )

    manifest = json.loads((release / "Release Manifest.json").read_text(encoding="ascii"))
    members = {member["path"]: member for member in manifest["members"]}
    assert members["Support/Licenses/Geist Mono OFL-1.1.txt"]["kind"] == "license"
