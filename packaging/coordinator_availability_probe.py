"""Fail fast when Windows packaging cannot acquire service authority.

This probe is advisory. It releases the current-SID ``Coordinator`` mutex
immediately, so another process can acquire it before the packaged runtime
starts. The runtime's own generation-fenced acquisition remains authoritative.
"""

from __future__ import annotations

import sys

from stockroom.service import (
    CurrentIdentityPort,
    MutexAcquireResult,
    NamedMutexFactoryPort,
    WindowsCurrentIdentity,
    current_user_mutex_name,
    secure_windows_mutex_factory,
)


class CoordinatorAvailabilityProbeError(RuntimeError):
    """The packaging preflight could not prove coordinator availability."""


class CoordinatorUnavailable(CoordinatorAvailabilityProbeError):
    """Another process currently owns the production coordinator mutex."""


def probe_coordinator_availability(
    *,
    identity: CurrentIdentityPort | None = None,
    mutex_factory: NamedMutexFactoryPort | None = None,
) -> MutexAcquireResult:
    """Claim, release, and close the exact production coordinator mutex once.

    ``CREATED``, ordinary ``ACQUIRED``, and ``ABANDONED`` claims are all
    available after release. ``BUSY`` fails without waiting. This is only an
    early resource check; it is deliberately not a substitute for the
    runtime's authoritative acquisition.
    """

    if identity is None:
        if sys.platform != "win32":
            raise CoordinatorAvailabilityProbeError(
                "Stockroom coordinator availability can only be verified on Windows."
            )
        identity = WindowsCurrentIdentity()
    if mutex_factory is None:
        mutex_factory = secure_windows_mutex_factory

    sid = identity.current_sid()
    handle = mutex_factory.open_current_user(
        name=current_user_mutex_name(sid),
        sid=sid,
    )
    acquired = False
    try:
        result = handle.try_acquire()
        if result is MutexAcquireResult.BUSY:
            raise CoordinatorUnavailable(
                "Another Stockroom instance owns coordinator authority in this Windows "
                "session. Close that instance, then rerun the package build."
            )
        if result not in {
            MutexAcquireResult.CREATED,
            MutexAcquireResult.ACQUIRED,
            MutexAcquireResult.ABANDONED,
        }:
            raise CoordinatorAvailabilityProbeError(
                "The Windows coordinator mutex returned an invalid availability result."
            )
        acquired = True
        return result
    finally:
        try:
            if acquired:
                handle.release()
        finally:
            close = getattr(handle, "close", None)
            if not callable(close):
                raise CoordinatorAvailabilityProbeError(
                    "The Windows coordinator mutex handle cannot be closed."
                )
            close()


def main() -> int:
    try:
        result = probe_coordinator_availability()
    except CoordinatorUnavailable as exc:
        print(f"Stockroom coordinator preflight failed: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001 - top-level packaging failure boundary
        print(
            f"Stockroom coordinator availability could not be verified: {exc}",
            file=sys.stderr,
        )
        return 2

    print(
        "Stockroom coordinator preflight is available "
        f"({result.value}). This advisory claim was released; the runtime will "
        "recheck authority."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
