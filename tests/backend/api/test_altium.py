import os
from pathlib import Path

ALTIUM_FIX = Path(__file__).parent.parent / "altium" / "fixtures"


def test_status_requires_token(anon_client):
    assert anon_client.get("/api/altium/status").status_code == 401


def test_odbc_status_requires_token(anon_client):
    assert anon_client.get("/api/altium/odbc-status").status_code == 401


def test_odbc_status_reports_the_driver_and_installer_and_an_honest_installed_flag(client):
    r = client.get("/api/altium/odbc-status")
    assert r.status_code == 200
    body = r.json()
    assert body["driver"] == "SQLite3 ODBC Driver"
    assert body["download_url"].endswith("sqliteodbc_w64.exe")
    # honest per-platform: a real bool on Windows (the registry can be read), null everywhere else
    if os.name == "nt":
        assert isinstance(body["installed"], bool)
    else:
        assert body["installed"] is None


def test_status_reports_active_profile_and_zero_ready(client):
    r = client.get("/api/altium/status")
    assert r.status_code == 200
    body = r.json()
    assert body["profile"] == "Main"  # per active profile
    assert body["total"] == 2  # the two fixture parts
    assert body["ready"] == 0  # neither has Altium assets yet
    assert body["dblib"].endswith("/altium/Stockroom.DbLib")
    ids = {row["id"] for row in body["rows"]}
    assert ids == {"tps62130", "mystery"}
    row = next(r for r in body["rows"] if r["id"] == "tps62130")
    assert row["ready"] is False and row["symbol"] == "" and row["footprint"] == ""


def test_regenerate_over_empty_is_ok(client):
    r = client.post("/api/altium/regenerate")
    assert r.status_code == 200
    body = r.json()
    assert body["emitted"] == 0
    assert "tps62130" in body["skipped"] and "mystery" in body["skipped"]
    assert body["dblib"].endswith("/altium/Stockroom.DbLib")


def test_attach_then_status_marks_ready(client):
    # attach the S1M sample assets to the (identity-complete) fixture part tps62130
    r = client.post(
        "/api/altium/parts/tps62130/attach",
        json={"paths": [str(ALTIUM_FIX / "sample.SchLib"), str(ALTIUM_FIX / "sample.PcbLib")]},
    )
    assert r.status_code == 200
    rec = r.json()
    assert rec["eda"]["altium"]["symbol"]["name"] and rec["eda"]["altium"]["footprint"]["name"]

    status = client.get("/api/altium/status").json()
    assert status["ready"] == 1
    row = next(x for x in status["rows"] if x["id"] == "tps62130")
    assert row["ready"] is True and row["symbol"] and row["footprint"]


def test_status_skips_a_bad_record_instead_of_404ing_the_surface(client, app_ctx):
    # a corrupt/unreadable JSON in parts_dir must not take down the whole Altium surface
    (app_ctx.profile.library.parts_dir / "broken.json").write_text("{ not json", encoding="utf-8")
    r = client.get("/api/altium/status")
    assert r.status_code == 200
    ids = {row["id"] for row in r.json()["rows"]}
    assert "broken" not in ids
    assert ids == {"tps62130", "mystery"}  # the two valid fixtures still shown


def test_attach_unknown_part_is_404(client):
    r = client.post("/api/altium/parts/nope/attach", json={"paths": [str(ALTIUM_FIX / "sample.IntLib")]})
    assert r.status_code == 404


def test_attach_without_paths_is_422(client):
    r = client.post("/api/altium/parts/tps62130/attach", json={"paths": []})
    assert r.status_code == 422


def test_status_resistor_value_keeps_ohm_unit(client, app_ctx):
    # FIX-07 (backend): the human-facing status modal shows a resistor's value WITH the Ω unit,
    # while the emitted DbLib keeps the schematic convention (no Ω) via row_for/derive_value.
    from stockroom.model.part import PartRecord

    rec = PartRecord(id="res1", display_name="5.05kΩ 0402", category="Resistors",
                     mpn="RES-5K05", specs={"Resistance": "5.05 kOhms"})
    (app_ctx.profile.library.parts_dir / "res1.json").write_text(rec.dumps(), encoding="utf-8")

    row = next(x for x in client.get("/api/altium/status").json()["rows"] if x["id"] == "res1")
    assert row["value"].endswith("Ω")
    assert row["value"] == "5.05kΩ"


