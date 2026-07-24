"""End-to-end wiring: one authed flow walks the read + mutate + job surfaces to prove
every router is mounted, token-guarded, and consistent with no engine re-implementation
(spec sections 2.1, 4). The KiCad-config write against real %APPDATA%\\kicad\\10.0\\ is
the one Windows-verified seam (Task 19 acceptance bar)."""

from __future__ import annotations

import pytest


def test_full_flow_over_every_router(client):
    # system + read surface (before any mutation)
    info = client.get("/api/system/info").json()
    assert info["active_profile"] == "Main"
    assert info["part_count"] == 2
    assert client.get("/api/library/parts").json()["count"] == 2
    assert client.get("/api/library/facets").json()["by_category"]["ICs"] == 2
    assert client.get("/api/library/parts/tps62130").json()["mpn"] == "TPS62130"

    # mutations through the gate-intact engine, read-after-write consistent
    edited = client.patch("/api/library/parts/mystery",
                          json={"field": "manufacturer", "value": "X"})
    assert edited.status_code == 200 and edited.json()["manufacturer"] == "X"
    moved = client.post("/api/library/parts/tps62130/move", json={"category": "Modules"})
    assert moved.status_code == 200 and moved.json()["category"] == "Modules"

    # previews router mounted (kicad-cli-free: an absent part is a clean 404)
    assert client.get("/api/previews/symbol/nope.svg").status_code == 404

    # sync + doctor: no network, first-class states, not 500s
    assert client.post("/api/sync").json()["state"] == "no_remote"
    assert "fixable" in client.get("/api/doctor/scan").json()

    # profiles: create -> activate -> active-delete guard -> delete a non-active one
    assert client.post("/api/profiles", json={"name": "P2"}).status_code == 200
    assert client.post("/api/profiles/P2/activate").json()["active"] == "P2"
    assert client.delete("/api/profiles/P2").status_code == 400  # cannot delete active
    assert client.post("/api/profiles/Main/activate").json()["active"] == "Main"
    assert client.delete("/api/profiles/P2").status_code == 204  # now non-active


def test_every_router_is_mounted_and_token_guarded(anon_client):
    # /api/health is the only open route; every other router is mounted AND rejects a
    # request without the per-launch token (401), so a hostile local process cannot
    # drive the library (spec section 2.2, defense in depth).
    assert anon_client.get("/api/health").status_code == 200
    guarded = [
        ("get", "/api/system/info", None),
        ("get", "/api/library/parts", None),
        ("get", "/api/previews/symbol/x.svg", None),
        ("post", "/api/ingest/inspect", {"paths": [], "lcsc_ids": []}),
        ("post", "/api/enrich/part", {}),
        ("get", "/api/profiles", None),
        ("get", "/api/sync/status", None),
        ("get", "/api/doctor/scan", None),
        ("get", "/api/update/check", None),
    ]
    for method, path, body in guarded:
        fn = getattr(anon_client, method)
        resp = fn(path, json=body) if body is not None else fn(path)
        assert resp.status_code == 401, f"{method} {path} -> {resp.status_code}, want 401"


@pytest.mark.windows_only
def test_kicad_config_write_end_to_end():
    # Owner runs on Windows against real %APPDATA%\kicad\10.0\ per the acceptance bar:
    # SR_LIB + SR- rows land, the (type "Table") row is untouched, restart_needed is
    # reported, a part is usable in a real project. Skipped everywhere else.
    ...
