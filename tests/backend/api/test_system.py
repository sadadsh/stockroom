from dataclasses import replace

from stockroom.service import WorkflowCoordinatorState, WorkflowCoordinatorStatus


def test_health_needs_no_token(anon_client):
    r = anon_client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_system_info_requires_a_token(anon_client):
    r = anon_client.get("/api/system/info")
    assert r.status_code == 401


def test_system_info_reports_active_profile_and_count(client):
    r = client.get("/api/system/info")
    assert r.status_code == 200
    body = r.json()
    assert body["active_profile"] == "Main"
    assert body["part_count"] == 2


def test_system_info_reports_kicad_cli_availability(client):
    # so the UI can honestly tell the user when previews/import are unavailable
    body = client.get("/api/system/info").json()
    assert isinstance(body["kicad_cli_available"], bool)
    assert "kicad_cli_path" in body


def test_workflow_coordinator_status_is_authenticated_and_honestly_unmounted(
    client,
    anon_client,
):
    assert anon_client.get("/api/system/workflow-coordinator").status_code == 401
    response = client.get("/api/system/workflow-coordinator")
    assert response.status_code == 503
    assert "not mounted" in response.json()["detail"].lower()


class _CoordinatorStatusStub:
    def __init__(self, status: WorkflowCoordinatorStatus):
        self._status = status

    def status(self) -> WorkflowCoordinatorStatus:
        return self._status


def _workflow_status() -> WorkflowCoordinatorStatus:
    return WorkflowCoordinatorStatus(
        state=WorkflowCoordinatorState.RUNNING,
        generation=7,
        worker_limit=4,
        in_flight=2,
        peak_in_flight=4,
        poll_round_count=11,
        poll_count=44,
        dispatch_count=31,
        idle_poll_count=13,
        recovered_claim_count=1,
        handler_error_count=2,
        unexpected_error_count=0,
        idle_round_count=3,
        current_backoff_seconds=0.25,
        minimum_worker_polls=11,
        maximum_worker_polls=11,
        started_at=100.0,
        last_activity_at=110.0,
        stopped_at=None,
        last_error_code=None,
        thread_alive=True,
    )


def test_workflow_coordinator_status_is_an_exact_payload_free_allowlist(client, app_ctx):
    secret = "secret-workflow-payload"
    owner_id = "secret-owner-id"
    app_ctx.workflow_coordinator = _CoordinatorStatusStub(_workflow_status())

    response = client.get(
        "/api/system/workflow-coordinator",
        headers={"X-Ignored-Workflow-Payload": secret},
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "state": "running",
        "generation": 7,
        "worker_limit": 4,
        "in_flight": 2,
        "peak_in_flight": 4,
        "poll_round_count": 11,
        "poll_count": 44,
        "dispatch_count": 31,
        "idle_poll_count": 13,
        "recovered_claim_count": 1,
        "handler_error_count": 2,
        "unexpected_error_count": 0,
        "idle_round_count": 3,
        "current_backoff_seconds": 0.25,
        "minimum_worker_polls": 11,
        "maximum_worker_polls": 11,
        "started_at": 100.0,
        "last_activity_at": 110.0,
        "stopped_at": None,
        "last_error_code": None,
        "thread_alive": True,
    }
    assert secret not in repr(body)
    assert owner_id not in repr(body)

    app_ctx.workflow_coordinator = _CoordinatorStatusStub(
        replace(
            _workflow_status(),
            state=WorkflowCoordinatorState.STALE,
            last_error_code="stale_generation",
            thread_alive=False,
        )
    )
    stale = client.get("/api/system/workflow-coordinator")
    assert stale.status_code == 200
    assert stale.json()["state"] == "stale"


def test_build_context_starts_without_kicad_cli(library_root, tmp_path, monkeypatch):
    # the regression the owner hit: no kicad-cli on PATH must NOT crash startup — the
    # app builds fine and degrades previews/import honestly.
    import stockroom.kicad.cli as cli_mod
    from stockroom.api.context import build_context
    from stockroom.store.machine_config import MachineConfig

    monkeypatch.setattr(cli_mod, "find_kicad_cli", lambda binary=None: None)
    kdir = tmp_path / "kc"
    kdir.mkdir()
    ctx = build_context(library_root, kicad_dir=kdir, config=MachineConfig(active_profile="Main"))
    assert ctx.cli.available is False
