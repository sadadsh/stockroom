from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest
from PIL import Image

from packaging.package_contract import (
    APPINSTALLER_NAMESPACE,
    BASE_ASSETS,
    PACKAGE_NAMESPACE,
    SHELL_TARGET_SIZES,
    PackageConfiguration,
    PackageContractError,
    inventory_tree,
    normalize_msix_timestamps,
    render_contract,
    validate_rendered_contract,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_DIRECTORY = REPOSITORY_ROOT / "packaging"
SOURCE_ICON = REPOSITORY_ROOT / "app/backend/stockroom/host/assets/stockroom.ico"
BUILD_SCRIPT = REPOSITORY_ROOT / "packaging/Build-Windows-Package.ps1"
PORTABLE_BUILD_SCRIPT = REPOSITORY_ROOT / "packaging/build_exe.ps1"


def fixture_configuration() -> PackageConfiguration:
    return PackageConfiguration.for_mode(
        mode="Fixture",
        publisher="CN=Stockroom Development",
        version="0.1.2.3",
        feed_base_uri="https://updates.example.invalid/stockroom/development/x64",
        signing_certificate_provided=False,
    )


def store_configuration() -> PackageConfiguration:
    return PackageConfiguration.for_mode(
        mode="Store",
        publisher="CN=6586C41B-410B-4C94-8631-F025DB362E47",
        version="1.0.42.0",
        feed_base_uri="",
        signing_certificate_provided=False,
    )


def render_fixture(root: Path) -> tuple[Path, Path, Path]:
    package_root = root / "Package"
    appinstaller = root / "Stockroom.Development.appinstaller"
    version_info = root / "StockroomVersionInfo.txt"
    render_contract(
        fixture_configuration(),
        template_directory=TEMPLATE_DIRECTORY,
        package_root=package_root,
        appinstaller_path=appinstaller,
        version_info_path=version_info,
        source_icon=SOURCE_ICON,
    )
    window_host = package_root / "WindowHost"
    window_host.mkdir()
    (window_host / "Stockroom.WindowHost.exe").write_bytes(b"MZwindow-host")
    (window_host / "Stockroom.WindowHost.dll").write_bytes(b"runtime")
    return package_root, appinstaller, version_info


def test_validation_requires_complete_native_window_host(tmp_path: Path) -> None:
    package_root, appinstaller, _ = render_fixture(tmp_path)
    (package_root / "WindowHost" / "Stockroom.WindowHost.dll").unlink()

    with pytest.raises(PackageContractError, match="self-contained runtime"):
        validate_rendered_contract(
            fixture_configuration(),
            manifest_path=package_root / "AppxManifest.xml",
            appinstaller_path=appinstaller,
            package_root=package_root,
        )


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_fixture_and_production_are_cryptographically_distinct_identities() -> None:
    fixture = fixture_configuration()
    production = PackageConfiguration.for_mode(
        mode="Production",
        publisher="CN=Stockroom LLC, O=Stockroom LLC, C=US",
        version="1.2.3.4",
        feed_base_uri="https://updates.stockroom.com/windows/x64",
        signing_certificate_provided=True,
    )

    assert fixture.package_name == "Stockroom.Desktop.Development"
    assert fixture.application_id == "StockroomDevelopment"
    assert production.package_name == "Stockroom.Desktop"
    assert production.application_id == "Stockroom"
    assert fixture.package_name != production.package_name


def test_store_configuration_uses_the_exact_partner_center_identity() -> None:
    store = PackageConfiguration.for_mode(
        mode="Store",
        publisher="CN=6586C41B-410B-4C94-8631-F025DB362E47",
        version="1.0.42.0",
        feed_base_uri="",
        signing_certificate_provided=False,
    )

    assert store.package_name == "Sadad.Stockroom"
    assert store.application_id == "Stockroom"
    assert store.display_name == "Stockroom"
    assert store.publisher_display_name == "Sadad"
    assert store.update_channel == "microsoft-store"
    assert store.requires_appinstaller is False
    assert store.package_filename == "Stockroom_1.0.42.0_x64_store.msix"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"publisher": "CN=Stockroom Development"},
            "Partner Center publisher",
        ),
        (
            {"version": "1.0.42.1"},
            "fourth component must be zero",
        ),
        (
            {"feed_base_uri": "https://sadadsh.github.io/stockroom/windows/x64"},
            "cannot use a direct feed",
        ),
        (
            {"signing_certificate_provided": True},
            "must remain unsigned",
        ),
    ],
)
def test_store_configuration_refuses_mixed_distribution_authority(
    overrides: dict[str, object], message: str
) -> None:
    values: dict[str, object] = {
        "mode": "Store",
        "publisher": "CN=6586C41B-410B-4C94-8631-F025DB362E47",
        "version": "1.0.42.0",
        "feed_base_uri": "",
        "signing_certificate_provided": False,
    }
    values.update(overrides)

    with pytest.raises(PackageContractError, match=message):
        PackageConfiguration.for_mode(**values)  # type: ignore[arg-type]


