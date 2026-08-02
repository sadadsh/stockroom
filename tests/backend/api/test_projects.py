"""The projects surface (M7a-5): /api/projects registers, lists, gets, deletes and
audits external KiCad projects through the ProjectOps engine. Read/list is served
from the derived project index; register/delete rebuild it. The audit resolves the
active profile's footprints/models dirs at request time and returns a markdown report.

No em dashes anywhere (standing owner rule)."""

from __future__ import annotations

from urllib.parse import quote

import pytest

from tests.backend.api.conftest import _drain_job

# a single unannotated resistor symbol with an empty Footprint: yields both an
# `unannotated` (R? reference) and a `no_footprint` finding when audited.
_UNANNOTATED = (
    "  (symbol\n"
    '    (lib_id "Device:R")\n'
    '    (property "Reference" "R?" (at 0 0 0))\n'
    '    (property "Value" "10k" (at 0 0 0))\n'
    '    (property "Footprint" "" (at 0 0 0))\n'
    "  )\n"
)


def _make_project(dir_path, sheet_body=_UNANNOTATED):
    """Materialise an external KiCad project dir: a JSON .kicad_pro plus a .kicad_sch
    holding the given symbols, so register() discovers it and audit() reads it."""
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "board.kicad_pro").write_text("{}", encoding="utf-8")
    (dir_path / "board.kicad_sch").write_text("(kicad_sch\n" + sheet_body + ")\n", encoding="utf-8")
    return dir_path


def _register(client, root) -> dict:
    r = client.post("/api/projects", json={"root": root.as_posix()})
    assert r.status_code == 200, r.text
    return r.json()


def _git_init_commit(root):
    """Give an external project dir its OWN git repo with everything committed, which is the state
    every project write requires (the commit-time gate refuses a project with no git_root)."""
    from stockroom.vcs.repo import GitRepo

    repo = GitRepo(root)
    repo.init()
    repo.commit("seed", sorted(p for p in root.iterdir() if p.is_file()))
    return repo


# ---- list -------------------------------------------------------------------


def test_list_is_empty_before_any_registration(client):
    r = client.get("/api/projects")
    assert r.status_code == 200
    assert r.json() == []


def test_list_returns_registered_projects_as_summaries(client, tmp_path):
    proj = _make_project(tmp_path / "ext" / "board")
    _register(client, proj)
    rows = client.get("/api/projects").json()
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "board"
    assert row["root"] == proj.as_posix()
    assert row["board_count"] == 0  # only a .kicad_pro + .kicad_sch, no .kicad_pcb
    assert row["sheet_count"] == 1
    assert row["has_git"] is False
    assert set(row) == {
        "id",
        "name",
        "root",
        "eda",
        "board_count",
        "sheet_count",
        "has_git",
        "registered_at",
    }


# ---- register ---------------------------------------------------------------


def test_register_returns_the_full_record(client, tmp_path):
    proj = _make_project(tmp_path / "ext" / "board")
    rec = _register(client, proj)
    assert rec["name"] == "board"
    assert rec["root"] == proj.as_posix()
    assert rec["pro_path"] == "board.kicad_pro"
    assert rec["sheet_paths"] == ["board.kicad_sch"]
    # the newly registered project is immediately visible in the rebuilt index
    assert [r["id"] for r in client.get("/api/projects").json()] == [rec["id"]]


def test_register_a_nonexistent_dir_is_a_400(client, tmp_path):
    r = client.post("/api/projects", json={"root": (tmp_path / "nope").as_posix()})
    assert r.status_code == 400


