from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from stockroom.service import (
    APPLICATION_ID,
    BUSY_TIMEOUT_MS,
    SCHEMA_VERSION,
    ControlDataCorruption,
    CoordinatorBusy,
    CoordinatorConflict,
    CoordinatorStatus,
    GenerationFence,
    IdentityMismatch,
    MutexAcquireResult,
    NamedMutexFactoryPort,
    ServiceControl,
    ServiceMode,
    ShadowModeViolation,
    StoragePolicyViolation,
    WindowsCurrentIdentity,
    WindowsLocalNtfsStorage,
)

SID_A = "S-1-5-21-1111111111-2222222222-3333333333-1001"
SID_B = "S-1-5-21-4444444444-5555555555-6666666666-1002"


@dataclass
class MutableIdentity:
    sid: str = SID_A

    def current_sid(self) -> str:
        return self.sid


class AllowTestStorage:
    def validate(self, database: Path) -> Path:
        return database.resolve(strict=False)


class RejectStorage:
    def validate(self, database: Path) -> Path:
        raise OSError("not local NTFS")


class FakeMutexHandle:
    def __init__(self, registry: FakeMutexRegistry):
        self.registry = registry
        self.held = False

    def try_acquire(self) -> MutexAcquireResult:
        if self.held:
            raise AssertionError("fake mutex does not support recursive claims")
        if self.registry.owner is not None:
            return MutexAcquireResult.BUSY
        self.registry.owner = self
        self.held = True
        if self.registry.recreated:
            self.registry.recreated = False
            return MutexAcquireResult.CREATED
        if self.registry.abandoned:
            self.registry.abandoned = False
            return MutexAcquireResult.ABANDONED
        return MutexAcquireResult.ACQUIRED

    def release(self) -> None:
        if not self.held or self.registry.owner is not self:
            raise AssertionError("fake mutex release without ownership")
        self.registry.owner = None
        self.held = False


class FakeMutexRegistry:
    def __init__(self):
        self.owner: FakeMutexHandle | None = None
        self.abandoned = False
        self.recreated = False
        self.opens: list[tuple[str, str]] = []
        self.handles: list[FakeMutexHandle] = []

    def open_current_user(self, *, name: str, sid: str) -> FakeMutexHandle:
        self.opens.append((name, sid))
        handle = FakeMutexHandle(self)
        self.handles.append(handle)
        return handle

    def abandon_owner(self) -> FakeMutexHandle:
        owner = self.owner
        if owner is None:
            raise AssertionError("no fake mutex owner to abandon")
        owner.held = False
        self.owner = None
        self.abandoned = True
        return owner

    def lose_owner_without_abandonment(self) -> FakeMutexHandle:
        owner = self.owner
        if owner is None:
            raise AssertionError("no fake mutex owner to lose")
        owner.held = False
        self.owner = None
        self.abandoned = False
        return owner

    def destroy_owner_and_mutex(self) -> FakeMutexHandle:
        owner = self.owner
        if owner is None:
            raise AssertionError("no fake mutex owner to destroy")
        owner.held = False
        self.owner = None
        self.abandoned = False
        self.recreated = True
        return owner


class ExplodingMutexFactory:
    def __init__(self):
        self.calls = 0

    def open_current_user(self, *, name: str, sid: str) -> FakeMutexHandle:
        self.calls += 1
        raise AssertionError("shadow mode must never open the coordinator mutex")


@pytest.fixture
def database(tmp_path: Path) -> Path:
    return tmp_path / "Control.sqlite"


def coordinator(
    database: Path,
    mutexes: FakeMutexRegistry,
    *,
    identity: MutableIdentity | None = None,
) -> ServiceControl:
    return ServiceControl(
        database,
        mode=ServiceMode.COORDINATOR,
        identity=MutableIdentity() if identity is None else identity,
        mutex_factory=mutexes,
        storage_policy=AllowTestStorage(),
    )


def shadow(
    database: Path,
    *,
    identity: MutableIdentity | None = None,
    mutex_factory: NamedMutexFactoryPort | None = None,
) -> ServiceControl:
    return ServiceControl(
        database,
        mode=ServiceMode.SHADOW,
        identity=MutableIdentity() if identity is None else identity,
        mutex_factory=mutex_factory,
        storage_policy=AllowTestStorage(),
    )


