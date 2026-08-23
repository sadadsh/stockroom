from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from stockroom.store import guided_setup


class _Config(SimpleNamespace):
    def save(self):
        self.saves = getattr(self, "saves", 0) + 1


class _Repo:
    def __init__(self, remote: str = "") -> None:
        self.remote = remote

    def remote_url(self, name: str = "origin") -> str:
        assert name == "origin"
        return self.remote


def _ctx(tmp_path: Path, *, primary: str = "kicad", remote: str = ""):
    profile = tmp_path / "catalog" / "Stockroom"
    profile.mkdir(parents=True)
    config = _Config(
        primary_eda=primary,
        primary_eda_pending="",
        guided_setup={},
        mouser_api_key="",
        digikey_client_id="",
        digikey_client_secret="",
    )
    return SimpleNamespace(
        config=config,
        repo=_Repo(remote),
        cli=SimpleNamespace(available=True),
        kicad_dir=tmp_path / "kicad",
        profile=SimpleNamespace(root=profile),
        last_wiring=None,
    )


def _github(*, authenticated: bool = True, online: bool = True):
    return {
        "available": True,
        "authenticated": authenticated,
        "online": online,
        "viewer": "engineer",
        "owners": [{"login": "engineer", "kind": "user"}],
        "verified_repository": {
            "owner": "engineer",
            "name": "stockroom-catalog",
            "url": "https://github.com/engineer/stockroom-catalog",
            "visibility": "private",
            "writable": True,
        },
    }


def _wire(ctx) -> None:
    ctx.kicad_dir.mkdir(parents=True, exist_ok=True)
    (ctx.kicad_dir / "kicad_common.json").write_text(
        json.dumps({"environment": {"vars": {"SR_LIB": str(ctx.profile.root.resolve())}}}),
        encoding="utf-8",
    )


def test_step_order_has_only_the_three_required_setup_decisions(tmp_path):
    ctx = _ctx(tmp_path, primary="", remote="")
    assert guided_setup.status(ctx, _github())["step"] == "choose_cad_tool"

    ctx.config.primary_eda = "kicad"
    assert guided_setup.status(ctx, _github())["step"] == "catalog_repository"

    ctx.repo.remote = "https://github.com/engineer/stockroom-catalog.git"
    assert guided_setup.status(ctx, _github())["step"] == "connect_the_tool"

    _wire(ctx)
    document = guided_setup.status(ctx, _github())
    assert document["step"] == "ready"
    assert document["ready"] is True
    assert document["steps"] == [
        "choose_cad_tool",
        "catalog_repository",
        "connect_the_tool",
    ]
    assert document["source_data"]["decided"] is False


def test_current_github_auth_and_connectivity_are_required_even_after_progress(tmp_path):
    ctx = _ctx(
        tmp_path,
        remote="https://github.com/engineer/stockroom-catalog.git",
    )
    _wire(ctx)
    guided_setup.record_source_decision(ctx.config, skipped=True)

    assert guided_setup.status(ctx, _github(authenticated=False))["step"] == "catalog_repository"
    assert guided_setup.status(ctx, _github(online=False))["step"] == "catalog_repository"


def test_read_only_repository_never_becomes_ready(tmp_path):
    ctx = _ctx(
        tmp_path,
        remote="https://github.com/engineer/stockroom-catalog.git",
    )
    github = _github()
    github["verified_repository"]["writable"] = False

    document = guided_setup.status(ctx, github)

    assert document["repository_ready"] is False
    assert document["step"] == "catalog_repository"


def test_repository_requires_a_credential_free_github_https_origin(tmp_path):
    ctx = _ctx(tmp_path, remote="https://token@github.com/engineer/catalog.git")
    assert guided_setup.status(ctx, _github())["repository"] is None

    ctx.repo.remote = "git@github.com:engineer/catalog.git"
    assert guided_setup.status(ctx, _github())["repository"] is None


def test_primary_change_clears_only_the_tool_receipt(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.config.guided_setup = {
        "schema": 1,
        "repository": {"owner": "engineer"},
        "tool_connection": {"tool": "kicad", "receipt": {"verified": True}},
        "source_data": {"decided": True, "skipped": True},
    }

    guided_setup.clear_after_primary_change(ctx.config)

    assert "tool_connection" not in ctx.config.guided_setup
    assert ctx.config.guided_setup["repository"] == {"owner": "engineer"}
    assert ctx.config.guided_setup["source_data"]["decided"] is True


def test_repository_and_tool_receipts_contain_no_secret_material(tmp_path):
    ctx = _ctx(tmp_path)
    guided_setup.record_repository(
        ctx.config,
        owner="engineer",
        name="stockroom-catalog",
        visibility="private",
        url="https://github.com/engineer/stockroom-catalog.git",
    )
    guided_setup.record_tool_connection(
        ctx.config,
        tool="kicad",
        receipt={"verified": True, "restart_required": False},
    )

    encoded = json.dumps(ctx.config.guided_setup, sort_keys=True)
    assert "token" not in encoded.casefold()
    assert "password" not in encoded.casefold()
    assert ctx.config.guided_setup["repository"]["visibility"] == "private"
