from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from types import MappingProxyType

import pytest

from stockroom.service import (
    CoordinatorConflict,
    GenerationFence,
    MutexAcquireResult,
    ServiceControl,
    ServiceMode,
)
from stockroom.update.activation import (
    ReleaseActivationFailed,
    ReleaseActivationPhase,
    ReleaseActivationRole,
    ReleaseActivationRoleError,
    ReleaseActivator,
    ReleaseHealthStage,
    ReleaseRollbackFailed,
)
from stockroom.update.immutable_store import (
    AcceptedRelease,
    AcceptedReleaseCorruption,
    ActiveReleaseState,
    ImmutableReleaseStore,
    ReleaseIdentityConflict,
    ReleaseStoreAuthorityError,
)
from stockroom.update.manifest import RELEASE_MANIFEST_NAME, ReleaseManifest
from stockroom.update.trusted_repository import VerifiedReleaseSet

_SID = "S-1-5-21-1111111111-2222222222-3333333333-1001"
_SECRET_ERROR = (
    "https://name:password@example.invalid/?token=must-not-enter-control-state"
)


class _Identity:
    def current_sid(self) -> str:
        return _SID


class _AllowTestStorage:
    def validate(self, database: Path) -> Path:
        return database.resolve(strict=False)


class _MutexHandle:
    def __init__(self, registry: _MutexRegistry) -> None:
        self._registry = registry
        self._held = False

    def try_acquire(self) -> MutexAcquireResult:
        if self._registry.owner is not None:
            return MutexAcquireResult.BUSY
        self._registry.owner = self
        self._held = True
        return MutexAcquireResult.ACQUIRED

    def release(self) -> None:
        if not self._held or self._registry.owner is not self:
            raise AssertionError("fake mutex release without ownership")
        self._registry.owner = None
        self._held = False


class _MutexRegistry:
    def __init__(self) -> None:
        self.owner: _MutexHandle | None = None

    def open_current_user(self, *, name: str, sid: str) -> _MutexHandle:
        assert name
        assert sid == _SID
        return _MutexHandle(self)


class _HandoffSeams:
    def __init__(
        self,
        *,
        live_release_id: str,
        fail_at: str | None = None,
        on_call: dict[str, Callable[[], None]] | None = None,
    ) -> None:
        self.live_release_id = live_release_id
        self.fail_at = fail_at
        self.on_call = {} if on_call is None else on_call
        self.calls: list[str] = []

    def _call(self, name: str) -> None:
        self.calls.append(name)
        callback = self.on_call.get(name)
        if callback is not None:
            callback()
        if self.fail_at == name:
            raise RuntimeError(_SECRET_ERROR)

    def rehearse(
        self,
        candidate: AcceptedRelease,
        current: AcceptedRelease,
        *,
        generation: int,
    ) -> None:
        assert candidate.release_id != current.release_id
        assert generation > 0
        self._call("rehearse")

    def rehearse_rollback(
        self,
        candidate: AcceptedRelease,
        current: AcceptedRelease,
        *,
        generation: int,
    ) -> None:
        assert candidate.release_id != current.release_id
        assert generation > 0
        self._call("rehearse_rollback")

    def launch_shadow(
        self,
        candidate: AcceptedRelease,
        *,
        generation: int,
    ) -> object:
        assert generation > 0
        self._call("launch")
        return {"candidate": candidate.release_id}

    def stop_shadow(self, launch_handle: object, *, generation: int) -> None:
        assert launch_handle
        assert generation > 0
        self._call("stop")

    def check(
        self,
        candidate: AcceptedRelease,
        launch_handle: object,
        *,
        stage: ReleaseHealthStage,
        generation: int,
    ) -> None:
        assert candidate.release_id
        assert launch_handle
        assert generation > 0
        self._call(
            "pre_health"
            if stage is ReleaseHealthStage.PRE_ADOPTION
            else "post_health"
        )

    def drain(self, current: AcceptedRelease, *, generation: int) -> object:
        assert current.release_id == self.live_release_id
        assert generation > 0
        self._call("drain")
        return {"drained": current.release_id}

    def resume(
        self,
        current: AcceptedRelease,
        drain_receipt: object,
        *,
        generation: int,
    ) -> None:
        assert self.live_release_id == current.release_id
        assert drain_receipt
        assert generation > 0
        self._call("resume")

    def adopt(
        self,
        candidate: AcceptedRelease,
        current: AcceptedRelease,
        launch_handle: object,
        drain_receipt: object,
        *,
        generation: int,
    ) -> object:
        assert self.live_release_id == current.release_id
        assert launch_handle
        assert drain_receipt
        assert generation > 0
        self._call("adopt")
        self.live_release_id = candidate.release_id
        return {"prior": current.release_id}

    def rollback(
        self,
        candidate: AcceptedRelease,
        current: AcceptedRelease,
        adoption_receipt: object,
        *,
        generation: int,
    ) -> None:
        assert self.live_release_id == candidate.release_id
        assert adoption_receipt
        assert generation > 0
        self._call("rollback")
        self.live_release_id = current.release_id

    def commit(
        self,
        candidate: AcceptedRelease,
        current: AcceptedRelease,
        adoption_receipt: object,
        *,
        generation: int,
    ) -> None:
        assert self.live_release_id == candidate.release_id
        assert current.release_id
        assert adoption_receipt
        assert generation > 0
        self._call("commit")