def test_new_database_has_durable_settings_schema_ledger_and_sid_binding(
    database: Path,
) -> None:
    mutexes = FakeMutexRegistry()
    control = coordinator(database, mutexes)

    with control._connect(readonly=False) as connection:
        settings = {
            "application_id": connection.execute("PRAGMA application_id").fetchone()[0],
            "busy_timeout": connection.execute("PRAGMA busy_timeout").fetchone()[0],
            "foreign_keys": connection.execute("PRAGMA foreign_keys").fetchone()[0],
            "journal_mode": connection.execute("PRAGMA journal_mode").fetchone()[0],
            "synchronous": connection.execute("PRAGMA synchronous").fetchone()[0],
            "user_version": connection.execute("PRAGMA user_version").fetchone()[0],
        }
        ledger = connection.execute(
            "SELECT version, name, sha256 FROM schema_migrations"
        ).fetchall()
        stored_sid = connection.execute(
            "SELECT windows_sid FROM runtime_identity WHERE singleton = 1"
        ).fetchone()[0]
        integrity = connection.execute("PRAGMA integrity_check").fetchall()
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()

    assert settings == {
        "application_id": APPLICATION_ID,
        "busy_timeout": BUSY_TIMEOUT_MS,
        "foreign_keys": 1,
        "journal_mode": "wal",
        "synchronous": 2,
        "user_version": SCHEMA_VERSION,
    }
    assert len(ledger) == 1
    assert tuple(ledger[0])[:2] == (1, "Initial control authority schema")
    assert len(ledger[0]["sha256"]) == 64
    assert stored_sid == SID_A
    assert [tuple(row) for row in integrity] == [("ok",)]
    assert foreign_key_errors == []

    mutex_name, acl_sid = mutexes.opens[0]
    assert SID_A not in mutex_name
    assert mutex_name.endswith(hashlib.sha256(SID_A.encode("ascii")).hexdigest())
    assert acl_sid == SID_A


def test_two_contenders_and_wall_clock_cannot_take_over_healthy_owner(
    database: Path,
) -> None:
    mutexes = FakeMutexRegistry()
    first = coordinator(database, mutexes)
    second = coordinator(database, mutexes)

    first_fence = first.acquire(now=1.0)
    with pytest.raises(CoordinatorBusy):
        second.acquire(now=10**15)

    assert first_fence.generation == 1
    assert first.snapshot().status is CoordinatorStatus.ACTIVE
    assert first.snapshot().generation == 1


def test_sqlite_fence_rejects_active_takeover_without_abandonment(
    database: Path,
) -> None:
    mutexes = FakeMutexRegistry()
    first = coordinator(database, mutexes)
    second = coordinator(database, mutexes)
    first_fence = first.acquire(now=1.0)

    mutexes.lose_owner_without_abandonment()
    with pytest.raises(
        CoordinatorConflict,
        match="without kernel crash evidence",
    ):
        second.acquire(now=2.0)

    snapshot = first.snapshot()
    assert snapshot.generation == first_fence.generation
    assert snapshot.owner_id == first_fence.owner_id
    assert snapshot.status is CoordinatorStatus.ACTIVE
    assert mutexes.owner is None


def test_abandoned_mutex_is_only_crash_recovery_authority_and_fences_old_writer(
    database: Path,
) -> None:
    mutexes = FakeMutexRegistry()
    first = coordinator(database, mutexes)
    first_fence = first.acquire(now=1.0)
    assert (
        first.record_event(
            first_fence,
            "worker_advanced",
            {"step": 1},
            now=2.0,
        )
        == 2
    )

    mutexes.abandon_owner()
    reopened = coordinator(database, mutexes)
    second_fence = reopened.acquire(now=3.0)

    assert second_fence.generation == first_fence.generation + 1
    with pytest.raises(CoordinatorConflict, match="stale"):
        first.record_event(
            first_fence,
            "worker_advanced",
            {"step": 2},
            now=4.0,
        )

    events = reopened.events()
    assert [event.sequence for event in events] == [1, 2, 3, 4]
    assert [event.event_type for event in events] == [
        "coordinator_acquired",
        "worker_advanced",
        "coordinator_abandoned",
        "coordinator_acquired",
    ]
    assert events[-1].generation == second_fence.generation
    assert events[-1].payload == {"acquisition": "abandoned"}


def test_recreated_mutex_is_cold_crash_evidence_and_fences_old_writer(
    database: Path,
) -> None:
    mutexes = FakeMutexRegistry()
    first = coordinator(database, mutexes)
    first_fence = first.acquire(now=1.0)
    first.record_event(first_fence, "worker_advanced", {"step": 1}, now=2.0)

    mutexes.destroy_owner_and_mutex()
    reopened = coordinator(database, mutexes)
    second_fence = reopened.acquire(now=3.0)

    assert second_fence.generation == first_fence.generation + 1
    with pytest.raises(CoordinatorConflict, match="stale"):
        first.record_event(
            first_fence,
            "worker_advanced",
            {"step": 2},
            now=4.0,
        )
    assert [event.event_type for event in reopened.events()] == [
        "coordinator_acquired",
        "worker_advanced",
        "coordinator_cold_crash",
        "coordinator_acquired",
    ]
    assert reopened.events()[-1].payload == {"acquisition": "recreated"}
    with sqlite3.connect(database) as connection:
        history = connection.execute(
            """
            SELECT generation, acquired_via, release_reason
            FROM coordinator_generations
            ORDER BY generation
            """
        ).fetchall()
    assert history == [
        (first_fence.generation, "normal", "cold_crash"),
        (second_fence.generation, "recreated", None),
    ]


