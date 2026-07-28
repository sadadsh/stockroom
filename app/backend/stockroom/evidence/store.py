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
from pathlib import Path
from typing import Protocol, TypeAlias
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MEDIA_TYPE = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*\Z")
_PROVIDER_KEY = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_MAX_OBJECT_BYTES = 64 * 1024 * 1024
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

    def verify_provider_success(
        self,
        digest: str,
        *,
        identity: ExactIdentity,
        operation: EvidenceOperation,
        provider_key: str,
        adapter_version: str,
    ) -> dict[str, JsonValue]:
        try:
            manifest = json.loads(self.object_bytes(digest))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EvidenceCorruption("evidence manifest is not canonical JSON") from exc
        if type(manifest) is not dict or _canonical_json(manifest) != self.object_bytes(digest):
            raise EvidenceCorruption("evidence manifest is not canonical JSON")
        expected_identity = {
            "authoritative_manufacturer_key": identity.authoritative_manufacturer_key,
            "mpn_canonical": identity.mpn_canonical,
        }
        if (
            manifest.get("schema") != "stockroom.provider-evidence/1"
            or manifest.get("identity") != expected_identity
            or manifest.get("operation") != operation.label
            or manifest.get("provider") != provider_key
            or manifest.get("adapter_version") != adapter_version
        ):
            raise EvidenceManifestMismatch("evidence manifest does not match the provider attempt")
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
