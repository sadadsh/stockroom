"""The projects surface (M7a-5): register / list / get / delete / audit external
KiCad projects through the ProjectOps engine (spec section 8). A registered project
is external to Stockroom: it is referenced by path, never owned; only its
registration record lives in the library repo.

List reads the derived project index (warm, rebuilt on register/delete); detail loads
the full canonical record. The audit resolves the ACTIVE profile's footprints/models
dirs at request time (projects are profile-independent, but the pin/pad and 3D-model
checks read against whichever library is active) and returns a shareable markdown report.

Routers never set a status code or invent an error shape: they raise the engine's own
exceptions and api/errors.py maps them (ValueError -> 400, FileNotFoundError -> 404).

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import threading
from dataclasses import asdict, replace
from pathlib import Path

from fastapi import APIRouter, Depends, Request, Response

from stockroom.api.schemas import (
    ApproveReviewBody,
    AssemblyEventBody,
    AssignGroupBody,
    ConformBody,
    ConnectProjectRemoteBody,
    DiscoverProjectsBody,
    ManualFillBody,
    ProjectSummary,
    RegisterProjectBody,
    RequestChangesBody,
    SetDesignRulesBody,
    SetFieldsBody,
    SetNetClassesBody,
    SetNetclassPatternsBody,
    SetSettingsBody,
    ShareWorkBody,
    StackupBody,
    StartAssemblyBody,
    StartWorkBody,
)
from stockroom.kicad.errors import KiCadCliError
from stockroom.mutation.project_ops import project_capabilities
from stockroom.projects.adapters import discover_projects, get_adapter
from stockroom.projects.collaboration import (
    CollaborationError,
    ReviewManager,
    WorkSessionManager,
    work_session_recovery,
)
from stockroom.projects.native_open import open_project_document
from stockroom.projects.parity import PROJECT_TOOLS, parity_payload
from stockroom.projects.review_evidence import (
    attach_native_validation,
    build_review_evidence,
    review_validation_key,
    run_review_native_validation,
)
from stockroom.vcs.locks import GitLfsLockService
from stockroom.vcs.repo import GitRepo
from stockroom.vcs.sync import SyncEngine

_WORK_SESSION_LOCKS: dict[str, threading.RLock] = {}
_WORK_SESSION_LOCKS_GUARD = threading.Lock()


def _description_payload(description) -> dict:
    adapter = get_adapter(description.adapter_key)
    return {
        "eda": description.adapter_key,
        "eda_label": adapter.label,
        "name": description.name,
        "root": description.root.as_posix(),
        "descriptor": description.descriptor,
        "boards": list(description.boards),
        "schematics": list(description.schematics),
    }


def _work_session_lock(project_id: str) -> threading.RLock:
    with _WORK_SESSION_LOCKS_GUARD:
        return _WORK_SESSION_LOCKS.setdefault(project_id, threading.RLock())


def _project_repo(rec) -> GitRepo:
    if not rec.git_root:
        raise ValueError("link the project to a Git repository before starting work")
    repo = GitRepo(Path(rec.git_root))
    if not repo.is_git_repo():
        raise ValueError("the linked project repository is unavailable")
    return repo


def _collaboration_payload(rec, ctx) -> dict:
    repo = _project_repo(rec)
    session = ctx.work_session_store.active(rec.id)
    ahead_behind = repo.ahead_behind() if repo.has_upstream() else None
    ahead, behind = ahead_behind or (0, 0)
    dirty = [repo._rel(path) for path in repo.dirty_paths()]
    recovery = (
        work_session_recovery(
            repo,
            GitLfsLockService(repo),
            session,
            verify_claims=False,
            trust_claims=session.id in ctx.work_session_verified,
        )
        if session is not None
        else None
    )
    return {
        "repository": {
            "root": repo.root.as_posix(),
            "remote": repo.remote_url(),
            "branch": repo.current_branch(),
            "commit": repo.head(),
            "clean": not dirty,
            "dirty_paths": dirty,
            "has_remote": repo.has_remote(),
            "has_upstream": repo.has_upstream(),
            "ahead": ahead,
            "behind": behind,
        },
        "session": asdict(session) if session is not None else None,
        "recovery": recovery,
    }


def _bom_evidence(rec, rows: list[dict]) -> dict:
    """Stable provenance for the live, format-neutral BOM snapshot."""

    source_commit = ""
    if rec.git_root:
        repo = GitRepo(Path(rec.git_root))
        if repo.is_git_repo():
            source_commit = repo.head()
    payload = {
        "eda": rec.eda,
        "variant": "Default",
        "source_commit": source_commit,
        "source_documents": list(rec.sheet_paths),
        "rows": rows,
    }
    digest = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "eda": rec.eda,
        "variant": "Default",
        "source_commit": source_commit,
        "source_documents": list(rec.sheet_paths),
        "bom_digest": digest,
        "repository_pinned": bool(source_commit),
    }


def projects_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/projects", dependencies=[Depends(require_token)])
    visual_cache: dict[str, tuple[tuple, object]] = {}

    def visual_source_key(rec) -> tuple:
        """Fingerprint native documents without changing their contents."""

        rows = []
        for relative in (*rec.sheet_paths, *rec.board_paths):
            path = Path(rec.root) / relative
            try:
                stat = path.stat()
                rows.append((relative, stat.st_size, stat.st_mtime_ns))
            except OSError:
                rows.append((relative, -1, -1))
        return rec.eda or "kicad", tuple(rows)

    def project_visual_bundle(ctx, project_id: str, *, refresh: bool = False):
        rec = ctx.project_ops.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        source_key = visual_source_key(rec)
        cached = visual_cache.get(project_id)
        if not refresh and cached is not None and cached[0] == source_key:
            return cached[1]
        if not refresh:
            return None
        adapter = get_adapter(rec.eda or "kicad")
        if (rec.eda or "kicad") == "kicad":
            # KiCad CLI may write a .kicad_prl preference sidecar while exporting.
            # Render a complete mirror so viewing a board cannot dirty the Git checkout.
            with tempfile.TemporaryDirectory(prefix="stockroom-kicad-render-") as raw:
                mirror_root = Path(raw) / "project"
                shutil.copytree(
                    Path(rec.root),
                    mirror_root,
                    symlinks=True,
                    ignore=shutil.ignore_patterns(".git", "Project Outputs for *"),
                )
                bundle = adapter.render(
                    replace(rec, root=mirror_root.as_posix(), git_root=None)
                )
        else:
            bundle = adapter.render(rec)
        visual_cache[project_id] = (source_key, bundle)
        return bundle

    @r.get("")
    def list_projects(request: Request) -> list:
        ctx = request.app.state.ctx
        return [ProjectSummary.from_row(row).model_dump() for row in ctx.project_index.all()]

    @r.post("")
    def register_project(request: Request, body: RegisterProjectBody) -> dict:
        # A bad/nonexistent dir, a dir with no project files, an ambiguous dir holding
        # both EDAs with no explicit choice, or an already-registered root each raises
        # ValueError in the store -> 400 via the error layer.
        ctx = request.app.state.ctx
        rec = ctx.project_ops.register(body.root, eda=body.eda)
        ctx.rebuild_project_index()
        return dict(rec.to_dict(), capabilities=project_capabilities(rec))

    @r.post("/discover")
    def discover_linkable_projects(body: DiscoverProjectsBody) -> dict:
        projects = discover_projects(Path(body.candidate), requested=body.eda)
        return {"projects": [_description_payload(project) for project in projects]}

    @r.get("/{project_id}/workspace")
    def project_workspace(request: Request, project_id: str) -> dict:
        """The format-neutral shell used by every rebuilt Projects route."""

        rec = request.app.state.ctx.project_ops.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        adapter = get_adapter(rec.eda)
        return {
            "project": rec.to_dict(),
            "eda_label": adapter.label,
            "tools": list(PROJECT_TOOLS),
            "parity": parity_payload(),
            "runtime": asdict(adapter.runtime(rec)),
            "documents": [asdict(document) for document in adapter.documents(rec)],
        }

    @r.get("/{project_id}/board-geometry")
    def project_board_geometry(request: Request, project_id: str) -> dict:
        """Read native placement geometry through the selected EDA adapter."""

        rec = request.app.state.ctx.project_ops.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        return get_adapter(rec.eda or "kicad").board_geometry(rec)

    @r.post("/{project_id}/documents/{document_id:path}/open")
    def open_linked_project_document(
        request: Request,
        project_id: str,
        document_id: str,
    ) -> dict:
        """Open one adapter-reported document through the Windows association."""

        rec = request.app.state.ctx.project_ops.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        document = open_project_document(
            Path(rec.root),
            document_id,
            get_adapter(rec.eda).documents(rec),
        )
        return {
            "opened": True,
            "document_id": document.document_id,
            "path": document.path,
        }

    @r.get("/{project_id}/visuals")
    def project_visuals(
        request: Request,
        project_id: str,
        refresh: bool = False,
    ) -> dict:
        """Return cached visuals, rendering native documents only after explicit refresh."""

        ctx = request.app.state.ctx
        bundle = project_visual_bundle(
            ctx,
            project_id,
            refresh=refresh,
        )
        if bundle is not None:
            return bundle.evidence
        rec = ctx.project_ops.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        adapter_key = rec.eda or "kicad"
        adapter = get_adapter(adapter_key)
        body = {
            "schema_version": 1,
            "adapter": adapter_key,
            "status": "blocked",
            "runtime": {"name": getattr(adapter, "label", adapter_key), "version": ""},
            "documents": [],
            "summary": {"documents": 0, "artifacts": 0, "blocked": 0},
            "detail": (
                "Native previews are paused. Choose Render PCB to run the selected EDA tool."
            ),
        }
        body["digest"] = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return body

    @r.get("/{project_id}/visuals/{artifact_id}")
    def project_visual_artifact(
        request: Request,
        project_id: str,
        artifact_id: str,
    ) -> Response:
        """Serve one immutable artifact from the same native render bundle."""

        bundle = project_visual_bundle(
            request.app.state.ctx,
            project_id,
        )
        artifact = bundle.artifacts.get(artifact_id) if bundle is not None else None
        if artifact is None:
            raise FileNotFoundError(
                f"no such project visual artifact: {artifact_id}"
            )
        return Response(
            content=artifact.content,
            media_type=artifact.media_type,
            headers={
                "Cache-Control": "private, max-age=31536000, immutable",
                "ETag": f'"{artifact_id}"',
            },
        )

    @r.get("/{project_id}/collaboration")
    def project_collaboration(request: Request, project_id: str) -> dict:
        rec = request.app.state.ctx.project_ops.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        if not rec.git_root:
            return {
                "repository": None,
                "session": None,
                "recovery": None,
                "blocked_reason": "Link this project to a Git repository to collaborate.",
            }
        return _collaboration_payload(rec, request.app.state.ctx)

    @r.post("/{project_id}/collaboration/remote")
    def connect_project_remote(
        request: Request,
        project_id: str,
        body: ConnectProjectRemoteBody,
    ) -> dict:
        """Add origin once, then run the existing non-force synchronization."""

        ctx = request.app.state.ctx
        rec = ctx.project_ops.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        with _work_session_lock(project_id):
            repo = _project_repo(rec)
            if repo.remote_url("origin"):
                raise ValueError("origin is already configured for this project")
            repo.add_remote("origin", body.url)
            sync = SyncEngine(repo).sync()
            return {
                "collaboration": _collaboration_payload(rec, ctx),
                "sync": asdict(sync),
            }

    @r.post("/{project_id}/work-sessions")
    def start_work_session(
        request: Request,
        project_id: str,
        body: StartWorkBody,
    ) -> dict:
        ctx = request.app.state.ctx
        rec = ctx.project_ops.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        with _work_session_lock(project_id):
            if ctx.work_session_store.active(project_id) is not None:
                raise CollaborationError(
                    "session_active",
                    "this project already has an active work session",
                )
            allowed = {
                document.path
                for document in get_adapter(rec.eda).documents(rec)
                if document.lock_required
            }
            requested = tuple(dict.fromkeys(body.documents))
            unknown = sorted(set(requested) - allowed)
            if unknown:
                raise CollaborationError(
                    "unknown_document",
                    "only linked project documents can be claimed: " + ", ".join(unknown),
                )
            repo = _project_repo(rec)
            manager = WorkSessionManager(repo, GitLfsLockService(repo))
            session = manager.start(
                owner=body.owner,
                branch=body.branch,
                documents=[Path(rec.root) / path for path in requested],
            )
            ctx.work_session_store.save(project_id, session)
            ctx.work_session_verified.add(session.id)
        return _collaboration_payload(rec, ctx)

    @r.post("/{project_id}/work-sessions/{session_id}/share")
    def share_work_session(
        request: Request,
        project_id: str,
        session_id: str,
        body: ShareWorkBody,
    ) -> dict:
        ctx = request.app.state.ctx
        rec = ctx.project_ops.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        with _work_session_lock(project_id):
            session = ctx.work_session_store.active(project_id)
            if session is None or session.id != session_id:
                raise FileNotFoundError(f"no such active work session: {session_id}")
            repo = _project_repo(rec)
            updated = WorkSessionManager(repo, GitLfsLockService(repo)).share(
                session,
                message=body.message,
            )
            ctx.work_session_store.save(project_id, updated)
            ctx.work_session_verified.add(updated.id)
        return _collaboration_payload(rec, ctx)

    @r.post("/{project_id}/work-sessions/{session_id}/resume")
    def resume_work_session(
        request: Request,
        project_id: str,
        session_id: str,
    ) -> dict:
        ctx = request.app.state.ctx
        rec = ctx.project_ops.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        with _work_session_lock(project_id):
            session = ctx.work_session_store.active(project_id)
            if session is None or session.id != session_id:
                raise FileNotFoundError(f"no such active work session: {session_id}")
            repo = _project_repo(rec)
            resumed = WorkSessionManager(repo, GitLfsLockService(repo)).resume(session)
            ctx.work_session_store.save(project_id, resumed)
            ctx.work_session_verified.add(resumed.id)
        return _collaboration_payload(rec, ctx)

    @r.post("/{project_id}/work-sessions/{session_id}/finish")
    def finish_work_session(
        request: Request,
        project_id: str,
        session_id: str,
    ) -> dict:
        ctx = request.app.state.ctx
        rec = ctx.project_ops.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        with _work_session_lock(project_id):
            session = ctx.work_session_store.active(project_id)
            if session is None or session.id != session_id:
                raise FileNotFoundError(f"no such active work session: {session_id}")
            repo = _project_repo(rec)
            integrated = WorkSessionManager(
                repo,
                GitLfsLockService(repo),
            ).finish_after_remote_integration(session)
            ctx.work_session_store.clear(project_id, session_id)
            ctx.work_session_verified.discard(session_id)
        return {
            "integrated_commit": integrated,
            "collaboration": _collaboration_payload(rec, ctx),
        }

    @r.get("/{project_id}/reviews")
    def list_reviews(request: Request, project_id: str) -> dict:
        ctx = request.app.state.ctx
        rec = ctx.project_ops.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        repo = _project_repo(rec)
        session = ctx.work_session_store.active(project_id)
        base_branch = session.base_branch if session is not None else repo.current_branch()
        candidates = ReviewManager(repo).list_candidates(base_branch=base_branch)
        return {
            "base_branch": base_branch,
            "candidates": [asdict(candidate) for candidate in candidates],
        }

    @r.post("/{project_id}/reviews/approve")
    def approve_review(
        request: Request,
        project_id: str,
        body: ApproveReviewBody,
    ) -> dict:
        ctx = request.app.state.ctx
        rec = ctx.project_ops.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        with _work_session_lock(project_id):
            manager = ReviewManager(_project_repo(rec))
            candidate = manager.discover(
                branch=body.branch,
                base_branch=body.base_branch,
            )
            if candidate.commit != body.commit:
                raise CollaborationError(
                    "review_changed",
                    "the work branch changed after this commit was displayed",
                )
            if candidate.base_commit != body.base_commit:
                raise CollaborationError(
                    "base_changed",
                    "the shared branch changed after this commit was displayed",
                )
            evidence = attach_native_validation(
                build_review_evidence(manager, rec, candidate),
                ctx.review_validation_cache.get(review_validation_key(rec, candidate)),
            )
            if not evidence["reviewable"]:
                raise CollaborationError(
                    "review_evidence_blocked",
                    "resolve the exact commit's source, BOM, semantic, and native validation "
                    "blockers before approval",
                )
            integrated = manager.approve_fast_forward(candidate)
        return {
            "integrated_commit": integrated,
            "candidate": asdict(candidate),
            "evidence_digest": evidence["digest"],
        }

    @r.post("/{project_id}/reviews/evidence")
    def review_evidence(
        request: Request,
        project_id: str,
        body: ApproveReviewBody,
    ) -> dict:
        ctx = request.app.state.ctx
        rec = ctx.project_ops.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        manager = ReviewManager(_project_repo(rec))
        candidate = manager.discover(
            branch=body.branch,
            base_branch=body.base_branch,
        )
        if candidate.commit != body.commit:
            raise CollaborationError(
                "review_changed",
                "the work branch changed after this commit was displayed",
            )
        if candidate.base_commit != body.base_commit:
            raise CollaborationError(
                "base_changed",
                "the shared branch changed after this commit was displayed",
            )
        return attach_native_validation(
            build_review_evidence(manager, rec, candidate),
            ctx.review_validation_cache.get(review_validation_key(rec, candidate)),
        )

    @r.post("/{project_id}/reviews/validate")
    def validate_review(
        request: Request,
        project_id: str,
        body: ApproveReviewBody,
    ) -> dict:
        ctx = request.app.state.ctx
        rec = ctx.project_ops.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        with _work_session_lock(project_id):
            manager = ReviewManager(_project_repo(rec))
            candidate = manager.discover(
                branch=body.branch,
                base_branch=body.base_branch,
            )
            if candidate.commit != body.commit:
                raise CollaborationError(
                    "review_changed",
                    "the work branch changed after this commit was displayed",
                )
            if candidate.base_commit != body.base_commit:
                raise CollaborationError(
                    "base_changed",
                    "the shared branch changed after this commit was displayed",
                )
            validation = run_review_native_validation(manager, rec, candidate)
            ctx.review_validation_cache[review_validation_key(rec, candidate)] = validation
            return validation

    @r.post("/{project_id}/reviews/request-changes")
    def request_review_changes(
        request: Request,
        project_id: str,
        body: RequestChangesBody,
    ) -> dict:
        rec = request.app.state.ctx.project_ops.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        with _work_session_lock(project_id):
            manager = ReviewManager(_project_repo(rec))
            candidate = manager.discover(
                branch=body.branch,
                base_branch=body.base_branch,
            )
            if candidate.commit != body.commit:
                raise CollaborationError(
                    "review_changed",
                    "the work branch changed after this commit was displayed",
                )
            if candidate.base_commit != body.base_commit:
                raise CollaborationError(
                    "base_changed",
                    "the shared branch changed after this commit was displayed",
                )
            event = manager.request_changes(
                candidate,
                reviewer=body.reviewer,
                message=body.message,
            )
        return {
            "event": asdict(event),
            "candidate": asdict(candidate),
        }

    @r.post("/{project_id}/assemblies")
    def start_assembly(
        request: Request,
        project_id: str,
        body: StartAssemblyBody,
    ) -> dict:
        rec = request.app.state.ctx.project_ops.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        return request.app.state.ctx.assembly_store.start(
            rec,
            operator=body.operator,
            boards=body.boards,
            library_parts=_library_parts(request.app.state.ctx),
        )

    @r.get("/{project_id}/assemblies/active")
    def active_assembly(request: Request, project_id: str) -> dict | None:
        if request.app.state.ctx.project_ops.get(project_id) is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        return request.app.state.ctx.assembly_store.active(project_id)

    @r.get("/{project_id}/assemblies/{run_id}")
    def get_assembly(request: Request, project_id: str, run_id: str) -> dict:
        if request.app.state.ctx.project_ops.get(project_id) is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        return request.app.state.ctx.assembly_store.get(project_id, run_id)

    @r.post("/{project_id}/assemblies/{run_id}/events")
    def record_assembly_event(
        request: Request,
        project_id: str,
        run_id: str,
        body: AssemblyEventBody,
    ) -> dict:
        if request.app.state.ctx.project_ops.get(project_id) is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        return request.app.state.ctx.assembly_store.record_event(
            project_id,
            run_id,
            placement_id=body.placement_id,
            state=body.state,
            scanned_mpn=body.scanned_mpn,
            note=body.note,
        )

    @r.post("/{project_id}/assemblies/{run_id}/complete")
    def complete_assembly(request: Request, project_id: str, run_id: str) -> dict:
        if request.app.state.ctx.project_ops.get(project_id) is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        return request.app.state.ctx.assembly_store.complete(project_id, run_id)

    @r.get("/{project_id}")
    def project_detail(request: Request, project_id: str) -> dict:
        ctx = request.app.state.ctx
        rec = ctx.project_ops.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        # capabilities say what this EDA's registration can do here, so the frontend
        # renders tabs from the server's truth instead of hardcoding per-EDA rules.
        return dict(rec.to_dict(), capabilities=project_capabilities(rec))

    @r.delete("/{project_id}", status_code=204)
    def delete_project(request: Request, project_id: str) -> Response:
        # An unknown id raises FileNotFoundError -> 404; a known one unregisters (the
        # external files are never touched) and the index is rebuilt.
        ctx = request.app.state.ctx
        if ctx.project_ops.get(project_id) is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        if ctx.work_session_store.active(project_id) is not None:
            raise CollaborationError(
                "session_active",
                "finish or recover the active work session before unlinking this project",
            )
        if ctx.assembly_store.active(project_id) is not None:
            raise ValueError(
                "complete the active assembly run before unlinking this project"
            )
        ctx.project_ops.delete(project_id)
        visual_cache.pop(project_id, None)
        ctx.checks_cache.pop(project_id, None)  # the cached ERC/DRC is now stale
        ctx.bom_cache.pop(project_id, None)  # the cached BOM is now stale too
        ctx.rebuild_project_index()
        return Response(status_code=204)

    @r.get("/{project_id}/audit")
    def project_audit(request: Request, project_id: str) -> dict:
        # Read-only health pass over the registered sheets. The footprint/model dirs come
        # from the ACTIVE profile at request time (enabling the pin/pad + 3D-model checks);
        # an unknown id raises FileNotFoundError -> 404. The markdown is the shareable report.
        from stockroom.projects.health import audit_report_markdown

        ctx = request.app.state.ctx
        au = ctx.project_ops.audit(
            project_id,
            footprint_dirs=[ctx.profile.library.footprints_dir],
            model_dirs=[ctx.profile.library.models_dir],
        )
        au["markdown"] = audit_report_markdown(au)
        return au

    @r.get("/{project_id}/buildability")
    def buildability(request: Request, project_id: str) -> dict:
        # Fuse completeness (computed live) + the cached ERC/DRC + the cached BOM + the git
        # working tree into ONE ready-to-build verdict (M7g). Read-only, no cache eviction. A
        # cold checks/BOM cache is an honest 'not run yet' hard blocker, NEVER a fabricated
        # pass (a false READY is worse than a false NOT-READY). Unknown id -> 404.
        ctx = request.app.state.ctx
        return ctx.project_ops.buildability(
            project_id,
            checks=ctx.checks_cache.get(project_id),
            bom=ctx.bom_cache.get(project_id),
        )

    @r.post("/{project_id}/checks")
    def run_checks(request: Request, project_id: str) -> dict:
        # Structured ERC (root schematic) + DRC (each board) via kicad-cli, run off the
        # request path as a job with SSE progress (each check can take seconds). The
        # unknown-id 404 is resolved before the cli gate; a missing kicad-cli is an
        # honest 502 (never a fabricated clean pass, Decision 8). The result is cached
        # in AppContext so Overview and Buildability read one consistent verdict.
        ctx = request.app.state.ctx
        # gate BEFORE the job is submitted: an Altium project gets its honest 400 now,
        # never a job that fails asynchronously
        ctx.project_ops.require_kicad(project_id)
        if not ctx.cli.available:
            raise KiCadCliError(
                "kicad-cli not found; install KiCad 10 (or set its path in Settings) to run ERC and DRC"
            )

        def work(progress):
            result = ctx.project_ops.checks(project_id, progress=progress)
            # A DELETE may have landed (and evicted the cache) while this ran; do not
            # resurrect a cache entry for a now-gone id (project ids are reusable slugs).
            if ctx.project_ops.get(project_id) is not None:
                ctx.checks_cache[project_id] = result
            return result

        return {"job_id": ctx.jobs.submit(work)}

    @r.get("/{project_id}/checks")
    def get_checks(request: Request, project_id: str) -> dict:
        # The cached last run, or an honest not-run shape (never a fabricated pass) so
        # the frontend can render a stable "not checked yet" state. Unknown id -> 404.
        ctx = request.app.state.ctx
        rec = ctx.project_ops.require_kicad(project_id)
        cached = ctx.checks_cache.get(project_id)
        if cached is None:
            return {"project": rec.name, "ran_at": None, "erc": None, "drc": [], "summary": None}
        return cached

    @r.post("/{project_id}/bom")
    def build_bom(request: Request, project_id: str, body: dict | None = None) -> dict:
        # Build a grouped, priced BOM off the request path as a job with SSE progress
        # (pricing each unique MPN through the enrich layer is network-bound). Grouping is
        # offline, so there is NO kicad-cli gate: the BOM works without KiCad installed;
        # pricing degrades honestly to unpriced lines when the enrich layer cannot reach a
        # distributor (Decision 8), never a fabricated price. Cached in AppContext so a
        # re-open renders instantly. Unknown id -> 404.
        ctx = request.app.state.ctx
        if ctx.project_ops.get(project_id) is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        boards = (body or {}).get("boards", 1)
        tax_rate = (body or {}).get("tax_rate", 0.0)

        def work(progress):
            price_lookup = _bom_price_lookup(ctx)
            # Combine the schematic with the active profile's library: fill blank identity + price
            # from the library's stored prices first, the enrich layer second.
            library_parts = _library_parts(ctx)
            result = ctx.project_ops.bom(
                project_id,
                boards=boards,
                tax_rate=tax_rate,
                library_parts=library_parts,
                price_lookup=price_lookup,
                progress=progress,
            )
            # A DELETE may have landed (and evicted the cache) during this network-bound
            # build; do not resurrect a cache entry for a now-gone id (ids are reusable
            # name-slugs, so a re-registered same-named project would surface stale data).
            if ctx.project_ops.get(project_id) is not None:
                ctx.bom_cache[project_id] = result
            return result

        return {"job_id": ctx.jobs.submit(work)}

    @r.get("/{project_id}/bom/live")
    def get_live_bom(request: Request, project_id: str, boards: int = 1) -> dict:
        """Build the current native BOM immediately without a network pricing pass.

        KiCad and Altium terminate at their placement readers. Grouping, library
        identity, quantities, build math, and the response shape are shared.
        """

        ctx = request.app.state.ctx
        rec = ctx.project_ops.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        result = ctx.project_ops.bom(
            project_id,
            boards=boards,
            library_parts=_library_parts(ctx),
            price_lookup=None,
        )
        result["evidence"] = _bom_evidence(rec, result["lines"])
        return result

    @r.get("/{project_id}/bom/live/export")
    def export_live_bom(
        request: Request,
        project_id: str,
        boards: int = 1,
        kind: str = "csv",
    ) -> Response:
        """Export the same immediate, format-neutral BOM shown in the rebuilt UI."""

        from stockroom.projects.bom_export import project_bom_export

        ctx = request.app.state.ctx
        rec = ctx.project_ops.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        live = ctx.project_ops.bom(
            project_id,
            boards=boards,
            library_parts=_library_parts(ctx),
            price_lookup=None,
        )
        out = project_bom_export(live, kind, boards=boards)
        data = out["data"]
        body = data.encode("utf-8") if isinstance(data, str) else data
        return Response(
            content=body,
            media_type=out["content_type"],
            headers={"Content-Disposition": f'attachment; filename="{out["filename"]}"'},
        )

    @r.get("/{project_id}/bom")
    def get_bom(request: Request, project_id: str) -> dict:
        # The cached last build, or an honest not-built shape so the frontend renders a
        # stable "not built yet" state (summary None, never a fabricated cost). Unknown id -> 404.
        ctx = request.app.state.ctx
        rec = ctx.project_ops.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        cached = ctx.bom_cache.get(project_id)
        if cached is None:
            return {
                "project": rec.name,
                "ran_at": None,
                "boards": 1,
                "tax_rate": 0.0,
                "priced": False,
                "line_count": 0,
                "component_count": 0,
                "lines": [],
                "summary": None,
                "by_source": None,
                "cost_at_qty": None,
                "build": None,
            }
        return cached

    @r.post("/{project_id}/bom/reprice")
    def reprice_bom_route(request: Request, project_id: str, body: dict | None = None) -> dict:
        # Re-cost the CACHED BOM for a new build quantity + tax/tariff rate, PURELY over the
        # already-built lines (no schematic re-read, no network, no kicad-cli): changing the
        # build size or the tax rate is just quantity + percentage math over the stored price
        # ladders, so it is synchronous and instant. Re-caches so procurement/exports and a
        # re-open see the same numbers. No cached build yet -> an honest not-built shape.
        # Unknown id -> 404.
        from stockroom.projects.bom import reprice_bom

        ctx = request.app.state.ctx
        rec = ctx.project_ops.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        boards = (body or {}).get("boards", 1)
        tax_rate = (body or {}).get("tax_rate", 0.0)
        cached = ctx.bom_cache.get(project_id)
        if cached is None:
            return {
                "project": rec.name,
                "ran_at": None,
                "boards": 1,
                "tax_rate": 0.0,
                "priced": False,
                "line_count": 0,
                "component_count": 0,
                "lines": [],
                "summary": None,
                "by_source": None,
                "cost_at_qty": None,
                "build": None,
            }
        result = reprice_bom(cached, boards, tax_rate)
        ctx.bom_cache[project_id] = result
        return result

    @r.get("/{project_id}/bom/export")
    def export_bom(
        request: Request,
        project_id: str,
        kind: str = "csv",
        boards: int | None = None,
        spares_pct: float = 0.0,
        pcb_multiple: int = 3,
        tax_rate: float = 0.0,
        shipping: float = 0.0,
        labour_per_board: float = 0.0,
        assembly_surcharge_rate: float = 0.0,
    ):
        # Render the CACHED BOM into a downloadable export (M7d): kind is one of
        # csv/priced/cart/jlcpcb/xlsx/procurement. Read-only, offline. An unknown kind is a
        # ValueError -> 400; an unbuilt project is a 400 (nothing to export yet, never an
        # empty/fabricated file); an unknown id -> 404. The procurement knobs (spares,
        # pcb_multiple, tax, shipping, assembly) pass through to the procurement sheet.
        from stockroom.projects.bom_export import project_bom_export

        ctx = request.app.state.ctx
        rec = ctx.project_ops.get(project_id)
        if rec is None:
            raise FileNotFoundError(f"no such project: {project_id}")
        cached = ctx.bom_cache.get(project_id)
        if cached is None or cached.get("ran_at") is None:
            raise ValueError("build the BOM before exporting it")
        out = project_bom_export(
            cached,
            kind,
            boards=boards,
            spares_pct=spares_pct,
            pcb_multiple=pcb_multiple,
            tax_rate=tax_rate,
            shipping=shipping,
            labour_per_board=labour_per_board,
            assembly_surcharge_rate=assembly_surcharge_rate,
        )
        data = out["data"]
        body = data.encode("utf-8") if isinstance(data, str) else data
        return Response(
            content=body,
            media_type=out["content_type"],
            headers={"Content-Disposition": f'attachment; filename="{out["filename"]}"'},
        )

    @r.get("/{project_id}/fab")
    def fab_status(request: Request, project_id: str) -> dict:
        # The Fab panel's honest gate (M7i): has this project a board to fabricate, and is
        # kicad-cli available. Read-only, no shell-out. Unknown id -> 404.
        return request.app.state.ctx.project_ops.fab_preview(project_id)

    @r.get("/{project_id}/fab/export")
    def fab_export(
        request: Request,
        project_id: str,
        board: str = "",
        drill_format: str = "excellon",
        drill_map: bool = True,
        include_pos: bool = True,
        pos_format: str = "csv",
        protel_ext: bool = True,
    ):
        # Plot the manufacturing bundle (gerbers + drill + placement) via kicad-cli and stream
        # it as a downloadable zip (M7i). Read-only: nothing is written into the project tree.
        # A project with no board is a ValueError -> 400; a missing/failed kicad-cli is a
        # KiCadCliError -> 502 (never a fabricated or empty zip); an unknown id -> 404.
        out = request.app.state.ctx.project_ops.fab_export(
            project_id,
            board=board or None,
            drill_format=drill_format,
            drill_map=drill_map,
            include_pos=include_pos,
            pos_format=pos_format,
            protel_ext=protel_ext,
        )
        return Response(
            content=out["data"],
            media_type=out["content_type"],
            headers={"Content-Disposition": f'attachment; filename="{out["filename"]}"'},
        )

    @r.get("/{project_id}/file")
    def project_file(request: Request, project_id: str, path: str):
        # Serve the raw bytes of one REGISTERED project KiCad file for the in-app kicanvas
        # viewer (M7 #11). Read-only, authed. Only a registered path is served (allowlist, no
        # traversal); an unknown id / unregistered path / escape / missing file is a 404. The
        # bytes are returned as text/plain so the viewer can inline them as a kicanvas-source.
        data = request.app.state.ctx.project_ops.project_file(project_id, path)
        return Response(content=data, media_type="text/plain; charset=utf-8")

    @r.get("/{project_id}/revisions")
    def project_revisions(request: Request, project_id: str) -> dict:
        # The project's git history, for the revision-diff pickers (M7d). A project not under
        # git is an honest {under_git: False, revisions: []}; an unknown id -> 404.
        ctx = request.app.state.ctx
        return ctx.project_ops.revisions(project_id)

    @r.get("/{project_id}/bom/diff")
    def bom_diff(request: Request, project_id: str, a: str = "", b: str = "") -> dict:
        # Diff the BOM between revision `a` (reconstructed from the project's git) and `b`
        # (blank = the current build). The current build's cached priced lines feed the
        # cost/lead deltas so they are meaningful. A missing `a` or a non-git project is a
        # ValueError -> 400; an unknown id -> 404.
        ctx = request.app.state.ctx
        cached = ctx.bom_cache.get(project_id)
        current_rows = cached["lines"] if (cached and cached.get("ran_at")) else None
        return ctx.project_ops.bom_diff(project_id, a, b, current_rows=current_rows)

    @r.get("/{project_id}/design")
    def get_design(request: Request, project_id: str, floor: str = "none") -> dict:
        # The project's current net classes + design rules read straight from its
        # .kicad_pro, plus a fab-floor validation and the fab-floor catalog for the
        # picker (M7e). Read-only. Unknown id -> 404; a project with no .kicad_pro is an
        # honest empty shape, never a crash.
        ctx = request.app.state.ctx
        return ctx.project_ops.design_settings(project_id, floor=floor)

    @r.patch("/{project_id}/net-classes")
    def patch_net_classes(request: Request, project_id: str, body: SetNetClassesBody) -> dict:
        # Edit the project's net classes: reconcile the submitted set onto the on-disk
        # classes and write net_settings.classes back as a minimal diff, one scoped commit
        # on the project's OWN git (M7e). A class with no name is a clean 422; an unknown id
        # -> 404; a project not under git (or without a .kicad_pro) -> 400; a GitError -> 503.
        # A net-class change can alter DRC, so the stale cached ERC/DRC is evicted (never a
        # fabricated pass) and the next check re-runs honestly.
        ctx = request.app.state.ctx
        result = ctx.project_ops.set_net_classes(
            project_id,
            [c.model_dump() for c in body.classes],
            deleted=body.deleted,
            floor=body.floor,
        )
        ctx.checks_cache.pop(project_id, None)
        return result

    @r.patch("/{project_id}/design-rules")
    def patch_design_rules(request: Request, project_id: str, body: SetDesignRulesBody) -> dict:
        # Edit the board design-rule constraints (and, when given, the track/via/diff-pair
        # size lists), one scoped commit on the project's own git (M7e). Unknown id -> 404;
        # a project not under git (or without a .kicad_pro) -> 400; a GitError -> 503. The
        # stale cached ERC/DRC is evicted since a design-rule change can alter DRC outcomes.
        ctx = request.app.state.ctx
        result = ctx.project_ops.set_design_rules(
            project_id,
            body.rules,
            track_widths=body.track_widths,
            via_dimensions=body.via_dimensions,
            diff_pair_dimensions=body.diff_pair_dimensions,
        )
        ctx.checks_cache.pop(project_id, None)
        return result

    @r.patch("/{project_id}/netclass-patterns")
    def patch_netclass_patterns(
        request: Request, project_id: str, body: SetNetclassPatternsBody
    ) -> dict:
        # Replace the project's netclass-pattern assignments (net-name glob -> net class),
        # one scoped commit on the project's OWN git (roadmap #4). A blank pattern/net class is
        # a clean 422; an unknown id -> 404; a project not under git (or without a .kicad_pro),
        # or a row referencing a net class the project does not define -> 400; a GitError -> 503.
        # A pattern change alters DRC net grouping, so the stale cached ERC/DRC is evicted and
        # the next check re-runs honestly.
        ctx = request.app.state.ctx
        result = ctx.project_ops.set_netclass_patterns(
            project_id, [p.model_dump() for p in body.patterns]
        )
        ctx.checks_cache.pop(project_id, None)
        return result

    @r.get("/{project_id}/settings")
    def get_settings(request: Request, project_id: str) -> dict:
        # The project's board setup + thickness (from its .kicad_pcb) AND its .kicad_pro
        # settings (ERC/DRC rule severities, the ERC pin-conflict matrix, project text variables)
        # plus the editor catalogs (M7f-A + A2). Read-only. Unknown id -> 404; a project with no
        # board and/or no .kicad_pro is an honest empty shape (pin_map None, never fabricated).
        ctx = request.app.state.ctx
        return ctx.project_ops.board_settings(project_id)

    @r.patch("/{project_id}/settings")
    def patch_settings(request: Request, project_id: str, body: SetSettingsBody) -> dict:
        # Write board setup / thickness (to the .kicad_pcb) and/or ERC/DRC severities, the ERC
        # pin map, project text variables (to the .kicad_pro) as a minimal diff, one atomic
        # commit on the project's OWN git (M7f-A + A2). Unknown id -> 404; a project not under
        # git, with no board (for a board edit) or no .kicad_pro (for a pro edit), nothing to
        # write, or a bad value -> 400; a GitError -> 503. A severity/board change can alter
        # ERC/DRC outcomes, so the stale cached ERC/DRC is evicted and the next check re-runs.
        ctx = request.app.state.ctx
        result = ctx.project_ops.set_settings(
            project_id,
            board_setup=body.board_setup,
            thickness=body.thickness,
            erc_severities=body.erc_severities,
            drc_severities=body.drc_severities,
            erc_pin_map=body.erc_pin_map,
            text_variables=body.text_variables,
        )
        ctx.checks_cache.pop(project_id, None)
        return result

    @r.get("/{project_id}/fields")
    def get_fields(request: Request, project_id: str) -> dict:
        # The KiField bulk-field grid: every placed component across every sheet as a
        # rows-by-fields table, Reference read-only (M7h). Read-only. Unknown id -> 404; a
        # project with no schematic is an honest empty grid.
        ctx = request.app.state.ctx
        return ctx.project_ops.fields(project_id)

    @r.patch("/{project_id}/fields")
    def patch_fields(request: Request, project_id: str, body: SetFieldsBody) -> dict:
        # Apply a batch of field-cell edits across the project's schematic as ONE atomic commit
        # on its own git (M7h). Unknown id -> 404; editing the Reference field, an unknown or
        # non-editable ref, a project not under git, or uncommitted schematic changes -> 400; a
        # GitError -> 503. A field change alters the netlist/BOM, so the stale cached ERC/DRC + BOM
        # are evicted and the next check/build re-runs honestly.
        ctx = request.app.state.ctx
        result = ctx.project_ops.set_fields(project_id, [e.model_dump() for e in body.edits])
        ctx.checks_cache.pop(project_id, None)
        ctx.bom_cache.pop(project_id, None)
        return result

    @r.get("/{project_id}/conform")
    def get_conform(request: Request, project_id: str) -> dict:
        # The object-conform category catalog (Title Case labels + suggested sizes) plus the
        # project's honest state (has a board / has a sheet / under git), for the editor's
        # initial render (M7f-B). Read-only. Unknown id -> 404.
        ctx = request.app.state.ctx
        return ctx.project_ops.conform_catalog(project_id)

    @r.post("/{project_id}/conform/preview")
    def preview_conform(request: Request, project_id: str, body: ConformBody) -> dict:
        # A dry-run of an object conform: per-file change counts for the given targets, computed
        # WITHOUT writing or touching git (M7f-B). Unknown id -> 404; an empty selection or a bad
        # size/thickness/category -> 400.
        ctx = request.app.state.ctx
        return ctx.project_ops.conform_preview(project_id, body.pcb(), body.sch())

    @r.patch("/{project_id}/conform")
    def apply_conform(request: Request, project_id: str, body: ConformBody) -> dict:
        # Apply the object conform across every board + sheet as ONE atomic commit on the
        # project's own git (M7f-B). Unknown id -> 404; an empty selection, a bad target, or a
        # project not under git -> 400; a GitError -> 503. Conforming text size/thickness can
        # change DRC (text height/thickness, silk clearance), so the stale cached ERC/DRC is
        # evicted and the next check re-runs honestly.
        ctx = request.app.state.ctx
        result = ctx.project_ops.conform_apply(project_id, body.pcb(), body.sch())
        ctx.checks_cache.pop(project_id, None)
        return result

    @r.get("/{project_id}/stackup")
    def get_stackup(request: Request, project_id: str) -> dict:
        # The project's current physical layer stack (structured layers + finish + constraints),
        # its copper layer names, overall thickness, and the fab-preset catalog, for the Stackup
        # editor's render (M7f-C). Read-only. Unknown id -> 404; a project with no board is an
        # honest empty shape.
        ctx = request.app.state.ctx
        return ctx.project_ops.stackup_read(project_id)

    @r.post("/{project_id}/stackup/preview")
    def preview_stackup(request: Request, project_id: str, body: StackupBody) -> dict:
        # A dry-run of a stackup change: the resulting stackup + new thickness + whether it differs,
        # WITHOUT writing or touching git (M7f-C). Unknown id -> 404; a bad/empty/conflicting mode,
        # an unknown or layer-mismatched preset, or a bad field value -> 400.
        ctx = request.app.state.ctx
        return ctx.project_ops.stackup_preview(
            project_id,
            preset_key=body.preset_key,
            copper_finish=body.copper_finish,
            dielectric_constraints=body.dielectric_constraints,
            layer_edits=body.layer_edits,
        )

    @r.patch("/{project_id}/stackup")
    def apply_stackup(request: Request, project_id: str, body: StackupBody) -> dict:
        # Apply a stackup change (fab preset OR per-field edits) as ONE atomic commit on the
        # project's own git (M7f-C). Unknown id -> 404; a bad request, no board, or a project not
        # under git -> 400; a GitError -> 503. A stackup/thickness change can affect DRC/impedance
        # outcomes, so the stale cached ERC/DRC is evicted and the next check re-runs honestly.
        ctx = request.app.state.ctx
        result = ctx.project_ops.stackup_apply(
            project_id,
            preset_key=body.preset_key,
            copper_finish=body.copper_finish,
            dielectric_constraints=body.dielectric_constraints,
            layer_edits=body.layer_edits,
        )
        ctx.checks_cache.pop(project_id, None)
        return result

    @r.get("/{project_id}/prepare")
    def get_prepare(request: Request, project_id: str) -> dict:
        # A dry-run of Prepare / Complete-All: the annotate count, the fill plan (per-ref proposed
        # changes matched against the ACTIVE profile's library), and the completion residual before and
        # after the auto-fill, computed WITHOUT writing (M7f-D). Read-only. Unknown id -> 404. The
        # library is loaded lazily (a thunk) so an unknown id 404s before the whole library is read.
        ctx = request.app.state.ctx
        return ctx.project_ops.prepare_read(project_id, library_parts=lambda: _library_parts(ctx))

    @r.post("/{project_id}/prepare")
    def run_prepare(request: Request, project_id: str) -> dict:
        # Prepare / Complete-All: annotate every unannotated reference and auto-fill every blank
        # identity field from the shared library, as ONE atomic commit on the project's own git, run
        # off the request path as a job with SSE progress (M7f-D). The unknown-id 404 and the
        # not-under-git 400 are resolved before the job is submitted (an immediate honest error, not an
        # async one). A Prepare changes the netlist/BOM, so the stale cached ERC/DRC + BOM are evicted.
        ctx = request.app.state.ctx
        rec = ctx.project_ops.require_kicad(project_id)
        if not rec.git_root:
            raise ValueError(
                "this project is not under git; initialize a git repo for it before preparing"
            )

        def work(progress):
            parts = _library_parts(ctx)
            result = ctx.project_ops.prepare_apply(
                project_id, library_parts=parts, progress=progress
            )
            # A DELETE may have landed (and evicted the caches) while this ran; do not resurrect a
            # cache entry for a now-gone id. Evict the stale ERC/DRC + BOM either way.
            if ctx.project_ops.get(project_id) is not None:
                ctx.checks_cache.pop(project_id, None)
                ctx.bom_cache.pop(project_id, None)
            return result

        # write=True: prepare_apply is one atomic commit on the project's git, so it runs on
        # the serialized write lane (never two git Transactions at once).
        return {"job_id": ctx.jobs.submit(work, write=True)}

    @r.post("/{project_id}/prepare/fill")
    def manual_fill(request: Request, project_id: str, body: ManualFillBody) -> dict:
        # Manually link one placed component to a chosen library part (the residual filler for a
        # component Prepare could not match), one atomic commit on the project's own git (M7f-D).
        # Unknown id -> 404; a project not under git, an unknown part, or a missing ref -> 400; a
        # GitError -> 503. A fill changes the netlist/BOM, so the stale cached ERC/DRC + BOM are evicted.
        # The library is loaded lazily (a thunk) so an unknown id 404 / a non-git 400 is returned
        # before the whole shared library is read from disk.
        ctx = request.app.state.ctx
        result = ctx.project_ops.manual_fill(
            project_id, body.ref, body.part_id, library_parts=lambda: _library_parts(ctx)
        )
        ctx.checks_cache.pop(project_id, None)
        ctx.bom_cache.pop(project_id, None)
        return result

    @r.get("/{project_id}/assign")
    def get_assign(request: Request, project_id: str) -> dict:
        # The bulk-assign surface: every placed component with no identified library part, grouped so
        # identical placements are one row, each with its ranked candidates. Read-only, no git.
        # Unknown id -> 404. The library is loaded lazily so an unknown id 404s before it is read.
        ctx = request.app.state.ctx
        return ctx.project_ops.assign_read(project_id, library_parts=lambda: _library_parts(ctx))

    @r.post("/{project_id}/assign")
    def assign_group(request: Request, project_id: str, body: AssignGroupBody) -> dict:
        # Assign one library part to a whole group of identical placements, as ONE atomic commit on the
        # project's own git. Unknown id -> 404; not under git, an unknown part, an empty ref list, or a
        # ref naming no component -> 400 (and nothing written); a GitError -> 503. An assignment changes
        # the netlist/BOM, so the stale cached ERC/DRC + BOM are evicted.
        ctx = request.app.state.ctx
        result = ctx.project_ops.assign_refs(
            project_id, body.refs, body.part_id, library_parts=lambda: _library_parts(ctx)
        )
        ctx.checks_cache.pop(project_id, None)
        ctx.bom_cache.pop(project_id, None)
        return result

    @r.get("/{project_id}/hygiene")
    def get_hygiene(request: Request, project_id: str) -> dict:
        # What syncing this project's workspace hygiene would change: the ignore/attributes rules its
        # EDA tool declares, plus the already-tracked per-user files those rules now cover. Read-only,
        # no git. Unknown id -> 404.
        ctx = request.app.state.ctx
        return ctx.project_ops.hygiene_read(project_id)

    @r.post("/{project_id}/hygiene")
    def sync_hygiene(request: Request, project_id: str) -> dict:
        # Write the rules AND untrack the per-user files, as ONE commit on the project's own git.
        # Both halves are required: an ignore rule has no effect on a file that is already tracked,
        # and those files being tracked is exactly why two peers conflict on them. Unknown id -> 404;
        # not under git, a dirty tree, or a hand-broken managed block -> 400; a GitError -> 503.
        ctx = request.app.state.ctx
        return ctx.project_ops.hygiene_apply(project_id)

    @r.get("/{project_id}/library-pin")
    def get_library_pin(request: Request, project_id: str) -> dict:
        # Which library version this project is pinned to, versus the library on THIS machine
        # (Batch 2 item 2). Read-only. Unknown id -> 404; an unreadable pin file -> 400. The active
        # profile comes from the context because a pin is taken against a specific profile, and two
        # profiles hold different parts inside the same repository.
        ctx = request.app.state.ctx
        return ctx.project_ops.library_pin_read(project_id, profile=ctx.profile.name)

    @r.post("/{project_id}/library-pin")
    def set_library_pin(request: Request, project_id: str) -> dict:
        # Record the library's current commit as this project's pin, as one commit on the PROJECT's
        # own git so it travels with the project. Unknown id -> 404; a project or library not under
        # git, or a pin written by a newer build -> 400; a GitError -> 503.
        ctx = request.app.state.ctx
        return ctx.project_ops.library_pin_apply(project_id, profile=ctx.profile.name)

    @r.post("/{project_id}/restore")
    def restore(request: Request, project_id: str) -> dict:
        # Undo the project's last Prepare / Fill by git-reverting that commit as a new commit
        # (non-destructive) (M7f-D). Unknown id -> 404; a project not under git, a dirty tree, or
        # nothing to restore -> 400; a revert conflict (GitError) -> 503. A restore changes the
        # netlist/BOM, so the stale cached ERC/DRC + BOM are evicted.
        ctx = request.app.state.ctx
        result = ctx.project_ops.restore(project_id)
        ctx.checks_cache.pop(project_id, None)
        ctx.bom_cache.pop(project_id, None)
        return result

    return r


def _library_parts(ctx) -> list:
    """The active profile's shared-library PartRecords, the match library for Prepare / fill. A
    malformed record is skipped (a corrupt library file is a library-side problem surfaced by the
    doctor, and must never crash a Prepare); an absent parts dir yields []."""
    from stockroom.model.part import PartRecord

    parts_dir = ctx.profile.library.parts_dir
    if not parts_dir.exists():
        return []
    out = []
    for json_path in sorted(parts_dir.glob("*.json")):
        try:
            out.append(PartRecord.loads(json_path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001 - a corrupt record drops from the match index, never crashes
            continue
    return out


def _bom_price_lookup(ctx):
    """A price_lookup(mpn) served by Stockroom's own enrich layer: build the same
    pipeline the enrich routes use, enrich each MPN (cache-first), and adapt the result
    into the BOM's flat cost dict. Any failure or a total miss returns None, so the line
    stays honestly unpriced and a price is never invented."""
    from stockroom.api.routers.enrich import _make_pipeline
    from stockroom.projects.bom import enrichment_to_bom_lookup

    pipeline = _make_pipeline(ctx)

    def lookup(mpn):
        try:
            result = pipeline.enrich(mpn, "Other")
        except Exception:  # noqa: BLE001 - a dead lookup leaves the line unpriced, never blocks
            return None
        return enrichment_to_bom_lookup(result)

    return lookup
