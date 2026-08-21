"""Task-bound browser intake for provider rows without a capture adapter.

The provider page remains entirely person-operated.  This broker leases Stockroom's dedicated
provider WebView, observes its native download journal, and inspects completed files.  One exact,
unambiguous attachment is applied automatically even when other requested roles remain. Ambiguous
or identity-free packages remain the same inactive proposal used by the manual picker.
"""

from __future__ import annotations

import shutil
import threading
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, TypedDict, cast

from stockroom.ingest.manual_files import (
    apply_manual_cad_proposal,
    discard_manual_cad_proposal,
    propose_manual_cad_files,
)


class _DownloadProgressItem(TypedDict):
    name: str
    state: str
    bytes_received: int
    total_bytes: int


def _string_list(value: object) -> list[str]:
    """Narrow trusted intake results without accepting malformed collection values."""

    if type(value) is not list or any(type(item) is not str for item in value):
        raise TypeError("CAD intake result must contain a list of strings")
    return cast(list[str], value)


def _apply_complete_proposal(ctx, part_id: str, proposal_token: str) -> dict[str, object]:
    """Use the existing serialized manual-Apply mutation and publication boundary."""

    result = ctx.jobs.run_write(lambda: apply_manual_cad_proposal(ctx, part_id, proposal_token))
    warnings: list[str] = []
    if result.get("attached"):
        for label, action in (
            ("index refresh", ctx.rebuild_index),
            ("library publication", ctx.auto_push),
        ):
            try:
                ctx.jobs.run_write(action)
            except Exception:  # noqa: BLE001 - the attachment mutation is already durable
                warnings.append(label)
    outcome = dict(result)
    if warnings:
        outcome["warning"] = (
            "CAD is attached, but Stockroom could not finish the " + " and ".join(warnings) + "."
        )
    return outcome


_ROLE_BY_REQUIREMENT = (
    ("kicad_symbol", "KiCad Symbol"),
    ("kicad_footprint", "KiCad Footprint"),
    ("kicad_model", "3D Model"),
    ("altium_symbol", "Altium Symbol"),
    ("altium_footprint", "Altium Footprint"),
)


def _selected_remaining_roles(edas: tuple[str, ...], result: dict[str, object]) -> list[str]:
    selected_requirements = {"kicad_model"}
    if "kicad" in edas:
        selected_requirements.update({"kicad_symbol", "kicad_footprint"})
    if "altium" in edas:
        selected_requirements.update({"altium_symbol", "altium_footprint"})
    raw_remaining = result.get("remaining")
    remaining = (
        {value for value in raw_remaining if type(value) is str}
        if isinstance(raw_remaining, list)
        else selected_requirements
    )
    return [
        role
        for requirement, role in _ROLE_BY_REQUIREMENT
        if requirement in selected_requirements and requirement in remaining
    ]


@dataclass(frozen=True, slots=True)
class ManualProviderBrowserSnapshot:
    session_id: str
    part_id: str
    provider_id: str
    url: str
    browser_owner_id: str
    state: str
    proposal: dict[str, object] | None = None
    error: str = ""
    browser_state: dict[str, object] | None = None
    download_progress: dict[str, object] | None = None
    cad_ready: dict[str, object] | None = None


@dataclass(slots=True)
class _Session:
    snapshot: ManualProviderBrowserSnapshot
    manufacturer: str
    mpn: str
    edas: tuple[str, ...]
    staging_root: Path
    stop: threading.Event
    started: threading.Event
    started_at: float
    thread: threading.Thread | None = None
    proposal_token: str = ""
    finished_at: float | None = None
    staging_released: bool = False