class _FailingCommitStore(ImmutableReleaseStore):
    fail_activation_commit = False
    fail_rollback_commit = False

    def select_active(
        self,
        current: AcceptedRelease,
        *,
        previous: AcceptedRelease | None,
        selection_reason: str,
        control: ServiceControl,
        fence: GenerationFence,
    ) -> ActiveReleaseState:
        if self.fail_activation_commit and selection_reason == "activate":
            raise AcceptedReleaseCorruption(_SECRET_ERROR)
        if self.fail_rollback_commit and selection_reason == "rollback":
            raise AcceptedReleaseCorruption(_SECRET_ERROR)
        return super().select_active(
            current,
            previous=previous,
            selection_reason=selection_reason,
            control=control,
            fence=fence,
        )


def _control(
    database: Path,
    mutexes: _MutexRegistry,
    *,
    mode: ServiceMode = ServiceMode.COORDINATOR,
) -> ServiceControl:
    return ServiceControl(
        database,
        mode=mode,
        identity=_Identity(),
        mutex_factory=mutexes if mode is ServiceMode.COORDINATOR else None,
        storage_policy=_AllowTestStorage(),
    )


def _verified_release(
    releases_directory: Path,
    *,
    release_id: str,
    rollback_release_id: str,
    content: str,
    compatible_from_release_ids: tuple[str, ...] | None = None,
) -> VerifiedReleaseSet:
    payloads = {
        "Backend/Stockroom.pyz": f"backend-{content}".encode(),
        "Frontend/Assets.zip": f"frontend-{content}".encode(),
        "Support/SBOM.spdx.json": (
            f'{{"name":"Stockroom","version":"{content}"}}'.encode()
        ),
    }
    kinds = {
        "Backend/Stockroom.pyz": "backend",
        "Frontend/Assets.zip": "frontend",
        "Support/SBOM.spdx.json": "sbom",
    }
    members = [
        {
            "kind": kinds[path],
            "path": path,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }
        for path, data in payloads.items()
    ]
    sbom_sha256 = next(
        member["sha256"] for member in members if member["kind"] == "sbom"
    )
    document = {
        "api_compatibility": {"maximum": 5, "minimum": 3},
        "manifest_version": 1,
        "members": members,
        "migration": {
            "catalog": {"from": 6, "to": 7},
            "control": {"from": 3, "to": 4},
        },
        "minimum_host_version": "2.1.0",
        "package_version": f"4.8.{content}",
        "protocol_version": 4,
        "release_id": release_id,
        "required_eda_bridge_version": "3.2.1",
        "required_odbc_driver_version": "18.5.1.1",
        "rollback_release_id": rollback_release_id,
        "sbom_sha256": sbom_sha256,
        "schema_compatibility": {
            "catalog": {"maximum": 8, "minimum": 7},
            "control": {"maximum": 5, "minimum": 4},
        },
        "workflow_code_versions": {"library-publication": 8},
    }
    if compatible_from_release_ids is not None:
        document["manifest_version"] = 2
        document["compatible_from_release_ids"] = list(
            compatible_from_release_ids
        )
    manifest_bytes = json.dumps(
        document, sort_keys=True, separators=(",", ":")
    ).encode()
    manifest = ReleaseManifest.from_bytes(manifest_bytes)
    directory = releases_directory / release_id
    directory.mkdir(parents=True)
    manifest_path = directory / RELEASE_MANIFEST_NAME
    manifest_path.write_bytes(manifest_bytes)
    member_paths: dict[str, Path] = {}
    for path, data in payloads.items():
        member_path = directory.joinpath(*path.split("/"))
        member_path.parent.mkdir(parents=True, exist_ok=True)
        member_path.write_bytes(data)
        member_paths[path] = member_path.resolve()
    return VerifiedReleaseSet(
        release_id=release_id,
        directory=directory,
        manifest_path=manifest_path,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        manifest=manifest,
        members=MappingProxyType(member_paths),
    )