def test_store_contract_emits_a_distribution_marker_without_appinstaller(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "Package"
    appinstaller = tmp_path / "Stockroom.appinstaller"
    version_info = tmp_path / "StockroomVersionInfo.txt"

    render_contract(
        store_configuration(),
        template_directory=TEMPLATE_DIRECTORY,
        package_root=package_root,
        appinstaller_path=appinstaller,
        version_info_path=version_info,
        source_icon=SOURCE_ICON,
    )

    assert not appinstaller.exists()
    assert json.loads((package_root / "Support/Distribution.json").read_text(encoding="utf-8")) == {
        "channel": "microsoft-store",
        "package_name": "Sadad.Stockroom",
        "publisher": "CN=6586C41B-410B-4C94-8631-F025DB362E47",
        "schema": "stockroom-distribution/1",
        "store_id": "9NQ6HP17PH4H",
        "store_uri": "https://apps.microsoft.com/detail/9NQ6HP17PH4H",
        "version": "1.0.42.0",
    }
    root = ElementTree.parse(package_root / "AppxManifest.xml").getroot()
    identity = root.find(f"{{{PACKAGE_NAMESPACE}}}Identity")
    assert identity is not None
    assert identity.attrib["Name"] == "Sadad.Stockroom"
    assert identity.attrib["Publisher"] == "CN=6586C41B-410B-4C94-8631-F025DB362E47"


def test_store_contract_rejects_a_direct_update_marker(tmp_path: Path) -> None:
    package_root = tmp_path / "Package"
    appinstaller = tmp_path / "Stockroom.appinstaller"
    render_contract(
        store_configuration(),
        template_directory=TEMPLATE_DIRECTORY,
        package_root=package_root,
        appinstaller_path=appinstaller,
        version_info_path=tmp_path / "StockroomVersionInfo.txt",
        source_icon=SOURCE_ICON,
    )
    marker_path = package_root / "Support/Distribution.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["channel"] = "production"
    marker_path.write_text(json.dumps(marker), encoding="utf-8")

    with pytest.raises(PackageContractError, match="Microsoft Store distribution marker"):
        validate_rendered_contract(
            store_configuration(),
            manifest_path=package_root / "AppxManifest.xml",
            appinstaller_path=appinstaller,
            package_root=package_root,
            require_payload=False,
        )


def test_package_contract_cli_renders_store_mode(tmp_path: Path) -> None:
    package_root = tmp_path / "Package"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "packaging.package_contract",
            "render",
            "--mode",
            "Store",
            "--publisher",
            "CN=6586C41B-410B-4C94-8631-F025DB362E47",
            "--version",
            "1.0.42.0",
            "--feed-base-uri",
            "",
            "--package-root",
            str(package_root),
            "--appinstaller-path",
            str(tmp_path / "Stockroom.appinstaller"),
            "--template-directory",
            str(TEMPLATE_DIRECTORY),
            "--version-info-path",
            str(tmp_path / "StockroomVersionInfo.txt"),
            "--source-icon",
            str(SOURCE_ICON),
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (package_root / "Support/Distribution.json").is_file()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"version": "1.2.3"}, "four-part"),
        ({"version": "1.2.3.65536"}, "at most 65535"),
        ({"version": "0.0.0.0"}, "not deployable"),
        ({"feed_base_uri": "http://updates.example.invalid/x"}, "absolute HTTPS"),
        (
            {"feed_base_uri": "https://updates.example.com/stockroom"},
            "reserved .invalid",
        ),
        (
            {"publisher": "CN=Stockroom"},
            "visibly development-only",
        ),
        (
            {"signing_certificate_provided": True},
            "must remain unsigned",
        ),
    ],
)
def test_fixture_configuration_fails_closed(overrides: dict[str, object], message: str) -> None:
    values: dict[str, object] = {
        "mode": "Fixture",
        "publisher": "CN=Stockroom Development",
        "version": "1.2.3.4",
        "feed_base_uri": "https://updates.example.invalid/stockroom",
        "signing_certificate_provided": False,
    }
    values.update(overrides)
    with pytest.raises(PackageContractError, match=message):
        PackageConfiguration.for_mode(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"feed_base_uri": "https://updates.example.invalid/stockroom"},
            "real HTTPS",
        ),
        (
            {"feed_base_uri": "https://updates.stockroom.example/windows"},
            "real HTTPS",
        ),
        (
            {"feed_base_uri": "https://updates.example.com/stockroom"},
            "real HTTPS",
        ),
        (
            {"publisher": "CN=Stockroom Test"},
            "development/test",
        ),
        (
            {"signing_certificate_provided": False},
            "real signing certificate",
        ),
    ],
)
def test_production_configuration_fails_closed_without_real_inputs(
    overrides: dict[str, object], message: str
) -> None:
    values: dict[str, object] = {
        "mode": "Production",
        "publisher": "CN=Stockroom LLC, O=Stockroom LLC, C=US",
        "version": "1.2.3.4",
        "feed_base_uri": "https://updates.stockroom.com/windows/x64",
        "signing_certificate_provided": True,
    }
    values.update(overrides)
    with pytest.raises(PackageContractError, match=message):
        PackageConfiguration.for_mode(**values)  # type: ignore[arg-type]


