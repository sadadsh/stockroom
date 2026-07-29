from __future__ import annotations

import json
from types import SimpleNamespace

from stockroom.api.routers.sync import _working_copy_status
from stockroom.vcs.repo import GitRepo


def test_sync_status_reads_without_network(client):
    r = client.get("/api/sync/status")
    assert r.status_code == 200
    body = r.json()
    assert "has_remote" in body
    assert "current_branch" in body


def test_handed_off_worker_reads_the_host_checkout_inventory(client, app_ctx, tmp_path):
    inventory = {
        "state": "complete",
        "rival_count": 1,
        "checkouts": [
            {
                "path": "D:\\Workspace\\Projects\\Stockroom",
                "classification": "rival",
                "revision": "abc123",
                "current": True,
                "tracked_dirty": False,
                "active_library": False,
            }
        ],
    }
    path = tmp_path / "checkout-inventory.json"
    path.write_text(json.dumps(inventory), encoding="utf-8")
    app_ctx.checkout_inventory_path = path

    response = client.get("/api/sync/status")

    assert response.status_code == 200
    assert response.json()["checkout_inventory"] == inventory


def test_sync_no_remote_is_a_first_class_state(client):
    # the fixture repo has no remote, so sync returns NO_REMOTE at 200, not a 500
    r = client.post("/api/sync")
    assert r.status_code == 200
    assert r.json()["state"] == "no_remote"


def test_sync_refreshes_derivations_then_rebuilds_both_indexes_on_pull(
    client, app_ctx, monkeypatch
):
    # A pull can bring in part records AND project registrations (both committed into
    # this same library repo), so the sync route must refresh BOTH derived indexes.
    # Load-bearing: drop the rebuild_project_index() call and this goes red.
    class _Pulled:
        state, pulled, pushed, detail = "ok", True, False, ""

    monkeypatch.setattr(app_ctx.sync, "sync", lambda: _Pulled())
    calls: list[str] = []
    monkeypatch.setattr(app_ctx, "refresh_stale_derivations", lambda: calls.append("derive"))
    monkeypatch.setattr(app_ctx, "rebuild_index", lambda: calls.append("library"))
    monkeypatch.setattr(app_ctx, "rebuild_project_index", lambda: calls.append("project"))
    r = client.post("/api/sync")
    assert r.status_code == 200
    assert calls == ["derive", "library", "project"]


def test_working_copy_status_detects_two_checkouts_of_the_same_application_remote(
    tmp_path,
):
    origin = GitRepo(tmp_path / "origin")
    origin.init()
    tracked = origin.root / "README.md"
    tracked.write_text("stockroom\n", encoding="utf-8")
    origin.commit("initialize", [tracked])
    app_repo = GitRepo(tmp_path / "app")
    library_repo = GitRepo(tmp_path / "rival")
    app_repo.clone_from(origin.root)
    library_repo.clone_from(origin.root)

    status = _working_copy_status(
        SimpleNamespace(repo=library_repo, app_repo=app_repo)
    )

    assert status["mode"] == "rival_application_checkout"


def test_working_copy_status_recognizes_an_in_repo_library(tmp_path):
    repo = GitRepo(tmp_path / "app")
    repo.init()
    tracked = repo.root / "README.md"
    tracked.write_text("stockroom\n", encoding="utf-8")
    repo.commit("initialize", [tracked])
    libraries = repo.root / "libraries"
    libraries.mkdir()

    status = _working_copy_status(
        SimpleNamespace(repo=GitRepo(libraries), app_repo=repo)
    )

    assert status["mode"] == "embedded"
