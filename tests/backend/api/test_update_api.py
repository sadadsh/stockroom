import json

from stockroom.api.updater import UpdateState


def test_check_explains_an_unmanaged_installation(client, app_ctx):
    app_ctx.app_repo = None

    response = client.get("/api/update/check")

    assert response.status_code == 200
    assert response.json() == {
        "update_available": False,
        "state": UpdateState.NO_REMOTE,
        "detail": "this installation is not managed by an application checkout",
        "current_revision": "",
        "target_revision": "",
        "channel": "unmanaged",
        "automatic_on_launch": False,
        "check_interval_seconds": 120,
    }


def test_apply_refuses_an_unmanaged_installation_without_requesting_restart(client, app_ctx):
    app_ctx.app_repo = None

    response = client.post("/api/update/apply")

    assert response.status_code == 200
    assert response.json() == {
        "state": UpdateState.NO_REMOTE,
        "updated": False,
        "detail": "no app repo available",
        "restart_requested": False,
    }


def test_check_uses_the_hosts_observable_automatic_convergence_state(client, app_ctx):
    expected = {
        "update_available": True,
        "state": "update_available",
        "current_revision": "111111111111",
        "target_revision": "222222222222",
        "convergence_phase": "applying",
        "automatic_apply": True,
    }

    class _Convergence:
        def status(self):
            return expected

    app_ctx.update_convergence = _Convergence()

    response = client.get("/api/update/check")

    assert response.status_code == 200
    assert response.json() == expected

    apply = client.post("/api/update/apply")

    assert apply.status_code == 200
    assert apply.json()["state"] == UpdateState.BLOCKED
    assert apply.json()["updated"] is False
    assert apply.json()["restart_requested"] is False
    assert "persistent window host" in apply.json()["detail"]


def test_handed_off_worker_reads_the_host_convergence_status_file(client, app_ctx, tmp_path):
    expected = {
        "update_available": False,
        "state": "up_to_date",
        "current_revision": "333333333333",
        "target_revision": "333333333333",
        "convergence_phase": "current",
        "automatic_apply": True,
    }
    status_path = tmp_path / "convergence.json"
    status_path.write_text(json.dumps(expected), encoding="utf-8")
    app_ctx.convergence_status_path = status_path

    response = client.get("/api/update/check")

    assert response.status_code == 200
    assert response.json() == expected

    apply = client.post("/api/update/apply")

    assert apply.status_code == 200
    assert apply.json()["updated"] is False
    assert apply.json()["restart_requested"] is False
    assert "persistent window host" in apply.json()["detail"]