def _setup(
    tmp_path: Path,
    *,
    store_type: type[ImmutableReleaseStore] = ImmutableReleaseStore,
) -> tuple[
    ServiceControl,
    GenerationFence,
    _MutexRegistry,
    ImmutableReleaseStore,
    VerifiedReleaseSet,
]:
    mutexes = _MutexRegistry()
    control = _control(tmp_path / "Control.sqlite", mutexes)
    fence = control.acquire()
    releases_directory = (tmp_path / "Releases").resolve()
    store = store_type(
        releases_directory=releases_directory,
        state_directory=(tmp_path / "State").resolve(),
    )
    initial = _verified_release(
        releases_directory,
        release_id="2026.07.28.4",
        rollback_release_id="2026.07.27.9",
        content="1",
    )
    store.initialize_active(initial, control=control, fence=fence)
    return control, fence, mutexes, store, initial


def _activator(
    control: ServiceControl,
    fence: GenerationFence,
    store: ImmutableReleaseStore,
    seams: _HandoffSeams,
) -> ReleaseActivator:
    return ReleaseActivator(
        control,
        store,
        role=ReleaseActivationRole.COORDINATOR,
        fence=fence,
        rehearsal=seams,
        launcher=seams,
        health=seams,
        drain=seams,
        adoption=seams,
    )


def test_atomic_pointer_reverifies_current_and_previous_without_deletion(
    tmp_path: Path,
) -> None:
    control, fence, _, store, initial = _setup(tmp_path)
    candidate = _verified_release(
        store.releases_directory,
        release_id="2026.07.29.1",
        rollback_release_id=initial.release_id,
        content="2",
    )
    accepted = store.accept_verified(candidate, control=control, fence=fence)
    selected = store.select_active(
        accepted,
        previous=store.verify_startup(control).current,
        selection_reason="activate",
        control=control,
        fence=fence,
    )

    reopened = store.verify_startup(_control(control.database, _MutexRegistry(), mode=ServiceMode.SHADOW))
    assert reopened.current.release_id == candidate.release_id
    assert reopened.previous is not None
    assert reopened.previous.release_id == initial.release_id
    assert selected.event_sequence == reopened.event_sequence
    pointer_events = [
        event
        for event in control.events()
        if event.event_type == "active_release_selected"
    ]
    assert pointer_events[-1].payload == {
        "current_manifest_sha256": candidate.manifest_sha256,
        "current_release_id": candidate.release_id,
        "previous_manifest_sha256": initial.manifest_sha256,
        "previous_release_id": initial.release_id,
        "schema_version": 1,
        "selection_reason": "activate",
    }
    assert initial.directory.is_dir()
    assert candidate.directory.is_dir()

    candidate.members["Backend/Stockroom.pyz"].write_bytes(b"tampered")
    with pytest.raises(AcceptedReleaseCorruption, match="byte verification"):
        store.verify_startup(control)
    control.release(fence)


def test_shadow_cannot_accept_initialize_or_select_release(tmp_path: Path) -> None:
    control, fence, _, store, initial = _setup(tmp_path)
    shadow = _control(control.database, _MutexRegistry(), mode=ServiceMode.SHADOW)
    active = store.verify_startup(shadow).current

    with pytest.raises(ReleaseStoreAuthorityError):
        store.accept_verified(initial, control=shadow, fence=fence)
    with pytest.raises(ReleaseStoreAuthorityError):
        store.select_active(
            active,
            previous=None,
            selection_reason="rollback",
            control=shadow,
            fence=fence,
        )
    control.release(fence)


