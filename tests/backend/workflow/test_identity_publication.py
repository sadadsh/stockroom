import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from stockroom.workflow import (
    BatchCancellationState,
    BatchStatus,
    IntakeIdentity,
    PublicationCompletionDisposition,
    PublicationMembershipState,
    PublicationState,
    StageName,
    StageRecord,
    StageStatus,
    WorkflowConflict,
    WorkflowDataCorruption,
    WorkflowStore,
)


def _digest(label: str) -> str:
    return f"sha256:{hashlib.sha256(label.encode()).hexdigest()}"


def _stage_lease(stage: StageRecord) -> dict[str, str | int]:
    assert stage.lease_token is not None
    return {
        "lease_token": stage.lease_token,
        "lease_generation": stage.lease_generation,
    }


def _publication_lease(lease) -> dict[str, str | int]:
    return {
        "lease_token": lease.lease_token,
        "lease_generation": lease.lease_generation,
    }


def _resolve(
    store: WorkflowStore,
    stage: StageRecord,
    manufacturer: str,
    mpn: str,
    *,
    now: float,
):
    return store.resolve_exact_identity(
        stage.id,
        "stage-worker",
        authoritative_manufacturer_key=manufacturer,
        mpn_canonical=mpn,
        registry_revision="registry-v1",
        rule_revision="identity-rules-v1",
        evidence={"method": "exact-test"},
        **_stage_lease(stage),
        now=now,
    )


def _advance_batches_to_publish(
    store: WorkflowStore,
    batch_identity: dict[str, tuple[str, str]],
    *,
    start: float = 10,
) -> tuple[dict[str, StageRecord], float]:
    publish: dict[str, StageRecord] = {}
    timestamp = start
    while len(publish) != len(batch_identity):
        claims = store.claim_ready(
            "stage-worker",
            now=timestamp,
            lease_seconds=10_000,
            limit=1000,
        )
        assert claims
        for claim in claims:
            assert claim.batch_id in batch_identity
            if claim.name is StageName.PUBLISH:
                publish[claim.batch_id] = claim
            elif claim.name is StageName.IDENTITY_DEDUPE:
                _resolve(
                    store,
                    claim,
                    *batch_identity[claim.batch_id],
                    now=timestamp + 0.25,
                )
            else:
                store.complete_stage(
                    claim.id,
                    "stage-worker",
                    {"stage": claim.name.value},
                    **_stage_lease(claim),
                    now=timestamp + 0.25,
                )
        timestamp += 1
    return publish, timestamp


def _join(
    store: WorkflowStore,
    stage: StageRecord,
    *,
    candidate: str = "candidate-a",
    manifest: str = "manifest-a",
    base: str = "base-a",
    expected_head: str | None = None,
    now: float,
):
    return store.join_publication(
        stage.id,
        "stage-worker",
        candidate_digest=_digest(candidate),
        manifest_digest=_digest(manifest),
        expected_base_commit=base,
        expected_head_publication_id=expected_head,
        **_stage_lease(stage),
        now=now,
    )


def _finish(
    store: WorkflowStore,
    publication_id: str,
    *,
    now: float,
    lease=None,
):
    active_lease = (
        store.claim_publications(
            "publisher",
            now=now,
            lease_seconds=100,
            limit=1,
        )[0]
        if lease is None
        else lease
    )
    credentials = _publication_lease(active_lease)
    store.arm_publication_commit(
        publication_id,
        "publisher",
        **credentials,
        now=now + 1,
    )
    store.record_git_commit(
        publication_id,
        "publisher",
        git_commit_oid="git-commit-a",
        verified_tree_digest=_digest("tree-a"),
        **credentials,
        now=now + 2,
    )
    store.record_catalog_activation(
        publication_id,
        "publisher",
        catalog_revision="catalog-a",
        catalog_semantic_digest=_digest("catalog-a"),
        **credentials,
        now=now + 3,
    )
    assert store.complete_publication(
        publication_id,
        "publisher",
        {"activated": True},
        **credentials,
        now=now + 4,
    )
    return active_lease


