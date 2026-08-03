"""Production composition for release-owned native Stockroom windows.

The lower layers deliberately stay separate:

* :mod:`window_supervisor` owns the same-user pipe and exact child process;
* :mod:`window_handoff` owns the reversible ordering and two-phase receipt;
* this module binds both to accepted immutable releases and durable UI state.

There is no legacy pywebview fallback here.  An accepted release must declare
the native ``window-host`` member, the renderer must export its exact durable
session and live physical geometry, and both renderer-side API probes must be
healthy.  Any missing or invented value fails before the old window is hidden.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from stockroom.host.window_geometry import (
    WindowGeometry,
    set_machine_config_window_geometry,
)
from stockroom.host.window_handoff import (
    ManagedWindowHandoff,
    WindowCandidate,
    WindowContinuity,
    WindowHandoffAdoption,
    WindowHandoffPorts,
    WindowHandoffReceipt,
    WindowProof,
)
from stockroom.host.window_supervisor import (
    ProviderDownloadEvent,
    ProviderLeaseHandshake,
    WindowHostClient,
    WindowHostHealth,
    WindowHostIdentity,
    WindowHostLaunch,
    WindowHostSupervisor,
)
from stockroom.store.machine_config import MachineConfig
from stockroom.store.ui_session import (
    load_draft,
    normalize_snapshot,
    persist_export_envelope,
)
from stockroom.update import AcceptedRelease

_EXPORT_KEYS = frozenset(
    {
        "ui_export",
        "theme",
        "api_healthy",
        "event_stream_healthy",
        "geometry",
    }
)
_UI_EXPORT_REQUIRED_KEYS = frozenset({"snapshot"})
_UI_EXPORT_OPTIONAL_KEYS = frozenset({"intake_draft"})
_THEMES = frozenset({"dark", "light"})
_WAIT_POLL_SECONDS = 0.2


class ReleaseWindowRuntimeError(RuntimeError):
    """A release-owned window could not prove a coherent durable state."""


class WindowClientPort(Protocol):
    @property
    def identity(self): ...

    @property
    def active(self) -> bool: ...

    def prepare_hidden(self) -> None: ...

    def show(self) -> None: ...

    def focus(self) -> None: ...

    def provider_endpoint(self) -> str: ...

    def begin_provider_lease(self, lease_id: str) -> ProviderLeaseHandshake: ...

    def release_provider_lease(self, lease_id: str, generation: int) -> bool: ...

    def provider_download_events(
        self,
        lease_id: str,
        generation: int,
        *,
        after_sequence: int = 0,
    ) -> tuple[ProviderDownloadEvent, ...]: ...

    def show_provider(self, lease_id: str, generation: int) -> None: ...

    def hide_provider(self, lease_id: str, generation: int) -> None: ...

    def provider_current_url(self, lease_id: str, generation: int) -> str: ...

    def navigate_provider(self, lease_id: str, generation: int, url: str) -> None: ...

    def provider_document_state(
        self,
        lease_id: str,
        generation: int,
        *,
        ready_selectors: tuple[str, ...] = (),
        ready_texts: tuple[str, ...] = (),
    ) -> dict[str, object]: ...

    def health(self) -> WindowHostHealth: ...

    def export_session(self) -> object: ...

    def shutdown(self) -> None: ...

    def close(self) -> None: ...

    def wait_for_exit(self, timeout: float | None = None) -> int | None: ...


class WindowSupervisorPort(Protocol):
    def launch(
        self,
        launch: WindowHostLaunch,
        *,
        handoff_id: str,
        base_url: str,
        api_credential: str,
    ) -> WindowClientPort: ...


@dataclass(frozen=True, slots=True)
class NativeWindowExport:
    """Strict renderer/native observation used to build a handoff proof."""

    snapshot: dict
    theme: str
    api_healthy: bool
    event_stream_healthy: bool
    geometry: WindowGeometry


@dataclass(frozen=True, slots=True)
class NativeWindowObservation:
    """One read-only observation of the currently active native window."""

    identity: WindowHostIdentity
    health: WindowHostHealth
    exported: NativeWindowExport


@dataclass(slots=True)
class ProviderBrowserLease:
    """A hidden, verified provider surface that becomes visible only when armed."""

    endpoint: str
    lease_id: str
    generation: int
    _show: Callable[[str, int], None]
    _hide: Callable[[str, int], None]
    _current_url: Callable[[str, int], str]
    _navigate: Callable[[str, int, str], None]
    _document_state: Callable[..., dict[str, object]]
    _download_events: Callable[..., tuple[ProviderDownloadEvent, ...]]
    _retained: bool = False

    def show(self) -> None:
        # Visibility can also change from the native header's Return To Stockroom control.
        # Always forward the idempotent host command instead of trusting process-local state
        # that the native window cannot update.
        self._show(self.lease_id, self.generation)

    def hide(self) -> None:
        self._hide(self.lease_id, self.generation)

    def current_url(self) -> str:
        return self._current_url(self.lease_id, self.generation)

    def navigate(self, url: str) -> None:
        self._navigate(self.lease_id, self.generation, url)

    def document_state(
        self,
        *,
        ready_selectors: tuple[str, ...] = (),
        ready_texts: tuple[str, ...] = (),
    ) -> dict[str, object]:
        return self._document_state(
            self.lease_id,
            self.generation,
            ready_selectors=ready_selectors,
            ready_texts=ready_texts,
        )

    def security_state(self) -> dict[str, object]:
        state = self.document_state()
        return {
            "ready": bool(state.get("ready")),
            "challenge": bool(state.get("challenge")),
            "account_verification": bool(state.get("account_verification")),
        }

    def download_events(
        self,
        *,
        after_sequence: int = 0,
    ) -> tuple[ProviderDownloadEvent, ...]:
        return self._download_events(
            self.lease_id,
            self.generation,
            after_sequence=after_sequence,
        )

    def retain(self) -> None:
        """Keep this exact provider document available after automation disconnects."""

        self._retained = True


def _strict_mapping(
    value: object,
    *,
    label: str,
    keys: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> dict[str, object]:
    if type(value) is not dict:
        raise ReleaseWindowRuntimeError(f"{label} is invalid")
    mapping = cast(dict[object, object], value)
    if any(type(key) is not str for key in mapping):
        raise ReleaseWindowRuntimeError(f"{label} is invalid")
    typed = cast(dict[str, object], mapping)
    actual = frozenset(typed)
    if not keys.issubset(actual) or not actual.issubset(keys | optional):
        raise ReleaseWindowRuntimeError(f"{label} fields are invalid")
    return typed


def _parse_export(value: object) -> NativeWindowExport:
    outer = _strict_mapping(value, label="native window export", keys=_EXPORT_KEYS)
    ui_export = _strict_mapping(
        outer["ui_export"],
        label="native UI export",
        keys=_UI_EXPORT_REQUIRED_KEYS,
        optional=_UI_EXPORT_OPTIONAL_KEYS,
    )
    # A hidden candidate cannot acquire new keystrokes.  Its export must point
    # at the already-persisted immutable draft rather than trying to stage a new
    # revision during a health probe.
    if ui_export.get("intake_draft") is not None:
        raise ReleaseWindowRuntimeError(
            "candidate window exported an unpersisted intake draft"
        )
    try:
        snapshot = normalize_snapshot(ui_export["snapshot"])
        geometry = WindowGeometry.from_config(outer["geometry"])
    except (TypeError, ValueError) as exc:
        raise ReleaseWindowRuntimeError("native window export values are invalid") from exc
    theme = outer["theme"]
    if type(theme) is not str or theme not in _THEMES:
        raise ReleaseWindowRuntimeError("native window theme is invalid")
    api_healthy = outer["api_healthy"]
    event_stream_healthy = outer["event_stream_healthy"]
    if type(api_healthy) is not bool or type(event_stream_healthy) is not bool:
        raise ReleaseWindowRuntimeError("native window health values are invalid")
    return NativeWindowExport(
        snapshot=snapshot,
        theme=theme,
        api_healthy=api_healthy,
        event_stream_healthy=event_stream_healthy,
        geometry=geometry,
    )


def _canonical_digest(value: object) -> str:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReleaseWindowRuntimeError("window continuity is not canonical JSON") from exc
    return hashlib.sha256(payload).hexdigest()


def _session_document(snapshot: dict, config: MachineConfig) -> dict[str, object]:
    draft = None
    ref = snapshot["intake_draft_ref"]
    if ref is not None:
        try:
            draft = load_draft(ref["draft_id"], ref["revision"], config)
        except (FileNotFoundError, ValueError) as exc:
            raise ReleaseWindowRuntimeError(
                "window continuity references an invalid intake draft"
            ) from exc
    return {"snapshot": snapshot, "intake_draft": draft}


def _continuity_from_export(
    exported: NativeWindowExport,
    *,
    config: MachineConfig,
) -> WindowContinuity:
    session_document = _session_document(exported.snapshot, config)
    selected_ids = exported.snapshot["selected_ids"]
    return WindowContinuity(
        session_digest=_canonical_digest(session_document),
        geometry=exported.geometry,
        theme=exported.theme,
        route=exported.snapshot["route"],
        selected_ids_digest=_canonical_digest(selected_ids),
        workflow_batch=selected_ids["workflow_batch"],
        event_sequence=exported.snapshot["event_sequence"],
    )


class SupervisorWindowHandoffPorts(WindowHandoffPorts):
    """Bind accepted releases and typed supervisor clients to handoff ordering."""

    def __init__(
        self,
        initial_release: AcceptedRelease,
        *,
        public_base_url: str,
        api_credential: str,
        config: MachineConfig,
        supervisor: WindowSupervisorPort | None = None,
        launch_factory: Callable[[AcceptedRelease], WindowHostLaunch] = (
            WindowHostLaunch.from_release
        ),
        id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        if not isinstance(initial_release, AcceptedRelease):
            raise TypeError("initial_release must be an AcceptedRelease")
        if (
            type(public_base_url) is not str
            or not public_base_url.startswith("http://127.0.0.1:")
        ):
            raise ValueError("public_base_url must be an IPv4 loopback origin")
        if type(api_credential) is not str or not api_credential:
            raise ValueError("api_credential must not be empty")
        if not isinstance(config, MachineConfig):
            raise TypeError("config must be a MachineConfig")
        if not callable(launch_factory) or not callable(id_factory):
            raise TypeError("window runtime factories must be callable")

        self._public_base_url = public_base_url.rstrip("/")
        self._api_credential = api_credential
        self._config = config
        self._supervisor = supervisor or WindowHostSupervisor()
        self._launch_factory = launch_factory
        self._id_factory = id_factory
        self._releases = {initial_release.release_id: initial_release}
        self._active: WindowClientPort | None = None
        self._candidate_clients: dict[WindowCandidate, WindowClientPort] = {}
        self._retiring: WindowClientPort | None = None
        self._closed = False
        self._lock = threading.RLock()

    @property
    def active_release_id(self) -> str | None:
        with self._lock:
            return None if self._active is None else self._active.identity.release_id

    def register_release(self, release: AcceptedRelease) -> None:
        if not isinstance(release, AcceptedRelease):
            raise TypeError("release must be an AcceptedRelease")
        with self._lock:
            if self._closed:
                raise ReleaseWindowRuntimeError("window runtime is closed")
            existing = self._releases.get(release.release_id)
            if existing is not None and (
                existing.directory != release.directory
                or existing.manifest_sha256 != release.manifest_sha256
            ):
                raise ReleaseWindowRuntimeError(
                    "release ID names a different accepted window set"
                )
            self._releases[release.release_id] = release

    def _launch(
        self,
        release: AcceptedRelease,
        *,
        handoff_id: str,
    ) -> WindowClientPort:
        launch = self._launch_factory(release)
        return self._supervisor.launch(
            launch,
            handoff_id=handoff_id,
            base_url=self._public_base_url,
            api_credential=self._api_credential,
        )

    def _client_for(self, candidate: WindowCandidate) -> WindowClientPort:
        try:
            return self._candidate_clients[candidate]
        except KeyError as exc:
            raise ReleaseWindowRuntimeError("window candidate is not owned") from exc

    def _persist_active_export(self, raw: object) -> NativeWindowExport:
        outer = _strict_mapping(raw, label="native window export", keys=_EXPORT_KEYS)
        ui_export = outer["ui_export"]
        if ui_export is None:
            raise ReleaseWindowRuntimeError("active window has no UI export hook")
        # Persist last-keystroke state first.  Unlike a candidate probe, the
        # active export may legitimately carry one pending intake draft.
        try:
            snapshot = persist_export_envelope(ui_export, self._config)
            reloaded = self._config.reload(migrate_credentials=False)
            geometry = WindowGeometry.from_config(outer["geometry"])
        except (TypeError, ValueError) as exc:
            raise ReleaseWindowRuntimeError(
                "active window continuity could not be persisted"
            ) from exc
        theme = outer["theme"]
        if type(theme) is not str or theme not in _THEMES:
            raise ReleaseWindowRuntimeError("active window theme is invalid")
        if outer["api_healthy"] is not True or outer["event_stream_healthy"] is not True:
            raise ReleaseWindowRuntimeError("active window renderer is not healthy")

        set_machine_config_window_geometry(reloaded, geometry)
        reloaded.ui = {**reloaded.ui, "theme": theme}
        try:
            source_path = reloaded.source_path
            if source_path is None:
                raise ReleaseWindowRuntimeError(
                    "managed window configuration has no durable source"
                )
            reloaded.save(source_path)
        except (OSError, ValueError) as exc:
            raise ReleaseWindowRuntimeError(
                "active window geometry could not be persisted"
            ) from exc
        self._config = reloaded
        return NativeWindowExport(
            snapshot=snapshot,
            theme=theme,
            api_healthy=True,
            event_stream_healthy=True,
            geometry=geometry,
        )

    def _proof(
        self,
        client: WindowClientPort,
        continuity: WindowContinuity,
    ) -> WindowProof:
        health = client.health()
        if health.window_handle != client.identity.window_handle:
            raise ReleaseWindowRuntimeError("window health HWND changed")
        exported = _parse_export(client.export_session())
        observed = _continuity_from_export(exported, config=self._config)
        if observed != continuity:
            raise ReleaseWindowRuntimeError(
                "candidate did not reproduce durable window continuity"
            )
        return WindowProof(
            release_id=client.identity.release_id,
            process_id=client.identity.process_id,
            window_handle=client.identity.window_handle,
            session_digest=observed.session_digest,
            geometry=observed.geometry,
            theme=observed.theme,
            route=observed.route,
            selected_ids_digest=observed.selected_ids_digest,
            workflow_batch=observed.workflow_batch,
            event_sequence=observed.event_sequence,
            hidden=health.hidden,
            visible=health.visible,
            api_healthy=exported.api_healthy,
            event_stream_healthy=exported.event_stream_healthy,
        )

    def start_initial(self, release: AcceptedRelease) -> WindowContinuity:
        """Start the selected accepted release hidden, prove it, then show it."""

        self.register_release(release)
        with self._lock:
            if self._active is not None:
                raise ReleaseWindowRuntimeError("initial window is already running")
            client = self._launch(release, handoff_id=self._id_factory())
        try:
            client.prepare_hidden()
            hidden_health = client.health()
            if not hidden_health.hidden or hidden_health.visible:
                raise ReleaseWindowRuntimeError("initial window did not stay hidden")
            continuity = _continuity_from_export(
                self._persist_active_export(client.export_session()),
                config=self._config,
            )
            client.show()
            client.focus()
            proof = self._proof(client, continuity)
            if not proof.visible or proof.hidden:
                raise ReleaseWindowRuntimeError("initial window did not become visible")
        except BaseException:
            client.close()
            raise
        with self._lock:
            self._active = client
        return continuity

    def capture_continuity(self) -> WindowContinuity:
        with self._lock:
            client = self._active
        if client is None or not client.active:
            raise ReleaseWindowRuntimeError("active native window is unavailable")
        exported = self._persist_active_export(client.export_session())
        return _continuity_from_export(exported, config=self._config)

    def observe_active(self) -> NativeWindowObservation:
        """Read the active child's exact identity, health, and sanitized export."""

        with self._lock:
            client = self._active
        if client is None or not client.active:
            raise ReleaseWindowRuntimeError("active native window is unavailable")
        identity = client.identity
        if type(identity) is not WindowHostIdentity:
            raise ReleaseWindowRuntimeError("active native window identity is invalid")
        health = client.health()
        if (
            health.window_handle != identity.window_handle
            or health.renderer != identity.renderer
        ):
            raise ReleaseWindowRuntimeError("active native window identity changed")
        exported = _parse_export(client.export_session())
        return NativeWindowObservation(
            identity=identity,
            health=health,
            exported=exported,
        )

    def begin_provider_browser_lease(self, lease_id: str) -> ProviderLeaseHandshake:
        """Fence the active window's hidden provider browser to one capture."""

        with self._lock:
            client = self._active
        if client is None or not client.active:
            raise ReleaseWindowRuntimeError(
                "active native provider browser is unavailable"
            )
        return client.begin_provider_lease(lease_id)

    def release_provider_browser_lease(self, lease_id: str, generation: int) -> bool:
        with self._lock:
            client = self._active
        if client is None or not client.active:
            return False
        return client.release_provider_lease(lease_id, generation)

    def provider_download_events(
        self,
        lease_id: str,
        generation: int,
        *,
        after_sequence: int = 0,
    ) -> tuple[ProviderDownloadEvent, ...]:
        with self._lock:
            client = self._active
        if client is None or not client.active:
            raise ReleaseWindowRuntimeError(
                "active native provider browser is unavailable"
            )
        return client.provider_download_events(
            lease_id,
            generation,
            after_sequence=after_sequence,
        )

    def show_provider_browser(self, lease_id: str, generation: int) -> None:
        with self._lock:
            client = self._active
        if client is None or not client.active:
            raise ReleaseWindowRuntimeError(
                "active native provider browser is unavailable"
            )
        client.show_provider(lease_id, generation)

    def close_provider_browser(self, lease_id: str, generation: int) -> None:
        with self._lock:
            client = self._active
        if client is None or not client.active:
            return
        client.hide_provider(lease_id, generation)

    def provider_current_url(self, lease_id: str, generation: int) -> str:
        with self._lock:
            client = self._active
        if client is None or not client.active:
            raise ReleaseWindowRuntimeError(
                "active native provider browser is unavailable"
            )
        return client.provider_current_url(lease_id, generation)

    def navigate_provider_browser(self, lease_id: str, generation: int, url: str) -> None:
        with self._lock:
            client = self._active
        if client is None or not client.active:
            raise ReleaseWindowRuntimeError(
                "active native provider browser is unavailable"
            )
        client.navigate_provider(lease_id, generation, url)

    def provider_document_state(
        self,
        lease_id: str,
        generation: int,
        *,
        ready_selectors: tuple[str, ...] = (),
        ready_texts: tuple[str, ...] = (),
    ) -> dict[str, object]:
        with self._lock:
            client = self._active
        if client is None or not client.active:
            raise ReleaseWindowRuntimeError(
                "active native provider browser is unavailable"
            )
        return client.provider_document_state(
            lease_id,
            generation,
            ready_selectors=ready_selectors,
            ready_texts=ready_texts,
        )

    def spawn_hidden(
        self,
        handoff_id: str,
        target_release_id: str,
        continuity: WindowContinuity,
    ) -> WindowCandidate:
        del continuity
        with self._lock:
            release = self._releases.get(target_release_id)
            if release is None:
                raise ReleaseWindowRuntimeError(
                    "target release is not registered for window launch"
                )
            client = self._launch(release, handoff_id=handoff_id)
            candidate = WindowCandidate(
                release_id=client.identity.release_id,
                process_id=client.identity.process_id,
                window_handle=client.identity.window_handle,
                profile_id=client.identity.profile_id,
            )
            self._candidate_clients[candidate] = client
            return candidate

    def wait_hidden_ready(
        self,
        candidate: WindowCandidate,
        continuity: WindowContinuity,
    ) -> WindowProof:
        client = self._client_for(candidate)
        client.prepare_hidden()
        return self._proof(client, continuity)

    def show_candidate(self, candidate: WindowCandidate) -> None:
        client = self._client_for(candidate)
        client.show()
        client.focus()

    def verify_visible(
        self,
        candidate: WindowCandidate,
        continuity: WindowContinuity,
    ) -> WindowProof:
        return self._proof(self._client_for(candidate), continuity)

    def hide_old(self) -> None:
        with self._lock:
            active = self._active
        if active is None:
            raise ReleaseWindowRuntimeError("old native window is unavailable")
        active.prepare_hidden()

    def verify_post_cutover(
        self,
        candidate: WindowCandidate,
        continuity: WindowContinuity,
    ) -> WindowProof:
        return self._proof(self._client_for(candidate), continuity)

    def commit_candidate(self, candidate: WindowCandidate) -> None:
        with self._lock:
            client = self._client_for(candidate)
            if self._active is None or self._retiring is not None:
                raise ReleaseWindowRuntimeError("native window ownership is incoherent")
            self._retiring = self._active
            self._active = client
            self._candidate_clients.pop(candidate)

    def retire_old(self) -> None:
        with self._lock:
            old = self._retiring
        if old is None:
            raise ReleaseWindowRuntimeError("retiring native window is unavailable")
        old.shutdown()
        with self._lock:
            if self._retiring is old:
                self._retiring = None

    def rollback_candidate(self, candidate: WindowCandidate) -> None:
        self._client_for(candidate).prepare_hidden()

    def show_old(self) -> None:
        with self._lock:
            old = self._active
        if old is None:
            raise ReleaseWindowRuntimeError("old native window is unavailable")
        old.show()
        old.focus()

    def verify_old_usable(self, continuity: WindowContinuity) -> None:
        with self._lock:
            old = self._active
        if old is None:
            raise ReleaseWindowRuntimeError("old native window is unavailable")
        proof = self._proof(old, continuity)
        if not proof.visible or proof.hidden:
            raise ReleaseWindowRuntimeError("old native window is not visible")

    def stop_candidate(self, candidate: WindowCandidate) -> None:
        with self._lock:
            client = self._candidate_clients.pop(candidate, None)
        if client is None:
            return
        client.shutdown()

    def wait_until_active_window_closes(
        self,
        *,
        poll_seconds: float = _WAIT_POLL_SECONDS,
    ) -> int:
        """Block across update retirements until the *current* window exits."""

        if type(poll_seconds) not in {int, float} or not 0 < float(poll_seconds) <= 5:
            raise ValueError("poll_seconds must be positive and at most five seconds")
        while True:
            with self._lock:
                if self._closed:
                    return 0
                active = self._active
            if active is None:
                raise ReleaseWindowRuntimeError("active native window is unavailable")
            exit_code = active.wait_for_exit(float(poll_seconds))
            if exit_code is not None:
                with self._lock:
                    # A normal update retires the client we were polling only
                    # after replacing `_active`; it must not close the stable
                    # broker.
                    if self._active is not active:
                        continue
                raise ReleaseWindowRuntimeError(
                    "active native window exited without authenticated shutdown"
                )
            try:
                health = active.health()
            except BaseException:
                with self._lock:
                    if self._active is not active:
                        continue
                raise
            if not health.close_requested:
                continue
            with self._lock:
                if self._active is not active:
                    continue
                if health.hidden or not health.visible:
                    raise ReleaseWindowRuntimeError(
                        "hidden native window requested application close"
                    )
                # Capture the last keystroke and current physical geometry before
                # authorizing the only graceful child shutdown path.
                self._persist_active_export(active.export_session())
                active.shutdown()
            return 0

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            clients = {
                client
                for client in (
                    self._active,
                    self._retiring,
                    *self._candidate_clients.values(),
                )
                if client is not None
            }
            self._active = None
            self._retiring = None
            self._candidate_clients.clear()
        errors: list[BaseException] = []
        for client in clients:
            try:
                client.close()
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise ReleaseWindowRuntimeError(
                "native window runtime cleanup was incomplete"
            ) from None


