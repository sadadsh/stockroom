"""GitHub authentication uses the configured credential helper, never Git config."""

from __future__ import annotations

import shutil
from types import SimpleNamespace

import pytest

from stockroom.vcs import github_auth
from stockroom.vcs.repo import GitRepo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _repo_with_origin(tmp_path, url: str) -> GitRepo:
    repo = GitRepo(tmp_path)
    repo.init()
    repo._run("remote", "add", "origin", url)
    return repo


def test_configure_scrubs_legacy_header_and_approves_path_scoped_credential(
    tmp_path,
    monkeypatch,
):
    repo = _repo_with_origin(tmp_path, "https://github.com/owner/repo.git")
    repo.set_config(github_auth.EXTRAHEADER_KEY, "AUTHORIZATION: basic LEGACY")
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        github_auth,
        "_run_credential",
        lambda _repo, action, payload: calls.append((action, payload)),
    )

    github_auth.configure(repo, "ghp_TOKEN")

    assert (
        repo._run(
            "config",
            "--get",
            github_auth.EXTRAHEADER_KEY,
            check=False,
        ).returncode
        != 0
    )
    assert repo._run("config", "--get", github_auth.USE_HTTP_PATH_KEY).stdout.strip() == "true"
    assert calls == [
        (
            "approve",
            "protocol=https\n"
            "host=github.com\n"
            "path=owner/repo.git\n"
            "username=x-access-token\n"
            "password=ghp_TOKEN\n\n",
        )
    ]
    assert "ghp_TOKEN" not in (tmp_path / ".git" / "config").read_text(encoding="utf-8")


def test_clearing_rejects_only_the_exact_repository_path(tmp_path, monkeypatch):
    repo = _repo_with_origin(tmp_path, "https://github.com/owner/repo.git")
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        github_auth,
        "_run_credential",
        lambda _repo, action, payload: calls.append((action, payload)),
    )

    github_auth.configure(repo, "")

    assert calls == [
        (
            "reject",
            "protocol=https\nhost=github.com\npath=owner/repo.git\nusername=x-access-token\n\n",
        )
    ]


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:owner/repo.git",
        "https://example.com/owner/repo.git",
    ],
)
def test_non_https_github_remote_only_scrubs_legacy_header(
    tmp_path,
    monkeypatch,
    url,
):
    repo = _repo_with_origin(tmp_path, url)
    repo.set_config(github_auth.EXTRAHEADER_KEY, "AUTHORIZATION: basic LEGACY")
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        github_auth,
        "_run_credential",
        lambda _repo, action, payload: calls.append((action, payload)),
    )

    github_auth.configure(repo, "ghp_TOKEN")

    assert calls == []
    assert (
        repo._run(
            "config",
            "--get",
            github_auth.EXTRAHEADER_KEY,
            check=False,
        ).returncode
        != 0
    )


def test_configure_never_puts_the_token_in_the_remote_url(tmp_path, monkeypatch):
    repo = _repo_with_origin(tmp_path, "https://github.com/owner/repo.git")
    monkeypatch.setattr(github_auth, "_run_credential", lambda *_args: None)

    github_auth.configure(repo, "ghp_SECRET")

    remotes = repo._run("remote", "-v").stdout
    assert "ghp_SECRET" not in remotes


def test_accounts_are_read_from_git_credential_manager_without_a_stockroom_token():
    calls: list[tuple[str, ...]] = []

    class _Repo:
        def _run(self, *args, **_kwargs):
            calls.append(args)
            return SimpleNamespace(returncode=0, stdout="sadadsh\ncollaborator\nsadadsh\n")

    assert github_auth.accounts(_Repo()) == ["collaborator", "sadadsh"]
    assert calls == [("credential-manager", "github", "list", "--no-ui")]


def test_login_delegates_oauth_to_git_credential_manager(monkeypatch):
    calls: list[tuple[str, ...]] = []

    class _Repo:
        def _run(self, *args, **_kwargs):
            calls.append(args)
            return SimpleNamespace(returncode=0, stdout="sadadsh\n")

    repo = _Repo()
    assert github_auth.login(repo) == ["sadadsh"]
    assert calls == [
        ("credential-manager", "github", "login"),
        ("credential-manager", "github", "list", "--no-ui"),
    ]
