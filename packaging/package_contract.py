"""Render and validate Stockroom's deterministic Windows package contract.

This module deliberately owns only static packaging concerns.  It does not
activate releases, coordinate services, or implement update handoff.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree
from xml.sax.saxutils import escape

from PIL import Image

from packaging.brand_assets import (
    SHELL_TARGET_SIZES,
    render_ico_bytes,
    render_png_bytes,
)

PACKAGE_NAMESPACE = "http://schemas.microsoft.com/appx/manifest/foundation/windows10"
UAP_NAMESPACE = "http://schemas.microsoft.com/appx/manifest/uap/windows10"
RESTRICTED_CAPABILITY_NAMESPACE = (
    "http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
)
APPINSTALLER_NAMESPACE = "http://schemas.microsoft.com/appx/appinstaller/2021"
MINIMUM_WINDOWS_VERSION = "10.0.19041.0"
MAXIMUM_TESTED_WINDOWS_VERSION = "10.0.26100.0"
VERSION_PATTERN = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
)
PACKAGE_NAME_PATTERN = re.compile(r"[A-Za-z0-9.-]{3,50}")
PUBLISHER_PATTERN = re.compile(r"[^\x00-\x1f]{3,8192}")
BASE_ASSETS = {
    "Square44x44Logo.png": (44, "tile"),
    "StoreLogo.png": (50, "tile"),
    "Square150x150Logo.png": (150, "tile"),
}
WINDOW_HOST_EXECUTABLE = "WindowHost/Stockroom.WindowHost.exe"


class PackageContractError(ValueError):
    """The requested Windows package contract is unsafe or inconsistent."""


@dataclass(frozen=True, slots=True)
class PackageConfiguration:
    """Inputs that must agree across the MSIX and App Installer contracts."""

    mode: str
    package_name: str
    application_id: str
    display_name: str
    publisher_display_name: str
    publisher: str
    version: str
    feed_base_uri: str
    signing_certificate_provided: bool

    @classmethod
    def for_mode(
        cls,
        *,
        mode: str,
        publisher: str,
        version: str,
        feed_base_uri: str,
        signing_certificate_provided: bool,
    ) -> PackageConfiguration:
        normalized_mode = mode.strip().casefold()
        if normalized_mode == "fixture":
            package_name = "Stockroom.Desktop.Development"
            application_id = "StockroomDevelopment"
            display_name = "Stockroom Development"
        elif normalized_mode == "production":
            package_name = "Stockroom.Desktop"
            application_id = "Stockroom"
            display_name = "Stockroom"
        else:
            raise PackageContractError("mode must be Fixture or Production")
        configuration = cls(
            mode=normalized_mode,
            package_name=package_name,
            application_id=application_id,
            display_name=display_name,
            publisher_display_name="Stockroom",
            publisher=publisher.strip(),
            version=version.strip(),
            feed_base_uri=feed_base_uri.rstrip("/"),
            signing_certificate_provided=signing_certificate_provided,
        )
        configuration.validate()
        return configuration

    @property
    def package_filename(self) -> str:
        if self.mode == "fixture":
            return f"Stockroom.Development_{self.version}_x64_unsigned.msix"
        return f"Stockroom_{self.version}_x64.msix"

    @property
    def appinstaller_filename(self) -> str:
        if self.mode == "fixture":
            return "Stockroom.Development.appinstaller"
        return "Stockroom.appinstaller"

    @property
    def package_uri(self) -> str:
        return f"{self.feed_base_uri}/{self.package_filename}"

    @property
    def appinstaller_uri(self) -> str:
        return f"{self.feed_base_uri}/{self.appinstaller_filename}"

    @property
    def version_tuple(self) -> tuple[int, int, int, int]:
        major, minor, patch, revision = (int(part) for part in self.version.split("."))
        return major, minor, patch, revision

    def validate(self) -> None:
        if not PACKAGE_NAME_PATTERN.fullmatch(self.package_name):
            raise PackageContractError("package_name is not a valid MSIX identity name")
        if not PUBLISHER_PATTERN.fullmatch(self.publisher):
            raise PackageContractError("publisher is not a valid certificate subject")
        if VERSION_PATTERN.fullmatch(self.version) is None:
            raise PackageContractError("version must be a canonical four-part numeric version")
        if any(part > 65_535 for part in self.version_tuple):
            raise PackageContractError("each version component must be at most 65535")
        if self.version_tuple == (0, 0, 0, 0):
            raise PackageContractError("version 0.0.0.0 is not deployable")

        parsed = urlparse(self.feed_base_uri)
        if parsed.scheme != "https" or not parsed.hostname:
            raise PackageContractError("feed_base_uri must be an absolute HTTPS URI")
        if parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise PackageContractError(
                "feed_base_uri cannot contain credentials, a query, or a fragment"
            )
        hostname = parsed.hostname.casefold()
        fixture_host = hostname.endswith(".invalid")
        reserved_production_host = any(
            hostname == suffix or hostname.endswith(f".{suffix}")
            for suffix in (
                "invalid",
                "example",
                "test",
                "localhost",
                "example.com",
                "example.net",
                "example.org",
            )
        )
        if self.mode == "fixture":
            if not fixture_host:
                raise PackageContractError(
                    "fixture builds must use the reserved .invalid namespace"
                )
            if self.signing_certificate_provided:
                raise PackageContractError("fixture builds must remain unsigned")
            if "development" not in self.publisher.casefold():
                raise PackageContractError("fixture publisher must be visibly development-only")
        else:
            if reserved_production_host or hostname in {"127.0.0.1", "::1"}:
                raise PackageContractError(
                    "production builds require a real HTTPS distribution host"
                )
            if re.search(
                r"\b(?:development|fixture|test)\b",
                self.publisher,
                flags=re.IGNORECASE,
            ):
                raise PackageContractError(
                    "production publisher cannot use a development/test identity"
                )
            if not self.signing_certificate_provided:
                raise PackageContractError("production builds require a real signing certificate")


def render_contract(
    configuration: PackageConfiguration,
    *,
    template_directory: Path,
    package_root: Path,
    appinstaller_path: Path,
    version_info_path: Path,
    source_icon: Path,
) -> None:
    """Render the complete static package contract and deterministic PNG assets."""

    configuration.validate()
    if not source_icon.is_file():
        raise PackageContractError(f"source icon does not exist: {source_icon}")
    package_root.mkdir(parents=True, exist_ok=True)
    appinstaller_path.parent.mkdir(parents=True, exist_ok=True)
    version_info_path.parent.mkdir(parents=True, exist_ok=True)

    values = {
        "APPLICATION_ID": configuration.application_id,
        "APPINSTALLER_URI": configuration.appinstaller_uri,
        "DISPLAY_NAME": configuration.display_name,
        "PACKAGE_NAME": configuration.package_name,
        "PACKAGE_URI": configuration.package_uri,
        "PUBLISHER": configuration.publisher,
        "PUBLISHER_DISPLAY_NAME": configuration.publisher_display_name,
        "VERSION": configuration.version,
        "VERSION_TUPLE": ", ".join(str(part) for part in configuration.version_tuple),
    }
    manifest = _render_template(template_directory / "AppxManifest.xml.in", values)
    appinstaller = _render_template(template_directory / "Stockroom.appinstaller.in", values)
    version_info = _render_template(template_directory / "StockroomVersionInfo.txt.in", values)
    (package_root / "AppxManifest.xml").write_text(manifest, encoding="utf-8", newline="\n")
    appinstaller_path.write_text(appinstaller, encoding="utf-8", newline="\n")
    version_info_path.write_text(version_info, encoding="utf-8", newline="\n")
    _render_assets(source_icon, package_root / "Assets")

    validate_rendered_contract(
        configuration,
        manifest_path=package_root / "AppxManifest.xml",
        appinstaller_path=appinstaller_path,
        package_root=package_root,
        require_payload=False,
    )


def validate_rendered_contract(
    configuration: PackageConfiguration,
    *,
    manifest_path: Path,
    appinstaller_path: Path,
    package_root: Path,
    require_payload: bool = True,
) -> None:
    """Validate both XML documents and their cross-file identity/update contract."""

    configuration.validate()
    _validate_manifest(configuration, manifest_path, package_root)
    if require_payload:
        _validate_window_host_payload(package_root)
    _validate_appinstaller(configuration, appinstaller_path)


def _validate_window_host_payload(package_root: Path) -> None:
    root = package_root / "WindowHost"
    executable = package_root / WINDOW_HOST_EXECUTABLE
    if not root.is_dir() or not executable.is_file():
        raise PackageContractError(
            f"package is missing the native window host: {WINDOW_HOST_EXECUTABLE}"
        )
    files = tuple(path for path in root.rglob("*") if path.is_file())
    if any(path.is_symlink() for path in files):
        raise PackageContractError("native window host payload must not contain symlinks")
    if len(files) < 2:
        raise PackageContractError(
            "native window host payload is incomplete; self-contained runtime files are required"
        )


def inventory_tree(root: Path) -> tuple[dict[str, object], ...]:
    """Return a stable content-only inventory for one package staging tree."""

    if not root.is_dir():
        raise PackageContractError(f"inventory root does not exist: {root}")
    entries: list[dict[str, object]] = []
    for path in sorted(
        (candidate for candidate in root.rglob("*") if candidate.is_file()),
        key=lambda candidate: candidate.relative_to(root).as_posix().casefold(),
    ):
        data = path.read_bytes()
        entries.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }
        )
    return tuple(entries)


def write_inventory(root: Path, output: Path) -> None:
    document = {
        "schema": "stockroom-windows-package-payload/1",
        "files": inventory_tree(root),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def normalize_msix_timestamps(path: Path, source_date_epoch: int) -> None:
    """Normalize only ZIP header timestamps in an SDK-built MSIX.

    MakeAppx emits deterministic payload, block-map, compression, and ordering,
    but stamps ZIP headers with its wall clock.  Header timestamps are outside
    the AppxBlockMap content contract.  Patch the local and central-directory
    DOS fields in place without decompressing or recompressing any package
    member, then rely on the SDK unpack round-trip as the format check.
    """

    try:
        instant = dt.datetime.fromtimestamp(source_date_epoch, tz=dt.UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise PackageContractError("source_date_epoch is outside the ZIP range") from exc
    if not 1980 <= instant.year <= 2107:
        raise PackageContractError("source_date_epoch is outside the ZIP range")
    dos_time = (instant.hour << 11) | (instant.minute << 5) | (instant.second // 2)
    dos_date = ((instant.year - 1980) << 9) | (instant.month << 5) | instant.day

    data = bytearray(path.read_bytes())
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            central_offset = archive.start_dir
    except (OSError, zipfile.BadZipFile) as exc:
        raise PackageContractError(f"{path.name} is not a readable MSIX/ZIP") from exc
    if not infos:
        raise PackageContractError("MSIX contains no package members")

    for info in infos:
        offset = info.header_offset
        if data[offset : offset + 4] != b"PK\x03\x04":
            raise PackageContractError("MSIX local-file header is malformed")
        struct.pack_into("<HH", data, offset + 10, dos_time, dos_date)

    offset = central_offset
    for _ in infos:
        if data[offset : offset + 4] != b"PK\x01\x02":
            raise PackageContractError("MSIX central directory is malformed")
        struct.pack_into("<HH", data, offset + 12, dos_time, dos_date)
        name_length, extra_length, comment_length = struct.unpack_from("<HHH", data, offset + 28)
        offset += 46 + name_length + extra_length + comment_length

    temporary = path.with_name(f"{path.name}.normalizing")
    temporary.write_bytes(data)
    try:
        with zipfile.ZipFile(temporary) as archive:
            bad_member = archive.testzip()
    except zipfile.BadZipFile as exc:
        temporary.unlink(missing_ok=True)
        raise PackageContractError("normalized MSIX is not a readable ZIP") from exc
    if bad_member is not None:
        temporary.unlink(missing_ok=True)
        raise PackageContractError(f"normalized MSIX member failed CRC validation: {bad_member}")
    temporary.replace(path)


def _render_template(path: Path, values: dict[str, str]) -> str:
    text = path.read_text(encoding="utf-8")
    for name, value in values.items():
        token = f"@@{name}@@"
        if text.count(token) > 1 and name not in {
            "DISPLAY_NAME",
            "PUBLISHER",
            "VERSION",
            "VERSION_TUPLE",
        }:
            raise PackageContractError(f"{path.name}: token {token} is duplicated")
        text = text.replace(token, escape(value, {'"': "&quot;"}))
    unresolved = sorted(set(re.findall(r"@@[A-Z_]+@@", text)))
    if unresolved:
        raise PackageContractError(f"{path.name}: unresolved template tokens: {unresolved}")
    return text.rstrip() + "\n"


def _render_assets(source_icon: Path, destination: Path) -> None:
    if source_icon.read_bytes() != render_ico_bytes():
        raise PackageContractError(
            "source icon is stale; run `uv run python packaging/brand_assets.py --write`"
        )
    destination.mkdir(parents=True, exist_ok=True)
    for filename, (size, variant) in _asset_contract().items():
        (destination / filename).write_bytes(render_png_bytes(size, variant=variant))


def _asset_contract() -> dict[str, tuple[int, str]]:
    assets = dict(BASE_ASSETS)
    for size in SHELL_TARGET_SIZES:
        base = f"Square44x44Logo.targetsize-{size}"
        assets[f"{base}.png"] = (size, "tile")
        assets[f"{base}_altform-unplated.png"] = (size, "unplated-dark")
        assets[f"{base}_altform-lightunplated.png"] = (size, "unplated-light")
    return assets


def _validate_assets(package_root: Path) -> None:
    assets_root = package_root / "Assets"
    actual = {
        path.relative_to(assets_root).as_posix()
        for path in assets_root.rglob("*")
        if path.is_file()
    }
    expected = set(_asset_contract())
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise PackageContractError(
            f"Windows asset inventory changed; missing={missing}, unexpected={unexpected}"
        )

    for filename, (size, variant) in _asset_contract().items():
        path = assets_root / filename
        payload = path.read_bytes()
        if payload != render_png_bytes(size, variant=variant):
            raise PackageContractError(f"Windows asset is stale or non-deterministic: {filename}")
        with Image.open(path) as image:
            if image.mode != "RGBA" or image.size != (size, size):
                raise PackageContractError(f"Windows asset shape is invalid: {filename}")
            red, green, blue, alpha = image.split()
            if red.tobytes() != green.tobytes() or green.tobytes() != blue.tobytes():
                raise PackageContractError(f"Windows asset is not grayscale: {filename}")
            if alpha.getpixel((0, 0)) != 0 or alpha.getbbox() is None:
                raise PackageContractError(f"Windows asset transparency is invalid: {filename}")


def _validate_manifest(
    configuration: PackageConfiguration,
    manifest_path: Path,
    package_root: Path,
) -> None:
    root = _parse_xml(manifest_path, PACKAGE_NAMESPACE, "Package")
    if set(root.attrib) != {"IgnorableNamespaces"}:
        raise PackageContractError("AppxManifest Package attributes changed")
    if root.attrib["IgnorableNamespaces"].split() != ["uap", "rescap"]:
        raise PackageContractError("AppxManifest ignorable namespaces changed")

    identity = _one(root, PACKAGE_NAMESPACE, "Identity")
    expected_identity = {
        "Name": configuration.package_name,
        "Publisher": configuration.publisher,
        "Version": configuration.version,
        "ProcessorArchitecture": "x64",
    }
    if identity.attrib != expected_identity:
        raise PackageContractError("AppxManifest identity does not match the build")

    family = _one(root, PACKAGE_NAMESPACE, "Dependencies/TargetDeviceFamily")
    if family.attrib != {
        "Name": "Windows.Desktop",
        "MinVersion": MINIMUM_WINDOWS_VERSION,
        "MaxVersionTested": MAXIMUM_TESTED_WINDOWS_VERSION,
    }:
        raise PackageContractError("AppxManifest Windows target contract changed")

    application = _one(root, PACKAGE_NAMESPACE, "Applications/Application")
    if application.attrib != {
        "Id": configuration.application_id,
        "Executable": r"WindowHost\Stockroom.WindowHost.exe",
        "EntryPoint": "Windows.FullTrustApplication",
    }:
        raise PackageContractError("AppxManifest full-trust application changed")

    visual = application.find(f"{{{UAP_NAMESPACE}}}VisualElements")
    if visual is None:
        raise PackageContractError("AppxManifest visual elements are missing")
    expected_visual = {
        "DisplayName": configuration.display_name,
        "Description": "Stockroom's native Windows desktop host.",
        "BackgroundColor": "transparent",
        "Square44x44Logo": r"Assets\Square44x44Logo.png",
        "Square150x150Logo": r"Assets\Square150x150Logo.png",
    }
    if visual.attrib != expected_visual:
        raise PackageContractError("AppxManifest visual contract changed")

    capabilities = list(root.findall(f".//{{{RESTRICTED_CAPABILITY_NAMESPACE}}}Capability"))
    if len(capabilities) != 1 or capabilities[0].attrib != {"Name": "runFullTrust"}:
        raise PackageContractError("AppxManifest must request only runFullTrust")

    referenced_files = {
        r"WindowHost\Stockroom.WindowHost.exe",
        r"Assets\StoreLogo.png",
        r"Assets\Square44x44Logo.png",
        r"Assets\Square150x150Logo.png",
    }
    for relative in referenced_files:
        if not (package_root / Path(relative.replace("\\", "/"))).is_file():
            if relative == r"WindowHost\Stockroom.WindowHost.exe":
                # Rendering occurs before the deterministic native host is copied.
                continue
            raise PackageContractError(f"AppxManifest asset is missing: {relative}")
    _validate_assets(package_root)


def _validate_appinstaller(
    configuration: PackageConfiguration,
    appinstaller_path: Path,
) -> None:
    root = _parse_xml(appinstaller_path, APPINSTALLER_NAMESPACE, "AppInstaller")
    if root.attrib != {
        "Version": configuration.version,
        "Uri": configuration.appinstaller_uri,
    }:
        raise PackageContractError("App Installer root identity does not match")

    main = _one(root, APPINSTALLER_NAMESPACE, "MainPackage")
    if main.attrib != {
        "Name": configuration.package_name,
        "Publisher": configuration.publisher,
        "Version": configuration.version,
        "ProcessorArchitecture": "x64",
        "Uri": configuration.package_uri,
    }:
        raise PackageContractError("App Installer package identity does not match MSIX")

    settings = _one(root, APPINSTALLER_NAMESPACE, "UpdateSettings")
    children = list(settings)
    if [child.tag for child in children] != [
        f"{{{APPINSTALLER_NAMESPACE}}}OnLaunch",
        f"{{{APPINSTALLER_NAMESPACE}}}AutomaticBackgroundTask",
    ]:
        raise PackageContractError(
            "App Installer must have exactly OnLaunch and AutomaticBackgroundTask"
        )
    on_launch, background = children
    if on_launch.attrib != {
        "HoursBetweenUpdateChecks": "0",
        "ShowPrompt": "false",
        "UpdateBlocksActivation": "false",
    }:
        raise PackageContractError("App Installer on-launch policy changed")
    if background.attrib or list(background):
        raise PackageContractError("AutomaticBackgroundTask must be empty")
    if root.find(f".//{{{APPINSTALLER_NAMESPACE}}}ForceUpdateFromAnyVersion") is not None:
        raise PackageContractError("App Installer must not permit package downgrade")


def _parse_xml(path: Path, namespace: str, root_name: str) -> ElementTree.Element:
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError) as exc:
        raise PackageContractError(f"{path.name} is not valid XML") from exc
    if root.tag != f"{{{namespace}}}{root_name}":
        raise PackageContractError(f"{path.name} uses the wrong root namespace")
    return root


def _one(
    root: ElementTree.Element,
    namespace: str,
    path: str,
) -> ElementTree.Element:
    qualified = "/".join(f"{{{namespace}}}{part}" for part in path.split("/"))
    matches = root.findall(qualified)
    if len(matches) != 1:
        raise PackageContractError(f"expected exactly one {path}, found {len(matches)}")
    return matches[0]


def _configuration_from_args(args: argparse.Namespace) -> PackageConfiguration:
    return PackageConfiguration.for_mode(
        mode=args.mode,
        publisher=args.publisher,
        version=args.version,
        feed_base_uri=args.feed_base_uri,
        signing_certificate_provided=args.signing_certificate_provided,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("render", "validate"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--mode", choices=("Fixture", "Production"), required=True)
        subparser.add_argument("--publisher", required=True)
        subparser.add_argument("--version", required=True)
        subparser.add_argument("--feed-base-uri", required=True)
        subparser.add_argument("--signing-certificate-provided", action="store_true")
        subparser.add_argument("--package-root", type=Path, required=True)
        subparser.add_argument("--appinstaller-path", type=Path, required=True)
        if command == "render":
            subparser.add_argument("--template-directory", type=Path, required=True)
            subparser.add_argument("--version-info-path", type=Path, required=True)
            subparser.add_argument("--source-icon", type=Path, required=True)
    inventory_parser = subparsers.add_parser("inventory")
    inventory_parser.add_argument("--root", type=Path, required=True)
    inventory_parser.add_argument("--output", type=Path, required=True)
    normalize_parser = subparsers.add_parser("normalize-msix")
    normalize_parser.add_argument("--path", type=Path, required=True)
    normalize_parser.add_argument("--source-date-epoch", type=int, required=True)

    args = parser.parse_args()
    if args.command == "inventory":
        write_inventory(args.root.resolve(), args.output.resolve())
        return 0
    if args.command == "normalize-msix":
        normalize_msix_timestamps(
            args.path.resolve(),
            args.source_date_epoch,
        )
        return 0

    configuration = _configuration_from_args(args)
    if args.command == "render":
        render_contract(
            configuration,
            template_directory=args.template_directory.resolve(),
            package_root=args.package_root.resolve(),
            appinstaller_path=args.appinstaller_path.resolve(),
            version_info_path=args.version_info_path.resolve(),
            source_icon=args.source_icon.resolve(),
        )
    else:
        validate_rendered_contract(
            configuration,
            manifest_path=args.package_root.resolve() / "AppxManifest.xml",
            appinstaller_path=args.appinstaller_path.resolve(),
            package_root=args.package_root.resolve(),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
