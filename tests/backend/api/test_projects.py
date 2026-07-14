"""The projects surface (M7a-5): /api/projects registers, lists, gets, deletes and
audits external KiCad projects through the ProjectOps engine. Read/list is served
from the derived project index; register/delete rebuild it. The audit resolves the
active profile's footprints/models dirs at request time and returns a markdown report.

No em dashes anywhere (standing owner rule)."""

from __future__ import annotations

# a single unannotated resistor symbol with an empty Footprint: yields both an
# `unannotated` (R? reference) and a `no_footprint` finding when audited.
_UNANNOTATED = (
    "  (symbol\n"
    '    (lib_id "Device:R")\n'
    '    (property "Reference" "R?" (at 0 0 0))\n'
    '    (property "Value" "10k" (at 0 0 0))\n'
    '    (property "Footprint" "" (at 0 0 0))\n'
    "  )\n"
)


def _make_project(dir_path, sheet_body=_UNANNOTATED):
    """Materialise an external KiCad project dir: a JSON .kicad_pro plus a .kicad_sch
    holding the given symbols, so register() discovers it and audit() reads it."""
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "board.kicad_pro").write_text("{}", encoding="utf-8")
    (dir_path / "board.kicad_sch").write_text(
        "(kicad_sch\n" + sheet_body + ")\n", encoding="utf-8"
    )
    return dir_path


def _register(client, root) -> dict:
    r = client.post("/api/projects", json={"root": root.as_posix()})
    assert r.status_code == 200, r.text
    return r.json()


# ---- list -------------------------------------------------------------------


def test_list_is_empty_before_any_registration(client):
    r = client.get("/api/projects")
    assert r.status_code == 200
    assert r.json() == []


def test_list_returns_registered_projects_as_summaries(client, tmp_path):
    proj = _make_project(tmp_path / "ext" / "board")
    _register(client, proj)
    rows = client.get("/api/projects").json()
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "board"
    assert row["root"] == proj.as_posix()
    assert row["board_count"] == 0  # only a .kicad_pro + .kicad_sch, no .kicad_pcb
    assert row["sheet_count"] == 1
    assert row["has_git"] is False
    assert set(row) == {
        "id",
        "name",
        "root",
        "board_count",
        "sheet_count",
        "has_git",
        "registered_at",
    }


# ---- register ---------------------------------------------------------------


def test_register_returns_the_full_record(client, tmp_path):
    proj = _make_project(tmp_path / "ext" / "board")
    rec = _register(client, proj)
    assert rec["name"] == "board"
    assert rec["root"] == proj.as_posix()
    assert rec["pro_path"] == "board.kicad_pro"
    assert rec["sheet_paths"] == ["board.kicad_sch"]
    # the newly registered project is immediately visible in the rebuilt index
    assert [r["id"] for r in client.get("/api/projects").json()] == [rec["id"]]


def test_register_a_nonexistent_dir_is_a_400(client, tmp_path):
    r = client.post("/api/projects", json={"root": (tmp_path / "nope").as_posix()})
    assert r.status_code == 400


