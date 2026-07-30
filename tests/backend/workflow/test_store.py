import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier, Lock
from time import sleep

import pytest

from stockroom.workflow import (
    BatchStatus,
    DecisionKind,
    DecisionStatus,
    IntakeIdentity,
    ItemStatus,
    StageName,
    StageRecord,
    StageStatus,
    WorkflowConflict,
    WorkflowDataCorruption,
    WorkflowStore,
    default_stage_plan,
)
from stockroom.workflow import store as workflow_store_module


def _store(tmp_path: Path) -> WorkflowStore:
    return WorkflowStore(tmp_path / "workflow.sqlite3")


def _claim_names(
    store: WorkflowStore,
    batch_id: str,
    *,
    worker: str = "worker",
    now: float = 100.0,
) -> list[StageName]:
    return [
        claim.name
        for claim in store.claim_ready(worker, now=now, lease_seconds=30.0, limit=1000)
        if claim.batch_id == batch_id
    ]


def _lease(claim: StageRecord) -> dict[str, str | int]:
    assert claim.lease_token is not None
    assert claim.lease_generation > 0
    return {
        "lease_token": claim.lease_token,
        "lease_generation": claim.lease_generation,
    }


def _resolve_identity(
    store: WorkflowStore,
    claim: StageRecord,
    *,
    worker: str = "worker",
    now: float = 3.0,
):
    item = store.get_item(claim.item_id)
    return store.resolve_exact_identity(
        claim.id,
        worker,
        authoritative_manufacturer_key=(item.manufacturer_key or "Resolved Manufacturer"),
        mpn_canonical=item.mpn_key,
        registry_revision="manufacturer-registry-v1",
        rule_revision="identity-rule-v1",
        evidence={"source": "test"},
        **_lease(claim),
        now=now,
    )


def _complete_claims(
    store: WorkflowStore,
    names: set[StageName],
    *,
    worker: str = "worker",
    now: float = 100.0,
) -> None:
    claims = store.claim_ready(worker, now=now, lease_seconds=30.0, limit=1000)
    selected = [claim for claim in claims if claim.name in names]
    assert {claim.name for claim in selected} == names
    for claim in selected:
        if claim.name is StageName.IDENTITY_DEDUPE:
            _resolve_identity(
                store,
                claim,
                worker=worker,
                now=now + 1.0,
            )
        else:
            store.complete_stage(
                claim.id,
                worker,
                {"stage": claim.name.value},
                **_lease(claim),
                now=now + 1.0,
            )


def _advance_to_publish(store: WorkflowStore, batch_id: str) -> StageRecord:
    timestamp = 10.0
    while True:
        claims = store.claim_ready(
            "worker",
            now=timestamp,
            lease_seconds=30,
            limit=1000,
        )
        assert claims
        assert {claim.batch_id for claim in claims} == {batch_id}
        publish = [claim for claim in claims if claim.name is StageName.PUBLISH]
        if publish:
            assert len(claims) == 1
            return publish[0]
        for claim in claims:
            if claim.name is StageName.IDENTITY_DEDUPE:
                _resolve_identity(
                    store,
                    claim,
                    now=timestamp + 0.5,
                )
            else:
                store.complete_stage(
                    claim.id,
                    "worker",
                    {"stage": claim.name.value},
                    **_lease(claim),
                    now=timestamp + 0.5,
                )
        timestamp += 1


def test_one_and_one_thousand_items_take_the_same_plan(tmp_path):
    store = _store(tmp_path)
    one = store.submit_batch([IntakeIdentity("Texas Instruments", "TPS7A20")], now=1)
    thousand = store.submit_batch(
        [IntakeIdentity("Vendor", f"PART-{index:04}") for index in range(1000)],
        now=2,
    )

    one_items = store.list_items(one.id)
    thousand_items = store.list_items(thousand.id)
    assert len(one_items) == 1
    assert len(thousand_items) == 1000

    expected = [
        StageName.IDENTITY_DEDUPE,
        StageName.METADATA,
        StageName.DATASHEET,
        StageName.EXISTING_EVIDENCE,
        StageName.CAD_ACQUISITION,
        StageName.RECONCILE,
        StageName.CANONICAL_DEFINITION,
        StageName.TEMPLATE_GENERATION,
        StageName.NATIVE_CONVERSION_ACQUISITION,
        StageName.KICAD_BUILD_READBACK,
        StageName.ALTIUM_BUILD_READBACK,
        StageName.CROSS_EDA_VERIFICATION,
        StageName.CATALOG_LINK_GENERATION,
        StageName.PUBLISH,
    ]
    assert [stage.name for stage in store.list_stages(one_items[0].id)] == expected
    assert [stage.name for stage in store.list_stages(thousand_items[0].id)] == expected
    assert [stage.name for stage in store.list_stages(thousand_items[-1].id)] == expected
    assert store.count_stages(thousand.id) == 14_000


def test_batch_cardinality_and_json_are_validated_before_writing(tmp_path):
    store = _store(tmp_path)

    with pytest.raises(ValueError, match="between 1 and 1000"):
        store.submit_batch([])
    with pytest.raises(ValueError, match="between 1 and 1000"):
        store.submit_batch([IntakeIdentity("", str(index)) for index in range(1001)])
    with pytest.raises(TypeError, match="JSON"):
        store.submit_batch([IntakeIdentity("", "MPN", payload={"bad": {1, 2}})])

    assert store.count_batches() == 0


