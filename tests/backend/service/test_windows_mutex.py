from __future__ import annotations

import ctypes
import multiprocessing
import os
import uuid
from ctypes import wintypes
from pathlib import Path
from typing import Any

import pytest

from stockroom.service import (
    CoordinatorConflict,
    GenerationFence,
    MutexAcquireResult,
    NamedMutexFactoryPort,
    ServiceControl,
    ServiceMode,
    WindowsCurrentIdentity,
    WindowsMutexSecurityError,
    WindowsMutexStateError,
    WindowsMutexWaitFailed,
    WindowsNamedMutexFactory,
    WindowsNamedMutexHandle,
    current_user_mutex_name,
    secure_windows_mutex_factory,
)

pytestmark = [
    pytest.mark.skipif(os.name != "nt", reason="real Windows mutex tests"),
    pytest.mark.global_windows_mutex,
]


def _owner_process(
    purpose: str,
    ready: Any,
    finish: Any,
    *,
    crash: bool,
) -> None:
    try:
        sid = WindowsCurrentIdentity().current_sid()
        factory = WindowsNamedMutexFactory(purpose=purpose)
        handle = factory.open_current_user(
            name=current_user_mutex_name(sid, purpose=purpose),
            sid=sid,
        )
        if handle.try_acquire() not in {
            MutexAcquireResult.CREATED,
            MutexAcquireResult.ACQUIRED,
        }:
            os._exit(91)
        ready.set()
        if not finish.wait(15):
            os._exit(92)
        if crash:
            os._exit(73)
        handle.release()
        handle.close()
    except BaseException:
        os._exit(93)


class _AllowTestStorage:
    def validate(self, database: Path) -> Path:
        return database.resolve(strict=False)


def _service_owner_process(
    database: str,
    ready: Any,
    finish: Any,
    fence_sender: Any,
) -> None:
    try:
        control = ServiceControl(
            Path(database),
            mode=ServiceMode.COORDINATOR,
            identity=WindowsCurrentIdentity(),
            mutex_factory=secure_windows_mutex_factory,
            storage_policy=_AllowTestStorage(),
        )
        fence = control.acquire(now=1.0)
        fence_sender.send((fence.generation, fence.owner_id))
        fence_sender.close()
        ready.set()
        if not finish.wait(15):
            os._exit(94)
        os._exit(74)
    except BaseException:
        os._exit(95)


def _spawn_owner(
    purpose: str,
    *,
    crash: bool,
) -> tuple[Any, Any, Any]:
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    finish = context.Event()
    process = context.Process(
        target=_owner_process,
        args=(purpose, ready, finish),
        kwargs={"crash": crash},
    )
    process.start()
    return process, ready, finish


def _stop_process(process: Any, finish: Any) -> None:
    finish.set()
    process.join(10)
    if process.is_alive():
        process.terminate()
        process.join(5)