def test_register_a_dir_with_no_kicad_files_is_a_400(client, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    r = client.post("/api/projects", json={"root": empty.as_posix()})
    assert r.status_code == 400


def test_register_an_already_registered_root_is_a_400(client, tmp_path):
    proj = _make_project(tmp_path / "ext" / "board")
    _register(client, proj)
    r = client.post("/api/projects", json={"root": proj.as_posix()})
    assert r.status_code == 400


# ---- get --------------------------------------------------------------------


def test_get_returns_the_full_record(client, tmp_path):
    proj = _make_project(tmp_path / "ext" / "board")
    rec = _register(client, proj)
    got = client.get(f"/api/projects/{rec['id']}")
    assert got.status_code == 200
    assert got.json()["id"] == rec["id"]
    assert got.json()["root"] == proj.as_posix()


def test_get_an_unknown_project_is_a_404(client):
    assert client.get("/api/projects/nope").status_code == 404


# ---- delete -----------------------------------------------------------------


def test_delete_returns_204_and_removes_the_registration(client, tmp_path):
    proj = _make_project(tmp_path / "ext" / "board")
    rec = _register(client, proj)
    r = client.delete(f"/api/projects/{rec['id']}")
    assert r.status_code == 204
    assert r.content == b""
    # the rebuilt index no longer lists it
    assert client.get("/api/projects").json() == []
    assert client.get(f"/api/projects/{rec['id']}").status_code == 404


def test_delete_an_unknown_project_is_a_404(client):
    assert client.delete("/api/projects/nope").status_code == 404


# ---- audit ------------------------------------------------------------------


def test_audit_reports_findings_and_markdown(client, tmp_path):
    proj = _make_project(tmp_path / "ext" / "board")
    rec = _register(client, proj)
    r = client.get(f"/api/projects/{rec['id']}/audit")
    assert r.status_code == 200
    au = r.json()
    assert au["project"] == "board"  # named for the record
    assert au["components"] == 1
    kinds = {(f["ref"], f["kind"]) for f in au["findings"]}
    assert ("R?", "unannotated") in kinds
    assert ("R?", "no_footprint") in kinds
    assert au["markdown"].startswith("# Project Health")
    assert "R?" in au["markdown"]


def test_audit_an_unknown_project_is_a_404(client):
    assert client.get("/api/projects/nope/audit").status_code == 404


# A 2-pin symbol plus a footprint the active profile resolves to 3 pads: the pin/pad
# mismatch only surfaces if the router passes the profile's footprint dir to the audit.
_MISMATCH_SHEET = (
    "  (lib_symbols\n"
    '    (symbol "Device:R"\n'
    '      (symbol "R_0_1" (pin passive line (at 0 0 0)) (pin passive line (at 0 0 0)))\n'
    "    )\n"
    "  )\n"
    "  (symbol\n"
    '    (lib_id "Device:R")\n'
    '    (property "Reference" "R1" (at 0 0 0))\n'
    '    (property "Value" "10k" (at 0 0 0))\n'
    '    (property "Footprint" "SR-ICs:TESTFP" (at 0 0 0))\n'
    '    (property "MPN" "RC0402" (at 0 0 0))\n'
    "  )\n"
)


def test_audit_uses_the_active_profile_footprints_for_the_pin_pad_check(client, app_ctx, tmp_path):
    # Seed a 3-pad footprint into the active profile; the 2-pin symbol references it,
    # so a pin_pad_mismatch is produced ONLY because the router wires the profile's
    # footprint dir into the audit. Load-bearing for that wiring (drop it -> red).
    fp_dir = app_ctx.profile.library.footprint_lib_path("ICs")
    fp_dir.mkdir(parents=True, exist_ok=True)
    (fp_dir / "TESTFP.kicad_mod").write_text(
        '(footprint "TESTFP" (pad "1" smd rect) (pad "2" smd rect) (pad "3" smd rect))',
        encoding="utf-8",
    )
    rec = _register(client, _make_project(tmp_path / "mismatch", _MISMATCH_SHEET))
    au = client.get(f"/api/projects/{rec['id']}/audit").json()
    kinds = {(f["ref"], f["kind"]) for f in au["findings"]}
    assert ("R1", "pin_pad_mismatch") in kinds
    assert au["checked_footprints"] >= 1


# ---- checks (ERC + DRC, M7b) ------------------------------------------------


def _add_board(proj):
    """Give a fixture project a .kicad_pcb so DRC has a board to run on."""
    (proj / "board.kicad_pcb").write_text("(kicad_pcb)\n", encoding="utf-8")
    return proj


def test_run_checks_without_kicad_cli_is_an_honest_502(client, app_ctx, tmp_path):
    # cli-absent must be an honest 502, never a fabricated clean pass (Decision 8).
    proj = _make_project(tmp_path / "ext" / "board")
    rec = _register(client, proj)
    app_ctx.cli.binary = None
    r = client.post(f"/api/projects/{rec['id']}/checks")
    assert r.status_code == 502
    assert "kicad-cli" in r.json()["detail"].lower()


def test_run_checks_for_an_unknown_project_is_a_404_before_any_cli_check(client, app_ctx):
    # 404 is resolved before the cli gate, so an unknown id 404s even with no cli.
    app_ctx.cli.binary = None
    assert client.post("/api/projects/nope/checks").status_code == 404


def test_run_checks_returns_a_job_and_caches_the_result(client, app_ctx, tmp_path, monkeypatch):
    from stockroom.projects import checks as checks_mod

    proj = _add_board(_make_project(tmp_path / "ext" / "board"))
    rec = _register(client, proj)
    app_ctx.cli.binary = "/fake/kicad-cli"  # deterministic: never a real subprocess

    def fake_erc(path, cli):
        return {"ok": True, "findings": [{"severity": "warning", "rule": "unconnected",
                "message": "pin floating", "where": "U1"}],
                "summary": checks_mod.summarize([{"severity": "warning", "rule": "unconnected"}]),
                "error": ""}

    def fake_drc(path, cli):
        return {"ok": True, "findings": [{"severity": "error", "rule": "clearance",
                "message": "too close", "where": ""}],
                "summary": checks_mod.summarize([{"severity": "error", "rule": "clearance"}]),
                "error": ""}

    monkeypatch.setattr(checks_mod, "run_erc", fake_erc)
    monkeypatch.setattr(checks_mod, "run_drc", fake_drc)

    r = client.post(f"/api/projects/{rec['id']}/checks")
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    result = None
    with client.stream("GET", f"/api/jobs/{job_id}/events") as s:
        for line in s.iter_lines():
            if line.startswith("data:") and '"result"' in line:
                import json as _j
                result = _j.loads(line[5:].strip())["result"]
    assert result is not None
    assert result["summary"] == {"ok": True, "errors": 1, "warnings": 1, "total": 2, "checked": 2}
    assert result["erc"]["sheet"] == "board.kicad_sch"
    assert result["drc"][0]["board"] == "board.kicad_pcb"

    # cached: GET serves the same result without re-running.
    got = client.get(f"/api/projects/{rec['id']}/checks")
    assert got.status_code == 200
    assert got.json()["summary"] == result["summary"]


def test_get_checks_before_a_run_is_an_honest_not_run_shape(client, tmp_path):
    rec = _register(client, _make_project(tmp_path / "ext" / "board"))
    r = client.get(f"/api/projects/{rec['id']}/checks")
    assert r.status_code == 200
    body = r.json()
    assert body["ran_at"] is None and body["summary"] is None and body["erc"] is None


def test_get_checks_for_an_unknown_project_is_a_404(client):
    assert client.get("/api/projects/nope/checks").status_code == 404


# ---- auth -------------------------------------------------------------------


def test_projects_requires_a_token(anon_client):
    assert anon_client.get("/api/projects").status_code == 401
    assert anon_client.post("/api/projects/x/checks").status_code == 401
