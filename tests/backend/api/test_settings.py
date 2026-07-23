"""The machine-settings surface (spec section 11): read the redacted per-machine
config and write the one field that is wired end-to-end today, the Mouser API key.
The key is a secret, so it is never echoed back raw; the write applies live (the
next enrich picks it up) and persists to the per-machine config.json."""

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


def test_patch_persists_the_key_to_disk(client):
    client.patch("/api/settings", json={"mouser_api_key": "PERSISTED42"})
    saved = json.loads((config_dir() / "config.json").read_text(encoding="utf-8"))
    assert saved["mouser_api_key"] == "PERSISTED42"


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


def test_settings_is_token_guarded(anon_client):
    assert anon_client.get("/api/settings").status_code in (401, 403)
    assert anon_client.patch(
        "/api/settings", json={"mouser_api_key": "x"}
    ).status_code in (401, 403)
    # a new credential field is guarded by the same per-launch token dependency
    assert anon_client.patch(
        "/api/settings", json={"digikey_client_secret": "x"}
    ).status_code in (401, 403)


# -- GitHub personal access token (auto-push auth) -----------------------------


def test_get_settings_reports_no_github_token_when_unset(client):
    assert client.get("/api/settings").json()["github_token_set"] is False


def test_patch_github_token_sets_it_live_and_never_leaks_it(client, app_ctx):
    r = client.patch("/api/settings", json={"github_token": "ghp_SECRET1234"})
    body = r.json()
    assert body["github_token_set"] is True and body["github_token_hint"] == "1234"
    assert "ghp_SECRET" not in json.dumps(body)  # only presence + last-4, never the raw token
    assert app_ctx.config.github_token == "ghp_SECRET1234"
    # applied LIVE to the library repo so push/pull authenticate immediately (a github extraheader)
    got = app_ctx.repo._run("config", "--get", "http.https://github.com/.extraheader", check=False)
    assert got.returncode == 0 and "basic" in got.stdout.lower()
    assert "ghp_SECRET" not in got.stdout  # base64-encoded, not the raw token


def test_patch_persists_the_github_token(client):
    client.patch("/api/settings", json={"github_token": "ghp_PERSIST42"})
    saved = json.loads((config_dir() / "config.json").read_text(encoding="utf-8"))
    assert saved["github_token"] == "ghp_PERSIST42"


def test_patch_empty_github_token_clears_the_credential(client, app_ctx):
    client.patch("/api/settings", json={"github_token": "ghp_TEMP"})
    client.patch("/api/settings", json={"github_token": ""})
    assert app_ctx.config.github_token == ""
    got = app_ctx.repo._run("config", "--get", "http.https://github.com/.extraheader", check=False)
    assert got.returncode != 0  # the credential header was removed


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


def test_patch_sets_vendor_logins(client, app_ctx):
    client.patch("/api/settings", json={
        "ul_username": "me@x.com", "ul_password": "secret",
        "snapeda_username": "s", "snapeda_password": "q",
    })
    assert app_ctx.config.ul_username == "me@x.com"
    assert app_ctx.config.ul_password == "secret"
    assert app_ctx.config.snapeda_username == "s"
    assert app_ctx.config.snapeda_password == "q"


def test_get_settings_masks_vendor_passwords(client, app_ctx):
    app_ctx.config.ul_username = "me@x.com"
    app_ctx.config.ul_password = "secret"
    body = client.get("/api/settings").json()
    assert body["ul_username"] == "me@x.com"
    assert body["ul_password_set"] is True
    assert body["ul_password_hint"] == "cret"
    assert "ul_password" not in body


def test_vendor_login_raw_password_never_leaks(client, app_ctx):
    import json as _json
    app_ctx.config.snapeda_password = "topsecretpw"
    body = client.get("/api/settings").json()
    assert "topsecretpw" not in _json.dumps(body)


def test_get_settings_tolerates_a_null_secret_field(client, app_ctx):
    # a hand-edited config.json can carry a JSON null; the hint must not 500
    app_ctx.config.ul_password = None
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    assert resp.json()["ul_password_set"] is False
    assert resp.json()["ul_password_hint"] == ""


# -- SamacSys (kept in-DigiKey CAD provider) -----------------------------------


def test_patch_sets_samacsys_login_live_and_persists(client, app_ctx):
    r = client.patch("/api/settings", json={
        "samacsys_username": "sam@x.com", "samacsys_password": "samsecret",
    })
    assert r.status_code == 200
    assert app_ctx.config.samacsys_username == "sam@x.com"
    assert app_ctx.config.samacsys_password == "samsecret"
    saved = json.loads((config_dir() / "config.json").read_text(encoding="utf-8"))
    assert saved["samacsys_username"] == "sam@x.com"
    assert saved["samacsys_password"] == "samsecret"


def test_get_settings_masks_samacsys_password(client, app_ctx):
    app_ctx.config.samacsys_username = "sam@x.com"
    app_ctx.config.samacsys_password = "samsecret"
    body = client.get("/api/settings").json()
    assert body["samacsys_username"] == "sam@x.com"
    assert body["samacsys_password_set"] is True
    assert body["samacsys_password_hint"] == "cret"
    assert "samacsys_password" not in body
    assert "samsecret" not in json.dumps(body)


def test_get_settings_tolerates_a_null_samacsys_password(client, app_ctx):
    app_ctx.config.samacsys_password = None
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    assert resp.json()["samacsys_password_set"] is False
    assert resp.json()["samacsys_password_hint"] == ""


# -- DigiKey API creds (OAuth client-credentials, now writable via settings) ----


def test_patch_sets_digikey_api_creds_live_and_persists(client, app_ctx):
    r = client.patch("/api/settings", json={
        "digikey_client_id": "CLIENTID", "digikey_client_secret": "APISECRET1234",
    })
    assert r.status_code == 200
    assert app_ctx.config.digikey_client_id == "CLIENTID"
    assert app_ctx.config.digikey_client_secret == "APISECRET1234"
    saved = json.loads((config_dir() / "config.json").read_text(encoding="utf-8"))
    assert saved["digikey_client_id"] == "CLIENTID"
    assert saved["digikey_client_secret"] == "APISECRET1234"


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


def test_patch_sets_digikey_account_login_live_and_persists(client, app_ctx):
    r = client.patch("/api/settings", json={
        "digikey_username": "dk@x.com", "digikey_password": "accountpw1234",
    })
    assert r.status_code == 200
    assert app_ctx.config.digikey_username == "dk@x.com"
    assert app_ctx.config.digikey_password == "accountpw1234"
    saved = json.loads((config_dir() / "config.json").read_text(encoding="utf-8"))
    assert saved["digikey_username"] == "dk@x.com"
    assert saved["digikey_password"] == "accountpw1234"


def test_get_settings_echoes_digikey_username_and_masks_the_password(client, app_ctx):
    app_ctx.config.digikey_username = "dk@x.com"
    app_ctx.config.digikey_password = "accountpw1234"
    body = client.get("/api/settings").json()
    assert body["digikey_username"] == "dk@x.com"
    assert body["digikey_password_set"] is True
    assert body["digikey_password_hint"] == "1234"
    assert "digikey_password" not in body
    assert "accountpw1234" not in json.dumps(body)
