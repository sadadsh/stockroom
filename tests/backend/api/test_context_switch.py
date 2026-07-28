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


def _profile_tree(root):
    profile = root / "Main"
    return {
        path.relative_to(profile): (path.is_dir(), b"" if path.is_dir() else path.read_bytes())
        for path in profile.rglob("*")
    }


def test_building_an_empty_context_is_read_only_for_canonical_profile_data(tmp_path):
    """One integrated boot invariant covers every EDA adapter and future derived artifact.

    KiCad category libraries and an Altium SQLite/DbLib pair were each observed being recreated by
    a native host launch after the owner intentionally emptied the library. Machine wiring and
    operational indexes may change elsewhere; the canonical profile tree must remain byte-exact.
    """

    root = _library(tmp_path / "empty")
    before = _profile_tree(root)

    ctx = build_context(
        root,
        kicad_dir=tmp_path / "kicad",
        config=MachineConfig(active_profile="Main"),
        token="T",
    )
    ctx.close()

    assert _profile_tree(root) == before


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


def test_opening_an_empty_library_does_not_materialize_altium_files(tmp_path):
    """Read/boot is not publication. A native-host inspection regenerated an SQLite/DbLib pair
    immediately after the owner intentionally emptied the canonical library. With no published
    entries there is nothing for Altium to place and therefore no derived artifact to activate."""
    root = _library(tmp_path / "fresh")
    db = root / "Main" / "altium" / "stockroom-parts.db"
    assert not db.exists()

    build_context(root, kicad_dir=tmp_path / "k", config=MachineConfig(active_profile="Main"),
                  token="T")

    assert not db.exists()
    assert not (db.parent / "Stockroom.DbLib").exists()


def test_switching_to_an_empty_profile_does_not_materialize_altium_files(tmp_path):
    """A profile switch repoints machine state but does not publish nonexistent entry data."""
    root = _library(tmp_path / "multi")
    repo = GitRepo(root)
    ProfileStore(root, repo).create("Second")
    ctx = build_context(root, kicad_dir=tmp_path / "k",
                        config=MachineConfig(active_profile="Main"), token="T")
    second_db = root / "Second" / "altium" / "stockroom-parts.db"
    assert not second_db.exists()

    ctx.switch_profile("Second")

    assert not second_db.exists()
    assert not (second_db.parent / "Stockroom.DbLib").exists()
