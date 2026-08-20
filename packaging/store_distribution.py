"""Microsoft Store identity and shipped distribution-marker contracts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

STORE_IDENTITY_PATH = Path(__file__).with_name("StoreIdentity.json")
STORE_IDENTITY_SCHEMA = "stockroom-microsoft-store-identity/1"
STORE_DISTRIBUTION_SCHEMA = "stockroom-distribution/1"
STORE_CHANNEL = "microsoft-store"


class StoreDistributionError(ValueError):
    """A Store identity or package marker is malformed or inconsistent."""


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise StoreDistributionError(f"duplicate Store identity key: {key}")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class StoreIdentity:
    schema: str
    product_name: str
    store_id: str
    package_name: str
    publisher: str
    publisher_display_name: str
    package_family_name: str
    store_uri: str

    @classmethod
    def load(cls, path: Path = STORE_IDENTITY_PATH) -> StoreIdentity:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise StoreDistributionError("Store identity is not valid JSON") from exc
        if not isinstance(raw, dict):
            raise StoreDistributionError("Store identity must be one JSON object")
        expected = set(cls.__dataclass_fields__)
        if set(raw) != expected or not all(isinstance(raw[key], str) for key in expected):
            raise StoreDistributionError("Store identity has the wrong fields")
        identity = cls(**raw)  # type: ignore[arg-type]
        identity.validate()
        return identity

    def validate(self) -> None:
        if self.schema != STORE_IDENTITY_SCHEMA:
            raise StoreDistributionError("Store identity schema is unsupported")
        if self.product_name != "Stockroom":
            raise StoreDistributionError("Store product name changed")
        if self.store_id != "9NQ6HP17PH4H":
            raise StoreDistributionError("Store ID changed")
        if self.package_name != "Sadad.Stockroom":
            raise StoreDistributionError("Store package name changed")
        if self.publisher != "CN=6586C41B-410B-4C94-8631-F025DB362E47":
            raise StoreDistributionError("Store Partner Center publisher changed")
        if self.publisher_display_name != "Sadad":
            raise StoreDistributionError("Store publisher display name changed")
        if self.package_family_name != "Sadad.Stockroom_p16bsq5x1dh0a":
            raise StoreDistributionError("Store package family name changed")
        parsed = urlparse(self.store_uri)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "apps.microsoft.com"
            or parsed.path != f"/detail/{self.store_id}"
            or parsed.query
            or parsed.fragment
        ):
            raise StoreDistributionError("Store URI does not match the Store ID")


@dataclass(frozen=True, slots=True)
class StoreDistributionMarker:
    schema: str
    channel: str
    store_id: str
    package_name: str
    publisher: str
    store_uri: str
    version: str

    @classmethod
    def from_identity(cls, identity: StoreIdentity, *, version: str) -> StoreDistributionMarker:
        return cls(
            schema=STORE_DISTRIBUTION_SCHEMA,
            channel=STORE_CHANNEL,
            store_id=identity.store_id,
            package_name=identity.package_name,
            publisher=identity.publisher,
            store_uri=identity.store_uri,
            version=version,
        )

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        identity: StoreIdentity,
        version: str,
    ) -> StoreDistributionMarker:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise StoreDistributionError("Microsoft Store distribution marker is invalid") from exc
        expected = set(cls.__dataclass_fields__)
        if (
            not isinstance(raw, dict)
            or set(raw) != expected
            or not all(isinstance(raw[key], str) for key in expected)
        ):
            raise StoreDistributionError("Microsoft Store distribution marker has wrong fields")
        marker = cls(**raw)  # type: ignore[arg-type]
        marker.validate(identity=identity, version=version)
        return marker

    def validate(self, *, identity: StoreIdentity, version: str) -> None:
        expected = self.from_identity(identity, version=version)
        if self != expected:
            raise StoreDistributionError("Microsoft Store distribution marker does not match package")

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"