def test_startup_reverification_fails_closed_when_previous_bytes_change(
    tmp_path: Path,
) -> None:
    control, fence, _, store, initial = _setup(tmp_path)
    candidate = _verified_release(
        store.releases_directory,
        release_id="2026.07.29.1",
        rollback_release_id=initial.release_id,
        content="2",
    )
    accepted = store.accept_verified(candidate, control=control, fence=fence)
    store.select_active(
        accepted,
        previous=store.verify_startup(control).current,
        selection_reason="activate",
        control=control,
        fence=fence,
    )
    initial.members["Frontend/Assets.zip"].write_bytes(b"tampered previous")

    with pytest.raises(AcceptedReleaseCorruption, match="byte verification"):
        store.verify_startup(control)

    assert candidate.directory.is_dir()
    assert initial.directory.is_dir()
    control.release(fence)


def test_startup_reverification_rejects_tampered_accepted_metadata(
    tmp_path: Path,
) -> None:
    control, fence, _, store, initial = _setup(tmp_path)
    receipt = store.state_directory / "Accepted Releases" / f"{initial.release_id}.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["manifest_sha256"] = "0" * 64
    receipt.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    with pytest.raises(ReleaseIdentityConflict, match="digest"):
        store.verify_startup(control)

    assert initial.directory.is_dir()
    control.release(fence)


def test_successful_activation_commits_only_after_post_health_and_retains_prior(
    tmp_path: Path,
) -> None:
    control, fence, _, store, initial = _setup(tmp_path)
    candidate = _verified_release(
        store.releases_directory,
        release_id="2026.07.29.1",
        rollback_release_id=initial.release_id,
        content="2",
    )
    pointer_seen_during_post_health: list[str] = []
    seams = _HandoffSeams(
        live_release_id=initial.release_id,
        on_call={
            "post_health": lambda: pointer_seen_during_post_health.append(
                store.verify_startup(control).current.release_id
            )
        },
    )
    activator = _activator(control, fence, store, seams)

    activated = activator.activate(candidate)

    assert seams.calls == [
        "rehearse",
        "launch",
        "pre_health",
        "drain",
        "adopt",
        "post_health",
        "commit",
    ]
    assert seams.live_release_id == candidate.release_id
    assert pointer_seen_during_post_health == [initial.release_id]
    assert activated.current.release_id == candidate.release_id
    assert activated.previous is not None
    assert activated.previous.release_id == initial.release_id
    assert activator.status().phase is ReleaseActivationPhase.ACTIVE
    assert store.verify_startup(control).current.release_id == candidate.release_id
    assert initial.directory.is_dir()
    assert candidate.directory.is_dir()

    shadow = ReleaseActivator(
        _control(control.database, _MutexRegistry(), mode=ServiceMode.SHADOW),
        store,
        role=ReleaseActivationRole.SHADOW,
    )
    assert shadow.status().phase is ReleaseActivationPhase.ACTIVE
    assert shadow.verify_startup().previous is not None
    with pytest.raises(ReleaseActivationRoleError):
        shadow.activate(candidate)
    control.release(fence)


@pytest.mark.parametrize(
    ("fail_at", "reason", "expected_cleanup"),
    [
        ("rehearse", "rehearsal_failed", []),
        ("launch", "launch_failed", []),
        ("pre_health", "pre_adoption_health_failed", ["stop"]),
        ("drain", "drain_failed", ["stop"]),
        ("adopt", "adoption_failed", ["resume", "stop"]),
    ],
)
def test_pre_adoption_failure_leaves_current_selected_and_cleans_owned_work(
    tmp_path: Path,
    fail_at: str,
    reason: str,
    expected_cleanup: list[str],
) -> None:
    control, fence, _, store, initial = _setup(tmp_path)
    candidate = _verified_release(
        store.releases_directory,
        release_id="2026.07.29.1",
        rollback_release_id=initial.release_id,
        content="2",
    )
    seams = _HandoffSeams(
        live_release_id=initial.release_id,
        fail_at=fail_at,
    )
    activator = _activator(control, fence, store, seams)

    with pytest.raises(ReleaseActivationFailed) as failure:
        activator.activate(candidate)

    assert failure.value.reason == reason
    assert failure.value.rolled_back is False
    assert seams.calls[-len(expected_cleanup) :] == expected_cleanup if expected_cleanup else True
    assert seams.live_release_id == initial.release_id
    assert store.verify_startup(control).current.release_id == initial.release_id
    assert activator.status().phase is ReleaseActivationPhase.FAILED
    assert activator.status().blocking_reason == reason
    assert candidate.directory.is_dir()
    control.checkpoint(fence)
    stored = b"".join(
        path.read_bytes() for path in control.database.parent.iterdir() if path.is_file()
    )
    assert b"must-not-enter-control-state" not in stored
    assert b"example.invalid" not in stored
    control.release(fence)


