from __future__ import annotations

import json
from threading import Event, Thread

from stockroom.catalog.build import run_catalog_build
from stockroom.model.part import AssetRef
from stockroom.store.machine_config import MachineConfig, config_dir


def test_catalog_build_status_is_authenticated_and_persists_restart_safe_pending(
    client, anon_client, app_ctx
):
    app_ctx.config.primary_eda = "kicad"

    denied = anon_client.get("/api/catalog-build/status")
    assert denied.status_code == 401

    response = client.get("/api/catalog-build/status")
    assert response.status_code == 200
    status = response.json()
    assert status["state"] == "pending"
    assert status["primary_eda"] == "kicad"
    assert status["pending_count"] == 1
    assert [part["id"] for part in status["pending_parts"]] == ["tps62130"]
    assert status["desired_identity"]
    assert status["completed_identity"] == ""

    persisted = MachineConfig.load(config_dir() / "config.json")
    assert persisted.catalog_build["profiles"]
    scope = next(iter(persisted.catalog_build["profiles"].values()))
    assert scope["kicad"]["desired"]["tps62130"] == status["pending_parts"][0]["identity"]
    assert scope["kicad"]["completed"] == {}


def test_kicad_build_requires_confirmation_coalesces_once_and_survives_restart(
    client, app_ctx, monkeypatch
):
    app_ctx.config.primary_eda = "kicad"
    calls = []

    class Wiring:
        error = ""
        skipped = ""

    def wire_once():
        calls.append("wire")
        app_ctx.last_wiring = Wiring()

    monkeypatch.setattr(app_ctx, "rewire_kicad", wire_once)

    rejected = client.post("/api/catalog-build", json={"confirmed": False})
    assert rejected.status_code == 422
    assert calls == []

    built = client.post("/api/catalog-build", json={"confirmed": True})
    assert built.status_code == 200
    result = built.json()
    assert calls == ["wire"]
    assert result["status"] == "completed"
    assert result["attempted"] == 1
    assert result["succeeded"] == 1
    assert result["failed"] == 0
    assert result["items"] == [
        {"part_id": "tps62130", "status": "current", "detail": "KiCad catalog wiring is current."}
    ]

    current = client.get("/api/catalog-build/status").json()
    assert current["state"] == "current"
    assert current["pending_count"] == 0
    assert current["completed_identity"] == current["desired_identity"]
    assert current["history"][0]["succeeded"] == 1

    config_path = config_dir() / "config.json"
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["catalog_build"]["profiles"]

    app_ctx.config = MachineConfig.load(config_path)
    restarted = client.get("/api/catalog-build/status").json()
    assert restarted["state"] == "current"
    assert restarted["completed_identity"] == restarted["desired_identity"]

    record = app_ctx.ops.load_record("tps62130")
    record.description = f"{record.description} changed"
    (app_ctx.profile.library.parts_dir / "tps62130.json").write_text(
        record.dumps(), encoding="utf-8"
    )
    changed = client.get("/api/catalog-build/status").json()
    assert changed["state"] == "pending"
    assert changed["desired_identity"] != changed["completed_identity"]


def test_status_reports_building_while_confirmed_batch_runs(client, app_ctx, monkeypatch):
    app_ctx.config.primary_eda = "kicad"
    client.get("/api/catalog-build/status")
    entered = Event()
    release = Event()
    results = []

    class Wiring:
        error = ""
        skipped = ""

    def blocked_wire():
        entered.set()
        release.wait(timeout=2)
        app_ctx.last_wiring = Wiring()

    monkeypatch.setattr(app_ctx, "rewire_kicad", blocked_wire)
    thread = Thread(target=lambda: results.append(run_catalog_build(app_ctx)))
    thread.start()
    try:
        assert entered.wait(timeout=1)
        assert client.get("/api/catalog-build/status").json()["state"] == "building"
    finally:
        release.set()
        thread.join(timeout=2)

    assert not thread.is_alive()
    assert results[0]["status"] == "completed"


def test_altium_build_preserves_successes_and_exact_failures(
    client, app_ctx, monkeypatch
):
    app_ctx.config.primary_eda = "altium"
    parts_dir = app_ctx.profile.library.parts_dir
    for part_id in ("tps62130", "mystery"):
        record = app_ctx.ops.load_record(part_id)
        record.description = record.description or "a part"
        record.mpn = record.mpn or part_id.upper()
        record.manufacturer = record.manufacturer or "TI"
        kicad = record.assets_for("kicad")
        kicad.model = kicad.model or AssetRef(file="models/x.step")
        altium = record.assets_for("altium")
        altium.symbol = kicad.symbol
        altium.footprint = kicad.footprint
        (parts_dir / f"{part_id}.json").write_text(record.dumps(), encoding="utf-8")
    app_ctx.rebuild_index()

    embed_calls = []
    regenerate_calls = []

    def embed(part_ids=None, **_kwargs):
        embed_calls.append(list(part_ids or []))
        return {
            "embedded": 1,
            "failed": 1,
            "attempted": 2,
            "skipped": [],
            "results": [
                {"part_id": "tps62130", "status": "ok", "detail": "verified"},
                {"part_id": "mystery", "status": "failed", "detail": "PcbLib readback failed"},
            ],
        }

    def regenerate():
        regenerate_calls.append("regenerate")
        return {"emitted": 1, "skipped": ["mystery"], "dblib": "x", "db": "y"}

    monkeypatch.setattr(app_ctx.ops, "embed_altium_models", embed)
    monkeypatch.setattr(app_ctx.ops, "regenerate_altium_dblib", regenerate)
    monkeypatch.setattr(app_ctx, "auto_push", lambda: None)

    pending = client.get("/api/catalog-build/status").json()
    assert pending["blocked_parts"] == [], pending["blocked_parts"]
    assert [part["id"] for part in pending["pending_parts"]] == ["mystery", "tps62130"], pending

    result = client.post("/api/catalog-build", json={"confirmed": True}).json()
    assert embed_calls == [["mystery", "tps62130"]]
    assert regenerate_calls == ["regenerate"]
    assert result["status"] == "partial"
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert result["items"] == [
        {"part_id": "mystery", "status": "failed", "detail": "PcbLib readback failed"},
        {"part_id": "tps62130", "status": "current", "detail": "Altium catalog projection is current."},
    ]

    status = client.get("/api/catalog-build/status").json()
    assert status["state"] == "pending"
    assert [part["id"] for part in status["pending_parts"]] == ["mystery"]
    assert status["last_result"]["failed"] == 1