def test_release_and_reacquire_are_monotonic_and_old_fence_never_reactivates(
    database: Path,
) -> None:
    mutexes = FakeMutexRegistry()
    control = coordinator(database, mutexes)

    first = control.acquire(now=1.0)
    control.release(first, now=2.0)
    second = control.acquire(now=3.0)
    sequence = control.record_event(second, "worker_advanced", {"step": 2}, now=4.0)

    assert first.generation == 1
    assert second.generation == 2
    assert first.owner_id != second.owner_id
    assert sequence == 4
    with pytest.raises(CoordinatorConflict):
        control.record_event(first, "worker_advanced", {"step": 3}, now=5.0)
    assert [event.sequence for event in control.events()] == [1, 2, 3, 4]


def test_shadow_is_read_only_and_never_opens_or_exercises_mutex(
    database: Path,
) -> None:
    mutexes = FakeMutexRegistry()
    owner = coordinator(database, mutexes)
    fence = owner.acquire(now=1.0)
    owner.record_event(fence, "worker_advanced", {"step": 1}, now=2.0)
    exploding_factory = ExplodingMutexFactory()

    observer = shadow(
        database,
        mutex_factory=exploding_factory,
    )
    before = observer.snapshot()

    with pytest.raises(ShadowModeViolation):
        observer.acquire()
    with pytest.raises(ShadowModeViolation):
        observer.release(fence)
    with pytest.raises(ShadowModeViolation):
        observer.record_event(fence, "worker_advanced", {"step": 2})
    with pytest.raises(ShadowModeViolation):
        observer.checkpoint(fence)

    after = observer.snapshot()
    assert exploding_factory.calls == 0
    assert before == after
    assert after.mode is ServiceMode.SHADOW
    assert [event.event_type for event in observer.events()] == [
        "coordinator_acquired",
        "worker_advanced",
    ]


def test_wrong_or_changed_sid_is_rejected_without_control_mutation(
    database: Path,
) -> None:
    mutexes = FakeMutexRegistry()
    identity = MutableIdentity()
    owner = coordinator(database, mutexes, identity=identity)
    fence = owner.acquire(now=1.0)
    before = owner.snapshot()

    identity.sid = SID_B
    with pytest.raises(IdentityMismatch):
        owner.snapshot()
    with pytest.raises(IdentityMismatch):
        owner.record_event(fence, "worker_advanced", {"step": 1}, now=2.0)
    with pytest.raises(IdentityMismatch):
        shadow(database, identity=identity)

    identity.sid = SID_A
    assert owner.snapshot() == before


def test_malformed_schema_ledger_and_shape_fail_closed(database: Path) -> None:
    mutexes = FakeMutexRegistry()
    coordinator(database, mutexes)

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE schema_migrations SET sha256 = ? WHERE version = 1",
            ("0" * 64,),
        )

    with pytest.raises(ControlDataCorruption, match="ledger"):
        shadow(database)


def test_duplicate_key_json_is_rejected_even_when_sqlite_json_accepts_it(
    database: Path,
) -> None:
    mutexes = FakeMutexRegistry()
    control = coordinator(database, mutexes)
    fence = control.acquire(now=1.0)

    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO control_events(
                event_id,
                generation,
                event_type,
                payload_json,
                occurred_at,
                schema_version
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "f" * 32,
                fence.generation,
                "worker_advanced",
                '{"step":1,"step":2}',
                2.0,
                SCHEMA_VERSION,
            ),
        )

    with pytest.raises(ControlDataCorruption, match="strict JSON"):
        control.events()


@pytest.mark.parametrize(
    "payload",
    [
        {"password": "not-for-storage"},
        {"authorization": "redacted"},
        {"value": "Bearer not-for-storage"},
        {"value": float("nan")},
        {"value": b"not-json"},
    ],
)
def test_event_payloads_are_strict_json_and_reject_secret_shaped_data(
    database: Path,
    payload: dict[str, Any],
) -> None:
    mutexes = FakeMutexRegistry()
    control = coordinator(database, mutexes)
    fence = control.acquire(now=1.0)

    with pytest.raises(ValueError) as error:
        control.record_event(
            fence,
            "worker_advanced",
            payload,
            now=2.0,
        )

    assert "not-for-storage" not in str(error.value)
    assert [event.event_type for event in control.events()] == ["coordinator_acquired"]
    for path in database.parent.iterdir():
        if path.is_file():
            assert b"not-for-storage" not in path.read_bytes()


def test_storage_policy_rejection_and_shadow_missing_database_are_fail_closed(
    database: Path,
) -> None:
    with pytest.raises(StoragePolicyViolation):
        ServiceControl(
            database,
            mode=ServiceMode.COORDINATOR,
            identity=MutableIdentity(),
            mutex_factory=FakeMutexRegistry(),
            storage_policy=RejectStorage(),
        )

    with pytest.raises(ControlDataCorruption, match="initialized"):
        shadow(database)
    assert not database.exists()


@pytest.mark.skipif(os.name != "nt", reason="real Windows port check")
def test_windows_identity_and_local_ntfs_ports_on_test_volume(
    database: Path,
) -> None:
    sid = WindowsCurrentIdentity().current_sid()
    resolved = WindowsLocalNtfsStorage().validate(database)

    assert sid.startswith("S-")
    assert resolved == database.resolve(strict=False)