def test_post_adoption_health_failure_atomically_reconnects_and_restores_pointer(
    tmp_path: Path,
) -> None:
    control, fence, _, store, initial = _setup(tmp_path)
    candidate = _verified_release(
        store.releases_directory,
        release_id="2026.07.29.1",
        rollback_release_id=initial.release_id,
        content="2",
    )
    seams = _HandoffSeams(
        live_release_id=initial.release_id,
        fail_at="post_health",
    )
    activator = _activator(control, fence, store, seams)

    with pytest.raises(ReleaseActivationFailed) as failure:
        activator.activate(candidate)

    assert failure.value.reason == "post_adoption_health_failed"
    assert failure.value.rolled_back is True
    assert seams.calls[-3:] == ["rollback", "resume", "stop"]
    assert seams.live_release_id == initial.release_id
    restored = store.verify_startup(control)
    assert restored.current.release_id == initial.release_id
    assert restored.previous is None
    assert restored.selection_reason == "rollback"
    assert activator.status().phase is ReleaseActivationPhase.ROLLED_BACK
    assert candidate.directory.is_dir()
    control.release(fence)


def test_pointer_commit_failure_uses_same_post_adoption_rollback_boundary(
    tmp_path: Path,
) -> None:
    control, fence, _, store, initial = _setup(
        tmp_path,
        store_type=_FailingCommitStore,
    )
    candidate = _verified_release(
        store.releases_directory,
        release_id="2026.07.29.1",
        rollback_release_id=initial.release_id,
        content="2",
    )
    assert isinstance(store, _FailingCommitStore)
    store.fail_activation_commit = True
    seams = _HandoffSeams(live_release_id=initial.release_id)
    activator = _activator(control, fence, store, seams)

    with pytest.raises(ReleaseActivationFailed) as failure:
        activator.activate(candidate)

    assert failure.value.reason == "pointer_commit_failed"
    assert failure.value.rolled_back is True
    assert seams.calls[-3:] == ["rollback", "resume", "stop"]
    assert seams.live_release_id == initial.release_id
    assert store.verify_startup(control).current.release_id == initial.release_id
    control.release(fence)


def test_host_commit_runs_after_pointer_and_failure_restores_prior_release(
    tmp_path: Path,
) -> None:
    control, fence, _, store, initial = _setup(tmp_path)
    candidate = _verified_release(
        store.releases_directory,
        release_id="2026.07.29.1",
        rollback_release_id=initial.release_id,
        content="2",
    )
    pointer_seen_during_commit: list[str] = []
    seams = _HandoffSeams(
        live_release_id=initial.release_id,
        fail_at="commit",
        on_call={
            "commit": lambda: pointer_seen_during_commit.append(
                store.verify_startup(control).current.release_id
            )
        },
    )

    with pytest.raises(ReleaseActivationFailed) as failure:
        _activator(control, fence, store, seams).activate(candidate)

    assert pointer_seen_during_commit == [candidate.release_id]
    assert failure.value.reason == "adoption_commit_failed"
    assert failure.value.rolled_back is True
    assert seams.calls[-4:] == ["commit", "rollback", "resume", "stop"]
    assert seams.live_release_id == initial.release_id
    restored = store.verify_startup(control)
    assert restored.current.release_id == initial.release_id
    assert restored.previous is None
    assert restored.selection_reason == "rollback"
    control.release(fence)


def test_rollback_restores_the_exact_prior_current_and_previous_pair(
    tmp_path: Path,
) -> None:
    control, fence, _, store, initial = _setup(tmp_path)
    middle = _verified_release(
        store.releases_directory,
        release_id="2026.07.29.1",
        rollback_release_id=initial.release_id,
        content="2",
    )
    first_seams = _HandoffSeams(live_release_id=initial.release_id)
    _activator(control, fence, store, first_seams).activate(middle)

    candidate = _verified_release(
        store.releases_directory,
        release_id="2026.07.29.2",
        rollback_release_id=middle.release_id,
        content="3",
    )
    second_seams = _HandoffSeams(
        live_release_id=middle.release_id,
        fail_at="post_health",
    )
    with pytest.raises(ReleaseActivationFailed):
        _activator(control, fence, store, second_seams).activate(candidate)

    restored = store.verify_startup(control)
    assert restored.current.release_id == middle.release_id
    assert restored.previous is not None
    assert restored.previous.release_id == initial.release_id
    assert candidate.release_id not in {
        restored.current.release_id,
        restored.previous.release_id,
    }
    assert all(
        release.directory.is_dir() for release in (initial, middle, candidate)
    )
    control.release(fence)