def test_submission_idempotency_is_concurrent_and_request_exact(tmp_path):
    store = _store(tmp_path)
    identities = [
        IntakeIdentity("ACME™", "P-1", payload={"source": ["bom", 7]}),
        IntakeIdentity("Vendor & Co.", "P-(2)"),
    ]
    start = Barrier(8)

    def submit(_: int):
        start.wait()
        return store.submit_batch(
            identities,
            idempotency_key="import-run-42",
            now=10,
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        batches = list(pool.map(submit, range(8)))

    assert len({batch.id for batch in batches}) == 1
    batch = batches[0]
    assert batch.idempotency_key == "import-run-42"
    assert batch.request_digest is not None
    assert len(batch.request_digest) == 64
    assert store.count_batches() == 1
    assert len(store.list_items(batch.id)) == 2
    assert len(store.events(batch.id)) == 5

    same = store.submit_batch(
        identities,
        idempotency_key="import-run-42",
        now=999,
    )
    assert same == batch
    assert len(store.events(batch.id)) == 5

    with pytest.raises(WorkflowConflict, match="different request"):
        store.submit_batch(
            [IntakeIdentity("ACME™", "P-CHANGED")],
            idempotency_key="import-run-42",
            now=1000,
        )
    assert store.count_batches() == 1
    assert len(store.list_items(batch.id)) == 2


def test_one_store_serializes_local_writers_before_sqlite_busy_wait(tmp_path):
    class ObservedWorkflowStore(WorkflowStore):
        def __init__(self, database: Path):
            self.observation_lock = Lock()
            self.active_writers = 0
            self.max_active_writers = 0
            super().__init__(database)

        @contextmanager
        def _writing(self):
            with self.observation_lock:
                self.active_writers += 1
                self.max_active_writers = max(
                    self.max_active_writers,
                    self.active_writers,
                )
            try:
                sleep(0.01)
                with super()._writing() as connection:
                    yield connection
            finally:
                with self.observation_lock:
                    self.active_writers -= 1

    store = ObservedWorkflowStore(tmp_path / "serialized-writers.sqlite3")
    start = Barrier(8)

    def recover(_: int) -> int:
        start.wait()
        return store.recover_expired_leases(now=10)

    with ThreadPoolExecutor(max_workers=8) as pool:
        recovered = list(pool.map(recover, range(8)))

    assert recovered == [0] * 8
    assert store.max_active_writers == 1


def test_exact_identity_fields_and_punctuation_collisions_survive_round_trip(tmp_path):
    store = _store(tmp_path)
    batch = store.submit_batch(
        [
            IntakeIdentity("  ACME & Sons  ", " ABC&_123 "),
            IntakeIdentity("ACME & Sons", "ABC(%123"),
            IntakeIdentity("ACME", "PART-1"),
            IntakeIdentity("acme", "part-1"),
        ],
        now=1,
    )

    first, second, uppercase, lowercase = store.list_items(batch.id)
    assert first.id != second.id
    assert first.entry_id != second.entry_id
    assert first.manufacturer == "  ACME & Sons  "
    assert first.mpn == " ABC&_123 "
    assert first.mpn_key == "ABC&_123"
    assert second.mpn == "ABC(%123"
    assert second.mpn_key == "ABC(%123"
    assert first.mpn_key != second.mpn_key
    assert uppercase.manufacturer_key == "ACME"
    assert lowercase.manufacturer_key == "acme"
    assert uppercase.manufacturer_key != lowercase.manufacturer_key
    assert uppercase.mpn_key == "PART-1"
    assert lowercase.mpn_key == "part-1"
    assert uppercase.mpn_key != lowercase.mpn_key


def test_dependencies_fan_out_and_join_without_repeating_completed_stages(tmp_path):
    store = _store(tmp_path)
    batch = store.submit_batch([IntakeIdentity("ACME", "P-1")], now=1)

    first = store.claim_ready("worker", now=2, lease_seconds=30, limit=10)
    assert [claim.name for claim in first] == [StageName.IDENTITY_DEDUPE]
    first_binding = _resolve_identity(store, first[0], now=3)
    assert _resolve_identity(store, first[0], now=4) == first_binding
    with pytest.raises(WorkflowDataCorruption, match="conflicts"):
        store.resolve_exact_identity(
            first[0].id,
            "worker",
            authoritative_manufacturer_key="Different Manufacturer",
            mpn_canonical="P-1",
            registry_revision="manufacturer-registry-v1",
            rule_revision="identity-rule-v1",
            evidence={"source": "test"},
            **_lease(first[0]),
            now=4,
        )

    fanout = store.claim_ready("worker", now=5, lease_seconds=30, limit=10)
    assert [claim.name for claim in fanout] == [
        StageName.METADATA,
        StageName.DATASHEET,
        StageName.EXISTING_EVIDENCE,
        StageName.CAD_ACQUISITION,
    ]

    by_name = {claim.name: claim for claim in fanout}
    metadata = by_name[StageName.METADATA]
    store.complete_stage(
        metadata.id,
        "worker",
        {},
        **_lease(metadata),
        now=6,
    )
    assert store.claim_ready("other", now=6, lease_seconds=30, limit=10) == []

    datasheet = by_name[StageName.DATASHEET]
    evidence = by_name[StageName.EXISTING_EVIDENCE]
    cad = by_name[StageName.CAD_ACQUISITION]
    store.complete_stage(
        datasheet.id,
        "worker",
        {},
        **_lease(datasheet),
        now=7,
    )
    assert store.claim_ready("other", now=7, lease_seconds=30, limit=10) == []
    store.complete_stage(
        evidence.id,
        "worker",
        {},
        **_lease(evidence),
        now=8,
    )
    reconcile = store.claim_ready("other", now=8, lease_seconds=30, limit=10)
    assert [claim.name for claim in reconcile] == [StageName.RECONCILE]

    store.complete_stage(cad.id, "worker", {}, **_lease(cad), now=8)
    assert store.claim_ready("third", now=8, lease_seconds=30, limit=10) == []
    store.complete_stage(
        reconcile[0].id,
        "other",
        {},
        **_lease(reconcile[0]),
        now=9,
    )
    definition = store.claim_ready("third", now=9, lease_seconds=30, limit=10)
    assert [claim.name for claim in definition] == [StageName.CANONICAL_DEFINITION]
    store.complete_stage(
        definition[0].id,
        "third",
        {},
        **_lease(definition[0]),
        now=10,
    )

    representation = store.claim_ready(
        "fourth",
        now=10,
        lease_seconds=30,
        limit=10,
    )
    assert [claim.name for claim in representation] == [
        StageName.TEMPLATE_GENERATION,
        StageName.NATIVE_CONVERSION_ACQUISITION,
    ]
    store.complete_stage(
        representation[0].id,
        "fourth",
        {},
        **_lease(representation[0]),
        now=11,
    )
    assert store.claim_ready("fifth", now=11, lease_seconds=30, limit=10) == []
    store.complete_stage(
        representation[1].id,
        "fourth",
        {},
        **_lease(representation[1]),
        now=12,
    )

    builds = store.claim_ready("fifth", now=12, lease_seconds=30, limit=10)
    assert [claim.name for claim in builds] == [
        StageName.KICAD_BUILD_READBACK,
        StageName.ALTIUM_BUILD_READBACK,
    ]
    store.complete_stage(
        builds[0].id,
        "fifth",
        {},
        **_lease(builds[0]),
        now=13,
    )
    assert store.claim_ready("sixth", now=13, lease_seconds=30, limit=10) == []
    store.complete_stage(
        builds[1].id,
        "fifth",
        {},
        **_lease(builds[1]),
        now=14,
    )

    cross = store.claim_ready("sixth", now=14, lease_seconds=30, limit=10)
    assert [claim.name for claim in cross] == [StageName.CROSS_EDA_VERIFICATION]
    store.complete_stage(
        cross[0].id,
        "sixth",
        {},
        **_lease(cross[0]),
        now=15,
    )
    catalog = store.claim_ready("seventh", now=15, lease_seconds=30, limit=10)
    assert [claim.name for claim in catalog] == [StageName.CATALOG_LINK_GENERATION]
    store.complete_stage(
        catalog[0].id,
        "seventh",
        {},
        **_lease(catalog[0]),
        now=16,
    )
    publish = store.claim_ready("publisher", now=16, lease_seconds=30, limit=10)
    assert [claim.name for claim in publish] == [StageName.PUBLISH]
    assert StageName.IDENTITY_DEDUPE not in [claim.name for claim in publish]
    assert batch.id == publish[0].batch_id


def test_concurrent_store_access_never_claims_the_same_work_twice(tmp_path):
    store = _store(tmp_path)
    store.submit_batch(
        [IntakeIdentity("Vendor", f"P-{index}") for index in range(50)],
        now=1,
    )
    start = Barrier(5)

    def claim(worker: int) -> list[str]:
        start.wait()
        return [
            item.id
            for item in store.claim_ready(
                f"worker-{worker}",
                now=2,
                lease_seconds=30,
                limit=20,
            )
        ]

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(claim, range(5)))

    claimed = [stage_id for result in results for stage_id in result]
    assert len(claimed) == 50
    assert len(set(claimed)) == 50


