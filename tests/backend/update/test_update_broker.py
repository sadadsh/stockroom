from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

import pytest
from tuf.api import exceptions as tuf_exceptions

from stockroom.service import (
    CoordinatorBusy,
    MutexAcquireResult,
    ServiceControl,
    ServiceMode,
)
from stockroom.update.broker import (
    UpdateBroker,
    UpdateBrokerJoinTimeout,
    UpdateBrokerLifecycleError,
    UpdateBrokerPhase,
    UpdateBrokerRole,
    UpdateBrokerRoleError,
)
from stockroom.update.manifest import RELEASE_MANIFEST_NAME, ReleaseManifest
from stockroom.update.trusted_repository import (
    ReleaseSetVerificationError,
    RepositoryRefreshError,
    TrustedReleaseRepository,
    VerifiedReleaseSet,
)

_SID = "S-1-5-21-1111111111-2222222222-3333333333-1001"


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


@dataclass(frozen=True, slots=True)
class _DeferredOutcome:
    operation: Callable[[], VerifiedReleaseSet]


_Outcome = VerifiedReleaseSet | BaseException | _DeferredOutcome


class _ScriptedRepository(TrustedReleaseRepository):
    def __init__(self, outcomes: list[_Outcome]) -> None:
        if not outcomes:
            raise ValueError("scripted repository needs an outcome")
        self._outcomes = outcomes
        self._lock = threading.Lock()
        self.call_count = 0

    def stage_release(self) -> VerifiedReleaseSet:
        with self._lock:
            index = min(self.call_count, len(self._outcomes) - 1)
            outcome = self._outcomes[index]
            self.call_count += 1
        if isinstance(outcome, BaseException):
            raise outcome
        if isinstance(outcome, _DeferredOutcome):
            return outcome.operation()
        return outcome


def _coordinator(
    database: Path,
    mutexes: _MutexRegistry,
) -> ServiceControl:
    return ServiceControl(
        database,
        mode=ServiceMode.COORDINATOR,
        identity=_Identity(),
        mutex_factory=mutexes,
        storage_policy=_AllowTestStorage(),
    )


def _shadow(database: Path) -> ServiceControl:
    return ServiceControl(
        database,
        mode=ServiceMode.SHADOW,
        identity=_Identity(),
        storage_policy=_AllowTestStorage(),
    )


def _release(tmp_path: Path, release_id: str = "2026.07.29.1") -> VerifiedReleaseSet:
    sbom = b'{"spdxVersion":"SPDX-2.3"}'
    document = {
        "api_compatibility": {"maximum": 5, "minimum": 3},
        "manifest_version": 1,
        "members": [
            {
                "kind": "sbom",
                "path": "Support/SBOM.spdx.json",
                "sha256": hashlib.sha256(sbom).hexdigest(),
                "size": len(sbom),
            }
        ],
        "migration": {
            "catalog": {"from": 6, "to": 7},
            "control": {"from": 3, "to": 4},
        },
        "minimum_host_version": "2.1.0",
        "package_version": "4.8.0",
        "protocol_version": 4,
        "release_id": release_id,
        "required_eda_bridge_version": "3.2.1",
        "required_odbc_driver_version": "18.5.1.1",
        "rollback_release_id": "2026.07.28.4",
        "sbom_sha256": hashlib.sha256(sbom).hexdigest(),
        "schema_compatibility": {
            "catalog": {"maximum": 8, "minimum": 7},
            "control": {"maximum": 5, "minimum": 4},
        },
        "workflow_code_versions": {"library-publication": 8},
    }
    manifest_bytes = json.dumps(
        document, sort_keys=True, separators=(",", ":")
    ).encode()
    manifest = ReleaseManifest.from_bytes(manifest_bytes)
    directory = tmp_path / "Staged" / release_id
    return VerifiedReleaseSet(
        release_id=release_id,
        directory=directory,
        manifest_path=directory / RELEASE_MANIFEST_NAME,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        manifest=manifest,
        members=MappingProxyType({}),
    )


def _broker(
    control: ServiceControl,
    fence,
    repository: TrustedReleaseRepository,
    **overrides: float,
) -> UpdateBroker:
    options = {
        "attempt_deadline_seconds": 0.25,
        "maximum_retry_backoff_seconds": 0.04,
        "minimum_retry_backoff_seconds": 0.02,
        "refresh_interval_seconds": 0.5,
        "retry_backoff_multiplier": 2.0,
        **overrides,
    }
    return UpdateBroker(
        control,
        role=UpdateBrokerRole.COORDINATOR,
        repository=repository,
        fence=fence,
        **options,
    )


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition did not become true before timeout")


def _failure_with_cause(
    error: RepositoryRefreshError,
    cause: BaseException,
) -> RepositoryRefreshError:
    error.__cause__ = cause
    return error


