from __future__ import annotations


def test_drift_report_is_returned(client):
    r = client.get("/api/doctor/drift")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert "missing_symbol" in body


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
