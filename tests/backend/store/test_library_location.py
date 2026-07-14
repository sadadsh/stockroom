"""M9a: where the library lives on this machine + whether first-run onboarding is needed.

The library location is a per-machine choice (MachineConfig.libraries_root), never baked
into the app: a frozen exe ships no library, so on first run it is unset and the app must
onboard before any library feature works. A source/dev checkout falls back to the in-repo
`libraries/` dir when that exists. Pure, Qt-free."""

from __future__ import annotations

from stockroom.store.library_location import (
    IN_REPO_DEFAULT,
    library_is_initialized,
    needs_onboarding,
    resolve_libraries_root,
)
from stockroom.store.machine_config import MachineConfig


def _profile_lib(root):
    """A minimal usable library on disk: a directory carrying one profile subdir."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "Main").mkdir()
    return root


def test_configured_root_wins(tmp_path):
    lib = tmp_path / "my-library"
    cfg = MachineConfig(libraries_root=str(lib))
    assert resolve_libraries_root(cfg) == lib


def test_configured_root_wins_even_when_in_repo_default_exists(tmp_path):
    # The persisted choice always beats the in-repo dev fallback.
    lib = tmp_path / "chosen"
    cfg = MachineConfig(libraries_root=str(lib))
    assert resolve_libraries_root(cfg) == lib
    assert resolve_libraries_root(cfg) != IN_REPO_DEFAULT


def test_blank_config_falls_back_to_in_repo_default_or_none():
    cfg = MachineConfig()  # libraries_root == ""
    got = resolve_libraries_root(cfg)
    # On a source checkout the in-repo library may exist; beside a frozen exe it does not.
    assert got == (IN_REPO_DEFAULT if IN_REPO_DEFAULT.exists() else None)


def test_whitespace_only_config_is_treated_as_unset(tmp_path):
    cfg = MachineConfig(libraries_root="   ")
    got = resolve_libraries_root(cfg)
    assert got == (IN_REPO_DEFAULT if IN_REPO_DEFAULT.exists() else None)


def test_library_is_initialized_true_for_dir_with_a_profile(tmp_path):
    lib = _profile_lib(tmp_path / "lib")
    assert library_is_initialized(lib) is True


def test_library_is_initialized_false_for_empty_dir(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert library_is_initialized(empty) is False


def test_library_is_initialized_ignores_dot_dirs(tmp_path):
    # A bare git repo with only `.git` (no profile) is not yet a usable library.
    lib = tmp_path / "bare"
    lib.mkdir()
    (lib / ".git").mkdir()
    assert library_is_initialized(lib) is False


def test_library_is_initialized_false_for_missing_or_none(tmp_path):
    assert library_is_initialized(tmp_path / "nope") is False
    assert library_is_initialized(None) is False


def test_needs_onboarding_true_when_unset_and_no_usable_default(monkeypatch, tmp_path):
    # Force the in-repo default to a nonexistent path so this is deterministic on any box.
    monkeypatch.setattr("stockroom.store.library_location.IN_REPO_DEFAULT", tmp_path / "absent")
    assert needs_onboarding(MachineConfig()) is True


def test_needs_onboarding_false_when_configured_library_is_initialized(tmp_path):
    lib = _profile_lib(tmp_path / "lib")
    assert needs_onboarding(MachineConfig(libraries_root=str(lib))) is False


def test_needs_onboarding_true_when_configured_root_is_empty(tmp_path):
    # A configured-but-empty root (e.g. a fresh clone that has no profiles) still onboards.
    empty = tmp_path / "empty"
    empty.mkdir()
    assert needs_onboarding(MachineConfig(libraries_root=str(empty))) is True
