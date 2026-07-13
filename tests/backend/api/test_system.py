def test_health_needs_no_token(anon_client):
    r = anon_client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_system_info_requires_a_token(anon_client):
    r = anon_client.get("/api/system/info")
    assert r.status_code == 401


def test_system_info_reports_active_profile_and_count(client):
    r = client.get("/api/system/info")
    assert r.status_code == 200
    body = r.json()
    assert body["active_profile"] == "Main"
    assert body["part_count"] == 2


def test_system_info_reports_kicad_cli_availability(client):
    # so the UI can honestly tell the user when previews/import are unavailable
    body = client.get("/api/system/info").json()
    assert isinstance(body["kicad_cli_available"], bool)
    assert "kicad_cli_path" in body


def test_build_context_starts_without_kicad_cli(library_root, tmp_path, monkeypatch):
    # the regression the owner hit: no kicad-cli on PATH must NOT crash startup — the
    # app builds fine and degrades previews/import honestly.
    import stockroom.kicad.cli as cli_mod

    from stockroom.api.context import build_context
    from stockroom.store.machine_config import MachineConfig

    monkeypatch.setattr(cli_mod, "find_kicad_cli", lambda binary=None: None)
    kdir = tmp_path / "kc"
    kdir.mkdir()
    ctx = build_context(library_root, kicad_dir=kdir, config=MachineConfig(active_profile="Main"))
    assert ctx.cli.available is False
