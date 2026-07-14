"""M9b: first-run library onboarding (open / clone / create) + boot bootstrap.

Each mode ends the same way: a git-backed dir carrying a profile, its path persisted, and
onboarded set. bootstrap_library guarantees the server can always boot without completing
onboarding. All offline (clone copies a local source repo)."""

from __future__ import annotations

import shutil

import pytest

from stockroom.store import onboarding
from stockroom.store.library_location import library_is_initialized
from stockroom.store.machine_config import MachineConfig
from stockroom.store.profile import ProfileStore
from stockroom.vcs.repo import GitRepo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    # Keep config.save()/load() and default_library_dir() inside the test's tmp dir.
    monkeypatch.setenv("STOCKROOM_CONFIG_DIR", str(tmp_path / "cfg"))


def _library(root, profile="Main"):
    root.mkdir(parents=True, exist_ok=True)
    repo = GitRepo(root)
    repo.init()
    ProfileStore(root, repo).create(profile)  # create() commits, so a clone has content
    return root


# -- create --------------------------------------------------------------------


def test_create_makes_git_repo_with_profile_and_persists(tmp_path):
    cfg = MachineConfig()
    root = onboarding.set_library(cfg, "create", path=tmp_path / "new")
    assert root == tmp_path / "new"
    assert (root / ".git").exists()
    assert library_is_initialized(root)
    assert cfg.libraries_root == str(root)
    assert cfg.onboarded is True
    assert MachineConfig.load().libraries_root == str(root)  # persisted to disk


def test_create_uses_default_location_when_no_path():
    cfg = MachineConfig()
    root = onboarding.set_library(cfg, "create")
    assert root == onboarding.default_library_dir()
    assert library_is_initialized(root)


# -- open ----------------------------------------------------------------------


def test_open_existing_library_persists(tmp_path):
    lib = _library(tmp_path / "L", "Main")
    cfg = MachineConfig()
    root = onboarding.set_library(cfg, "open", path=lib)
    assert root == lib and cfg.libraries_root == str(lib) and cfg.onboarded is True


def test_open_missing_dir_raises(tmp_path):
    with pytest.raises(ValueError):
        onboarding.set_library(MachineConfig(), "open", path=tmp_path / "nope")


def test_open_dir_without_a_profile_bootstraps_one(tmp_path):
    bare = tmp_path / "bare"
    bare.mkdir()
    root = onboarding.set_library(MachineConfig(), "open", path=bare)
    assert library_is_initialized(root)  # a profile was created + it became git-backed
    assert (root / ".git").exists()


def test_open_repoints_active_profile_to_one_that_exists(tmp_path):
    lib = _library(tmp_path / "L", "Bench")  # only a Bench profile
    cfg = MachineConfig(active_profile="Main")  # this machine's active is not there
    onboarding.set_library(cfg, "open", path=lib)
    assert cfg.active_profile == "Bench"


# -- clone ---------------------------------------------------------------------


def test_clone_from_local_source_repo(tmp_path):
    src = _library(tmp_path / "remote", "Main")
    cfg = MachineConfig()
    root = onboarding.set_library(cfg, "clone", url=str(src), dest=tmp_path / "cloned")
    assert root == tmp_path / "cloned"
    assert library_is_initialized(root) and cfg.onboarded is True


def test_clone_requires_a_url():
    with pytest.raises(ValueError):
        onboarding.set_library(MachineConfig(), "clone", url="")


def test_clone_refuses_nonempty_destination(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "stuff.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        onboarding.set_library(MachineConfig(), "clone", url="anything", dest=dest)


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        onboarding.set_library(MachineConfig(), "teleport")


# -- bootstrap + complete ------------------------------------------------------


def test_bootstrap_creates_default_when_nothing_usable(tmp_path, monkeypatch):
    # No configured library and no in-repo default -> a default is auto-created so the
    # server can boot, but onboarding is NOT marked complete (the welcome still shows).
    monkeypatch.setattr("stockroom.store.library_location.IN_REPO_DEFAULT", tmp_path / "absent")
    cfg = MachineConfig()
    root = onboarding.bootstrap_library(cfg)
    assert library_is_initialized(root)
    assert cfg.onboarded is False
    assert cfg.libraries_root == str(root)


def test_bootstrap_returns_existing_usable_library_untouched(tmp_path):
    lib = _library(tmp_path / "L", "Main")
    cfg = MachineConfig(libraries_root=str(lib))
    root = onboarding.bootstrap_library(cfg)
    assert root == lib and cfg.onboarded is False


def test_complete_onboarding_sets_and_persists_flag():
    cfg = MachineConfig()
    onboarding.complete_onboarding(cfg)
    assert cfg.onboarded is True
    assert MachineConfig.load().onboarded is True