class ManualProviderBrowserBroker:
    """Own one thread-bound native lease per direct provider browsing session."""

    def __init__(
        self,
        ctx,
        provider_surface,
        *,
        proposal_factory: Callable[..., dict[str, object]] = propose_manual_cad_files,
        apply_factory: Callable[..., dict[str, object]] = _apply_complete_proposal,
        proposal_discarder: Callable[[str, str], bool] = discard_manual_cad_proposal,
        root: Path,
        poll_interval: float = 0.1,
        maximum_lifetime: float = 30 * 60,
        stall_timeout: float = 30.0,
        session_retention: float = 5 * 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not callable(provider_surface):
            raise ValueError("the embedded provider browser is unavailable")
        self._ctx = ctx
        self._provider_surface = provider_surface
        self._proposal_factory = proposal_factory
        self._apply_factory = apply_factory
        self._proposal_discarder = proposal_discarder
        requested_root = Path(root)
        requested_root.mkdir(parents=True, exist_ok=True)
        if requested_root.is_symlink() or not requested_root.is_dir():
            raise ValueError("manual provider browser root must be a real directory")
        self._root = requested_root.resolve(strict=True)
        self._poll_interval = poll_interval
        self._maximum_lifetime = maximum_lifetime
        self._stall_timeout = stall_timeout
        self._session_retention = session_retention
        self._clock = clock
        if (
            poll_interval <= 0
            or maximum_lifetime <= 0
            or stall_timeout <= 0
            or session_retention <= 0
        ):
            raise ValueError("manual provider browser timing must be positive")
        self._lock = threading.RLock()
        self._start_lock = threading.Lock()
        self._sessions: dict[str, _Session] = {}
        self._active_by_part: dict[str, str] = {}
        self._shutdown = False

    def start(
        self,
        *,
        session_id: str,
        part_id: str,
        manufacturer: str,
        mpn: str,
        provider_id: str,
        url: str,
        edas: tuple[str, ...],
        browser_owner_id: str,
    ) -> ManualProviderBrowserSnapshot:
        try:
            parsed_session = uuid.UUID(session_id)
        except (ValueError, AttributeError) as exc:
            raise ValueError("manual provider browser session id is invalid") from exc
        if str(parsed_session) != session_id:
            raise ValueError("manual provider browser session id is invalid")
        if not all(
            type(value) is str and value and value == value.strip() and len(value) <= 512
            for value in (part_id, manufacturer, mpn, provider_id, url, browser_owner_id)
        ):
            raise ValueError("manual provider browser identity is invalid")
        if not edas or len(set(edas)) != len(edas) or set(edas) - {"kicad", "altium"}:
            raise ValueError("manual provider browser EDA selection is invalid")

        self.cleanup_expired()
        with self._start_lock:
            prior: _Session | None = None
            with self._lock:
                if self._shutdown:
                    raise RuntimeError("the manual provider browser broker is shut down")
                if session_id in self._sessions:
                    raise ValueError("manual provider browser session already exists")
                prior_id = self._active_by_part.get(part_id)
                if prior_id is not None:
                    prior = self._sessions.get(prior_id)
                    if prior is not None:
                        prior.snapshot = replace(prior.snapshot, state="replaced")
                        prior.stop.set()
            if prior is not None and prior.thread is not None:
                prior.thread.join(timeout=5.0)
                if prior.thread.is_alive():
                    raise RuntimeError("the previous provider browser did not release its lease")

            staging_root = (self._root / session_id).resolve(strict=False)
            if staging_root.parent != self._root:
                raise ValueError("manual provider browser staging root is invalid")
            try:
                staging_root.mkdir(exist_ok=False)
            except FileExistsError as exc:
                raise RuntimeError(
                    "manual provider browser staging root already exists and is not owned by "
                    "this session"
                ) from exc
            snapshot = ManualProviderBrowserSnapshot(
                session_id=session_id,
                part_id=part_id,
                provider_id=provider_id,
                url=url,
                browser_owner_id=browser_owner_id,
                state="starting",
            )
            session = _Session(
                snapshot=snapshot,
                manufacturer=manufacturer,
                mpn=mpn,
                edas=edas,
                staging_root=staging_root,
                stop=threading.Event(),
                started=threading.Event(),
                started_at=self._clock(),
            )
            thread = threading.Thread(
                target=self._run,
                args=(session,),
                name=f"Stockroom Manual Provider {session_id}",
                daemon=True,
            )
            session.thread = thread
            with self._lock:
                self._sessions[session_id] = session
                self._active_by_part[part_id] = session_id
            thread.start()
            if not session.started.wait(timeout=min(5.0, self._stall_timeout)):
                with self._lock:
                    if session.snapshot.state == "starting":
                        session.snapshot = replace(
                            session.snapshot,
                            state="stalled",
                            error=(
                                "Provider opening stalled. Retry, choose another provider, or "
                                "close the browser."
                            ),
                        )
            return self.status(session_id)

    def cleanup_expired(self) -> int:
        """Expire live sessions and prune terminal metadata using the injected monotonic clock."""

        now = self._clock()
        due: list[threading.Thread] = []
        with self._lock:
            for session in self._sessions.values():
                if (
                    session.finished_at is None
                    and session.snapshot.state
                    not in {"replaced", "failed", "expired", "closed", "ready"}
                    and now - session.started_at >= self._maximum_lifetime
                ):
                    session.snapshot = replace(session.snapshot, state="expired")
                    session.stop.set()
                    if session.thread is not None:
                        due.append(session.thread)
        for thread in due:
            if thread is not threading.current_thread():
                thread.join(timeout=5.0)
        with self._lock:
            expired_ids = [
                session_id
                for session_id, session in self._sessions.items()
                if session.finished_at is not None
                and now - session.finished_at >= self._session_retention
            ]
            for session_id in expired_ids:
                session = self._sessions.pop(session_id)
                if self._active_by_part.get(session.snapshot.part_id) == session_id:
                    self._active_by_part.pop(session.snapshot.part_id, None)
            return len(expired_ids)

    def status(self, session_id: str) -> ManualProviderBrowserSnapshot:
        self.cleanup_expired()
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError("manual provider browser session does not exist")
            if (
                session.snapshot.state == "starting"
                and self._clock() - session.started_at >= self._stall_timeout
            ):
                session.snapshot = replace(
                    session.snapshot,
                    state="stalled",
                    error=(
                        "Provider opening stalled. Retry, choose another provider, or close "
                        "the browser."
                    ),
                )
            return replace(session.snapshot)

    def stop(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            if session.snapshot.state not in {"replaced", "failed", "expired", "closed", "ready"}:
                session.snapshot = replace(session.snapshot, state="closed")
            session.stop.set()
            thread = session.thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5.0)
        released = bool(thread is None or not thread.is_alive())
        if released:
            self._release_session(session)
        return released and session.staging_released

    def stop_part(self, part_id: str) -> bool:
        with self._lock:
            session_id = self._active_by_part.get(part_id)
        return bool(session_id and self.stop(session_id))

    def shutdown(self) -> None:
        """Release every lease and exact session-owned staging root, then reject new work."""

        with self._start_lock:
            with self._lock:
                if self._shutdown:
                    return
                self._shutdown = True
                sessions = list(self._sessions.values())
                for session in sessions:
                    if session.snapshot.state not in {
                        "replaced",
                        "failed",
                        "expired",
                        "closed",
                        "ready",
                    }:
                        session.snapshot = replace(session.snapshot, state="closed")
                    session.stop.set()
            for session in sessions:
                thread = session.thread
                if thread is not None and thread is not threading.current_thread():
                    thread.join(timeout=5.0)
                if thread is None or not thread.is_alive():
                    self._release_session(session)
            with self._lock:
                alive = [
                    session.snapshot.session_id
                    for session in sessions
                    if (
                        session.thread is not None and session.thread.is_alive()
                    )
                    or not session.staging_released
                ]
                if not alive:
                    self._sessions.clear()
                    self._active_by_part.clear()
            if alive:
                raise RuntimeError(
                    "manual provider browser shutdown could not release sessions: "
                    + ", ".join(alive)
                )

    def _discard_proposal(self, session: _Session, proposal_token: str) -> None:
        if not proposal_token:
            return
        try:
            self._proposal_discarder(session.snapshot.part_id, proposal_token)
        except Exception as exc:  # noqa: BLE001 - staging cleanup must still finish
            with self._lock:
                message = f"Staged proposal cleanup did not finish: {exc}"
                session.snapshot = replace(
                    session.snapshot,
                    error=(session.snapshot.error + " " + message).strip(),
                )

    def _replace_proposal_token(self, session: _Session, proposal_token: str) -> None:
        with self._lock:
            previous = session.proposal_token
            session.proposal_token = proposal_token
        if previous and previous != proposal_token:
            self._discard_proposal(session, previous)

    def _release_session(self, session: _Session) -> None:
        with self._lock:
            if session.staging_released:
                return
            proposal_token = session.proposal_token
            session.proposal_token = ""
        self._discard_proposal(session, proposal_token)
        cleanup_error = ""
        staging_root = session.staging_root
        if (
            staging_root.parent != self._root
            or staging_root.name != session.snapshot.session_id
        ):
            cleanup_error = "Session staging ownership changed; temporary evidence was not deleted."
        else:
            try:
                if staging_root.is_symlink():
                    staging_root.unlink(missing_ok=True)
                elif staging_root.exists():
                    shutil.rmtree(staging_root)
            except OSError as exc:
                cleanup_error = f"Temporary evidence cleanup did not finish: {exc}"
        with self._lock:
            if cleanup_error:
                session.snapshot = replace(
                    session.snapshot,
                    error=(session.snapshot.error + " " + cleanup_error).strip(),
                )
            else:
                session.staging_released = True
                session.finished_at = self._clock()
            if self._active_by_part.get(session.snapshot.part_id) == session.snapshot.session_id:
                self._active_by_part.pop(session.snapshot.part_id, None)

    def _run(self, session: _Session) -> None:
        cursor = 0
        landed: list[Path] = []
        progress_items: dict[str, _DownloadProgressItem] = {}
        last_download_progress = self._clock()
        last_navigation_progress = self._clock()
        prior_browser_state: dict[str, object] | None = None
        stalled_for = ""
        deadline = session.started_at + self._maximum_lifetime
        try:
            with self._provider_surface(
                staging_root=str(session.staging_root),
                component_id=session.snapshot.browser_owner_id,
                manufacturer=session.manufacturer,
                mpn=session.mpn,
                provider_id=session.snapshot.provider_id,
            ) as lease:
                lease.navigate(session.snapshot.url)
                lease.show()
                state_reader = getattr(lease, "state", None)
                initial_browser_state = state_reader() if callable(state_reader) else None
                with self._lock:
                    if session.snapshot.state in {"starting", "stalled"}:
                        session.snapshot = replace(
                            session.snapshot,
                            state="active",
                            browser_state=initial_browser_state,
                            error="",
                        )
                session.started.set()
                while not session.stop.wait(self._poll_interval):
                    now = self._clock()
                    if now >= deadline:
                        with self._lock:
                            session.snapshot = replace(session.snapshot, state="expired")
                        break
                    events = lease.download_events(after_sequence=cursor)
                    if callable(state_reader):
                        try:
                            browser_state = state_reader()
                        except Exception:  # noqa: BLE001 - navigation state is advisory
                            browser_state = None
                        if isinstance(browser_state, dict):
                            if browser_state != prior_browser_state:
                                last_navigation_progress = now
                                prior_browser_state = browser_state.copy()
                            with self._lock:
                                session.snapshot = replace(
                                    session.snapshot,
                                    browser_state=browser_state,
                                )
                            if browser_state.get("navigation_error"):
                                stalled_for = "navigation"
                                with self._lock:
                                    session.snapshot = replace(
                                        session.snapshot,
                                        state="stalled",
                                        error=(
                                            "Provider navigation stopped. Retry, choose another "
                                            "provider, or close the browser."
                                        ),
                                    )
                            elif (
                                browser_state.get("loading") is True
                                and now - last_navigation_progress >= self._stall_timeout
                            ):
                                stalled_for = "navigation"
                                with self._lock:
                                    session.snapshot = replace(
                                        session.snapshot,
                                        state="stalled",
                                        error=(
                                            "Provider navigation stalled. Retry, choose another "
                                            "provider, or close the browser."
                                        ),
                                    )
                            elif stalled_for == "navigation" and not browser_state.get("loading"):
                                stalled_for = ""
                                with self._lock:
                                    session.snapshot = replace(
                                        session.snapshot,
                                        state="active",
                                        error="",
                                    )
                    changed = False
                    for event in events:
                        cursor = max(cursor, event.sequence)
                        if event.phase not in {"started", "progress", "terminal"}:
                            continue
                        item_state = event.state if event.state in {
                            "in_progress", "completed", "interrupted", "unknown"
                        } else "unknown"
                        progress_items[event.operation_id] = {
                            "name": event.suggested_file_name or "CAD download",
                            "state": item_state,
                            "bytes_received": max(0, event.bytes_received),
                            "total_bytes": event.total_bytes if event.total_bytes >= -1 else -1,
                        }
                        last_download_progress = now
                        if stalled_for == "download":
                            stalled_for = ""
                            with self._lock:
                                session.snapshot = replace(session.snapshot, state="active", error="")
                        if event.phase != "terminal" or event.state != "completed":
                            continue
                        path = Path(event.result_file_path).resolve(strict=False)
                        if (
                            path.parent != session.staging_root
                            or not path.is_file()
                            or path.is_symlink()
                            or path in landed
                        ):
                            continue
                        landed.append(path)
                        changed = True
                    if progress_items:
                        files = list(progress_items.values())
                        known_totals = [
                            item["total_bytes"]
                            for item in files
                            if item["total_bytes"] >= 0
                        ]
                        progress = {
                            "active": sum(
                                item["state"] in {"in_progress", "unknown"} for item in files
                            ),
                            "completed": sum(item["state"] == "completed" for item in files),
                            "bytes_received": sum(item["bytes_received"] for item in files),
                            "total_bytes": (
                                sum(known_totals) if len(known_totals) == len(files) else -1
                            ),
                            "files": files,
                        }
                        with self._lock:
                            session.snapshot = replace(
                                session.snapshot,
                                download_progress=progress,
                            )
                        if (
                            progress["active"]
                            and now - last_download_progress >= self._stall_timeout
                        ):
                            stalled_for = "download"
                            with self._lock:
                                session.snapshot = replace(
                                    session.snapshot,
                                    state="stalled",
                                    error=(
                                        "The provider download stalled. Retry, choose another "
                                        "provider, or close the browser."
                                    ),
                                )
                    if not changed:
                        continue
                    try:
                        proposal = self._proposal_factory(
                            self._ctx,
                            session.snapshot.part_id,
                            tuple(landed),
                            edas=session.edas,
                        )
                    except Exception as exc:  # noqa: BLE001 - browser remains usable after intake
                        with self._lock:
                            session.snapshot = replace(
                                session.snapshot,
                                error=f"Downloaded files could not be inspected: {exc}",
                            )
                    else:
                        raw_proposal_token = proposal.get("proposal_token")
                        if type(raw_proposal_token) is not str or not raw_proposal_token:
                            with self._lock:
                                session.snapshot = replace(
                                    session.snapshot,
                                    error="Downloaded files produced no reviewable proposal.",
                                )
                            continue
                        proposal_token = raw_proposal_token
                        self._replace_proposal_token(session, proposal_token)
                        if proposal.get("automatic_apply_ready") is True:
                            try:
                                result = self._apply_factory(
                                    self._ctx,
                                    session.snapshot.part_id,
                                    proposal_token,
                                )
                            except Exception as exc:  # noqa: BLE001 - retain the safe review path
                                with self._lock:
                                    session.snapshot = replace(
                                        session.snapshot,
                                        proposal=proposal,
                                        error=(
                                            "Automatic attachment did not finish. Review and Apply "
                                            f"the staged proposal: {exc}"
                                        ),
                                    )
                            else:
                                with self._lock:
                                    # Apply consumes the proposal before copying reviewed bytes into
                                    # durable library-owned assets.
                                    session.proposal_token = ""
                                selected_remaining = _selected_remaining_roles(session.edas, result)
                                warning = str(result.get("warning", "") or "")
                                cad_ready = {
                                    "attached": _string_list(result.get("attached", [])),
                                    "edas": list(session.edas),
                                    "landed_files": _string_list(
                                        proposal.get("landed_files", [])
                                    ),
                                    "part_complete": bool(result.get("complete")),
                                    "provider_id": session.snapshot.provider_id,
                                    "remaining_roles": selected_remaining,
                                }
                                if warning:
                                    cad_ready["warning"] = warning
                                message = warning
                                if selected_remaining:
                                    message = (
                                        "Downloaded files added. Still needed: "
                                        + ", ".join(selected_remaining)
                                        + "."
                                    )
                                    if warning:
                                        message += " " + warning
                                with self._lock:
                                    session.snapshot = replace(
                                        session.snapshot,
                                        state="ready",
                                        proposal=None,
                                        cad_ready=cad_ready,
                                        error=message,
                                    )
                                break
                        else:
                            with self._lock:
                                session.snapshot = replace(
                                    session.snapshot,
                                    proposal=proposal,
                                    error="",
                                )
        except Exception as exc:  # noqa: BLE001 - expose a bounded browser failure to the UI
            with self._lock:
                if session.snapshot.state not in {"replaced", "closed", "ready"}:
                    session.snapshot = replace(
                        session.snapshot,
                        state="failed",
                        error=f"The provider browser could not start: {exc}",
                    )
        finally:
            session.started.set()
            self._release_session(session)


__all__ = ["ManualProviderBrowserBroker", "ManualProviderBrowserSnapshot"]