def test_exact_identity_converges_concurrently_without_rewriting_intake(tmp_path):
    store = WorkflowStore(tmp_path / "workflow.sqlite3")
    batch = store.submit_batch(
        [
            IntakeIdentity("raw alias one", "raw-1", {"row": 1}),
            IntakeIdentity("raw alias two", "raw-2", {"row": 2}),
        ],
        now=1,
    )
    claims = store.claim_ready(
        "stage-worker",
        now=2,
        lease_seconds=100,
        limit=2,
    )
    start = Barrier(2)

    def resolve(claim: StageRecord):
        start.wait()
        return _resolve(store, claim, "ACME Incorporated", "P-1", now=3)

    with ThreadPoolExecutor(max_workers=2) as pool:
        bindings = list(pool.map(resolve, claims))

    assert len({binding.component_id for binding in bindings}) == 1
    assert len(store.list_component_memberships(bindings[0].component_id)) == 2
    items = store.list_items(batch.id)
    assert [(item.manufacturer, item.mpn, item.payload) for item in items] == [
        ("raw alias one", "raw-1", {"row": 1}),
        ("raw alias two", "raw-2", {"row": 2}),
    ]


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (("ACME", "P-1"), ("Acme", "P-1")),
        (("ACME", "P-1"), ("ACME.", "P-1")),
        (("ACME", "P-1"), ("ＡＣＭＥ", "P-1")),
        (("ACME", "P-1"), ("ACME", "P-1A")),
        (("Unknown", "P-1"), ("UNKNOWN", "P-1")),
        (("ACME", "P-1"), ("Other Manufacturer", "P-1")),
    ],
)
def test_authoritative_identity_does_not_guess_aliases(tmp_path, left, right):
    store = WorkflowStore(tmp_path / "workflow.sqlite3")
    store.submit_batch(
        [IntakeIdentity("raw", "left"), IntakeIdentity("raw", "right")],
        now=1,
    )
    claims = store.claim_ready(
        "stage-worker",
        now=2,
        lease_seconds=100,
        limit=2,
    )
    bindings = [
        _resolve(store, claim, *identity, now=3 + index)
        for index, (claim, identity) in enumerate(zip(claims, (left, right)))
    ]
    assert bindings[0].component_id != bindings[1].component_id


def test_authoritative_identity_requires_exact_nfc_and_is_cross_database_stable(
    tmp_path,
):
    invalid_store = WorkflowStore(tmp_path / "invalid.sqlite3")
    invalid_store.submit_batch([IntakeIdentity("raw", "P-1")], now=1)
    invalid = invalid_store.claim_ready(
        "stage-worker",
        now=2,
        lease_seconds=100,
        limit=1,
    )[0]
    with pytest.raises(ValueError, match="surrounding whitespace"):
        _resolve(invalid_store, invalid, " ACME", "P-1", now=3)
    with pytest.raises(ValueError, match="canonical NFC"):
        _resolve(invalid_store, invalid, "Cafe\u0301", "P-1", now=3)

    component_ids = []
    for index in range(2):
        store = WorkflowStore(tmp_path / f"stable-{index}.sqlite3")
        store.submit_batch([IntakeIdentity("anything", "anything")], now=1)
        claim = store.claim_ready(
            "stage-worker",
            now=2,
            lease_seconds=100,
            limit=1,
        )[0]
        component_ids.append(_resolve(store, claim, "Café", "P-1", now=3).component_id)
    assert component_ids[0] == component_ids[1]
    assert component_ids[0].startswith("cmp_")
    assert len(component_ids[0]) == 56