def test_crash_reopen_replays_monotonic_events_and_recovers_expired_lease(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    first_store = WorkflowStore(database)
    batch = first_store.submit_batch([IntakeIdentity("ACME", "P-1")], now=1)
    claim = first_store.claim_ready("crashed-worker", now=2, lease_seconds=5, limit=1)[0]

    reopened = WorkflowStore(database)
    before = reopened.events(batch.id)
    assert [event.sequence for event in before] == sorted(event.sequence for event in before)
    assert len({event.sequence for event in before}) == len(before)

    assert reopened.recover_expired_leases(now=6.9) == 0
    assert reopened.recover_expired_leases(now=7) == 1
    retry = reopened.claim_ready("replacement", now=7, lease_seconds=5, limit=1)
    assert [item.id for item in retry] == [claim.id]
    assert retry[0].attempt_count == 2

    after = reopened.events(batch.id, after_sequence=before[-1].sequence)
    assert after
    assert after[0].sequence > before[-1].sequence
    assert {"stage_lease_expired", "stage_claimed"} <= {event.kind for event in after}


@pytest.mark.parametrize(
    "transition",
    ["renew", "complete", "retry", "fail", "block"],
)
def test_stale_same_worker_attempt_cannot_cross_a_new_lease_fence(
    tmp_path,
    transition,
):
    store = _store(tmp_path)
    store.submit_batch([IntakeIdentity("ACME", "P-1")], now=1)
    stale = store.claim_ready("same-worker", now=2, lease_seconds=5, limit=1)[0]
    assert stale.lease_token is not None
    assert store.recover_expired_leases(now=7) == 1

    current = store.claim_ready(
        "same-worker",
        now=7,
        lease_seconds=30,
        limit=1,
    )[0]
    assert current.id == stale.id
    assert current.lease_token is not None
    assert current.lease_token != stale.lease_token
    assert current.lease_generation == stale.lease_generation + 1

    with pytest.raises(WorkflowConflict, match="stale"):
        if transition == "renew":
            store.renew_lease(
                stale.id,
                "same-worker",
                **_lease(stale),
                now=8,
                lease_seconds=30,
            )
        elif transition == "complete":
            store.resolve_exact_identity(
                stale.id,
                "same-worker",
                authoritative_manufacturer_key="ACME",
                mpn_canonical="P-1",
                registry_revision="registry-v1",
                rule_revision="rules-v1",
                evidence={},
                **_lease(stale),
                now=8,
            )
        elif transition == "retry":
            store.retry_stage(
                stale.id,
                "same-worker",
                {},
                **_lease(stale),
                retry_at=20,
                now=8,
            )
        elif transition == "fail":
            store.fail_stage(
                stale.id,
                "same-worker",
                {},
                **_lease(stale),
                now=8,
            )
        else:
            store.block_for_decision(
                stale.id,
                "same-worker",
                DecisionKind.SAFETY,
                {},
                **_lease(stale),
                now=8,
            )

    unchanged = store.get_stage(current.id)
    assert unchanged.status is StageStatus.RUNNING
    assert unchanged.lease_token == current.lease_token
    assert unchanged.lease_generation == current.lease_generation


def test_lease_renewal_is_owned_persisted_and_cannot_revive_expired_work(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    store = WorkflowStore(database)
    store.submit_batch([IntakeIdentity("ACME", "P-1")], now=1)
    claim = store.claim_ready("worker", now=2, lease_seconds=5, limit=1)[0]
    assert claim.lease_expires_at == 7

    with pytest.raises(WorkflowConflict, match="another worker"):
        store.renew_lease(
            claim.id,
            "intruder",
            **_lease(claim),
            now=6,
            lease_seconds=10,
        )

    renewed = store.renew_lease(
        claim.id,
        "worker",
        **_lease(claim),
        now=6,
        lease_seconds=10,
    )
    assert renewed.lease_expires_at == 16
    assert renewed.attempt_count == 1
    assert renewed.lease_token == claim.lease_token
    assert renewed.lease_generation == claim.lease_generation
    assert WorkflowStore(database).get_stage(claim.id).lease_expires_at == 16

    with pytest.raises(WorkflowConflict, match="expired"):
        store.renew_lease(
            claim.id,
            "worker",
            **_lease(renewed),
            now=16,
            lease_seconds=10,
        )
    assert store.recover_expired_leases(now=16) == 1


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_external_times_and_lease_values_are_rejected(tmp_path, invalid):
    store = _store(tmp_path)
    identity = IntakeIdentity("ACME", "P-1")

    with pytest.raises(ValueError, match="finite"):
        store.submit_batch([identity], now=invalid)

    batch = store.submit_batch([identity], now=1)
    with pytest.raises(ValueError, match="finite"):
        store.claim_ready("worker", now=invalid, lease_seconds=10, limit=1)
    with pytest.raises(ValueError, match="finite"):
        store.claim_ready("worker", now=2, lease_seconds=invalid, limit=1)
    with pytest.raises(ValueError, match="finite"):
        store.recover_expired_leases(now=invalid)

    claim = store.claim_ready("worker", now=2, lease_seconds=10, limit=1)[0]
    with pytest.raises(ValueError, match="finite"):
        store.retry_stage(
            claim.id,
            "worker",
            {"timeout": True},
            **_lease(claim),
            retry_at=invalid,
            now=3,
        )
    assert store.get_batch(batch.id).status is BatchStatus.RUNNING


def test_retry_time_and_attempts_persist_without_creating_a_decision(tmp_path):
    store = _store(tmp_path)
    batch = store.submit_batch([IntakeIdentity("ACME", "P-1")], now=1)
    claim = store.claim_ready("worker", now=2, lease_seconds=30, limit=1)[0]

    store.retry_stage(
        claim.id,
        "worker",
        {"provider": "temporary miss"},
        **_lease(claim),
        retry_at=20,
        now=3,
    )
    assert store.claim_ready("other", now=19.99, lease_seconds=30, limit=1) == []
    retried = store.claim_ready("other", now=20, lease_seconds=30, limit=1)
    assert len(retried) == 1
    assert retried[0].id == claim.id
    assert retried[0].attempt_count == 2
    assert store.list_decisions(batch.id) == []


def test_identity_decision_blocks_once_then_resolution_requeues_the_stage(tmp_path):
    store = _store(tmp_path)
    store.submit_batch([IntakeIdentity("", "P-1")], now=1)
    claim = store.claim_ready("worker", now=2, lease_seconds=30, limit=1)[0]

    decision = store.block_for_decision(
        claim.id,
        "worker",
        DecisionKind.IDENTITY,
        {"question": "Which manufacturer is exact?"},
        **_lease(claim),
        now=3,
    )
    assert decision.status is DecisionStatus.OPEN
    assert store.get_item(claim.item_id).status is ItemStatus.BLOCKED
    assert store.claim_ready("other", now=4, lease_seconds=30, limit=1) == []

    resolved = store.resolve_decision(
        decision.id,
        {"manufacturer": "ACME"},
        now=5,
    )
    assert resolved.status is DecisionStatus.RESOLVED
    resumed = store.claim_ready("other", now=5, lease_seconds=30, limit=1)
    assert len(resumed) == 1
    assert resumed[0].id == claim.id
    assert resumed[0].attempt_count == 2


def test_blocked_branch_does_not_stall_running_retry_or_ready_branches(tmp_path):
    store = _store(tmp_path)
    batch = store.submit_batch([IntakeIdentity("ACME", "P-1")], now=1)
    identity = store.claim_ready("worker", now=2, lease_seconds=30, limit=1)[0]
    _resolve_identity(store, identity, now=3)

    metadata = store.claim_ready("worker", now=4, lease_seconds=30, limit=1)[0]
    assert metadata.name is StageName.METADATA
    store.block_for_decision(
        metadata.id,
        "worker",
        DecisionKind.SAFETY,
        {"question": "Is this claim safe?"},
        **_lease(metadata),
        now=5,
    )
    assert store.get_item(metadata.item_id).status is ItemStatus.QUEUED
    assert store.get_batch(batch.id).status is BatchStatus.QUEUED

    fanout = store.claim_ready("worker", now=5, lease_seconds=30, limit=3)
    by_name = {claim.name: claim for claim in fanout}
    assert set(by_name) == {
        StageName.DATASHEET,
        StageName.EXISTING_EVIDENCE,
        StageName.CAD_ACQUISITION,
    }
    assert store.get_item(metadata.item_id).status is ItemStatus.RUNNING
    assert store.get_batch(batch.id).status is BatchStatus.RUNNING

    cad = by_name[StageName.CAD_ACQUISITION]
    store.retry_stage(
        cad.id,
        "worker",
        {"provider": "temporarily unavailable"},
        **_lease(cad),
        retry_at=20,
        now=6,
    )
    for stage_name, timestamp in (
        (StageName.DATASHEET, 7),
        (StageName.EXISTING_EVIDENCE, 8),
    ):
        claim = by_name[stage_name]
        store.complete_stage(
            claim.id,
            "worker",
            {},
            **_lease(claim),
            now=timestamp,
        )

    assert store.get_item(metadata.item_id).status is ItemStatus.QUEUED
    assert store.get_batch(batch.id).status is BatchStatus.QUEUED
    assert store.claim_ready("other", now=19, lease_seconds=30, limit=10) == []

    due = store.claim_ready("other", now=20, lease_seconds=30, limit=10)
    assert [claim.id for claim in due] == [cad.id]
    store.complete_stage(
        due[0].id,
        "other",
        {},
        **_lease(due[0]),
        now=21,
    )
    assert store.get_item(metadata.item_id).status is ItemStatus.BLOCKED
    assert store.get_batch(batch.id).status is BatchStatus.BLOCKED


def test_claim_fairness_serves_a_new_batch_before_an_old_batch_backlog(tmp_path):
    store = _store(tmp_path)
    old = store.submit_batch(
        [IntakeIdentity("Vendor", f"PART-{index:04}") for index in range(1000)],
        now=1,
    )
    served = store.claim_ready("worker", now=2, lease_seconds=30, limit=1)[0]
    assert served.batch_id == old.id
    _resolve_identity(store, served, now=3)

    fresh = store.submit_batch([IntakeIdentity("ACME", "ONE")], now=4)
    next_claim = store.claim_ready("worker", now=5, lease_seconds=30, limit=1)
    assert len(next_claim) == 1
    assert next_claim[0].batch_id == fresh.id


def test_pause_resume_and_cancel_are_persisted_and_claim_aware(tmp_path):
    store = _store(tmp_path)
    batch = store.submit_batch(
        [IntakeIdentity("ACME", "P-1"), IntakeIdentity("ACME", "P-2")],
        now=1,
    )

    store.pause_batch(batch.id, now=2)
    assert store.get_batch(batch.id).status is BatchStatus.PAUSED
    assert store.claim_ready("worker", now=3, lease_seconds=30, limit=10) == []

    store.resume_batch(batch.id, now=4)
    claims = store.claim_ready("worker", now=4, lease_seconds=30, limit=1)
    assert len(claims) == 1

    store.cancel_batch(batch.id, now=5)
    assert store.get_batch(batch.id).status is BatchStatus.CANCELLED
    assert store.claim_ready("other", now=6, lease_seconds=30, limit=10) == []
    assert all(
        stage.status in {StageStatus.CANCELLED, StageStatus.COMPLETED}
        for item in store.list_items(batch.id)
        for stage in store.list_stages(item.id)
    )
    with pytest.raises(WorkflowConflict, match="cancelled"):
        store.resolve_exact_identity(
            claims[0].id,
            "worker",
            authoritative_manufacturer_key="ACME",
            mpn_canonical="P-1",
            registry_revision="registry-v1",
            rule_revision="rules-v1",
            evidence={},
            **_lease(claims[0]),
            now=6,
        )


def test_batch_retry_requeues_only_failures_and_is_idempotent(tmp_path):
    store = _store(tmp_path)
    batch = store.submit_batch([IntakeIdentity("ACME", "P-1")], now=1)
    identity = store.claim_ready("worker", now=2, lease_seconds=30, limit=1)[0]
    _resolve_identity(store, identity, now=3)
    completed_identity = store.get_stage(identity.id)
    failed = store.claim_ready("provider-worker", now=4, lease_seconds=30, limit=1)[0]
    store.fail_stage(
        failed.id,
        "provider-worker",
        {"kind": "provider_failure", "secret": "must-stay-durable"},
        **_lease(failed),
        now=5,
    )
    assert store.get_batch(batch.id).status is BatchStatus.FAILED

    terminal_events_before = [
        event for event in store.events(batch.id) if event.kind == "stage_completed"
    ]
    retried = store.retry_batch(batch.id, now=6)
    assert retried.status is BatchStatus.QUEUED
    assert store.get_stage(identity.id) == completed_identity
    assert store.get_stage(failed.id).status is StageStatus.READY
    assert store.get_stage(failed.id).attempt_count == 1

    events_after_first_retry = store.events(batch.id)
    repeated = store.retry_batch(batch.id, now=7)
    assert repeated == retried
    assert store.events(batch.id) == events_after_first_retry
    assert sum(event.kind == "batch_retry_requested" for event in events_after_first_retry) == 1
    assert [
        event for event in events_after_first_retry if event.kind == "stage_completed"
    ] == terminal_events_before


def test_generic_completion_rejects_publish_and_legacy_receipts_stay_empty(tmp_path):
    store = _store(tmp_path)
    batch = store.submit_batch([IntakeIdentity("ACME", "P-1")], now=1)
    publish = _advance_to_publish(store, batch.id)
    item_id = publish.item_id

    with pytest.raises(ValueError, match="component publication methods"):
        store.complete_stage(
            publish.id,
            "worker",
            {"ok": True},
            **_lease(publish),
            now=17,
        )
    assert store.get_stage(publish.id).status is StageStatus.RUNNING
    assert store.get_publication_receipt(item_id) is None
    assert store.list_publication_receipts(batch.id) == []

    with pytest.raises(KeyError):
        store.get_publication_receipt(batch.id)


def test_seeded_pickle_payload_is_quarantined_as_corrupt_json(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    store = WorkflowStore(database)
    batch = store.submit_batch([IntakeIdentity("ACME", "P-1")], now=1)
    item = store.list_items(batch.id)[0]

    seeded_pickle = sqlite3.Binary(b"\x80\x04cos\nsystem\n\x94.")
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute(
            "UPDATE items SET payload_json = ? WHERE id = ?",
            (seeded_pickle, item.id),
        )
        connection.commit()

    with pytest.raises(WorkflowDataCorruption, match="invalid JSON"):
        store.get_item(item.id)


def test_sqlite_durability_settings_migration_and_json_storage(tmp_path):
    store = _store(tmp_path)
    settings = store.database_settings()
    assert settings == {
        "busy_timeout": 5000,
        "foreign_keys": 1,
        "journal_mode": "wal",
        "synchronous": 2,
    }

    database = tmp_path / "workflow.sqlite3"
    with sqlite3.connect(database) as connection:
        migrations = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        payload_columns = connection.execute(
            "SELECT payload_json FROM events ORDER BY sequence"
        ).fetchall()
    assert migrations == [(1,), (2,), (3,), (4,), (5,)]
    assert all(json.loads(row[0]) is not None for row in payload_columns)


def test_stage_lease_expiry_probe_uses_its_exact_migration_index(tmp_path):
    store = WorkflowStore(tmp_path / "workflow.sqlite3")

    with sqlite3.connect(store.database) as connection:
        plan = connection.execute(
            """
            EXPLAIN QUERY PLAN
            SELECT s.id
            FROM stages AS s
            JOIN items AS i ON i.id = s.item_id
            WHERE s.status = 'running'
              AND s.lease_expires_at <= 10
            ORDER BY s.id
            """
        ).fetchall()

    assert any("idx_stages_lease_expiry" in str(row[3]) for row in plan)


def test_v2_migration_requeues_running_stage_before_adding_lease_fence(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY CHECK (version > 0),
                applied_at REAL NOT NULL
            )
            """
        )
        for statement in (
            *workflow_store_module._MIGRATION_1,
            *workflow_store_module._MIGRATION_2,
        ):
            connection.execute(statement)
        connection.executemany(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            [(1, 1.0), (2, 2.0)],
        )
        connection.execute(
            """
            INSERT INTO batches(
                id, status, created_at, updated_at,
                idempotency_key, request_digest
            ) VALUES ('batch', 'running', 1, 2, NULL, NULL)
            """
        )
        connection.execute(
            """
            INSERT INTO items(
                id, entry_id, batch_id, ordinal,
                manufacturer, mpn, manufacturer_key, mpn_key,
                payload_json, status, created_at, updated_at
            ) VALUES (
                'item', 'entry', 'batch', 0,
                'ACME', 'P-1', 'acme', 'p-1',
                '{}', 'running', 1, 2
            )
            """
        )
        stage_ids: dict[StageName, str] = {}
        for spec in default_stage_plan():
            stage_id = f"stage-{spec.ordinal}"
            stage_ids[spec.name] = stage_id
            connection.execute(
                """
                INSERT INTO stages(
                    id, item_id, ordinal, name, status, attempt_count,
                    lease_owner, lease_expires_at, created_at, updated_at
                ) VALUES (?, 'item', ?, ?, ?, ?, ?, ?, 1, 2)
                """,
                (
                    stage_id,
                    spec.ordinal,
                    spec.name.value,
                    (
                        StageStatus.RUNNING.value
                        if spec.name is StageName.IDENTITY_DEDUPE
                        else StageStatus.PENDING.value
                    ),
                    1 if spec.name is StageName.IDENTITY_DEDUPE else 0,
                    "old-worker" if spec.name is StageName.IDENTITY_DEDUPE else None,
                    999 if spec.name is StageName.IDENTITY_DEDUPE else None,
                ),
            )
        for spec in default_stage_plan():
            for dependency in spec.dependencies:
                connection.execute(
                    """
                    INSERT INTO stage_dependencies(stage_id, depends_on_stage_id)
                    VALUES (?, ?)
                    """,
                    (stage_ids[spec.name], stage_ids[dependency]),
                )
        connection.commit()

    store = WorkflowStore(database)
    migrated = store.get_stage("stage-0")
    assert migrated.status is StageStatus.READY
    assert migrated.lease_owner is None
    assert migrated.lease_expires_at is None
    assert migrated.lease_token is None
    assert migrated.lease_generation == 1

    claimed = store.claim_ready("new-worker", now=3, lease_seconds=30, limit=1)[0]
    assert claimed.id == migrated.id
    assert claimed.lease_token is not None
    assert claimed.lease_generation == 2


def test_malformed_v2_graph_is_refused_before_v3_mutates_lease_bytes(tmp_path):
    database = tmp_path / "malformed-v2.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY CHECK (version > 0),
                applied_at REAL NOT NULL
            )
            """
        )
        for statement in (
            *workflow_store_module._MIGRATION_1,
            *workflow_store_module._MIGRATION_2,
        ):
            connection.execute(statement)
        connection.executemany(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            [(1, 1.0), (2, 2.0)],
        )
        connection.execute(
            """
            INSERT INTO batches(
                id, status, created_at, updated_at,
                idempotency_key, request_digest
            ) VALUES ('batch', 'running', 1, 2, NULL, NULL)
            """
        )
        connection.execute(
            """
            INSERT INTO items(
                id, entry_id, batch_id, ordinal,
                manufacturer, mpn, manufacturer_key, mpn_key,
                payload_json, status, created_at, updated_at
            ) VALUES (
                'item', 'entry', 'batch', 0,
                'ACME', 'P-1', 'ACME', 'P-1',
                '{}', 'running', 1, 2
            )
            """
        )
        connection.execute(
            """
            INSERT INTO stages(
                id, item_id, ordinal, name, status, attempt_count,
                lease_owner, lease_expires_at, created_at, updated_at
            ) VALUES (
                'stage', 'item', 0, 'identity_dedupe', 'running', 7,
                'old-worker', 999, 1, 2
            )
            """
        )
        original_stage = connection.execute(
            """
            SELECT status, attempt_count, lease_owner, lease_expires_at
            FROM stages WHERE id = 'stage'
            """
        ).fetchone()
        connection.commit()

    with pytest.raises(WorkflowDataCorruption, match="unsupported stage graph"):
        WorkflowStore(database)

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall() == [(1,), (2,)]
        stage_columns = {row[1] for row in connection.execute("PRAGMA table_info(stages)")}
        assert "lease_token" not in stage_columns
        assert "lease_generation" not in stage_columns
        assert (
            connection.execute(
                """
                SELECT status, attempt_count, lease_owner, lease_expires_at
                FROM stages WHERE id = 'stage'
                """
            ).fetchone()
            == original_stage
        )


@pytest.mark.parametrize(
    "corruption",
    [
        "missing",
        "extra",
        "unknown",
        "reordered",
        "rewired",
        "cross-item",
        "zero-stage",
        "graph-version",
    ],
)
def test_every_open_refuses_noncanonical_persisted_graph(tmp_path, corruption):
    database = tmp_path / f"{corruption}.sqlite3"
    store = WorkflowStore(database)
    batch = store.submit_batch(
        [IntakeIdentity("ACME", "P-1"), IntakeIdentity("ACME", "P-2")],
        now=1,
    )
    first, second = store.list_items(batch.id)

    with sqlite3.connect(database) as connection:
        stage_rows = connection.execute(
            """
            SELECT id, ordinal, name FROM stages
            WHERE item_id = ? ORDER BY ordinal
            """,
            (first.id,),
        ).fetchall()
        stage_ids = {row[2]: row[0] for row in stage_rows}
        second_identity = connection.execute(
            """
            SELECT id FROM stages
            WHERE item_id = ? AND name = 'identity_dedupe'
            """,
            (second.id,),
        ).fetchone()[0]

        if corruption == "missing":
            connection.execute(
                "DELETE FROM stages WHERE id = ?",
                (stage_ids[StageName.PUBLISH.value],),
            )
        elif corruption == "extra":
            connection.execute(
                """
                INSERT INTO stages(
                    id, item_id, ordinal, name, status, attempt_count,
                    created_at, updated_at
                ) VALUES ('extra', ?, 14, 'extra_stage', 'pending', 0, 1, 1)
                """,
                (first.id,),
            )
        elif corruption == "unknown":
            connection.execute(
                "UPDATE stages SET name = 'unknown_stage' WHERE id = ?",
                (stage_ids[StageName.IDENTITY_DEDUPE.value],),
            )
        elif corruption == "reordered":
            identity_id = stage_ids[StageName.IDENTITY_DEDUPE.value]
            metadata_id = stage_ids[StageName.METADATA.value]
            connection.execute(
                "UPDATE stages SET ordinal = 99 WHERE id = ?",
                (identity_id,),
            )
            connection.execute(
                "UPDATE stages SET ordinal = 0 WHERE id = ?",
                (metadata_id,),
            )
            connection.execute(
                "UPDATE stages SET ordinal = 1 WHERE id = ?",
                (identity_id,),
            )
        elif corruption in {"rewired", "cross-item"}:
            metadata_id = stage_ids[StageName.METADATA.value]
            identity_id = stage_ids[StageName.IDENTITY_DEDUPE.value]
            connection.execute(
                """
                DELETE FROM stage_dependencies
                WHERE stage_id = ? AND depends_on_stage_id = ?
                """,
                (metadata_id, identity_id),
            )
            replacement = (
                second_identity
                if corruption == "cross-item"
                else stage_ids[StageName.DATASHEET.value]
            )
            connection.execute(
                """
                INSERT INTO stage_dependencies(stage_id, depends_on_stage_id)
                VALUES (?, ?)
                """,
                (metadata_id, replacement),
            )
        elif corruption == "zero-stage":
            connection.execute("DELETE FROM stages WHERE item_id = ?", (first.id,))
        else:
            connection.execute("PRAGMA ignore_check_constraints=ON")
            connection.execute(
                "UPDATE items SET workflow_graph_version = 999 WHERE id = ?",
                (first.id,),
            )
        connection.commit()

    with pytest.raises(
        WorkflowDataCorruption,
        match="graph|stage dependencies|cross-item stage dependency",
    ):
        WorkflowStore(database)


def test_persisted_dependency_verification_is_bounded_by_item(tmp_path):
    database = tmp_path / "bounded-graph-verification.sqlite3"
    store = WorkflowStore(database)
    batch = store.submit_batch(
        [IntakeIdentity("ACME", f"P-{index}") for index in range(100)],
        now=1,
    )
    item_id = store.list_items(batch.id)[50].id

    with sqlite3.connect(database) as connection:
        plan = connection.execute(
            "EXPLAIN QUERY PLAN " + workflow_store_module._PERSISTED_DEPENDENCY_SELECT,
            (item_id,),
        ).fetchall()

    details = [str(row[3]) for row in plan]
    assert any("SEARCH child" in detail and "item_id=?" in detail for detail in details)
    assert any("SEARCH dependency" in detail and "stage_id=?" in detail for detail in details)
    assert not any("SCAN dependency" in detail for detail in details)


def test_schema_ledger_gaps_and_missing_required_objects_are_rejected(tmp_path):
    gap_database = tmp_path / "gap.sqlite3"
    WorkflowStore(gap_database)
    with sqlite3.connect(gap_database) as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 2")
        connection.commit()
    with pytest.raises(WorkflowDataCorruption, match="not contiguous"):
        WorkflowStore(gap_database)

    index_database = tmp_path / "missing-index.sqlite3"
    WorkflowStore(index_database)
    with sqlite3.connect(index_database) as connection:
        connection.execute("DROP INDEX idx_events_batch_sequence")
        connection.commit()
    with pytest.raises(WorkflowDataCorruption, match="required index"):
        WorkflowStore(index_database)

    table_database = tmp_path / "missing-table.sqlite3"
    WorkflowStore(table_database)
    with sqlite3.connect(table_database) as connection:
        connection.execute("DROP TABLE publication_receipts")
        connection.commit()
    with pytest.raises(WorkflowDataCorruption, match="required table"):
        WorkflowStore(table_database)
