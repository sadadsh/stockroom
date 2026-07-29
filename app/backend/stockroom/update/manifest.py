"""Strict schema for a coherent Stockroom release manifest.

The manifest is itself a TUF target.  Its members are relative paths inside one
immutable release directory; their repository target paths are derived from the
release ID so payloads from different releases cannot share a namespace.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping

RELEASE_MANIFEST_NAME = "Release Manifest.json"
RELEASE_MANIFEST_VERSION = 2
SUPPORTED_RELEASE_MANIFEST_VERSIONS = frozenset({1, RELEASE_MANIFEST_VERSION})
MAX_RELEASE_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_RELEASE_MEMBERS = 10_000
MAX_COMPATIBLE_RELEASES = 1_024

_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_VERSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}")
_WORKFLOW_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_PATH_SEGMENT_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._()+@-]{0,127}")
_WINDOWS_RESERVED_NAMES = {
    "aux",
    "clock$",
    "com1",
    "com2",
    "com3",
    "com4",
    "com5",
    "com6",
    "com7",
    "com8",
    "com9",
    "con",
    "lpt1",
    "lpt2",
    "lpt3",
    "lpt4",
    "lpt5",
    "lpt6",
    "lpt7",
    "lpt8",
    "lpt9",
    "nul",
    "prn",
}


class ReleaseManifestError(ValueError):
    """The release manifest is malformed, ambiguous, or internally incoherent."""


@dataclass(frozen=True, slots=True)
class IntegerRange:
    """Inclusive compatibility range."""

    minimum: int
    maximum: int


@dataclass(frozen=True, slots=True)
class SchemaCompatibility:
    """Compatible on-disk schema versions."""

    catalog: IntegerRange
    control: IntegerRange


@dataclass(frozen=True, slots=True)
class MigrationPair:
    """One supported schema transition."""

    source: int
    target: int


@dataclass(frozen=True, slots=True)
class ReleaseMigration:
    """Catalog and control schema transitions shipped by a release."""

    catalog: MigrationPair
    control: MigrationPair


@dataclass(frozen=True, slots=True)
class ReleaseMember:
    """A file that must be present in the coherent release set."""

    path: str
    size: int
    sha256: str
    kind: str


@dataclass(frozen=True, slots=True)
class ReleaseManifest:
    """Validated and deeply immutable release metadata."""

    manifest_version: int
    release_id: str
    package_version: str
    protocol_version: int
    minimum_host_version: str
    api_compatibility: IntegerRange
    workflow_code_versions: Mapping[str, int]
    schema_compatibility: SchemaCompatibility
    migration: ReleaseMigration
    required_eda_bridge_version: str
    required_odbc_driver_version: str
    rollback_release_id: str
    compatible_from_release_ids: tuple[str, ...]
    sbom_sha256: str
    members: tuple[ReleaseMember, ...]

    @classmethod
    def from_bytes(cls, data: bytes) -> ReleaseManifest:
        """Parse a strict UTF-8 JSON manifest and validate all invariants."""

        if not data:
            raise ReleaseManifestError("Release manifest is empty.")
        if len(data) > MAX_RELEASE_MANIFEST_BYTES:
            raise ReleaseManifestError("Release manifest exceeds the size limit.")

        try:
            document = json.loads(
                data.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_nonfinite_number,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReleaseManifestError("Release manifest is not strict UTF-8 JSON.") from exc

        root = _expect_object(document, "release manifest")
        if "manifest_version" not in root:
            raise ReleaseManifestError(
                "release manifest has invalid fields: missing ['manifest_version']."
            )
        manifest_version = _expect_int(root["manifest_version"], "manifest_version", minimum=1)
        if manifest_version not in SUPPORTED_RELEASE_MANIFEST_VERSIONS:
            raise ReleaseManifestError(
                f"Unsupported release manifest version {manifest_version}."
            )
        expected_keys = {
            "api_compatibility",
            "manifest_version",
            "members",
            "migration",
            "minimum_host_version",
            "package_version",
            "protocol_version",
            "release_id",
            "required_eda_bridge_version",
            "required_odbc_driver_version",
            "rollback_release_id",
            "sbom_sha256",
            "schema_compatibility",
            "workflow_code_versions",
        }
        if manifest_version >= 2:
            expected_keys.add("compatible_from_release_ids")
        _expect_exact_keys(root, expected_keys, "release manifest")

        release_id = _expect_release_identifier(root["release_id"], "release_id")
        rollback_release_id = _expect_release_identifier(
            root["rollback_release_id"], "rollback_release_id"
        )
        if release_id.casefold() == rollback_release_id.casefold():
            raise ReleaseManifestError("rollback_release_id must name another release.")
        compatible_from_release_ids = _parse_compatible_releases(
            root.get("compatible_from_release_ids"),
            manifest_version=manifest_version,
            release_id=release_id,
            rollback_release_id=rollback_release_id,
        )

        api_compatibility = _parse_range(root["api_compatibility"], "api_compatibility")
        schema_compatibility = _parse_schema_compatibility(root["schema_compatibility"])
        migration = _parse_release_migration(root["migration"])
        _validate_migration(migration.catalog, schema_compatibility.catalog, "catalog")
        _validate_migration(migration.control, schema_compatibility.control, "control")

        workflows_value = _expect_object(
            root["workflow_code_versions"], "workflow_code_versions"
        )
        if not workflows_value:
            raise ReleaseManifestError("workflow_code_versions must not be empty.")
        workflow_versions: dict[str, int] = {}
        for name, value in workflows_value.items():
            if not _WORKFLOW_PATTERN.fullmatch(name):
                raise ReleaseManifestError(f"Invalid workflow name {name!r}.")
            folded = name.casefold()
            if any(existing.casefold() == folded for existing in workflow_versions):
                raise ReleaseManifestError(
                    f"workflow_code_versions contains a case-insensitive duplicate: {name!r}."
                )
            workflow_versions[name] = _expect_int(
                value, f"workflow_code_versions.{name}", minimum=1
            )

        members_value = root["members"]
        if not isinstance(members_value, list):
            raise ReleaseManifestError("members must be an array.")
        if not members_value:
            raise ReleaseManifestError("members must not be empty.")
        if len(members_value) > MAX_RELEASE_MEMBERS:
            raise ReleaseManifestError("members exceeds the member-count limit.")

        members: list[ReleaseMember] = []
        member_paths: dict[str, str] = {}
        directory_casing: dict[str, str] = {}
        for index, member_value in enumerate(members_value):
            context = f"members[{index}]"
            member_object = _expect_object(member_value, context)
            _expect_exact_keys(member_object, {"kind", "path", "sha256", "size"}, context)
            member_path = _expect_safe_member_path(member_object["path"], f"{context}.path")
            if member_path.casefold() == RELEASE_MANIFEST_NAME.casefold():
                raise ReleaseManifestError(
                    f"{context}.path collides with the release manifest."
                )
            folded_path = member_path.casefold()
            if folded_path in member_paths:
                raise ReleaseManifestError(
                    f"members contains a case-insensitive duplicate path: {member_path!r}."
                )
            if any(
                folded_path.startswith(f"{existing}/")
                or existing.startswith(f"{folded_path}/")
                for existing in member_paths
            ):
                raise ReleaseManifestError(
                    f"members contains a file/directory path collision: {member_path!r}."
                )
            for prefix in _directory_prefixes(member_path):
                folded_prefix = prefix.casefold()
                prior_prefix = directory_casing.get(folded_prefix)
                if prior_prefix is not None and prior_prefix != prefix:
                    raise ReleaseManifestError(
                        f"members contains inconsistent directory casing: {prefix!r}."
                    )
                directory_casing[folded_prefix] = prefix
            member_paths[folded_path] = member_path
            members.append(
                ReleaseMember(
                    path=member_path,
                    size=_expect_int(
                        member_object["size"], f"{context}.size", minimum=0
                    ),
                    sha256=_expect_digest(member_object["sha256"], f"{context}.sha256"),
                    kind=_expect_identifier(member_object["kind"], f"{context}.kind"),
                )
            )

        sbom_sha256 = _expect_digest(root["sbom_sha256"], "sbom_sha256")
        sbom_members = [member for member in members if member.kind == "sbom"]
        if len(sbom_members) != 1:
            raise ReleaseManifestError("members must contain exactly one member of kind 'sbom'.")
        if sbom_members[0].sha256 != sbom_sha256:
            raise ReleaseManifestError("sbom_sha256 does not match the declared SBOM member.")

        return cls(
            manifest_version=manifest_version,
            release_id=release_id,
            package_version=_expect_version(root["package_version"], "package_version"),
            protocol_version=_expect_int(
                root["protocol_version"], "protocol_version", minimum=1
            ),
            minimum_host_version=_expect_version(
                root["minimum_host_version"], "minimum_host_version"
            ),
            api_compatibility=api_compatibility,
            workflow_code_versions=MappingProxyType(workflow_versions),
            schema_compatibility=schema_compatibility,
            migration=migration,
            required_eda_bridge_version=_expect_version(
                root["required_eda_bridge_version"], "required_eda_bridge_version"
            ),
            required_odbc_driver_version=_expect_version(
                root["required_odbc_driver_version"], "required_odbc_driver_version"
            ),
            rollback_release_id=rollback_release_id,
            compatible_from_release_ids=compatible_from_release_ids,
            sbom_sha256=sbom_sha256,
            members=tuple(members),
        )

    def supports_direct_activation_from(self, release_id: str) -> bool:
        """Whether this signed manifest explicitly permits this live predecessor."""

        if not isinstance(release_id, str):
            return False
        folded = release_id.casefold()
        return any(
            predecessor.casefold() == folded
            for predecessor in self.compatible_from_release_ids
        )

    def target_path_for(self, member: ReleaseMember) -> str:
        """Return the TUF target path for a release member."""

        if member not in self.members:
            raise ReleaseManifestError("Member is not declared by this release manifest.")
        return f"Releases/{self.release_id}/{member.path}"


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseManifestError(f"Duplicate JSON key {key!r}.")
        result[key] = value
    return result


def _reject_nonfinite_number(value: str) -> None:
    raise ReleaseManifestError(f"Non-finite JSON number {value!r} is not permitted.")


def _expect_object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReleaseManifestError(f"{context} must be an object.")
    if not all(isinstance(key, str) for key in value):
        raise ReleaseManifestError(f"{context} contains a non-string key.")
    return value


def _expect_exact_keys(value: Mapping[str, Any], expected: set[str], context: str) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append(f"missing {missing}")
        if unknown:
            details.append(f"unknown {unknown}")
        raise ReleaseManifestError(f"{context} has invalid fields: {', '.join(details)}.")


def _expect_int(value: Any, context: str, *, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        raise ReleaseManifestError(f"{context} must be an integer >= {minimum}.")
    return value


def _expect_identifier(value: Any, context: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_PATTERN.fullmatch(value):
        raise ReleaseManifestError(f"{context} is not a valid identifier.")
    return value


def _expect_release_identifier(value: Any, context: str) -> str:
    identifier = _expect_identifier(value, context)
    if (
        identifier.endswith(".")
        or identifier.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES
    ):
        raise ReleaseManifestError(f"{context} is not a safe release directory name.")
    return identifier


def _parse_compatible_releases(
    value: Any,
    *,
    manifest_version: int,
    release_id: str,
    rollback_release_id: str,
) -> tuple[str, ...]:
    if manifest_version == 1:
        return (rollback_release_id,)
    if not isinstance(value, list):
        raise ReleaseManifestError("compatible_from_release_ids must be an array.")
    if not 1 <= len(value) <= MAX_COMPATIBLE_RELEASES:
        raise ReleaseManifestError(
            "compatible_from_release_ids must contain between 1 and "
            f"{MAX_COMPATIBLE_RELEASES} releases."
        )
    compatible: list[str] = []
    folded: set[str] = set()
    for index, candidate in enumerate(value):
        predecessor = _expect_release_identifier(
            candidate,
            f"compatible_from_release_ids[{index}]",
        )
        normalized = predecessor.casefold()
        if normalized == release_id.casefold():
            raise ReleaseManifestError(
                "compatible_from_release_ids must not contain the candidate release."
            )
        if normalized in folded:
            raise ReleaseManifestError(
                "compatible_from_release_ids contains a case-insensitive duplicate."
            )
        folded.add(normalized)
        compatible.append(predecessor)
    if rollback_release_id.casefold() not in folded:
        raise ReleaseManifestError(
            "compatible_from_release_ids must contain rollback_release_id."
        )
    return tuple(compatible)


def _expect_version(value: Any, context: str) -> str:
    if not isinstance(value, str) or not _VERSION_PATTERN.fullmatch(value):
        raise ReleaseManifestError(f"{context} is not a valid version.")
    return value


def _expect_digest(value: Any, context: str) -> str:
    if not isinstance(value, str) or not _DIGEST_PATTERN.fullmatch(value):
        raise ReleaseManifestError(f"{context} must be a lowercase SHA-256 digest.")
    return value


def _expect_safe_member_path(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 240:
        raise ReleaseManifestError(f"{context} is not a valid release-relative path.")
    if "\\" in value or ":" in value or value.startswith("/"):
        raise ReleaseManifestError(f"{context} is not a safe release-relative path.")

    path = PurePosixPath(value)
    if path.as_posix() != value or any(part in {"", ".", ".."} for part in path.parts):
        raise ReleaseManifestError(f"{context} is not a normalized release-relative path.")

    for segment in path.parts:
        if (
            not _PATH_SEGMENT_PATTERN.fullmatch(segment)
            or segment.endswith((" ", "."))
            or segment.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES
        ):
            raise ReleaseManifestError(f"{context} contains an unsafe Windows path segment.")
    return value


def _directory_prefixes(path: str) -> tuple[str, ...]:
    parts = path.split("/")[:-1]
    return tuple("/".join(parts[:index]) for index in range(1, len(parts) + 1))


def _parse_range(value: Any, context: str) -> IntegerRange:
    range_object = _expect_object(value, context)
    _expect_exact_keys(range_object, {"maximum", "minimum"}, context)
    minimum = _expect_int(range_object["minimum"], f"{context}.minimum", minimum=1)
    maximum = _expect_int(range_object["maximum"], f"{context}.maximum", minimum=1)
    if minimum > maximum:
        raise ReleaseManifestError(f"{context}.minimum must be <= maximum.")
    return IntegerRange(minimum=minimum, maximum=maximum)


def _parse_schema_compatibility(value: Any) -> SchemaCompatibility:
    schema_object = _expect_object(value, "schema_compatibility")
    _expect_exact_keys(schema_object, {"catalog", "control"}, "schema_compatibility")
    return SchemaCompatibility(
        catalog=_parse_range(
            schema_object["catalog"], "schema_compatibility.catalog"
        ),
        control=_parse_range(
            schema_object["control"], "schema_compatibility.control"
        ),
    )


def _parse_migration_pair(value: Any, context: str) -> MigrationPair:
    pair_object = _expect_object(value, context)
    _expect_exact_keys(pair_object, {"from", "to"}, context)
    source = _expect_int(pair_object["from"], f"{context}.from", minimum=1)
    target = _expect_int(pair_object["to"], f"{context}.to", minimum=1)
    if source > target:
        raise ReleaseManifestError(f"{context}.from must be <= to.")
    return MigrationPair(source=source, target=target)


def _parse_release_migration(value: Any) -> ReleaseMigration:
    migration_object = _expect_object(value, "migration")
    _expect_exact_keys(migration_object, {"catalog", "control"}, "migration")
    return ReleaseMigration(
        catalog=_parse_migration_pair(migration_object["catalog"], "migration.catalog"),
        control=_parse_migration_pair(migration_object["control"], "migration.control"),
    )


def _validate_migration(
    migration: MigrationPair, compatibility: IntegerRange, schema_name: str
) -> None:
    if not compatibility.minimum <= migration.target <= compatibility.maximum:
        raise ReleaseManifestError(
            f"migration.{schema_name}.to is outside schema_compatibility.{schema_name}."
        )