def test_seeded_deterministic_identity_collision_is_quarantined(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    store = WorkflowStore(database)
    store.submit_batch(
        [IntakeIdentity("raw", "one"), IntakeIdentity("raw", "two")],
        now=1,
    )
    claims = store.claim_ready(
        "stage-worker",
        now=2,
        lease_seconds=100,
        limit=2,
    )
    first = _resolve(store, claims[0], "ACME", "P-1", now=3)
    component = store.get_resolved_component(first.component_id)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            UPDATE resolved_manufacturers
            SET authoritative_key = 'corrupt'
            WHERE manufacturer_id = ?
            """,
            (component.manufacturer_id,),
        )
        connection.commit()

    with pytest.raises(WorkflowDataCorruption, match="manufacturer identity collision"):
        _resolve(store, claims[1], "ACME", "P-1", now=4)
    assert store.get_item_component(claims[1].item_id) is None


def test_generic_completion_cannot_bypass_identity_or_publication(tmp_path):
    store = WorkflowStore(tmp_path / "workflow.sqlite3")
    batch = store.submit_batch([IntakeIdentity("ACME", "P-1")], now=1)
    identity = store.claim_ready(
        "stage-worker",
        now=2,
        lease_seconds=100,
        limit=1,
    )[0]
    with pytest.raises(ValueError, match="resolve_exact_identity"):
        store.complete_stage(
            identity.id,
            "stage-worker",
            {},
            **_stage_lease(identity),
            now=3,
        )
    _resolve(store, identity, "ACME", "P-1", now=3)
    publish, timestamp = _advance_batches_to_publish(
        store,
        {batch.id: ("ACME", "P-1")},
        start=4,
    )
    with pytest.raises(ValueError, match="component publication methods"):
        store.complete_stage(
            publish[batch.id].id,
            "stage-worker",
            {},
            **_stage_lease(publish[batch.id]),
            now=timestamp,
        )


def test_same_candidate_is_one_global_publication_and_one_receipt(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    store = WorkflowStore(database)
    first = store.submit_batch([IntakeIdentity("alias-a", "raw-a")], now=1)
    second = store.submit_batch([IntakeIdentity("alias-b", "raw-b")], now=2)
    publish, timestamp = _advance_batches_to_publish(
        store,
        {
            first.id: ("ACME", "P-1"),
            second.id: ("ACME", "P-1"),
        },
    )
    memberships = [
        _join(store, publish[batch_id], now=timestamp + index)
        for index, batch_id in enumerate((first.id, second.id))
    ]
    assert len({membership.publication_id for membership in memberships}) == 1
    publication_id = memberships[0].publication_id
    assert len(store.claim_publications("probe", now=timestamp + 2, limit=10)) == 1

    # Let the probe lease expire, then reconcile with a new generation.
    lease = store.claim_publications(
        "publisher",
        now=timestamp + 63,
        lease_seconds=100,
        limit=1,
    )[0]
    _finish(store, publication_id, now=timestamp + 64, lease=lease)

    assert store.get_batch(first.id).status is BatchStatus.COMPLETED
    assert store.get_batch(second.id).status is BatchStatus.COMPLETED
    assert store.get_component_publication_receipt(publication_id) is not None
    assert all(
        store.get_publication_membership(stage.item_id).state
        is PublicationMembershipState.COMPLETED
        for stage in publish.values()
    )
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM component_publication_receipts").fetchone()[0]
            == 1
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM component_publication_heads").fetchone()[0]
            == 1
        )

    operation = store.get_publication_operation(publication_id)
    assert not hasattr(operation, "lease_token")
    assert "lease_token" not in json.dumps([event.payload for event in store.events(first.id)])


def test_different_candidate_conflicts_instead_of_silent_first_writer_merge(tmp_path):
    store = WorkflowStore(tmp_path / "workflow.sqlite3")
    first = store.submit_batch([IntakeIdentity("a", "a")], now=1)
    second = store.submit_batch([IntakeIdentity("b", "b")], now=2)
    publish, timestamp = _advance_batches_to_publish(
        store,
        {
            first.id: ("ACME", "P-1"),
            second.id: ("ACME", "P-1"),
        },
    )
    first_membership = _join(
        store,
        publish[first.id],
        candidate="candidate-a",
        now=timestamp,
    )
    second_membership = _join(
        store,
        publish[second.id],
        candidate="candidate-b",
        now=timestamp + 1,
    )
    assert first_membership.publication_id != second_membership.publication_id
    assert (
        store.get_publication_membership(publish[first.id].item_id).state
        is PublicationMembershipState.CONFLICT
    )
    assert second_membership.state is PublicationMembershipState.CONFLICT
    assert store.claim_publications("publisher", now=timestamp + 2) == []


def test_publication_generation_fence_and_plan_immutability(tmp_path):
    store = WorkflowStore(tmp_path / "workflow.sqlite3")
    batch = store.submit_batch([IntakeIdentity("ACME", "P-1")], now=1)
    publish, timestamp = _advance_batches_to_publish(
        store,
        {batch.id: ("ACME", "P-1")},
    )
    membership = _join(store, publish[batch.id], now=timestamp)
    stale = store.claim_publications(
        "publisher",
        now=timestamp + 1,
        lease_seconds=5,
    )[0]
    current = store.claim_publications(
        "publisher",
        now=timestamp + 6,
        lease_seconds=100,
    )[0]
    assert current.lease_generation == stale.lease_generation + 1
    with pytest.raises(WorkflowConflict, match="stale|expired"):
        store.arm_publication_commit(
            membership.publication_id,
            "publisher",
            **_publication_lease(stale),
            now=timestamp + 7,
        )

    replanned = store.replan_publication(
        membership.publication_id,
        "publisher",
        manifest_digest=_digest("manifest-b"),
        expected_base_commit="base-b",
        expected_head_publication_id=None,
        **_publication_lease(current),
        now=timestamp + 7,
    )
    assert replanned.publication_id == membership.publication_id
    assert replanned.manifest_digest == _digest("manifest-b")
    store.arm_publication_commit(
        membership.publication_id,
        "publisher",
        **_publication_lease(current),
        now=timestamp + 8,
    )
    with pytest.raises(WorkflowConflict, match="immutable"):
        store.replan_publication(
            membership.publication_id,
            "publisher",
            manifest_digest=_digest("manifest-c"),
            expected_base_commit="base-c",
            expected_head_publication_id=None,
            **_publication_lease(current),
            now=timestamp + 9,
        )


def test_pre_fence_cancellation_aborts_only_when_no_live_members_remain(tmp_path):
    store = WorkflowStore(tmp_path / "workflow.sqlite3")
    first = store.submit_batch([IntakeIdentity("a", "a")], now=1)
    second = store.submit_batch([IntakeIdentity("b", "b")], now=2)
    publish, timestamp = _advance_batches_to_publish(
        store,
        {
            first.id: ("ACME", "P-1"),
            second.id: ("ACME", "P-1"),
        },
    )
    first_member = _join(store, publish[first.id], now=timestamp)
    _join(store, publish[second.id], now=timestamp + 1)

    assert (
        store.cancel_batch(first.id, reason={"why": "test"}, now=timestamp + 2).status
        is BatchStatus.CANCELLED
    )
    assert (
        store.get_publication_membership(publish[first.id].item_id).state
        is PublicationMembershipState.CANCELLED
    )
    assert (
        store.get_publication_operation(first_member.publication_id).state
        is PublicationState.PREPARING
    )
    _finish(store, first_member.publication_id, now=timestamp + 3)
    assert store.get_batch(second.id).status is BatchStatus.COMPLETED


def test_post_fence_cancel_reconciles_as_completed_before_cancel(tmp_path):
    store = WorkflowStore(tmp_path / "workflow.sqlite3")
    batch = store.submit_batch([IntakeIdentity("ACME", "P-1")], now=1)
    publish, timestamp = _advance_batches_to_publish(
        store,
        {batch.id: ("ACME", "P-1")},
    )
    membership = _join(store, publish[batch.id], now=timestamp)
    lease = store.claim_publications(
        "publisher",
        now=timestamp + 1,
        lease_seconds=100,
    )[0]
    store.arm_publication_commit(
        membership.publication_id,
        "publisher",
        **_publication_lease(lease),
        now=timestamp + 2,
    )
    cancelled = store.cancel_batch(
        batch.id,
        reason={"why": "after-fence"},
        now=timestamp + 3,
    )
    assert cancelled.status is BatchStatus.BLOCKED
    cancellation = store.get_batch_cancellation(batch.id)
    assert cancellation is not None
    assert cancellation.state is BatchCancellationState.REQUESTED

    store.record_git_commit(
        membership.publication_id,
        "publisher",
        git_commit_oid="git-commit-a",
        verified_tree_digest=_digest("tree-a"),
        **_publication_lease(lease),
        now=timestamp + 4,
    )
    store.record_catalog_activation(
        membership.publication_id,
        "publisher",
        catalog_revision="catalog-a",
        catalog_semantic_digest=_digest("catalog-a"),
        **_publication_lease(lease),
        now=timestamp + 5,
    )
    store.complete_publication(
        membership.publication_id,
        "publisher",
        {"activated": True},
        **_publication_lease(lease),
        now=timestamp + 6,
    )
    settled = store.get_publication_membership(publish[batch.id].item_id)
    assert settled is not None
    assert (
        settled.completion_disposition is PublicationCompletionDisposition.COMPLETED_BEFORE_CANCEL
    )
    assert store.get_batch(batch.id).status is BatchStatus.CANCELLED
    assert store.get_batch_cancellation(batch.id).state is BatchCancellationState.COMPLETED


def test_checkpoint_reopen_reconciles_once_and_rejects_early_completion(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    store = WorkflowStore(database)
    batch = store.submit_batch([IntakeIdentity("ACME", "P-1")], now=1)
    publish, timestamp = _advance_batches_to_publish(
        store,
        {batch.id: ("ACME", "P-1")},
    )
    membership = _join(store, publish[batch.id], now=timestamp)
    stale = store.claim_publications(
        "publisher-a",
        now=timestamp + 1,
        lease_seconds=5,
    )[0]
    with pytest.raises(WorkflowConflict, match="not catalog_activated"):
        store.complete_publication(
            membership.publication_id,
            "publisher-a",
            {},
            **_publication_lease(stale),
            now=timestamp + 2,
        )
    store.arm_publication_commit(
        membership.publication_id,
        "publisher-a",
        **_publication_lease(stale),
        now=timestamp + 2,
    )

    reopened = WorkflowStore(database)
    assert [
        operation.publication_id for operation in reopened.list_publications_for_reconciliation()
    ] == [membership.publication_id]
    current = reopened.claim_publications(
        "publisher-b",
        now=timestamp + 6,
        lease_seconds=100,
    )[0]
    with pytest.raises(WorkflowConflict, match="stale|expired|another worker"):
        reopened.record_git_commit(
            membership.publication_id,
            "publisher-a",
            git_commit_oid="old",
            verified_tree_digest=_digest("old-tree"),
            **_publication_lease(stale),
            now=timestamp + 7,
        )
    reopened.record_git_commit(
        membership.publication_id,
        "publisher-b",
        git_commit_oid="git-commit-a",
        verified_tree_digest=_digest("tree-a"),
        **_publication_lease(current),
        now=timestamp + 7,
    )
    reopened.record_catalog_activation(
        membership.publication_id,
        "publisher-b",
        catalog_revision="catalog-a",
        catalog_semantic_digest=_digest("catalog-a"),
        **_publication_lease(current),
        now=timestamp + 8,
    )
    assert reopened.complete_publication(
        membership.publication_id,
        "publisher-b",
        {"activated": True},
        **_publication_lease(current),
        now=timestamp + 9,
    )
    assert not reopened.complete_publication(
        membership.publication_id,
        "publisher-b",
        {"activated": True},
        **_publication_lease(current),
        now=timestamp + 10,
    )
    with pytest.raises(WorkflowConflict, match="different receipt"):
        reopened.complete_publication(
            membership.publication_id,
            "publisher-b",
            {"activated": False},
            **_publication_lease(current),
            now=timestamp + 10,
        )


def test_completed_operation_requires_receipt_and_current_head_for_late_join(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    store = WorkflowStore(database)
    first = store.submit_batch([IntakeIdentity("a", "a")], now=1)
    publish, timestamp = _advance_batches_to_publish(
        store,
        {first.id: ("ACME", "P-1")},
    )
    membership = _join(store, publish[first.id], now=timestamp)
    _finish(store, membership.publication_id, now=timestamp + 1)

    second = store.submit_batch([IntakeIdentity("b", "b")], now=timestamp + 10)
    late_publish, late_time = _advance_batches_to_publish(
        store,
        {second.id: ("ACME", "P-1")},
        start=timestamp + 11,
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM component_publication_receipts WHERE publication_id = ?",
            (membership.publication_id,),
        )
        connection.commit()

    with pytest.raises(WorkflowDataCorruption, match="no global receipt"):
        _join(store, late_publish[second.id], now=late_time)
    assert store.get_publication_membership(late_publish[second.id].item_id) is None
