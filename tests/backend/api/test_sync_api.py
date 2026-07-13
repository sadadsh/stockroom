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