def test_manifest_is_one_x64_full_trust_desktop_application(tmp_path: Path) -> None:
    package_root, _, _ = render_fixture(tmp_path)
    root = ElementTree.parse(package_root / "AppxManifest.xml").getroot()
    identity = root.find(f"{{{PACKAGE_NAMESPACE}}}Identity")
    application = root.find(
        f"{{{PACKAGE_NAMESPACE}}}Applications/{{{PACKAGE_NAMESPACE}}}Application"
    )

    assert identity is not None
    assert identity.attrib == {
        "Name": "Stockroom.Desktop.Development",
        "Publisher": "CN=Stockroom Development",
        "Version": "0.1.2.3",
        "ProcessorArchitecture": "x64",
    }
    assert application is not None
    assert application.attrib == {
        "Id": "StockroomDevelopment",
        "Executable": r"WindowHost\Stockroom.WindowHost.exe",
        "EntryPoint": "Windows.FullTrustApplication",
    }


def test_appinstaller_is_silent_on_launch_and_background_updates(
    tmp_path: Path,
) -> None:
    _, appinstaller, _ = render_fixture(tmp_path)
    root = ElementTree.parse(appinstaller).getroot()
    settings = root.find(f"{{{APPINSTALLER_NAMESPACE}}}UpdateSettings")
    assert settings is not None
    children = list(settings)

    assert [child.tag.rsplit("}", 1)[-1] for child in children] == [
        "OnLaunch",
        "AutomaticBackgroundTask",
    ]
    assert children[0].attrib == {
        "HoursBetweenUpdateChecks": "0",
        "ShowPrompt": "false",
        "UpdateBlocksActivation": "false",
    }
    assert root.find(f".//{{{APPINSTALLER_NAMESPACE}}}ForceUpdateFromAnyVersion") is None


