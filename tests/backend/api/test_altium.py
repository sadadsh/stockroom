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
    assert rec["altium_symbol"]["name"] and rec["altium_footprint"]["name"]

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
