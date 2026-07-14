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


# ---- bom (M7c) --------------------------------------------------------------

# a sheet with one MPN'd IC and one bare passive: the IC prices, the passive stays
# unpriced (no purchasable part number), so a build is a "partial" cost verdict.
_IC_AND_PASSIVE = (
    "  (symbol\n"
    '    (lib_id "Device:U")\n'
    '    (property "Reference" "U1" (at 0 0 0))\n'
    '    (property "Value" "TPS2121" (at 0 0 0))\n'
    '    (property "MPN" "TPS2121RUXR" (at 0 0 0))\n'
    '    (property "MANUFACTURER" "TI" (at 0 0 0))\n'
    "  )\n"
    "  (symbol\n"
    '    (lib_id "Device:R")\n'
    '    (property "Reference" "R1" (at 0 0 0))\n'
    '    (property "Value" "10k" (at 0 0 0))\n'
    '    (property "Footprint" "Resistor_SMD:R_0402" (at 0 0 0))\n'
    "  )\n"
)


class _FakePipeline:
    """A stand-in for the enrich pipeline so BOM pricing never touches the network."""

    def enrich(self, mpn, category, want=None):
        from stockroom.enrich.schema import EnrichmentResult, PriceBreak, Sourced

        r = EnrichmentResult()
        if mpn == "TPS2121RUXR":
            r.mpn = Sourced(mpn, "mouser", "high")
            r.stock = Sourced(5000, "mouser", "high")
            r.price_breaks = [PriceBreak(qty=1, price=1.25)]
        return r


def _stream_job_result(client, job_id):
    import json as _j

    result = None
    with client.stream("GET", f"/api/jobs/{job_id}/events") as s:
        for line in s.iter_lines():
            if line.startswith("data:") and '"result"' in line:
                result = _j.loads(line[5:].strip())["result"]
    return result


def test_run_bom_prices_and_caches_the_result(client, app_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "stockroom.api.routers.enrich._make_pipeline", lambda ctx: _FakePipeline()
    )
    proj = _make_project(tmp_path / "ext" / "board", _IC_AND_PASSIVE)
    rec = _register(client, proj)

    r = client.post(f"/api/projects/{rec['id']}/bom")
    assert r.status_code == 200
    result = _stream_job_result(client, r.json()["job_id"])
    assert result is not None and result["priced"] is True
    by_mpn = {ln["mpn"]: ln for ln in result["lines"]}
    assert by_mpn["TPS2121RUXR"]["unit_price"] == 1.25
    assert by_mpn["TPS2121RUXR"]["source"] == "Mouser"
    assert result["summary"]["total_cost"] == 1.25
    assert result["summary"]["priced_lines"] == 1 and result["summary"]["unpriced_lines"] == 1
    assert result["summary"]["state"] == "partial"
    assert result["by_source"]["sources"]["Mouser"]["total_cost"] == 1.25

    # cached: GET serves the same build without rebuilding.
    got = client.get(f"/api/projects/{rec['id']}/bom")
    assert got.status_code == 200
    assert got.json()["summary"]["total_cost"] == 1.25


def test_run_bom_does_not_require_kicad_cli(client, app_ctx, tmp_path):
    # The BOM is built offline from the schematic, so a missing kicad-cli is NOT a 502:
    # grouping still works, and a passive-only project needs no pricing lookup at all.
    app_ctx.cli.binary = None
    rec = _register(client, _make_project(tmp_path / "ext" / "board"))
    r = client.post(f"/api/projects/{rec['id']}/bom")
    assert r.status_code == 200
    result = _stream_job_result(client, r.json()["job_id"])
    assert result is not None and result["line_count"] == 1
    # priced was attempted but the lone passive has no MPN -> honestly unpriced.
    assert result["summary"]["state"] == "unpriced"


def test_run_bom_for_an_unknown_project_is_a_404(client):
    assert client.post("/api/projects/nope/bom").status_code == 404


def test_get_bom_before_a_build_is_an_honest_not_built_shape(client, tmp_path):
    rec = _register(client, _make_project(tmp_path / "ext" / "board"))
    body = client.get(f"/api/projects/{rec['id']}/bom").json()
    assert body["ran_at"] is None and body["summary"] is None and body["lines"] == []