def test_appinstaller_identity_must_match_the_msix_contract(tmp_path: Path) -> None:
    package_root, appinstaller, _ = render_fixture(tmp_path)
    appinstaller.write_text(
        appinstaller.read_text(encoding="utf-8").replace(
            'Name="Stockroom.Desktop.Development"',
            'Name="Stockroom.Desktop"',
        ),
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(PackageContractError, match="does not match MSIX"):
        validate_rendered_contract(
            fixture_configuration(),
            manifest_path=package_root / "AppxManifest.xml",
            appinstaller_path=appinstaller,
            package_root=package_root,
        )


def test_rendered_assets_and_contract_are_byte_reproducible(tmp_path: Path) -> None:
    first_root, first_appinstaller, first_version = render_fixture(tmp_path / "First")
    second_root, second_appinstaller, second_version = render_fixture(tmp_path / "Second")

    assert inventory_tree(first_root) == inventory_tree(second_root)
    assert digest(first_appinstaller) == digest(second_appinstaller)
    assert digest(first_version) == digest(second_version)
    for name, expected_size in (
        ("Square44x44Logo.png", (44, 44)),
        ("StoreLogo.png", (50, 50)),
        ("Square150x150Logo.png", (150, 150)),
    ):
        with Image.open(first_root / "Assets" / name) as image:
            assert image.mode == "RGBA"
            assert image.size == expected_size

    assets = first_root / "Assets"
    expected_names = set(BASE_ASSETS)
    for size in SHELL_TARGET_SIZES:
        base = f"Square44x44Logo.targetsize-{size}"
        expected_names.update(
            {
                f"{base}.png",
                f"{base}_altform-unplated.png",
                f"{base}_altform-lightunplated.png",
            }
        )
    assert {path.name for path in assets.iterdir()} == expected_names

    for size in SHELL_TARGET_SIZES:
        for suffix in (
            ".png",
            "_altform-unplated.png",
            "_altform-lightunplated.png",
        ):
            with Image.open(assets / f"Square44x44Logo.targetsize-{size}{suffix}") as image:
                assert image.mode == "RGBA"
                assert image.size == (size, size)


def test_rendered_contract_rejects_a_changed_shell_asset(tmp_path: Path) -> None:
    package_root, appinstaller, _ = render_fixture(tmp_path)
    changed = package_root / "Assets" / "Square44x44Logo.targetsize-32.png"
    changed.write_bytes(changed.read_bytes() + b"changed")

    with pytest.raises(PackageContractError, match="stale or non-deterministic"):
        validate_rendered_contract(
            fixture_configuration(),
            manifest_path=package_root / "AppxManifest.xml",
            appinstaller_path=appinstaller,
            package_root=package_root,
        )


def test_inventory_is_case_insensitive_path_sorted_and_content_only(
    tmp_path: Path,
) -> None:
    (tmp_path / "z").mkdir()
    (tmp_path / "A.txt").write_bytes(b"a")
    (tmp_path / "z" / "B.txt").write_bytes(b"b")

    assert inventory_tree(tmp_path) == (
        {
            "path": "A.txt",
            "sha256": hashlib.sha256(b"a").hexdigest(),
            "size": 1,
        },
        {
            "path": "z/B.txt",
            "sha256": hashlib.sha256(b"b").hexdigest(),
            "size": 1,
        },
    )


def test_msix_timestamp_normalization_preserves_members_and_reproduces_bytes(
    tmp_path: Path,
) -> None:
    first = tmp_path / "First.msix"
    second = tmp_path / "Second.msix"
    for path, timestamp in (
        (first, (2026, 7, 29, 6, 30, 2)),
        (second, (2026, 7, 29, 6, 45, 58)),
    ):
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in (
                ("AppxManifest.xml", b"<Package />"),
                ("Stockroom.exe", b"MZ" + b"\0" * 1_024),
            ):
                info = zipfile.ZipInfo(name, date_time=timestamp)
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, data)

    assert digest(first) != digest(second)
    normalize_msix_timestamps(first, 1_704_067_200)
    normalize_msix_timestamps(second, 1_704_067_200)

    assert digest(first) == digest(second)
    with zipfile.ZipFile(first) as archive:
        assert archive.read("AppxManifest.xml") == b"<Package />"
        assert archive.read("Stockroom.exe") == b"MZ" + b"\0" * 1_024
        assert {info.date_time for info in archive.infolist()} == {(2024, 1, 1, 0, 0, 0)}


def test_windows_build_keeps_sdk_validation_and_round_trip_enabled() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert '"/nv"' not in script
    assert '"pack",' in script
    assert '"unpack",' in script
    assert '"normalize-msix",' in script
    assert "MakeAppx round-trip changed AppxManifest.xml." in script
    assert "MakeAppx round-trip changed the native window host payload." in script
    assert '"--runtime", "win-x64"' in script
    assert '"--self-contained", "true"' in script
    assert '"--window-host-root", (Join-Path $stage "WindowHost")' in script
    assert "MakeAppx round-trip changed the native window host payload." in script


