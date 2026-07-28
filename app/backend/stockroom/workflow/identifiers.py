"""Pure deterministic identity helpers for the isolated workflow kernel."""

from __future__ import annotations

import base64
import hashlib
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DerivedComponentIdentity:
    manufacturer_id: str
    manufacturer_digest: bytes
    component_id: str
    component_digest: bytes


@dataclass(frozen=True, slots=True)
class DerivedPublicationIdentity:
    publication_id: str
    publication_digest: bytes


def authoritative_text(value: str, name: str) -> str:
    """Validate already-authoritative text without silently normalizing it."""

    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value or not value.strip():
        raise ValueError(f"{name} must not be blank")
    if value != value.strip():
        raise ValueError(f"{name} must not contain surrounding whitespace")
    if unicodedata.normalize("NFC", value) != value:
        raise ValueError(f"{name} must be canonical NFC")
    return value


def opaque_text(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value or not value.strip():
        raise ValueError(f"{name} must not be blank")
    return value


def digest_id(prefix: str, digest: bytes) -> str:
    encoded = base64.b32encode(digest).decode("ascii").rstrip("=").lower()
    return f"{prefix}_{encoded}"


def digest_text(digest: bytes) -> str:
    return f"sha256:{digest.hex()}"


def parse_sha256(value: str, name: str) -> bytes:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if len(value) != 71 or not value.startswith("sha256:") or value != value.lower():
        raise ValueError(f"{name} must be a lowercase sha256 digest")
    try:
        digest = bytes.fromhex(value[7:])
    except ValueError as exc:
        raise ValueError(f"{name} must be a lowercase sha256 digest") from exc
    if len(digest) != 32:
        raise ValueError(f"{name} must be a lowercase sha256 digest")
    return digest


def derive_component_identity(
    authoritative_manufacturer_key: str,
    mpn_canonical: str,
) -> DerivedComponentIdentity:
    manufacturer_digest = hashlib.sha256(
        b"stockroom.manufacturer.v1\0" + authoritative_manufacturer_key.encode("utf-8")
    ).digest()
    component_digest = hashlib.sha256(
        b"stockroom.component.v1\0" + manufacturer_digest + b"\0" + mpn_canonical.encode("utf-8")
    ).digest()
    return DerivedComponentIdentity(
        manufacturer_id=digest_id("mfr", manufacturer_digest),
        manufacturer_digest=manufacturer_digest,
        component_id=digest_id("cmp", component_digest),
        component_digest=component_digest,
    )


def derive_publication_identity(
    component_digest: bytes,
    candidate_digest: bytes,
) -> DerivedPublicationIdentity:
    publication_digest = hashlib.sha256(
        b"stockroom.publish.v1\0" + component_digest + b"\0" + candidate_digest
    ).digest()
    return DerivedPublicationIdentity(
        publication_id=digest_id("pub", publication_digest),
        publication_digest=publication_digest,
    )
