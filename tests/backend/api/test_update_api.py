import json

from stockroom.api.routers.update import _frontend_revision
from stockroom.api.updater import UpdateState


def test_check_explains_an_unmanaged_installation(client, app_ctx):
    app_ctx.app_repo = None
    frontend_revision = _frontend_revision()
    assert frontend_revision

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
        "frontend_revision": frontend_revision,
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
        activated = False

        def status(self):
            return expected

        def activate_ready(self):
            self.activated = True
            return True

    convergence = _Convergence()
    app_ctx.update_convergence = convergence

    response = client.get("/api/update/check")

    assert response.status_code == 200
    assert response.json() == {**expected, "frontend_revision": _frontend_revision()}

    apply = client.post("/api/update/apply")

    assert apply.status_code == 200
    assert apply.json()["state"] == "updating"
    assert apply.json()["updated"] is False
    assert apply.json()["restart_requested"] is False
    assert apply.json()["seamless_handoff_requested"] is True
    assert convergence.activated is True


def test_store_managed_installation_refuses_direct_update_activation(client, app_ctx):
    class _StoreConvergence:
        activated = False

        def status(self):
            return {
                "state": "store_managed",
                "channel": "microsoft-store",
                "store_uri": "https://apps.microsoft.com/detail/9NQ6HP17PH4H",
                "update_available": False,
            }

        def activate_ready(self):
            self.activated = True
            return True

    convergence = _StoreConvergence()
    app_ctx.update_convergence = convergence

    checked = client.get("/api/update/check")
    applied = client.post("/api/update/apply")

    assert checked.status_code == 200
    assert checked.json()["channel"] == "microsoft-store"
    assert applied.status_code == 409
    assert applied.json() == {
        "detail": "Microsoft Store manages installation and updates.",
        "state": "store_managed",
        "store_uri": "https://apps.microsoft.com/detail/9NQ6HP17PH4H",
        "updated": False,
    }
    assert convergence.activated is False


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
    assert response.json() == {**expected, "frontend_revision": _frontend_revision()}

    apply = client.post("/api/update/apply")

    assert apply.status_code == 200
    assert apply.json()["updated"] is False
    assert apply.json()["restart_requested"] is False
    assert "persistent window host" in apply.json()["detail"]
