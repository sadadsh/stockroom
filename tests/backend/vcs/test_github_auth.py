"""GitHub PAT auth for a repo's git operations: inject the token as a per-repo, github-scoped
http extraheader (never in the remote URL, never committed), so push/pull authenticate."""

from __future__ import annotations

import base64
import shutil

import pytest

from stockroom.vcs import github_auth
from stockroom.vcs.repo import GitRepo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def test_auth_header_is_basic_base64_of_the_token():
    h = github_auth.auth_header("ghp_ABC123")
    assert h.lower().startswith("authorization: basic ")
    decoded = base64.b64decode(h.split()[-1]).decode()
    assert decoded == "x-access-token:ghp_ABC123"  # the token is the basic-auth password


def test_extraheader_key_scopes_to_github_only():
    # the credential is bound to https://github.com/ so it is never sent to another host
    assert github_auth.EXTRAHEADER_KEY == "http.https://github.com/.extraheader"


def test_configure_sets_then_clears_the_github_credential(tmp_path):
    repo = GitRepo(tmp_path)
    repo.init()
    github_auth.configure(repo, "ghp_TOKEN")
    got = repo._run("config", "--get", github_auth.EXTRAHEADER_KEY).stdout.strip()
    assert base64.b64decode(got.split()[-1]).decode() == "x-access-token:ghp_TOKEN"
    # a blank token removes the header (idempotent: absent is fine)
    github_auth.configure(repo, "")
    assert repo._run("config", "--get", github_auth.EXTRAHEADER_KEY, check=False).returncode != 0
    github_auth.configure(repo, "")  # a second clear does not raise


def test_configure_is_not_in_the_remote_url(tmp_path):
    # the token lives in an extraheader, NOT baked into origin, so `git remote -v` never leaks it
    repo = GitRepo(tmp_path)
    repo.init()
    repo._run("remote", "add", "origin", "https://github.com/owner/repo.git")
    github_auth.configure(repo, "ghp_SECRET")
    remotes = repo._run("remote", "-v").stdout
    assert "ghp_SECRET" not in remotes
