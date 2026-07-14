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