def _raw_kernel32() -> Any:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32.CreateMutexW.argtypes = [
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


def test_factory_is_protocol_compatible_and_name_is_local_sid_digest() -> None:
    sid = WindowsCurrentIdentity().current_sid()
    name = current_user_mutex_name(sid)

    assert isinstance(secure_windows_mutex_factory, NamedMutexFactoryPort)
    assert name.startswith("Local\\Stockroom.Coordinator.")
    assert sid not in name
    assert len(name.rsplit(".", 1)[-1]) == 64


def test_factory_rejects_global_wrong_name_and_wrong_identity() -> None:
    sid = WindowsCurrentIdentity().current_sid()
    purpose = f"Tests.Security.{uuid.uuid4().hex}"
    factory = WindowsNamedMutexFactory(purpose=purpose)

    with pytest.raises(WindowsMutexSecurityError, match="name"):
        factory.open_current_user(name="Global\\Stockroom.Coordinator", sid=sid)

    other_sid = "S-1-5-21-4444444444-5555555555-6666666666-1002"
    with pytest.raises(WindowsMutexSecurityError, match="current identity"):
        factory.open_current_user(
            name=current_user_mutex_name(other_sid, purpose=purpose),
            sid=other_sid,
        )


def test_factory_rejects_precreated_object_without_protected_single_sid_dacl() -> None:
    sid = WindowsCurrentIdentity().current_sid()
    purpose = f"Tests.Precreated.{uuid.uuid4().hex}"
    name = current_user_mutex_name(sid, purpose=purpose)
    kernel32 = _raw_kernel32()
    raw_handle = kernel32.CreateMutexW(None, False, name)
    assert raw_handle

    try:
        with pytest.raises(WindowsMutexSecurityError, match="DACL"):
            WindowsNamedMutexFactory(purpose=purpose).open_current_user(
                name=name,
                sid=sid,
            )
    finally:
        assert kernel32.CloseHandle(raw_handle)


def test_handle_maps_acquired_prevents_recursion_and_closes_deterministically() -> None:
    sid = WindowsCurrentIdentity().current_sid()
    purpose = f"Tests.Lifecycle.{uuid.uuid4().hex}"
    factory = WindowsNamedMutexFactory(purpose=purpose)
    handle = factory.open_current_user(
        name=current_user_mutex_name(sid, purpose=purpose),
        sid=sid,
    )

    with handle:
        assert handle.try_acquire() is MutexAcquireResult.CREATED
        with pytest.raises(WindowsMutexStateError, match="recursive"):
            handle.try_acquire()

    with pytest.raises(WindowsMutexStateError, match="closed"):
        handle.try_acquire()
    handle.close()


@pytest.mark.timeout(30)
def test_real_second_process_observes_busy_until_clean_release() -> None:
    sid = WindowsCurrentIdentity().current_sid()
    purpose = f"Tests.Contention.{uuid.uuid4().hex}"
    process, ready, finish = _spawn_owner(purpose, crash=False)
    contender = None
    try:
        assert ready.wait(10), f"owner failed before ready; exit={process.exitcode}"
        factory = WindowsNamedMutexFactory(purpose=purpose)
        contender = factory.open_current_user(
            name=current_user_mutex_name(sid, purpose=purpose),
            sid=sid,
        )
        assert contender.try_acquire() is MutexAcquireResult.BUSY

        finish.set()
        process.join(10)
        assert process.exitcode == 0
        assert contender.try_acquire() is MutexAcquireResult.ACQUIRED
        contender.release()
    finally:
        _stop_process(process, finish)
        if contender is not None:
            contender.close()


@pytest.mark.timeout(30)
def test_real_crashed_owner_maps_to_abandoned_when_object_handle_survives() -> None:
    sid = WindowsCurrentIdentity().current_sid()
    purpose = f"Tests.Abandoned.{uuid.uuid4().hex}"
    factory = WindowsNamedMutexFactory(purpose=purpose)
    sentinel = factory.open_current_user(
        name=current_user_mutex_name(sid, purpose=purpose),
        sid=sid,
    )
    process, ready, finish = _spawn_owner(purpose, crash=True)
    try:
        assert ready.wait(10), f"owner failed before ready; exit={process.exitcode}"
        finish.set()
        process.join(10)
        assert process.exitcode == 73
        assert sentinel.try_acquire() is MutexAcquireResult.ABANDONED
        sentinel.release()
    finally:
        _stop_process(process, finish)
        sentinel.close()


@pytest.mark.timeout(30)
def test_real_final_handle_crash_recreates_mutex_and_fences_stale_generation(
    tmp_path: Path,
) -> None:
    database = tmp_path / "Control.sqlite"
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    finish = context.Event()
    fence_receiver, fence_sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_service_owner_process,
        args=(str(database), ready, finish, fence_sender),
    )
    process.start()
    fence_sender.close()

    reopened: ServiceControl | None = None
    new_fence: GenerationFence | None = None
    try:
        assert ready.wait(10), f"owner failed before ready; exit={process.exitcode}"
        assert fence_receiver.poll(5)
        old_generation, old_owner = fence_receiver.recv()
        old_fence = GenerationFence(old_generation, old_owner)

        finish.set()
        process.join(10)
        assert process.exitcode == 74

        reopened = ServiceControl(
            database,
            mode=ServiceMode.COORDINATOR,
            identity=WindowsCurrentIdentity(),
            mutex_factory=secure_windows_mutex_factory,
            storage_policy=_AllowTestStorage(),
        )
        new_fence = reopened.acquire(now=2.0)
        assert new_fence.generation == old_fence.generation + 1

        held_fence = reopened._held_fence
        reopened._held_fence = old_fence
        try:
            with pytest.raises(CoordinatorConflict, match="stale"):
                reopened.record_event(
                    old_fence,
                    "worker_advanced",
                    {"step": 2},
                    now=3.0,
                )
        finally:
            reopened._held_fence = held_fence

        assert [event.event_type for event in reopened.events()] == [
            "coordinator_acquired",
            "coordinator_cold_crash",
            "coordinator_acquired",
        ]
        assert reopened.events()[-1].payload == {"acquisition": "recreated"}
    finally:
        _stop_process(process, finish)
        fence_receiver.close()
        if reopened is not None and new_fence is not None:
            reopened.release(new_fence, now=4.0)
        if reopened is not None and isinstance(reopened._mutex, WindowsNamedMutexHandle):
            reopened._mutex.close()


def test_wait_failed_has_a_distinct_error_mapping() -> None:
    sid = WindowsCurrentIdentity().current_sid()
    purpose = f"Tests.WaitFailed.{uuid.uuid4().hex}"
    handle = WindowsNamedMutexFactory(purpose=purpose).open_current_user(
        name=current_user_mutex_name(sid, purpose=purpose),
        sid=sid,
    )
    kernel32 = _raw_kernel32()
    assert kernel32.CloseHandle(handle._handle)

    with pytest.raises(WindowsMutexWaitFailed) as error:
        handle.try_acquire()

    assert error.value.winerror != 0