def test_windows_build_fails_closed_around_production_signing() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert "Production mode requires -SigningCertificatePath" in script
    assert "EphemeralKeySet" in script
    assert "Publisher must exactly equal the signing certificate subject." in script
    assert "The signing PFX does not contain the Code Signing EKU." in script
    assert '"verify", "/pa", "/all", (Join-Path $FirstStage "WindowHost\\Stockroom.WindowHost.exe")' in script
    assert '"verify", "/pa", "/all", $FinalPackage' in script
    assert "Fixture mode refuses a signing certificate." in script


def test_pyinstaller_build_uses_a_neutral_working_directory() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    start = script.index("function Build-Executable")
    end = script.index("function Build-WindowHost", start)
    function = script[start:end]

    assert '"--project", $RepositoryRoot' in function
    assert '"--directory", $buildRoot' in function
    assert function.index('"--project", $RepositoryRoot') < function.index('"pyinstaller"')
    assert function.index('"--directory", $buildRoot') < function.index('"pyinstaller"')
    assert "STOCKROOM_CAD_CONVERTER_ROOT" not in function
    assert "CadConverterRoot" not in function


def test_release_carries_one_native_cad_converter_outside_the_worker() -> None:
    spec = (REPOSITORY_ROOT / "packaging" / "stockroom.spec").read_text(
        encoding="utf-8"
    )
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert "STOCKROOM_CAD_CONVERTER_ROOT" not in spec
    assert '(_cad_converter, "cad-converter")' not in spec
    assert '"--cad-converter-root", $CadConverterRoot' in script
    assert "-CadConverterRoot $FirstCadConverter" in script
    assert "-CadConverterRoot $SecondCadConverter" in script
    assert "tree_sha256 = Get-TextSha256 -Text" in script
    assert "[Security.Cryptography.SHA256]::Create()" in script
    assert ".ComputeHash($bytes)" in script
    assert "::HashData(" not in script
    assert "[Convert]::ToHexString" not in script


def test_packaged_worker_carries_no_mutable_startup_toolchain() -> None:
    spec = (REPOSITORY_ROOT / "packaging" / "stockroom.spec").read_text(
        encoding="utf-8"
    )

    assert "STOCKROOM_NODE_ROOT" not in spec
    assert "STOCKROOM_MINGIT_ROOT" not in spec
    assert "STOCKROOM_UV_EXECUTABLE" not in spec
    assert "STOCKROOM_WEBVIEW2_BOOTSTRAPPER" not in spec
    assert "COLLECT(" in spec


def test_obsolete_portable_build_fails_closed_without_downloading_inputs() -> None:
    script = PORTABLE_BUILD_SCRIPT.read_text(encoding="utf-8")

    assert "Standalone bootstrap executables are no longer supported" in script
    assert "Invoke-WebRequest" not in script
    assert "MinGit" not in script
    assert "MicrosoftEdgeWebview2Setup.exe" not in script


def test_no_dev_fresh_install_keeps_host_startup_image_runtime() -> None:
    import tomllib

    project = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    runtime = {entry.split(">", 1)[0].split("=", 1)[0].casefold() for entry in project["project"]["dependencies"]}
    development = {
        entry.split(">", 1)[0].split("=", 1)[0].casefold()
        for entry in project["dependency-groups"]["dev"]
    }

    assert "pillow" in runtime
    assert "pillow" not in development


def test_window_host_publish_returns_only_its_publish_root():
    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    start = script.index("function Build-WindowHost")
    end = script.index("$FirstExecutable =", start)
    function = script[start:end]

    assert "$null = Invoke-Checked -FilePath $DotNetPath" in function
    assert 'Join-Path $WorkRoot "Window Host Compilation"' in function
    assert '"-p:UseArtifactsOutput=true"' in function
    assert '"-p:ArtifactsPath=$compileRoot"' in function
    assert "$hostExecutable = Join-Path" in function
    assert "$host = Join-Path" not in function