def test_embed_capability_requires_token(anon_client):
    assert anon_client.get("/api/altium/embed-capability").status_code == 401


def test_embed_capability_explains_itself_on_a_machine_without_altium(client, monkeypatch):
    # A KiCad-only peer must get an EXPLAINED unavailable state, never a button that silently does
    # nothing. The requirement is registry data, so the reason comes from there rather than from a
    # string in the router.
    monkeypatch.setattr("stockroom.altium.driver.find_x2", lambda env=None: None)
    r = client.get("/api/altium/embed-capability")
    assert r.status_code == 200
    body = r.json()
    assert body["installed"] is False
    assert body["available"] is False
    assert body["requires_tool_installed"] is True
    assert "Altium installed" in body["reason"]
    assert body["binary"] == ""


def test_embed_capability_is_available_when_altium_is_installed_and_idle(client, monkeypatch, tmp_path):
    exe = tmp_path / "AD99" / "X2.EXE"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    monkeypatch.setattr("stockroom.altium.driver.find_x2", lambda env=None: exe)
    monkeypatch.setattr("stockroom.altium.driver.AltiumDriver.busy_titles", lambda self: [])
    body = client.get("/api/altium/embed-capability").json()
    assert body["installed"] is True and body["available"] is True
    assert body["binary"] == exe.as_posix()  # never str(Path): backslashes would break a consumer
    assert body["busy"] == ""


def test_embed_capability_reports_a_held_license_seat_rather_than_hanging_later(
    client, monkeypatch, tmp_path
):
    # A windowed Altium holds the single On-Demand seat, so a scripted run would wait forever.
    # Saying so up front is the alternative to discovering it via a run that never returns.
    exe = tmp_path / "AD99" / "X2.EXE"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    monkeypatch.setattr("stockroom.altium.driver.find_x2", lambda env=None: exe)
    monkeypatch.setattr(
        "stockroom.altium.driver.AltiumDriver.busy_titles", lambda self: ["Altium Designer"]
    )
    body = client.get("/api/altium/embed-capability").json()
    assert body["installed"] is True
    assert body["available"] is False
    assert body["busy"] == "Altium Designer"


def test_embed_model_requires_token(anon_client):
    assert anon_client.post("/api/altium/parts/tps62130/embed-model").status_code == 401


def test_embed_model_404s_an_unknown_part(client):
    assert client.post("/api/altium/parts/nope/embed-model").status_code == 404


def test_embed_model_400s_with_the_reason_when_the_part_cannot_take_one(client):
    # The fixture parts have no Altium footprint, and a 3D body lives inside the footprint's
    # .PcbLib, so this is a refusal WITH a reason rather than a silent no-op.
    r = client.post("/api/altium/parts/tps62130/embed-model")
    assert r.status_code == 400
    assert "no Altium footprint" in r.text


def test_embed_model_returns_the_verified_result_and_rebuilds_the_index(client, monkeypatch):
    # The route's own contract: it reports what `embed_altium_model` verified, and the index is
    # rebuilt so the surface the user reads stops showing the gap.
    calls = {}

    def fake_embed(part_id, *, replace=False, driver=None):
        calls["part_id"] = part_id
        calls["replace"] = replace
        return {"part_id": part_id, "status": "ok", "detail": "done", "embedded": 1,
                "payload_bytes": 65536, "orphaned": 0, "pcblib": f"{part_id}.PcbLib",
                "model": "models/x.step", "commit": "abc123"}

    ctx = client.app.state.ctx
    monkeypatch.setattr(ctx.ops, "embed_altium_model", fake_embed)
    r = client.post("/api/altium/parts/tps62130/embed-model", json={"replace": True})
    assert r.status_code == 200
    assert r.json()["payload_bytes"] == 65536
    assert calls == {"part_id": "tps62130", "replace": True}


def test_embed_model_defaults_replace_to_false(client, monkeypatch):
    # Default-off matters: a replace leaves a superseded payload in the container, so it must be
    # asked for rather than assumed.
    seen = {}
    ctx = client.app.state.ctx
    monkeypatch.setattr(
        ctx.ops,
        "embed_altium_model",
        lambda part_id, *, replace=False, driver=None: seen.setdefault("replace", replace) or {},
    )
    client.post("/api/altium/parts/tps62130/embed-model")
    assert seen["replace"] is False


