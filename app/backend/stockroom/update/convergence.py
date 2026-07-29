"""Bounded, observable automatic application convergence.

The desktop host owns this service for its whole lifetime. It checks immediately
after a short window-start grace period and then on a fixed interval. Failures
remain visible and are retried; no update button is required for progress.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from typing import Callable

from stockroom.api.updater import AppUpdater, UpdateResult, UpdateState


class ConvergencePhase:
    IDLE = "idle"
    CHECKING = "checking"
    CURRENT = "current"
    APPLYING = "applying"
    RELOADING_FRONTEND = "reloading_frontend"
    HANDING_OFF = "handing_off"
    RESTARTING = "restarting"
    ROLLED_BACK = "rolled_back"
    OFFLINE = "offline"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class _Snapshot:
    convergence_phase: str
    current_revision: str
    target_revision: str
    channel: str
    detail: str
    last_checked_at: float | None
    attempts: int
    automatic_on_launch: bool = True
    automatic_apply: bool = True
    check_interval_seconds: float = 120.0


class ConvergenceLoop:
    """Owned stop/join handle for the host's single convergence thread."""

    def __init__(self, stop: threading.Event, thread: threading.Thread) -> None:
        self._stop = stop
        self._thread = thread

    def set(self) -> None:
        self._stop.set()

    def is_set(self) -> bool:
        return self._stop.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._stop.wait(timeout)

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout)

    def is_alive(self) -> bool:
        return self._thread.is_alive()


