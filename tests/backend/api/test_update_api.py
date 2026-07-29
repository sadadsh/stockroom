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