def test_unproven_host_rollback_fails_explicitly_without_claiming_completion(
    tmp_path: Path,
) -> None:
    control, fence, _, store, initial = _setup(tmp_path)
    candidate = _verified_release(
        store.releases_directory,
        release_id="2026.07.29.1",
        rollback_release_id=initial.release_id,
        content="2",
    )
    seams = _HandoffSeams(
        live_release_id=initial.release_id,
        fail_at="post_health",
    )
    original_rollback = seams.rollback

    def failing_rollback(
        candidate_release: AcceptedRelease,
        current_release: AcceptedRelease,
        adoption_receipt: object,
        *,
        generation: int,
    ) -> None:
        del candidate_release, current_release, adoption_receipt, generation
        seams.calls.append("rollback")
        raise RuntimeError(_SECRET_ERROR)

    seams.rollback = failing_rollback  # ty: ignore[invalid-assignment]
    activator = _activator(control, fence, store, seams)

    with pytest.raises(ReleaseRollbackFailed, match="could not be proven"):
        activator.activate(candidate)

    assert original_rollback
    assert activator.status().phase is ReleaseActivationPhase.FAILED
    assert activator.status().blocking_reason == "rollback_failed"
    assert store.verify_startup(control).current.release_id == initial.release_id
    assert seams.live_release_id == candidate.release_id
    control.release(fence)


def test_generation_supersession_stops_before_any_later_transition(
    tmp_path: Path,
) -> None:
    control, fence, mutexes, store, initial = _setup(tmp_path)
    candidate = _verified_release(
        store.releases_directory,
        release_id="2026.07.29.1",
        rollback_release_id=initial.release_id,
        content="2",
    )
    successor = _control(control.database, mutexes)
    successor_fence: GenerationFence | None = None

    def supersede() -> None:
        nonlocal successor_fence
        control.release(fence)
        successor_fence = successor.acquire()

    seams = _HandoffSeams(
        live_release_id=initial.release_id,
        on_call={"rehearse": supersede},
    )
    activator = _activator(control, fence, store, seams)

    with pytest.raises(CoordinatorConflict, match="stale"):
        activator.activate(candidate)

    assert seams.calls == ["rehearse"]
    assert activator.status().phase is ReleaseActivationPhase.STALE
    assert store.verify_startup(successor).current.release_id == initial.release_id
    assert successor_fence is not None
    successor.release(successor_fence)


def test_incompatible_declared_rollback_target_never_reaches_handoff(
    tmp_path: Path,
) -> None:
    control, fence, _, store, initial = _setup(tmp_path)
    candidate = _verified_release(
        store.releases_directory,
        release_id="2026.07.29.1",
        rollback_release_id="2026.07.20.1",
        content="2",
    )
    seams = _HandoffSeams(live_release_id=initial.release_id)
    activator = _activator(control, fence, store, seams)

    with pytest.raises(ReleaseActivationFailed) as failure:
        activator.activate(candidate)

    assert failure.value.reason == "rollback_target_incompatible"
    assert seams.calls == []
    assert store.verify_startup(control).current.release_id == initial.release_id
    control.release(fence)


def test_signed_v2_compatibility_allows_skipping_uninstalled_releases(
    tmp_path: Path,
) -> None:
    control, fence, _, store, initial = _setup(tmp_path)
    candidate = _verified_release(
        store.releases_directory,
        release_id="2026.07.29.4",
        rollback_release_id="2026.07.29.3",
        compatible_from_release_ids=(
            "2026.07.29.3",
            initial.release_id,
        ),
        content="4",
    )
    seams = _HandoffSeams(live_release_id=initial.release_id)

    activated = _activator(control, fence, store, seams).activate(candidate)

    assert activated.current.release_id == candidate.release_id
    assert activated.previous is not None
    assert activated.previous.release_id == initial.release_id
    assert seams.live_release_id == candidate.release_id
    control.release(fence)
