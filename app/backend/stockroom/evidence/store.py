"""Content-addressed provider evidence with exact semantic verification.

Provider adapters may write only sanitized immutable observations here.  The
canonical component model remains a later reconciliation product; evidence
never writes canonical records or the publication repository directly.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeAlias
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MEDIA_TYPE = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*\Z")
_PROVIDER_KEY = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_ARTIFACT_ROLE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_MAX_OBJECT_BYTES = 64 * 1024 * 1024
_CAD_REQUIRED_ROLES = frozenset({"symbol", "footprint", "model", "validation_report"})
DEFAULT_CAD_PROVIDER_PREFERENCE = ("ultralibrarian", "snapmagic")
_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "apikey",
        "api_key",
        "cookie",
        "password",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "client_secret",
    }
)


class EvidenceError(RuntimeError):
    """The evidence store rejected an unsafe or invalid operation."""


class EvidenceCorruption(EvidenceError):
    """Stored bytes do not match their content address."""


class EvidenceManifestMismatch(EvidenceError):
    """A manifest does not prove the exact requested provider operation."""


class ExactIdentity(Protocol):
    @property
    def authoritative_manufacturer_key(self) -> str: ...

    @property
    def mpn_canonical(self) -> str: ...


class EvidenceOperation(Protocol):
    @property
    def label(self) -> str: ...


@dataclass(frozen=True, slots=True)
class EvidenceArtifact:
    """One immutable file that contributes to a provider operation."""

    role: str
    data: bytes
    media_type: str
    suggested_name: str = ""

    def __post_init__(self) -> None:
        if type(self.role) is not str or _ARTIFACT_ROLE.fullmatch(self.role) is None:
            raise EvidenceError("artifact role is not canonical")
        if type(self.data) is not bytes or not self.data:
            raise EvidenceError("artifact data must be non-empty immutable bytes")
        if type(self.media_type) is not str or _MEDIA_TYPE.fullmatch(self.media_type) is None:
            raise EvidenceError("artifact media type is not canonical")
        if self.suggested_name:
            _required_text(self.suggested_name, "artifact suggested name", limit=255)
            if Path(self.suggested_name).name != self.suggested_name:
                raise EvidenceError("artifact suggested name must not contain a path")


@dataclass(frozen=True, slots=True)
class VerifiedRoleArtifact:
    """One reverified CAD variant addressable by exact identity and role."""

    manifest_digest: str
    artifact_digest: str
    role: str
    data: bytes
    media_type: str
    suggested_name: str
    provider_key: str
    adapter_version: str
    operation: str
    source_manifests: tuple[str, ...] = ()


def _canonical_json(value: JsonValue) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _sanitize_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.query:
        return value
    filtered = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() not in _SENSITIVE_KEYS
    ]
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(filtered),
            parsed.fragment,
        )
    )


def _sanitize_json(value: object, *, depth: int = 0) -> JsonValue:
    if depth > 64:
        raise EvidenceError("provider evidence exceeds the maximum JSON nesting depth")
    if value is None:
        return None
    if type(value) is bool:
        return bool(value)
    if type(value) is int:
        return int(value)
    if type(value) is float:
        if not math.isfinite(value):
            raise EvidenceError("provider evidence contains a non-finite number")
        return value
    if type(value) is str:
        return _sanitize_url(value)
    if type(value) is list:
        return [_sanitize_json(item, depth=depth + 1) for item in value]
    if type(value) is dict:
        document: dict[str, JsonValue] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise EvidenceError("provider evidence JSON object keys must be strings")
            if key.casefold() in _SENSITIVE_KEYS:
                continue
            document[key] = _sanitize_json(item, depth=depth + 1)
        return document
    raise EvidenceError("provider evidence must be strict JSON")


def _required_text(value: object, name: str, *, limit: int = 512) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > limit
        or any(ord(character) < 32 for character in value)
    ):
        raise EvidenceError(f"{name} is not canonical")
    return value


def _identity_document(identity: ExactIdentity) -> dict[str, JsonValue]:
    manufacturer = _required_text(
        getattr(identity, "authoritative_manufacturer_key", None),
        "authoritative manufacturer key",
    )
    mpn = _required_text(getattr(identity, "mpn_canonical", None), "canonical MPN")
    return {
        "authoritative_manufacturer_key": manufacturer,
        "mpn_canonical": mpn,
    }


class EvidenceStore:
    """Install and verify immutable objects beneath one local CAS root."""

    def __init__(self, root: Path, *, max_object_bytes: int = _MAX_OBJECT_BYTES):
        supplied = Path(root)
        if not supplied.is_absolute():
            raise ValueError("evidence root must be absolute")
        if supplied.exists() and supplied.is_symlink():
            raise ValueError("evidence root must not be a filesystem link")
        if type(max_object_bytes) is not int or not 1 <= max_object_bytes <= _MAX_OBJECT_BYTES:
            raise ValueError("max_object_bytes is outside the supported bound")
        supplied.mkdir(parents=True, exist_ok=True)
        resolved = supplied.resolve(strict=True)
        if not resolved.is_dir():
            raise ValueError("evidence root must be a directory")
        self._root = resolved
        self._max_object_bytes = max_object_bytes

    @property
    def root(self) -> Path:
        return self._root

    def object_path(self, digest: str) -> Path:
        if type(digest) is not str or _DIGEST.fullmatch(digest) is None:
            raise ValueError("evidence digest is not canonical")
        hexadecimal = digest.removeprefix("sha256:")
        return self._root / "Objects" / "sha256" / hexadecimal[:2] / hexadecimal[2:]

    def _verify_path(self, path: Path, digest: str) -> int:
        if not path.is_file() or path.is_symlink():
            raise EvidenceCorruption("evidence object is missing or linked")
        data = path.read_bytes()
        if len(data) > self._max_object_bytes or _digest(data) != digest:
            raise EvidenceCorruption("evidence object bytes do not match their digest")
        return len(data)

    def install_bytes(self, data: bytes) -> str:
        if type(data) is not bytes:
            raise TypeError("evidence object must be immutable bytes")
        if not data or len(data) > self._max_object_bytes:
            raise EvidenceError("evidence object size is outside the supported bound")
        digest = _digest(data)
        destination = self.object_path(digest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            self._verify_path(destination, digest)
            return digest

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".Evidence-",
            suffix=".tmp",
            dir=destination.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, destination)
            except FileExistsError:
                pass
            except OSError as exc:
                raise EvidenceError(
                    "evidence filesystem does not support atomic installation"
                ) from exc
            self._verify_path(destination, digest)
        finally:
            temporary.unlink(missing_ok=True)
        return digest

    def object_bytes(self, digest: str) -> bytes:
        path = self.object_path(digest)
        self._verify_path(path, digest)
        return path.read_bytes()

    def _canonical_manifest(self, digest: str) -> dict[str, JsonValue]:
        data = self.object_bytes(digest)
        try:
            manifest = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EvidenceCorruption("evidence manifest is not canonical JSON") from exc
        if type(manifest) is not dict or _canonical_json(manifest) != data:
            raise EvidenceCorruption("evidence manifest is not canonical JSON")
        return manifest

    def _role_index_directory(self, identity: ExactIdentity, role: str) -> Path:
        if type(role) is not str or _ARTIFACT_ROLE.fullmatch(role) is None:
            raise EvidenceError("artifact role is not canonical")
        identity_key = hashlib.sha256(_canonical_json(_identity_document(identity))).hexdigest()
        directory = (
            self._root
            / "Indexes"
            / "Exact Identity"
            / "sha256"
            / identity_key[:2]
            / identity_key[2:]
            / role
        )
        directory.mkdir(parents=True, exist_ok=True)
        if directory.is_symlink() or not directory.resolve(strict=True).is_relative_to(self._root):
            raise EvidenceCorruption("evidence role index escaped its store root")
        return directory

    def _index_manifest_role(
        self,
        *,
        identity: ExactIdentity,
        role: str,
        manifest_digest: str,
        provider_key: str,
    ) -> None:
        hexadecimal = manifest_digest.removeprefix("sha256:")
        if _DIGEST.fullmatch(manifest_digest) is None:
            raise EvidenceError("evidence manifest digest is not canonical")
        pointer: JsonValue = {
            "identity": _identity_document(identity),
            "manifest_digest": manifest_digest,
            "provider": provider_key,
            "role": role,
            "schema": "stockroom.cad-role-index/1",
        }
        data = _canonical_json(pointer)
        directory = self._role_index_directory(identity, role)
        destination = directory / f"{hexadecimal}.json"
        if destination.exists():
            if destination.is_symlink() or destination.read_bytes() != data:
                raise EvidenceCorruption("evidence role index entry is corrupt")
            return

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".Evidence-Index-",
            suffix=".tmp",
            dir=directory,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, destination)
            except FileExistsError:
                pass
            except OSError as exc:
                raise EvidenceError(
                    "evidence filesystem does not support atomic role indexing"
                ) from exc
            if destination.is_symlink() or destination.read_bytes() != data:
                raise EvidenceCorruption("evidence role index entry is corrupt")
        finally:
            temporary.unlink(missing_ok=True)

    def record_provider_success(
        self,
        *,
        identity: ExactIdentity,
        operation: EvidenceOperation,
        provider_key: str,
        adapter_version: str,
        payload: object,
        media_type: str,
    ) -> str:
        _required_text(
            getattr(identity, "authoritative_manufacturer_key", None),
            "authoritative manufacturer key",
        )
        _required_text(getattr(identity, "mpn_canonical", None), "canonical MPN")
        _required_text(getattr(operation, "label", None), "operation label")
        if type(provider_key) is not str or _PROVIDER_KEY.fullmatch(provider_key) is None:
            raise EvidenceError("provider key is not canonical")
        _required_text(adapter_version, "adapter version", limit=128)
        if type(media_type) is not str or _MEDIA_TYPE.fullmatch(media_type) is None:
            raise EvidenceError("media type is not canonical")

        sanitized = _sanitize_json(payload)
        payload_bytes = _canonical_json(sanitized)
        payload_digest = self.install_bytes(payload_bytes)
        manifest: JsonValue = {
            "adapter_version": adapter_version,
            "identity": {
                "authoritative_manufacturer_key": identity.authoritative_manufacturer_key,
                "mpn_canonical": identity.mpn_canonical,
            },
            "operation": operation.label,
            "payload": {
                "bytes": len(payload_bytes),
                "digest": payload_digest,
                "disposition": "local_cas",
                "media_type": media_type,
            },
            "provider": provider_key,
            "sanitization": {
                "credential_fields_removed": True,
                "credential_query_values_removed": True,
            },
            "schema": "stockroom.provider-evidence/1",
        }
        return self.install_bytes(_canonical_json(manifest))

    def record_provider_artifact_success(
        self,
        *,
        identity: ExactIdentity,
        operation: EvidenceOperation,
        provider_key: str,
        adapter_version: str,
        artifacts: tuple[EvidenceArtifact, ...],
    ) -> str:
        """Record the actual files required to satisfy one CAD operation.

        CAD success is intentionally stronger than "a vendor download landed":
        the manifest must contain a symbol, footprint, model, and validation
        report. Optional role-labelled objects may retain the original provider
        bundle without weakening that minimum.
        """
        _required_text(
            getattr(identity, "authoritative_manufacturer_key", None),
            "authoritative manufacturer key",
        )
        _required_text(getattr(identity, "mpn_canonical", None), "canonical MPN")
        operation_label = _required_text(
            getattr(operation, "label", None),
            "operation label",
        )
        if not operation_label.startswith("cad:"):
            raise EvidenceError("artifact evidence currently supports CAD operations only")
        if type(provider_key) is not str or _PROVIDER_KEY.fullmatch(provider_key) is None:
            raise EvidenceError("provider key is not canonical")
        _required_text(adapter_version, "adapter version", limit=128)
        if type(artifacts) is not tuple or not artifacts:
            raise EvidenceError("artifact evidence must be a non-empty tuple")
        if any(type(artifact) is not EvidenceArtifact for artifact in artifacts):
            raise EvidenceError("artifact evidence contains an invalid object")

        roles = [artifact.role for artifact in artifacts]
        if len(set(roles)) != len(roles):
            raise EvidenceError("artifact evidence roles must be unique")
        missing = sorted(_CAD_REQUIRED_ROLES.difference(roles))
        if missing:
            raise EvidenceError(
                "CAD artifact evidence is incomplete: missing " + ", ".join(missing)
            )

        objects: list[JsonValue] = []
        for artifact in sorted(artifacts, key=lambda item: item.role):
            digest = self.install_bytes(artifact.data)
            reference: dict[str, JsonValue] = {
                "bytes": len(artifact.data),
                "digest": digest,
                "disposition": "local_cas",
                "media_type": artifact.media_type,
                "provider": provider_key,
                "role": artifact.role,
            }
            if artifact.suggested_name:
                reference["suggested_name"] = artifact.suggested_name
            objects.append(reference)

        manifest: JsonValue = {
            "adapter_version": adapter_version,
            "identity": {
                "authoritative_manufacturer_key": identity.authoritative_manufacturer_key,
                "mpn_canonical": identity.mpn_canonical,
            },
            "objects": objects,
            "operation": operation_label,
            "provider": provider_key,
            "required_roles": sorted(_CAD_REQUIRED_ROLES),
            "schema": "stockroom.provider-artifact-evidence/1",
        }
        return self.install_bytes(_canonical_json(manifest))

    def record_role_artifact_success(
        self,
        *,
        identity: ExactIdentity,
        operation: EvidenceOperation,
        provider_key: str,
        adapter_version: str,
        artifacts: tuple[EvidenceArtifact, ...],
        validation_report: bytes,
        source_manifests: tuple[str, ...] = (),
    ) -> str:
        """Record an independently validated partial CAD role set.

        Role manifests are append-only variants. They never select or replace an
        active library reference. ``source_manifests`` binds a derived role set,
        such as native Altium, to the exact KiCad bytes used by cross-EDA
        verification.
        """
        identity_document = _identity_document(identity)
        operation_label = _required_text(
            getattr(operation, "label", None),
            "operation label",
        )
        if not operation_label.startswith("cad:"):
            raise EvidenceError("role evidence currently supports CAD operations only")
        if type(provider_key) is not str or _PROVIDER_KEY.fullmatch(provider_key) is None:
            raise EvidenceError("provider key is not canonical")
        _required_text(adapter_version, "adapter version", limit=128)
        if type(artifacts) is not tuple or not artifacts:
            raise EvidenceError("role evidence must contain at least one artifact")
        if any(type(artifact) is not EvidenceArtifact for artifact in artifacts):
            raise EvidenceError("role evidence contains an invalid object")
        roles = [artifact.role for artifact in artifacts]
        if "validation_report" in roles or len(set(roles)) != len(roles):
            raise EvidenceError("role evidence artifact roles must be unique data roles")
        if type(validation_report) is not bytes or not validation_report:
            raise EvidenceError("role evidence validation report must be non-empty bytes")
        try:
            report = json.loads(validation_report)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EvidenceError("role evidence validation report is not canonical JSON") from exc
        if type(report) is not dict or _canonical_json(report) != validation_report:
            raise EvidenceError("role evidence validation report is not canonical JSON")

        if type(source_manifests) is not tuple or any(
            type(item) is not str or _DIGEST.fullmatch(item) is None for item in source_manifests
        ):
            raise EvidenceError("role evidence source manifests are invalid")
        sorted_sources = sorted(set(source_manifests))
        if len(sorted_sources) != len(source_manifests):
            raise EvidenceError("role evidence source manifests must be unique")
        for source_digest in sorted_sources:
            self.verify_role_artifact_success(
                source_digest,
                identity=identity,
            )

        objects: list[JsonValue] = []
        for artifact in sorted(artifacts, key=lambda item: item.role):
            digest = self.install_bytes(artifact.data)
            reference: dict[str, JsonValue] = {
                "bytes": len(artifact.data),
                "digest": digest,
                "disposition": "local_cas",
                "media_type": artifact.media_type,
                "provider": provider_key,
                "role": artifact.role,
            }
            if artifact.suggested_name:
                reference["suggested_name"] = artifact.suggested_name
            objects.append(reference)

        report_digest = self.install_bytes(validation_report)
        manifest: JsonValue = {
            "adapter_version": adapter_version,
            "identity": identity_document,
            "objects": objects,
            "operation": operation_label,
            "provider": provider_key,
            "roles": sorted(roles),
            "schema": "stockroom.cad-role-evidence/1",
            "source_manifests": sorted_sources,
            "validation_report": {
                "bytes": len(validation_report),
                "digest": report_digest,
                "disposition": "local_cas",
                "media_type": "application/json",
            },
        }
        digest = self.install_bytes(_canonical_json(manifest))
        self.verify_role_artifact_success(digest, identity=identity)
        self.index_artifact_manifest(
            digest,
            identity=identity,
            roles=tuple(sorted(roles)),
        )
        return digest

    def index_artifact_manifest(
        self,
        digest: str,
        *,
        identity: ExactIdentity,
        roles: tuple[str, ...],
    ) -> None:
        """Append verified role pointers without changing an active selection."""
        if type(roles) is not tuple or not roles or len(set(roles)) != len(roles):
            raise EvidenceError("indexed artifact roles must be a unique non-empty tuple")
        manifest = self._canonical_manifest(digest)
        if manifest.get("identity") != _identity_document(identity):
            raise EvidenceManifestMismatch("evidence manifest does not match the exact identity")
        schema = manifest.get("schema")
        if schema == "stockroom.cad-role-evidence/1":
            self.verify_role_artifact_success(digest, identity=identity)
        elif schema == "stockroom.provider-artifact-evidence/1":
            operation_label = manifest.get("operation")
            if type(operation_label) is not str:
                raise EvidenceCorruption("CAD artifact evidence operation is invalid")
            self._verify_artifact_manifest(manifest, operation_label)
        else:
            raise EvidenceManifestMismatch("manifest does not contain indexable CAD artifacts")

        objects = manifest.get("objects")
        assert isinstance(objects, list)
        available = {reference.get("role") for reference in objects if isinstance(reference, dict)}
        provider_key = manifest.get("provider")
        if (
            type(provider_key) is not str
            or _PROVIDER_KEY.fullmatch(provider_key) is None
            or any(
                type(role) is not str
                or _ARTIFACT_ROLE.fullmatch(role) is None
                or role not in available
                or role == "validation_report"
                for role in roles
            )
        ):
            raise EvidenceManifestMismatch("manifest does not prove every indexed artifact role")
        for role in roles:
            self._index_manifest_role(
                identity=identity,
                role=role,
                manifest_digest=digest,
                provider_key=provider_key,
            )

    def verify_role_artifact_success(
        self,
        digest: str,
        *,
        identity: ExactIdentity,
        required_roles: tuple[str, ...] = (),
        _seen: frozenset[str] = frozenset(),
    ) -> dict[str, JsonValue]:
        """Reverify a partial role manifest and every manifest it depends on."""
        if digest in _seen:
            raise EvidenceCorruption("role evidence source manifests contain a cycle")
        manifest = self._canonical_manifest(digest)
        if manifest.get("schema") != "stockroom.cad-role-evidence/1" or manifest.get(
            "identity"
        ) != _identity_document(identity):
            raise EvidenceManifestMismatch("role evidence does not match the exact identity")
        operation = manifest.get("operation")
        provider = manifest.get("provider")
        adapter_version = manifest.get("adapter_version")
        roles = manifest.get("roles")
        objects = manifest.get("objects")
        source_manifests = manifest.get("source_manifests")
        if (
            type(operation) is not str
            or not operation.startswith("cad:")
            or type(provider) is not str
            or _PROVIDER_KEY.fullmatch(provider) is None
            or type(adapter_version) is not str
            or not adapter_version
            or type(roles) is not list
            or not roles
            or roles != sorted(roles)
            or len(set(str(role) for role in roles)) != len(roles)
            or type(objects) is not list
            or len(objects) != len(roles)
            or type(source_manifests) is not list
            or source_manifests != sorted(source_manifests)
            or len(set(str(item) for item in source_manifests)) != len(source_manifests)
        ):
            raise EvidenceCorruption("role evidence manifest envelope is invalid")
        if any(
            type(role) is not str
            or _ARTIFACT_ROLE.fullmatch(role) is None
            or role == "validation_report"
            for role in roles
        ):
            raise EvidenceCorruption("role evidence manifest roles are invalid")
        if any(role not in roles for role in required_roles):
            raise EvidenceManifestMismatch("role evidence does not contain every required role")

        observed_roles: set[str] = set()
        for reference in objects:
            if type(reference) is not dict:
                raise EvidenceCorruption("role evidence object is invalid")
            role = reference.get("role")
            object_digest = reference.get("digest")
            byte_count = reference.get("bytes")
            media_type = reference.get("media_type")
            suggested_name = reference.get("suggested_name", "")
            if (
                type(role) is not str
                or role not in roles
                or role in observed_roles
                or type(object_digest) is not str
                or type(byte_count) is not int
                or byte_count <= 0
                or type(media_type) is not str
                or _MEDIA_TYPE.fullmatch(media_type) is None
                or type(suggested_name) is not str
                or (suggested_name and Path(suggested_name).name != suggested_name)
                or reference.get("provider") != provider
                or reference.get("disposition") != "local_cas"
                or self._verify_path(self.object_path(object_digest), object_digest) != byte_count
            ):
                raise EvidenceCorruption("role evidence object does not match stored bytes")
            observed_roles.add(role)
        if observed_roles != set(roles):
            raise EvidenceCorruption("role evidence object roles do not match its declaration")

        report_reference = manifest.get("validation_report")
        if type(report_reference) is not dict:
            raise EvidenceCorruption("role evidence validation reference is invalid")
        report_digest = report_reference.get("digest")
        report_bytes = report_reference.get("bytes")
        if (
            type(report_digest) is not str
            or type(report_bytes) is not int
            or report_bytes <= 0
            or report_reference.get("media_type") != "application/json"
            or report_reference.get("disposition") != "local_cas"
            or self._verify_path(self.object_path(report_digest), report_digest) != report_bytes
        ):
            raise EvidenceCorruption("role evidence validation bytes do not match their digest")
        validation_bytes = self.object_bytes(report_digest)
        try:
            validation = json.loads(validation_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EvidenceCorruption("role evidence validation is not canonical JSON") from exc
        if (
            type(validation) is not dict
            or _canonical_json(validation) != validation_bytes
            or validation.get("schema") != "stockroom.cad-role-validation/1"
            or validation.get("valid") is not True
            or validation.get("identity") != manifest.get("identity")
            or validation.get("operation") != operation
            or validation.get("provider") != provider
            or validation.get("roles") != roles
            or validation.get("source_manifests") != source_manifests
        ):
            raise EvidenceCorruption(
                "role validation report does not prove the manifest identity and roles"
            )

        next_seen = _seen | {digest}
        for source_digest in source_manifests:
            if type(source_digest) is not str or _DIGEST.fullmatch(source_digest) is None:
                raise EvidenceCorruption("role evidence source manifest digest is invalid")
            self.verify_role_artifact_success(
                source_digest,
                identity=identity,
                _seen=next_seen,
            )
        return manifest

    def verified_role_artifacts(
        self,
        digest: str,
        *,
        identity: ExactIdentity,
        roles: tuple[str, ...],
    ) -> dict[str, VerifiedRoleArtifact]:
        """Return requested bytes only after revalidating their complete manifest."""
        if type(roles) is not tuple or not roles or len(set(roles)) != len(roles):
            raise EvidenceError("requested artifact roles must be a unique non-empty tuple")
        manifest = self._canonical_manifest(digest)
        schema = manifest.get("schema")
        if manifest.get("identity") != _identity_document(identity):
            raise EvidenceManifestMismatch("evidence manifest does not match the exact identity")
        if schema == "stockroom.cad-role-evidence/1":
            self.verify_role_artifact_success(
                digest,
                identity=identity,
                required_roles=roles,
            )
        elif schema == "stockroom.provider-artifact-evidence/1":
            operation_label = manifest.get("operation")
            if type(operation_label) is not str:
                raise EvidenceCorruption("CAD artifact evidence operation is invalid")
            self._verify_artifact_manifest(manifest, operation_label)
        else:
            raise EvidenceManifestMismatch("manifest does not contain CAD role evidence")

        objects = manifest.get("objects")
        assert isinstance(objects, list)
        by_role = {
            str(reference["role"]): reference
            for reference in objects
            if isinstance(reference, dict) and "role" in reference
        }
        if any(role not in by_role for role in roles):
            raise EvidenceManifestMismatch("manifest does not contain every requested role")
        provider = str(manifest["provider"])
        adapter_version = str(manifest["adapter_version"])
        operation = str(manifest["operation"])
        source_values = manifest.get("source_manifests", [])
        if not isinstance(source_values, list):
            raise EvidenceCorruption("role evidence source manifests are invalid")
        source_manifests = tuple(str(item) for item in source_values if isinstance(item, str))
        result: dict[str, VerifiedRoleArtifact] = {}
        for role in roles:
            reference = by_role[role]
            object_digest = str(reference["digest"])
            data = self.object_bytes(object_digest)
            result[role] = VerifiedRoleArtifact(
                manifest_digest=digest,
                artifact_digest=object_digest,
                role=role,
                data=data,
                media_type=str(reference["media_type"]),
                suggested_name=str(reference.get("suggested_name", "")),
                provider_key=provider,
                adapter_version=adapter_version,
                operation=operation,
                source_manifests=source_manifests,
            )
        return result

    def verified_role_validation_report(
        self,
        digest: str,
        *,
        identity: ExactIdentity,
    ) -> dict[str, JsonValue]:
        """Return the canonical validation document after full dependency revalidation."""

        manifest = self.verify_role_artifact_success(digest, identity=identity)
        reference = manifest.get("validation_report")
        assert isinstance(reference, dict)
        data = self.object_bytes(str(reference["digest"]))
        validation = json.loads(data)
        assert isinstance(validation, dict)
        return validation

    def verified_cad_validation_report(
        self,
        digest: str,
        *,
        identity: ExactIdentity,
    ) -> dict[str, JsonValue]:
        """Return validation from either current role evidence or retained full CAD evidence."""

        manifest = self._canonical_manifest(digest)
        if manifest.get("schema") == "stockroom.cad-role-evidence/1":
            return self.verified_role_validation_report(digest, identity=identity)
        artifact = self.verified_role_artifacts(
            digest,
            identity=identity,
            roles=("validation_report",),
        )["validation_report"]
        validation = json.loads(artifact.data)
        if not isinstance(validation, dict):
            raise EvidenceCorruption("CAD validation report is not a JSON object")
        return validation

    def list_role_variants(
        self,
        *,
        identity: ExactIdentity,
        role: str,
        provider_preference: tuple[str, ...] = DEFAULT_CAD_PROVIDER_PREFERENCE,
    ) -> tuple[VerifiedRoleArtifact, ...]:
        """List every verified variant, ranked without selecting or deleting one."""
        directory = self._role_index_directory(identity, role)
        preference = {provider: index for index, provider in enumerate(provider_preference)}

        def provider_rank(provider_key: str) -> tuple[int, int]:
            exact = preference.get(provider_key)
            if exact is not None:
                return exact, 0
            for family, index in preference.items():
                if provider_key.endswith(f"-{family}"):
                    return index, 1
            return len(preference), 0

        variants: list[VerifiedRoleArtifact] = []
        for path in sorted(directory.glob("*.json"), key=lambda item: item.name):
            if not path.is_file() or path.is_symlink():
                raise EvidenceCorruption("evidence role index entry is missing or linked")
            data = path.read_bytes()
            try:
                pointer = json.loads(data)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise EvidenceCorruption("evidence role index entry is not canonical JSON") from exc
            if (
                type(pointer) is not dict
                or _canonical_json(pointer) != data
                or pointer.get("schema") != "stockroom.cad-role-index/1"
                or pointer.get("identity") != _identity_document(identity)
                or pointer.get("role") != role
                or type(pointer.get("manifest_digest")) is not str
            ):
                raise EvidenceCorruption("evidence role index entry is invalid")
            artifact = self.verified_role_artifacts(
                str(pointer["manifest_digest"]),
                identity=identity,
                roles=(role,),
            )[role]
            if pointer.get("provider") != artifact.provider_key:
                raise EvidenceCorruption("evidence role index provider does not match its manifest")
            variants.append(artifact)
        return tuple(
            sorted(
                variants,
                key=lambda item: (
                    *provider_rank(item.provider_key),
                    item.provider_key,
                    item.manifest_digest,
                ),
            )
        )

    def verify_provider_success(
        self,
        digest: str,
        *,
        identity: ExactIdentity,
        operation: EvidenceOperation,
        provider_key: str,
        adapter_version: str,
    ) -> dict[str, JsonValue]:
        manifest = self._canonical_manifest(digest)
        expected_identity = {
            "authoritative_manufacturer_key": identity.authoritative_manufacturer_key,
            "mpn_canonical": identity.mpn_canonical,
        }
        schema = manifest.get("schema")
        if (
            schema
            not in {
                "stockroom.provider-evidence/1",
                "stockroom.provider-artifact-evidence/1",
            }
            or manifest.get("identity") != expected_identity
            or manifest.get("operation") != operation.label
            or manifest.get("provider") != provider_key
            or manifest.get("adapter_version") != adapter_version
        ):
            raise EvidenceManifestMismatch("evidence manifest does not match the provider attempt")
        if schema == "stockroom.provider-artifact-evidence/1":
            self._verify_artifact_manifest(manifest, operation.label)
            return manifest
        payload = manifest.get("payload")
        if type(payload) is not dict:
            raise EvidenceCorruption("evidence manifest payload reference is invalid")
        payload_digest = payload.get("digest")
        payload_bytes = payload.get("bytes")
        if (
            type(payload_digest) is not str
            or type(payload_bytes) is not int
            or payload_bytes <= 0
            or self._verify_path(self.object_path(payload_digest), payload_digest) != payload_bytes
        ):
            raise EvidenceCorruption("evidence manifest payload does not match stored bytes")
        return manifest

    def _verify_artifact_manifest(
        self,
        manifest: dict[str, JsonValue],
        operation_label: str,
    ) -> None:
        if not operation_label.startswith("cad:"):
            raise EvidenceManifestMismatch(
                "artifact evidence cannot satisfy a non-CAD provider operation"
            )
        if manifest.get("required_roles") != sorted(_CAD_REQUIRED_ROLES):
            raise EvidenceCorruption("CAD artifact evidence required roles are invalid")
        objects = manifest.get("objects")
        if type(objects) is not list or not objects:
            raise EvidenceCorruption("CAD artifact evidence objects are invalid")
        roles: set[str] = set()
        for reference in objects:
            if type(reference) is not dict:
                raise EvidenceCorruption("CAD artifact evidence object is invalid")
            role = reference.get("role")
            digest = reference.get("digest")
            byte_count = reference.get("bytes")
            media_type = reference.get("media_type")
            if (
                type(role) is not str
                or _ARTIFACT_ROLE.fullmatch(role) is None
                or role in roles
                or type(digest) is not str
                or type(byte_count) is not int
                or byte_count <= 0
                or type(media_type) is not str
                or _MEDIA_TYPE.fullmatch(media_type) is None
                or reference.get("provider") != manifest.get("provider")
                or reference.get("disposition") != "local_cas"
                or self._verify_path(self.object_path(digest), digest) != byte_count
            ):
                raise EvidenceCorruption("CAD artifact evidence object does not match stored bytes")
            roles.add(role)
        if not _CAD_REQUIRED_ROLES.issubset(roles):
            raise EvidenceCorruption("CAD artifact evidence is missing a required object")
        report_reference = next(
            reference
            for reference in objects
            if isinstance(reference, dict) and reference.get("role") == "validation_report"
        )
        try:
            report_bytes = self.object_bytes(str(report_reference["digest"]))
            report = json.loads(report_bytes)
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EvidenceCorruption("CAD validation report is not canonical JSON") from exc
        if (
            type(report) is not dict
            or _canonical_json(report) != report_bytes
            or report.get("schema") != "stockroom.cad-validation/1"
            or report.get("valid") is not True
            or report.get("identity") != manifest.get("identity")
            or report.get("operation") != manifest.get("operation")
            or report.get("provider") != manifest.get("provider")
        ):
            raise EvidenceCorruption(
                "CAD validation report does not prove the manifest identity and operation"
            )