def test_get_bom_for_an_unknown_project_is_a_404(client):
    assert client.get("/api/projects/nope/bom").status_code == 404


def test_delete_evicts_the_cached_bom(client, app_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "stockroom.api.routers.enrich._make_pipeline", lambda ctx: _FakePipeline()
    )
    proj = _make_project(tmp_path / "ext" / "board", _IC_AND_PASSIVE)
    rec = _register(client, proj)
    _stream_job_result(client, client.post(f"/api/projects/{rec['id']}/bom").json()["job_id"])
    assert rec["id"] in app_ctx.bom_cache
    client.delete(f"/api/projects/{rec['id']}")
    assert rec["id"] not in app_ctx.bom_cache


def test_bom_job_does_not_resurrect_cache_for_a_deleted_project(client, app_ctx, tmp_path, monkeypatch):
    # A DELETE landing while a BOM job runs evicts the cache; the job's write-back must
    # NOT re-insert a stale entry for the now-gone id (project ids are reusable slugs).
    monkeypatch.setattr(
        "stockroom.api.routers.enrich._make_pipeline", lambda ctx: _FakePipeline()
    )
    proj = _make_project(tmp_path / "ext" / "board", _IC_AND_PASSIVE)
    rec = _register(client, proj)
    real_bom = app_ctx.project_ops.bom

    def deleting_bom(pid, **kw):
        result = real_bom(pid, **kw)
        # simulate a concurrent DELETE landing mid-job (evicts the cache before write-back)
        app_ctx.project_ops.delete(pid)
        app_ctx.bom_cache.pop(pid, None)
        return result

    monkeypatch.setattr(app_ctx.project_ops, "bom", deleting_bom)
    _stream_job_result(client, client.post(f"/api/projects/{rec['id']}/bom").json()["job_id"])
    assert rec["id"] not in app_ctx.bom_cache  # the existence re-check prevented resurrection


# ---- procurement (M7d) ------------------------------------------------------


class _ProcPipeline:
    """A stand-in enrich pipeline that prices the IC as a short-stock, NRND, long-lead
    part so the procurement roll-ups have a real risk + lead to report."""

    def enrich(self, mpn, category, want=None):
        from stockroom.enrich.schema import EnrichmentResult, PriceBreak, Sourced

        r = EnrichmentResult()
        if mpn == "TPS2121RUXR":
            r.mpn = Sourced(mpn, "mouser", "high")
            r.stock = Sourced(0, "mouser", "high")  # no stock -> a real risk
            r.lifecycle = Sourced("NRND", "mouser", "high")
            r.lead_time = Sourced("18 Weeks", "mouser", "high")
            r.price_breaks = [PriceBreak(qty=1, price=1.25)]
        return r


def test_get_procurement_before_a_build_is_an_honest_not_built_shape(client, tmp_path):
    rec = _register(client, _make_project(tmp_path / "ext" / "board", _IC_AND_PASSIVE))
    body = client.get(f"/api/projects/{rec['id']}/procurement").json()
    assert body["built"] is False
    assert body["lines"] == []
    assert body["risks"]["any"] is False
    assert body["lead"]["any"] is False


def test_get_procurement_after_a_build_reports_risk_and_lead(client, app_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "stockroom.api.routers.enrich._make_pipeline", lambda ctx: _ProcPipeline()
    )
    rec = _register(client, _make_project(tmp_path / "ext" / "board", _IC_AND_PASSIVE))
    _stream_job_result(client, client.post(f"/api/projects/{rec['id']}/bom").json()["job_id"])

    body = client.get(f"/api/projects/{rec['id']}/procurement").json()
    assert body["built"] is True
    assert body["priced"] is True
    by_mpn = {ln["mpn"]: ln for ln in body["lines"]}
    assert by_mpn["TPS2121RUXR"]["stock_risk"]["kind"] == "err"  # 0 stock
    assert by_mpn["TPS2121RUXR"]["orderable"] is False
    assert body["risks"]["not_active"] == 1  # NRND
    assert body["risks"]["no_stock"] == 1
    assert "TPS2121RUXR" in body["risks"]["risky_mpns"]
    assert body["lead"]["max_weeks"] == 18
    assert body["lead"]["critical_mpn"] == "TPS2121RUXR"
    assert body["summary"].startswith("BOM: ")


