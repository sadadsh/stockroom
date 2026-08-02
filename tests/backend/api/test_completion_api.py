"""The completion surface: "is my library complete", and "make it complete".

Both of these were things only a script outside the app could do, which by the owner's
standing rule (*"everything u do manually the app should do by itself"*) made them missing
features rather than tooling. These tests drive the REAL routes on the real app.
"""

import hashlib
import json
from types import SimpleNamespace

import pytest

from stockroom.service import WorkflowCoordinatorLifecycleError
from stockroom.workflow import (
    BatchStatus,
    CompletionOutcome,
    ExactIdentityOutcome,
    PublicationProposalOutcome,
    StageName,
    WorkflowRuntime,
    WorkflowStore,
)


def _digest(label: str) -> str:
    return f"sha256:{hashlib.sha256(label.encode()).hexdigest()}"


class _MountedCompletionAuthority:
    """Production-shaped durable API authority backed by the real store."""

    def __init__(self, store: WorkflowStore, *, submit_error: Exception | None = None):
        self.store = store
        self.submit_error = submit_error
        self.submissions = []

    def status(self):
        return SimpleNamespace(
            state=SimpleNamespace(value="running"),
            thread_alive=True,
        )

    def submit_batch(self, identities, *, idempotency_key=None):
        submitted = tuple(identities)
        self.submissions.append((submitted, idempotency_key))
        if self.submit_error is not None:
            raise self.submit_error
        return self.store.submit_batch(
            submitted,
            idempotency_key=idempotency_key,
        )

    def get_batch(self, batch_id):
        return self.store.get_batch(batch_id)

    def list_items(self, batch_id):
        return self.store.list_items(batch_id)

    def item_status_counts(self, batch_id):
        return self.store.item_status_counts(batch_id)

    def list_stages(self, item_id):
        return self.store.list_stages(item_id)

    def events(self, batch_id, *, after_sequence=0, limit=10_000):
        return self.store.events(
            batch_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def latest_event_sequence(self, batch_id):
        return self.store.latest_event_sequence(batch_id)

    def get_batch_cancellation(self, batch_id):
        return self.store.get_batch_cancellation(batch_id)


def _mount_completion_authority(app_ctx, tmp_path, *, submit_error=None):
    store = WorkflowStore(tmp_path / "Completion Workflow.sqlite3")
    authority = _MountedCompletionAuthority(store, submit_error=submit_error)
    app_ctx.workflow_coordinator = authority
    return store, authority


def _finish_durable_batch(store: WorkflowStore, batch_id: str) -> None:
    """Drive the real DAG and publication journal to its terminal receipt."""

    def handle(context):
        if context.stage.name is StageName.IDENTITY_DEDUPE:
            return ExactIdentityOutcome(
                authoritative_manufacturer_key=(
                    context.item.manufacturer_key or "unknown-manufacturer"
                ),
                mpn_canonical=context.item.mpn,
                registry_revision="api-test-registry-v1",
                rule_revision="api-test-rules-v1",
                evidence={"source": "completion-api-test"},
            )
        if context.stage.name is StageName.PUBLISH:
            return PublicationProposalOutcome(
                candidate_digest=_digest(f"candidate:{context.item.id}"),
                manifest_digest=_digest(f"manifest:{context.item.id}"),
                expected_base_commit="base-commit",
            )
        return CompletionOutcome({"stage": context.stage.name.value})

    runtime = WorkflowRuntime(store, {name: handle for name in StageName})
    timestamp = 10.0
    for _ in range(100):
        dispatched = runtime.poll_once(
            "api-test-stage-worker",
            now=timestamp,
            lease_seconds=1_000,
        )
        timestamp += 1
        if dispatched is None:
            break
    else:
        raise AssertionError("durable workflow did not reach the publication wait")

    item = store.list_items(batch_id)[0]
    membership = store.get_publication_membership(item.id)
    assert membership is not None
    lease = store.claim_publications(
        "api-test-publisher",
        now=timestamp,
        lease_seconds=1_000,
        limit=1,
    )[0]
    credentials = {
        "lease_token": lease.lease_token,
        "lease_generation": lease.lease_generation,
    }
    store.arm_publication_commit(
        membership.publication_id,
        "api-test-publisher",
        **credentials,
        now=timestamp + 1,
    )
    store.record_git_commit(
        membership.publication_id,
        "api-test-publisher",
        git_commit_oid="api-test-commit",
        verified_tree_digest=_digest("api-test-tree"),
        **credentials,
        now=timestamp + 2,
    )
    store.record_catalog_activation(
        membership.publication_id,
        "api-test-publisher",
        catalog_revision="api-test-catalog",
        catalog_semantic_digest=_digest("api-test-catalog"),
        **credentials,
        now=timestamp + 3,
    )
    assert store.complete_publication(
        membership.publication_id,
        "api-test-publisher",
        {"activated": True},
        **credentials,
        now=timestamp + 4,
    )
    assert store.get_batch(batch_id).status is BatchStatus.COMPLETED


def _sse(client, job_id):
    """Drain a job's SSE stream into (kind, payload) pairs."""
    out = []
    with client.stream("GET", f"/api/jobs/{job_id}/events") as resp:
        assert resp.status_code == 200
        kind = None
        for line in resp.iter_lines():
            if line.startswith("event:"):
                kind = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                out.append((kind, json.loads(line.split(":", 1)[1].strip())))
    return out


# --- coverage ------------------------------------------------------------------------------


def test_coverage_answers_whether_the_library_is_complete(client):
    body = client.get("/api/library/completion").json()
    # The fixture library holds one part with a symbol+footprint and one without.
    assert body["total"] == 2
    assert set(body) >= {
        "total",
        "complete",
        "needs_files",
        "needs_assistance",
        "unsourced",
        "by_requirement",
        "sources",
        "can_provide",
        "assisted_sources",
        "assisted_can_provide",
    }


def test_coverage_breaks_the_gap_down_by_what_is_actually_missing(client):
    body = client.get("/api/library/completion").json()
    # Named per requirement, not one anonymous "incomplete" number: "3 parts need a 3D model"
    # is actionable and "3 parts are incomplete" is not.
    assert body["by_requirement"], body
    assert all(k.count("_") >= 1 for k in body["by_requirement"])


def test_coverage_separates_a_gap_with_a_source_from_a_gap_with_none(client):
    """Retained exact evidence is an automatic dual-EDA source, while uncached commercial
    acquisition remains an assisted fallback. A part may therefore count in both lanes: the
    automatic source is tried first and declines honestly when no exact bundle is retained."""
    body = client.get("/api/library/completion").json()
    assert body["needs_files"] + body["unsourced"] + body["complete"] <= body["total"]
    assert "altium_symbol" in body["by_requirement"]
    assert "altium_symbol" in body["can_provide"]
    assert "altium_symbol" in body["assisted_can_provide"]
    assert body["needs_assistance"] > 0


def test_coverage_needs_a_token(anon_client):
    assert anon_client.get("/api/library/completion").status_code == 401


def test_durable_completion_includes_present_but_unverified_cad(monkeypatch):
    from stockroom.api.routers.library import _needs_durable_completion
    from stockroom.capture.complete import CompletionEvidence
    from stockroom.capture.requirements import Requirement, split_requirement
    from stockroom.model.part import AssetRef, Datasheet, PartRecord, Purchase

    record = PartRecord(
        id="present-not-proven",
        display_name="Present Not Proven",
        category="ICs",
        description="all passport fields and references are populated",
        mpn="EXACT-123",
        manufacturer="Example",
        datasheet=Datasheet(source_url="https://example.test/datasheet.pdf"),
        purchase=[Purchase(vendor="Example", url="https://example.test/part")],
    )
    for owned in Requirement:
        tool, kind = split_requirement(owned)
        record.assets_for(tool).set(
            kind,
            AssetRef(file="model.step")
            if kind == "model"
            else AssetRef(lib="Present", name=record.mpn),
        )
    # Durable completion also tracks the separately closable Altium embedded-body
    # action. Populate that legacy projection fact so this test isolates evidence
    # authority rather than exercising the embedding gate.
    record.assets_for("altium").set("model", AssetRef(file="embedded-in.PcbLib"))

    monkeypatch.setattr(
        "stockroom.capture.verified_cache.record_completion_evidence",
        lambda _store, _record: CompletionEvidence.unverified(
            "the active evidence pointer is absent"
        ),
    )
    assert _needs_durable_completion(record, evidence_store=object()) is True

    monkeypatch.setattr(
        "stockroom.capture.verified_cache.record_completion_evidence",
        lambda _store, _record: CompletionEvidence(
            state="verified",
            manifest_digest="sha256:" + ("a" * 64),
            reason="the active projection was reverified",
        ),
    )
    assert _needs_durable_completion(record, evidence_store=object()) is False


# --- running -------------------------------------------------------------------------------


def test_a_run_streams_progress_and_finishes(client, monkeypatch):
    """Drives the real route end to end with the network source stubbed out. The point is the
    JOB: it starts, streams named progress, and lands a terminal result."""
    from stockroom.capture.complete import SourceOutcome
    from stockroom.capture.requirements import Requirement

    class Nothing:
        key = "stub"

        def provides(self):
            return frozenset({Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT})

        def supply(self, record):
            return SourceOutcome(skipped="stubbed")

    monkeypatch.setattr("stockroom.capture.runner.build_sources", lambda ctx, **kw: [Nothing()])
    job_id = client.post("/api/library/completion/run", json={}).json()["job_id"]
    events = _sse(client, job_id)
    kinds = [k for k, _ in events]
    assert "result" in kinds
    assert "error" not in kinds
    result = [p for k, p in events if k == "result"][0]["result"]
    assert "counts" in result and "items" in result


def test_a_run_can_be_limited_so_a_huge_library_is_previewable(client, monkeypatch):
    # Starting a 21-hour run to find out whether it works is not a reasonable first step.
    from stockroom.capture.complete import SourceOutcome
    from stockroom.capture.requirements import Requirement

    seen = []

    class Counting:
        key = "stub"

        def provides(self):
            # KICAD_MODEL is the asset the fixture library genuinely lacks (both parts carry
            # a symbol and a footprint), so this source has real work to be limited.
            return frozenset({Requirement.KICAD_MODEL})

        def supply(self, record):
            seen.append(record.id)
            return SourceOutcome(skipped="stubbed")

    monkeypatch.setattr("stockroom.capture.runner.build_sources", lambda ctx, **kw: [Counting()])
    job_id = client.post("/api/library/completion/run", json={"limit": 1}).json()["job_id"]
    _sse(client, job_id)
    assert len(seen) == 1


def test_a_run_over_a_chosen_part_touches_only_that_part(client, monkeypatch):
    from stockroom.capture.complete import SourceOutcome
    from stockroom.capture.requirements import Requirement

    seen = []

    class Counting:
        key = "stub"

        def provides(self):
            return frozenset({Requirement.KICAD_MODEL})

        def supply(self, record):
            seen.append(record.id)
            return SourceOutcome(skipped="stubbed")

    monkeypatch.setattr("stockroom.capture.runner.build_sources", lambda ctx, **kw: [Counting()])
    job_id = client.post("/api/library/completion/run", json={"part_ids": ["mystery"]}).json()[
        "job_id"
    ]
    _sse(client, job_id)
    assert seen == ["mystery"]


def test_mounted_completion_is_one_idempotent_durable_batch_and_never_a_legacy_job(
    client,
    app_ctx,
    tmp_path,
    monkeypatch,
):
    store, authority = _mount_completion_authority(app_ctx, tmp_path)

    def reject_legacy_launch(*_args, **_kwargs):
        raise AssertionError("mounted completion must not launch the legacy runner")

    monkeypatch.setattr(app_ctx.jobs, "submit_cancellable", reject_legacy_launch)
    command = {"part_ids": ["tps62130"], "limit": 1}
    headers = {"Idempotency-Key": "completion-command-1"}

    first = client.post("/api/library/completion/run", json=command, headers=headers)
    retry = client.post("/api/library/completion/run", json=command, headers=headers)

    assert first.status_code == retry.status_code == 200
    assert retry.json() == first.json()
    assert first.json()["event_cursor"] == 0
    batch_id = first.json()["workflow_batch_id"]
    assert store.count_batches() == 1
    assert store.get_batch(batch_id).status is BatchStatus.QUEUED
    assert [event.kind for event in store.events(batch_id)].count("batch_submitted") == 1
    assert len(authority.submissions) == 2
    submitted, key = authority.submissions[0]
    assert key == "completion-command-1"
    assert len(submitted) == 1
    assert submitted[0].manufacturer == "TI"
    assert submitted[0].mpn == "TPS62130"
    assert dict(submitted[0].payload) == {"part_id": "tps62130"}
    assert type(submitted[0].payload).__name__ == "mappingproxy"
    stored_item = store.list_items(batch_id)[0]
    assert stored_item.payload == {"part_id": "tps62130"}

    # The key binds to the current resolved identity, not merely the URL/body.
    # A record change between attempts is a different command and must not
    # silently return the old batch or create a second one.
    record = app_ctx.ops.load_record("tps62130")
    record.manufacturer = "Changed Manufacturer"
    (app_ctx.profile.library.parts_dir / "tps62130.json").write_text(
        record.dumps(),
        encoding="utf-8",
    )
    conflict = client.post("/api/library/completion/run", json=command, headers=headers)
    assert conflict.status_code == 409
    assert store.count_batches() == 1


def test_returned_cursor_follows_the_submitted_batch_through_terminal_publication(
    client,
    app_ctx,
    tmp_path,
    monkeypatch,
):
    store, _ = _mount_completion_authority(app_ctx, tmp_path)
    monkeypatch.setattr(
        app_ctx.jobs,
        "submit_cancellable",
        lambda *_args, **_kwargs: pytest.fail("durable submission launched a legacy job"),
    )

    response = client.post(
        "/api/library/completion/run",
        json={"part_ids": ["tps62130"]},
    )
    assert response.status_code == 200
    reference = response.json()
    batch_id = reference["workflow_batch_id"]
    cursor = reference["event_cursor"]
    # Submission returns at the durable boundary, before any stage executes.
    assert cursor == 0
    assert store.get_batch(batch_id).status is BatchStatus.QUEUED

    _finish_durable_batch(store, batch_id)

    observed_kinds = []
    while True:
        page_response = client.get(
            f"/api/workflows/batches/{batch_id}/events",
            params={"after_sequence": cursor, "limit": 7},
        )
        assert page_response.status_code == 200
        page = page_response.json()
        observed_kinds.extend(event["kind"] for event in page["events"])
        next_cursor = page["cursor"]["next_sequence"]
        assert next_cursor > cursor
        cursor = next_cursor
        if not page["cursor"]["has_more"]:
            assert page["batch"]["status"] == "completed"
            break

    assert "publication_completed" in observed_kinds
    assert cursor == store.latest_event_sequence(batch_id)


def test_mounted_guided_capture_is_one_reconnectable_workflow_item(
    client,
    app_ctx,
    tmp_path,
    monkeypatch,
):
    store, authority = _mount_completion_authority(app_ctx, tmp_path)
    monkeypatch.setenv("STOCKROOM_CAPTURE_DIR", str(tmp_path / "Capture State"))
    monkeypatch.setattr(
        app_ctx.jobs,
        "submit_cancellable",
        lambda *_args, **_kwargs: pytest.fail("durable capture launched a legacy job"),
    )
    command = {
        "part_ids": ["tps62130"],
        "mode": "assisted",
        "vendor": "ultralibrarian",
        "idempotency_key": "capture-tps62130",
    }

    first = client.post("/api/library/capture/run", json=command)
    second = client.post("/api/library/capture/run", json=command)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    reference = first.json()
    assert second.json() == reference
    assert set(reference) == {
        "workflow_batch_id",
        "workflow_item_id",
        "event_cursor",
    }
    assert reference["event_cursor"] == 0
    batch_id = reference["workflow_batch_id"]
    item_id = reference["workflow_item_id"]
    assert len(authority.submissions) == 2
    submitted, idempotency_key = authority.submissions[0]
    assert idempotency_key == "capture-tps62130"
    assert len(submitted) == 1
    assert dict(submitted[0].payload) == {
        "part_id": "tps62130",
        "workflow_kind": "guided_capture",
        "capture": {
            "mode": "assisted",
            "vendor": "ultralibrarian",
            "background": False,
            "initial_needs": [
                "kicad_symbol",
                "kicad_footprint",
                "kicad_model",
                "altium_symbol",
                "altium_footprint",
            ],
        },
    }
    assert store.list_items(batch_id)[0].id == item_id

    projected = client.get(f"/api/library/capture/batches/{batch_id}")
    assert projected.status_code == 200, projected.text
    body = projected.json()
    # `handoff` is asserted separately below: it is derived guidance, not part of the durable
    # request, and pinning its full text here would make every provider wording change a failure.
    handoff = body.pop("handoff")
    assert body == {
        "workflow_batch_id": batch_id,
        "workflow_item_id": item_id,
        "part_id": "tps62130",
        "mode": "assisted",
        "vendor": "ultralibrarian",
        "background": False,
        "initial_needs": [
            "kicad_symbol",
            "kicad_footprint",
            "kicad_model",
            "altium_symbol",
            "altium_footprint",
        ],
        "report": None,
    }
    # Ultra Librarian is the ONE route Stockroom is authorized to drive, so it keeps the
    # Playwright transport and its own window; the checklist still travels with it.
    assert handoff["transport"] == "playwright"
    assert handoff["opens_in"] == "a Stockroom-controlled window"
    assert handoff["mpn"]
    assert handoff["routes"] and all(route["required_files"] for route in handoff["routes"])
    replay = client.get(
        f"/api/workflows/batches/{batch_id}/events",
        params={"after_sequence": 0},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["batch"]["kind"] == "guided_capture"


def test_durable_capture_projection_returns_the_retained_terminal_report(
    client,
    app_ctx,
    tmp_path,
    monkeypatch,
):
    from stockroom.capture.runner import write_durable_capture_report

    _mount_completion_authority(app_ctx, tmp_path)
    monkeypatch.setenv("STOCKROOM_CAPTURE_DIR", str(tmp_path / "Capture State"))
    reference = client.post(
        "/api/library/capture/run",
        json={"part_ids": ["tps62130"]},
    ).json()
    report = {
        "items": [
            {
                "part_id": "tps62130",
                "status": "completed",
                "remaining": [],
                "completion_evidence": {
                    "state": "verified",
                    "manifest_digest": _digest("capture-manifest"),
                    "reason": "Verified.",
                },
            }
        ],
        "counts": {"completed": 1},
        "retained": 0,
        "collection_complete": None,
        "stopped": False,
        "stop_reason": "",
    }
    write_durable_capture_report(reference["workflow_item_id"], report)

    projected = client.get(f"/api/library/capture/batches/{reference['workflow_batch_id']}")

    assert projected.status_code == 200, projected.text
    assert projected.json()["report"] == report


def _write_completable_part(app_ctx, part_id: str, mpn: str) -> None:
    """One more current record that a library-wide batch can legitimately pick up."""

    from stockroom.model.part import AssetRef, PartRecord

    record = PartRecord(
        id=part_id,
        display_name=mpn,
        category="ICs",
        description="a part",
        mpn=mpn,
        manufacturer="TI",
    )
    record.assets_for("kicad").symbol = AssetRef(lib="SR-ICs", name=mpn)
    (app_ctx.profile.library.parts_dir / f"{part_id}.json").write_text(
        record.dumps(),
        encoding="utf-8",
    )


def _item_ids_by_part(store, batch_id: str) -> dict[str, str]:
    return {item.payload["part_id"]: item.id for item in store.list_items(batch_id)}


def _batch_report(part_id: str, **item) -> dict:
    row = {
        "part_id": part_id,
        "mpn": part_id.upper(),
        "display_name": part_id.upper(),
        "status": "completed",
        "needed": [],
        "satisfied": [],
        "remaining": [],
        "sources": [],
        "notes": [],
        "error": "",
        "provider_outcomes": [],
        "collection_complete": None,
        "completion_evidence": {
            "state": "verified",
            "manifest_digest": _digest(part_id),
            "reason": "Verified.",
        },
    }
    row.update(item)
    return {
        "items": [row],
        "counts": {row["status"]: 1},
        "retained": 0,
        "collection_complete": None,
        "stopped": False,
        "stop_reason": "",
    }


def test_batch_worklist_separates_unattended_parts_from_the_routes_needing_a_person(
    client,
    app_ctx,
    tmp_path,
    monkeypatch,
):
    """One library-wide batch, split into what finished alone and what a person must finish.

    This is the whole point of the worklist: the run is allowed to do everything it is
    permitted to do, and what remains is named per part with the route's OWN reason, so the
    person is routed rather than left to guess which provider page to open.
    """
    store, _ = _mount_completion_authority(app_ctx, tmp_path)
    monkeypatch.setenv("STOCKROOM_CAPTURE_DIR", str(tmp_path / "Capture State"))
    _write_completable_part(app_ctx, "lm317", "LM317")
    from stockroom.capture.runner import write_durable_capture_report

    reference = client.post(
        "/api/library/capture/run",
        json={"part_ids": ["tps62130", "lm317"]},
    ).json()
    batch_id = reference["workflow_batch_id"]
    item_ids = _item_ids_by_part(store, batch_id)
    write_durable_capture_report(
        item_ids["tps62130"],
        _batch_report("tps62130", status="completed"),
    )
    write_durable_capture_report(
        item_ids["lm317"],
        _batch_report(
            "lm317",
            status="improved",
            remaining=["kicad_model", "altium_symbol"],
            provider_outcomes=[
                {
                    "route_id": "ultralibrarian:ultralibrarian",
                    "provider_key": "ultralibrarian",
                    "author_key": "ultralibrarian",
                    "label": "Ultra Librarian",
                    "status": "requires-human",
                    "attempted": True,
                    "retained": 0,
                    "activated": False,
                    "reason": "no Ultra Librarian sign-in is saved on this PC",
                },
                {
                    "route_id": "digikey:samacsys",
                    "provider_key": "digikey",
                    "author_key": "samacsys",
                    "label": "DigiKey - SamacSys",
                    "status": "requires-human",
                    "attempted": True,
                    "retained": 0,
                    "activated": False,
                    "reason": "SamacSys needs a person-driven download choice",
                },
            ],
        ),
    )

    body = client.get(f"/api/library/capture/batches/{batch_id}/worklist")

    assert body.status_code == 200, body.text
    projected = body.json()
    assert projected["workflow_batch_id"] == batch_id
    assert projected["total_items"] == 2
    assert projected["pending_items"] == 0
    assert projected["worklist_unit"] == "components"
    assert [row["part_id"] for row in projected["unattended"]] == ["tps62130"]
    # Exactly one actionable row per component even when several provider routes need a person.
    # Get Files exhausts all of them; route rows would rerun this component repeatedly.
    assert projected["worklist_total"] == 1
    assert projected["worklist"] == [
        {
            "part_id": "lm317",
            "mpn": "LM317",
            "display_name": "LM317",
            "route_id": "ultralibrarian:ultralibrarian",
            "provider_key": "ultralibrarian",
            "label": "Ultra Librarian + DigiKey - SamacSys",
            "status": "requires-human",
            "reason": (
                "Ultra Librarian: no Ultra Librarian sign-in is saved on this PC; "
                "DigiKey - SamacSys: SamacSys needs a person-driven download choice"
            ),
            "remaining": ["kicad_model", "altium_symbol"],
        }
    ]
    assert projected["stalled"] == []
    assert projected["unreadable"] == []


def test_batch_worklist_counts_an_unreported_item_as_pending_rather_than_finished(
    client,
    app_ctx,
    tmp_path,
    monkeypatch,
):
    # A part whose report has not landed yet is neither done nor stuck, and saying either
    # would be the surface inventing a result the run never produced.
    store, _ = _mount_completion_authority(app_ctx, tmp_path)
    monkeypatch.setenv("STOCKROOM_CAPTURE_DIR", str(tmp_path / "Capture State"))
    reference = client.post(
        "/api/library/capture/run",
        json={"part_ids": ["tps62130"]},
    ).json()
    assert store.list_items(reference["workflow_batch_id"])

    projected = client.get(
        f"/api/library/capture/batches/{reference['workflow_batch_id']}/worklist"
    ).json()

    assert projected["pending_items"] == 1
    assert projected["unattended"] == []
    assert projected["worklist"] == []


def test_batch_worklist_reports_a_finished_part_no_route_can_help_apart_from_the_worklist(
    client,
    app_ctx,
    tmp_path,
    monkeypatch,
):
    store, _ = _mount_completion_authority(app_ctx, tmp_path)
    monkeypatch.setenv("STOCKROOM_CAPTURE_DIR", str(tmp_path / "Capture State"))
    from stockroom.capture.runner import write_durable_capture_report

    reference = client.post(
        "/api/library/capture/run",
        json={"part_ids": ["tps62130"]},
    ).json()
    batch_id = reference["workflow_batch_id"]
    write_durable_capture_report(
        _item_ids_by_part(store, batch_id)["tps62130"],
        _batch_report(
            "tps62130",
            status="unchanged",
            remaining=["kicad_model"],
            notes=["no exact model exists for this package"],
        ),
    )

    projected = client.get(f"/api/library/capture/batches/{batch_id}/worklist").json()

    assert projected["worklist"] == []
    assert projected["unattended"] == []
    assert projected["stalled"] == [
        {
            "part_id": "tps62130",
            "mpn": "TPS62130",
            "display_name": "TPS62130",
            "status": "unchanged",
            "reason": "no exact model exists for this package",
            "remaining": ["kicad_model"],
        }
    ]


def test_batch_worklist_rejects_an_invalid_reference_and_needs_a_token(client, anon_client):
    assert client.get("/api/library/capture/batches/not a reference/worklist").status_code == 400
    assert anon_client.get("/api/library/capture/batches/batch-1/worklist").status_code == 401


@pytest.mark.parametrize(
    ("command", "expected_status"),
    [
        ({"part_ids": ["tps62130", "tps62130"]}, 400),
        ({"part_ids": ["tps62130", "does-not-exist"], "limit": 1}, 404),
        ({"part_ids": []}, 400),
        ({"part_ids": "tps62130"}, 400),
        ({"part_ids": ["tps62130"], "limit": True}, 400),
        ({"part_ids": ["tps62130"], "limit": 0}, 400),
        ({"part_ids": ["tps62130"], "limit": 1_001}, 400),
        ({"part_ids": ["tps62130"], "limit": "1"}, 400),
        ({"part_ids": ["tps62130"], "limti": 1}, 400),
        ({"part_ids": ["mystery"]}, 422),
    ],
)
def test_invalid_durable_completion_commands_never_submit_or_launch_legacy_work(
    client,
    app_ctx,
    tmp_path,
    monkeypatch,
    command,
    expected_status,
):
    store, authority = _mount_completion_authority(app_ctx, tmp_path)
    monkeypatch.setattr(
        app_ctx.jobs,
        "submit_cancellable",
        lambda *_args, **_kwargs: pytest.fail("invalid durable command launched a legacy job"),
    )

    response = client.post("/api/library/completion/run", json=command)

    assert response.status_code == expected_status
    assert authority.submissions == []
    assert store.count_batches() == 0


def test_mounted_but_unavailable_completion_returns_503_without_legacy_fallback(
    client,
    app_ctx,
    tmp_path,
    monkeypatch,
):
    store, authority = _mount_completion_authority(
        app_ctx,
        tmp_path,
        submit_error=WorkflowCoordinatorLifecycleError(
            "workflow coordinator is not accepting API requests"
        ),
    )
    monkeypatch.setattr(
        app_ctx.jobs,
        "submit_cancellable",
        lambda *_args, **_kwargs: pytest.fail("stale coordinator fell back to legacy work"),
    )

    response = client.post(
        "/api/library/completion/run",
        json={"part_ids": ["tps62130"]},
    )

    assert response.status_code == 503
    assert "not accepting" in response.json()["detail"]
    assert len(authority.submissions) == 1
    assert store.count_batches() == 0


def test_non_object_completion_body_is_rejected_before_any_work(
    client,
    app_ctx,
    tmp_path,
    monkeypatch,
):
    store, authority = _mount_completion_authority(app_ctx, tmp_path)
    monkeypatch.setattr(
        app_ctx.jobs,
        "submit_cancellable",
        lambda *_args, **_kwargs: pytest.fail("invalid body launched legacy work"),
    )

    response = client.post("/api/library/completion/run", json=["tps62130"])

    assert response.status_code == 422
    assert authority.submissions == []
    assert store.count_batches() == 0


def test_durable_completion_rejects_more_than_one_thousand_requested_ids(
    client,
    app_ctx,
    tmp_path,
    monkeypatch,
):
    store, authority = _mount_completion_authority(app_ctx, tmp_path)
    monkeypatch.setattr(
        app_ctx.jobs,
        "submit_cancellable",
        lambda *_args, **_kwargs: pytest.fail("oversized batch launched legacy work"),
    )

    response = client.post(
        "/api/library/completion/run",
        json={"part_ids": [f"part-{index}" for index in range(1_001)]},
    )

    assert response.status_code == 400
    assert authority.submissions == []
    assert store.count_batches() == 0


def test_a_run_needs_a_token(anon_client):
    assert anon_client.post("/api/library/completion/run", json={}).status_code == 401


# --- stopping ------------------------------------------------------------------------------


def test_stopping_an_unknown_job_is_a_404_not_a_silent_success(client):
    # A stop that quietly succeeds against a job that does not exist is a lie the UI would
    # render as "stopping...", forever.
    assert client.post("/api/jobs/does-not-exist/stop").status_code == 404


def test_stop_marks_a_real_job(client, app_ctx):
    import threading

    gate = threading.Event()

    def work(progress, should_stop):
        gate.wait(5)
        return {"stopped": should_stop()}

    job_id = app_ctx.jobs.submit_cancellable(work)
    body = client.post(f"/api/jobs/{job_id}/stop").json()
    assert body == {"job_id": job_id, "stopping": True}
    gate.set()
    assert [p for k, p in _sse(client, job_id) if k == "result"][0]["result"] == {"stopped": True}


def test_stop_needs_a_token(anon_client, app_ctx):
    job_id = app_ctx.jobs.submit_cancellable(lambda progress, should_stop: None)
    assert anon_client.post(f"/api/jobs/{job_id}/stop").status_code == 401


# --- the wiring layer's own promises ---------------------------------------------------------


def test_real_run_never_registers_partial_lcsc_cad_as_an_active_source(app_ctx):
    """Distributor identity is not authority for converted one-tool CAD."""
    from stockroom.capture.pacing import PacedSource
    from stockroom.capture.runner import build_sources

    sources = build_sources(app_ctx)
    assert [source.key for source in sources] == ["verified-cache"]
    assert not any(isinstance(source, PacedSource) for source in sources)


def test_a_single_part_run_is_not_rate_limited(app_ctx):
    # Making one part wait behind a library-wide limiter would be a pointless delay.
    from stockroom.capture.pacing import PacedSource
    from stockroom.capture.runner import build_sources

    assert not any(isinstance(s, PacedSource) for s in build_sources(app_ctx, paced=False))


@pytest.mark.parametrize(
    "key",
    [
        "kicad_symbol",
        "kicad_footprint",
        "kicad_model",
        "altium_symbol",
        "altium_footprint",
    ],
)
def test_the_registered_source_requires_the_complete_dual_eda_set(app_ctx, key):
    from stockroom.capture.runner import build_sources

    provided = {r.value for s in build_sources(app_ctx) for r in s.provides()}
    assert key in provided


def test_a_person_can_finish_the_open_route_or_skip_the_part_from_stockrooms_own_window(client):
    """The Finish / Skip route, against the SAME registry `run_guided_capture` publishes into.

    De-automation removed the provider HUD, so these two statements of the person's own intent
    have nowhere to live but Stockroom's window. Nothing here touches a provider page.
    """

    from stockroom.capture.intent import PersonCaptureIntent, person_capture_intent

    intent = PersonCaptureIntent()
    with person_capture_intent("tps62130", intent):
        finished = client.post(
            "/api/library/capture/parts/tps62130/intent",
            json={"action": "finish-route"},
        )
        assert finished.status_code == 200
        assert finished.json() == {
            "part_id": "tps62130",
            "action": "finish-route",
            "accepted": True,
        }
        # The open route takes the answer, and finishing never stops the part.
        assert intent.take_route_finish() is True
        assert intent.part_skipped() is False

        skipped = client.post(
            "/api/library/capture/parts/tps62130/intent",
            json={"action": "skip-part"},
        )
        assert skipped.status_code == 200
        assert intent.part_skipped() is True


def test_a_person_driven_signal_for_a_component_with_no_running_capture_is_refused(client):
    # Remembering it would silently end the next run the person started.
    response = client.post(
        "/api/library/capture/parts/tps62130/intent",
        json={"action": "finish-route"},
    )

    assert response.status_code == 409


@pytest.mark.parametrize(
    ("part_id", "body", "expected_status"),
    [
        ("tps62130", {"action": "finish-everything"}, 400),
        ("tps62130", {}, 400),
        ("tps62130", {"action": "skip-part", "vendor": "digikey"}, 400),
        ("not a part id", {"action": "skip-part"}, 400),
    ],
)
def test_an_invalid_person_driven_signal_is_refused(client, part_id, body, expected_status):
    response = client.post(
        f"/api/library/capture/parts/{part_id}/intent",
        json=body,
    )

    assert response.status_code == expected_status


def test_a_person_driven_signal_needs_a_token(anon_client):
    response = anon_client.post(
        "/api/library/capture/parts/tps62130/intent",
        json={"action": "skip-part"},
    )

    assert response.status_code == 401
