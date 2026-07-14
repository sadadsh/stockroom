"""M9b: AppContext.switch_library repoints the whole engine at a different library root in
place, preserving the token + host-wired hooks so auth keeps working and onboarding can
switch the library live without a restart."""

from __future__ import annotations

import shutil

import pytest

from stockroom.api.context import build_context
from stockroom.store.machine_config import MachineConfig
from stockroom.store.profile import ProfileStore
from stockroom.vcs.repo import GitRepo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _library(root, profile="Main"):
    root.mkdir(parents=True, exist_ok=True)
    repo = GitRepo(root)
    repo.init()
    ProfileStore(root, repo).create(profile)
    return root


def test_switch_library_repoints_and_preserves_token_and_clears_caches(tmp_path):
    a, b = _library(tmp_path / "A"), _library(tmp_path / "B")
    cfg = MachineConfig(active_profile="Main")
    ctx = build_context(a, kicad_dir=tmp_path / "k", config=cfg, token="TOK123")
    ctx.checks_cache["p"] = {"stale": 1}
    ctx.bom_cache["p"] = {"stale": 1}

    ctx.switch_library(b)

    assert ctx.libraries_root == b
    assert ctx.repo.root == b
    assert ctx.token == "TOK123"  # preserved: require_token closure keeps authenticating
    assert ctx.checks_cache == {} and ctx.bom_cache == {}  # old library's caches dropped
    assert ctx.config.libraries_root == str(b)
    assert ctx.profile_store.list() == ["Main"]  # points at B's profiles now


def test_switch_library_preserves_host_wired_hooks(tmp_path):
    a, b = _library(tmp_path / "A"), _library(tmp_path / "B")
    ctx = build_context(a, kicad_dir=tmp_path / "k", config=MachineConfig(), token="T")
    sentinel = object()

    def restart():
        return None

    ctx.rendered_dom_fetcher = sentinel
    ctx.request_restart = restart

    ctx.switch_library(b)

    assert ctx.rendered_dom_fetcher is sentinel
    assert ctx.request_restart is restart
