"""Build Stockroom's portable native-EXE archive from a verified MSIX."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import unquote

_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


class PortableReleaseError(ValueError):
    """The signed package cannot become a safe portable release."""


def _portable_path(name: str) -> str | None:
    if "\\" in name:
        raise PortableReleaseError("package member uses a Windows path separator")
    decoded = unquote(name)
    segments = decoded.rstrip("/").split("/")
    if decoded.startswith("/") or any(
        segment in {"", ".", ".."} or ":" in segment for segment in segments
    ):
        raise PortableReleaseError("package member path is unsafe")
    if segments[0] == "WindowHost" and len(segments) > 1:
        relative = "/".join(segments[1:])
        return "Stockroom.exe" if relative == "Stockroom.WindowHost.exe" else relative
    if segments[0] == "Update" and len(segments) > 1:
        return "/".join(segments)
    return None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_portable_release(msix_path: Path, output_path: Path) -> dict[str, object]:
    """Write a deterministic ZIP whose root executable is ``Stockroom.exe``."""

    msix_path = Path(msix_path).resolve(strict=True)
    output_path = Path(output_path).resolve()
    members: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(msix_path) as package:
            for info in package.infolist():
                if info.is_dir():
                    continue
                destination = _portable_path(info.filename)
                if destination is None:
                    continue
                if destination in members:
                    raise PortableReleaseError(
                        f"portable package contains duplicate member {destination!r}"
                    )
                members[destination] = package.read(info)
    except zipfile.BadZipFile as exc:
        raise PortableReleaseError("MSIX is not a readable ZIP package") from exc

    required = {
        "Stockroom.exe",
        "Stockroom.WindowHost.dll",
        "Update/Update Feed.json",
    }
    missing = sorted(required - members.keys())
    has_worker = any(
        name.startswith("Update/Initial Release/")
        and name.endswith("/Backend/Stockroom Worker.exe")
        for name in members
    )
    if missing or not has_worker or not members["Stockroom.exe"].startswith(b"MZ"):
        raise PortableReleaseError(
            f"portable package is incomplete; missing={missing}, worker={has_worker}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}-", suffix=".tmp", dir=output_path.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for name in sorted(members):
                info = zipfile.ZipInfo(name, date_time=_ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, members[name], compresslevel=9)
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)

    payload = output_path.read_bytes()
    return {
        "schema": "stockroom-portable-release/1",
        "path": output_path.name,
        "sha256": _sha256(payload),
        "size": len(payload),
        "files": len(members),
        "executable_sha256": _sha256(members["Stockroom.exe"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--msix", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build_portable_release(args.msix, args.output), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
