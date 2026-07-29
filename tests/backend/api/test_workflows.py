from __future__ import annotations

from types import SimpleNamespace

from stockroom.workflow import IntakeIdentity, WorkflowStore


class _MountedWorkflowAuthority:
    """Production-shaped coordinator seam backed by the real durable store."""

    def __init__(self, store: WorkflowStore):
        self.store = store
        self.calls: list[str] = []

    def status(self):
        return SimpleNamespace(
            state=SimpleNamespace(value="running"),
            thread_alive=True,
        )

    def get_batch(self, batch_id):
        self.calls.append("get_batch")
        return self.store.get_batch(batch_id)

    def list_items(self, batch_id):
        self.calls.append("list_items")
        return self.store.list_items(batch_id)

    def item_status_counts(self, batch_id):
        return self.store.item_status_counts(batch_id)

    def list_stages(self, item_id):
        return self.store.list_stages(item_id)

    def events(self, batch_id, *, after_sequence=0, limit=10_000):
        self.calls.append("events")
        return self.store.events(
            batch_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def latest_event_sequence(self, batch_id):
        self.calls.append("latest_event_sequence")
        return self.store.latest_event_sequence(batch_id)

    def get_batch_cancellation(self, batch_id):
        return self.store.get_batch_cancellation(batch_id)

    def pause_batch(self, batch_id):
        return self.store.pause_batch(batch_id)

    def resume_batch(self, batch_id):
        return self.store.resume_batch(batch_id)

    def retry_batch(self, batch_id):
        return self.store.retry_batch(batch_id)

    def cancel_batch(self, batch_id):
        return self.store.cancel_batch(batch_id)


def _mount(app_ctx, tmp_path):
    store = WorkflowStore(tmp_path / "Workflow.sqlite3")
    app_ctx.workflow_coordinator = _MountedWorkflowAuthority(store)
    return store


def _lease(stage) -> dict:
    assert stage.lease_token is not None
    return {
        "lease_token": stage.lease_token,
        "lease_generation": stage.lease_generation,
    }


def test_workflow_api_is_authenticated_and_honestly_unmounted(client, anon_client):
    assert anon_client.get("/api/workflows/batches/not-mounted").status_code == 401
    response = client.get("/api/workflows/batches/not-mounted")
    assert response.status_code == 503
    assert "not mounted" in response.json()["detail"].lower()


def test_snapshot_is_bounded_and_omits_raw_identity_payload_and_stage_state(
    client,
    app_ctx,
    tmp_path,
):
    store = _mount(app_ctx, tmp_path)
    secret = "Bearer should-never-cross-the-api"
    batch = store.submit_batch(
        [
            IntakeIdentity("Secret Manufacturer", f"PRIVATE-{index}", {"secret": secret})
            for index in range(3)
        ],
        now=1,
    )
    store.claim_ready(secret, now=2, lease_seconds=30, limit=1)

    first = client.get(
        f"/api/workflows/batches/{batch.id}",
        params={"limit": 2},
    )
    assert first.status_code == 200
    body = first.json()
    assert body["schema_version"] == 1
    assert body["batch"]["total_items"] == 3
    assert [item["ordinal"] for item in body["items"]] == [0, 1]
    assert body["page"] == {
        "after_ordinal": -1,
        "next_ordinal": 1,
        "limit": 2,
        "has_more": True,
    }
    assert set(body["items"][0]) == {"id", "ordinal", "status", "stages"}
    assert set(body["items"][0]["stages"][0]) == {
        "id",
        "name",
        "status",
        "attempt_count",
        "next_attempt_at",
    }
    assert secret not in repr(body)
    assert "PRIVATE-" not in repr(body)
    assert "Secret Manufacturer" not in repr(body)
    authority = app_ctx.workflow_coordinator
    assert authority.calls.index("latest_event_sequence") < authority.calls.index("get_batch")
    assert authority.calls.index("latest_event_sequence") < authority.calls.index("list_items")

    second = client.get(
        f"/api/workflows/batches/{batch.id}",
        params={"after_ordinal": 1, "limit": 2},
    ).json()
    assert [item["ordinal"] for item in second["items"]] == [2]
    assert second["page"]["has_more"] is False

    assert (
        client.get(
            f"/api/workflows/batches/{batch.id}",
            params={"limit": 251},
        ).status_code
        == 400
    )


def test_event_cursor_replays_without_overlap_and_sanitizes_payloads(
    client,
    app_ctx,
    tmp_path,
):
    store = _mount(app_ctx, tmp_path)
    secret = "secret-worker-owner"
    batch = store.submit_batch(
        [IntakeIdentity("ACME", "P-1", {"credential": secret})],
        now=1,
    )
    store.claim_ready(secret, now=2, lease_seconds=30, limit=1)

    first = client.get(
        f"/api/workflows/batches/{batch.id}/events",
        params={"after_sequence": 0, "limit": 2},
    )
    assert first.status_code == 200
    first_body = first.json()
    first_sequences = [event["sequence"] for event in first_body["events"]]
    assert first_sequences == sorted(first_sequences)
    assert first_body["cursor"]["has_more"] is True
    authority = app_ctx.workflow_coordinator
    assert authority.calls.index("get_batch") < authority.calls.index("events")

    second_body = client.get(
        f"/api/workflows/batches/{batch.id}/events",
        params={
            "after_sequence": first_body["cursor"]["next_sequence"],
            "limit": 500,
        },
    ).json()
    second_sequences = [event["sequence"] for event in second_body["events"]]
    assert set(first_sequences).isdisjoint(second_sequences)
    assert first_sequences + second_sequences == sorted(first_sequences + second_sequences)
    assert secret not in repr(first_body)
    assert secret not in repr(second_body)
    assert all(
        set(event)
        == {
            "sequence",
            "item_id",
            "stage_id",
            "kind",
            "details",
            "created_at",
        }
        for event in first_body["events"] + second_body["events"]
    )

    assert (
        client.get(
            f"/api/workflows/batches/{batch.id}/events",
            params={"after_sequence": 9_007_199_254_740_992},
        ).status_code
        == 400
    )
    assert (
        client.get(
            f"/api/workflows/batches/{batch.id}/events",
            params={"limit": 501},
        ).status_code
        == 400
    )


def test_controls_are_state_idempotent_and_retry_never_replays_completed_work(
    client,
    app_ctx,
    tmp_path,
):
    store = _mount(app_ctx, tmp_path)
    batch = store.submit_batch([IntakeIdentity("ACME", "P-1")], now=1)

    paused = client.post(f"/api/workflows/batches/{batch.id}/pause")
    assert paused.status_code == 200
    assert paused.json()["changed"] is True
    assert paused.json()["batch"]["status"] == "paused"
    assert client.post(f"/api/workflows/batches/{batch.id}/pause").json()["changed"] is False

    resumed = client.post(f"/api/workflows/batches/{batch.id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["changed"] is True
    assert client.post(f"/api/workflows/batches/{batch.id}/resume").json()["changed"] is False

    claim = store.claim_ready("worker", now=2, lease_seconds=30, limit=1)[0]
    store.fail_stage(
        claim.id,
        "worker",
        {"kind": "provider_failure"},
        **_lease(claim),
        now=3,
    )
    retried = client.post(f"/api/workflows/batches/{batch.id}/retry")
    assert retried.status_code == 200
    assert retried.json()["changed"] is True
    assert retried.json()["batch"]["status"] == "queued"
    assert client.post(f"/api/workflows/batches/{batch.id}/retry").json()["changed"] is False

    cancelled = client.post(f"/api/workflows/batches/{batch.id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["changed"] is True
    assert cancelled.json()["batch"]["status"] == "cancelled"
    assert client.post(f"/api/workflows/batches/{batch.id}/cancel").json()["changed"] is False

    kinds = [event.kind for event in store.events(batch.id)]
    assert kinds.count("batch_paused") == 1
    assert kinds.count("batch_resumed") == 1
    assert kinds.count("batch_retry_requested") == 1
    assert kinds.count("batch_cancel_requested") == 1
    assert kinds.count("batch_cancelled") == 1
    assert kinds.count("stage_completed") == 0
