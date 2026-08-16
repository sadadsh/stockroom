"""The machine-settings surface (spec section 11): read the redacted per-machine
config and write the one field that is wired end-to-end today, the Mouser API key.
The key is a secret, so it is never echoed back raw; the write applies live (the
next enrich picks it up) and persists in the machine credential store."""

from __future__ import annotations

import json

from stockroom.store.machine_config import config_dir


def test_get_settings_reports_no_key_when_unset(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["mouser_api_key_set"] is False
    assert body["mouser_api_key_hint"] == ""


def test_get_settings_never_leaks_the_raw_key(client):
    client.patch("/api/settings", json={"mouser_api_key": "SECRETKEY1234"})
    body = client.get("/api/settings").json()
    # the response carries only presence + a last-4 hint, never the raw secret
    assert "mouser_api_key" not in body
    assert body["mouser_api_key_set"] is True
    assert body["mouser_api_key_hint"] == "1234"
    assert "SECRETKEY" not in json.dumps(body)


def test_patch_sets_the_key_live_on_the_context(client, app_ctx):
    r = client.patch("/api/settings", json={"mouser_api_key": "LIVEKEY9999"})
    assert r.status_code == 200
    # the running context sees the new key immediately (the next enrich uses it)
    assert app_ctx.config.mouser_api_key == "LIVEKEY9999"
    assert r.json()["mouser_api_key_set"] is True


def test_patch_persists_the_key_outside_plaintext_config(client):
    client.patch("/api/settings", json={"mouser_api_key": "PERSISTED42"})
    saved = json.loads((config_dir() / "config.json").read_text(encoding="utf-8"))
    assert "mouser_api_key" not in saved
    from stockroom.store.machine_config import MachineConfig

    assert MachineConfig.load().mouser_api_key == "PERSISTED42"


def test_patch_empty_string_clears_the_key(client):
    client.patch("/api/settings", json={"mouser_api_key": "TEMPKEY0000"})
    assert client.get("/api/settings").json()["mouser_api_key_set"] is True
    r = client.patch("/api/settings", json={"mouser_api_key": ""})
    assert r.status_code == 200
    body = client.get("/api/settings").json()
    assert body["mouser_api_key_set"] is False
    assert body["mouser_api_key_hint"] == ""


def test_patch_ignores_unknown_fields_without_error(client):
    # a stray field must not 500 or silently corrupt the config
    r = client.patch("/api/settings", json={"nonsense": "x", "mouser_api_key": "KEEP5678"})
    assert r.status_code == 200
    assert client.get("/api/settings").json()["mouser_api_key_hint"] == "5678"


def test_patch_without_the_key_leaves_it_unchanged(client):
    client.patch("/api/settings", json={"mouser_api_key": "STAY1111"})
    r = client.patch("/api/settings", json={})
    assert r.status_code == 200
    assert client.get("/api/settings").json()["mouser_api_key_hint"] == "1111"


def test_load_dev_creds_applies_the_config_dir_file(client, app_ctx):
    config_dir().mkdir(parents=True, exist_ok=True)
    (config_dir() / "dev-creds.json").write_text(
        json.dumps(
            {
                "digikey_client_id": "DKID1234",
                "digikey_client_secret": "DKSECRET9",
                "mouser_api_key": "MOUSER77",
                "ignored_field": "nope",
            }
        ),
        encoding="utf-8",
    )
    r = client.post("/api/settings/load-dev-creds")
    assert r.status_code == 200
    body = r.json()
    assert set(body["loaded"]) >= {"digikey_client_id", "digikey_client_secret", "mouser_api_key"}
    assert "ignored_field" not in body["loaded"]
    # applied live on the context; identifier echoed, secret masked to presence
    assert app_ctx.config.digikey_client_id == "DKID1234"
    assert body["digikey_client_id"] == "DKID1234"
    assert body["digikey_client_secret_set"] is True
    assert body["mouser_api_key_set"] is True
    # identifiers persist in config.json; secrets persist only in the credential store
    saved = json.loads((config_dir() / "config.json").read_text(encoding="utf-8"))
    assert saved["digikey_client_id"] == "DKID1234"
    assert "digikey_client_secret" not in saved
    assert "mouser_api_key" not in saved
    assert not (config_dir() / "dev-creds.json").exists()


def test_load_dev_creds_missing_file_is_a_noop(client):
    r = client.post("/api/settings/load-dev-creds")
    assert r.status_code == 200
    assert r.json()["loaded"] == []


def test_load_dev_creds_is_token_guarded(anon_client):
    assert anon_client.post("/api/settings/load-dev-creds").status_code in (401, 403)


def test_settings_is_token_guarded(anon_client):
    assert anon_client.get("/api/settings").status_code in (401, 403)
    assert anon_client.patch("/api/settings", json={"mouser_api_key": "x"}).status_code in (
        401,
        403,
    )
    # a new credential field is guarded by the same per-launch token dependency
    assert anon_client.patch("/api/settings", json={"digikey_client_secret": "x"}).status_code in (
        401,
        403,
    )


# -- GitHub browser authentication ---------------------------------------------


def test_get_settings_reports_no_legacy_github_token_when_unset(client):
    assert client.get("/api/settings").json()["github_token_set"] is False


def test_settings_rejects_pasted_github_tokens(client, app_ctx):
    response = client.patch(
        "/api/settings",
        json={"github_token": "ghp_SECRET1234"},
    )

    assert response.status_code == 400
    assert "Sign In With GitHub" in response.json()["detail"]
    assert app_ctx.config.github_token == ""
    assert not (config_dir() / "config.json").exists()


# -- Primary CAD Tool (per-machine, explicit, switchable) -----------------------


def test_get_settings_requires_an_explicit_primary_eda_choice(client):
    body = client.get("/api/settings").json()

    assert body["primary_eda"] is None
    assert body["primary_eda_pending"] is None
    assert body["primary_eda_confirmation_required"] is True
    assert body["recommended_primary_eda"] in {"kicad", "altium", None}
    assert [tool["key"] for tool in body["eda_tools"]] == ["kicad", "altium"]


def test_patch_primary_eda_applies_live_and_persists(client, app_ctx):
    response = client.patch("/api/settings", json={"primary_eda": "altium"})

    assert response.status_code == 200
    assert response.json()["primary_eda"] == "altium"
    assert response.json()["primary_eda_confirmation_required"] is False
    assert app_ctx.config.primary_eda == "altium"
    saved = json.loads((config_dir() / "config.json").read_text(encoding="utf-8"))
    assert saved["primary_eda"] == "altium"


def test_patch_primary_eda_rejects_an_unknown_tool(client, app_ctx):
    response = client.patch("/api/settings", json={"primary_eda": "unknown"})

    assert response.status_code == 400
    assert app_ctx.config.primary_eda == ""


# -- KiCad overrides + wiring status (not secrets: shown raw) -------------------


def test_get_settings_reports_kicad_state(client, app_ctx):
    body = client.get("/api/settings").json()
    assert body["kicad_config_override"] == ""
    assert body["kicad_cli_override"] == ""
    assert body["kicad_config_dir"] == app_ctx.kicad_dir.as_posix()
    assert isinstance(body["kicad_cli_available"], bool)
    assert body["kicad_cli_path"] == (app_ctx.cli.binary or "")
    assert body["kicad_wired"] is False  # nothing has wired the fixture config dir yet


def test_patch_kicad_cli_override_rebuilds_the_live_engine(client, app_ctx):
    old_cli = app_ctx.cli
    r = client.patch("/api/settings", json={"kicad_cli_override": "/nonexistent/kicad-cli"})
    assert r.status_code == 200
    assert app_ctx.config.kicad_cli_override == "/nonexistent/kicad-cli"
    assert app_ctx.cli is not old_cli
    # the engines that captured the old cli were rebuilt onto the new one
    assert app_ctx.ops.cli is app_ctx.cli
    assert app_ctx.project_ops.cli is app_ctx.cli
    saved = json.loads((config_dir() / "config.json").read_text(encoding="utf-8"))
    assert saved["kicad_cli_override"] == "/nonexistent/kicad-cli"


def test_patch_kicad_config_override_repoints_and_rewires(client, app_ctx, tmp_path):
    from stockroom.kicad.common_json import read_env_var

    target = tmp_path / "kicad-override"
    target.mkdir()
    r = client.patch("/api/settings", json={"kicad_config_override": str(target)})
    assert r.status_code == 200
    assert app_ctx.kicad_dir == target
    # the automatic rewire repointed SR_LIB at the active profile in the NEW dir
    assert read_env_var(target / "kicad_common.json", "SR_LIB") == str(
        app_ctx.profile.root.resolve()
    )
    assert client.get("/api/settings").json()["kicad_wired"] is True


def test_patch_clearing_kicad_config_override_returns_to_autodetect(
    client, app_ctx, tmp_path, monkeypatch
):
    # keep the autodetected default inside the test's tmp dir on every OS
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    target = tmp_path / "kicad-override"
    target.mkdir()
    client.patch("/api/settings", json={"kicad_config_override": str(target)})
    assert app_ctx.kicad_dir == target
    client.patch("/api/settings", json={"kicad_config_override": ""})
    assert app_ctx.config.kicad_config_override == ""
    assert app_ctx.kicad_dir != target


def test_patch_kicad_cli_override_never_moves_a_pinned_config_dir(client, app_ctx, tmp_path):
    # THE review-confirmed footgun: the fixture context pins kicad_dir to a tmp
    # dir, and saving a CLI override must NOT silently repoint it at the REAL
    # machine's KiCad config (which a rewire would then WRITE into).
    pinned = app_ctx.kicad_dir
    client.patch("/api/settings", json={"kicad_cli_override": "/nonexistent/kicad-cli"})
    assert app_ctx.kicad_dir == pinned


def test_patch_strips_windows_copy_as_path_quotes(client, app_ctx, tmp_path):
    target = tmp_path / "kicad-quoted"
    target.mkdir()
    client.patch("/api/settings", json={"kicad_config_override": f'"{target}"'})
    assert app_ctx.config.kicad_config_override == str(target)
    assert app_ctx.kicad_dir == target


# -- SamacSys (kept in-DigiKey CAD provider) -----------------------------------


# -- DigiKey API creds (OAuth client-credentials, now writable via settings) ----


def test_patch_sets_digikey_api_creds_live_and_persists(client, app_ctx):
    r = client.patch(
        "/api/settings",
        json={
            "digikey_client_id": "CLIENTID",
            "digikey_client_secret": "APISECRET1234",
        },
    )
    assert r.status_code == 200
    assert app_ctx.config.digikey_client_id == "CLIENTID"
    assert app_ctx.config.digikey_client_secret == "APISECRET1234"
    saved = json.loads((config_dir() / "config.json").read_text(encoding="utf-8"))
    assert saved["digikey_client_id"] == "CLIENTID"
    assert "digikey_client_secret" not in saved


def test_get_settings_echoes_client_id_and_masks_the_secret(client, app_ctx):
    app_ctx.config.digikey_client_id = "CLIENTID"
    app_ctx.config.digikey_client_secret = "APISECRET1234"
    body = client.get("/api/settings").json()
    assert body["digikey_client_id"] == "CLIENTID"
    assert body["digikey_client_secret_set"] is True
    assert body["digikey_client_secret_hint"] == "1234"
    assert "digikey_client_secret" not in body
    assert "APISECRET" not in json.dumps(body)


# -- DigiKey account web login (the driver's hands-free sign-in) ----------------


# -- stm_cubemx_source (stm-viewer workstream, Phase 3, API-02) - a plain path, not a secret --


def test_get_settings_reports_blank_stm_cubemx_source_by_default(client):
    body = client.get("/api/settings").json()
    assert body["stm_cubemx_source"] == ""


def test_patch_sets_stm_cubemx_source_live_and_persists(client, app_ctx, tmp_path):
    target = tmp_path / "cubemx" / "mcu"
    r = client.patch("/api/settings", json={"stm_cubemx_source": str(target)})
    assert r.status_code == 200
    assert app_ctx.config.stm_cubemx_source == str(target)
    assert r.json()["stm_cubemx_source"] == str(target)  # raw echo, never masked
    saved = json.loads((config_dir() / "config.json").read_text(encoding="utf-8"))
    assert saved["stm_cubemx_source"] == str(target)


def test_patch_normalizes_a_cubemx_install_root_to_its_device_data(client, app_ctx, tmp_path):
    install_root = tmp_path / "STM32CubeMX"
    device_data = install_root / "db" / "mcu"
    device_data.mkdir(parents=True)
    (device_data / "STM32TEST.xml").write_text(
        '<Mcu Family="STM32F4" RefName="STM32TEST" />',
        encoding="utf-8",
    )

    response = client.patch(
        "/api/settings",
        json={"stm_cubemx_source": str(install_root)},
    )

    assert response.status_code == 200
    assert app_ctx.config.stm_cubemx_source == str(device_data)
    assert response.json()["stm_cubemx_source"] == str(device_data)
    saved = json.loads((config_dir() / "config.json").read_text(encoding="utf-8"))
    assert saved["stm_cubemx_source"] == str(device_data)


def test_patch_clears_stm_cubemx_source_to_blank(client, app_ctx, tmp_path):
    client.patch("/api/settings", json={"stm_cubemx_source": str(tmp_path)})
    assert app_ctx.config.stm_cubemx_source != ""
    r = client.patch("/api/settings", json={"stm_cubemx_source": ""})
    assert r.status_code == 200
    assert app_ctx.config.stm_cubemx_source == ""
    assert r.json()["stm_cubemx_source"] == ""


def test_patch_without_stm_cubemx_source_leaves_it_unchanged(client, app_ctx, tmp_path):
    client.patch("/api/settings", json={"stm_cubemx_source": str(tmp_path)})
    r = client.patch("/api/settings", json={})
    assert r.status_code == 200
    assert app_ctx.config.stm_cubemx_source == str(tmp_path)


def test_default_cubemx_source_prefers_the_configured_setting(monkeypatch, tmp_path):
    # STOCKROOM_CONFIG_DIR is already isolated by the autouse _isolate_machine_config
    # fixture (same tmp_path), so MachineConfig.save()/load() here never touch the
    # developer's real ~/.config/stockroom.
    from stockroom.stm import source as stm_source
    from stockroom.store.machine_config import MachineConfig

    configured = tmp_path / "configured-cubemx"
    configured.mkdir()
    (configured / "STM32TEST.xml").write_text(
        '<Mcu Family="STM32F4" RefName="STM32TEST" />',
        encoding="utf-8",
    )
    MachineConfig(stm_cubemx_source=str(configured)).save()
    monkeypatch.setenv("STM32_CUBEMX", str(tmp_path))  # would win if the setting were ignored

    assert stm_source.default_cubemx_source() == configured


def test_settings_never_echoes_or_accepts_a_provider_website_login(client, app_ctx):
    """The person signs in to Ultra Librarian, SnapMagic, SamacSys, and DigiKey.com themselves.

    A saved provider password only exists to be replayed into someone else's sign-in form, so
    there is nowhere left for one to be stored and nothing left for this route to echo.
    """

    body = client.get("/api/settings").json()
    for retired in (
        "ul_username",
        "ul_password_set",
        "snapeda_username",
        "snapeda_password_set",
        "samacsys_username",
        "samacsys_password_set",
        "digikey_username",
        "digikey_password_set",
    ):
        assert retired not in body, retired

    # A stale client may still send them; they are ignored rather than stored.
    assert client.patch("/api/settings", json={"ul_username": "me@x.com"}).status_code == 200
    assert not hasattr(app_ctx.config, "ul_username")

    # The official catalogue API credentials are not website logins and remain.
    assert "digikey_client_id" in body
    assert "digikey_client_secret_set" in body
    assert "mouser_api_key_set" in body or "has_key" in body
