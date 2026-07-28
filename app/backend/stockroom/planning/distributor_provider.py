"""Production-shaped distributor metadata adapters for the provider runtime.

The existing Mouser and DigiKey clients continue to own transport and parsing.
This module adds exact-identity enforcement and immutable evidence installation;
it does not write component records or bypass provider policy.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from stockroom.enrich.errors import EnrichError
from stockroom.enrich.schema import EnrichmentResult
from stockroom.evidence import EvidenceStore

from .provider_policy import (
    METADATA_OPERATION,
    AdapterOutcome,
    ExactPartIdentity,
    FailureClassification,
    ProviderDeclaration,
    ProviderOperation,
    ProviderPlanner,
    ProviderRegistration,
)
from .provider_runtime import ProviderExecutionRuntime

if TYPE_CHECKING:
    from stockroom.store.machine_config import MachineConfig

PayloadFetcher = Callable[[str], dict | None]
PayloadParser = Callable[[dict | None, str], EnrichmentResult]

_RATE_LIMIT_RETRY_SECONDS = 60.0
_MOUSER_ADAPTER_VERSION = "mouser-api-v1"
_DIGIKEY_ADAPTER_VERSION = "digikey-product-v4"


class _LegacyPayloadClient(Protocol):
    last_status: str

    def fetch_payload(self, mpn: str) -> dict | None: ...


def _failure_for_transport(error: EnrichError) -> AdapterOutcome:
    if error.status_code == 429:
        return AdapterOutcome.failure(
            FailureClassification.RATE_LIMITED,
            retry_after_seconds=_RATE_LIMIT_RETRY_SECONDS,
        )
    if error.status_code in {401, 403}:
        return AdapterOutcome.failure(FailureClassification.AUTH_INVALID)
    return AdapterOutcome.failure(FailureClassification.UNAVAILABLE)


@dataclass(slots=True)
class DistributorMetadataProviderAdapter:
    """Turn one distributor JSON response into exact immutable metadata evidence."""

    provider_key: str
    adapter_version: str
    fetch_payload: PayloadFetcher
    parse_payload: PayloadParser
    evidence_store: EvidenceStore
    executable_operations: frozenset[ProviderOperation] = frozenset({METADATA_OPERATION})

    def __post_init__(self) -> None:
        if not self.provider_key or not self.adapter_version:
            raise ValueError("provider key and adapter version are required")
        if not callable(self.fetch_payload) or not callable(self.parse_payload):
            raise TypeError("distributor payload functions must be callable")
        if not isinstance(self.evidence_store, EvidenceStore):
            raise TypeError("evidence_store must be EvidenceStore")

    def execute(
        self,
        identity: ExactPartIdentity,
        operation: ProviderOperation,
    ) -> AdapterOutcome:
        if operation not in self.executable_operations:
            return AdapterOutcome.failure(FailureClassification.UNSUPPORTED_FORMAT)
        try:
            payload = self.fetch_payload(identity.mpn_canonical)
        except EnrichError as error:
            return _failure_for_transport(error)
        if type(payload) is not dict:
            return AdapterOutcome.failure(FailureClassification.NOT_FOUND_EXACT)

        result = self.parse_payload(payload, identity.mpn_canonical)
        returned_manufacturer = None if result.manufacturer is None else result.manufacturer.value
        returned_mpn = None if result.mpn is None else result.mpn.value
        if (
            type(returned_manufacturer) is not str
            or type(returned_mpn) is not str
            or returned_manufacturer != identity.authoritative_manufacturer_key
            or returned_mpn != identity.mpn_canonical
        ):
            return AdapterOutcome.failure(FailureClassification.NEAR_MATCH_REJECTED)

        evidence_digest = self.evidence_store.record_provider_success(
            identity=identity,
            operation=operation,
            provider_key=self.provider_key,
            adapter_version=self.adapter_version,
            payload=payload,
            media_type="application/json",
        )
        return AdapterOutcome.success(identity, evidence_digests=(evidence_digest,))


def _legacy_fetch(client: _LegacyPayloadClient, mpn: str) -> dict | None:
    payload = client.fetch_payload(mpn)
    if payload is not None:
        return payload
    status = getattr(client, "last_status", "")
    if status == "rate_limited":
        raise EnrichError(status_code=429)
    if status == "auth_error":
        raise EnrichError(status_code=401)
    if status == "error":
        raise EnrichError()
    return None


def build_configured_distributor_metadata_registrations(
    config: MachineConfig,
    evidence_store: EvidenceStore,
) -> tuple[ProviderRegistration, ...]:
    """Build credential-backed registrations without exposing credential values."""

    from stockroom.enrich.digikey_api import DigiKeyAdapter, parse_digikey_payload
    from stockroom.enrich.mouser import MouserAdapter, parse_mouser_payload

    registrations: list[ProviderRegistration] = []
    if config.mouser_api_key:
        client = MouserAdapter(config.mouser_api_key)
        adapter = DistributorMetadataProviderAdapter(
            provider_key="mouser",
            adapter_version=_MOUSER_ADAPTER_VERSION,
            fetch_payload=lambda mpn, client=client: _legacy_fetch(client, mpn),
            parse_payload=parse_mouser_payload,
            evidence_store=evidence_store,
        )
        registrations.append(
            ProviderRegistration(
                ProviderDeclaration(
                    key=adapter.provider_key,
                    adapter_version=adapter.adapter_version,
                    operations=(METADATA_OPERATION,),
                    max_concurrency=1,
                ),
                adapter,
            )
        )
    if config.digikey_client_id and config.digikey_client_secret:
        client = DigiKeyAdapter(config.digikey_client_id, config.digikey_client_secret)
        adapter = DistributorMetadataProviderAdapter(
            provider_key="digikey",
            adapter_version=_DIGIKEY_ADAPTER_VERSION,
            fetch_payload=lambda mpn, client=client: _legacy_fetch(client, mpn),
            parse_payload=parse_digikey_payload,
            evidence_store=evidence_store,
        )
        registrations.append(
            ProviderRegistration(
                ProviderDeclaration(
                    key=adapter.provider_key,
                    adapter_version=adapter.adapter_version,
                    operations=(METADATA_OPERATION,),
                    max_concurrency=1,
                ),
                adapter,
            )
        )
    return tuple(registrations)


def build_configured_distributor_metadata_runtime(
    config: MachineConfig,
    evidence_store: EvidenceStore,
) -> ProviderExecutionRuntime | None:
    """Compose configured providers with mandatory immutable evidence verification."""

    registrations = build_configured_distributor_metadata_registrations(config, evidence_store)
    if not registrations:
        return None
    return ProviderExecutionRuntime(
        ProviderPlanner(registrations),
        evidence_verifier=evidence_store,
    )


__all__ = [
    "DistributorMetadataProviderAdapter",
    "build_configured_distributor_metadata_registrations",
    "build_configured_distributor_metadata_runtime",
]