def test_get_procurement_for_an_unknown_project_is_a_404(client):
    assert client.get("/api/projects/nope/procurement").status_code == 404


# ---- exports (M7d) ----------------------------------------------------------


def _build_bom(client, monkeypatch, tmp_path, pipeline_cls):
    monkeypatch.setattr(
        "stockroom.api.routers.enrich._make_pipeline", lambda ctx: pipeline_cls()
    )
    rec = _register(client, _make_project(tmp_path / "ext" / "board", _IC_AND_PASSIVE))
    _stream_job_result(client, client.post(f"/api/projects/{rec['id']}/bom").json()["job_id"])
    return rec


def test_export_csv_kinds_download_with_a_named_attachment(client, tmp_path, monkeypatch):
    rec = _build_bom(client, monkeypatch, tmp_path, _FakePipeline)
    for kind in ("csv", "priced", "cart", "jlcpcb"):
        r = client.get(f"/api/projects/{rec['id']}/bom/export", params={"kind": kind})
        assert r.status_code == 200, (kind, r.text)
        assert r.headers["content-type"].startswith("text/csv")
        assert "attachment" in r.headers["content-disposition"]
        assert ".csv" in r.headers["content-disposition"]
        assert r.text  # non-empty CSV body


def test_export_xlsx_kinds_are_valid_binary_workbooks(client, tmp_path, monkeypatch):
    import io
    import zipfile

    rec = _build_bom(client, monkeypatch, tmp_path, _FakePipeline)
    for kind in ("xlsx", "procurement"):
        r = client.get(f"/api/projects/{rec['id']}/bom/export", params={"kind": kind})
        assert r.status_code == 200, (kind, r.text)
        assert r.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert ".xlsx" in r.headers["content-disposition"]
        assert not zipfile.ZipFile(io.BytesIO(r.content)).testzip()  # a valid workbook


def test_export_an_unknown_kind_is_a_400(client, tmp_path, monkeypatch):
    rec = _build_bom(client, monkeypatch, tmp_path, _FakePipeline)
    assert client.get(f"/api/projects/{rec['id']}/bom/export", params={"kind": "pdf"}).status_code == 400


def test_export_before_a_build_is_an_honest_400(client, tmp_path):
    rec = _register(client, _make_project(tmp_path / "ext" / "board", _IC_AND_PASSIVE))
    r = client.get(f"/api/projects/{rec['id']}/bom/export", params={"kind": "csv"})
    assert r.status_code == 400  # nothing built yet to export


def test_export_for_an_unknown_project_is_a_404(client):
    assert client.get("/api/projects/nope/bom/export", params={"kind": "csv"}).status_code == 404


# ---- revision diff (M7d) ----------------------------------------------------

import subprocess


