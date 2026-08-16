"""Non-secret GitHub authority delegated to the GitHub CLI.

The packaged worker resolves its release-bound ``Tools/gh.exe`` before PATH.
GitHub CLI owns browser authentication and token custody; Stockroom consumes
only narrowly selected, non-secret JSON fields and credential-free HTTPS URLs.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, cast
from urllib.parse import urlsplit

_NO_WINDOW = 0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0
_DEFAULT_TIMEOUT_SECONDS = 30.0
_LOGIN_TIMEOUT_SECONDS = 10 * 60.0
_MAX_REPOSITORIES = 100
_OWNER_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?")
_REPOSITORY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_VERSION_PATTERN = re.compile(r"gh version ([0-9]+(?:\.[0-9]+){1,3})(?=\s|$)")

Visibility = Literal["public", "private", "internal"]
OwnerKind = Literal["personal", "organization"]
RepositoryPermission = Literal["admin", "maintain", "write", "triage", "read"]


class GitHubCliError(RuntimeError):
    """A GitHub CLI operation failed without exposing process output."""


class GitHubCliRunner(Protocol):
    """Injectable argv-only subprocess boundary."""

    def __call__(
        self,
        argv: Sequence[str],
        *,
        input_text: str | None = None,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]: ...


@dataclass(frozen=True, slots=True)
class GitHubCliAvailability:
    available: bool
    version: str | None


@dataclass(frozen=True, slots=True)
class GitHubViewer:
    login: str
    name: str | None


@dataclass(frozen=True, slots=True)
class GitHubOwner:
    login: str
    kind: OwnerKind


@dataclass(frozen=True, slots=True)
class GitHubRepository:
    owner: str
    name: str
    url: str
    visibility: Visibility
    permission: RepositoryPermission

    @property
    def writable(self) -> bool:
        return self.permission in {"admin", "maintain", "write"}


def _default_runner(
    argv: Sequence[str],
    *,
    input_text: str | None = None,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        capture_output=True,
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        check=False,
        creationflags=_NO_WINDOW,
        timeout=timeout,
    )


def resolve_github_cli(
    *,
    frozen: bool | None = None,
    process_executable: Path | None = None,
    path_lookup: Callable[[str], str | None] = shutil.which,
) -> Path | None:
    """Resolve the immutable release CLI before consulting mutable PATH."""

    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    executable = Path(sys.executable) if process_executable is None else Path(process_executable)
    if is_frozen:
        packaged = executable.resolve().parent.parent / "Tools" / "gh.exe"
        return packaged if packaged.is_file() else None
    discovered = path_lookup("gh")
    return Path(discovered).resolve() if discovered else None


def validate_owner(owner: str) -> str:
    value = owner if isinstance(owner, str) else ""
    if _OWNER_PATTERN.fullmatch(value) is None or "--" in value:
        raise ValueError("GitHub owner is invalid.")
    return value


def validate_repository_name(name: str) -> str:
    value = name if isinstance(name, str) else ""
    if _REPOSITORY_PATTERN.fullmatch(value) is None or value in {".", ".."}:
        raise ValueError("GitHub repository name is invalid.")
    return value


def validate_owner_repository(owner: str, name: str) -> tuple[str, str]:
    return validate_owner(owner), validate_repository_name(name)


def credential_free_clone_url(owner: str, name: str) -> str:
    valid_owner, valid_name = validate_owner_repository(owner, name)
    return f"https://github.com/{valid_owner}/{valid_name}.git"


class GitHubCli:
    """Bounded GitHub operations whose credential authority remains in ``gh``."""

    def __init__(
        self,
        *,
        executable: Path | None = None,
        runner: GitHubCliRunner = _default_runner,
    ) -> None:
        self._executable = Path(executable) if executable is not None else resolve_github_cli()
        self._runner = runner

    def _argv(self, *args: str) -> list[str]:
        if self._executable is None:
            raise GitHubCliError("GitHub CLI is unavailable.")
        return [str(self._executable), *args]

    def _run(
        self,
        *args: str,
        input_text: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        error: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = self._runner(
                self._argv(*args),
                input_text=input_text,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError):
            raise GitHubCliError(error) from None
        if check and result.returncode != 0:
            raise GitHubCliError(error)
        return result

    @staticmethod
    def _json(result: subprocess.CompletedProcess[str], *, error: str) -> object:
        try:
            return json.loads(
                result.stdout,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_nonfinite_number,
            )
        except (TypeError, ValueError):
            raise GitHubCliError(error) from None

    def availability(self) -> GitHubCliAvailability:
        if self._executable is None:
            return GitHubCliAvailability(available=False, version=None)
        try:
            result = self._run(
                "--version",
                error="GitHub CLI version check failed.",
                timeout=10.0,
            )
        except GitHubCliError:
            return GitHubCliAvailability(available=False, version=None)
        first_line = result.stdout.splitlines()[0].strip() if result.stdout.splitlines() else ""
        match = _VERSION_PATTERN.match(first_line)
        if match is None:
            return GitHubCliAvailability(available=False, version=None)
        return GitHubCliAvailability(available=True, version=match.group(1))

    def version(self) -> str:
        status = self.availability()
        if not status.available or status.version is None:
            raise GitHubCliError("GitHub CLI is unavailable.")
        return status.version

    def authenticated(self) -> bool:
        """Read local gh credential state without exposing or printing the credential."""

        if self._executable is None:
            return False
        result = self._run(
            "auth",
            "status",
            "--hostname",
            "github.com",
            "--active",
            error="GitHub sign-in status check failed.",
            check=False,
            timeout=10.0,
        )
        return result.returncode == 0

    def login_browser(self) -> GitHubViewer:
        self._run(
            "auth",
            "login",
            "--web",
            "--hostname",
            "github.com",
            "--git-protocol",
            "https",
            "--skip-ssh-key",
            timeout=_LOGIN_TIMEOUT_SECONDS,
            error="GitHub browser sign-in did not complete.",
        )
        return self.viewer()

    def viewer(self) -> GitHubViewer:
        result = self._run(
            "api",
            "--method",
            "GET",
            "user",
            error="GitHub account lookup failed.",
        )
        document = self._json(result, error="GitHub account response was invalid.")
        record = _object(document, "GitHub account response")
        login = _response_owner(
            _required_string(record, "login", "GitHub account response"),
            "GitHub account response",
        )
        name = record.get("name")
        if name is not None and not isinstance(name, str):
            raise GitHubCliError("GitHub account response was invalid.")
        return GitHubViewer(login=login, name=name or None)

    def owners(self) -> tuple[GitHubOwner, ...]:
        viewer = self.viewer()
        result = self._run(
            "api",
            "--method",
            "GET",
            "user/orgs?per_page=100",
            "--paginate",
            "--slurp",
            error="GitHub organization lookup failed.",
        )
        document = self._json(result, error="GitHub organization response was invalid.")
        if not isinstance(document, list):
            raise GitHubCliError("GitHub organization response was invalid.")
        organizations: set[str] = set()
        for page in document:
            if not isinstance(page, list):
                raise GitHubCliError("GitHub organization response was invalid.")
            for item in page:
                record = _object(item, "GitHub organization response")
                organizations.add(
                    _response_owner(
                        _required_string(record, "login", "GitHub organization response"),
                        "GitHub organization response",
                    )
                )
        return (
            GitHubOwner(login=viewer.login, kind="personal"),
            *(
                GitHubOwner(login=login, kind="organization")
                for login in sorted(organizations, key=str.casefold)
                if login.casefold() != viewer.login.casefold()
            ),
        )

    def list_repositories(
        self,
        owner: str,
        *,
        limit: int = 50,
    ) -> tuple[GitHubRepository, ...]:
        valid_owner = validate_owner(owner)
        if type(limit) is not int or not 1 <= limit <= _MAX_REPOSITORIES:
            raise ValueError(f"Repository limit must be between 1 and {_MAX_REPOSITORIES}.")
        result = self._run(
            "repo",
            "list",
            valid_owner,
            "--limit",
            str(limit),
            "--json",
            "name,url,visibility,viewerPermission",
            error="GitHub repository listing failed.",
        )
        document = self._json(result, error="GitHub repository list was invalid.")
        if not isinstance(document, list) or len(document) > limit:
            raise GitHubCliError("GitHub repository list was invalid.")
        return tuple(
            _repository(item, expected_owner=valid_owner)
            for item in document
        )

    def _lookup_repository(self, owner: str, name: str) -> GitHubRepository | None:
        result = self._run(
            "repo",
            "view",
            f"{owner}/{name}",
            "--json",
            "name,url,visibility,viewerPermission",
            error="GitHub repository lookup failed.",
            check=False,
        )
        if result.returncode != 0:
            return None
        document = self._json(result, error="GitHub repository response was invalid.")
        repository = _repository(document, expected_owner=owner)
        if repository.name.casefold() != name.casefold():
            raise GitHubCliError("GitHub repository response was invalid.")
        return repository

    def repository(self, owner: str, name: str) -> GitHubRepository:
        """Return one exact repository or fail without leaking CLI output."""

        valid_owner, valid_name = validate_owner_repository(owner, name)
        repository = self._lookup_repository(valid_owner, valid_name)
        if repository is None:
            raise GitHubCliError("The selected GitHub repository is unavailable.")
        return repository

    def create_repository(
        self,
        owner: str,
        name: str,
        *,
        visibility: Literal["public", "private"],
    ) -> GitHubRepository:
        valid_owner, valid_name = validate_owner_repository(owner, name)
        if visibility not in {"public", "private"}:
            raise ValueError("Repository visibility must be public or private.")
        available_owners = {item.login.casefold(): item for item in self.owners()}
        selected_owner = available_owners.get(valid_owner.casefold())
        if selected_owner is None:
            raise GitHubCliError("The selected GitHub owner is unavailable.")

        existing = self._lookup_repository(valid_owner, valid_name)
        if existing is not None:
            if existing.visibility != visibility:
                raise GitHubCliError(
                    "A repository with that name already exists with different visibility. "
                    "Connect Existing or choose another name."
                )
            return existing

        endpoint = (
            "user/repos"
            if selected_owner.kind == "personal"
            else f"orgs/{valid_owner}/repos"
        )
        payload = json.dumps(
            {"name": valid_name, "private": visibility == "private"},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        result = self._run(
            "api",
            "--method",
            "POST",
            endpoint,
            "--input",
            "-",
            input_text=payload,
            error="GitHub repository creation failed.",
            check=False,
        )
        if result.returncode != 0:
            raced = self._lookup_repository(valid_owner, valid_name)
            if raced is not None:
                if raced.visibility != visibility:
                    raise GitHubCliError(
                        "A repository with that name already exists with different visibility. "
                        "Connect Existing or choose another name."
                    )
                return raced
            raise GitHubCliError("GitHub repository creation failed.")
        repository = _repository(
            self._json(result, error="GitHub repository response was invalid."),
            expected_owner=valid_owner,
        )
        if repository.name.casefold() != valid_name.casefold():
            raise GitHubCliError("GitHub repository response was invalid.")
        return repository


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate JSON key")
        document[key] = value
    return document


def _reject_nonfinite_number(value: str) -> object:
    raise ValueError(f"non-finite JSON number: {value}")


def _object(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise GitHubCliError(f"{context} was invalid.")
    return cast(Mapping[str, object], value)


def _required_string(record: Mapping[str, object], key: str, context: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise GitHubCliError(f"{context} was invalid.")
    return value


def _response_owner(value: str, context: str) -> str:
    try:
        return validate_owner(value)
    except ValueError:
        raise GitHubCliError(f"{context} was invalid.") from None


def _response_repository_name(value: str, context: str) -> str:
    try:
        return validate_repository_name(value)
    except ValueError:
        raise GitHubCliError(f"{context} was invalid.") from None


def _repository(value: object, *, expected_owner: str) -> GitHubRepository:
    record = _object(value, "GitHub repository response")
    name = _response_repository_name(
        _required_string(record, "name", "GitHub repository response"),
        "GitHub repository response",
    )
    raw_url = _required_string(record, "url", "GitHub repository response")
    parsed = urlsplit(raw_url)
    expected_path = f"/{expected_owner}/{name}"
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").casefold() != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.casefold().removesuffix(".git") != expected_path.casefold()
    ):
        raise GitHubCliError("GitHub repository response was invalid.")
    raw_visibility = _required_string(
        record,
        "visibility",
        "GitHub repository response",
    ).casefold()
    if raw_visibility not in {"public", "private", "internal"}:
        raise GitHubCliError("GitHub repository response was invalid.")
    visibility = raw_visibility
    raw_permission = _required_string(
        record,
        "viewerPermission",
        "GitHub repository response",
    ).casefold()
    if raw_permission not in {"admin", "maintain", "write", "triage", "read"}:
        raise GitHubCliError("GitHub repository response was invalid.")
    permission = raw_permission
    return GitHubRepository(
        owner=expected_owner,
        name=name,
        url=f"https://github.com/{expected_owner}/{name}",
        visibility=visibility,
        permission=permission,
    )
