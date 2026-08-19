from __future__ import annotations

import json

import httpx

from stockroom.api.app import create_app
from stockroom.host.run import run_windowed
from stockroom.store.ui_session import (
    MAX_DRAFT_BYTES,
    MAX_SESSION_BYTES,
    default_snapshot,
    draft_directory,
    save_snapshot,
    snapshot_path,
)


def _draft_body(value: str = "STM32G474RET6") -> dict:
    network_input = {"kind": "mpn", "value": value}
    return {
        "network_input": network_input,
        "review": {
            "lookup_input": network_input,
            "enrichment_result": None,
            "candidates": [],
        },
    }


def test_ui_session_api_is_token_protected_and_returns_a_canonical_default(
    client,
    anon_client,
) -> None:
    assert anon_client.get("/api/ui-session").status_code == 401
    response = client.get("/api/ui-session")
    assert response.status_code == 200
    assert response.json() == default_snapshot()


def test_ui_session_put_round_trips_the_assets_route(client) -> None:
    snapshot = default_snapshot()
    snapshot["route"] = "assets"

    response = client.put("/api/ui-session", json=snapshot)

    assert response.status_code == 200
    assert client.get("/api/ui-session").json()["route"] == "assets"


def test_ui_session_put_persists_all_capability_state(client) -> None:
    snapshot = default_snapshot()
    snapshot.update(
        {
            "route": "stm",
            "detail_tab": "handoff",
            "settings_group": "maintenance",
            "event_sequence": 5004,
        }
    )
    snapshot["selected_ids"].update(
        {
            "component": "tps62130",
            "stm_part": "STM32G474RET6",
            "stm_pin": "PA0",
            "workflow_batch": "capture-tps62130",
            "workflow_item": "ultra-librarian",
        }
    )
    snapshot["search_filters"].update(
        {
            "query": "100 nF",
            "category": "Capacitors",
            "in_stock": True,
            "options": [{"key": "Package", "values": ["0402", "0603"]}],
            "ranges": [{"key": "Voltage", "min": 16, "max": 50}],
        }
    )
    snapshot["search_sort"] = {
        "kind": "spec",
        "key": "Capacitance",
        "numeric": True,
        "direction": "desc",
    }

    response = client.put("/api/ui-session", json=snapshot)

    assert response.status_code == 200
    assert client.get("/api/ui-session").json() == response.json()


def test_ui_session_rejects_unknown_oversize_and_secret_input_without_reflection(
    client,
) -> None:
    hostile = default_snapshot()
    secret = "github_pat_do_not_ever_reflect_123456789"
    hostile["github_token"] = secret
    response = client.put("/api/ui-session", json=hostile)

    assert response.status_code == 400
    assert secret not in response.text
    assert not snapshot_path().exists()

    response = client.put(
        "/api/ui-session",
        content=b"{" + b"x" * MAX_SESSION_BYTES + b"}",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413


def test_draft_and_snapshot_survive_a_new_app_origin(client, app_ctx) -> None:
    created = client.post("/api/intake-drafts", json=_draft_body())
    assert created.status_code == 200
    first = created.json()

    updated = client.put(
        f"/api/intake-drafts/{first['draft_id']}",
        json={**_draft_body("STM32G474VET6"), "revision": first["revision"]},
    )
    assert updated.status_code == 200
    second = updated.json()

    snapshot = default_snapshot()
    snapshot["route"] = "components"
    snapshot["open_surface"] = "add_part"
    snapshot["intake_draft_ref"] = {
        "draft_id": second["draft_id"],
        "revision": second["revision"],
    }
    snapshot["event_sequence"] = 41
    assert client.put("/api/ui-session", json=snapshot).status_code == 200

    # A new ASGI app stands in for a host restart/new ephemeral loopback origin:
    # nothing process-local or origin-scoped is needed to recover either document.
    from fastapi.testclient import TestClient

    with TestClient(
        create_app(app_ctx),
        base_url="http://different-origin",
        raise_server_exceptions=False,
        headers={"X-Stockroom-Token": "testtoken"},
    ) as restarted:
        assert restarted.get("/api/ui-session").json() == snapshot
        restored = restarted.get(
            f"/api/intake-drafts/{second['draft_id']}",
            params={"revision": second["revision"]},
        )
        assert restored.status_code == 200
        assert restored.json()["network_input"]["value"] == "STM32G474VET6"


def test_draft_revision_conflict_and_duplicate_json_fail_closed(client) -> None:
    first = client.post("/api/intake-drafts", json=_draft_body()).json()
    response = client.put(
        f"/api/intake-drafts/{first['draft_id']}",
        json={**_draft_body(), "revision": first["revision"] + 1},
    )
    assert response.status_code == 409

    payload = json.dumps(default_snapshot()).removesuffix("}") + ',"route":"settings"}'
    response = client.put(
        "/api/ui-session",
        content=payload,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400


def test_draft_api_rejects_unknown_oversize_and_secret_input_without_reflection(
    client,
) -> None:
    secret = "github_pat_never_reflect_this_123456789"
    hostile = _draft_body()
    hostile["github_token"] = secret
    response = client.post("/api/intake-drafts", json=hostile)

    assert response.status_code == 400
    assert secret not in response.text
    assert not draft_directory().exists()

    response = client.post(
        "/api/intake-drafts",
        content=b"{" + b"x" * MAX_DRAFT_BYTES + b"}",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert not draft_directory().exists()


def test_served_index_injects_snapshot_synchronously_and_corruption_fails_closed(
    app_ctx,
) -> None:
    snapshot = default_snapshot()
    snapshot["route"] = "settings"
    snapshot["settings_group"] = "sources"
    save_snapshot(snapshot)
    secret = "github_pat_never_reach_the_renderer_123456789"
    seen: dict[str, str] = {}

    def inspect_index(base_url: str, _token: str) -> None:
        seen["valid"] = httpx.get(f"{base_url}/").text
        snapshot_path().write_text(
            '{"github_token":"' + secret + '"}',
            encoding="utf-8",
        )
        seen["corrupt"] = httpx.get(f"{base_url}/").text

    run_windowed(ctx=app_ctx, open_window=inspect_index)

    assert "window.__STOCKROOM_SESSION__" in seen["valid"]
    assert '"route":"settings"' in seen["valid"]
    assert '"settings_group":"sources"' in seen["valid"]
    assert secret not in seen["corrupt"]
    assert '"route":"components"' in seen["corrupt"]
