"""The CAD-clear surface: "what CAD does my library hold", and "remove all of it".

Owner, 2026-07-27: *"remove all the current cad files before guided capture"*. Destructive and
library-wide, so the route defaults to a DRY RUN and a caller has to ask for the write.

These drive the REAL routes on the real app.
"""

import json


def _sse(client, job_id):
    out = []
    with client.stream("GET", f"/api/jobs/{job_id}/events") as resp:
        assert resp.status_code == 200
        kind = None
        for line in resp.iter_lines():
            if line.startswith("event:"):
                kind = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                out.append((kind, json.loads(line.split(":", 1)[1].strip() or "{}")))
    return out


def _result(events):
    assert "error" not in [k for k, _ in events], events
    return [p for k, p in events if k == "result"][0]["result"]


def test_the_inventory_counts_the_cad_without_touching_it(client, library_root):
    parts = library_root / "Main" / "parts"
    before = {p.name: p.read_bytes() for p in parts.glob("*.json")}

    body = client.get("/api/library/cad").json()

    assert set(body) >= {"cleared", "kept_stock", "items", "failed"}
    # The fixture library: two parts x (symbol + footprint) in SR-ICs, plus one 3D model ref.
    assert body["cleared"] == 5
    assert {p.name: p.read_bytes() for p in parts.glob("*.json")} == before


def test_the_clear_route_DEFAULTS_TO_A_DRY_RUN(client, library_root):
    """A destructive library-wide action must not be reachable by an empty POST. The report is
    identical either way, so the only difference a caller can see is that nothing moved."""
    parts = library_root / "Main" / "parts"
    before = {p.name: p.read_bytes() for p in parts.glob("*.json")}

    job_id = client.post("/api/library/cad/clear", json={}).json()["job_id"]
    report = _result(_sse(client, job_id))

    assert report["cleared"] == 5
    assert report["failed"] == []
    assert {p.name: p.read_bytes() for p in parts.glob("*.json")} == before


def test_asking_for_the_write_actually_removes_the_files_and_the_references(client, library_root):
    from stockroom.model.part import PartRecord

    lib = library_root / "Main"
    fp = lib / "footprints" / "SR-ICs.pretty" / "TPS62130.kicad_mod"
    assert fp.exists()

    job_id = client.post(
        "/api/library/cad/clear", json={"dry_run": False}
    ).json()["job_id"]
    report = _result(_sse(client, job_id))

    assert report["cleared"] == 5
    assert report["failed"] == []
    assert not fp.exists()
    rec = PartRecord.loads((lib / "parts" / "tps62130.json").read_text(encoding="utf-8"))
    assert rec.assets_for("kicad").symbol is None
    assert rec.assets_for("kicad").footprint is None
    # And the part itself survives: this removes assets, not parts.
    assert rec.mpn and rec.display_name
    # The index moved with it, so the surface stops claiming the part has files.
    assert client.get("/api/library/cad").json()["cleared"] == 0


def test_both_routes_need_a_token(anon_client):
    assert anon_client.get("/api/library/cad").status_code == 401
    assert anon_client.post("/api/library/cad/clear", json={}).status_code == 401
