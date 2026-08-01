"""Bind an HTTPS GitHub remote to Git Credential Manager without disk leakage.

Legacy Stockroom wrote a reversible Basic token into ``.git/config`` as an
``extraheader``. This module always removes that value. For an HTTPS GitHub
origin, the token is piped to Git's configured credential helper and scoped to
the exact repository path. It never appears in a URL, command line, environment
variable, repository config, or captured subprocess output.
"""

from __future__ import annotations

from urllib.parse import urlsplit

_GITHUB_HTTPS = "https://github.com/"
EXTRAHEADER_KEY = f"http.{_GITHUB_HTTPS}.extraheader"
USE_HTTP_PATH_KEY = f"credential.{_GITHUB_HTTPS}.useHttpPath"


def _github_https_path(repo) -> str | None:
    remote = repo._run("remote", "get-url", "origin", check=False)
    if remote.returncode != 0:
        return None
    parsed = urlsplit(remote.stdout.strip())
    if parsed.scheme.casefold() != "https" or (parsed.hostname or "").casefold() != "github.com":
        return None
    path = parsed.path.lstrip("/")
    return path or None


def _credential_payload(path: str, token: str) -> str:
    rows = [
        "protocol=https",
        "host=github.com",
        f"path={path}",
        "username=x-access-token",
    ]
    if token:
        rows.append(f"password={token}")
    return "\n".join(rows) + "\n\n"


def _run_credential(repo, action: str, payload: str) -> None:
    result = repo._run(
        "credential",
        action,
        check=False,
        input_text=payload,
    )
    if result.returncode != 0:
        from stockroom.vcs.repo import GitError

        raise GitError(f"git credential {action} failed")


def configure(repo, token: str) -> None:
    """Store or erase the exact-origin credential and scrub the legacy header."""

    repo.unset_config(EXTRAHEADER_KEY)
    path = _github_https_path(repo)
    if path is None:
        return
    repo.set_config(USE_HTTP_PATH_KEY, "true")
    token = (token or "").strip()
    if token:
        _run_credential(repo, "approve", _credential_payload(path, token))
    else:
        _run_credential(repo, "reject", _credential_payload(path, ""))


def accounts(repo) -> list[str]:
    """GitHub accounts already owned by this Windows user's Git Credential Manager."""
    result = repo._run(
        "credential-manager",
        "github",
        "list",
        "--no-ui",
        check=False,
    )
    if result.returncode != 0:
        return []
    return sorted({line.strip() for line in result.stdout.splitlines() if line.strip()})


def login(repo) -> list[str]:
    """Open Git Credential Manager's GitHub OAuth flow, then return the signed-in accounts.

    No token crosses Stockroom's API or configuration. GCM owns the browser/device flow and stores
    the resulting credential for the current Windows user.
    """
    result = repo._run("credential-manager", "github", "login", check=False)
    if result.returncode != 0:
        from stockroom.vcs.repo import GitError

        raise GitError("GitHub sign-in did not complete")
    return accounts(repo)