def test_coordinator_stages_and_shadow_observes_without_repository_authority(
    tmp_path: Path,
) -> None:
    database = tmp_path / "Control.sqlite"
    mutexes = _MutexRegistry()
    control = _coordinator(database, mutexes)
    fence = control.acquire()
    release = _release(tmp_path)
    repository = _ScriptedRepository([release])
    broker = _broker(control, fence, repository)

    handle = broker.start()
    _wait_until(lambda: broker.status().phase is UpdateBrokerPhase.STAGED)

    observer = UpdateBroker(
        _shadow(database),
        role=UpdateBrokerRole.SHADOW,
    )
    observed = observer.status()
    assert observed.role is UpdateBrokerRole.SHADOW
    assert observed.phase is UpdateBrokerPhase.STAGED
    assert observed.last_verified_release_id == release.release_id
    assert observed.target_release_id == release.release_id
    assert observed.deadline_at is not None
    assert observed.next_attempt_at == observed.deadline_at
    assert observed.thread_alive is False
    with pytest.raises(UpdateBrokerRoleError):
        observer.start()
    with pytest.raises(UpdateBrokerRoleError):
        UpdateBroker(
            _shadow(database),
            role=UpdateBrokerRole.SHADOW,
            repository=repository,
        )

    handle.cancel()
    handle.join(timeout=1)
    assert handle.status().phase is UpdateBrokerPhase.STOPPED
    assert handle.status().thread_alive is False
    assert repository.call_count == 1
    assert not hasattr(broker, "activate")
    control.release(fence)


@pytest.mark.parametrize(
    ("outcome", "expected_reason"),
    [
        (
            _failure_with_cause(
                RepositoryRefreshError("safe refresh failure"),
                tuf_exceptions.DownloadError(
                    "offline https://name:password@example.invalid/?token=not-for-storage"
                ),
            ),
            "repository_offline",
        ),
        (
            _failure_with_cause(
                RepositoryRefreshError("safe refresh failure"),
                tuf_exceptions.ExpiredMetadataError(
                    "expired credential-not-for-storage"
                ),
            ),
            "tuf_metadata_expired",
        ),
        (
            ReleaseSetVerificationError(
                "verification failed with secret-not-for-storage"
            ),
            "release_verification_failed",
        ),
    ],
)
def test_failures_retry_with_fixed_sanitized_reason_and_bounded_backoff(
    tmp_path: Path,
    outcome: BaseException,
    expected_reason: str,
) -> None:
    database = tmp_path / "Control.sqlite"
    mutexes = _MutexRegistry()
    control = _coordinator(database, mutexes)
    fence = control.acquire()
    repository = _ScriptedRepository([outcome])
    broker = _broker(control, fence, repository)

    handle = broker.start()
    _wait_until(
        lambda: any(
            event.event_type == "update_broker_status"
            and event.payload["blocking_reason"] == expected_reason
            for event in control.events()
        )
    )
    retry_events = [
        event
        for event in control.events()
        if event.event_type == "update_broker_status"
        and event.payload["blocking_reason"] == expected_reason
    ]
    first = retry_events[0].payload
    assert first["phase"] == "retry_wait"
    assert first["deadline_at"] == first["next_attempt_at"]
    assert isinstance(first["attempt"], int)
    _wait_until(lambda: repository.call_count >= 2)

    handle.cancel()
    handle.join(timeout=1)
    control.checkpoint(fence)
    stored = b"".join(
        path.read_bytes() for path in database.parent.iterdir() if path.is_file()
    )
    assert b"password" not in stored
    assert b"not-for-storage" not in stored
    assert b"example.invalid" not in stored
    control.release(fence)


def test_restart_recovers_last_verified_release_and_monotonic_attempt(
    tmp_path: Path,
) -> None:
    database = tmp_path / "Control.sqlite"
    mutexes = _MutexRegistry()
    first_control = _coordinator(database, mutexes)
    first_fence = first_control.acquire()
    release = _release(tmp_path)
    first_broker = _broker(
        first_control,
        first_fence,
        _ScriptedRepository([release]),
    )
    first_handle = first_broker.start()
    _wait_until(lambda: first_broker.status().phase is UpdateBrokerPhase.STAGED)
    first_attempt = first_broker.status().attempt
    first_handle.cancel()
    first_handle.join(timeout=1)
    first_control.release(first_fence)

    second_control = _coordinator(database, mutexes)
    second_fence = second_control.acquire()
    offline = _failure_with_cause(
        RepositoryRefreshError("offline"),
        tuf_exceptions.DownloadError("offline"),
    )
    second_broker = _broker(
        second_control,
        second_fence,
        _ScriptedRepository([offline]),
    )
    restored = second_broker.status()
    assert restored.last_verified_release_id == release.release_id
    assert restored.attempt == first_attempt

    second_handle = second_broker.start()
    _wait_until(
        lambda: (
            second_broker.status().phase is UpdateBrokerPhase.RETRY_WAIT
            and second_broker.status().blocking_reason == "repository_offline"
        )
    )
    retried = second_broker.status()
    assert retried.attempt == first_attempt + 1
    assert retried.last_verified_release_id == release.release_id

    shadow_status = UpdateBroker(
        _shadow(database),
        role=UpdateBrokerRole.SHADOW,
    ).status()
    assert shadow_status.phase is UpdateBrokerPhase.RETRY_WAIT
    assert shadow_status.last_verified_release_id == release.release_id
    assert shadow_status.generation == second_fence.generation
    second_handle.cancel()
    second_handle.join(timeout=1)
    second_control.release(second_fence)


