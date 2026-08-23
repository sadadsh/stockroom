from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from stockroom.vcs.github_cli import (
    GitHubCli,
    GitHubCliError,
    GitHubOwner,
    GitHubRepository,
    GitHubViewer,
    credential_free_clone_url,
    resolve_github_cli,
    validate_owner_repository,
)


class ScriptedRunner:
    def __init__(self, *results: subprocess.CompletedProcess[str]) -> None:
        self.results = list(results)
        self.calls: list[tuple[list[str], str | None, float]] = []

    def __call__(
        self,
        argv,
        *,
        input_text: str | None = None,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(argv), input_text, timeout))
        return self.results.pop(0)


def _result(stdout: str = "", *, returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def _repo_json(
    owner: str = "sadadsh",
    name: str = "Stockroom-Catalog",
    visibility: str = "PRIVATE",
) -> str:
    return json.dumps(
        {
            "name": name,
            "url": f"https://github.com/{owner}/{name}",
            "visibility": visibility,
            "viewerPermission": "ADMIN",
            "ignored": "not returned",
        }
    )


def test_packaged_cli_is_resolved_before_path(tmp_path: Path) -> None:
    worker = tmp_path / "release-1" / "Backend" / "Stockroom Worker.exe"
    packaged = tmp_path / "release-1" / "Tools" / "gh.exe"
    worker.parent.mkdir(parents=True)
    worker.write_bytes(b"worker")
    packaged.parent.mkdir(parents=True)
    packaged.write_bytes(b"gh")
    path_calls: list[str] = []

    resolved = resolve_github_cli(
        frozen=True,
        process_executable=worker,
        path_lookup=lambda name: path_calls.append(name) or "C:/Other/gh.exe",
    )

    assert resolved == packaged
    assert path_calls == []


def test_frozen_runtime_never_falls_back_to_mutable_path(tmp_path: Path) -> None:
    worker = tmp_path / "release-1" / "Backend" / "Stockroom Worker.exe"
    worker.parent.mkdir(parents=True)
    worker.write_bytes(b"worker")
    path_calls: list[str] = []

    assert resolve_github_cli(
        frozen=True,
        process_executable=worker,
        path_lookup=lambda name: path_calls.append(name) or "C:/Mutable/gh.exe",
    ) is None
    assert path_calls == []


def test_source_runtime_falls_back_to_path(tmp_path: Path) -> None:
    path_gh = tmp_path / "PATH" / "gh.exe"
    path_gh.parent.mkdir()
    path_gh.write_bytes(b"gh")

    assert resolve_github_cli(
        frozen=False,
        process_executable=tmp_path / "python.exe",
        path_lookup=lambda _name: str(path_gh),
    ) == path_gh


def test_availability_and_version_use_an_argv_list(tmp_path: Path) -> None:
    executable = tmp_path / "Tools" / "gh.exe"
    output = "gh version 2.95.0 (2026-06-17)\nhttps://example.invalid\n"
    runner = ScriptedRunner(_result(output), _result(output))
    cli = GitHubCli(executable=executable, runner=runner)

    status = cli.availability()
    assert status.available is True
    assert status.version == "2.95.0"
    assert cli.version() == "2.95.0"
    assert runner.calls == [
        ([str(executable), "--version"], None, 10.0),
        ([str(executable), "--version"], None, 10.0),
    ]


def test_unavailable_or_unparseable_version_fails_closed() -> None:
    missing = GitHubCli(executable=None, runner=ScriptedRunner())
    # Force the test independent of a developer PATH installation.
    missing._executable = None
    assert missing.availability().available is False
    with pytest.raises(GitHubCliError, match="unavailable"):
        missing.version()

    malformed = GitHubCli(
        executable=Path("gh.exe"),
        runner=ScriptedRunner(_result("unexpected output")),
    )
    assert malformed.availability().available is False


def test_local_authentication_status_never_requests_token_output() -> None:
    runner = ScriptedRunner(_result(returncode=0))
    cli = GitHubCli(executable=Path("gh.exe"), runner=runner)

    assert cli.authenticated() is True
    assert runner.calls[0] == (
        ["gh.exe", "auth", "status", "--hostname", "github.com", "--active"],
        None,
        10.0,
    )


def test_authentication_status_distinguishes_signed_out_from_operational_failure() -> None:
    signed_out = GitHubCli(
        executable=Path("gh.exe"),
        runner=ScriptedRunner(
            _result(returncode=1, stderr="You are not logged into any GitHub hosts")
        ),
    )
    assert signed_out.authenticated() is False

    offline = GitHubCli(
        executable=Path("gh.exe"),
        runner=ScriptedRunner(
            _result(returncode=1, stderr="could not resolve api.github.com")
        ),
    )
    with pytest.raises(GitHubCliError, match="status check failed"):
        offline.authenticated()


def test_browser_login_keeps_auth_output_private_and_returns_selected_viewer_fields() -> None:
    runner = ScriptedRunner(
        _result("one-time-browser-output-that-must-not-return"),
        _result('{"login":"sadadsh","name":"Sadad","token":"secret"}'),
    )
    cli = GitHubCli(executable=Path("gh.exe"), runner=runner)

    assert cli.login_browser() == GitHubViewer(login="sadadsh", name="Sadad")
    assert runner.calls[0][0] == [
        "gh.exe",
        "auth",
        "login",
        "--web",
        "--clipboard",
        "--hostname",
        "github.com",
        "--git-protocol",
        "https",
        "--skip-ssh-key",
    ]
    assert runner.calls[1][0] == ["gh.exe", "api", "--method", "GET", "user"]


def test_viewer_and_owners_return_personal_then_sorted_organizations() -> None:
    runner = ScriptedRunner(
        _result('{"login":"sadadsh","name":null}'),
        _result('[[{"login":"Zulu"},{"login":"alpha"}],[]]'),
    )
    cli = GitHubCli(executable=Path("gh.exe"), runner=runner)

    assert cli.owners() == (
        GitHubOwner(login="sadadsh", kind="personal"),
        GitHubOwner(login="alpha", kind="organization"),
        GitHubOwner(login="Zulu", kind="organization"),
    )
    assert runner.calls[1][0] == [
        "gh.exe",
        "api",
        "--method",
        "GET",
        "user/orgs?per_page=100",
        "--paginate",
        "--slurp",
    ]


def test_repository_listing_is_bounded_and_selects_non_secret_fields() -> None:
    runner = ScriptedRunner(
        _result(
            json.dumps(
                [
                    {
                        "name": "Catalog",
                        "url": "https://github.com/acme/Catalog",
                        "visibility": "PUBLIC",
                        "viewerPermission": "ADMIN",
                    }
                ]
            )
        )
    )
    cli = GitHubCli(executable=Path("gh.exe"), runner=runner)

    assert cli.list_repositories("acme", limit=25) == (
        GitHubRepository(
            owner="acme",
            name="Catalog",
            url="https://github.com/acme/Catalog",
            visibility="public",
            permission="admin",
        ),
    )
    assert runner.calls[0][0] == [
        "gh.exe",
        "repo",
        "list",
        "acme",
        "--limit",
        "25",
        "--json",
        "name,url,visibility,viewerPermission",
    ]
    with pytest.raises(ValueError, match="between 1 and 100"):
        cli.list_repositories("acme", limit=101)


def test_exact_repository_lookup_returns_non_secret_identity() -> None:
    runner = ScriptedRunner(_result(_repo_json(owner="acme", name="Catalog")))
    cli = GitHubCli(executable=Path("gh.exe"), runner=runner)

    repository = cli.repository("acme", "Catalog")

    assert repository.owner == "acme"
    assert repository.url == "https://github.com/acme/Catalog"
    assert runner.calls[0][0] == [
        "gh.exe",
        "repo",
        "view",
        "acme/Catalog",
        "--json",
        "name,url,visibility,viewerPermission",
    ]


def test_create_personal_private_repository_uses_json_stdin() -> None:
    runner = ScriptedRunner(
        _result('{"login":"sadadsh","name":"Sadad"}'),
        _result("[[]]"),
        _result(returncode=1, stderr="not found"),
        _result('{"name":"Stockroom-Catalog","html_url":"https://github.com/sadadsh/Stockroom-Catalog"}'),
        _result(_repo_json()),
    )
    cli = GitHubCli(executable=Path("gh.exe"), runner=runner)

    created = cli.create_repository(
        "sadadsh",
        "Stockroom-Catalog",
        visibility="private",
    )

    assert created.visibility == "private"
    assert runner.calls[3][0] == [
        "gh.exe",
        "api",
        "--method",
        "POST",
        "user/repos",
        "--input",
        "-",
    ]
    assert json.loads(runner.calls[3][1] or "") == {
        "name": "Stockroom-Catalog",
        "private": True,
    }
    assert runner.calls[4][0] == [
        "gh.exe",
        "repo",
        "view",
        "sadadsh/Stockroom-Catalog",
        "--json",
        "name,url,visibility,viewerPermission",
    ]


def test_create_organization_public_repository_uses_org_endpoint() -> None:
    runner = ScriptedRunner(
        _result('{"login":"sadadsh","name":null}'),
        _result('[[{"login":"acme"}]]'),
        _result(returncode=1),
        _result('{"name":"Catalog","html_url":"https://github.com/acme/Catalog"}'),
        _result(_repo_json(owner="acme", name="Catalog", visibility="PUBLIC")),
    )
    cli = GitHubCli(executable=Path("gh.exe"), runner=runner)

    assert cli.create_repository("acme", "Catalog", visibility="public").owner == "acme"
    assert runner.calls[3][0][4] == "orgs/acme/repos"


def test_create_returns_existing_repository_without_a_second_write() -> None:
    runner = ScriptedRunner(
        _result('{"login":"sadadsh","name":null}'),
        _result("[[]]"),
        _result(_repo_json(visibility="PUBLIC")),
    )
    cli = GitHubCli(executable=Path("gh.exe"), runner=runner)

    repository = cli.create_repository(
        "sadadsh",
        "Stockroom-Catalog",
        visibility="public",
    )

    assert repository.visibility == "public"
    assert len(runner.calls) == 3


def test_create_refuses_existing_repository_with_different_visibility() -> None:
    runner = ScriptedRunner(
        _result('{"login":"sadadsh","name":null}'),
        _result("[[]]"),
        _result(_repo_json(visibility="PUBLIC")),
    )
    cli = GitHubCli(executable=Path("gh.exe"), runner=runner)

    with pytest.raises(GitHubCliError, match="different visibility"):
        cli.create_repository("sadadsh", "Stockroom-Catalog", visibility="private")
    assert len(runner.calls) == 3


def test_create_race_rechecks_existing_repository_after_failure() -> None:
    runner = ScriptedRunner(
        _result('{"login":"sadadsh","name":null}'),
        _result("[[]]"),
        _result(returncode=1),
        _result(returncode=1, stderr="already exists"),
        _result(_repo_json()),
    )
    cli = GitHubCli(executable=Path("gh.exe"), runner=runner)

    assert cli.create_repository(
        "sadadsh",
        "Stockroom-Catalog",
        visibility="private",
    ).name == "Stockroom-Catalog"


def test_failures_are_sanitized_and_never_include_cli_output() -> None:
    runner = ScriptedRunner(
        _result(
            returncode=1,
            stdout="ghp_secret_stdout",
            stderr="authorization: token ghp_secret_stderr",
        )
    )
    cli = GitHubCli(executable=Path("gh.exe"), runner=runner)

    with pytest.raises(GitHubCliError) as caught:
        cli.viewer()

    assert str(caught.value) == "GitHub account lookup failed."
    assert "ghp_" not in str(caught.value)
    assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    ("owner", "name"),
    [
        ("-evil", "catalog"),
        ("evil--owner", "catalog"),
        ("owner", "../catalog"),
        ("owner", "catalog?token=secret"),
        ("owner", ""),
    ],
)
def test_validation_rejects_unsafe_owner_and_repository_values(owner: str, name: str) -> None:
    with pytest.raises(ValueError):
        validate_owner_repository(owner, name)