def _make_git_project(dir_path, sheet_body):
    """A registered-able project dir that is its OWN git repo, with one commit."""
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "board.kicad_pro").write_text("{}", encoding="utf-8")
    (dir_path / "board.kicad_sch").write_text(
        "(kicad_sch\n" + sheet_body + ")\n", encoding="utf-8")
    for args in (["init", "-b", "main"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"], ["add", "."], ["commit", "-m", "rev A"]):
        subprocess.run(["git", "-C", str(dir_path), *args], check=True, capture_output=True)
    head = subprocess.run(["git", "-C", str(dir_path), "rev-parse", "HEAD"],
                          check=True, capture_output=True, text=True).stdout.strip()
    return dir_path, head


_TWO_RES = (
    '  (symbol (lib_id "Device:R") (property "Reference" "R1" (at 0 0 0))'
    ' (property "Value" "10k" (at 0 0 0)))\n'
    '  (symbol (lib_id "Device:R") (property "Reference" "R2" (at 0 0 0))'
    ' (property "Value" "10k" (at 0 0 0)))\n'
)


def test_revisions_lists_the_project_git_history(client, tmp_path):
    proj, rev_a = _make_git_project(tmp_path / "board", _TWO_RES)
    rec = _register(client, proj)
    body = client.get(f"/api/projects/{rec['id']}/revisions").json()
    assert body["under_git"] is True
    assert len(body["revisions"]) == 1
    assert body["revisions"][0]["sha"] == rev_a
    assert body["revisions"][0]["short"] == rev_a[:7]


def test_revisions_for_a_non_git_project_is_an_honest_empty(client, tmp_path):
    rec = _register(client, _make_project(tmp_path / "ext" / "board"))  # not a git repo
    body = client.get(f"/api/projects/{rec['id']}/revisions").json()
    assert body["under_git"] is False
    assert body["revisions"] == []


def test_bom_diff_reconstructs_rev_a_against_the_working_tree(client, tmp_path):
    proj, rev_a = _make_git_project(tmp_path / "board", _TWO_RES)
    rec = _register(client, proj)
    # add a third 10k in the working tree after registration
    (proj / "board.kicad_sch").write_text(
        "(kicad_sch\n" + _TWO_RES
        + '  (symbol (lib_id "Device:R") (property "Reference" "R3" (at 0 0 0))'
          ' (property "Value" "10k" (at 0 0 0)))\n)\n', encoding="utf-8")
    body = client.get(f"/api/projects/{rec['id']}/bom/diff", params={"a": rev_a}).json()
    assert body["rev_a"] == rev_a
    assert body["rev_b"] == "current"
    changed = {c["value"]: c for c in body["changed"]}
    assert changed["10k"]["from_qty"] == 2 and changed["10k"]["to_qty"] == 3


def test_bom_diff_cost_delta_comes_from_the_cached_priced_build(client, tmp_path, monkeypatch):
    # Locks the router wire that feeds the cached PRICED build as rev B (current_rows) into
    # the diff: without it the working tree is reconstructed unpriced and the cost delta is 0.
    monkeypatch.setattr(
        "stockroom.api.routers.enrich._make_pipeline", lambda ctx: _FakePipeline()
    )
    # rev A holds only the passive (with the current footprint so it does not itself diff).
    rev_a_body = (
        '  (symbol (lib_id "Device:R") (property "Reference" "R1" (at 0 0 0))'
        ' (property "Value" "10k" (at 0 0 0)) (property "Footprint" "Resistor_SMD:R_0402" (at 0 0 0)))\n'
    )
    proj, rev_a = _make_git_project(tmp_path / "board", rev_a_body)
    rec = _register(client, proj)
    # working tree adds the priced IC (TPS2121RUXR, $1.25 from the fake pipeline)
    (proj / "board.kicad_sch").write_text("(kicad_sch\n" + _IC_AND_PASSIVE + ")\n", encoding="utf-8")
    _stream_job_result(client, client.post(f"/api/projects/{rec['id']}/bom").json()["job_id"])

    body = client.get(f"/api/projects/{rec['id']}/bom/diff", params={"a": rev_a}).json()
    assert any(x["mpn"] == "TPS2121RUXR" for x in body["added"])
    assert body["cost"]["priced"] is True  # the current build is priced -> delta is meaningful
    assert body["cost"]["added_cost"] == 1.25
    assert body["cost"]["delta"] == 1.25


def test_bom_diff_without_a_revision_is_a_400(client, tmp_path):
    proj, _rev = _make_git_project(tmp_path / "board", _TWO_RES)
    rec = _register(client, proj)
    assert client.get(f"/api/projects/{rec['id']}/bom/diff").status_code == 400


def test_bom_diff_for_a_non_git_project_is_a_400(client, tmp_path):
    rec = _register(client, _make_project(tmp_path / "ext" / "board"))
    r = client.get(f"/api/projects/{rec['id']}/bom/diff", params={"a": "HEAD"})
    assert r.status_code == 400


def test_revisions_and_diff_for_an_unknown_project_are_404(client):
    assert client.get("/api/projects/nope/revisions").status_code == 404
    assert client.get("/api/projects/nope/bom/diff", params={"a": "HEAD"}).status_code == 404


# ---- auth -------------------------------------------------------------------


def test_projects_requires_a_token(anon_client):
    assert anon_client.get("/api/projects").status_code == 401
    assert anon_client.post("/api/projects/x/checks").status_code == 401
    assert anon_client.post("/api/projects/x/bom").status_code == 401
    assert anon_client.get("/api/projects/x/bom").status_code == 401
    assert anon_client.get("/api/projects/x/procurement").status_code == 401
    assert anon_client.get("/api/projects/x/bom/export").status_code == 401
    assert anon_client.get("/api/projects/x/revisions").status_code == 401
    assert anon_client.get("/api/projects/x/bom/diff").status_code == 401
