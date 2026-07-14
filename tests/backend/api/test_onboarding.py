"""M9b: the onboarding API (status, set-library open/create/clone) with a LIVE engine
repoint, and complete. Uses the standard api conftest client (token-authed, config isolated
to the test's tmp dir)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from stockroom.store.profile import ProfileStore
from stockroom.vcs.repo import GitRepo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _library(root, profile="Main"):
    root.mkdir(parents=True, exist_ok=True)
    repo = GitRepo(root)
    repo.init()
    ProfileStore(root, repo).create(profile)
    return root


def test_status_reports_current_library(client):
    d = client.get("/api/onboarding").json()
    assert d["libraries_root"].endswith("/libraries")  # the fixture library root
    assert d["profiles"] == ["Main"]
    assert d["under_git"] is True
    assert set(d) >= {"onboarded", "first_run", "libraries_root", "profiles",
                      "under_git", "default_dir"}


def test_status_onboarded_when_library_ships_in_repo(client, app_ctx, monkeypatch):
    # The library committed inside the app repo counts as onboarded even if this machine never
    # ran the setup screen (a clone of the app already carries it), so the welcome gate is skipped.
    app_ctx.config.onboarded = False
    monkeypatch.setattr(
        "stockroom.store.library_location.IN_REPO_DEFAULT", Path(app_ctx.libraries_root)
    )
    d = client.get("/api/onboarding").json()
    assert d["onboarded"] is True and d["first_run"] is False
    assert d["under_git"] is True


def test_status_requires_token(anon_client):
    assert anon_client.get("/api/onboarding").status_code == 401


def test_set_library_open_repoints_engine_live(client, app_ctx, tmp_path):
    other = _library(tmp_path / "other", "Bench")
    r = client.post("/api/onboarding/library", json={"mode": "open", "path": str(other)})
    assert r.status_code == 200
    d = r.json()
    assert d["libraries_root"] == other.as_posix()
    assert d["profiles"] == ["Bench"]
    assert d["onboarded"] is True
    # the running context actually repointed (in place), and the token still authenticates
    assert app_ctx.libraries_root == other
    assert client.get("/api/onboarding").json()["libraries_root"] == other.as_posix()


def test_set_library_create_makes_a_fresh_library(client, tmp_path):
    dest = tmp_path / "fresh"
    r = client.post("/api/onboarding/library", json={"mode": "create", "path": str(dest)})
    assert r.status_code == 200
    assert (dest / ".git").exists()
    assert r.json()["libraries_root"] == dest.as_posix()


def test_set_library_open_missing_dir_is_400(client, tmp_path):
    r = client.post("/api/onboarding/library",
                    json={"mode": "open", "path": str(tmp_path / "nope")})
    assert r.status_code == 400


def test_set_library_unknown_mode_is_400(client):
    assert client.post("/api/onboarding/library", json={"mode": "teleport"}).status_code == 400


def test_complete_marks_onboarded(client, app_ctx):
    r = client.post("/api/onboarding/complete")
    assert r.status_code == 200 and r.json()["onboarded"] is True
    assert app_ctx.config.onboarded is True