def test_clone_url_is_https_and_credential_free() -> None:
    url = credential_free_clone_url("sadadsh", "Stockroom-Catalog")

    assert url == "https://github.com/sadadsh/Stockroom-Catalog.git"
    assert "@" not in url
    assert "token" not in url


def test_private_repository_clone_uses_authenticated_github_cli(tmp_path: Path) -> None:
    executable = Path("gh.exe")
    runner = ScriptedRunner(_result())
    cli = GitHubCli(executable=executable, runner=runner)
    destination = tmp_path / "Mainline"

    cli.clone_repository("sadadsh", "Mainline-Components", destination)

    assert runner.calls == [
        (
            [
                str(executable),
                "repo",
                "clone",
                "https://github.com/sadadsh/Mainline-Components.git",
                str(destination.resolve()),
                "--",
                "-c",
                "core.autocrlf=false",
                "-c",
                "core.longpaths=true",
            ],
            None,
            10 * 60.0,
        )
    ]


def test_repository_response_rejects_credentials_and_mismatched_owner() -> None:
    runner = ScriptedRunner(
        _result(
            json.dumps(
                [
                    {
                        "name": "Catalog",
                        "url": "https://token@github.com/other/Catalog",
                        "visibility": "PRIVATE",
                    }
                ]
            )
        )
    )
    cli = GitHubCli(executable=Path("gh.exe"), runner=runner)

    with pytest.raises(GitHubCliError, match="response was invalid"):
        cli.list_repositories("sadadsh")


@pytest.mark.parametrize(
    "payload",
    [
        "not-json ghp_secret",
        '{"login":"safe","login":"ghp_secret"}',
        '{"login":"safe","value":NaN}',
    ],
)
def test_invalid_json_is_sanitized(payload: str) -> None:
    cli = GitHubCli(
        executable=Path("gh.exe"),
        runner=ScriptedRunner(_result(payload)),
    )

    with pytest.raises(GitHubCliError) as caught:
        cli.viewer()

    assert str(caught.value) == "GitHub account response was invalid."
    assert "ghp_secret" not in str(caught.value)
    assert caught.value.__cause__ is None
