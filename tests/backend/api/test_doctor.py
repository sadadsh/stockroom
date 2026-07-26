from __future__ import annotations


def test_wire_kicad_runs_as_a_job(client, monkeypatch):
    from stockroom.kicad.wiring import WiringReport

    class _FakeWiring:
        def __init__(self, *a, **k):
            pass

        def apply(self, profile):
            return WiringReport(sr_lib_value="/x", categories_registered=["ICs"],
                                restart_needed=True)

    monkeypatch.setattr("stockroom.api.routers.doctor.KiCadWiring", _FakeWiring)

    r = client.post("/api/doctor/wire-kicad")
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    with client.stream("GET", f"/api/jobs/{job_id}/events") as s:
        body = "".join(chunk for chunk in s.iter_text())
    assert "restart_needed" in body
    assert "done" in body


def test_scan_returns_a_repair_plan(client):
    r = client.get("/api/doctor/scan")
    assert r.status_code == 200
    body = r.json()
    for key in ("fixable", "manual", "uncommitted", "healthy"):
        assert key in body
    # the seed fixture references a 3D model + datasheet file that are not on disk
    kinds = {f["kind"] for f in body["manual"]}
    assert "dangling_model" in kinds


def test_scan_manual_findings_carry_how_to_fix(client):
    body = client.get("/api/doctor/scan").json()
    assert body["manual"]  # the fixture has dangling references
    assert all(f["how_to_fix"] for f in body["manual"])
    assert all({"kind", "part_id", "detail", "how_to_fix"} <= set(f) for f in body["manual"])


def test_repair_applies_and_reports(client):
    r = client.post("/api/doctor/repair")
    assert r.status_code == 200
    body = r.json()
    for key in ("healed_drift", "fixed_paths", "committed_files", "commit", "manual"):
        assert key in body
    # a dangling FILE can never be auto-fixed, so it survives as a manual finding
    assert any(f["kind"] == "dangling_model" for f in body["manual"])


def test_repair_is_idempotent(client):
    client.post("/api/doctor/repair")
    body = client.post("/api/doctor/repair").json()
    assert body["healed_drift"] == 0
    assert body["fixed_paths"] == 0


def test_scan_and_repair_require_a_token(anon_client):
    assert anon_client.get("/api/doctor/scan").status_code == 401
    assert anon_client.post("/api/doctor/repair").status_code == 401