class UpdateConvergenceService:
    """Continuously discover and adopt the latest verifiable application revision."""

    def __init__(
        self,
        updater: AppUpdater,
        *,
        interval_seconds: float = 120.0,
        running_revision: str = "",
        clock: Callable[[], float] = time.time,
        status_sink: Callable[[dict[str, object]], None] | None = None,
        health_interval_seconds: float = 2.0,
    ) -> None:
        if not 1 <= float(interval_seconds) <= 86400:
            raise ValueError("update convergence interval must be between 1 second and 1 day")
        self._updater = updater
        self._interval = float(interval_seconds)
        self._clock = clock
        self._status_sink = status_sink
        self._health_interval = max(0.25, min(float(health_interval_seconds), self._interval))
        revision = running_revision or updater.repo.head()
        self._snapshot = _Snapshot(
            convergence_phase=ConvergencePhase.IDLE,
            current_revision=revision[:12],
            target_revision="",
            channel=updater.repo.current_branch() or "detached",
            detail="Automatic convergence has not checked the remote yet.",
            last_checked_at=None,
            attempts=0,
            check_interval_seconds=self._interval,
        )
        self._activation_pending = False
        self._activation_frontend_only = False
        self._state_lock = threading.RLock()
        self._run_lock = threading.Lock()
        self._loop_lock = threading.Lock()
        self._loop_handle: ConvergenceLoop | None = None

    def _replace(self, **changes: object) -> None:
        with self._state_lock:
            current = asdict(self._snapshot)
            current.update(changes)
            self._snapshot = _Snapshot(**current)
        if self._status_sink is not None:
            try:
                self._status_sink(self.status())
            except OSError:
                # Status mirroring is observability only; it cannot veto an update.
                pass

    def status(self) -> dict[str, object]:
        """Return a stable API document without doing network work."""
        with self._state_lock:
            snapshot = self._snapshot
        current = snapshot.current_revision
        target = snapshot.target_revision
        verified_current = (
            snapshot.convergence_phase == ConvergencePhase.CURRENT
            and bool(current)
            and current == target
        )
        transitional = snapshot.convergence_phase in {
            ConvergencePhase.APPLYING,
            ConvergencePhase.RELOADING_FRONTEND,
            ConvergencePhase.HANDING_OFF,
            ConvergencePhase.RESTARTING,
        }
        state = (
            UpdateState.UP_TO_DATE
            if verified_current
            else UpdateState.OFFLINE
            if snapshot.convergence_phase == ConvergencePhase.OFFLINE
            else UpdateState.BLOCKED
            if snapshot.convergence_phase == ConvergencePhase.BLOCKED
            else UpdateState.UNVERIFIED
            if snapshot.convergence_phase in {ConvergencePhase.IDLE, ConvergencePhase.CHECKING}
            else ConvergencePhase.FAILED
            if snapshot.convergence_phase == ConvergencePhase.FAILED
            else ConvergencePhase.ROLLED_BACK
            if snapshot.convergence_phase == ConvergencePhase.ROLLED_BACK
            else "updating"
            if transitional
            else "update_available"
        )
        document = asdict(snapshot)
        document.update(
            {
                "state": state,
                # A failed or rolled-back adoption is not an "update ready" call to action.
                # The host owns retries automatically; the target/current fields retain the
                # diagnostic evidence without mislabelling the failure in every passive UI.
                "update_available": bool(
                    transitional and target and current != target
                ),
                "behind": 0 if verified_current else None,
            }
        )
        return document

    def _record_result(self, result: UpdateResult, target_revision: str) -> None:
        if result.updated:
            new_revision = (result.activated_revision or self._updater.repo.head())[:12]
            self._activation_pending = False
            if result.seamless_handoff_requested:
                phase = ConvergencePhase.CURRENT
                detail = "The verified release was adopted without closing the window."
            elif result.frontend_reload_requested:
                phase = ConvergencePhase.CURRENT
                detail = "The new frontend bundle was adopted without closing the window."
            else:
                phase = ConvergencePhase.RESTARTING
                detail = "The updated backend is handing off to a fresh process."
            self._replace(
                convergence_phase=phase,
                current_revision=new_revision,
                target_revision=target_revision or new_revision,
                detail=detail,
            )
            return
        phase = (
            ConvergencePhase.OFFLINE
            if result.state == UpdateState.OFFLINE
            else ConvergencePhase.BLOCKED
            if result.state in {UpdateState.BLOCKED, UpdateState.DIVERGED}
            else ConvergencePhase.FAILED
        )
        self._replace(convergence_phase=phase, detail=result.detail or result.state)

    def _record_health(self, health: object) -> bool:
        if bool(getattr(health, "ok", False)):
            return True
        revision = str(getattr(health, "revision", ""))
        rolled_back = bool(getattr(health, "rolled_back", False))
        self._replace(
            convergence_phase=(
                ConvergencePhase.ROLLED_BACK if rolled_back else ConvergencePhase.FAILED
            ),
            current_revision=revision[:12],
            detail=str(getattr(health, "detail", "active backend health check failed")),
            last_checked_at=self._clock(),
        )
        return False

    def verify_health_once(self) -> dict[str, object]:
        """Probe the active worker without fetching the remote; concurrent work coalesces."""
        if not self._run_lock.acquire(blocking=False):
            return self.status()
        try:
            health = self._updater.verify_active()
            if health is not None:
                self._record_health(health)
            return self.status()
        finally:
            self._run_lock.release()

    def run_once(self) -> dict[str, object]:
        """Perform one bounded check/apply attempt; concurrent callers coalesce."""
        if not self._run_lock.acquire(blocking=False):
            return self.status()
        try:
            with self._state_lock:
                attempts = self._snapshot.attempts + 1
            health = self._updater.verify_active()
            if health is not None and not self._record_health(health):
                self._replace(attempts=attempts)
                return self.status()
            self._replace(
                convergence_phase=ConvergencePhase.CHECKING,
                detail="Checking the application remote for the latest revision.",
                attempts=attempts,
            )
            checked = self._updater.check()
            now = self._clock()
            target = str(checked.get("target_revision", ""))
            channel = str(checked.get("channel", "detached"))
            self._replace(
                target_revision=target,
                channel=channel,
                last_checked_at=now,
                detail=str(checked.get("detail", "")),
            )

            if self._activation_pending:
                self._replace(
                    convergence_phase=ConvergencePhase.APPLYING,
                    detail="Retrying activation of the already downloaded revision.",
                )
                try:
                    result = self._updater.activate_current(
                        frontend_only=self._activation_frontend_only
                    )
                except Exception as exc:  # activation remains pending for the next interval
                    self._replace(
                        convergence_phase=ConvergencePhase.FAILED,
                        detail=f"Activation failed and will retry automatically: {exc}",
                    )
                    return self.status()
                self._record_result(result, target)
                return self.status()

            if not bool(checked.get("update_available", False)):
                state = str(checked.get("state", UpdateState.UNVERIFIED))
                phase = (
                    ConvergencePhase.CURRENT
                    if state == UpdateState.UP_TO_DATE
                    else ConvergencePhase.OFFLINE
                    if state == UpdateState.OFFLINE
                    else ConvergencePhase.BLOCKED
                )
                self._replace(
                    convergence_phase=phase,
                    current_revision=str(checked.get("current_revision", "")),
                    detail=str(checked.get("detail", ""))
                    or (
                        "The application remote confirms this installation is current."
                        if phase == ConvergencePhase.CURRENT
                        else state
                    ),
                )
                return self.status()

            self._replace(
                convergence_phase=ConvergencePhase.APPLYING,
                detail="A newer verified revision is being adopted automatically.",
            )
            before = self._updater.repo.head()
            try:
                result = self._updater.update(
                    target_revision=str(checked.get("target_revision_full", ""))
                )
            except Exception as exc:
                after = self._updater.repo.head()
                if after != before:
                    self._activation_pending = True
                    try:
                        paths = self._updater.repo.changed_paths(before, after)
                    except Exception:  # next retry safely defaults to a full process handoff
                        paths = ()
                    self._activation_frontend_only = self._updater.frontend_only(paths)
                self._replace(
                    convergence_phase=ConvergencePhase.FAILED,
                    detail=f"Activation failed and will retry automatically: {exc}",
                )
                return self.status()
            self._record_result(result, target)
            return self.status()
        finally:
            self._run_lock.release()

    def start(
        self,
        *,
        initial_delay_seconds: float = 5.0,
    ) -> ConvergenceLoop:
        """Start one stoppable daemon loop owned by the desktop host."""
        if not 0 <= float(initial_delay_seconds) <= self._interval:
            raise ValueError("initial delay must be between zero and the check interval")
        with self._loop_lock:
            if self._loop_handle is not None and self._loop_handle.is_alive():
                return self._loop_handle
            stop = threading.Event()

            def guarded(operation: Callable[[], object], label: str) -> None:
                try:
                    operation()
                except Exception as exc:  # noqa: BLE001 - daemon must remain observable and alive
                    self._replace(
                        convergence_phase=ConvergencePhase.FAILED,
                        detail=(
                            f"Automatic update {label} failed and will retry "
                            f"({type(exc).__name__})."
                        ),
                        last_checked_at=self._clock(),
                    )

            def loop() -> None:
                if stop.wait(float(initial_delay_seconds)):
                    return
                guarded(self.run_once, "check")
                next_update = time.monotonic() + self._interval
                while not stop.wait(self._health_interval):
                    now = time.monotonic()
                    if now >= next_update:
                        guarded(self.run_once, "check")
                        next_update = now + self._interval
                    else:
                        guarded(self.verify_health_once, "health check")

            thread = threading.Thread(
                target=loop,
                name="stockroom-update-convergence",
                daemon=True,
            )
            handle = ConvergenceLoop(stop, thread)
            self._loop_handle = handle
            thread.start()
            return handle
