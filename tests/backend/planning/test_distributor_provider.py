from __future__ import annotations

import json
from pathlib import Path

from stockroom.enrich.errors import EnrichError
from stockroom.enrich.mouser import parse_mouser_payload
from stockroom.evidence import EvidenceStore
from stockroom.planning import (
    METADATA_OPERATION,
    AdapterOutcomeStatus,
    ExactPartIdentity,
    FailureClassification,
)
from stockroom.planning.distributor_provider import (
    DistributorMetadataProviderAdapter,
    build_configured_distributor_metadata_registrations,
    build_configured_distributor_metadata_runtime,
)
from stockroom.store.machine_config import MachineConfig

_FIXTURE = Path(__file__).parents[1] / "enrich" / "fixtures" / "mouser_partnumber.json"
_IDENTITY = ExactPartIdentity("Texas Instruments", "TPS62130RGTR")


def _adapter(tmp_path: Path, fetch):
    return DistributorMetadataProviderAdapter(
        provider_key="mouser",
        adapter_version="1.0.0",
        fetch_payload=fetch,
        parse_payload=parse_mouser_payload,
        evidence_store=EvidenceStore(tmp_path / "Evidence"),
    )


def test_mouser_metadata_adapter_records_real_sanitized_fixture_evidence(
    tmp_path: Path,
) -> None:
    body = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    adapter = _adapter(tmp_path, lambda _mpn: body)

    outcome = adapter.execute(_IDENTITY, METADATA_OPERATION)

    assert outcome.status is AdapterOutcomeStatus.SUCCESS
    assert len(outcome.evidence_digests) == 1
    adapter.evidence_store.verify_provider_success(
        outcome.evidence_digests[0],
        identity=_IDENTITY,
        operation=METADATA_OPERATION,
        provider_key="mouser",
        adapter_version="1.0.0",
    )


def test_distributor_metadata_adapter_fails_closed_on_near_identity(
    tmp_path: Path,
) -> None:
    body = {
        "SearchResults": {
            "Parts": [
                {
                    "Manufacturer": "Different Manufacturer",
                    "ManufacturerPartNumber": "TPS62130RGTR",
                }
            ]
        }
    }
    outcome = _adapter(tmp_path, lambda _mpn: body).execute(_IDENTITY, METADATA_OPERATION)

    assert outcome.status is FailureClassification.NEAR_MATCH_REJECTED
    assert outcome.evidence_digests == ()


def test_distributor_metadata_adapter_classifies_transport_without_leaking_errors(
    tmp_path: Path,
) -> None:
    secret = "do-not-persist"

    def fail(_mpn):
        raise EnrichError(secret, status_code=429)

    adapter = _adapter(tmp_path, fail)
    outcome = adapter.execute(_IDENTITY, METADATA_OPERATION)

    assert outcome.status is FailureClassification.RATE_LIMITED
    assert outcome.retry_after_seconds == 60
    assert secret not in repr(outcome)
    assert list(adapter.evidence_store.root.rglob("*")) == []


def test_distributor_metadata_adapter_rejects_an_unadvertised_operation(
    tmp_path: Path,
) -> None:
    from stockroom.planning import DATASHEET_OPERATION

    outcome = _adapter(tmp_path, lambda _mpn: {}).execute(_IDENTITY, DATASHEET_OPERATION)
    assert outcome.status is FailureClassification.UNSUPPORTED_FORMAT


def test_configured_registrations_use_credential_presence_without_exposing_values(
    tmp_path: Path,
) -> None:
    secret = "never-show-this-secret"
    registrations = build_configured_distributor_metadata_registrations(
        MachineConfig(
            mouser_api_key=secret,
            digikey_client_id="configured-client",
            digikey_client_secret=secret,
        ),
        EvidenceStore(tmp_path / "Evidence"),
    )

    assert [item.declaration.key for item in registrations] == ["mouser", "digikey"]
    assert all(item.declaration.operations == (METADATA_OPERATION,) for item in registrations)
    assert secret not in repr(registrations)


def test_configured_runtime_makes_evidence_verification_mandatory(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "Evidence")
    assert build_configured_distributor_metadata_runtime(MachineConfig(), store) is None

    runtime = build_configured_distributor_metadata_runtime(
        MachineConfig(mouser_api_key="configured-secret"),
        store,
    )
    assert runtime is not None
    assert runtime.concurrency_limits == {"mouser": 1}