def test_status_reports_whether_the_derived_data_source_is_built(client, app_ctx):
    """The .db is derived and no longer shared through git, so it can legitimately be absent on a
    fresh clone. The surface has to be able to say so instead of implying the library is broken."""
    body = client.get("/api/altium/status")
    assert body.status_code == 200, body.text
    assert "datasource_present" in body.json()

    db = app_ctx.profile.library.parts_dir.parent / "altium" / "stockroom-parts.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    db.unlink(missing_ok=True)
    assert client.get("/api/altium/status").json()["datasource_present"] is False

    # a GET must never rebuild it: reporting a gap is not the same as fixing one
    assert not db.exists()

    app_ctx.ops.ensure_altium_datasource()
    assert client.get("/api/altium/status").json()["datasource_present"] is True


# --- The bulk embed: one action for a whole library. ---------------------------------------------


def _drain_altium_job(client, job_id):
    """Consume a job's SSE stream, keeping the progress MESSAGES as well as the terminal payload.
    The enrich helper keeps only stage names, and here the message IS the contract: it has to name
    the part being embedded."""
    import json as _json

    messages: list[str] = []
    kind = None
    with client.stream("GET", f"/api/jobs/{job_id}/events") as s:
        for line in s.iter_lines():
            line = line.strip()
            if line.startswith("event:"):
                kind = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = _json.loads(line[len("data:"):].strip())
                if kind == "progress" and data.get("message"):
                    messages.append(data["message"])
                elif kind == "result":
                    return {"result": data["result"], "messages": messages}
    raise AssertionError("the job stream ended without a result")


def test_models_pending_requires_token(anon_client):
    assert anon_client.get("/api/altium/models-pending").status_code == 401


def test_embed_models_requires_token(anon_client):
    assert anon_client.post("/api/altium/embed-models", json={}).status_code == 401


def test_models_pending_reports_what_the_action_would_work_on(client, monkeypatch):
    ctx = client.app.state.ctx
    monkeypatch.setattr(ctx.ops, "altium_models_pending", lambda: ["a", "b"])
    body = client.get("/api/altium/models-pending").json()
    assert body == {"pending": ["a", "b"], "count": 2}


def test_embed_models_runs_as_a_job_and_reports_the_whole_run(client, monkeypatch):
    """The owner walks away from this one, so the report must carry every part's outcome - not
    just a count, and not just the first failure."""
    report = {
        "embedded": 2, "failed": 1, "attempted": 3, "skipped": ["kicad-only"],
        "results": [
            {"part_id": "a", "status": "ok"},
            {"part_id": "b", "status": "ok"},
            {"part_id": "c", "status": "failed", "detail": "Altium could not load c.step"},
        ],
    }
    seen = {}
    ctx = client.app.state.ctx

    def fake_bulk(part_ids=None, *, replace=False, on_progress=None):
        seen["part_ids"] = part_ids
        seen["replace"] = replace
        if on_progress:
            on_progress(1, 2, "a")
            on_progress(2, 2, "b")
        return report

    monkeypatch.setattr(ctx.ops, "embed_altium_models", fake_bulk)

    job = client.post("/api/altium/embed-models", json={}).json()
    assert "job_id" in job
    out = _drain_altium_job(client, job["job_id"])

    assert out["result"]["embedded"] == 2 and out["result"]["failed"] == 1
    assert out["result"]["skipped"] == ["kicad-only"]
    # the failing part's REASON survives to the report; a bulk run the owner walked away from is
    # exactly where "it did not work" without the reason is useless
    failed = next(r for r in out["result"]["results"] if r["status"] == "failed")
    assert "could not load" in failed["detail"]
    assert seen == {"part_ids": None, "replace": False}
    # it named the part it was on, because a silent multi-minute bar reads as a hang
    assert any("embedding a (1 of 2)" == m for m in out["messages"]), out["messages"]


def test_embed_models_can_be_scoped_to_named_parts(client, monkeypatch):
    seen = {}
    ctx = client.app.state.ctx
    monkeypatch.setattr(
        ctx.ops, "embed_altium_models",
        lambda part_ids=None, *, replace=False, on_progress=None: seen.setdefault(
            "ids", part_ids) or {"embedded": 0, "failed": 0, "attempted": 0,
                                 "skipped": [], "results": []},
    )
    job = client.post("/api/altium/embed-models", json={"part_ids": ["x"]}).json()
    _drain_altium_job(client, job["job_id"])
    assert seen["ids"] == ["x"]
