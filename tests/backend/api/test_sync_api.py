from __future__ import annotations


def test_sync_status_reads_without_network(client):
    r = client.get("/api/sync/status")
    assert r.status_code == 200
    body = r.json()
    assert "has_remote" in body
    assert "current_branch" in body


def test_sync_no_remote_is_a_first_class_state(client):
    # the fixture repo has no remote, so sync returns NO_REMOTE at 200, not a 500
    r = client.post("/api/sync")
    assert r.status_code == 200
    assert r.json()["state"] == "no_remote"


def test_sync_rebuilds_both_derived_indexes_on_pull(client, app_ctx, monkeypatch):
    # A pull can bring in part records AND project registrations (both committed into
    # this same library repo), so the sync route must refresh BOTH derived indexes.
    # Load-bearing: drop the rebuild_project_index() call and this goes red.
    class _Pulled:
        state, pulled, pushed, detail = "ok", True, False, ""

    monkeypatch.setattr(app_ctx.sync, "sync", lambda: _Pulled())
    calls: list[str] = []
    monkeypatch.setattr(app_ctx, "rebuild_index", lambda: calls.append("library"))
    monkeypatch.setattr(app_ctx, "rebuild_project_index", lambda: calls.append("project"))
    r = client.post("/api/sync")
    assert r.status_code == 200
    assert "library" in calls and "project" in calls