class ProductionWindowReplacement:
    """ReleaseActivator-facing two-phase adapter plus root-window lifecycle."""

    def __init__(
        self,
        initial_release: AcceptedRelease,
        *,
        public_base_url: str,
        api_credential: str,
        config: MachineConfig,
        supervisor: WindowSupervisorPort | None = None,
        launch_factory: Callable[[AcceptedRelease], WindowHostLaunch] = (
            WindowHostLaunch.from_release
        ),
        id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ports = SupervisorWindowHandoffPorts(
            initial_release,
            public_base_url=public_base_url,
            api_credential=api_credential,
            config=config,
            supervisor=supervisor,
            launch_factory=launch_factory,
            id_factory=id_factory,
        )
        self._handoff = ManagedWindowHandoff(
            self._ports,
            clock=clock,
            id_factory=id_factory,
        )
        self._initial_release = initial_release
        self._id_factory = id_factory
        self._started = False
        self._provider_lock = threading.RLock()
        self._active_provider_lease: ProviderLeaseHandshake | None = None

    @property
    def active_release_id(self) -> str | None:
        return self._ports.active_release_id

    def observe_active(self) -> NativeWindowObservation:
        return self._ports.observe_active()

    @contextmanager
    def provider_browser_surface(self):
        """Lease a hidden embedded browser until capture has armed its listeners."""

        with self._provider_lock:
            # A partial prior task may deliberately retain its document. An explicit next capture
            # replaces that one surface; release the old identity before beginning the new lease.
            previous = self._active_provider_lease
            if previous is not None:
                self._ports.release_provider_browser_lease(
                    previous.lease_id,
                    previous.generation,
                )
                self._active_provider_lease = None
            handshake = self._ports.begin_provider_browser_lease(self._id_factory())
            self._active_provider_lease = handshake
            lease = ProviderBrowserLease(
                endpoint=handshake.endpoint,
                lease_id=handshake.lease_id,
                generation=handshake.generation,
                _show=self._ports.show_provider_browser,
                _hide=self._ports.close_provider_browser,
                _current_url=self._ports.provider_current_url,
                _navigate=self._ports.navigate_provider_browser,
                _document_state=self._ports.provider_document_state,
                _download_events=self._ports.provider_download_events,
            )
            try:
                yield lease
            finally:
                if not lease._retained:
                    try:
                        self._ports.release_provider_browser_lease(
                            lease.lease_id,
                            lease.generation,
                        )
                    finally:
                        if self._active_provider_lease == handshake:
                            self._active_provider_lease = None

    def show_active_provider_browser(self) -> None:
        """Reveal the provider document retained behind the Stockroom surface."""

        lease = self._active_provider_lease
        if lease is None:
            raise ReleaseWindowRuntimeError("provider browser has no active lease")
        self._ports.show_provider_browser(lease.lease_id, lease.generation)

    def close_active_provider_browser(self) -> None:
        """Release a retained provider document after canonical completion."""

        with self._provider_lock:
            lease = self._active_provider_lease
            if lease is None:
                return
            try:
                self._ports.release_provider_browser_lease(
                    lease.lease_id,
                    lease.generation,
                )
            finally:
                if self._active_provider_lease == lease:
                    self._active_provider_lease = None

    def start_initial(self, release: AcceptedRelease | None = None) -> WindowContinuity:
        selected = self._initial_release if release is None else release
        continuity = self._ports.start_initial(selected)
        self._started = True
        return continuity

    def begin(self, target_release: AcceptedRelease) -> WindowHandoffAdoption:
        if not isinstance(target_release, AcceptedRelease):
            raise TypeError("target_release must be an AcceptedRelease")
        self._provider_lock.acquire()
        try:
            self._ports.register_release(target_release)
            return self._handoff.begin(target_release.release_id)
        except BaseException:
            self._provider_lock.release()
            raise

    def commit(self, adoption: object) -> WindowHandoffReceipt:
        if type(adoption) is not WindowHandoffAdoption:
            raise TypeError("adoption must be a WindowHandoffAdoption")
        try:
            return self._handoff.commit(adoption)
        finally:
            self._provider_lock.release()

    def rollback(self, adoption: object) -> None:
        if type(adoption) is not WindowHandoffAdoption:
            raise TypeError("adoption must be a WindowHandoffAdoption")
        try:
            self._handoff.rollback(adoption)
        finally:
            self._provider_lock.release()

    def wait_until_closed(self) -> int:
        if not self._started:
            raise ReleaseWindowRuntimeError("initial native window is not running")
        return self._ports.wait_until_active_window_closes()

    def close(self) -> None:
        self._ports.close()


__all__ = [
    "NativeWindowExport",
    "NativeWindowObservation",
    "ProductionWindowReplacement",
    "ReleaseWindowRuntimeError",
    "SupervisorWindowHandoffPorts",
    "WindowClientPort",
    "WindowSupervisorPort",
]