def test_current_sid_mutex_and_generation_fence_leave_only_one_live_broker(
    tmp_path: Path,
) -> None:
    database = tmp_path / "Control.sqlite"
    mutexes = _MutexRegistry()
    first_control = _coordinator(database, mutexes)
    second_control = _coordinator(database, mutexes)
    first_fence = first_control.acquire()
    with pytest.raises(CoordinatorBusy):
        second_control.acquire()

    repository = _ScriptedRepository([_release(tmp_path)])
    first_broker = _broker(
        first_control,
        first_fence,
        repository,
        refresh_interval_seconds=0.02,
    )
    handle = first_broker.start()
    _wait_until(lambda: first_broker.status().phase is UpdateBrokerPhase.STAGED)
    duplicate_repository = _ScriptedRepository([_release(tmp_path)])
    duplicate = _broker(first_control, first_fence, duplicate_repository)
    with pytest.raises(UpdateBrokerLifecycleError, match="already has"):
        duplicate.start()
    assert duplicate_repository.call_count == 0

    first_control.release(first_fence)
    second_fence = second_control.acquire()
    _wait_until(
        lambda: (
            first_broker.status().phase is UpdateBrokerPhase.STALE
            and not first_broker.status().thread_alive
        )
    )
    handle.join(timeout=1)
    call_count = repository.call_count
    time.sleep(0.04)
    assert repository.call_count == call_count
    assert first_broker.status().generation == first_fence.generation
    second_control.release(second_fence)


def test_missed_attempt_deadline_is_visible_but_verified_set_is_preserved(
    tmp_path: Path,
) -> None:
    database = tmp_path / "Control.sqlite"
    mutexes = _MutexRegistry()
    control = _coordinator(database, mutexes)
    fence = control.acquire()
    release = _release(tmp_path)

    def slow_stage() -> VerifiedReleaseSet:
        time.sleep(0.04)
        return release

    broker = _broker(
        control,
        fence,
        _ScriptedRepository([_DeferredOutcome(slow_stage)]),
        attempt_deadline_seconds=0.01,
        minimum_retry_backoff_seconds=0.1,
        maximum_retry_backoff_seconds=0.1,
    )
    handle = broker.start()
    _wait_until(
        lambda: (
            broker.status().phase is UpdateBrokerPhase.RETRY_WAIT
            and broker.status().blocking_reason == "attempt_deadline_exceeded"
        )
    )

    assert broker.status().last_verified_release_id == release.release_id
    assert any(
        event.event_type == "update_release_staged" for event in control.events()
    )
    handle.cancel()
    handle.join(timeout=1)
    control.release(fence)


def test_owned_handle_reports_in_flight_cancellation_timeout_then_joins(
    tmp_path: Path,
) -> None:
    database = tmp_path / "Control.sqlite"
    mutexes = _MutexRegistry()
    control = _coordinator(database, mutexes)
    fence = control.acquire()
    entered = threading.Event()
    allow_finish = threading.Event()
    release = _release(tmp_path)

    def blocking_stage() -> VerifiedReleaseSet:
        entered.set()
        if not allow_finish.wait(2):
            raise AssertionError("test did not release staged operation")
        return release

    broker = _broker(
        control,
        fence,
        _ScriptedRepository([_DeferredOutcome(blocking_stage)]),
        attempt_deadline_seconds=0.02,
    )
    handle = broker.start()
    assert entered.wait(1)
    _wait_until(
        lambda: broker.status().blocking_reason == "attempt_deadline_exceeded"
    )
    handle.cancel()
    with pytest.raises(UpdateBrokerJoinTimeout):
        handle.join(timeout=0.01)

    allow_finish.set()
    handle.join(timeout=1)
    assert handle.status().phase is UpdateBrokerPhase.STOPPED
    assert handle.status().thread_alive is False
    control.release(fence)
