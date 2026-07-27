"""The derivation surface: "which rules produced what I am looking at", and "bring it current".

A derivation-rules change (a new naming scheme, a cleaned-up description, a different spec
normalization) makes every stored `derived` block stale. Until this shipped, the only way to
close that was `scripts/import_library.py`, which refuses to run without distributor credentials
and re-fetches over the network. By the owner's standing rule -- *"everything u do manually the
app should do by itself"* -- that made it a missing feature.

These drive the REAL routes on the real app.
"""

import json

from stockroom.model.derived import DERIVED_BY


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
    return [p for k, p in events if k == "result"][0]["result"]


def test_the_surface_states_which_ruleset_is_running_and_what_the_library_carries(client):
    body = client.get("/api/library/derivation").json()
    assert body["ruleset"] == DERIVED_BY
    assert set(body) >= {"ruleset", "counts", "current", "stale"}
    # Every part is accounted for under exactly one stamp: a part cannot be both current and
    # stale, and none may go missing between the two numbers.
    assert body["current"] + body["stale"] == sum(body["counts"].values())


def test_a_part_produced_by_an_OLDER_ruleset_reads_as_stale(client, library_root):
    from stockroom.model.part import PartRecord

    parts = library_root / "Main" / "parts"
    path = next(parts.glob("*.json"))
    rec = PartRecord.loads(path.read_text(encoding="utf-8"))
    rec.derived_by = "rules@0"
    path.write_text(rec.dumps(), encoding="utf-8")
    # The index is rebuilt by any library write. This test edits the record file underneath
    # the app, so it syncs the index the same way a write would.
    client.app.state.ctx.rebuild_index()

    body = client.get("/api/library/derivation").json()
    assert body["counts"].get("rules@0") == 1
    assert body["stale"] >= 1


def test_a_rebuild_runs_as_a_job_and_reports_what_it_did(client):
    job_id = client.post("/api/library/derivation/rebuild", json={}).json()["job_id"]
    events = _sse(client, job_id)
    assert "error" not in [k for k, _ in events]
    report = _result(events)
    assert report["ruleset"] == DERIVED_BY
    assert set(report) >= {"checked", "rewritten", "unchanged", "no_evidence", "failed"}
    # The fixture library holds no `sourced/` evidence, so every part must be SKIPPED. A
    # rebuild that "succeeded" by blanking them would report rewrites here.
    assert report["rewritten"] == 0
    assert report["no_evidence"] == report["checked"] > 0


def _seed_evidence(client, library_root, part_id: str) -> None:
    """Give one fixture part a real stored Mouser payload and an OLD derivation stamp, so a
    rebuild has genuine work to do. Without this the fixture library holds no evidence at all
    and every rebuild test is vacuous -- which is exactly what a tamper caught."""
    from stockroom.model.part import PartRecord
    from stockroom.model.sourced import SOURCED_DIRNAME, SourceEntry, source_rel_path

    lib = library_root / "Main"
    src_dir = lib / SOURCED_DIRNAME / part_id
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "mouser.json").write_text(
        json.dumps({
            "Errors": [],
            "SearchResults": {"NumberOfResult": 1, "Parts": [{
                "ManufacturerPartNumber": "TPS62130RGTR",
                "Manufacturer": "Texas Instruments",
                "MouserPartNumber": "595-TPS62130RGTR",
                "Description": "Switching Voltage Regulators 3-17V 3A SD Cnvrtr A A 595-TPS62130RGTT",
                "Category": "Switching Voltage Regulators",
            }]},
        }),
        encoding="utf-8",
    )
    path = lib / "parts" / f"{part_id}.json"
    rec = PartRecord.loads(path.read_text(encoding="utf-8"))
    rec.derived_by = "rules@0"
    rec.sources["mouser"] = SourceEntry(
        fetched_at="2026-07-27T00:00:00Z", file=source_rel_path(part_id, "mouser")
    )
    path.write_text(rec.dumps(), encoding="utf-8")
    client.app.state.ctx.rebuild_index()


def test_a_rebuild_with_real_evidence_rewrites_the_part_through_the_route(client, library_root):
    """The route's real job, driven end to end: a stale part with stored evidence comes back
    on the current ruleset with the catalogue tail gone from its description."""
    from stockroom.model.part import PartRecord

    _seed_evidence(client, library_root, "tps62130")

    job_id = client.post("/api/library/derivation/rebuild", json={}).json()["job_id"]
    report = _result(_sse(client, job_id))

    assert report["rewritten"] == 1
    rec = PartRecord.loads(
        (library_root / "Main" / "parts" / "tps62130.json").read_text(encoding="utf-8")
    )
    assert rec.derived_by == DERIVED_BY
    assert rec.description == "Switching Voltage Regulators 3-17V 3A SD Cnvrtr"
    # And the index moved with it, so the surface stops reporting the part as stale.
    assert client.get("/api/library/derivation").json()["counts"].get("rules@0") is None


def test_a_dry_run_writes_nothing(client, library_root):
    """NEGATIVE CONTROL for the test above: the same part, the same real work to do, and the
    bytes on disk must not move. Seeding the evidence is what makes this able to fail -- with
    an evidence-free library a dry run and a real run are indistinguishable."""
    _seed_evidence(client, library_root, "tps62130")
    parts = library_root / "Main" / "parts"
    before = {p.name: p.read_bytes() for p in parts.glob("*.json")}

    job_id = client.post(
        "/api/library/derivation/rebuild", json={"dry_run": True}
    ).json()["job_id"]
    report = _result(_sse(client, job_id))

    assert report["rewritten"] == 1  # it found the work...
    assert {p.name: p.read_bytes() for p in parts.glob("*.json")} == before  # ...and did not do it


def test_both_routes_need_a_token(anon_client):
    assert anon_client.get("/api/library/derivation").status_code == 401
    assert anon_client.post("/api/library/derivation/rebuild", json={}).status_code == 401
