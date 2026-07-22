from pathlib import Path

ALTIUM_FIX = Path(__file__).parent.parent / "altium" / "fixtures"


def test_status_requires_token(anon_client):
    assert anon_client.get("/api/altium/status").status_code == 401


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


def test_attach_unknown_part_is_404(client):
    r = client.post("/api/altium/parts/nope/attach", json={"paths": [str(ALTIUM_FIX / "sample.IntLib")]})
    assert r.status_code == 404


def test_attach_without_paths_is_422(client):
    r = client.post("/api/altium/parts/tps62130/attach", json={"paths": []})
    assert r.status_code == 422
