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


# -- in-repo library (lives inside the app repo) -------------------------------


def test_ensure_git_isolates_a_library_nested_in_an_unrelated_repo(tmp_path):
    # An ONBOARDED library (open/create) that happens to live inside an unrelated git checkout
    # must get its OWN repo, so its part commits + sync never leak into that unrelated repo
    # (review #3/#6: is_git_repo() would have wrongly bound it to the enclosing repo).
    outer = tmp_path / "projects"
    outer.mkdir()
    GitRepo(outer).init()
    lib = outer / "kicad-lib"
    lib.mkdir()
    onboarding._ensure_git(lib)
    assert (lib / ".git").exists()  # its OWN repo, isolated from the unrelated parent


def test_bootstrap_prefers_in_repo_over_a_placeholder_config(tmp_path, monkeypatch):
    # A machine whose config only holds the auto-created bootstrap placeholder (never onboarded)
    # repoints at the library that ships in the app repo, so the app opens straight on it.
    in_repo = _library(tmp_path / "libraries")
    monkeypatch.setattr("stockroom.store.library_location.IN_REPO_DEFAULT", in_repo)
    placeholder = str(onboarding._bootstrap_dir())
    cfg = MachineConfig(libraries_root=placeholder, onboarded=False)
    root = onboarding.bootstrap_library(cfg)
    assert root == in_repo
    assert cfg.libraries_root == str(in_repo)


def test_bootstrap_prefers_in_repo_when_config_is_unset(tmp_path, monkeypatch):
    in_repo = _library(tmp_path / "libraries")
    monkeypatch.setattr("stockroom.store.library_location.IN_REPO_DEFAULT", in_repo)
    cfg = MachineConfig()  # unset
    assert onboarding.bootstrap_library(cfg) == in_repo


def test_bootstrap_does_not_override_a_real_configured_library(tmp_path, monkeypatch):
    # A config pointing at a REAL library (not the placeholder) is respected even if the in-repo
    # library also exists and onboarding was not completed.
    in_repo = _library(tmp_path / "libraries")
    monkeypatch.setattr("stockroom.store.library_location.IN_REPO_DEFAULT", in_repo)
    chosen = _library(tmp_path / "chosen", "Bench")
    cfg = MachineConfig(active_profile="Bench", libraries_root=str(chosen), onboarded=False)
    assert onboarding.bootstrap_library(cfg) == chosen


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


# -- adversarial-review fix round (M9 review, confirmed findings) --------------


def test_bootstrap_uses_a_distinct_dir_from_the_onboarding_default(tmp_path, monkeypatch):
    # The boot placeholder must NOT occupy default_library_dir(), else a first-run
    # clone/create into the default always collides with it (confirmed HIGH).
    monkeypatch.setattr("stockroom.store.library_location.IN_REPO_DEFAULT", tmp_path / "absent")
    cfg = MachineConfig()
    root = onboarding.bootstrap_library(cfg)
    assert root != onboarding.default_library_dir()
    assert not library_is_initialized(onboarding.default_library_dir())  # left free


def test_clone_default_dest_succeeds_after_bootstrap(tmp_path, monkeypatch):
    # The confirmed HIGH: a default-dest clone on a frozen first run must SUCCEED, not 400.
    monkeypatch.setattr("stockroom.store.library_location.IN_REPO_DEFAULT", tmp_path / "absent")
    src = _library(tmp_path / "remote", "Main")
    cfg = MachineConfig()
    onboarding.bootstrap_library(cfg)  # occupies the placeholder, not the default
    root = onboarding.set_library(cfg, "clone", url=str(src))  # blank dest -> default
    assert root == onboarding.default_library_dir()
    assert library_is_initialized(root) and cfg.onboarded is True


def test_bootstrap_repairs_active_profile_on_existing_library(tmp_path):
    # Confirmed MED: an already-usable library whose profiles do not include this machine's
    # active_profile must have it repaired, or the following build_context crashes at boot.
    lib = _library(tmp_path / "L", "Bench")  # only a Bench profile
    cfg = MachineConfig(active_profile="Main", libraries_root=str(lib))
    root = onboarding.bootstrap_library(cfg)  # must NOT crash
    assert root == lib
    assert cfg.active_profile == "Bench"  # repointed to a profile that exists


def test_create_refuses_a_nonempty_existing_directory(tmp_path):
    # Confirmed MED: create must not write a commit into a user's populated dir/repo.
    d = tmp_path / "occupied"
    d.mkdir()
    (d / "x.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        onboarding.set_library(MachineConfig(), "create", path=d)


def test_create_refuses_an_existing_file_path(tmp_path):
    # Confirmed LOW: a clean 400, not an opaque mkdir 500.
    f = tmp_path / "afile"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        onboarding.set_library(MachineConfig(), "create", path=f)


def test_create_into_a_new_dir_still_works(tmp_path):
    root = onboarding.set_library(MachineConfig(), "create", path=tmp_path / "brand-new")
    assert library_is_initialized(root)


def test_bootstrap_reonboards_when_a_configured_library_went_missing(tmp_path, monkeypatch):
    # Honesty (plausible finding): if the user's configured library is gone, do NOT hand
    # back a fresh empty one as if nothing happened; re-show onboarding.
    monkeypatch.setattr("stockroom.store.library_location.IN_REPO_DEFAULT", tmp_path / "absent")
    missing = tmp_path / "gone"
    cfg = MachineConfig(libraries_root=str(missing), onboarded=True)
    onboarding.bootstrap_library(cfg)
    assert cfg.onboarded is False
