"""Auto-push on a library write: adding / editing a part pushes it to the remote when a GitHub
token is configured (so a part lands in git immediately and collaborators get it on next launch),
and is a quiet no-op without a token or with sync disabled (the commit still stands locally)."""

from __future__ import annotations

import shutil
import subprocess

import pytest

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _origin_with_upstream(repo, tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True)
    root = str(repo.root)
    subprocess.run(["git", "-C", root, "remote", "add", "origin", str(origin)], check=True, capture_output=True)
    subprocess.run(["git", "-C", root, "push", "-u", "origin", "HEAD:main"], check=True, capture_output=True)
    return origin


def _head(repo_path):
    return subprocess.run(["git", "-C", str(repo_path), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


def _add_local_commit(repo, name):
    p = repo.root / name
    p.write_text("{}", encoding="utf-8")
    repo.commit(f"add {name}", [p])


def test_auto_push_pushes_a_write_when_a_token_is_set(app_ctx, tmp_path):
    origin = _origin_with_upstream(app_ctx.repo, tmp_path)
    app_ctx.config.github_token = "tok"
    app_ctx.config.sync_enabled = True
    _add_local_commit(app_ctx.repo, "newpart.json")
    before = _head(origin)
    app_ctx.auto_push()
    assert _head(origin) != before  # the commit reached the remote


def test_auto_push_is_a_noop_without_a_token(app_ctx, tmp_path):
    origin = _origin_with_upstream(app_ctx.repo, tmp_path)
    app_ctx.config.github_token = ""  # no credential yet
    _add_local_commit(app_ctx.repo, "p2.json")
    before = _head(origin)
    app_ctx.auto_push()  # never pushes, never raises
    assert _head(origin) == before


def test_auto_push_is_a_noop_when_sync_disabled(app_ctx, tmp_path):
    origin = _origin_with_upstream(app_ctx.repo, tmp_path)
    app_ctx.config.github_token = "tok"
    app_ctx.config.sync_enabled = False
    _add_local_commit(app_ctx.repo, "p3.json")
    before = _head(origin)
    app_ctx.auto_push()
    assert _head(origin) == before


def test_auto_push_never_raises_without_a_remote(app_ctx):
    app_ctx.config.github_token = "tok"
    app_ctx.config.sync_enabled = True
    app_ctx.auto_push()  # no remote configured -> honest no-op, never a crash
