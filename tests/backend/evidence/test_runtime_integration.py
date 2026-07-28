from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from stockroom.evidence import EvidenceStore
from stockroom.planning import (
    METADATA_OPERATION,
    AdapterOutcome,
    AuthenticationState,
    ExactPartIdentity,
    FailureClassification,
    LicenseDecision,
    ProviderDeclaration,
    ProviderExecutionRuntime,
    ProviderHealth,
    ProviderPlanner,
    ProviderPolicyInput,
    ProviderRegistration,
    ProviderRequest,
    TrustDecision,
)


@dataclass
class _EvidenceAdapter:
    store: EvidenceStore
    claimed_digest: str | None = None
    provider_key: str = "mouser"
    executable_operations: frozenset = frozenset({METADATA_OPERATION})

    def execute(self, identity, operation):
        digest = self.claimed_digest or self.store.record_provider_success(
            identity=identity,
            operation=operation,
            provider_key=self.provider_key,
            adapter_version="1.0.0",
            payload={
                "manufacturer": identity.authoritative_manufacturer_key,
                "mpn": identity.mpn_canonical,
            },
            media_type="application/json",
        )
        return AdapterOutcome.success(identity, evidence_digests=(digest,))


def _run(adapter: _EvidenceAdapter):
    registration = ProviderRegistration(
        ProviderDeclaration(
            key="mouser",
            adapter_version="1.0.0",
            operations=(METADATA_OPERATION,),
            max_concurrency=1,
        ),
        adapter,
    )
    planner = ProviderPlanner((registration,))
    identity = ExactPartIdentity("ON Semiconductor", "S1M")
    policy = (
        ProviderPolicyInput(
            provider_key="mouser",
            operation=METADATA_OPERATION,
            trust=TrustDecision.PRIMARY,
            license=LicenseDecision.ALLOWED,
            authentication=AuthenticationState.AVAILABLE,
            health=ProviderHealth.HEALTHY,
            priority=1,
        ),
    )
    plan = planner.plan((ProviderRequest(identity, (METADATA_OPERATION,)),), policy)
    return ProviderExecutionRuntime(
        planner,
        evidence_verifier=adapter.store,
    ).execute(plan, policy)[0]


def test_runtime_accepts_only_existing_exactly_bound_evidence(tmp_path: Path) -> None:
    receipt = _run(_EvidenceAdapter(EvidenceStore(tmp_path / "Evidence")))
    assert receipt.complete is True
    assert receipt.selections[0].attempts[0].evidence_digests


def test_runtime_turns_forged_evidence_into_sanitized_adapter_fault(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "Evidence")
    receipt = _run(_EvidenceAdapter(store, claimed_digest="sha256:" + ("0" * 64)))

    assert receipt.complete is False
    attempt = receipt.selections[0].attempts[0]
    assert attempt.status is FailureClassification.ADAPTER_FAULT
    assert attempt.evidence_digests == ()
