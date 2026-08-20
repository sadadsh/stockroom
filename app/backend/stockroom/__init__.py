"""Stockroom backend package and immutable runtime build identity."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_SOURCE_VERSION = "1.0.0"
_BUILD_IDENTITY_NAME = "stockroom-build-identity.json"
_VERSION_PATTERN = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
)


@dataclass(frozen=True, slots=True)
class BuildIdentity:
    package_version: str
    protocol_version: int
    release_id: str
    source_revision: str


def _packaged_build_identity(root: Path) -> BuildIdentity:
    path = Path(root) / _BUILD_IDENTITY_NAME
    try:
        document = json.loads(path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("packaged Stockroom build identity is unavailable") from exc
    expected = {
        "package_version",
        "protocol_version",
        "release_id",
        "schema",
        "source_revision",
    }
    if type(document) is not dict or set(document) != expected:
        raise RuntimeError("packaged Stockroom build identity is invalid")
    package_version = document["package_version"]
    protocol_version = document["protocol_version"]
    release_id = document["release_id"]
    source_revision = document["source_revision"]
    if (
        type(package_version) is not str
        or _VERSION_PATTERN.fullmatch(package_version) is None
        or type(protocol_version) is not int
        or protocol_version <= 0
        or type(release_id) is not str
        or release_id != f"release-{package_version}"
        or type(source_revision) is not str
        or re.fullmatch(r"[0-9a-f]{40}", source_revision) is None
        or document["schema"] != "stockroom-build-identity/1"
    ):
        raise RuntimeError("packaged Stockroom build identity is invalid")
    return BuildIdentity(
        package_version=package_version,
        protocol_version=protocol_version,
        release_id=release_id,
        source_revision=source_revision,
    )


def _runtime_build_identity() -> BuildIdentity:
    if bool(getattr(sys, "frozen", False)):
        return _packaged_build_identity(
            Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        )
    return BuildIdentity(
        package_version=_SOURCE_VERSION,
        protocol_version=1,
        release_id="development-source",
        source_revision="",
    )


BUILD_IDENTITY = _runtime_build_identity()
__version__ = BUILD_IDENTITY.package_version
__protocol_version__ = BUILD_IDENTITY.protocol_version

__all__ = [
    "BUILD_IDENTITY",
    "BuildIdentity",
    "__protocol_version__",
    "__version__",
]