def test_register_a_dir_with_no_kicad_files_is_a_400(client, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    r = client.post("/api/projects", json={"root": empty.as_posix()})
    assert r.status_code == 400


def test_register_an_already_registered_root_is_a_400(client, tmp_path):
    proj = _make_project(tmp_path / "ext" / "board")
    _register(client, proj)
    r = client.post("/api/projects", json={"root": proj.as_posix()})
    assert r.status_code == 400


def test_discover_previews_every_project_before_linking(client, tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _make_project(root, sheet_body=_UNANNOTATED)
    (root / "Amp.PrjPcb").write_text(
        "[Design]\n[Document1]\nDocumentPath=Amp.SchDoc\n[Document2]\nDocumentPath=Amp.PcbDoc\n",
        encoding="utf-8",
    )
    (root / "Amp.SchDoc").write_bytes(b"binary")
    (root / "Amp.PcbDoc").write_bytes(b"binary")

    response = client.post("/api/projects/discover", json={"candidate": root.as_posix()})
    assert response.status_code == 200
    rows = response.json()["projects"]
    assert [(row["eda"], row["name"]) for row in rows] == [
        ("kicad", "board"),
        ("altium", "Amp"),
    ]
    assert rows[0]["schematics"] == ["board.kicad_sch"]
    assert rows[1]["boards"] == ["Amp.PcbDoc"]


def test_workspace_has_the_same_tools_and_document_shape_for_both_edas(
    client, tmp_path, monkeypatch
):
    from stockroom.projects.adapters import get_adapter

    def native_call(*args, **kwargs):
        raise AssertionError("project selection must not start or probe a native tool")

    monkeypatch.setattr(get_adapter("kicad").cli, "version", native_call)
    monkeypatch.setattr(get_adapter("altium").driver, "busy_titles", native_call)
    monkeypatch.setattr(get_adapter("altium").driver, "run_script", native_call)

    kicad = _register(client, _make_project(tmp_path / "kicad"))
    altium_root = tmp_path / "altium"
    altium_root.mkdir()
    (altium_root / "Amp.PrjPcb").write_text(
        "[Design]\n[Document1]\nDocumentPath=Amp.SchDoc\n",
        encoding="utf-8",
    )
    (altium_root / "Amp.SchDoc").write_bytes(b"binary")
    altium = _register(client, altium_root)

    workspaces = [
        client.get(f"/api/projects/{project['id']}/workspace").json() for project in (kicad, altium)
    ]
    assert (
        workspaces[0]["tools"]
        == workspaces[1]["tools"]
        == [
            "design",
            "bom",
            "assemble",
            "changes",
            "releases",
        ]
    )
    assert [document["kind"] for document in workspaces[0]["documents"]] == [
        "project",
        "schematic",
    ]
    assert [document["kind"] for document in workspaces[1]["documents"]] == [
        "project",
        "schematic",
    ]
    assert {workspace["runtime"]["adapter_key"] for workspace in workspaces} == {
        "kicad",
        "altium",
    }


def test_live_bom_has_the_same_evidenced_shape_for_both_edas(client, tmp_path):
    kicad = _register(
        client,
        _make_project(
            tmp_path / "bom-kicad",
            sheet_body=(
                '  (symbol (lib_id "Amplifier_Operational:LM358")'
                ' (property "Reference" "U1" (at 0 0 0))'
                ' (property "Value" "LM358DR" (at 0 0 0))'
                ' (property "MPN" "LM358DR" (at 0 0 0))'
                ' (property "Manufacturer" "TI" (at 0 0 0))'
                ' (property "Footprint" "Package_SO:SOIC-8" (at 0 0 0)))\n'
            ),
        ),
    )
    altium = _register(client, _make_altium_api_project(tmp_path / "bom-altium"))

    payloads = [
        client.get(f"/api/projects/{project['id']}/bom/live?boards=3").json()
        for project in (kicad, altium)
    ]
    for payload, eda in zip(payloads, ("kicad", "altium"), strict=True):
        assert payload["boards"] == 3
        assert payload["line_count"] == 1
        assert payload["component_count"] == 1
        assert payload["lines"][0]["mpn"] == "LM358DR"
        assert payload["lines"][0]["final_qty"] == 3
        assert payload["evidence"]["eda"] == eda
        assert payload["evidence"]["variant"] == "Default"
        assert len(payload["evidence"]["bom_digest"]) == 64
        assert payload["evidence"]["source_documents"]


def test_live_bom_export_is_the_same_one_click_csv_workflow_for_both_edas(
    client, tmp_path
):
    kicad = _register(
        client,
        _make_project(
            tmp_path / "export-kicad",
            sheet_body=(
                '  (symbol (lib_id "Amplifier_Operational:LM358")'
                ' (property "Reference" "U1" (at 0 0 0))'
                ' (property "Value" "LM358DR" (at 0 0 0))'
                ' (property "MPN" "LM358DR" (at 0 0 0))'
                ' (property "Manufacturer" "TI" (at 0 0 0))'
                ' (property "Footprint" "Package_SO:SOIC-8" (at 0 0 0)))\n'
            ),
        ),
    )
    altium = _register(
        client,
        _make_altium_api_project(tmp_path / "export-altium"),
    )

    exports = [
        client.get(
            f"/api/projects/{project['id']}/bom/live/export",
            params={"boards": 3, "kind": "csv"},
        )
        for project in (kicad, altium)
    ]
    assert all(response.status_code == 200 for response in exports)
    assert all(
        response.headers["content-type"].startswith("text/csv")
        for response in exports
    )
    assert all(
        "attachment" in response.headers["content-disposition"]
        for response in exports
    )
    headers = [response.text.splitlines()[0] for response in exports]
    assert headers[0] == headers[1]
    assert all("LM358DR" in response.text for response in exports)


def test_assembly_routes_use_the_same_project_service_contract(client, app_ctx, tmp_path):
    project = _register(client, _make_project(tmp_path / "assembly"))
    calls = []

    class Store:
        def start(self, rec, *, operator, boards, library_parts):
            assert isinstance(library_parts, list)
            calls.append(("start", rec.id, operator, boards))
            return {"id": "run-a", "project_id": rec.id}

        def active(self, project_id):
            calls.append(("active", project_id))
            return {"id": "run-a", "project_id": project_id}

        def get(self, project_id, run_id):
            calls.append(("get", project_id, run_id))
            return {"id": run_id, "project_id": project_id}

        def record_event(
            self,
            project_id,
            run_id,
            *,
            placement_id,
            state,
            scanned_mpn,
            note,
        ):
            calls.append(
                (
                    "event",
                    project_id,
                    run_id,
                    placement_id,
                    state,
                    scanned_mpn,
                    note,
                )
            )
            return {"id": run_id, "project_id": project_id, "event_count": 1}

        def complete(self, project_id, run_id):
            calls.append(("complete", project_id, run_id))
            return {"id": run_id, "project_id": project_id, "status": "completed"}

    app_ctx.assembly_store = Store()
    project_id = project["id"]
    assert (
        client.post(
            f"/api/projects/{project_id}/assemblies",
            json={"operator": "Sadad", "boards": 2},
        ).json()["id"]
        == "run-a"
    )
    assert client.get(f"/api/projects/{project_id}/assemblies/active").json()["id"] == "run-a"
    assert client.get(f"/api/projects/{project_id}/assemblies/run-a").json()["id"] == "run-a"
    assert (
        client.post(
            f"/api/projects/{project_id}/assemblies/run-a/events",
            json={
                "placement_id": "p1",
                "state": "done",
                "scanned_mpn": "ABC",
                "note": "placed",
            },
        ).json()["event_count"]
        == 1
    )
    assert (
        client.post(f"/api/projects/{project_id}/assemblies/run-a/complete").json()["status"]
        == "completed"
    )
    assert calls == [
        ("start", project_id, "Sadad", 2),
        ("active", project_id),
        ("get", project_id, "run-a"),
        ("event", project_id, "run-a", "p1", "done", "ABC", "placed"),
        ("complete", project_id, "run-a"),
    ]


def test_work_session_routes_persist_start_and_share(
    client, app_ctx, tmp_path, monkeypatch
):
    from dataclasses import replace

    from stockroom.projects.collaboration import WorkSession
    from stockroom.vcs.locks import DocumentLock

    project_root, head = _make_git_project(tmp_path / "work-session", _UNANNOTATED)
    project = _register(client, project_root)
    calls = []

    class Manager:
        def __init__(self, repo, locks):
            calls.append(("manager", repo.root.as_posix(), type(locks).__name__))

        def start(self, *, owner, branch, documents):
            calls.append(
                (
                    "start",
                    owner,
                    branch,
                    tuple(path.name for path in documents),
                )
            )
            return WorkSession(
                id="session-a",
                owner=owner,
                branch=branch,
                base_branch="main",
                base_commit=head,
                documents=("board.kicad_sch",),
                locks=(
                    DocumentLock(
                        id="lock-a",
                        path="board.kicad_sch",
                        owner=owner,
                    ),
                ),
                started_at="2026-07-28T12:00:00Z",
            )

        def share(self, session, *, message):
            calls.append(("share", session.id, message))
            return replace(session, shared_commit="b" * 40)

    monkeypatch.setattr(
        "stockroom.api.routers.projects.WorkSessionManager",
        Manager,
    )
    project_id = project["id"]
    started = client.post(
        f"/api/projects/{project_id}/work-sessions",
        json={
            "owner": "Sadad",
            "branch": "work/sadad/power",
            "documents": ["board.kicad_sch"],
        },
    )
    assert started.status_code == 200, started.text
    assert started.json()["session"]["id"] == "session-a"
    assert (
        app_ctx.work_session_store.active(project_id).documents
        == ("board.kicad_sch",)
    )

    shared = client.post(
        f"/api/projects/{project_id}/work-sessions/session-a/share",
        json={"message": "Update power stage"},
    )
    assert shared.status_code == 200, shared.text
    assert shared.json()["session"]["shared_commit"] == "b" * 40
    assert calls[-1] == ("share", "session-a", "Update power stage")


def test_review_routes_discover_and_approve_the_exact_remote_commit(
    client, tmp_path, monkeypatch
):
    from stockroom.projects.collaboration import (
        ReviewCandidate,
        ReviewEvent,
        ReviewListing,
    )

    project_root, head = _make_git_project(tmp_path / "review", _UNANNOTATED)
    project = _register(client, project_root)
    review_commit = "b" * 40
    calls = []

    class Manager:
        def __init__(self, repo):
            calls.append(("manager", repo.root.as_posix()))

        def list_candidates(self, *, base_branch):
            calls.append(("list", base_branch))
            return (
                ReviewListing(
                    branch="work/mina/power",
                    commit=review_commit,
                    base_branch=base_branch,
                    base_commit=head,
                    fork_commit=head,
                    changed_paths=("board.kicad_sch",),
                    commit_count=1,
                    ready=True,
                ),
            )

        def discover(self, *, branch, base_branch):
            calls.append(("discover", branch, base_branch))
            return ReviewCandidate(
                branch=branch,
                commit=review_commit,
                base_branch=base_branch,
                base_commit=head,
                changed_paths=("board.kicad_sch",),
            )

        def approve_fast_forward(self, candidate):
            calls.append(("approve", candidate.commit))
            return candidate.commit

        def request_changes(self, candidate, *, reviewer, message):
            calls.append(("request", candidate.commit, reviewer, message))
            return ReviewEvent(
                id="event-1",
                kind="changes_requested",
                branch=candidate.branch,
                commit=candidate.commit,
                base_branch=candidate.base_branch,
                base_commit=candidate.base_commit,
                reviewer=reviewer,
                message=message,
                created_at="2026-07-28T12:30:00Z",
            )

    monkeypatch.setattr("stockroom.api.routers.projects.ReviewManager", Manager)
    monkeypatch.setattr(
        "stockroom.api.routers.projects.build_review_evidence",
        lambda manager, rec, candidate: {
            "schema_version": 1,
            "project_id": rec.id,
            "project_name": rec.name,
            "eda": rec.eda,
            "branch": candidate.branch,
            "commit": candidate.commit,
            "base_branch": candidate.base_branch,
            "base_commit": candidate.base_commit,
            "source_digest": "s" * 64,
            "blockers": [],
            "reviewable": True,
            "native_validation": {
                "status": "pending",
                "detail": "Native checks are pending.",
            },
            "digest": "d" * 64,
        },
    )
    monkeypatch.setattr(
        "stockroom.api.routers.projects.run_review_native_validation",
        lambda manager, rec, candidate: {
            "schema_version": 1,
            "adapter": rec.eda,
            "status": "passed",
            "runtime": {"name": "KiCad", "version": "9.0.4"},
            "checks": [],
            "summary": {"checked": 0, "errors": 0, "warnings": 0},
            "detail": "Native checks passed.",
            "project_id": rec.id,
            "branch": candidate.branch,
            "commit": candidate.commit,
            "base_branch": candidate.base_branch,
            "base_commit": candidate.base_commit,
            "source_digest": "s" * 64,
            "digest": "v" * 64,
        },
    )
    project_id = project["id"]

    listed = client.get(f"/api/projects/{project_id}/reviews")
    assert listed.status_code == 200, listed.text
    assert listed.json()["candidates"][0]["commit"] == review_commit
    assert listed.json()["candidates"][0]["changed_paths"] == ["board.kicad_sch"]
    assert listed.json()["candidates"][0]["events"] == []

    requested = client.post(
        f"/api/projects/{project_id}/reviews/request-changes",
        json={
            "branch": "work/mina/power",
            "commit": review_commit,
            "base_branch": "main",
            "base_commit": head,
            "reviewer": "Sadad",
            "message": "Verify the power-stage clearance.",
        },
    )
    assert requested.status_code == 200, requested.text
    assert requested.json()["event"]["kind"] == "changes_requested"
    assert requested.json()["event"]["commit"] == review_commit
    assert calls[-2:] == [
        ("discover", "work/mina/power", "main"),
        (
            "request",
            review_commit,
            "Sadad",
            "Verify the power-stage clearance.",
        ),
    ]

    validated = client.post(
        f"/api/projects/{project_id}/reviews/validate",
        json={
            "branch": "work/mina/power",
            "commit": review_commit,
            "base_branch": "main",
            "base_commit": head,
        },
    )
    assert validated.status_code == 200, validated.text
    assert validated.json()["status"] == "passed"

    evidence = client.post(
        f"/api/projects/{project_id}/reviews/evidence",
        json={
            "branch": "work/mina/power",
            "commit": review_commit,
            "base_branch": "main",
            "base_commit": head,
        },
    )
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["reviewable"] is True
    assert evidence.json()["native_validation"]["status"] == "passed"
    assert len(evidence.json()["digest"]) == 64
    assert calls[-1] == ("discover", "work/mina/power", "main")

    approved = client.post(
        f"/api/projects/{project_id}/reviews/approve",
        json={
            "branch": "work/mina/power",
            "commit": review_commit,
            "base_branch": "main",
            "base_commit": head,
        },
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["integrated_commit"] == review_commit
    assert len(approved.json()["evidence_digest"]) == 64
    assert calls[-2:] == [("discover", "work/mina/power", "main"), ("approve", review_commit)]


def test_review_approval_refuses_an_exact_commit_with_evidence_blockers(
    client,
    tmp_path,
    monkeypatch,
):
    from stockroom.projects.collaboration import ReviewCandidate

    project_root, head = _make_git_project(tmp_path / "blocked-evidence", _UNANNOTATED)
    project = _register(client, project_root)
    review_commit = "b" * 40
    approved = []

    class Manager:
        def __init__(self, repo):
            pass

        def discover(self, *, branch, base_branch):
            return ReviewCandidate(
                branch=branch,
                commit=review_commit,
                base_branch=base_branch,
                base_commit=head,
                changed_paths=("board.kicad_sch",),
            )

        def approve_fast_forward(self, candidate):
            approved.append(candidate.commit)
            return candidate.commit

    monkeypatch.setattr("stockroom.api.routers.projects.ReviewManager", Manager)
    monkeypatch.setattr(
        "stockroom.api.routers.projects.build_review_evidence",
        lambda manager, rec, candidate: {
            "schema_version": 1,
            "project_id": rec.id,
            "project_name": rec.name,
            "eda": rec.eda,
            "branch": candidate.branch,
            "commit": candidate.commit,
            "base_branch": candidate.base_branch,
            "base_commit": candidate.base_commit,
            "source_digest": "s" * 64,
            "blockers": [
                {
                    "kind": "missing_identity",
                    "path": "board.kicad_sch",
                    "detail": "R1 has no MPN.",
                }
            ],
            "reviewable": False,
            "native_validation": {
                "status": "pending",
                "detail": "Native checks are pending.",
            },
            "digest": "d" * 64,
        },
    )

    response = client.post(
        f"/api/projects/{project['id']}/reviews/approve",
        json={
            "branch": "work/mina/power",
            "commit": review_commit,
            "base_branch": "main",
            "base_commit": head,
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "review_evidence_blocked"
    assert approved == []


def test_review_listing_uses_the_active_sessions_base_branch(
    client,
    app_ctx,
    tmp_path,
    monkeypatch,
):
    from stockroom.projects.collaboration import WorkSession

    project_root, head = _make_git_project(tmp_path / "session-reviews", _UNANNOTATED)
    project = _register(client, project_root)
    session = WorkSession(
        id="session-a",
        owner="Mina",
        branch="work/mina/power",
        base_branch="release",
        base_commit=head,
        documents=("board.kicad_sch",),
        locks=(),
        started_at="2026-07-28T12:00:00Z",
        shared_commit="b" * 40,
    )
    app_ctx.work_session_store.save(project["id"], session)
    seen = []

    class Manager:
        def __init__(self, repo):
            pass

        def list_candidates(self, *, base_branch):
            seen.append(base_branch)
            return ()

    monkeypatch.setattr("stockroom.api.routers.projects.ReviewManager", Manager)
    response = client.get(f"/api/projects/{project['id']}/reviews")

    assert response.status_code == 200, response.text
    assert response.json() == {"base_branch": "release", "candidates": []}
    assert seen == ["release"]


def test_review_listing_turns_a_missing_saved_remote_base_into_recovery_state(
    client,
    app_ctx,
    tmp_path,
    monkeypatch,
):
    from stockroom.projects.collaboration import CollaborationError, WorkSession

    project_root, head = _make_git_project(tmp_path / "stale-session-reviews", _UNANNOTATED)
    project = _register(client, project_root)
    app_ctx.work_session_store.save(
        project["id"],
        WorkSession(
            id="session-stale",
            owner="Mina",
            branch="work/mina/old",
            base_branch="deleted-release",
            base_commit=head,
            documents=("board.kicad_sch",),
            locks=(),
            started_at="2026-07-28T12:00:00Z",
            shared_commit="",
        ),
    )

    class Manager:
        def __init__(self, repo):
            pass

        def list_candidates(self, *, base_branch):
            raise CollaborationError(
                "base_missing",
                f"remote ref is unavailable: refs/remotes/origin/{base_branch}",
            )

    monkeypatch.setattr("stockroom.api.routers.projects.ReviewManager", Manager)
    response = client.get(f"/api/projects/{project['id']}/reviews")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "base_branch": "deleted-release",
        "candidates": [],
        "blocked_reason": (
            "The saved work session's shared branch is no longer available. "
            "Your active work remains preserved. Restore that branch, or share and "
            "finish the current session before starting another."
        ),
    }
    assert "refs/remotes" not in response.text


def test_review_approval_refuses_a_commit_other_than_the_one_displayed(
    client, tmp_path, monkeypatch
):
    from stockroom.projects.collaboration import ReviewCandidate

    project_root, head = _make_git_project(tmp_path / "changed-review", _UNANNOTATED)
    project = _register(client, project_root)

    class Manager:
        def __init__(self, repo):
            pass

        def discover(self, *, branch, base_branch):
            return ReviewCandidate(
                branch=branch,
                commit="c" * 40,
                base_branch=base_branch,
                base_commit=head,
                changed_paths=("board.kicad_sch",),
            )

    monkeypatch.setattr("stockroom.api.routers.projects.ReviewManager", Manager)
    response = client.post(
        f"/api/projects/{project['id']}/reviews/approve",
        json={
            "branch": "work/mina/power",
            "commit": "b" * 40,
            "base_branch": "main",
            "base_commit": head,
        },
    )
    assert response.status_code == 409
    assert response.json()["code"] == "review_changed"


def test_finish_work_session_releases_claims_only_after_integration(
    client, app_ctx, tmp_path, monkeypatch
):
    from stockroom.projects.collaboration import WorkSession

    project_root, head = _make_git_project(tmp_path / "finish-session", _UNANNOTATED)
    project = _register(client, project_root)
    session = WorkSession(
        id="session-a",
        owner="Sadad",
        branch="work/sadad/power",
        base_branch="main",
        base_commit=head,
        documents=("board.kicad_sch",),
        locks=(),
        started_at="2026-07-28T12:00:00Z",
        shared_commit="b" * 40,
    )
    app_ctx.work_session_store.save(project["id"], session)
    calls = []

    class Manager:
        def __init__(self, repo, locks):
            calls.append(("manager", repo.root.as_posix(), type(locks).__name__))

        def finish_after_remote_integration(self, current):
            calls.append(("finish", current.id))
            return "c" * 40

    monkeypatch.setattr("stockroom.api.routers.projects.WorkSessionManager", Manager)
    response = client.post(
        f"/api/projects/{project['id']}/work-sessions/session-a/finish"
    )

    assert response.status_code == 200, response.text
    assert response.json()["integrated_commit"] == "c" * 40
    assert response.json()["collaboration"]["session"] is None
    assert app_ctx.work_session_store.active(project["id"]) is None
    assert calls[-1] == ("finish", "session-a")


def test_resume_work_session_persists_recovered_claim_identities(
    client, app_ctx, tmp_path, monkeypatch
):
    from dataclasses import replace

    from stockroom.projects.collaboration import WorkSession
    from stockroom.vcs.locks import DocumentLock
    from stockroom.vcs.repo import GitRepo

    project_root, head = _make_git_project(tmp_path / "resume-session", _UNANNOTATED)
    project = _register(client, project_root)
    session = WorkSession(
        id="session-a",
        owner="Sadad",
        branch="work/sadad/power",
        base_branch="main",
        base_commit=head,
        documents=("board.kicad_sch",),
        locks=(DocumentLock("old-lock", "board.kicad_sch", "Sadad"),),
        started_at="2026-07-28T12:00:00Z",
    )
    assert GitRepo(project_root)._run("branch", session.branch, head).returncode == 0
    app_ctx.work_session_store.save(project["id"], session)
    calls = []
    recovered = client.get(f"/api/projects/{project['id']}/collaboration")
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["recovery"]["state"] == "resume_available"
    assert recovered.json()["recovery"]["claims"]["unknown"] == ["board.kicad_sch"]

    class Manager:
        def __init__(self, repo, locks):
            self.repo = repo
            calls.append(("manager", repo.root.as_posix(), type(locks).__name__))

        def resume(self, current):
            calls.append(("resume", current.id))
            assert self.repo._run("switch", current.branch).returncode == 0
            return replace(
                current,
                locks=(DocumentLock("recovered-lock", "board.kicad_sch", "Sadad"),),
            )

    monkeypatch.setattr("stockroom.api.routers.projects.WorkSessionManager", Manager)
    response = client.post(
        f"/api/projects/{project['id']}/work-sessions/session-a/resume"
    )

    assert response.status_code == 200, response.text
    assert response.json()["session"]["locks"][0]["id"] == "recovered-lock"
    assert response.json()["recovery"]["state"] == "healthy"
    assert response.json()["recovery"]["claims"]["held"] == ["board.kicad_sch"]
    assert app_ctx.work_session_store.active(project["id"]).locks[0].id == "recovered-lock"
    assert calls[-1] == ("resume", "session-a")


def test_collaboration_status_explains_when_git_is_not_linked(client, tmp_path):
    project = _register(client, _make_project(tmp_path / "local-only"))
    response = client.get(f"/api/projects/{project['id']}/collaboration")
    assert response.status_code == 200
    assert response.json() == {
        "repository": None,
        "session": None,
        "recovery": None,
        "blocked_reason": "Link this project to a Git repository to collaborate.",
    }


def test_open_document_route_uses_the_same_adapter_reported_id_for_both_edas(
    client,
    monkeypatch,
    tmp_path,
):
    kicad_root = _make_project(tmp_path / "open" / "kicad")
    (kicad_root / "board.kicad_pcb").write_text("(kicad_pcb)\n", encoding="utf-8")
    altium_root = _make_altium_api_project(tmp_path / "open" / "altium")
    (altium_root / "Amp.PrjPcb").write_text(
        "[Design]\nVersion=1.0\n\n"
        "[Document1]\nDocumentPath=Amp.SchDoc\n\n"
        "[Document2]\nDocumentPath=Amp.PcbDoc\n",
        encoding="utf-8",
    )
    (altium_root / "Amp.PcbDoc").write_bytes(b"Stockroom route fixture")
    projects = [
        _register(client, kicad_root),
        _register(client, altium_root),
    ]
    calls = []

    def open_document(root, document_id, documents):
        document = next(row for row in documents if row.document_id == document_id)
        calls.append((root, document.document_id, document.path))
        return document

    monkeypatch.setattr(
        "stockroom.api.routers.projects.open_project_document",
        open_document,
    )

    for project in projects:
        workspace = client.get(f"/api/projects/{project['id']}/workspace").json()
        document = next(row for row in workspace["documents"] if row["kind"] == "pcb")
        response = client.post(
            f"/api/projects/{project['id']}/documents/"
            f"{quote(document['document_id'], safe='')}/open"
        )
        assert response.status_code == 200, response.text
        assert response.json() == {
            "opened": True,
            "document_id": document["document_id"],
            "path": document["path"],
        }

    assert [path for _root, _document_id, path in calls] == [
        "board.kicad_pcb",
        "Amp.PcbDoc",
    ]


def test_connect_project_remote_adds_origin_and_runs_one_safe_sync(
    client,
    monkeypatch,
    tmp_path,
):
    from stockroom.vcs.repo import GitRepo
    from stockroom.vcs.sync import SyncResult

    project_root, _head = _make_git_project(
        tmp_path / "connect-remote",
        _UNANNOTATED,
    )
    project = _register(client, project_root)
    calls = []
    remote = "https://github.com/team/power-board.git"
    unsafe = client.post(
        f"/api/projects/{project['id']}/collaboration/remote",
        json={"url": "https://token@github.com/team/power-board.git"},
    )
    assert unsafe.status_code == 422, unsafe.text
    assert GitRepo(project_root).remote_url("origin") == ""

    class SafeSync:
        def __init__(self, repo):
            calls.append(("init", repo.root))

        def sync(self):
            calls.append(("sync",))
            return SyncResult(state="pushed", pushed=True)

    monkeypatch.setattr("stockroom.api.routers.projects.SyncEngine", SafeSync)
    response = client.post(
        f"/api/projects/{project['id']}/collaboration/remote",
        json={"url": remote},
    )

    assert response.status_code == 200, response.text
    assert GitRepo(project_root).remote_url("origin") == remote
    assert response.json()["collaboration"]["repository"]["remote"] == remote
    assert response.json()["collaboration"]["repository"]["has_remote"] is True
    assert response.json()["sync"] == {
        "state": "pushed",
        "pulled": False,
        "pushed": True,
        "detail": "",
        "converged": False,
    }
    assert calls == [("init", project_root), ("sync",)]


def test_connect_project_remote_accepts_the_secure_collaboration_url_set():
    from stockroom.api.schemas import ConnectProjectRemoteBody

    accepted = [
        "https://github.com/team/power-board.git",
        "ssh://git@github.com/team/power-board.git",
        "git@github.com:team/power-board.git",
        "git@forge:team/power-board.git",
    ]

    assert [ConnectProjectRemoteBody(url=url).url for url in accepted] == accepted


def test_connect_project_remote_rejects_unsafe_or_non_shareable_urls():
    from pydantic import ValidationError

    from stockroom.api.schemas import ConnectProjectRemoteBody

    rejected = [
        "",
        "-uhttps://github.com/team/project.git",
        "http://github.com/team/project.git",
        "git://github.com/team/project.git",
        "ftp://github.com/team/project.git",
        "file:///C:/work/project",
        "C:\\work\\project",
        "../project",
        "ext::sh -c whoami",
        "https://token@github.com/team/project.git",
        "ssh://git:token@github.com/team/project.git",
        "https://github.com/team/project.git?token=secret",
        "https://github.com/team/project.git#fragment",
        "https://github.com/team/\nproject.git",
        "git@github.com:",
        "git@github..com:team/project.git",
        "https://-github.com/team/project.git",
        "https://git_hub.com/team/project.git",
    ]

    for remote in rejected:
        with pytest.raises(ValidationError):
            ConnectProjectRemoteBody(url=remote)


def test_connect_project_remote_never_replaces_existing_origin(client, tmp_path):
    from stockroom.vcs.repo import GitRepo

    project_root, _head = _make_git_project(
        tmp_path / "existing-origin",
        _UNANNOTATED,
    )
    project = _register(client, project_root)
    repo = GitRepo(project_root)
    original = "https://github.com/team/original.git"
    repo.add_remote("origin", original)

    response = client.post(
        f"/api/projects/{project['id']}/collaboration/remote",
        json={"url": "https://github.com/team/replacement.git"},
    )

    assert response.status_code == 400, response.text
    assert repo.remote_url("origin") == original


# ---- get --------------------------------------------------------------------


def test_get_returns_the_full_record(client, tmp_path):
    proj = _make_project(tmp_path / "ext" / "board")
    rec = _register(client, proj)
    got = client.get(f"/api/projects/{rec['id']}")
    assert got.status_code == 200
    assert got.json()["id"] == rec["id"]
    assert got.json()["root"] == proj.as_posix()


def test_get_an_unknown_project_is_a_404(client):
    assert client.get("/api/projects/nope").status_code == 404


# ---- delete -----------------------------------------------------------------


def test_delete_returns_204_and_removes_the_registration(client, tmp_path):
    proj = _make_project(tmp_path / "ext" / "board")
    rec = _register(client, proj)
    r = client.delete(f"/api/projects/{rec['id']}")
    assert r.status_code == 204
    assert r.content == b""
    # the rebuilt index no longer lists it
    assert client.get("/api/projects").json() == []
    assert client.get(f"/api/projects/{rec['id']}").status_code == 404


def test_delete_an_unknown_project_is_a_404(client):
    assert client.delete("/api/projects/nope").status_code == 404


def test_delete_preserves_a_project_with_an_active_work_session(
    client, app_ctx, tmp_path
):
    from stockroom.projects.collaboration import WorkSession

    rec = _register(client, _make_project(tmp_path / "claimed"))
    app_ctx.work_session_store.save(
        rec["id"],
        WorkSession(
            id="session-a",
            owner="Sadad",
            branch="work/sadad/board",
            base_branch="main",
            base_commit="a" * 40,
            documents=("board.kicad_sch",),
            locks=(),
            started_at="2026-07-28T12:00:00Z",
        ),
    )

    response = client.delete(f"/api/projects/{rec['id']}")
    assert response.status_code == 409
    assert response.json()["code"] == "session_active"
    assert client.get(f"/api/projects/{rec['id']}").status_code == 200


# ---- audit ------------------------------------------------------------------


def test_audit_reports_findings_and_markdown(client, tmp_path):
    proj = _make_project(tmp_path / "ext" / "board")
    rec = _register(client, proj)
    r = client.get(f"/api/projects/{rec['id']}/audit")
    assert r.status_code == 200
    au = r.json()
    assert au["project"] == "board"  # named for the record
    assert au["components"] == 1
    kinds = {(f["ref"], f["kind"]) for f in au["findings"]}
    assert ("R?", "unannotated") in kinds
    assert ("R?", "no_footprint") in kinds
    assert au["markdown"].startswith("# Project Health")
    assert "R?" in au["markdown"]


def test_audit_an_unknown_project_is_a_404(client):
    assert client.get("/api/projects/nope/audit").status_code == 404


# ---- buildability (M7g) -----------------------------------------------------

_BUILD_CHECKS_OK = {
    "ran_at": "2026-07-14T00:00:00Z",
    "summary": {"ok": True, "errors": 0, "warnings": 0, "checked": 1},
}
_BUILD_BOM_OK = {
    "ran_at": "2026-07-14T00:00:00Z",
    "boards": 1,
    "priced": True,
    "lines": [
        {
            "mpn": "X",
            "qty": 1,
            "stock": 100,
            "unit_price": 0.1,
            "extended": 0.1,
            "lifecycle": "Active",
        }
    ],
    "summary": {"unpriced_lines": 0},
}


def test_buildability_cold_caches_are_honest_blockers(client, tmp_path):
    proj = _make_project(tmp_path / "ext" / "board")  # R? with an empty footprint
    rec = _register(client, proj)
    v = client.get(f"/api/projects/{rec['id']}/buildability").json()
    assert v["ready"] is False
    kinds = {b["kind"] for b in v["blockers"]}
    assert {"unannotated", "missing_footprint", "checks_not_run", "bom_not_built"} <= kinds
    # a cold cache is surfaced as its honest state, never a fabricated pass
    assert v["signals"]["checks"]["state"] == "not_run"
    assert v["signals"]["bom"]["state"] == "not_built"


def test_buildability_reads_the_injected_caches(client, app_ctx, tmp_path):
    proj = _make_project(tmp_path / "ext" / "board")
    rec = _register(client, proj)
    app_ctx.checks_cache[rec["id"]] = _BUILD_CHECKS_OK
    app_ctx.bom_cache[rec["id"]] = _BUILD_BOM_OK
    v = client.get(f"/api/projects/{rec['id']}/buildability").json()
    assert v["signals"]["checks"]["state"] == "pass"  # the router injected the cached run
    assert v["signals"]["bom"]["state"] == "pass"
    assert v["ready"] is False  # still blocked on the unannotated/no-footprint sheet


def test_buildability_unknown_id_is_404(client):
    assert client.get("/api/projects/nope/buildability").status_code == 404


# A 2-pin symbol plus a footprint the active profile resolves to 3 pads: the pin/pad
# mismatch only surfaces if the router passes the profile's footprint dir to the audit.
_MISMATCH_SHEET = (
    "  (lib_symbols\n"
    '    (symbol "Device:R"\n'
    '      (symbol "R_0_1" (pin passive line (at 0 0 0)) (pin passive line (at 0 0 0)))\n'
    "    )\n"
    "  )\n"
    "  (symbol\n"
    '    (lib_id "Device:R")\n'
    '    (property "Reference" "R1" (at 0 0 0))\n'
    '    (property "Value" "10k" (at 0 0 0))\n'
    '    (property "Footprint" "SR-ICs:TESTFP" (at 0 0 0))\n'
    '    (property "MPN" "RC0402" (at 0 0 0))\n'
    "  )\n"
)


def test_audit_uses_the_active_profile_footprints_for_the_pin_pad_check(client, app_ctx, tmp_path):
    # Seed a 3-pad footprint into the active profile; the 2-pin symbol references it,
    # so a pin_pad_mismatch is produced ONLY because the router wires the profile's
    # footprint dir into the audit. Load-bearing for that wiring (drop it -> red).
    fp_dir = app_ctx.profile.library.footprint_lib_path("ICs")
    fp_dir.mkdir(parents=True, exist_ok=True)
    (fp_dir / "TESTFP.kicad_mod").write_text(
        '(footprint "TESTFP" (pad "1" smd rect) (pad "2" smd rect) (pad "3" smd rect))',
        encoding="utf-8",
    )
    rec = _register(client, _make_project(tmp_path / "mismatch", _MISMATCH_SHEET))
    au = client.get(f"/api/projects/{rec['id']}/audit").json()
    kinds = {(f["ref"], f["kind"]) for f in au["findings"]}
    assert ("R1", "pin_pad_mismatch") in kinds
    assert au["checked_footprints"] >= 1


# ---- checks (ERC + DRC, M7b) ------------------------------------------------


def _add_board(proj):
    """Give a fixture project a .kicad_pcb so DRC has a board to run on."""
    (proj / "board.kicad_pcb").write_text("(kicad_pcb)\n", encoding="utf-8")
    return proj


def test_run_checks_without_kicad_cli_is_an_honest_502(client, app_ctx, tmp_path):
    # cli-absent must be an honest 502, never a fabricated clean pass (Decision 8).
    proj = _make_project(tmp_path / "ext" / "board")
    rec = _register(client, proj)
    app_ctx.cli.binary = None
    r = client.post(f"/api/projects/{rec['id']}/checks")
    assert r.status_code == 502
    assert "kicad-cli" in r.json()["detail"].lower()


def test_run_checks_for_an_unknown_project_is_a_404_before_any_cli_check(client, app_ctx):
    # 404 is resolved before the cli gate, so an unknown id 404s even with no cli.
    app_ctx.cli.binary = None
    assert client.post("/api/projects/nope/checks").status_code == 404


def test_run_checks_returns_a_job_and_caches_the_result(client, app_ctx, tmp_path, monkeypatch):
    from stockroom.projects import checks as checks_mod

    proj = _add_board(_make_project(tmp_path / "ext" / "board"))
    rec = _register(client, proj)
    app_ctx.cli.binary = "/fake/kicad-cli"  # deterministic: never a real subprocess

    def fake_erc(path, cli):
        return {
            "ok": True,
            "findings": [
                {
                    "severity": "warning",
                    "rule": "unconnected",
                    "message": "pin floating",
                    "where": "U1",
                }
            ],
            "summary": checks_mod.summarize([{"severity": "warning", "rule": "unconnected"}]),
            "error": "",
        }

    def fake_drc(path, cli):
        return {
            "ok": True,
            "findings": [
                {"severity": "error", "rule": "clearance", "message": "too close", "where": ""}
            ],
            "summary": checks_mod.summarize([{"severity": "error", "rule": "clearance"}]),
            "error": "",
        }

    monkeypatch.setattr(checks_mod, "run_erc", fake_erc)
    monkeypatch.setattr(checks_mod, "run_drc", fake_drc)

    r = client.post(f"/api/projects/{rec['id']}/checks")
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    result = None
    with client.stream("GET", f"/api/jobs/{job_id}/events") as s:
        for line in s.iter_lines():
            if line.startswith("data:") and '"result"' in line:
                import json as _j

                result = _j.loads(line[5:].strip())["result"]
    assert result is not None
    assert result["summary"] == {"ok": True, "errors": 1, "warnings": 1, "total": 2, "checked": 2}
    assert result["erc"]["sheet"] == "board.kicad_sch"
    assert result["drc"][0]["board"] == "board.kicad_pcb"

    # cached: GET serves the same result without re-running.
    got = client.get(f"/api/projects/{rec['id']}/checks")
    assert got.status_code == 200
    assert got.json()["summary"] == result["summary"]


def test_get_checks_before_a_run_is_an_honest_not_run_shape(client, tmp_path):
    rec = _register(client, _make_project(tmp_path / "ext" / "board"))
    r = client.get(f"/api/projects/{rec['id']}/checks")
    assert r.status_code == 200
    body = r.json()
    assert body["ran_at"] is None and body["summary"] is None and body["erc"] is None


def test_get_checks_for_an_unknown_project_is_a_404(client):
    assert client.get("/api/projects/nope/checks").status_code == 404


# ---- bom (M7c) --------------------------------------------------------------

# a sheet with one MPN'd IC and one bare passive: the IC prices, the passive stays
# unpriced (no purchasable part number), so a build is a "partial" cost verdict.
_IC_AND_PASSIVE = (
    "  (symbol\n"
    '    (lib_id "Device:U")\n'
    '    (property "Reference" "U1" (at 0 0 0))\n'
    '    (property "Value" "TPS2121" (at 0 0 0))\n'
    '    (property "MPN" "TPS2121RUXR" (at 0 0 0))\n'
    '    (property "MANUFACTURER" "TI" (at 0 0 0))\n'
    "  )\n"
    "  (symbol\n"
    '    (lib_id "Device:R")\n'
    '    (property "Reference" "R1" (at 0 0 0))\n'
    '    (property "Value" "10k" (at 0 0 0))\n'
    '    (property "Footprint" "Resistor_SMD:R_0402" (at 0 0 0))\n'
    "  )\n"
)


class _FakePipeline:
    """A stand-in for the enrich pipeline so BOM pricing never touches the network."""

    def enrich(self, mpn, category, want=None):
        from stockroom.enrich.schema import EnrichmentResult, PriceBreak, Sourced

        r = EnrichmentResult()
        if mpn == "TPS2121RUXR":
            r.mpn = Sourced(mpn, "mouser", "high")
            r.stock = Sourced(5000, "mouser", "high")
            r.price_breaks = [PriceBreak(qty=1, price=1.25)]
        return r


def _stream_job_result(client, job_id):
    import json as _j

    result = None
    with client.stream("GET", f"/api/jobs/{job_id}/events") as s:
        for line in s.iter_lines():
            if line.startswith("data:") and '"result"' in line:
                result = _j.loads(line[5:].strip())["result"]
    return result


def test_run_bom_prices_and_caches_the_result(client, app_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr("stockroom.api.routers.enrich._make_pipeline", lambda ctx: _FakePipeline())
    proj = _make_project(tmp_path / "ext" / "board", _IC_AND_PASSIVE)
    rec = _register(client, proj)

    r = client.post(f"/api/projects/{rec['id']}/bom")
    assert r.status_code == 200
    result = _stream_job_result(client, r.json()["job_id"])
    assert result is not None and result["priced"] is True
    by_mpn = {ln["mpn"]: ln for ln in result["lines"]}
    assert by_mpn["TPS2121RUXR"]["unit_price"] == 1.25
    assert by_mpn["TPS2121RUXR"]["source"] == "Mouser"
    assert result["summary"]["total_cost"] == 1.25
    assert result["summary"]["priced_lines"] == 1 and result["summary"]["unpriced_lines"] == 1
    assert result["summary"]["state"] == "partial"
    assert result["by_source"]["sources"]["Mouser"]["total_cost"] == 1.25

    # cached: GET serves the same build without rebuilding.
    got = client.get(f"/api/projects/{rec['id']}/bom")
    assert got.status_code == 200
    assert got.json()["summary"]["total_cost"] == 1.25


def test_run_bom_does_not_require_kicad_cli(client, app_ctx, tmp_path):
    # The BOM is built offline from the schematic, so a missing kicad-cli is NOT a 502:
    # grouping still works, and a passive-only project needs no pricing lookup at all.
    app_ctx.cli.binary = None
    rec = _register(client, _make_project(tmp_path / "ext" / "board"))
    r = client.post(f"/api/projects/{rec['id']}/bom")
    assert r.status_code == 200
    result = _stream_job_result(client, r.json()["job_id"])
    assert result is not None and result["line_count"] == 1
    # priced was attempted but the lone passive has no MPN -> honestly unpriced.
    assert result["summary"]["state"] == "unpriced"


def test_run_bom_for_an_unknown_project_is_a_404(client):
    assert client.post("/api/projects/nope/bom").status_code == 404


def test_get_bom_before_a_build_is_an_honest_not_built_shape(client, tmp_path):
    rec = _register(client, _make_project(tmp_path / "ext" / "board"))
    body = client.get(f"/api/projects/{rec['id']}/bom").json()
    assert body["ran_at"] is None and body["summary"] is None and body["lines"] == []


def test_get_bom_for_an_unknown_project_is_a_404(client):
    assert client.get("/api/projects/nope/bom").status_code == 404


def test_reprice_bom_recosts_the_cached_build_for_a_new_qty_and_tax(client, app_ctx, tmp_path):
    rec = _register(client, _make_project(tmp_path / "ext" / "board"))
    app_ctx.bom_cache[rec["id"]] = {
        "project": rec["name"],
        "ran_at": "t",
        "boards": 1,
        "priced": True,
        "line_count": 1,
        "component_count": 1,
        "lines": [{"mpn": "X", "qty": 2, "price_breaks": [{"qty": 100, "price": 0.05}]}],
        "summary": {"priced": True},
        "by_source": None,
        "cost_at_qty": None,
    }
    body = client.post(
        f"/api/projects/{rec['id']}/bom/reprice", json={"boards": 10, "tax_rate": 8.25}
    ).json()
    assert body["boards"] == 10 and body["tax_rate"] == 8.25
    line = body["lines"][0]
    assert line["final_qty"] == 100 and line["final_extended"] == 5.0
    assert body["build"]["grand_total"] == round(5.0 + 5.0 * 8.25 / 100, 2)
    # re-cached so a subsequent GET / procurement sees the same numbers
    assert app_ctx.bom_cache[rec["id"]]["boards"] == 10


def test_reprice_bom_before_a_build_is_an_honest_not_built_shape(client, tmp_path):
    rec = _register(client, _make_project(tmp_path / "ext" / "board"))
    body = client.post(f"/api/projects/{rec['id']}/bom/reprice", json={"boards": 5}).json()
    assert body["ran_at"] is None and body["lines"] == [] and body["build"] is None


def test_reprice_bom_for_an_unknown_project_is_a_404(client):
    assert client.post("/api/projects/nope/bom/reprice", json={}).status_code == 404


def test_delete_evicts_the_cached_bom(client, app_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr("stockroom.api.routers.enrich._make_pipeline", lambda ctx: _FakePipeline())
    proj = _make_project(tmp_path / "ext" / "board", _IC_AND_PASSIVE)
    rec = _register(client, proj)
    _stream_job_result(client, client.post(f"/api/projects/{rec['id']}/bom").json()["job_id"])
    assert rec["id"] in app_ctx.bom_cache
    client.delete(f"/api/projects/{rec['id']}")
    assert rec["id"] not in app_ctx.bom_cache


def test_bom_job_does_not_resurrect_cache_for_a_deleted_project(
    client, app_ctx, tmp_path, monkeypatch
):
    # A DELETE landing while a BOM job runs evicts the cache; the job's write-back must
    # NOT re-insert a stale entry for the now-gone id (project ids are reusable slugs).
    monkeypatch.setattr("stockroom.api.routers.enrich._make_pipeline", lambda ctx: _FakePipeline())
    proj = _make_project(tmp_path / "ext" / "board", _IC_AND_PASSIVE)
    rec = _register(client, proj)
    real_bom = app_ctx.project_ops.bom

    def deleting_bom(pid, **kw):
        result = real_bom(pid, **kw)
        # simulate a concurrent DELETE landing mid-job (evicts the cache before write-back)
        app_ctx.project_ops.delete(pid)
        app_ctx.bom_cache.pop(pid, None)
        return result

    monkeypatch.setattr(app_ctx.project_ops, "bom", deleting_bom)
    _stream_job_result(client, client.post(f"/api/projects/{rec['id']}/bom").json()["job_id"])
    assert rec["id"] not in app_ctx.bom_cache  # the existence re-check prevented resurrection


# ---- procurement (M7d) ------------------------------------------------------


class _ProcPipeline:
    """A stand-in enrich pipeline that prices the IC as a short-stock, NRND, long-lead
    part so the procurement roll-ups have a real risk + lead to report."""

    def enrich(self, mpn, category, want=None):
        from stockroom.enrich.schema import EnrichmentResult, PriceBreak, Sourced

        r = EnrichmentResult()
        if mpn == "TPS2121RUXR":
            r.mpn = Sourced(mpn, "mouser", "high")
            r.stock = Sourced(0, "mouser", "high")  # no stock -> a real risk
            r.lifecycle = Sourced("NRND", "mouser", "high")
            r.lead_time = Sourced("18 Weeks", "mouser", "high")
            r.price_breaks = [PriceBreak(qty=1, price=1.25)]
        return r


def _build_bom(client, monkeypatch, tmp_path, pipeline_cls):
    monkeypatch.setattr("stockroom.api.routers.enrich._make_pipeline", lambda ctx: pipeline_cls())
    rec = _register(client, _make_project(tmp_path / "ext" / "board", _IC_AND_PASSIVE))
    _stream_job_result(client, client.post(f"/api/projects/{rec['id']}/bom").json()["job_id"])
    return rec


def test_export_csv_kinds_download_with_a_named_attachment(client, tmp_path, monkeypatch):
    rec = _build_bom(client, monkeypatch, tmp_path, _FakePipeline)
    for kind in ("csv", "priced", "cart", "jlcpcb"):
        r = client.get(f"/api/projects/{rec['id']}/bom/export", params={"kind": kind})
        assert r.status_code == 200, (kind, r.text)
        assert r.headers["content-type"].startswith("text/csv")
        assert "attachment" in r.headers["content-disposition"]
        assert ".csv" in r.headers["content-disposition"]
        assert r.text  # non-empty CSV body


def test_export_xlsx_kinds_are_valid_binary_workbooks(client, tmp_path, monkeypatch):
    import io
    import zipfile

    rec = _build_bom(client, monkeypatch, tmp_path, _FakePipeline)
    for kind in ("xlsx", "procurement"):
        r = client.get(f"/api/projects/{rec['id']}/bom/export", params={"kind": kind})
        assert r.status_code == 200, (kind, r.text)
        assert r.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert ".xlsx" in r.headers["content-disposition"]
        assert not zipfile.ZipFile(io.BytesIO(r.content)).testzip()  # a valid workbook


def test_export_an_unknown_kind_is_a_400(client, tmp_path, monkeypatch):
    rec = _build_bom(client, monkeypatch, tmp_path, _FakePipeline)
    assert (
        client.get(f"/api/projects/{rec['id']}/bom/export", params={"kind": "pdf"}).status_code
        == 400
    )


def test_export_before_a_build_is_an_honest_400(client, tmp_path):
    rec = _register(client, _make_project(tmp_path / "ext" / "board", _IC_AND_PASSIVE))
    r = client.get(f"/api/projects/{rec['id']}/bom/export", params={"kind": "csv"})
    assert r.status_code == 400  # nothing built yet to export


def test_export_for_an_unknown_project_is_a_404(client):
    assert client.get("/api/projects/nope/bom/export", params={"kind": "csv"}).status_code == 404


# ---- revision diff (M7d) ----------------------------------------------------

import subprocess


def _make_git_project(dir_path, sheet_body):
    """A registered-able project dir that is its OWN git repo, with one commit."""
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "board.kicad_pro").write_text("{}", encoding="utf-8")
    (dir_path / "board.kicad_sch").write_text("(kicad_sch\n" + sheet_body + ")\n", encoding="utf-8")
    for args in (
        ["init", "-b", "main"],
        ["config", "user.email", "t@t"],
        ["config", "user.name", "t"],
        ["add", "."],
        ["commit", "-m", "rev A"],
    ):
        subprocess.run(["git", "-C", str(dir_path), *args], check=True, capture_output=True)
    head = subprocess.run(
        ["git", "-C", str(dir_path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return dir_path, head


_TWO_RES = (
    '  (symbol (lib_id "Device:R") (property "Reference" "R1" (at 0 0 0))'
    ' (property "Value" "10k" (at 0 0 0)))\n'
    '  (symbol (lib_id "Device:R") (property "Reference" "R2" (at 0 0 0))'
    ' (property "Value" "10k" (at 0 0 0)))\n'
)


def test_revisions_lists_the_project_git_history(client, tmp_path):
    proj, rev_a = _make_git_project(tmp_path / "board", _TWO_RES)
    rec = _register(client, proj)
    body = client.get(f"/api/projects/{rec['id']}/revisions").json()
    assert body["under_git"] is True
    assert len(body["revisions"]) == 1
    assert body["revisions"][0]["sha"] == rev_a
    assert body["revisions"][0]["short"] == rev_a[:7]


def test_revisions_for_a_non_git_project_is_an_honest_empty(client, tmp_path):
    rec = _register(client, _make_project(tmp_path / "ext" / "board"))  # not a git repo
    body = client.get(f"/api/projects/{rec['id']}/revisions").json()
    assert body["under_git"] is False
    assert body["revisions"] == []


def test_bom_diff_reconstructs_rev_a_against_the_working_tree(client, tmp_path):
    proj, rev_a = _make_git_project(tmp_path / "board", _TWO_RES)
    rec = _register(client, proj)
    # add a third 10k in the working tree after registration
    (proj / "board.kicad_sch").write_text(
        "(kicad_sch\n"
        + _TWO_RES
        + '  (symbol (lib_id "Device:R") (property "Reference" "R3" (at 0 0 0))'
        ' (property "Value" "10k" (at 0 0 0)))\n)\n',
        encoding="utf-8",
    )
    body = client.get(f"/api/projects/{rec['id']}/bom/diff", params={"a": rev_a}).json()
    assert body["rev_a"] == rev_a
    assert body["rev_b"] == "current"
    changed = {c["value"]: c for c in body["changed"]}
    assert changed["10k"]["from_qty"] == 2 and changed["10k"]["to_qty"] == 3


def test_bom_diff_cost_delta_comes_from_the_cached_priced_build(client, tmp_path, monkeypatch):
    # Locks the router wire that feeds the cached PRICED build as rev B (current_rows) into
    # the diff: without it the working tree is reconstructed unpriced and the cost delta is 0.
    monkeypatch.setattr("stockroom.api.routers.enrich._make_pipeline", lambda ctx: _FakePipeline())
    # rev A holds only the passive (with the current footprint so it does not itself diff).
    rev_a_body = (
        '  (symbol (lib_id "Device:R") (property "Reference" "R1" (at 0 0 0))'
        ' (property "Value" "10k" (at 0 0 0)) (property "Footprint" "Resistor_SMD:R_0402" (at 0 0 0)))\n'
    )
    proj, rev_a = _make_git_project(tmp_path / "board", rev_a_body)
    rec = _register(client, proj)
    # working tree adds the priced IC (TPS2121RUXR, $1.25 from the fake pipeline)
    (proj / "board.kicad_sch").write_text(
        "(kicad_sch\n" + _IC_AND_PASSIVE + ")\n", encoding="utf-8"
    )
    _stream_job_result(client, client.post(f"/api/projects/{rec['id']}/bom").json()["job_id"])

    body = client.get(f"/api/projects/{rec['id']}/bom/diff", params={"a": rev_a}).json()
    assert any(x["mpn"] == "TPS2121RUXR" for x in body["added"])
    assert body["cost"]["priced"] is True  # the current build is priced -> delta is meaningful
    assert body["cost"]["added_cost"] == 1.25
    assert body["cost"]["delta"] == 1.25


def test_bom_diff_without_a_revision_is_a_400(client, tmp_path):
    proj, _rev = _make_git_project(tmp_path / "board", _TWO_RES)
    rec = _register(client, proj)
    assert client.get(f"/api/projects/{rec['id']}/bom/diff").status_code == 400


def test_bom_diff_for_a_non_git_project_is_a_400(client, tmp_path):
    rec = _register(client, _make_project(tmp_path / "ext" / "board"))
    r = client.get(f"/api/projects/{rec['id']}/bom/diff", params={"a": "HEAD"})
    assert r.status_code == 400


def test_revisions_and_diff_for_an_unknown_project_are_404(client):
    assert client.get("/api/projects/nope/revisions").status_code == 404
    assert client.get("/api/projects/nope/bom/diff", params={"a": "HEAD"}).status_code == 404


# ---- auth -------------------------------------------------------------------


# ---- M7e Editor: design rules + net classes ---------------------------------

_PRO_FULL = (
    "{\n"
    '  "board": {\n'
    '    "design_settings": {\n'
    '      "rules": {\n'
    '        "min_clearance": 0.2,\n'
    '        "min_track_width": 0.2\n'
    "      },\n"
    '      "track_widths": []\n'
    "    }\n"
    "  },\n"
    '  "net_settings": {\n'
    '    "classes": [\n'
    "      {\n"
    '        "bus_width": 12,\n'
    '        "clearance": 0.2,\n'
    '        "name": "Default",\n'
    '        "track_width": 0.2,\n'
    '        "via_diameter": 0.6,\n'
    '        "via_drill": 0.3,\n'
    '        "wire_width": 6\n'
    "      }\n"
    "    ],\n"
    '    "netclass_patterns": []\n'
    "  }\n"
    "}\n"
)


def _make_git_pro_project(dir_path, pro_text=_PRO_FULL):
    """A project dir that is its own git repo with a real-shaped .kicad_pro committed."""
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "board.kicad_pro").write_text(pro_text, encoding="utf-8")
    (dir_path / "board.kicad_sch").write_text("(kicad_sch)\n", encoding="utf-8")
    for args in (
        ["init", "-b", "main"],
        ["config", "user.email", "t@t"],
        ["config", "user.name", "t"],
        ["add", "."],
        ["commit", "-m", "init"],
    ):
        subprocess.run(["git", "-C", str(dir_path), *args], check=True, capture_output=True)
    head = subprocess.run(
        ["git", "-C", str(dir_path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return dir_path, head


def test_get_design_returns_current_classes_rules_and_floors(client, tmp_path):
    proj, _ = _make_git_pro_project(tmp_path / "board")
    rec = _register(client, proj)
    body = client.get(f"/api/projects/{rec['id']}/design").json()
    assert body["under_git"] is True
    assert [c["name"] for c in body["net_classes"]] == ["Default"]
    assert body["design_rules"]["min_track_width"] == 0.2
    assert "jlcpcb" in body["fab_floors"]
    assert body["validation"] == []


def test_get_design_unknown_project_is_404(client):
    assert client.get("/api/projects/nope/design").status_code == 404


def test_patch_net_classes_edits_the_kicad_pro_and_commits(client, tmp_path):
    proj, head = _make_git_pro_project(tmp_path / "board")
    rec = _register(client, proj)
    r = client.patch(
        f"/api/projects/{rec['id']}/net-classes",
        json={"classes": [{"name": "Default", "track_width": 0.15}]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["committed"] and body["committed"] != head
    on_disk = (proj / "board.kicad_pro").read_text(encoding="utf-8")
    assert '"track_width": 0.15' in on_disk
    # the design-settings block is untouched by a net-class edit
    assert '"min_track_width": 0.2' in on_disk


def test_patch_net_classes_returns_fab_validation(client, tmp_path):
    proj, _ = _make_git_pro_project(tmp_path / "board")
    rec = _register(client, proj)
    r = client.patch(
        f"/api/projects/{rec['id']}/net-classes",
        json={"classes": [{"name": "Default", "track_width": 0.05}], "floor": "oshpark_2"},
    )
    assert any("track" in f["issue"] for f in r.json()["validation"])


def test_patch_design_rules_edits_the_rules(client, tmp_path):
    proj, _ = _make_git_pro_project(tmp_path / "board")
    rec = _register(client, proj)
    r = client.patch(
        f"/api/projects/{rec['id']}/design-rules", json={"rules": {"min_track_width": 0.13}}
    )
    assert r.status_code == 200, r.text
    on_disk = (proj / "board.kicad_pro").read_text(encoding="utf-8")
    assert '"min_track_width": 0.13' in on_disk
    assert '"min_clearance": 0.2' in on_disk  # sibling rule preserved


def test_patch_net_classes_class_without_name_is_422(client, tmp_path):
    proj, _ = _make_git_pro_project(tmp_path / "board")
    rec = _register(client, proj)
    r = client.patch(
        f"/api/projects/{rec['id']}/net-classes", json={"classes": [{"track_width": 0.15}]}
    )  # no name
    assert r.status_code == 422


def test_patch_net_classes_empty_name_is_422(client, tmp_path):
    # an empty (or whitespace) class name passes a bare `name: str` but reconcile would
    # silently drop it and still report success. The DTO must reject it as a clean 422.
    proj, _ = _make_git_pro_project(tmp_path / "board")
    rec = _register(client, proj)
    r = client.patch(
        f"/api/projects/{rec['id']}/net-classes",
        json={"classes": [{"name": "  ", "track_width": 0.15}]},
    )
    assert r.status_code == 422


def test_patch_net_classes_on_a_non_git_project_is_400(client, tmp_path):
    rec = _register(client, _make_project(tmp_path / "ext" / "board"))  # not a git repo
    r = client.patch(
        f"/api/projects/{rec['id']}/net-classes",
        json={"classes": [{"name": "Default", "track_width": 0.15}]},
    )
    assert r.status_code == 400


def test_patch_net_classes_unknown_project_is_404(client):
    r = client.patch("/api/projects/nope/net-classes", json={"classes": [{"name": "Default"}]})
    assert r.status_code == 404


def test_patch_design_rules_evicts_the_stale_checks_cache(client, tmp_path, app_ctx):
    # a design-rule change can change DRC outcomes, so the cached ERC/DRC must not
    # linger as a fabricated pass. The write evicts it, forcing an honest re-run.
    proj, _ = _make_git_pro_project(tmp_path / "board")
    rec = _register(client, proj)
    app_ctx.checks_cache[rec["id"]] = {"stale": True}
    client.patch(
        f"/api/projects/{rec['id']}/design-rules", json={"rules": {"min_track_width": 0.13}}
    )
    assert rec["id"] not in app_ctx.checks_cache


# ---- roadmap #4 Editor: netclass patterns -----------------------------------


def test_patch_netclass_patterns_edits_the_kicad_pro_and_commits(client, tmp_path):
    proj, head = _make_git_pro_project(tmp_path / "board")
    rec = _register(client, proj)
    r = client.patch(
        f"/api/projects/{rec['id']}/netclass-patterns",
        json={"patterns": [{"pattern": "*GND", "netclass": "Default"}]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["committed"] and body["committed"] != head
    assert body["netclass_patterns"] == [{"netclass": "Default", "pattern": "*GND"}]
    on_disk = (proj / "board.kicad_pro").read_text(encoding="utf-8")
    assert '"pattern": "*GND"' in on_disk
    # the net classes are untouched by a patterns edit
    assert '"name": "Default"' in on_disk


def test_patch_netclass_patterns_unknown_netclass_is_400(client, tmp_path):
    proj, _ = _make_git_pro_project(tmp_path / "board")
    rec = _register(client, proj)
    r = client.patch(
        f"/api/projects/{rec['id']}/netclass-patterns",
        json={"patterns": [{"pattern": "*X", "netclass": "Nope"}]},
    )
    assert r.status_code == 400


def test_patch_netclass_patterns_blank_pattern_is_422(client, tmp_path):
    proj, _ = _make_git_pro_project(tmp_path / "board")
    rec = _register(client, proj)
    r = client.patch(
        f"/api/projects/{rec['id']}/netclass-patterns",
        json={"patterns": [{"pattern": "   ", "netclass": "Default"}]},
    )
    assert r.status_code == 422


def test_patch_netclass_patterns_on_a_non_git_project_is_400(client, tmp_path):
    rec = _register(client, _make_project(tmp_path / "ext" / "board"))  # not a git repo
    r = client.patch(
        f"/api/projects/{rec['id']}/netclass-patterns",
        json={"patterns": [{"pattern": "*GND", "netclass": "Default"}]},
    )
    assert r.status_code == 400


def test_patch_netclass_patterns_unknown_project_is_404(client):
    r = client.patch("/api/projects/nope/netclass-patterns", json={"patterns": []})
    assert r.status_code == 404


def test_patch_netclass_patterns_evicts_the_stale_checks_cache(client, tmp_path, app_ctx):
    # a netclass-pattern change alters DRC net grouping, so the cached ERC/DRC must not
    # linger as a fabricated pass. The write evicts it, forcing an honest re-run.
    proj, _ = _make_git_pro_project(tmp_path / "board")
    rec = _register(client, proj)
    app_ctx.checks_cache[rec["id"]] = {"stale": True}
    client.patch(
        f"/api/projects/{rec['id']}/netclass-patterns",
        json={"patterns": [{"pattern": "*GND", "netclass": "Default"}]},
    )
    assert rec["id"] not in app_ctx.checks_cache


# ---- M7f-A Editor: board setup + thickness ----------------------------------

_PCB_FULL = (
    "(kicad_pcb\n"
    "\t(version 20260206)\n"
    '\t(generator "pcbnew")\n'
    '\t(generator_version "10.0")\n'
    "\t(general\n\t\t(thickness 1.6)\n\t)\n"
    '\t(paper "A4")\n'
    "\t(setup\n"
    "\t\t(pad_to_mask_clearance 0.0508)\n"
    "\t\t(allow_soldermask_bridges_in_footprints no)\n"
    "\t)\n"
    '\t(net 0 "")\n'
    ")\n"
)


def _make_git_pcb_project(dir_path, pro_text=_PRO_FULL, pcb_text=_PCB_FULL):
    """A git-backed project dir with a committed .kicad_pro AND .kicad_pcb (so the
    board-setup / thickness editor has a real board to write)."""
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "board.kicad_pro").write_text(pro_text, encoding="utf-8")
    (dir_path / "board.kicad_sch").write_text("(kicad_sch)\n", encoding="utf-8")
    (dir_path / "board.kicad_pcb").write_text(pcb_text, encoding="utf-8")
    for args in (
        ["init", "-b", "main"],
        ["config", "user.email", "t@t"],
        ["config", "user.name", "t"],
        ["add", "."],
        ["commit", "-m", "init"],
    ):
        subprocess.run(["git", "-C", str(dir_path), *args], check=True, capture_output=True)
    head = subprocess.run(
        ["git", "-C", str(dir_path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return dir_path, head


def test_get_settings_returns_board_setup_thickness_and_fields(client, tmp_path):
    proj, _ = _make_git_pcb_project(tmp_path / "board")
    rec = _register(client, proj)
    body = client.get(f"/api/projects/{rec['id']}/settings").json()
    assert body["under_git"] is True
    assert body["has_board"] is True
    assert body["board_setup"]["pad_to_mask_clearance"] == 0.0508
    assert body["thickness"] == 1.6
    assert any(f["key"] == "pad_to_mask_clearance" for f in body["fields"])


def test_get_settings_no_board_is_honest(client, tmp_path):
    proj, _ = _make_git_pro_project(tmp_path / "board")  # .kicad_pro only, no board
    rec = _register(client, proj)
    body = client.get(f"/api/projects/{rec['id']}/settings").json()
    assert body["has_board"] is False
    assert body["board_setup"] == {}
    assert body["thickness"] is None


def test_get_settings_unknown_project_is_404(client):
    assert client.get("/api/projects/nope/settings").status_code == 404


def test_patch_settings_edits_the_kicad_pcb_and_commits(client, tmp_path):
    proj, head = _make_git_pcb_project(tmp_path / "board")
    rec = _register(client, proj)
    r = client.patch(
        f"/api/projects/{rec['id']}/settings", json={"board_setup": {"pad_to_mask_clearance": 0.1}}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["committed"] and body["committed"] != head
    on_disk = (proj / "board.kicad_pcb").read_text(encoding="utf-8")
    assert "(pad_to_mask_clearance 0.1)" in on_disk
    assert "(allow_soldermask_bridges_in_footprints no)" in on_disk  # sibling preserved


def test_patch_settings_writes_thickness(client, tmp_path):
    proj, _ = _make_git_pcb_project(tmp_path / "board")
    rec = _register(client, proj)
    r = client.patch(f"/api/projects/{rec['id']}/settings", json={"thickness": 0.8})
    assert r.status_code == 200, r.text
    assert r.json()["thickness"] == 0.8


def test_patch_settings_bad_key_is_400(client, tmp_path):
    proj, _ = _make_git_pcb_project(tmp_path / "board")
    rec = _register(client, proj)
    r = client.patch(
        f"/api/projects/{rec['id']}/settings", json={"board_setup": {"not_a_real_key": 1}}
    )
    assert r.status_code == 400


def test_patch_settings_bad_thickness_is_400(client, tmp_path):
    proj, _ = _make_git_pcb_project(tmp_path / "board")
    rec = _register(client, proj)
    r = client.patch(f"/api/projects/{rec['id']}/settings", json={"thickness": 0})
    assert r.status_code == 400


def test_patch_settings_no_board_is_400(client, tmp_path):
    proj, _ = _make_git_pro_project(tmp_path / "board")  # no .kicad_pcb
    rec = _register(client, proj)
    r = client.patch(f"/api/projects/{rec['id']}/settings", json={"thickness": 1.2})
    assert r.status_code == 400


def test_patch_settings_non_git_is_400(client, tmp_path):
    proj = _make_project(tmp_path / "ext" / "board")
    (proj / "board.kicad_pcb").write_text(_PCB_FULL, encoding="utf-8")
    rec = _register(client, proj)
    r = client.patch(f"/api/projects/{rec['id']}/settings", json={"thickness": 1.2})
    assert r.status_code == 400


def test_patch_settings_unknown_project_is_404(client):
    r = client.patch("/api/projects/nope/settings", json={"thickness": 1.2})
    assert r.status_code == 404


def test_patch_settings_evicts_the_stale_checks_cache(client, tmp_path, app_ctx):
    # a board-setup change can change DRC outcomes, so the cached ERC/DRC must be evicted.
    proj, _ = _make_git_pcb_project(tmp_path / "board")
    rec = _register(client, proj)
    app_ctx.checks_cache[rec["id"]] = {"stale": True}
    client.patch(f"/api/projects/{rec['id']}/settings", json={"thickness": 1.2})
    assert rec["id"] not in app_ctx.checks_cache


# ---- M7f-A2 Editor: .kicad_pro severities + ERC pin-map + text-variables -----


def _pro_a2_text():
    """A canonical .kicad_pro carrying the A2 surfaces (ERC + DRC severities, a 12x12 ERC
    pin-conflict matrix, top-level text variables), built through the serializer so it is
    byte-canonical and a minimal-diff edit is provable."""
    from stockroom.kicad import project_settings as _ps

    pin_map = [[0] * 12 for _ in range(12)]
    pin_map[1][1] = 2
    pin_map[6][0] = pin_map[0][6] = 1
    data = {
        "board": {
            "design_settings": {
                "rule_severities": {"clearance": "error", "silk_overlap": "warning"},
                "rules": {"min_clearance": 0.2, "min_track_width": 0.2},
            }
        },
        "erc": {
            "pin_map": pin_map,
            "rule_severities": {"pin_not_connected": "error", "wire_dangling": "warning"},
        },
        "net_settings": {"classes": [{"name": "Default"}], "netclass_patterns": []},
        "text_variables": {"REV": "A", "OLD": "drop"},
    }
    return _ps.serialize(data)


def test_get_settings_returns_pro_severities_pin_map_and_catalogs(client, tmp_path):
    proj, _ = _make_git_pcb_project(tmp_path / "board", pro_text=_pro_a2_text())
    rec = _register(client, proj)
    body = client.get(f"/api/projects/{rec['id']}/settings").json()
    assert body["has_pro"] is True
    assert body["erc_severities"]["pin_not_connected"] == "error"
    assert body["drc_severities"]["clearance"] == "error"
    assert body["erc_pin_map"][1][1] == 2
    assert body["text_variables"] == {"REV": "A", "OLD": "drop"}
    assert body["severity_levels"] == ["error", "warning", "ignore"]
    assert len(body["erc_pin_types"]) == 12


def test_patch_settings_edits_severities_and_commits(client, tmp_path):
    proj, head = _make_git_pcb_project(tmp_path / "board", pro_text=_pro_a2_text())
    rec = _register(client, proj)
    r = client.patch(
        f"/api/projects/{rec['id']}/settings",
        json={
            "erc_severities": {"pin_not_connected": "warning"},
            "drc_severities": {"clearance": "ignore"},
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["committed"] != head
    on_disk = (proj / "board.kicad_pro").read_text(encoding="utf-8")
    assert '"pin_not_connected": "warning"' in on_disk
    assert '"clearance": "ignore"' in on_disk
    assert '"wire_dangling": "warning"' in on_disk  # sibling severity preserved


def test_patch_settings_writes_pin_map(client, tmp_path):
    proj, _ = _make_git_pcb_project(tmp_path / "board", pro_text=_pro_a2_text())
    rec = _register(client, proj)
    new_map = [[0] * 12 for _ in range(12)]
    new_map[3][3] = 2
    r = client.patch(f"/api/projects/{rec['id']}/settings", json={"erc_pin_map": new_map})
    assert r.status_code == 200, r.text
    assert r.json()["erc_pin_map"] == new_map


def test_patch_settings_writes_and_deletes_text_variables(client, tmp_path):
    proj, _ = _make_git_pcb_project(tmp_path / "board", pro_text=_pro_a2_text())
    rec = _register(client, proj)
    r = client.patch(
        f"/api/projects/{rec['id']}/settings", json={"text_variables": {"REV": "B", "NEW": "x"}}
    )
    assert r.status_code == 200, r.text
    tv = r.json()["text_variables"]
    assert tv == {"REV": "B", "NEW": "x"} and "OLD" not in tv


def test_patch_settings_unknown_severity_rule_is_400(client, tmp_path):
    proj, _ = _make_git_pcb_project(tmp_path / "board", pro_text=_pro_a2_text())
    rec = _register(client, proj)
    r = client.patch(
        f"/api/projects/{rec['id']}/settings", json={"erc_severities": {"not_a_rule_xyz": "error"}}
    )
    assert r.status_code == 400


def test_patch_settings_bad_pin_map_is_400(client, tmp_path):
    proj, _ = _make_git_pcb_project(tmp_path / "board", pro_text=_pro_a2_text())
    rec = _register(client, proj)
    r = client.patch(
        f"/api/projects/{rec['id']}/settings", json={"erc_pin_map": [[0] * 12 for _ in range(11)]}
    )  # 11 rows
    assert r.status_code == 400


def test_patch_settings_blank_text_var_name_is_400(client, tmp_path):
    proj, _ = _make_git_pcb_project(tmp_path / "board", pro_text=_pro_a2_text())
    rec = _register(client, proj)
    r = client.patch(f"/api/projects/{rec['id']}/settings", json={"text_variables": {"  ": "x"}})
    assert r.status_code == 400


def test_patch_settings_board_and_pro_land_in_one_commit(client, tmp_path):
    proj, head = _make_git_pcb_project(tmp_path / "board", pro_text=_pro_a2_text())
    rec = _register(client, proj)
    r = client.patch(
        f"/api/projects/{rec['id']}/settings",
        json={
            "board_setup": {"pad_to_mask_clearance": 0.1},
            "erc_severities": {"pin_not_connected": "warning"},
        },
    )
    assert r.status_code == 200, r.text
    added = subprocess.run(
        ["git", "-C", str(proj), "rev-list", "--count", f"{head}..HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert added == "1"  # both edits in a single commit
    names = subprocess.run(
        ["git", "-C", str(proj), "show", "--name-only", "--format=", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert "board.kicad_pcb" in names and "board.kicad_pro" in names


def test_patch_settings_severity_change_evicts_the_checks_cache(client, tmp_path, app_ctx):
    proj, _ = _make_git_pcb_project(tmp_path / "board", pro_text=_pro_a2_text())
    rec = _register(client, proj)
    app_ctx.checks_cache[rec["id"]] = {"stale": True}
    client.patch(
        f"/api/projects/{rec['id']}/settings",
        json={"erc_severities": {"pin_not_connected": "warning"}},
    )
    assert rec["id"] not in app_ctx.checks_cache


def test_projects_requires_a_token(anon_client):
    assert anon_client.get("/api/projects").status_code == 401
    assert anon_client.post("/api/projects/x/checks").status_code == 401
    assert anon_client.post("/api/projects/x/bom").status_code == 401
    assert anon_client.get("/api/projects/x/bom").status_code == 401
    assert anon_client.get("/api/projects/x/bom/export").status_code == 401
    assert anon_client.get("/api/projects/x/revisions").status_code == 401
    assert anon_client.get("/api/projects/x/bom/diff").status_code == 401
    assert anon_client.get("/api/projects/x/design").status_code == 401
    assert anon_client.patch("/api/projects/x/net-classes", json={"classes": []}).status_code == 401
    assert anon_client.patch("/api/projects/x/design-rules", json={"rules": {}}).status_code == 401
    assert (
        anon_client.patch("/api/projects/x/netclass-patterns", json={"patterns": []}).status_code
        == 401
    )
    assert anon_client.get("/api/projects/x/settings").status_code == 401
    assert anon_client.patch("/api/projects/x/settings", json={"thickness": 1.2}).status_code == 401
    assert anon_client.get("/api/projects/x/fields").status_code == 401
    assert anon_client.patch("/api/projects/x/fields", json={"edits": []}).status_code == 401


# ---- M7f-B Editor: object conform (font/thickness normalize) -----------------

_PCB_CONFORM = (
    "(kicad_pcb\n"
    "\t(version 20260206)\n"
    "\t(general\n\t\t(thickness 1.6)\n\t)\n"
    '\t(gr_text "BRD"\n\t\t(at 5 5 0)\n\t\t(layer "F.SilkS")\n'
    "\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.5 1.5)\n\t\t\t\t(thickness 0.3)\n\t\t\t)\n\t\t)\n\t)\n"
    '\t(footprint "R"\n\t\t(property "Reference" "R1"\n\t\t\t(at 0 0 0)\n\t\t\t(layer "F.SilkS")\n'
    "\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n)\n"
)
_SCH_CONFORM = (
    "(kicad_sch\n"
    "\t(version 20260306)\n"
    '\t(text "NOTE"\n\t\t(at 10 10 0)\n'
    "\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 2.54 2.54)\n\t\t\t)\n\t\t)\n\t)\n"
    '\t(label "NET1"\n\t\t(at 20 20 0)\n'
    "\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t)\n\t)\n)\n"
)


def _make_git_conform_project(dir_path):
    """A git-backed project whose board + sheet both carry conformable text objects."""
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "board.kicad_pro").write_text("{}", encoding="utf-8")
    (dir_path / "board.kicad_sch").write_text(_SCH_CONFORM, encoding="utf-8")
    (dir_path / "board.kicad_pcb").write_text(_PCB_CONFORM, encoding="utf-8")
    for args in (
        ["init", "-b", "main"],
        ["config", "user.email", "t@t"],
        ["config", "user.name", "t"],
        ["add", "."],
        ["commit", "-m", "init"],
    ):
        subprocess.run(["git", "-C", str(dir_path), *args], check=True, capture_output=True)
    head = subprocess.run(
        ["git", "-C", str(dir_path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return dir_path, head


def test_get_conform_returns_catalog_and_state(client, tmp_path):
    proj, _ = _make_git_conform_project(tmp_path / "board")
    rec = _register(client, proj)
    body = client.get(f"/api/projects/{rec['id']}/conform").json()
    assert body["under_git"] is True
    assert body["has_pcb"] is True and body["has_sch"] is True
    assert {c["key"] for c in body["pcb_categories"]} == {"silk", "fab", "copper"}
    assert {c["key"] for c in body["sch_categories"]} == {"text", "labels"}
    assert body["suggested"]["silk"]["size"] > 0


def test_get_conform_unknown_project_is_404(client):
    assert client.get("/api/projects/nope/conform").status_code == 404


def test_post_conform_preview_counts_without_writing(client, tmp_path):
    proj, head = _make_git_conform_project(tmp_path / "board")
    rec = _register(client, proj)
    r = client.post(
        f"/api/projects/{rec['id']}/conform/preview",
        json={"pcb_targets": {"silk": {"size": 2.0}}, "sch_targets": {"labels": {"size": 2.0}}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3  # 2 silk + 1 label
    on_disk = (proj / "board.kicad_pcb").read_text(encoding="utf-8")
    assert "(size 1.5 1.5)" in on_disk  # unchanged: a preview writes nothing


def test_post_conform_preview_empty_selection_is_400(client, tmp_path):
    proj, _ = _make_git_conform_project(tmp_path / "board")
    rec = _register(client, proj)
    r = client.post(f"/api/projects/{rec['id']}/conform/preview", json={})
    assert r.status_code == 400


def test_patch_conform_applies_and_commits(client, tmp_path):
    proj, head = _make_git_conform_project(tmp_path / "board")
    rec = _register(client, proj)
    r = client.patch(
        f"/api/projects/{rec['id']}/conform",
        json={"pcb_targets": {"silk": {"size": 2.0}}, "sch_targets": {"labels": {"size": 2.0}}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["committed"] and body["committed"] != head
    assert body["total"] == 3
    assert (proj / "board.kicad_pcb").read_text(encoding="utf-8").count("(size 2 2)") == 2
    assert "(size 2 2)" in (proj / "board.kicad_sch").read_text(encoding="utf-8")


def test_patch_conform_bad_size_is_400(client, tmp_path):
    proj, _ = _make_git_conform_project(tmp_path / "board")
    rec = _register(client, proj)
    r = client.patch(
        f"/api/projects/{rec['id']}/conform", json={"pcb_targets": {"silk": {"size": 0}}}
    )
    assert r.status_code == 400


def test_patch_conform_unknown_category_is_400(client, tmp_path):
    proj, _ = _make_git_conform_project(tmp_path / "board")
    rec = _register(client, proj)
    r = client.patch(
        f"/api/projects/{rec['id']}/conform", json={"pcb_targets": {"bogus": {"size": 1.0}}}
    )
    assert r.status_code == 400


def test_patch_conform_non_git_is_400(client, tmp_path):
    proj = _make_project(tmp_path / "ext" / "board")
    (proj / "board.kicad_pcb").write_text(_PCB_CONFORM, encoding="utf-8")
    rec = _register(client, proj)
    r = client.patch(
        f"/api/projects/{rec['id']}/conform", json={"pcb_targets": {"silk": {"size": 2.0}}}
    )
    assert r.status_code == 400


def test_patch_conform_unknown_project_is_404(client):
    r = client.patch("/api/projects/nope/conform", json={"pcb_targets": {"silk": {"size": 2.0}}})
    assert r.status_code == 404


def test_patch_conform_evicts_the_stale_checks_cache(client, tmp_path, app_ctx):
    # conforming text size/thickness can change DRC (text height/thickness, silk clearance), so
    # the cached ERC/DRC must be evicted and the next check re-run honestly.
    proj, _ = _make_git_conform_project(tmp_path / "board")
    rec = _register(client, proj)
    app_ctx.checks_cache[rec["id"]] = {"stale": True}
    client.patch(
        f"/api/projects/{rec['id']}/conform", json={"pcb_targets": {"silk": {"size": 2.0}}}
    )
    assert rec["id"] not in app_ctx.checks_cache


# ---- M7f-C Editor: stackup / fab-preset --------------------------------------

_PCB_STACKUP = (
    "(kicad_pcb\n"
    "\t(version 20260206)\n"
    '\t(generator_version "10.0")\n'
    "\t(general\n\t\t(thickness 1.51)\n\t)\n"
    "\t(layers\n"
    '\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n\t\t(4 "In1.Cu" signal)\n\t\t(6 "In2.Cu" signal)\n'
    "\t)\n"
    "\t(setup\n"
    "\t\t(stackup\n"
    '\t\t\t(layer "F.Cu"\n\t\t\t\t(type "copper")\n\t\t\t\t(thickness 0.035)\n\t\t\t)\n'
    '\t\t\t(layer "dielectric 1"\n\t\t\t\t(type "prepreg")\n\t\t\t\t(thickness 0.1)\n'
    '\t\t\t\t(material "FR4")\n\t\t\t\t(epsilon_r 4.5)\n\t\t\t\t(loss_tangent 0.02)\n\t\t\t)\n'
    '\t\t\t(layer "In1.Cu"\n\t\t\t\t(type "copper")\n\t\t\t\t(thickness 0.035)\n\t\t\t)\n'
    '\t\t\t(layer "dielectric 2"\n\t\t\t\t(type "core")\n\t\t\t\t(thickness 1.24)\n'
    '\t\t\t\t(material "FR4")\n\t\t\t\t(epsilon_r 4.5)\n\t\t\t\t(loss_tangent 0.02)\n\t\t\t)\n'
    '\t\t\t(layer "In2.Cu"\n\t\t\t\t(type "copper")\n\t\t\t\t(thickness 0.035)\n\t\t\t)\n'
    '\t\t\t(layer "dielectric 3"\n\t\t\t\t(type "prepreg")\n\t\t\t\t(thickness 0.1)\n'
    '\t\t\t\t(material "FR4")\n\t\t\t\t(epsilon_r 4.5)\n\t\t\t\t(loss_tangent 0.02)\n\t\t\t)\n'
    '\t\t\t(layer "B.Cu"\n\t\t\t\t(type "copper")\n\t\t\t\t(thickness 0.035)\n\t\t\t)\n'
    '\t\t\t(copper_finish "None")\n\t\t\t(dielectric_constraints no)\n'
    "\t\t)\n"
    "\t)\n"
    ")\n"
)


def _make_git_stackup_project(dir_path, pcb_text=_PCB_STACKUP):
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "board.kicad_pro").write_text("{}", encoding="utf-8")
    (dir_path / "board.kicad_pcb").write_text(pcb_text, encoding="utf-8")
    for args in (
        ["init", "-b", "main"],
        ["config", "user.email", "t@t"],
        ["config", "user.name", "t"],
        ["add", "."],
        ["commit", "-m", "init"],
    ):
        subprocess.run(["git", "-C", str(dir_path), *args], check=True, capture_output=True)
    head = subprocess.run(
        ["git", "-C", str(dir_path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return dir_path, head


def test_get_stackup_returns_stack_and_presets(client, tmp_path):
    proj, _ = _make_git_stackup_project(tmp_path / "board")
    rec = _register(client, proj)
    body = client.get(f"/api/projects/{rec['id']}/stackup").json()
    assert body["under_git"] is True and body["has_board"] is True
    assert body["copper_layers"] == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
    assert body["thickness"] == 1.51
    assert body["stackup"]["copper_finish"] == "None"
    assert {p["key"] for p in body["presets"]} == {"oshpark_2", "oshpark_4"}


def test_get_stackup_unknown_project_is_404(client):
    assert client.get("/api/projects/nope/stackup").status_code == 404


def test_post_stackup_preview_preset_without_writing(client, tmp_path):
    proj, head = _make_git_stackup_project(tmp_path / "board")
    rec = _register(client, proj)
    before = (proj / "board.kicad_pcb").read_text(encoding="utf-8")
    r = client.post(f"/api/projects/{rec['id']}/stackup/preview", json={"preset_key": "oshpark_4"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["changed"] is True
    assert body["thickness"] == 1.5318  # the generated stack's own sum, KiCad's invariant
    assert body["stackup"]["copper_finish"] == "ENIG"
    assert body["verify_note"]
    assert (proj / "board.kicad_pcb").read_text(encoding="utf-8") == before  # nothing written


def test_post_stackup_preview_layer_mismatch_is_400(client, tmp_path):
    two_layer = _PCB_STACKUP.replace(
        '\t\t(4 "In1.Cu" signal)\n\t\t(6 "In2.Cu" signal)\n', ""
    )  # a board whose (layers) declares only F.Cu/B.Cu
    proj, _ = _make_git_stackup_project(tmp_path / "board", pcb_text=two_layer)
    rec = _register(client, proj)
    r = client.post(f"/api/projects/{rec['id']}/stackup/preview", json={"preset_key": "oshpark_4"})
    assert r.status_code == 400


def test_patch_stackup_applies_preset_and_commits(client, tmp_path):
    proj, head = _make_git_stackup_project(tmp_path / "board")
    rec = _register(client, proj)
    r = client.patch(f"/api/projects/{rec['id']}/stackup", json={"preset_key": "oshpark_4"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["committed"] and body["committed"] != head
    after = (proj / "board.kicad_pcb").read_text(encoding="utf-8")
    assert '(copper_finish "ENIG")' in after
    assert "(thickness 1.5318)" in after  # the generated stack's own sum


def test_patch_stackup_field_edit_applies(client, tmp_path):
    proj, _ = _make_git_stackup_project(tmp_path / "board")
    rec = _register(client, proj)
    r = client.patch(
        f"/api/projects/{rec['id']}/stackup",
        json={"copper_finish": "ENIG", "dielectric_constraints": True},
    )
    assert r.status_code == 200, r.text
    after = (proj / "board.kicad_pcb").read_text(encoding="utf-8")
    assert '(copper_finish "ENIG")' in after
    assert "(dielectric_constraints yes)" in after


def test_patch_stackup_both_modes_is_400(client, tmp_path):
    proj, _ = _make_git_stackup_project(tmp_path / "board")
    rec = _register(client, proj)
    r = client.patch(
        f"/api/projects/{rec['id']}/stackup",
        json={"preset_key": "oshpark_4", "copper_finish": "ENIG"},
    )
    assert r.status_code == 400


def test_patch_stackup_bad_thickness_is_400(client, tmp_path):
    proj, _ = _make_git_stackup_project(tmp_path / "board")
    rec = _register(client, proj)
    r = client.patch(
        f"/api/projects/{rec['id']}/stackup",
        json={"layer_edits": {"dielectric 1": {"thickness": -1}}},
    )
    assert r.status_code == 400


def test_patch_stackup_no_setup_block_is_400_not_500(client, tmp_path):
    # a board with copper but no (setup ...) block: an honest 400, never a raw 500 (KiCadFileError)
    no_setup = '(kicad_pcb\n\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n\t)\n)\n'
    proj, _ = _make_git_stackup_project(tmp_path / "board", pcb_text=no_setup)
    rec = _register(client, proj)
    r = client.patch(f"/api/projects/{rec['id']}/stackup", json={"preset_key": "oshpark_2"})
    assert r.status_code == 400


def test_patch_stackup_non_git_is_400(client, tmp_path):
    proj = tmp_path / "board"
    proj.mkdir(parents=True)
    (proj / "board.kicad_pro").write_text("{}", encoding="utf-8")
    (proj / "board.kicad_pcb").write_text(_PCB_STACKUP, encoding="utf-8")
    rec = _register(client, proj)
    r = client.patch(f"/api/projects/{rec['id']}/stackup", json={"preset_key": "oshpark_4"})
    assert r.status_code == 400


def test_patch_stackup_unknown_project_is_404(client):
    r = client.patch("/api/projects/nope/stackup", json={"preset_key": "oshpark_4"})
    assert r.status_code == 404


def test_patch_stackup_evicts_the_stale_checks_cache(client, tmp_path, app_ctx):
    # a stackup / thickness change can alter DRC / impedance outcomes, so the cached ERC/DRC must
    # be evicted and the next check re-run honestly.
    proj, _ = _make_git_stackup_project(tmp_path / "board")
    rec = _register(client, proj)
    app_ctx.checks_cache[rec["id"]] = {"stale": True}
    client.patch(f"/api/projects/{rec['id']}/stackup", json={"preset_key": "oshpark_4"})
    assert rec["id"] not in app_ctx.checks_cache


# ---- M7f-D Editor: Library Fill + Prepare/Complete-All + Restore ------------

# An unannotated component whose lib_id is the fixture library's TPS62130 (so Prepare annotates it
# U? -> U1 AND fills its blank identity from the library), with both reference forms.
_PREPARE_SHEET = (
    "\t(symbol\n"
    '\t\t(lib_id "SR-ICs:TPS62130")\n'
    '\t\t(at 10 10 0)\n\t\t(unit 1)\n\t\t(uuid "u-prep")\n'
    '\t\t(property "Reference" "U?" (at 10 8 0))\n'
    '\t\t(property "Value" "TPS62130" (at 12 10 0))\n'
    '\t\t(property "Footprint" "" (at 10 10 0))\n'
    '\t\t(property "Datasheet" "" (at 10 10 0))\n'
    '\t\t(instances\n\t\t\t(project "board"\n'
    '\t\t\t\t(path "/root-uuid"\n\t\t\t\t\t(reference "U?")\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n'
    "\t)\n"
)


def test_get_prepare_previews_annotate_fill_and_residual(client, tmp_path):
    proj, _head = _make_git_project(tmp_path / "prep", _PREPARE_SHEET)
    rec = _register(client, proj)
    r = client.get(f"/api/projects/{rec['id']}/prepare")
    assert r.status_code == 200
    body = r.json()
    assert body["under_git"] is True and body["has_sch"] is True
    assert body["annotate"] == 1
    assert (
        body["fill_fields"] >= 2
    )  # MPN + Manufacturer (+ Description + Footprint) from the library
    assert any(i["part_id"] == "tps62130" for i in body["plan"]["items"])
    # a preview never commits: the file is unchanged
    assert '"U?"' in (proj / "board.kicad_sch").read_text(encoding="utf-8")


def test_get_prepare_unknown_project_is_404(client):
    assert client.get("/api/projects/nope/prepare").status_code == 404


def test_post_prepare_runs_a_job_and_commits(client, app_ctx, tmp_path):
    proj, head = _make_git_project(tmp_path / "prep", _PREPARE_SHEET)
    rec = _register(client, proj)
    r = client.post(f"/api/projects/{rec['id']}/prepare")
    assert r.status_code == 200
    result = _stream_job_result(client, r.json()["job_id"])
    assert result is not None and result["committed"]
    after = (proj / "board.kicad_sch").read_text(encoding="utf-8")
    assert '(property "Reference" "U1"' in after
    assert '(property "MPN" "TPS62130"' in after


def test_post_prepare_non_git_is_400(client, tmp_path):
    rec = _register(client, _make_project(tmp_path / "ext" / "board", _PREPARE_SHEET))
    assert client.post(f"/api/projects/{rec['id']}/prepare").status_code == 400


def test_post_prepare_unknown_project_is_404(client):
    assert client.post("/api/projects/nope/prepare").status_code == 404


def test_manual_fill_links_a_component(client, tmp_path):
    # an annotated generic resistor manually linked to the fixture library IC (by part id)
    sheet = (
        "\t(symbol\n"
        '\t\t(lib_id "Device:R")\n\t\t(at 10 10 0)\n\t\t(uuid "u-mf")\n'
        '\t\t(property "Reference" "R1" (at 10 8 0))\n'
        '\t\t(property "Value" "10k" (at 12 10 0))\n'
        '\t\t(property "Footprint" "" (at 10 10 0))\n'
        '\t\t(instances\n\t\t\t(project "board"\n'
        '\t\t\t\t(path "/r"\n\t\t\t\t\t(reference "R1")\n\t\t\t\t)\n\t\t\t)\n\t\t)\n'
        "\t)\n"
    )
    proj, _head = _make_git_project(tmp_path / "mf", sheet)
    rec = _register(client, proj)
    r = client.post(
        f"/api/projects/{rec['id']}/prepare/fill", json={"ref": "R1", "part_id": "tps62130"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["committed"]
    assert '(lib_id "SR-ICs:TPS62130")' in (proj / "board.kicad_sch").read_text(encoding="utf-8")


def test_manual_fill_unknown_part_is_400(client, tmp_path):
    proj, _head = _make_git_project(tmp_path / "mf", _PREPARE_SHEET)
    rec = _register(client, proj)
    r = client.post(
        f"/api/projects/{rec['id']}/prepare/fill", json={"ref": "U?", "part_id": "nope"}
    )
    assert r.status_code == 400


def test_restore_reverts_the_last_prepare(client, tmp_path):
    proj, _head = _make_git_project(tmp_path / "prep", _PREPARE_SHEET)
    rec = _register(client, proj)
    before = (proj / "board.kicad_sch").read_text(encoding="utf-8")
    _stream_job_result(client, client.post(f"/api/projects/{rec['id']}/prepare").json()["job_id"])
    assert (proj / "board.kicad_sch").read_text(encoding="utf-8") != before

    r = client.post(f"/api/projects/{rec['id']}/restore")
    assert r.status_code == 200, r.text
    assert r.json()["restored"]
    assert (proj / "board.kicad_sch").read_text(encoding="utf-8") == before


def test_restore_nothing_to_restore_is_400(client, tmp_path):
    proj, _head = _make_git_project(tmp_path / "prep", _PREPARE_SHEET)
    rec = _register(client, proj)
    assert client.post(f"/api/projects/{rec['id']}/restore").status_code == 400


def test_restore_unknown_project_is_404(client):
    assert client.post("/api/projects/nope/restore").status_code == 404


# ---- M7h KiField bulk-field editor -------------------------------------------

_FIELDS_SHEET = (
    "\t(symbol\n"
    '\t\t(lib_id "Device:R")\n\t\t(at 10 10 0)\n\t\t(uuid "u-r1")\n'
    '\t\t(property "Reference" "R1" (at 10 8 0))\n'
    '\t\t(property "Value" "10k" (at 12 10 0))\n'
    '\t\t(property "Footprint" "Resistor_SMD:R_0402" (at 10 10 0))\n'
    '\t\t(property "MPN" "" (at 10 10 0))\n'
    '\t\t(instances\n\t\t\t(project "board"\n'
    '\t\t\t\t(path "/r1"\n\t\t\t\t\t(reference "R1")\n\t\t\t\t)\n\t\t\t)\n\t\t)\n'
    "\t)\n"
    "\t(symbol\n"
    '\t\t(lib_id "Device:C")\n\t\t(at 20 10 0)\n\t\t(uuid "u-c1")\n'
    '\t\t(property "Reference" "C1" (at 20 8 0))\n'
    '\t\t(property "Value" "100nF" (at 22 10 0))\n'
    '\t\t(property "Footprint" "Capacitor_SMD:C_0402" (at 20 10 0))\n'
    '\t\t(instances\n\t\t\t(project "board"\n'
    '\t\t\t\t(path "/c1"\n\t\t\t\t\t(reference "C1")\n\t\t\t\t)\n\t\t\t)\n\t\t)\n'
    "\t)\n"
)


def test_get_fields_returns_the_grid(client, tmp_path):
    proj, _head = _make_git_project(tmp_path / "flds", _FIELDS_SHEET)
    rec = _register(client, proj)
    body = client.get(f"/api/projects/{rec['id']}/fields").json()
    assert body["under_git"] is True and body["has_sch"] is True
    assert [r["ref"] for r in body["rows"]] == ["C1", "R1"]  # natural sort, C before R
    assert body["columns"][:3] == ["Reference", "Value", "Footprint"]
    assert "MPN" in body["columns"]
    assert body["readonly_columns"] == ["Reference"]
    r1 = next(r for r in body["rows"] if r["ref"] == "R1")
    assert r1["editable"] is True and r1["fields"]["Value"] == "10k"


def test_get_fields_unknown_project_is_404(client):
    assert client.get("/api/projects/nope/fields").status_code == 404


def test_patch_fields_writes_only_the_edited_cells_and_commits(client, tmp_path):
    proj, head = _make_git_project(tmp_path / "flds", _FIELDS_SHEET)
    rec = _register(client, proj)
    r = client.patch(
        f"/api/projects/{rec['id']}/fields",
        json={
            "edits": [
                {"ref": "R1", "field": "MPN", "value": "RC0402FR-0710KL"},
                {"ref": "R1", "field": "Value", "value": "22k"},
                {"ref": "C1", "field": "Footprint", "value": "Capacitor_SMD:C_0603"},
            ]
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["committed"] and body["committed"] != head
    assert body["components"] == 2 and body["fields"] == 3
    after = (proj / "board.kicad_sch").read_text(encoding="utf-8")
    assert '(property "MPN" "RC0402FR-0710KL"' in after
    assert '(property "Value" "22k"' in after
    assert '(property "Footprint" "Capacitor_SMD:C_0603"' in after
    # the reference and the OTHER component's value are untouched
    assert '(property "Reference" "R1"' in after
    assert '(property "Value" "100nF"' in after


def test_patch_fields_adds_a_new_field_column(client, tmp_path):
    proj, _head = _make_git_project(tmp_path / "flds", _FIELDS_SHEET)
    rec = _register(client, proj)
    r = client.patch(
        f"/api/projects/{rec['id']}/fields",
        json={"edits": [{"ref": "R1", "field": "Tolerance", "value": "1%"}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["committed"]
    assert '(property "Tolerance" "1%"' in (proj / "board.kicad_sch").read_text(encoding="utf-8")


def test_patch_fields_editing_reference_is_400(client, tmp_path):
    proj, _head = _make_git_project(tmp_path / "flds", _FIELDS_SHEET)
    rec = _register(client, proj)
    r = client.patch(
        f"/api/projects/{rec['id']}/fields",
        json={"edits": [{"ref": "R1", "field": "Reference", "value": "R9"}]},
    )
    assert r.status_code == 400


def test_patch_fields_blank_field_is_422(client, tmp_path):
    proj, _head = _make_git_project(tmp_path / "flds", _FIELDS_SHEET)
    rec = _register(client, proj)
    r = client.patch(
        f"/api/projects/{rec['id']}/fields",
        json={"edits": [{"ref": "R1", "field": "   ", "value": "x"}]},
    )
    assert r.status_code == 422


def test_patch_fields_noop_does_not_commit(client, tmp_path):
    proj, head = _make_git_project(tmp_path / "flds", _FIELDS_SHEET)
    rec = _register(client, proj)
    # write the value already on disk -> byte no-op -> no commit, HEAD unchanged
    r = client.patch(
        f"/api/projects/{rec['id']}/fields",
        json={"edits": [{"ref": "R1", "field": "Value", "value": "10k"}]},
    )
    assert r.status_code == 200 and r.json()["committed"] is None
    now = subprocess.run(
        ["git", "-C", str(proj), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    assert now == head


def test_patch_fields_non_git_is_400(client, tmp_path):
    rec = _register(client, _make_project(tmp_path / "ext" / "board", _FIELDS_SHEET))
    r = client.patch(
        f"/api/projects/{rec['id']}/fields",
        json={"edits": [{"ref": "R1", "field": "MPN", "value": "x"}]},
    )
    assert r.status_code == 400


def test_patch_fields_dirty_tree_is_400(client, tmp_path):
    proj, _head = _make_git_project(tmp_path / "flds", _FIELDS_SHEET)
    rec = _register(client, proj)
    sch = proj / "board.kicad_sch"
    sch.write_text(sch.read_text(encoding="utf-8") + "\n", encoding="utf-8")  # dirty after register
    r = client.patch(
        f"/api/projects/{rec['id']}/fields",
        json={"edits": [{"ref": "R1", "field": "MPN", "value": "x"}]},
    )
    assert r.status_code == 400


def test_patch_fields_evicts_stale_caches(client, app_ctx, tmp_path):
    proj, _head = _make_git_project(tmp_path / "flds", _FIELDS_SHEET)
    rec = _register(client, proj)
    app_ctx.checks_cache[rec["id"]] = {"stale": True}
    app_ctx.bom_cache[rec["id"]] = {"stale": True}
    client.patch(
        f"/api/projects/{rec['id']}/fields",
        json={"edits": [{"ref": "R1", "field": "MPN", "value": "NEW"}]},
    )
    assert rec["id"] not in app_ctx.checks_cache
    assert rec["id"] not in app_ctx.bom_cache


# ---- fab-prep (M7i) ---------------------------------------------------------
from pathlib import Path as _Path  # noqa: E402

_FIXTURE_PCB = _Path(__file__).parent.parent / "fixtures" / "kicad" / "minimal.kicad_pcb"


def _make_board_project(dir_path):
    """A project dir with a real .kicad_pcb (the minimal fixture) so register() discovers a
    board and fab export has something to plot."""
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "board.kicad_pro").write_text("{}", encoding="utf-8")
    # copy the fixture BYTE-for-byte (write_text would translate LF to CRLF on Windows and
    # drift from the served bytes / the byte-preserving layer); a real KiCad board is LF.
    (dir_path / "board.kicad_pcb").write_bytes(_FIXTURE_PCB.read_bytes())
    return dir_path


def test_fab_status_reports_a_board_and_cli_availability(client, tmp_path):
    rec = _register(client, _make_board_project(tmp_path / "brd"))
    st = client.get(f"/api/projects/{rec['id']}/fab").json()
    assert st["has_board"] is True
    assert st["boards"] == ["board.kicad_pcb"]
    assert "cli_available" in st


def test_fab_status_no_board_is_honest(client, tmp_path):
    rec = _register(client, _make_project(tmp_path / "sch"))  # .kicad_pro + .kicad_sch only
    st = client.get(f"/api/projects/{rec['id']}/fab").json()
    assert st["has_board"] is False and st["boards"] == []


def test_fab_status_unknown_id_is_404(client):
    assert client.get("/api/projects/nope/fab").status_code == 404


@pytest.mark.serial_only
def test_fab_export_streams_the_zip(client, tmp_path, monkeypatch):
    from stockroom.projects import fab_export as fx

    rec = _register(client, _make_board_project(tmp_path / "brd"))

    def fake_bundle(pcb, cli, **kw):
        return {
            "data": b"PK\x03\x04zip",
            "filename": "board-fab.zip",
            "content_type": "application/zip",
            "files": ["board-F_Cu.gtl"],
        }

    monkeypatch.setattr(fx, "build_fab_bundle", fake_bundle)
    r = client.get(f"/api/projects/{rec['id']}/fab/export")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert 'filename="board-fab.zip"' in r.headers["content-disposition"]
    assert r.content == b"PK\x03\x04zip"


def test_fab_export_no_board_is_400(client, tmp_path):
    rec = _register(client, _make_project(tmp_path / "sch"))
    assert client.get(f"/api/projects/{rec['id']}/fab/export").status_code == 400


def test_fab_export_unknown_id_is_404(client):
    assert client.get("/api/projects/nope/fab/export").status_code == 404


@pytest.mark.serial_only
def test_fab_export_missing_cli_is_502(client, tmp_path, monkeypatch):
    from stockroom.kicad.errors import KiCadCliError
    from stockroom.projects import fab_export as fx

    rec = _register(client, _make_board_project(tmp_path / "brd"))

    def no_cli(pcb, cli, **kw):
        raise KiCadCliError("kicad-cli was not found")

    monkeypatch.setattr(fx, "build_fab_bundle", no_cli)
    r = client.get(f"/api/projects/{rec['id']}/fab/export")
    assert r.status_code == 502
    assert "not found" in r.json()["detail"]


@pytest.mark.serial_only
def test_fab_export_passes_options_through(client, tmp_path, monkeypatch):
    from stockroom.projects import fab_export as fx

    rec = _register(client, _make_board_project(tmp_path / "brd"))
    seen = {}

    def capture(pcb, cli, **kw):
        seen.update(kw)
        return {
            "data": b"z",
            "filename": "board-fab.zip",
            "content_type": "application/zip",
            "files": [],
        }

    monkeypatch.setattr(fx, "build_fab_bundle", capture)
    client.get(
        f"/api/projects/{rec['id']}/fab/export"
        "?drill_format=gerber&drill_map=false&include_pos=false&protel_ext=false"
    )
    assert seen["drill_format"] == "gerber"
    assert seen["drill_map"] is False
    assert seen["include_pos"] is False
    assert seen["protel_ext"] is False


# ---- kicanvas raw project-file endpoint (M7 #11) ----------------------------


def test_project_file_returns_the_registered_board_bytes(client, tmp_path):
    rec = _register(client, _make_board_project(tmp_path / "brd"))
    r = client.get(f"/api/projects/{rec['id']}/file", params={"path": "board.kicad_pcb"})
    assert r.status_code == 200
    # the endpoint serves the exact file bytes; compare bytes, not newline-normalized text
    assert r.content == _FIXTURE_PCB.read_bytes()


def test_project_file_rejects_an_unregistered_path_as_404(client, tmp_path):
    proj = _make_board_project(tmp_path / "brd")
    (proj / "secret.txt").write_text("secret", encoding="utf-8")
    rec = _register(client, proj)
    assert (
        client.get(f"/api/projects/{rec['id']}/file", params={"path": "secret.txt"}).status_code
        == 404
    )


def test_project_file_rejects_path_traversal_as_404(client, tmp_path):
    # a ../ escape is not a registered project file: never serve outside the project
    rec = _register(client, _make_board_project(tmp_path / "brd"))
    (tmp_path / "outside.txt").write_text("nope", encoding="utf-8")
    assert (
        client.get(f"/api/projects/{rec['id']}/file", params={"path": "../outside.txt"}).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/projects/{rec['id']}/file", params={"path": "../../etc/passwd"}
        ).status_code
        == 404
    )


def test_project_file_unknown_id_is_404(client):
    assert (
        client.get("/api/projects/nope/file", params={"path": "board.kicad_pcb"}).status_code == 404
    )


def test_project_file_requires_the_token(anon_client, client, tmp_path):
    rec = _register(client, _make_board_project(tmp_path / "brd"))
    assert (
        anon_client.get(
            f"/api/projects/{rec['id']}/file", params={"path": "board.kicad_pcb"}
        ).status_code
        == 401
    )


# ---- EDA-neutral projects: Altium registration + per-EDA capabilities --------


def _make_altium_api_project(dir_path, name="Amp", blocks=None):
    from tests.backend.projects.test_bom import _write_schdoc

    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / f"{name}.PrjPcb").write_text(
        f"[Design]\nVersion=1.0\n\n[Document1]\nDocumentPath={name}.SchDoc\n",
        encoding="utf-8",
    )
    _write_schdoc(
        dir_path / f"{name}.SchDoc",
        *(
            blocks
            if blocks is not None
            else [
                {
                    "designator": "U1",
                    "lib_ref": "LM358",
                    "params": {
                        "MPN": "LM358DR",
                        "Manufacturer": "TI",
                        "Value": "LM358DR",
                        "Datasheet": "https://ti.com/lm358.pdf",
                        "Description": "Dual op-amp",
                    },
                    "footprint": "SOIC-8",
                },
            ]
        ),
    )
    return dir_path


def test_register_detects_an_altium_project(client, tmp_path):
    proj = _make_altium_api_project(tmp_path / "ext" / "amp")
    rec = _register(client, proj)
    assert rec["eda"] == "altium"
    assert rec["pro_path"] == "Amp.PrjPcb"
    assert rec["sheet_paths"] == ["Amp.SchDoc"]
    row = client.get("/api/projects").json()[0]
    assert row["eda"] == "altium"


def test_register_an_ambiguous_dir_needs_an_explicit_eda(client, tmp_path):
    proj = _make_project(tmp_path / "ext" / "board")
    _make_altium_api_project(proj, name="board")
    r = client.post("/api/projects", json={"root": proj.as_posix()})
    assert r.status_code == 400
    assert "both" in r.json()["detail"]
    r = client.post("/api/projects", json={"root": proj.as_posix(), "eda": "altium"})
    assert r.status_code == 200
    assert r.json()["eda"] == "altium"


def test_project_detail_carries_the_same_workspace_capabilities_for_every_eda(
    client, tmp_path
):
    kicad = _register(client, _make_project(tmp_path / "ext" / "board"))
    altium = _register(client, _make_altium_api_project(tmp_path / "ext" / "amp"))
    k = client.get(f"/api/projects/{kicad['id']}").json()
    a = client.get(f"/api/projects/{altium['id']}").json()
    assert k["capabilities"] == a["capabilities"] == [
        "design",
        "bom",
        "assemble",
        "changes",
        "releases",
    ]


def test_workspace_exposes_one_executable_parity_contract_for_both_edas(
    client, tmp_path
):
    kicad = _register(client, _make_project(tmp_path / "parity" / "board"))
    altium = _register(
        client, _make_altium_api_project(tmp_path / "parity" / "amp")
    )

    workspaces = [
        client.get(f"/api/projects/{project['id']}/workspace").json()
        for project in (kicad, altium)
    ]
    assert workspaces[0]["parity"] == workspaces[1]["parity"]
    parity = workspaces[0]["parity"]
    assert parity["schema"] == "stockroom-project-parity/1"
    assert parity["edas"] == ["kicad", "altium"]
    assert parity["strict"] is True
    assert [tool["key"] for tool in parity["tools"]] == workspaces[0]["tools"]
    assert all(tool["behavior"] == "identical" for tool in parity["tools"])
    assert all(tool["actions"] for tool in parity["tools"] if tool["status"] == "active")


def test_audit_reads_an_altium_project(client, tmp_path):
    proj = _make_altium_api_project(
        tmp_path / "ext" / "amp",
        blocks=[
            {
                "designator": "U1",
                "lib_ref": "LM358",
                "params": {"MPN": "LM358DR", "Manufacturer": "TI"},
                "footprint": "SOIC-8",
            },
            {"designator": "R?", "lib_ref": "RES", "params": {"Value": "10k"}},
        ],
    )
    rec = _register(client, proj)
    au = client.get(f"/api/projects/{rec['id']}/audit").json()
    assert au["components"] == 2
    kinds = {f["kind"] for f in au["findings"]}
    assert "unannotated" in kinds


def test_kicad_only_endpoints_are_an_honest_400_for_an_altium_project(client, tmp_path):
    rec = _register(client, _make_altium_api_project(tmp_path / "ext" / "amp"))
    pid = rec["id"]
    gated = [
        ("post", f"/api/projects/{pid}/checks", {}),
        ("get", f"/api/projects/{pid}/checks", None),
        ("get", f"/api/projects/{pid}/fab", None),
        ("get", f"/api/projects/{pid}/design", None),
        ("get", f"/api/projects/{pid}/settings", None),
        ("get", f"/api/projects/{pid}/fields", None),
        ("get", f"/api/projects/{pid}/conform", None),
        ("get", f"/api/projects/{pid}/stackup", None),
        ("get", f"/api/projects/{pid}/prepare", None),
        ("post", f"/api/projects/{pid}/prepare", {}),
    ]
    for method, path, body in gated:
        fn = getattr(client, method)
        r = fn(path, json=body) if body is not None else fn(path)
        assert r.status_code == 400, (path, r.status_code, r.text)
        assert "Altium" in r.json()["detail"], path


def test_buildability_for_an_altium_project_skips_erc_drc_honestly(client, tmp_path):
    rec = _register(client, _make_altium_api_project(tmp_path / "ext" / "amp"))
    v = client.get(f"/api/projects/{rec['id']}/buildability").json()
    # ERC/DRC run inside Altium, not here: the signal says not_applicable and never
    # blocks, while the BOM cold cache still does.
    assert v["signals"]["checks"]["state"] == "not_applicable"
    kinds = {b["kind"] for b in v["blockers"]}
    assert "checks_not_run" not in kinds
    assert "bom_not_built" in kinds
    # the complete DbLib placement carries an annotated ref and a footprint
    assert v["signals"]["completeness"]["state"] == "pass"


def test_bom_builds_for_an_altium_project(client, app_ctx, tmp_path):
    rec = _register(client, _make_altium_api_project(tmp_path / "ext" / "amp"))
    r = client.post(f"/api/projects/{rec['id']}/bom", json={})
    assert r.status_code == 200, r.text
    job = r.json()["job_id"]
    _drain_job(client, job)
    bom = client.get(f"/api/projects/{rec['id']}/bom").json()
    assert bom["line_count"] == 1
    assert bom["lines"][0]["mpn"] == "LM358DR"


# -- bulk assign surface -------------------------------------------------------

_ASSIGN_SHEET = (
    '  (symbol (lib_id "Device:R") (property "Reference" "R1" (at 0 0 0))'
    ' (property "Value" "10k" (at 0 0 0))'
    ' (property "Footprint" "Resistor_SMD:R_0402_1005Metric" (at 0 0 0)))\n'
    '  (symbol (lib_id "Device:R") (property "Reference" "R2" (at 0 0 0))'
    ' (property "Value" "10k" (at 0 0 0))'
    ' (property "Footprint" "Resistor_SMD:R_0402_1005Metric" (at 0 0 0)))\n'
)


def _write_stock_passive(app_ctx, part_id="r10k"):
    """Add a passive to the fixture library, filed the way `add_passive_part` really files one: its
    symbol and footprint are KiCad STOCK references, so it is unreachable by the symbol identity tier
    and only the value-matched candidate tier can offer it."""
    import json

    parts_dir = app_ctx.profile.library.parts_dir
    parts_dir.mkdir(parents=True, exist_ok=True)
    (parts_dir / f"{part_id}.json").write_text(
        json.dumps(
            {
                "id": part_id,
                "display_name": "10k 0402",
                "category": "Resistors",
                "description": "10k 1% 0402",
                "mpn": "RC0402FR-0710KL",
                "manufacturer": "Yageo",
                "passive": True,
                "eda": {
                    "kicad": {
                        "symbol": {"lib": "Device", "name": "R"},
                        "footprint": {"lib": "Resistor_SMD", "name": "R_0402_1005Metric"},
                    },
                    "altium": {
                        "symbol": {"lib": "Stockroom.SchLib", "name": "R"},
                        "footprint": {
                            "lib": "Stockroom.PcbLib",
                            "name": "R_0402_1005Metric",
                        },
                    },
                },
                "specs": {"Resistance": "10 kOhm", "Package": "0402"},
            }
        ),
        encoding="utf-8",
    )
    return part_id


def test_get_assign_groups_unidentified_placements(client, app_ctx, tmp_path):
    _write_stock_passive(app_ctx)
    proj, _head = _make_git_project(tmp_path / "asg", _ASSIGN_SHEET)
    rec = _register(client, proj)
    r = client.get(f"/api/projects/{rec['id']}/assign")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["unassigned"] == 2
    assert [g["refs"] for g in body["groups"]] == [["R1", "R2"]]
    assert [c["part_id"] for c in body["groups"][0]["candidates"]] == ["r10k"]
    assert body["groups"][0]["candidates"][0]["confidence"] == "value+footprint"


def test_get_assign_unknown_project_is_404(client):
    assert client.get("/api/projects/nope/assign").status_code == 404


def test_post_assign_fills_the_group(client, app_ctx, tmp_path):
    _write_stock_passive(app_ctx)
    proj, _head = _make_git_project(tmp_path / "asg", _ASSIGN_SHEET)
    rec = _register(client, proj)
    r = client.post(
        f"/api/projects/{rec['id']}/assign", json={"refs": ["R1", "R2"], "part_id": "r10k"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["committed"]
    after = (proj / "board.kicad_sch").read_text(encoding="utf-8")
    assert after.count('(property "MPN" "RC0402FR-0710KL"') == 2
    # the stock reference is kept verbatim, never requalified into a Stockroom category library
    assert "SR-Resistors" not in after
    # the group is gone from the surface afterwards
    assert client.get(f"/api/projects/{rec['id']}/assign").json()["unassigned"] == 0


def test_post_assign_unknown_part_is_400(client, app_ctx, tmp_path):
    _write_stock_passive(app_ctx)
    proj, _head = _make_git_project(tmp_path / "asg", _ASSIGN_SHEET)
    rec = _register(client, proj)
    r = client.post(f"/api/projects/{rec['id']}/assign", json={"refs": ["R1"], "part_id": "nope"})
    assert r.status_code == 400


def test_post_assign_stale_ref_is_400_and_writes_nothing(client, app_ctx, tmp_path):
    _write_stock_passive(app_ctx)
    proj, _head = _make_git_project(tmp_path / "asg", _ASSIGN_SHEET)
    rec = _register(client, proj)
    before = (proj / "board.kicad_sch").read_text(encoding="utf-8")
    r = client.post(
        f"/api/projects/{rec['id']}/assign", json={"refs": ["R1", "Z99"], "part_id": "r10k"}
    )
    assert r.status_code == 400
    assert (proj / "board.kicad_sch").read_text(encoding="utf-8") == before


def test_post_assign_empty_refs_is_400(client, app_ctx, tmp_path):
    _write_stock_passive(app_ctx)
    proj, _head = _make_git_project(tmp_path / "asg", _ASSIGN_SHEET)
    rec = _register(client, proj)
    assert (
        client.post(
            f"/api/projects/{rec['id']}/assign", json={"refs": [], "part_id": "r10k"}
        ).status_code
        == 400
    )


def test_post_assign_non_git_is_400(client, app_ctx, tmp_path):
    _write_stock_passive(app_ctx)
    rec = _register(client, _make_project(tmp_path / "ext" / "asg2", _ASSIGN_SHEET))
    assert (
        client.post(
            f"/api/projects/{rec['id']}/assign", json={"refs": ["R1"], "part_id": "r10k"}
        ).status_code
        == 400
    )


def test_identity_resolution_is_in_the_bom_contract_for_every_eda(client, tmp_path):
    """Identity resolution is one shared BOM action, never an EDA-specific capability."""
    kicad = _register(client, _make_project(tmp_path / "ext" / "board"))
    altium = _register(client, _make_altium_api_project(tmp_path / "ext" / "amp"))
    for proj in (kicad, altium):
        workspace = client.get(f"/api/projects/{proj['id']}/workspace").json()
        bom = next(tool for tool in workspace["parity"]["tools"] if tool["key"] == "bom")
        assert "resolve_identity" in bom["actions"]


def test_the_assign_endpoint_serves_an_altium_project(client, tmp_path):
    altium = _register(client, _make_altium_api_project(tmp_path / "ext" / "amp"))
    body = client.get(f"/api/projects/{altium['id']}/assign")
    assert body.status_code == 200, body.text
    data = body.json()
    assert data["eda"] == "altium"
    # The surface states where an assignment LANDS, because for this tool it is not the schematic.
    assert data["binding"]["writable"] is False
    assert data["binding"]["reason"]


def test_altium_assignment_uses_the_same_group_decision_and_updates_the_live_bom(
    client, app_ctx, tmp_path
):
    _write_stock_passive(app_ctx)
    project = _make_altium_api_project(
        tmp_path / "ext" / "altium-passives",
        blocks=[
            {
                "designator": "R1",
                "lib_ref": "R",
                "params": {"Value": "10k"},
                "footprint": "R_0402_1005Metric",
                "unique_id": "ALTIUM-R1",
            },
            {
                "designator": "R2",
                "lib_ref": "R",
                "params": {"Value": "10k"},
                "footprint": "R_0402_1005Metric",
                "unique_id": "ALTIUM-R2",
            },
        ],
    )
    record = _register(client, project)

    unresolved = client.get(f"/api/projects/{record['id']}/assign").json()
    assert [group["refs"] for group in unresolved["groups"]] == [["R1", "R2"]]
    assert unresolved["groups"][0]["candidates"][0]["part_id"] == "r10k"

    assigned = client.post(
        f"/api/projects/{record['id']}/assign",
        json={"refs": ["R1", "R2"], "part_id": "r10k"},
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["bound"] == 2
    assert (project / "Amp.SchDoc").exists()

    job_id = client.post(f"/api/projects/{record['id']}/bom", json={}).json()["job_id"]
    _drain_job(client, job_id)
    live_bom = client.get(f"/api/projects/{record['id']}/bom").json()
    assert live_bom["lines"][0]["refs"] == ["R1", "R2"]
    assert live_bom["lines"][0]["mpn"] == "RC0402FR-0710KL"
    assert live_bom["lines"][0]["in_library"] is True


def test_workspace_hygiene_endpoints_preview_then_apply(client, tmp_path):
    """The measured cause of the owner's KiCad peer-sync failures, reachable from the app. Preview is
    read-only; apply writes the ignore rules AND untracks the per-user files they now cover, because
    an ignore rule does nothing to a file that is already tracked."""
    root = _make_project(tmp_path / "ext" / "board")
    (root / "board.kicad_prl").write_text('{"window":{}}\n', encoding="utf-8")
    _git_init_commit(root)
    proj = _register(client, root)

    preview = client.get(f"/api/projects/{proj['id']}/hygiene")
    assert preview.status_code == 200, preview.text
    assert preview.json()["untracked"] == ["board.kicad_prl"]

    applied = client.post(f"/api/projects/{proj['id']}/hygiene")
    assert applied.status_code == 200, applied.text
    assert applied.json()["untracked"] == ["board.kicad_prl"]
    assert "*.kicad_prl" in (root / ".gitignore").read_text(encoding="utf-8")

    # ...and it is idempotent, so re-syncing does not churn the project's history.
    again = client.post(f"/api/projects/{proj['id']}/hygiene")
    assert again.json()["committed"] is None


def test_library_pin_endpoints_read_then_pin(client, tmp_path, app_ctx):
    """Batch 2 item 2, reachable from the app: an unpinned project says so, pinning writes the pin
    into the PROJECT's own repo, and reading it back reports a match against this machine."""
    root = _make_project(tmp_path / "ext" / "pinned")
    _git_init_commit(root)
    proj = _register(client, root)

    before = client.get(f"/api/projects/{proj['id']}/library-pin")
    assert before.status_code == 200, before.text
    body = before.json()
    assert body["status"] == "unpinned"
    assert body["pinned"] is None
    # the surface is told HOW this tool's paths stay portable, rather than hardcoding SR_LIB
    assert body["path_contract"]["variable"] == "SR_LIB"

    applied = client.post(f"/api/projects/{proj['id']}/library-pin")
    assert applied.status_code == 200, applied.text
    assert applied.json()["pinned"]["commit"] == app_ctx.repo.head()
    assert (root / "stockroom-library.json").exists()

    after = client.get(f"/api/projects/{proj['id']}/library-pin")
    assert after.json()["status"] == "match"
    # re-pinning an unchanged library commits nothing
    assert client.post(f"/api/projects/{proj['id']}/library-pin").json()["committed"] is None


def test_library_pin_on_a_project_with_no_git_is_a_400_not_a_silent_write(client, tmp_path):
    root = _make_project(tmp_path / "ext" / "loose")
    proj = _register(client, root)
    assert client.get(f"/api/projects/{proj['id']}/library-pin").json()["under_git"] is False
    resp = client.post(f"/api/projects/{proj['id']}/library-pin")
    assert resp.status_code == 400, resp.text
    assert not (root / "stockroom-library.json").exists()


def test_library_pin_for_an_unknown_project_is_a_404(client):
    assert client.get("/api/projects/nope/library-pin").status_code == 404
    assert client.post("/api/projects/nope/library-pin").status_code == 404
