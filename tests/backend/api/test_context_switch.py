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


def test_switch_library_leaves_stm_index_untouched(tmp_path):
    """The CubeMX source is machine-global config (stm-viewer workstream, Phase 3), not
    library-scoped - unlike `index`, switch_library must never rebuild or repoint it."""
    a, b = _library(tmp_path / "A"), _library(tmp_path / "B")
    ctx = build_context(a, kicad_dir=tmp_path / "k", config=MachineConfig(active_profile="Main"), token="T")
    sentinel = object()
    ctx.stm_index = sentinel

    ctx.switch_library(b)

    assert ctx.stm_index is sentinel


def test_switch_library_preserves_host_wired_hooks(tmp_path):
    a, b = _library(tmp_path / "A"), _library(tmp_path / "B")
    ctx = build_context(a, kicad_dir=tmp_path / "k", config=MachineConfig(active_profile="Main"), token="T")
    sentinel = object()

    def restart():
        return None

    ctx.rendered_dom_fetcher = sentinel
    ctx.request_restart = restart

    ctx.switch_library(b)

    assert ctx.rendered_dom_fetcher is sentinel
    assert ctx.request_restart is restart


def _precreate_category_libs(profile) -> None:
    from stockroom.model.category import CATEGORIES, category_symbol_lib

    empty = '(kicad_symbol_lib\r\n\t(version 20251024)\r\n\t(generator "x")\r\n)\r\n'
    profile.library.symbols_dir.mkdir(parents=True, exist_ok=True)
    for cat in CATEGORIES:
        (profile.library.symbols_dir / category_symbol_lib(cat)).write_text(empty, newline="")


def test_switch_profile_rewires_sr_lib(tmp_path):
    # the stale-SR_LIB bug: after a profile switch KiCad kept showing the OLD
    # profile's library; switching must repoint SR_LIB immediately
    from stockroom.kicad.common_json import read_env_var

    a = _library(tmp_path / "A")
    kdir = tmp_path / "k"
    kdir.mkdir()
    ctx = build_context(a, kicad_dir=kdir, config=MachineConfig(active_profile="Main"), token="T")
    alt = ctx.profile_store.create("Alt")
    _precreate_category_libs(alt)

    ctx.switch_profile("Alt")

    assert read_env_var(kdir / "kicad_common.json", "SR_LIB") == str(alt.root.resolve())
    assert ctx.last_wiring is not None


def test_switch_library_rewires_sr_lib(tmp_path):
    from stockroom.kicad.common_json import read_env_var

    a, b = _library(tmp_path / "A"), _library(tmp_path / "B")
    kdir = tmp_path / "k"
    kdir.mkdir()
    ctx = build_context(a, kicad_dir=kdir, config=MachineConfig(active_profile="Main"), token="T")
    _precreate_category_libs(ProfileStore(b, GitRepo(b)).get("Main"))

    ctx.switch_library(b)

    assert read_env_var(kdir / "kicad_common.json", "SR_LIB") == str(ctx.profile.root.resolve())
    assert str(b) in read_env_var(kdir / "kicad_common.json", "SR_LIB")


def test_a_fresh_clone_gets_its_derived_altium_data_source_built_at_boot(tmp_path):
    """The property that PAID for committing the derived .db until 2026-07-25: a fresh clone must
    be placeable with no regenerate step. It is now bought by building the file at boot instead of
    sharing an unmergeable binary, so this is the test that keeps that promise honest."""
    root = _library(tmp_path / "fresh")
    db = root / "Main" / "altium" / "stockroom-parts.db"
    assert not db.exists()

    build_context(root, kicad_dir=tmp_path / "k", config=MachineConfig(active_profile="Main"),
                  token="T")

    assert db.exists()


def test_switching_profile_rebuilds_the_data_source_for_the_new_profile(tmp_path):
    """Each profile holds different parts, so leaving the previous profile's data source in place
    would have Altium placing parts from a library the user is no longer looking at."""
    root = _library(tmp_path / "multi")
    repo = GitRepo(root)
    ProfileStore(root, repo).create("Second")
    ctx = build_context(root, kicad_dir=tmp_path / "k",
                        config=MachineConfig(active_profile="Main"), token="T")
    second_db = root / "Second" / "altium" / "stockroom-parts.db"
    assert not second_db.exists()

    ctx.switch_profile("Second")

    assert second_db.exists()
