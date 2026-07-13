import pytest

from launcher.gitshim import choose_pull_backend


def test_prefers_git_when_on_path():
    assert choose_pull_backend(which=lambda name: "/usr/bin/git", have_dulwich=False) == "git"


def test_falls_back_to_dulwich_when_no_git():
    assert choose_pull_backend(which=lambda name: None, have_dulwich=True) == "dulwich"


def test_raises_when_neither_available():
    with pytest.raises(RuntimeError):
        choose_pull_backend(which=lambda name: None, have_dulwich=False)
