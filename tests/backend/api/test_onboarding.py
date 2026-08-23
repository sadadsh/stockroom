"""M9b: the onboarding API (status, set-library open/create/clone) with a LIVE engine
repoint, and complete. Uses the standard api conftest client (token-authed, config isolated
to the test's tmp dir)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from stockroom.store.profile import ProfileStore
from stockroom.vcs.github_cli import GitHubOwner, GitHubRepository, GitHubViewer
from stockroom.vcs.repo import GitRepo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _library(root, profile="Main"):
    root.mkdir(parents=True, exist_ok=True)
    repo = GitRepo(root)
    repo.init()
    ProfileStore(root, repo).create(profile)
    return root


def test_github_status_distinguishes_sign_in_from_an_outage():
    from stockroom.api.routers.onboarding import _github_status
    from stockroom.vcs.github_cli import GitHubCliAvailability, GitHubCliError

    class SignedOut:
        def availability(self):
            return GitHubCliAvailability(True, "2.95.0")

        def authenticated(self):
            return False

    signed_out = _github_status(SignedOut())
    assert signed_out["authenticated"] is False
    assert signed_out["online"] is True
    assert "Sign in" in signed_out["error"]

    class Offline(SignedOut):
        def authenticated(self):
            return True

        def viewer(self):
            raise GitHubCliError("sanitized")

    offline = _github_status(Offline())
    assert offline["authenticated"] is True
    assert offline["online"] is False
    assert "retry automatically" in offline["error"]

    class AuthProbeOffline(SignedOut):
        def authenticated(self):
            raise GitHubCliError("sanitized")

    auth_probe_offline = _github_status(AuthProbeOffline())
    assert auth_probe_offline["authenticated"] is False
    assert auth_probe_offline["online"] is False
    assert "retry automatically" in auth_probe_offline["error"]


def test_github_login_streams_the_device_code_without_a_token(client, monkeypatch):
    class Authority:
        def login_browser(self, *, on_code):
            on_code("ABCD-EFGH")
            return GitHubViewer(login="engineer", name=None)

        def owners(self):
            return (GitHubOwner(login="engineer", kind="personal"),)

    monkeypatch.setattr("stockroom.api.routers.onboarding.GitHubCli", Authority)

    started = client.post("/api/onboarding/github/login")
    assert started.status_code == 200
    with client.stream(
        "GET",
        f"/api/jobs/{started.json()['job_id']}/events",
    ) as stream:
        events = "".join(stream.iter_text())

    assert '"user_code": "ABCD-EFGH"' in events
    assert '"verification_uri": "https://github.com/login/device"' in events
    assert "token" not in events.casefold()


def test_status_reports_current_library(client):
    d = client.get("/api/onboarding").json()
    assert d["libraries_root"].endswith("/libraries")  # the fixture library root
    assert d["profiles"] == ["Main"]
    assert d["under_git"] is True
    assert set(d) >= {
        "onboarded",
        "first_run",
        "libraries_root",
        "profiles",
        "under_git",
        "default_dir",
        "primary_eda",
        "primary_eda_pending",
        "primary_eda_confirmation_required",
        "recommended_primary_eda",
        "primary_eda_requirements",
        "retained_optional_eda",
        "eda_tools",
    }
    assert d["primary_eda"] is None
    assert d["primary_eda_confirmation_required"] is True


def test_status_never_treats_an_application_repo_library_as_onboarded(
    client, app_ctx, monkeypatch
):
    app_ctx.config.onboarded = False
    monkeypatch.setattr(
        "stockroom.store.library_location.IN_REPO_DEFAULT", Path(app_ctx.libraries_root)
    )
    d = client.get("/api/onboarding").json()
    assert d["onboarded"] is False and d["first_run"] is True
    assert d["under_git"] is True


def test_status_requires_token(anon_client):
    assert anon_client.get("/api/onboarding").status_code == 401


def test_set_library_open_repoints_engine_live(client, app_ctx, tmp_path):
    app_ctx.config.primary_eda = "kicad"
    other = _library(tmp_path / "other", "Bench")
    r = client.post("/api/onboarding/library", json={"mode": "open", "path": str(other)})
    assert r.status_code == 200
    d = r.json()
    assert d["libraries_root"] == other.as_posix()
    assert d["profiles"] == ["Bench"]
    assert d["onboarded"] is False
    assert d["libraries"] == [
        {
            "name": "other",
            "path": other.as_posix(),
            "active": True,
            "available": True,
            "under_git": True,
        }
    ]
    # the running context actually repointed (in place), and the token still authenticates
    assert app_ctx.libraries_root == other
    assert client.get("/api/onboarding").json()["libraries_root"] == other.as_posix()


def test_set_library_create_makes_a_fresh_library(client, app_ctx, tmp_path):
    app_ctx.config.primary_eda = "kicad"
    dest = tmp_path / "fresh"
    r = client.post("/api/onboarding/library", json={"mode": "create", "path": str(dest)})
    assert r.status_code == 200
    assert (dest / ".git").exists()
    assert r.json()["libraries_root"] == dest.as_posix()


def test_set_library_rejects_unconfirmed_primary_eda(client, app_ctx, tmp_path):
    app_ctx.config.primary_eda = ""
    destination = tmp_path / "fresh"

    response = client.post(
        "/api/onboarding/library",
        json={"mode": "create", "path": str(destination)},
    )

    assert response.status_code == 400
    assert not destination.exists()
    assert app_ctx.config.onboarded is False


def test_set_library_open_missing_dir_is_400(client, tmp_path):
    r = client.post("/api/onboarding/library",
                    json={"mode": "open", "path": str(tmp_path / "nope")})
    assert r.status_code == 400


def test_set_library_unknown_mode_is_400(client):
    assert client.post("/api/onboarding/library", json={"mode": "teleport"}).status_code == 400


def test_legacy_onboarded_machine_still_requires_explicit_guided_setup_completion(
    client, app_ctx
):
    app_ctx.config.onboarded = True
    app_ctx.config.primary_eda = ""

    status = client.get("/api/onboarding").json()

    assert status["onboarded"] is False
    assert status["first_run"] is True
    assert status["primary_eda"] is None
    assert status["primary_eda_confirmation_required"] is True
    assert status["recommended_primary_eda"] in {"kicad", "altium", None}


def test_completion_rejects_an_unconfirmed_primary_eda(client, app_ctx):
    app_ctx.config.primary_eda = ""

    response = client.post("/api/onboarding/complete")

    assert response.status_code == 400
    assert app_ctx.config.onboarded is False


def test_complete_marks_onboarded_only_after_authoritative_readiness(
    client, app_ctx, monkeypatch
):
    app_ctx.config.primary_eda = "kicad"
    monkeypatch.setattr(
        "stockroom.api.routers.onboarding.guided_setup.status",
        lambda *_args, **_kwargs: {"ready": True, "step": "ready"},
    )
    r = client.post("/api/onboarding/complete")
    assert r.status_code == 200 and r.json()["onboarded"] is True
    assert app_ctx.config.onboarded is True
    assert app_ctx.config.guided_setup["completed"] is True


def test_complete_revalidates_the_exact_repository_without_mocking_readiness(
    client, app_ctx, monkeypatch
):
    from stockroom.store import guided_setup

    app_ctx.config.primary_eda = "kicad"
    app_ctx.repo._run(
        "remote",
        "add",
        "origin",
        "https://github.com/engineer/stockroom-catalog.git",
    )
    guided_setup.record_source_decision(app_ctx.config, skipped=True)
    monkeypatch.setattr(
        guided_setup,
        "current_tool_connection",
        lambda _ctx: {
            "tool": "kicad",
            "installed": True,
            "connected": True,
            "restart_required": False,
            "detail": "KiCad is connected.",
        },
    )
    observed = []

    def github_status(_cli=None, *, repository=None):
        observed.append(repository)
        return {
            "available": True,
            "authenticated": True,
            "online": True,
            "verified_repository": {
                "owner": "engineer",
                "name": "stockroom-catalog",
                "visibility": "private",
                "writable": True,
            },
        }

    monkeypatch.setattr(
        "stockroom.api.routers.onboarding._github_status",
        github_status,
    )

    response = client.post("/api/onboarding/complete")

    assert response.status_code == 200
    assert app_ctx.config.onboarded is True
    assert app_ctx.config.guided_setup["completed"] is True
    assert observed[0] == {
        "owner": "engineer",
        "name": "stockroom-catalog",
        "url": "https://github.com/engineer/stockroom-catalog.git",
    }


def test_complete_refuses_a_partial_guided_setup(client, app_ctx, monkeypatch):
    app_ctx.config.primary_eda = "kicad"
    monkeypatch.setattr(
        "stockroom.api.routers.onboarding.guided_setup.status",
        lambda *_args, **_kwargs: {"ready": False, "step": "catalog_repository"},
    )

    response = client.post("/api/onboarding/complete")

    assert response.status_code == 400
    assert "catalog_repository" in response.json()["detail"]
    assert app_ctx.config.onboarded is False


def test_guided_mutations_refuse_to_overlap_tool_setup(client, app_ctx, tmp_path):
    from stockroom.api.routers.onboarding import _TOOL_SETUP_LOCK

    app_ctx.config.primary_eda = "kicad"
    assert _TOOL_SETUP_LOCK.acquire(blocking=False)
    try:
        repository = client.post(
            "/api/onboarding/repository",
            json={
                "mode": "connect",
                "owner": "engineer",
                "name": "catalog",
                "path": str(tmp_path / "catalog"),
            },
        )
        switch = client.patch("/api/settings", json={"primary_eda": "altium"})
    finally:
        _TOOL_SETUP_LOCK.release()

    assert repository.status_code == 409
    assert switch.status_code == 409
    assert app_ctx.config.primary_eda == "kicad"


def test_guided_repository_preserves_an_occupied_folder_and_uses_a_safe_sibling(
    client, app_ctx, tmp_path, monkeypatch
):
    app_ctx.config.primary_eda = "kicad"
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "person-owned.txt").write_text("keep", encoding="utf-8")
    repository = GitHubRepository(
        owner="engineer",
        name="stockroom-catalog",
        url="https://github.com/engineer/stockroom-catalog.git",
        visibility="private",
        permission="admin",
    )

    class Authority:
        def create_repository(self, owner, name, *, visibility):
            return repository

        def clone_repository(self, owner, name, destination):
            assert (owner, name) == ("engineer", "stockroom-catalog")
            _library(destination, "Main")

    monkeypatch.setattr("stockroom.api.routers.onboarding.GitHubCli", Authority)
    monkeypatch.setattr(
        "stockroom.api.routers.onboarding._github_status",
        lambda *_args, **_kwargs: {
            "available": True,
            "authenticated": True,
            "online": True,
            "viewer": {"login": "engineer", "name": None},
            "owners": [{"login": "engineer", "kind": "personal"}],
        },
    )

    response = client.post(
        "/api/onboarding/repository",
        json={
            "mode": "create",
            "owner": "engineer",
            "name": "stockroom-catalog",
            "visibility": "private",
            "path": str(occupied),
        },
    )

    assert response.status_code == 200
    assert (occupied / "person-owned.txt").read_text(encoding="utf-8") == "keep"
    assert app_ctx.libraries_root == tmp_path / "stockroom-catalog"


def test_guided_repository_create_switches_only_after_github_returns_identity(
    client, app_ctx, tmp_path, monkeypatch
):
    app_ctx.config.primary_eda = "kicad"
    selected = tmp_path / "catalog"
    repository = GitHubRepository(
        owner="engineer",
        name="stockroom-catalog",
        url="https://github.com/engineer/stockroom-catalog.git",
        visibility="private",
        permission="admin",
    )

    class Authority:
        def create_repository(self, owner, name, *, visibility):
            assert (owner, name, visibility) == (
                "engineer",
                "stockroom-catalog",
                "private",
            )
            return repository

        def clone_repository(self, owner, name, destination):
            observed["clone"] = (owner, name, destination)
            _library(destination, "Main")

    observed = {}

    def prepare(config, mode, **options):
        observed["prepare"] = (mode, options)
        return selected

    monkeypatch.setattr("stockroom.api.routers.onboarding.GitHubCli", Authority)
    monkeypatch.setattr("stockroom.api.routers.onboarding.onb.set_library", prepare)
    monkeypatch.setattr(
        "stockroom.api.routers.onboarding._github_status",
        lambda *_args, **_kwargs: {
            "available": True,
            "authenticated": True,
            "online": True,
            "viewer": {"login": "engineer", "name": None},
            "owners": [{"login": "engineer", "kind": "personal"}],
        },
    )

    response = client.post(
        "/api/onboarding/repository",
        json={
            "mode": "create",
            "owner": "engineer",
            "name": "stockroom-catalog",
            "visibility": "private",
            "path": str(selected),
        },
    )

    assert response.status_code == 200, response.json()
    assert observed == {
        "clone": ("engineer", "stockroom-catalog", selected.resolve()),
        "prepare": ("open", {"path": selected.resolve(), "complete": False}),
    }
    assert app_ctx.libraries_root == selected
    assert app_ctx.config.guided_setup["repository"] == {
        "owner": "engineer",
        "name": "stockroom-catalog",
        "visibility": "private",
        "url": repository.url,
    }
    assert app_ctx.config.onboarded is False


def test_guided_private_repository_clones_through_signed_in_github_cli(
    client, app_ctx, tmp_path, monkeypatch
):
    app_ctx.config.primary_eda = "kicad"
    selected = tmp_path / "Mainline"
    repository = GitHubRepository(
        owner="sadadsh",
        name="Mainline-Components",
        url="https://github.com/sadadsh/Mainline-Components.git",
        visibility="private",
        permission="admin",
    )
    observed: dict[str, object] = {}

    class Authority:
        def repository(self, owner, name):
            assert (owner, name) == ("sadadsh", "Mainline-Components")
            return repository

        def clone_repository(self, owner, name, destination):
            observed["clone"] = (owner, name, destination)
            _library(destination, "Main")

    def prepare(config, mode, **options):
        observed["prepare"] = (mode, options)
        if not selected.exists():
            _library(selected, "Main")
        return selected

    monkeypatch.setattr("stockroom.api.routers.onboarding.GitHubCli", Authority)
    monkeypatch.setattr("stockroom.api.routers.onboarding.onb.set_library", prepare)
    monkeypatch.setattr(
        "stockroom.api.routers.onboarding._github_status",
        lambda *_args, **_kwargs: {
            "available": True,
            "authenticated": True,
            "online": True,
            "viewer": {"login": "sadadsh", "name": None},
            "owners": [{"login": "sadadsh", "kind": "personal"}],
        },
    )

    response = client.post(
        "/api/onboarding/repository",
        json={
            "mode": "connect",
            "owner": "sadadsh",
            "name": "Mainline-Components",
            "path": str(selected),
        },
    )

    assert response.status_code == 200, response.json()
    assert observed == {
        "clone": ("sadadsh", "Mainline-Components", selected.resolve()),
        "prepare": ("open", {"path": selected.resolve(), "complete": False}),
    }


def test_read_only_repository_is_rejected_before_local_mutation(
    client, app_ctx, tmp_path, monkeypatch
):
    app_ctx.config.primary_eda = "kicad"
    selected = tmp_path / "catalog"
    repository = GitHubRepository(
        owner="engineer",
        name="stockroom-catalog",
        url="https://github.com/engineer/stockroom-catalog.git",
        visibility="private",
        permission="read",
    )

    class Authority:
        def repository(self, owner, name):
            return repository

    monkeypatch.setattr("stockroom.api.routers.onboarding.GitHubCli", Authority)
    monkeypatch.setattr(
        "stockroom.api.routers.onboarding.onb.set_library",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("read-only repository must not mutate local state")
        ),
    )

    response = client.post(
        "/api/onboarding/repository",
        json={
            "mode": "connect",
            "owner": "engineer",
            "name": "stockroom-catalog",
            "path": str(selected),
        },
    )

    assert response.status_code == 400
    assert "write permission" in response.json()["detail"]
    assert app_ctx.libraries_root != selected
    assert "repository" not in app_ctx.config.guided_setup


def test_connect_selected_kicad_runs_as_a_job_and_records_verified_receipt(
    client, app_ctx, monkeypatch
):
    app_ctx.config.primary_eda = "kicad"
    monkeypatch.setattr(app_ctx, "rewire_kicad", lambda: None)
    submitted_write_lanes = []
    original_submit = app_ctx.jobs.submit

    def submit(fn, *, write=False):
        submitted_write_lanes.append(write)
        return original_submit(fn, write=write)

    monkeypatch.setattr(app_ctx.jobs, "submit", submit)
    monkeypatch.setattr(
        "stockroom.api.routers.onboarding.guided_setup.current_tool_connection",
        lambda _ctx: {
            "tool": "kicad",
            "installed": True,
            "connected": True,
            "restart_required": True,
            "detail": "KiCad is connected.",
        },
    )

    started = client.post("/api/onboarding/tool/connect")
    assert started.status_code == 200
    with client.stream(
        "GET",
        f"/api/jobs/{started.json()['job_id']}/events",
    ) as stream:
        events = "".join(stream.iter_text())

    assert '"verified": true' in events
    assert submitted_write_lanes == [True]
    assert app_ctx.config.guided_setup["tool_connection"] == {
        "tool": "kicad",
        "receipt": {"verified": True, "restart_required": True},
    }
    assert app_ctx.config.guided_setup["completed"] is True
    assert app_ctx.config.onboarded is True


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"mouser_api_key": "   "},
        {"digikey_client_id": "client-only"},
        {"digikey_client_secret": "secret-only"},
    ],
)
def test_source_data_requires_complete_credentials_or_explicit_skip(
    client, payload
):
    response = client.post("/api/onboarding/source-data", json=payload)
    assert response.status_code == 400


def test_source_data_validates_credentials_before_persisting(
    client, app_ctx, monkeypatch
):
    monkeypatch.setattr(
        "stockroom.enrich.mouser.validate_api_key",
        lambda key: "ok" if key == "valid-mouser" else "auth_error",
    )

    rejected = client.post(
        "/api/onboarding/source-data",
        json={"mouser_api_key": "invalid"},
    )
    assert rejected.status_code == 400
    assert app_ctx.config.mouser_api_key == ""

    accepted = client.post(
        "/api/onboarding/source-data",
        json={"mouser_api_key": "valid-mouser"},
    )
    assert accepted.status_code == 200
    assert app_ctx.config.mouser_api_key == "valid-mouser"


def test_source_data_skip_is_persisted_without_credentials(client, app_ctx, monkeypatch):
    monkeypatch.setattr(
        "stockroom.api.routers.onboarding._github_status",
        lambda *_args, **_kwargs: {
            "available": True,
            "authenticated": False,
            "online": True,
        },
    )

    response = client.post(
        "/api/onboarding/source-data",
        json={"skipped": True},
    )

    assert response.status_code == 200
    assert app_ctx.config.guided_setup["source_data"] == {
        "decided": True,
        "skipped": True,
    }


def test_guided_repository_body_has_no_typed_url_escape_hatch(client, app_ctx, tmp_path):
    app_ctx.config.primary_eda = "kicad"
    response = client.post(
        "/api/onboarding/repository",
        json={
            "mode": "connect",
            "owner": "engineer",
            "name": "stockroom-catalog",
            "path": str(tmp_path / "catalog"),
            "url": "https://example.invalid/person-typed",
        },
    )
    assert response.status_code == 422
