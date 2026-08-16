"""First-run onboarding surface (M9b): tell the app where the library lives (open an
existing one, clone a git URL, or create a fresh one), then repoint the running engine at
it LIVE via AppContext.switch_library (same token, so auth keeps working, no restart).

A frozen exe ships no library, so this is the gate that makes every library and project
feature usable on a real install. Read-only status + a set + a dismiss. Routers never
invent an error shape: onboarding raises ValueError for a bad request and api/errors.py
maps it to 400.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

import threading
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from stockroom.api.errors import ApiError
from stockroom.api.schemas import (
    GuidedRepositoryBody,
    GuidedSourceDataBody,
    SetLibraryBody,
)
from stockroom.eda.primary_policy import (
    PrimaryEdaPolicy,
    machine_detected_tool_keys,
)
from stockroom.store import guided_setup
from stockroom.store import onboarding as onb
from stockroom.vcs.github_cli import (
    GitHubCli,
    GitHubCliError,
    credential_free_clone_url,
)
from stockroom.vcs.repo import GitError, GitRepo

_TOOL_SETUP_LOCK = threading.Lock()


def _github_status(
    cli: GitHubCli | None = None,
    *,
    repository: dict[str, str] | None = None,
) -> dict[str, object]:
    authority = cli or GitHubCli()
    availability = authority.availability()
    base: dict[str, object] = {
        "available": availability.available,
        "version": availability.version,
        "authenticated": False,
        "online": False,
        "viewer": None,
        "owners": [],
    }
    if not availability.available:
        return base
    try:
        authenticated = authority.authenticated()
    except GitHubCliError:
        return {
            **base,
            "error": "GitHub could not be reached. Stockroom will retry automatically.",
        }
    if not authenticated:
        return {
            **base,
            "online": True,
            "error": "Sign in with GitHub to continue.",
        }
    try:
        viewer = authority.viewer()
    except GitHubCliError:
        return {
            **base,
            "authenticated": True,
            "error": "GitHub could not be reached. Stockroom will retry automatically.",
        }
    try:
        owners = authority.owners()
    except GitHubCliError:
        return {
            **base,
            "authenticated": True,
            "online": True,
            "viewer": {"login": viewer.login, "name": viewer.name},
            "error": "GitHub organizations could not be loaded. Try this step again.",
        }
    result: dict[str, object] = {
        **base,
        "authenticated": True,
        "online": True,
        "viewer": {"login": viewer.login, "name": viewer.name},
        "owners": [
            {"login": owner.login, "kind": owner.kind}
            for owner in owners
        ],
    }
    if repository is not None:
        try:
            exact = authority.repository(repository["owner"], repository["name"])
        except GitHubCliError:
            try:
                authority.viewer()
            except GitHubCliError:
                result["online"] = False
                result["error"] = (
                    "GitHub could not be reached. Stockroom will retry automatically."
                )
            else:
                result["error"] = (
                    "The connected Catalog Repository is unavailable to this GitHub account."
                )
        else:
            result["verified_repository"] = {
                "owner": exact.owner,
                "name": exact.name,
                "url": exact.url,
                "visibility": exact.visibility,
                "permission": exact.permission,
                "writable": exact.writable,
            }
    return result


def _status(ctx, *, github: dict[str, object] | None = None) -> dict:
    cfg = ctx.config
    root = Path(ctx.libraries_root)
    onboarded = guided_setup.completed(cfg)
    # under_git via git itself (rev-parse), so the in-repo library, backed by the ENCLOSING app
    # repo with no nested .git of its own, still reports True.
    try:
        under_git = GitRepo(root).is_git_repo()
    except GitError:
        under_git = (root / ".git").exists()
    workspaces = []
    for item in getattr(cfg, "library_workspaces", []):
        if not isinstance(item, dict) or not str(item.get("path", "")).strip():
            continue
        path = Path(str(item["path"]))
        try:
            active = path.resolve(strict=False) == root.resolve(strict=False)
        except OSError:
            active = str(path) == str(root)
        workspaces.append({
            "name": str(item.get("name") or path.name),
            "path": path.as_posix(),
            "active": active,
            "available": path.is_dir(),
            "under_git": (path / ".git").exists(),
        })
    return {
        **PrimaryEdaPolicy(cfg).dto(machine_detected_tool_keys(ctx)),
        "onboarded": onboarded,
        "first_run": not onboarded,
        "libraries_root": root.as_posix(),
        "profiles": ctx.profile_store.list(),
        "under_git": under_git,
        "default_dir": onb.default_library_dir().as_posix(),
        "libraries": workspaces,
        "guided_setup": guided_setup.status(
            ctx,
            github
            or _github_status(repository=guided_setup.github_remote(ctx.repo)),
        ),
    }


def _require_primary_eda(ctx) -> None:
    if PrimaryEdaPolicy(ctx.config).primary_tool is None:
        raise ValueError("choose KiCad or Altium before completing setup")


def onboarding_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/onboarding", dependencies=[Depends(require_token)])

    @r.get("")
    def get_onboarding(request: Request) -> dict:
        # The current library location + whether the one-time welcome screen should show.
        return _status(request.app.state.ctx)

    @r.post("/library")
    def set_library(request: Request, body: SetLibraryBody) -> dict:
        # Open / create / clone the library, then repoint the running engine at it live (the
        # same token keeps authenticating). A bad mode / missing dir / non-empty clone dest
        # is a ValueError -> 400; a clone GitError -> 503.
        ctx = request.app.state.ctx
        _require_primary_eda(ctx)
        if not _TOOL_SETUP_LOCK.acquire(blocking=False):
            raise ApiError(409, "Guided Setup is already changing the Catalog Repository")
        try:
            root = onb.set_library(
                ctx.config, body.mode,
                path=body.path or None, url=body.url or None, dest=body.dest or None,
                complete=False,
            )
            ctx.switch_library(root)
            ctx.config.onboarded = False
            ctx.config.save()
            return _status(ctx)
        finally:
            _TOOL_SETUP_LOCK.release()

    @r.post("/github/login")
    def github_login(request: Request) -> dict:
        """Start the bundled GitHub CLI browser flow without exposing its token."""

        ctx = request.app.state.ctx

        def work(progress):
            progress({"stage": "waiting", "pct": 0.2, "message": "waiting for GitHub sign-in"})
            cli = GitHubCli()
            viewer = cli.login_browser()
            return {
                "viewer": {"login": viewer.login, "name": viewer.name},
                "owners": [
                    {"login": owner.login, "kind": owner.kind}
                    for owner in cli.owners()
                ],
            }

        return {"job_id": ctx.jobs.submit(work)}

    @r.get("/github/repositories/{owner}")
    def github_repositories(owner: str) -> dict:
        repositories = GitHubCli().list_repositories(owner, limit=100)
        return {
            "repositories": [
                {
                    "owner": repository.owner,
                    "name": repository.name,
                    "url": repository.url,
                    "visibility": repository.visibility,
                    "permission": repository.permission,
                    "writable": repository.writable,
                }
                for repository in repositories
            ]
        }

    @r.post("/repository")
    def set_guided_repository(request: Request, body: GuidedRepositoryBody) -> dict:
        """Create/connect, clone, initialize, and switch one GitHub Catalog Repository."""

        ctx = request.app.state.ctx
        _require_primary_eda(ctx)
        destination = body.path.strip()
        if not destination:
            raise ValueError("choose a Catalog Repository folder with Windows Explorer")
        if not _TOOL_SETUP_LOCK.acquire(blocking=False):
            raise ApiError(409, "Guided Setup is already changing the CAD tool or Catalog Repository")
        try:
            expected_url = credential_free_clone_url(body.owner, body.name)
            selected_root, adopt_existing = onb.guided_clone_destination(
                destination,
                expected_url=expected_url,
            )
            cli = GitHubCli()
            if body.mode == "create":
                if body.visibility is None:
                    raise ValueError("choose Public or Private for the Catalog Repository")
                repository = cli.create_repository(
                    body.owner,
                    body.name,
                    visibility=body.visibility,
                )
            else:
                repository = cli.repository(body.owner, body.name)
            if not repository.writable:
                raise ValueError(
                    "Stockroom needs write permission for the selected Catalog Repository"
                )

            if adopt_existing:
                root = onb.set_library(
                    ctx.config,
                    "open",
                    path=selected_root,
                    complete=False,
                )
            else:
                root = onb.set_library(
                    ctx.config,
                    "clone",
                    url=repository.url,
                    dest=selected_root,
                    complete=False,
                )
            ctx.switch_library(root)
            ctx.config.onboarded = False
            guided_setup.record_repository(
                ctx.config,
                owner=repository.owner,
                name=repository.name,
                visibility=repository.visibility,
                url=repository.url,
            )
            return _status(
                ctx,
                github=_github_status(
                    cli,
                    repository={"owner": repository.owner, "name": repository.name},
                ),
            )
        finally:
            _TOOL_SETUP_LOCK.release()

    @r.post("/tool/connect")
    def connect_tool(request: Request) -> dict:
        """Run the selected tool's explicit setup operation as one resumable job."""

        ctx = request.app.state.ctx
        policy = PrimaryEdaPolicy(ctx.config)
        primary = policy.primary_tool
        if primary is None:
            raise ValueError("choose KiCad or Altium before connecting the tool")
        if not _TOOL_SETUP_LOCK.acquire(blocking=False):
            raise ApiError(409, "CAD tool setup is already running")
        selected_tool = primary.key
        selected_profile_root = Path(ctx.profile.root)
        selected_ops = ctx.ops

        def work(progress):
            try:
                return _connect_selected_tool(progress)
            finally:
                _TOOL_SETUP_LOCK.release()

        def _connect_selected_tool(progress):
            current = PrimaryEdaPolicy(ctx.config).primary_tool
            if (
                current is None
                or current.key != selected_tool
                or Path(ctx.profile.root) != selected_profile_root
            ):
                raise ValueError("The selected CAD tool or Catalog Repository changed; try again")
            receipt: dict[str, object]
            if selected_tool == "kicad":
                progress({"stage": "wiring", "pct": 0.3, "message": "connecting KiCad"})
                ctx.rewire_kicad()
                connection = guided_setup.current_tool_connection(ctx)
                if not connection["connected"]:
                    raise ValueError(str(connection["detail"]))
                receipt = {
                    "verified": True,
                    "restart_required": bool(connection["restart_required"]),
                }
            else:
                progress({"stage": "setup", "pct": 0.2, "message": "connecting Altium"})
                from stockroom.altium.convergence import (
                    converge_altium_library,
                    verify_catalog_library,
                )
                from stockroom.api.routers.altium import _WRITE_LOCK

                target = selected_profile_root / "altium" / "Stockroom.DbLib"
                with _WRITE_LOCK:
                    selected_ops.regenerate_altium_dblib()
                    result = converge_altium_library(
                        target,
                        verifier=verify_catalog_library,
                    )
                if result.status not in {"verified", "already-verified"} or not target.is_file():
                    raise ValueError(result.detail)
                receipt = {"verified": True, "result": asdict(result)}
            guided_setup.record_tool_connection(
                ctx.config,
                tool=selected_tool,
                receipt=receipt,
            )
            final = PrimaryEdaPolicy(ctx.config).primary_tool
            if (
                final is None
                or final.key != selected_tool
                or Path(ctx.profile.root) != selected_profile_root
            ):
                raise ValueError("The selected CAD tool or Catalog Repository changed; try again")
            progress({"stage": "verified", "pct": 1.0, "message": f"{primary.label} connected"})
            return {
                "tool_connection": guided_setup.current_tool_connection(ctx),
                "receipt": receipt,
            }

        try:
            return {"job_id": ctx.jobs.submit(work, write=True)}
        except Exception:
            _TOOL_SETUP_LOCK.release()
            raise

    @r.post("/source-data")
    def source_data(request: Request, body: GuidedSourceDataBody) -> dict:
        ctx = request.app.state.ctx
        mouser = (
            body.mouser_api_key.strip()
            if not body.skipped and body.mouser_api_key is not None
            else None
        )
        digikey_id = (
            body.digikey_client_id.strip()
            if not body.skipped and body.digikey_client_id is not None
            else None
        )
        digikey_secret = (
            body.digikey_client_secret.strip()
            if not body.skipped and body.digikey_client_secret is not None
            else None
        )
        submitted_mouser = bool(mouser)
        submitted_digikey = bool(digikey_id and digikey_secret)
        partial_digikey = bool(digikey_id) != bool(digikey_secret)
        if partial_digikey:
            raise ValueError("DigiKey needs both Client ID and Client Secret")
        if not body.skipped and not (submitted_mouser or submitted_digikey):
            raise ValueError("connect Mouser or DigiKey, or skip this optional step")
        if submitted_mouser:
            from stockroom.enrich.mouser import validate_api_key

            result = validate_api_key(mouser or "")
            if result == "auth_error":
                raise ValueError("Mouser rejected that API key")
            if result not in {"ok", "not_found"}:
                raise ApiError(503, "Mouser could not be reached; try this step again")
        if submitted_digikey:
            from stockroom.enrich.digikey_api import validate_credentials

            result = validate_credentials(digikey_id or "", digikey_secret or "")
            if result == "auth_error":
                raise ValueError("DigiKey rejected those API credentials")
            if result != "ok":
                raise ApiError(503, "DigiKey could not be reached; try this step again")
        if mouser is not None:
            ctx.config.mouser_api_key = mouser
        if digikey_id is not None:
            ctx.config.digikey_client_id = digikey_id
        if digikey_secret is not None:
            ctx.config.digikey_client_secret = digikey_secret
        ctx.config.save()
        guided_setup.record_source_decision(ctx.config, skipped=body.skipped)
        return _status(ctx)

    @r.post("/complete")
    def complete(request: Request) -> dict:
        # Dismiss the welcome screen keeping the current (e.g. auto-created default) library.
        ctx = request.app.state.ctx
        _require_primary_eda(ctx)
        document = guided_setup.status(
            ctx,
            _github_status(repository=guided_setup.github_remote(ctx.repo)),
        )
        if not document["ready"]:
            raise ValueError(f"complete the {document['step']} setup step first")
        onb.complete_onboarding(ctx.config)
        guided_setup.record_completion(ctx.config)
        return _status(ctx)

    return r
