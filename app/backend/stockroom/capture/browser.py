"""Provider capture: watch what a PERSON downloads, with nothing driving their page.

TWO CLASSES, TWO JOBS, AND THE LINE BETWEEN THEM IS THE SECURITY BOUNDARY

  * ``ProviderSurfaceCapture`` is the production path. Stockroom hosts the provider page in its
    OWN native WebView2 surface, leased from the window host, and then attaches NOTHING to it.
    No debugging port is opened, no driver connects, no script is injected, and no provider
    control is ever operated. The person navigates, signs in, clears any security check, picks
    the formats, and starts the download; Stockroom learns what happened only from the host's
    own download journal, which reports every download that surface begins and ends. That
    journal is the entire observation channel.

  * ``PlaywrightCaptureBrowser`` launches a SEPARATE, Stockroom-owned browser to READ a page
    (``scripts/webread.py``) and, in tests, to exercise the task-bound download broker against a
    real Playwright download. It never touches the provider surface.

WHAT WAS REMOVED, AND WHY IT CANNOT COME BACK AS A HELPER
Provider capture used to attach Playwright to the native provider WebView over a loopback CDP
port, and injected a Stockroom HUD into the provider document to show the required-file checklist
and outline the next control. Both are gone. The port was an unauthenticated local handle on the
person's signed-in provider session; the HUD needed a driver in the page to exist at all, and its
control outlines needed measured provider selectors to stay correct. The native host now owns the
provider chrome (Back/Forward/Refresh/URL/loading/error) and Stockroom's own window shows the
required-file checklist, so neither has a job left. ``tests/backend/capture/test_no_provider_
automation.py`` asserts that no driver-attachment call appears anywhere in this package.

A NOTE ON THE PERSISTENT PROFILE, which is not a free choice
Vendor logins must survive between parts, which means a persistent user-data dir, and Chromium
permits only one owner of one at a time. The native provider surface holds its own profile with
exclusive access. The standalone browser below takes an explicit inter-process profile lock for
the whole session, so two workers can never corrupt one provider's cookies.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict
from urllib.parse import urlsplit

from stockroom.capture.classify import classify_asset
from stockroom.capture.download_broker import (
    DownloadBroker,
    DownloadBrokerError,
    DownloadReceipt,
)
from stockroom.capture.requirements import Requirement
from stockroom.capture.trace import file_note, trace, trace_warning, url_note


class CaptureBrowserError(RuntimeError):
    """Something the caller must fix, phrased so the message names the actual blocker."""


UserCaptureStatus = Literal["completed", "try_another", "cancelled", "timed_out"]
_PROVIDER_FORMAT_REQUIREMENTS = {
    "kicad": frozenset({Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT}),
    "kicad_symbol": frozenset({Requirement.KICAD_SYMBOL}),
    "kicad_footprint": frozenset({Requirement.KICAD_FOOTPRINT}),
    "model": frozenset({Requirement.KICAD_MODEL}),
    "altium": frozenset({Requirement.ALTIUM_SYMBOL, Requirement.ALTIUM_FOOTPRINT}),
    "altium_symbol": frozenset({Requirement.ALTIUM_SYMBOL}),
    "altium_footprint": frozenset({Requirement.ALTIUM_FOOTPRINT}),
}
_DEFAULT_PROVIDER_FORMATS = (
    "kicad_symbol",
    "kicad_footprint",
    "model",
    "altium_symbol",
    "altium_footprint",
)


@dataclass(frozen=True, slots=True)
class ProviderHudSpec:
    """The required-file checklist for ONE provider route, as Stockroom-owned data.

    It is shown in STOCKROOM'S OWN window - never inside the provider page, which Stockroom does
    not touch - and it is also what decides completion: ``required_formats`` names, in stable
    machine keys, the CAD formats this route must come home with. Capture counts receipts, but it
    finishes on CONTENT, because one provider archive can carry every format while several
    unrelated downloads carry none.
    """

    provider_label: str
    author_route: str
    manufacturer: str
    mpn: str
    required_file_labels: tuple[str, ...]
    # Stable machine keys corresponding one-for-one with ``required_file_labels``.
    required_formats: tuple[str, ...] = ()
    automated_step: str = "Listening for provider downloads."
    human_action: str = "Start this part's download with every required format shown here."

    def __post_init__(self) -> None:
        for value, label in (
            (self.provider_label, "provider_label"),
            (self.author_route, "author_route"),
            (self.manufacturer, "manufacturer"),
            (self.mpn, "mpn"),
            (self.automated_step, "automated_step"),
            (self.human_action, "human_action"),
        ):
            if type(value) is not str or not value or value != value.strip():
                raise ValueError(f"{label} must be exact non-empty text")
        labels = self.required_file_labels
        if (
            type(labels) is not tuple
            or not labels
            or any(
                type(label) is not str or not label or label != label.strip() for label in labels
            )
        ):
            raise ValueError("required_file_labels must be a non-empty tuple of exact labels")
        formats = self.required_formats or _DEFAULT_PROVIDER_FORMATS[: len(labels)]
        if (
            type(formats) is not tuple
            or len(formats) != len(labels)
            or len(set(formats)) != len(formats)
            or any(value not in _PROVIDER_FORMAT_REQUIREMENTS for value in formats)
        ):
            raise ValueError(
                "required_formats must uniquely identify every required_file_labels entry"
            )
        object.__setattr__(self, "required_formats", formats)


@dataclass(frozen=True)
class CapturedFile:
    """One file the vendor actually delivered, already on disk at `path`.

    `suggested_name` is the vendor's own filename, kept because it is evidence (and because the
    classifier's zip-by-content path exists precisely for downloads that arrive without one).
    """

    path: Path
    suggested_name: str
    url: str


@dataclass(frozen=True, slots=True)
class UserCaptureResult:
    """Files Stockroom intercepted while the person controlled the provider page."""

    status: UserCaptureStatus
    files: tuple[DownloadReceipt, ...]
    final_url: str


def _completed_provider_formats(
    receipts: tuple[DownloadReceipt, ...],
    required_formats: tuple[str, ...],
) -> tuple[str, ...]:
    """Return CAD format groups actually present in the task-bound downloaded bytes.

    Receipt count is intentionally not used as a proxy. Providers variously deliver one archive
    containing every asset, two complementary archives, or a download that contains no CAD at
    all. The existing content classifier safely inspects loose files and nested vendor ZIPs, so
    the auto-finish decision speaks the same format truth as downstream ingest.
    """

    requirements: set[Requirement] = set()
    for receipt in receipts:
        requirements.update(classify_asset(Path(receipt.path)).requirements)
    return tuple(
        format_key
        for format_key in required_formats
        if _PROVIDER_FORMAT_REQUIREMENTS[format_key] <= requirements
    )


@dataclass(frozen=True)
class _BrowserCandidate:
    label: str
    browser_type: str
    channel: str | None = None


_PROVIDER_KEY = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", re.ASCII)
_WINDOWS_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED_NAMES = {
    "aux",
    "clock$",
    "con",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}
_PROCESS_LOCK_GUARD = threading.Lock()
_PROCESS_LOCKS: set[str] = set()
_USER_CAPTURE_WINDOW_LOCK = threading.Lock()
_CHROMIUM_PREFERENCES = Path("Default") / "Preferences"
_BROWSER_LAUNCH_TIMEOUT_MS = 20_000
_DISABLE_WEBRTC_INIT_SCRIPT = """
(() => {
  for (const key of ["RTCPeerConnection", "webkitRTCPeerConnection"]) {
    try {
      Object.defineProperty(globalThis, key, {
        value: undefined,
        writable: false,
        configurable: false,
      });
    } catch {}
  }
})();
"""


@contextmanager
def exclusive_user_capture_window():
    """At most ONE person-driven capture window in this process, whatever transport opened it.

    Public because the de-automated transport in ``capture/handoff.py`` must hold the SAME lock,
    not one of its own. Two concurrent person-driven captures watching one download stream is
    precisely how the retired implementation attributed a file to the wrong task; one person can
    only work one provider page at a time, so serializing them removes the ambiguity at the source
    rather than trying to resolve it afterwards.
    """

    if not _USER_CAPTURE_WINDOW_LOCK.acquire(blocking=False):
        raise CaptureBrowserError(
            "another assisted capture window is already active; Stockroom will retry this "
            "task after that window finishes"
        )
    try:
        yield
    finally:
        _USER_CAPTURE_WINDOW_LOCK.release()


_exclusive_user_capture_window = exclusive_user_capture_window


def _disable_webrtc(context) -> None:
    """Prevent capture pages from opening inbound WebRTC UDP listeners.

    Playwright controls Chromium over a pipe, so its automation transport does not need an
    inbound firewall exception. Provider and fingerprinting scripts can still instantiate
    ``RTCPeerConnection``, though, which makes Chromium's Network Service bind wildcard UDP
    endpoints and can trigger Windows Defender Firewall. CAD capture does not use WebRTC.

    A context init script applies before page scripts in every subsequently created document and
    child frame. Fail closed: continuing without this boundary can surface the firewall prompt.
    """

    try:
        context.add_init_script(_DISABLE_WEBRTC_INIT_SCRIPT)
    except Exception as exc:  # noqa: BLE001 - browser implementations expose different errors
        raise CaptureBrowserError("could not disable WebRTC in the capture browser") from exc


def _normalise_provider_key(provider_key: str) -> str:
    key = (provider_key or "").strip().casefold()
    if _PROVIDER_KEY.fullmatch(key) is None:
        raise CaptureBrowserError(f"invalid capture provider key {provider_key!r}")
    return key


def provider_profile_dir(profile_root: Path, provider_key: str) -> Path:
    """Return the provider's isolated persistent profile below ``profile_root``."""

    return Path(profile_root) / _normalise_provider_key(provider_key)


def _allow_automatic_downloads(profile_dir: Path) -> None:
    """Allow a provider page to deliver every file in one export.

    SnapMagic and similar CAD providers fan one explicit "download" action out into
    several browser downloads (symbol, footprint, model, metadata). Chromium otherwise
    pauses after the first file behind an "allow multiple downloads" prompt while the
    page itself reports success. This profile is isolated to one capture provider, and
    every resulting file still has to pass Stockroom's content and identity verification.
    """

    preferences_path = Path(profile_dir) / _CHROMIUM_PREFERENCES
    preferences_path.parent.mkdir(parents=True, exist_ok=True)
    preferences: dict = {}
    if preferences_path.is_file():
        try:
            loaded = json.loads(preferences_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CaptureBrowserError(
                f"could not safely update capture browser preferences at {preferences_path}"
            ) from exc
        if not isinstance(loaded, dict):
            raise CaptureBrowserError(
                f"capture browser preferences are not an object at {preferences_path}"
            )
        preferences = loaded

    profile = preferences.setdefault("profile", {})
    if not isinstance(profile, dict):
        raise CaptureBrowserError(
            f"capture browser profile preferences are malformed at {preferences_path}"
        )
    defaults = profile.setdefault("default_content_setting_values", {})
    if not isinstance(defaults, dict):
        raise CaptureBrowserError(
            f"capture browser content settings are malformed at {preferences_path}"
        )
    defaults["automatic_downloads"] = 1

    temporary_path = preferences_path.with_suffix(".stockroom.tmp")
    try:
        temporary_path.write_text(
            json.dumps(preferences, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary_path, preferences_path)
    except OSError as exc:
        temporary_path.unlink(missing_ok=True)
        raise CaptureBrowserError(
            f"could not enable provider multi-file downloads at {preferences_path}"
        ) from exc


class _DownloadProgressItem(TypedDict):
    name: str
    state: str
    bytes_received: int
    total_bytes: int


@dataclass(slots=True)
class _NativeSurfaceDownload:
    """One download the native host reported, tracked until its bytes are staged or refused."""

    operation_id: str
    generation: int
    broker: DownloadBroker | None
    suggested_name: str
    source_url: str
    result_path: Path
    state: str = "in_progress"
    total_bytes: int = -1
    bytes_received: int = 0
    interrupt_reason: str = ""
    captured: bool = False


class ProviderProfileLock:
    """Fail-fast process and OS lock protecting one provider's browser profile.

    Chromium already refuses many duplicate profile launches, but relying on its incidental error
    makes contention browser-version dependent and can leave partially updated profile state.
    This guard establishes ownership before Playwright touches the directory.
    """

    def __init__(self, profile_dir: Path, provider_key: str):
        self.profile_dir = Path(profile_dir)
        self.provider_key = _normalise_provider_key(provider_key)
        self.path = (
            self.profile_dir.parent / ".locks" / f"{self.provider_key}.stockroom-browser.lock"
        )
        self._handle = None
        self._process_key = os.path.normcase(str(self.path.resolve(strict=False)))
        self._held = False

    def acquire(self) -> None:
        with _PROCESS_LOCK_GUARD:
            if self._process_key in _PROCESS_LOCKS:
                self._raise_busy()
            _PROCESS_LOCKS.add(self._process_key)

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = self.path.open("a+b")
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:  # pragma: no cover - Windows is authoritative; keeps unit tests portable
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (OSError, BlockingIOError):
                handle.close()
                self._raise_busy()
            self._handle = handle
            self._held = True
        except BaseException:
            with _PROCESS_LOCK_GUARD:
                _PROCESS_LOCKS.discard(self._process_key)
            raise

    def _raise_busy(self) -> None:
        raise CaptureBrowserError(
            f"{self.provider_key} capture is already using its browser profile; "
            "wait for that capture worker to finish"
        )

    def release(self) -> None:
        if not self._held:
            return
        handle = self._handle
        try:
            if handle is not None:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:  # pragma: no cover - Windows authoritative; tests stay portable
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                finally:
                    handle.close()
        finally:
            self._handle = None
            self._held = False
            with _PROCESS_LOCK_GUARD:
                _PROCESS_LOCKS.discard(self._process_key)

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()


class SharedPlaywrightRuntime:
    """One lazy synchronous Playwright owner shared by every standalone browser in a run.

    Playwright's synchronous API cannot nest two runtime context managers on one thread, so
    several browser contexts that must stay alive at once share this single engine runtime while
    retaining separate browser/profile ownership.
    """

    def __init__(self) -> None:
        self._manager = None
        self._playwright = None
        self._thread_id: int | None = None
        self._generation = 0

    @property
    def generation(self) -> int:
        return self._generation

    def get(self):
        thread_id = threading.get_ident()
        if self._playwright is not None:
            if self._thread_id != thread_id:
                raise CaptureBrowserError(
                    "the guided-capture browser runtime cannot move between worker threads"
                )
            return self._playwright
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise CaptureBrowserError(
                "playwright is not installed; it is a declared dependency, run `uv sync`"
            ) from exc
        manager = sync_playwright()
        self._playwright = manager.__enter__()
        self._manager = manager
        self._thread_id = thread_id
        self._generation += 1
        return self._playwright

    def close(self) -> None:
        manager = self._manager
        if manager is None:
            return
        if self._thread_id != threading.get_ident():
            raise CaptureBrowserError(
                "the guided-capture browser runtime must close on its owning worker thread"
            )
        self._manager = None
        self._playwright = None
        self._thread_id = None
        manager.__exit__(None, None, None)


class ProviderSurfaceCapture:
    """Observe ONE person-driven provider page hosted in Stockroom's native surface.

    Nothing here drives the page. There is no driver connection, no injected script, and no
    provider control is ever read or operated: Stockroom navigates its own surface to an
    already-validated URL and then only listens. Every fact it learns comes from the native
    lease - the download journal, the current URL, and two coarse document signals (a terminal
    provider error page, and a provider-owned account restriction) that exist so an unusable page
    ends in seconds instead of burning the whole capture window.

    GENERATION FENCING, which is why a slow export cannot land on the next part
    Every ``capture_user_downloads`` call opens a new generation. A download event is filed under
    the generation that was active when the host first reported it, and a generation that has been
    sealed accepts nothing further. A file that finishes after its task ended is therefore
    discarded rather than attributed to whichever task happens to be open.
    """

    # Stockroom owns this window and is responsible for what it shows. The de-automated transport
    # in ``capture/handoff.py`` declares the opposite, and that difference is the whole contract:
    # a window Stockroom owns is one it can bind downloads to; a window it does not own is not.
    owns_window = True
    launched_browser = "Stockroom Embedded WebView2"

    def __init__(
        self,
        *,
        download_dir: Path,
        provider_key: str | None = None,
        native_surface: object,
    ) -> None:
        if native_surface is None:
            raise CaptureBrowserError("a native provider surface is required")
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self._native_surface = native_surface
        self.provider_key = (
            _normalise_provider_key(provider_key) if provider_key is not None else None
        )
        self._captured: list[CapturedFile] = []
        self._download_errors: list[CaptureBrowserError] = []
        self._lock = threading.RLock()
        self._active_broker: DownloadBroker | None = None
        self._generation = 0
        self._active_generation = 0
        self._finalized_generations: set[int] = set()
        self._download_cursor = 0
        self._downloads: dict[str, _NativeSurfaceDownload] = {}
        self._progress_items: dict[str, _DownloadProgressItem] = {}

    @property
    def captured(self) -> list[CapturedFile]:
        self._drain_native_downloads()
        return list(self._captured)

    @property
    def download_errors(self) -> tuple[CaptureBrowserError, ...]:
        with self._lock:
            return tuple(self._download_errors)

    def close(self) -> None:
        """The native surface lease owns the window; releasing it is the lease's job."""

    def retain_provider_surface(self) -> bool:
        """Keep the native provider document when this capture ends incomplete."""

        retain = getattr(self._native_surface, "retain", None)
        if not callable(retain):
            return False
        retain()
        return True

    @contextmanager
    def _task(self, broker: DownloadBroker):
        """Bind one exact download task for the duration of one route."""

        with self._lock:
            if self._active_broker is not None:
                raise CaptureBrowserError("a provider capture task is already active")
            self._generation += 1
            generation = self._generation
            self._active_generation = generation
            self._active_broker = broker
            self._progress_items = {}
        try:
            yield generation
        finally:
            with self._lock:
                self._active_broker = None
                if self._active_generation == generation:
                    self._active_generation = 0

    def capture_user_downloads(
        self,
        url: str,
        broker: DownloadBroker,
        *,
        hud: ProviderHudSpec | None = None,
        should_finish: Callable[[], bool] | None = None,
        should_cancel: Callable[[], bool] | None = None,
        on_progress: Callable[[dict[str, object]], None] | None = None,
        on_navigation_state: Callable[[dict[str, object]], None] | None = None,
        timeout_s: float = 600.0,
        poll_interval_s: float = 0.1,
        settle_seconds: float = 0.75,
        auto_finish_seconds: float = 2.0,
        auto_finish_idle_seconds: float = 25.0,
        termination_grace_seconds: float = 30.0,
    ) -> UserCaptureResult:
        """Open one provider page in the native surface and stage what the person downloads.

        HOW THIS ENDS
        ``should_cancel`` and ``should_finish`` are Stockroom's own UI, polled - the person's Skip
        and Finish Route. Beyond those, capture finishes by itself once every format ``hud``
        declares required is present in the staged bytes and a short quiet period passes; a
        capture still missing a required format keeps waiting, because finishing on the first file
        truncates multi-asset providers and the partial set is rejected downstream. A longer idle
        gap is the backstop for a provider that packs several formats into one archive. A terminal
        provider error page ends the route immediately as ``try_another``, and a provider-owned
        account restriction ends it as ``timed_out`` with the exact final URL, which the guided
        layer turns into a resumable blocked verdict.

        Every ending drains the native journal to quiescence first. A timeout is a capture
        boundary, not permission to discard bytes the host finished writing one poll ago.
        """

        if type(broker) is not DownloadBroker:
            raise TypeError("broker must be a DownloadBroker")
        if hud is not None:
            if type(hud) is not ProviderHudSpec:
                raise TypeError("hud must be a ProviderHudSpec")
            if (
                hud.manufacturer != broker.task.manufacturer_key
                or hud.mpn != broker.task.mpn_canonical
            ):
                raise CaptureBrowserError(
                    "provider route identity must exactly match its bound download task"
                )
        _validate_capture_url(url)
        for callback, label in (
            (should_finish, "should_finish"),
            (should_cancel, "should_cancel"),
            (on_progress, "on_progress"),
            (on_navigation_state, "on_navigation_state"),
        ):
            if callback is not None and not callable(callback):
                raise TypeError(f"{label} must be callable")
        timeout = _bounded_seconds(timeout_s, "timeout_s", maximum=3600.0)
        poll_interval = _bounded_seconds(poll_interval_s, "poll_interval_s", maximum=1.0)
        settle = _bounded_seconds(
            settle_seconds,
            "settle_seconds",
            maximum=30.0,
            allow_zero=True,
        )
        auto_finish = _bounded_seconds(
            auto_finish_seconds,
            "auto_finish_seconds",
            maximum=30.0,
            allow_zero=True,
        )
        idle = _bounded_seconds(
            auto_finish_idle_seconds,
            "auto_finish_idle_seconds",
            maximum=600.0,
            allow_zero=True,
        )
        termination_grace = _bounded_seconds(
            termination_grace_seconds,
            "termination_grace_seconds",
            maximum=60.0,
        )
        trace(
            "capture.user-window.open",
            provider=self.provider_key,
            url=url_note(url),
            task=broker.task.task_id,
            required=list(hud.required_file_labels) if hud is not None else [],
            timeout_s=timeout,
            automation_attached=False,
        )
        required_formats = hud.required_formats if hud is not None else ()

        with _exclusive_user_capture_window(), self._task(broker):
            return self._watch(
                url,
                broker,
                required_formats=required_formats,
                should_finish=should_finish,
                should_cancel=should_cancel,
                on_progress=on_progress,
                on_navigation_state=on_navigation_state,
                timeout=timeout,
                poll_interval=poll_interval,
                settle=settle,
                auto_finish=auto_finish,
                idle=idle,
                termination_grace=termination_grace,
            )

    def _watch(
        self,
        url: str,
        broker: DownloadBroker,
        *,
        required_formats: tuple[str, ...],
        should_finish: Callable[[], bool] | None,
        should_cancel: Callable[[], bool] | None,
        on_progress: Callable[[dict[str, object]], None] | None,
        on_navigation_state: Callable[[dict[str, object]], None] | None,
        timeout: float,
        poll_interval: float,
        settle: float,
        auto_finish: float,
        idle: float,
        termination_grace: float,
    ) -> UserCaptureResult:
        deadline = time.monotonic() + timeout
        status: UserCaptureStatus = "timed_out"
        final_url = url
        error_mark = len(self.download_errors)

        show = getattr(self._native_surface, "show", None)
        if callable(show):
            # The broker is bound above, so every download this page can start already has an
            # owner. Only then may a person see and work the provider surface.
            show()

        navigate = getattr(self._native_surface, "navigate", None)
        if not callable(navigate):
            raise CaptureBrowserError("the provider surface cannot open a page")
        navigate(url)

        quiet_since = time.monotonic()
        receipt_count = len(broker.receipts)
        completed_formats = _completed_provider_formats(broker.receipts, required_formats)
        requested_status: UserCaptureStatus | None = None
        requested_at: float | None = None
        last_progress: dict[str, object] | None = None
        last_navigation_state: dict[str, object] | None = None
        while True:
            pending, _ = self._drain_native_downloads()
            progress = self._download_progress()
            if on_progress is not None and progress != last_progress:
                on_progress(progress)
                last_progress = progress
            now = time.monotonic()
            navigation_state = self._navigation_state(final_url)
            final_url = str(navigation_state["url"] or final_url)
            if (
                on_navigation_state is not None
                and navigation_state != last_navigation_state
            ):
                on_navigation_state(navigation_state)
                last_navigation_state = navigation_state

            errors = self.download_errors
            if len(errors) > error_mark:
                # A failing companion does not invalidate files already staged. Surface the
                # failure only when there is genuinely nothing to hand back; downstream
                # verification judges whether the set is complete.
                if not broker.receipts:
                    raise errors[error_mark]
                if self._finalize_native_downloads_if_idle():
                    status = "completed"
                    break

            current_count = len(broker.receipts)
            if current_count != receipt_count:
                receipt_count = current_count
                completed_formats = _completed_provider_formats(
                    broker.receipts,
                    required_formats,
                )
                quiet_since = now

            if requested_status is None:
                if should_cancel is not None and should_cancel():
                    requested_status = "cancelled"
                elif should_finish is not None and should_finish():
                    requested_status = "completed"
                elif now >= deadline:
                    requested_status = "timed_out"
                else:
                    document = self._document_signals()
                    if document.get("navigation_error"):
                        trace(
                            "capture.user-window.navigation-error",
                            provider=self.provider_key or "",
                            url=url_note(final_url),
                        )
                        requested_status = "try_another"
                    elif document.get("provider_error"):
                        # A known provider error document cannot become useful by continuing to
                        # poll it. Advance to the next independent author route immediately.
                        trace(
                            "capture.user-window.provider-error",
                            provider=self.provider_key or "",
                            url=url_note(final_url),
                        )
                        requested_status = "try_another"
                    elif document.get("account_verification"):
                        # A provider-owned account restriction is not a transient CAPTCHA. It
                        # cannot clear without the account owner entering a phone number and a
                        # one-time code, so do not spend the rest of the capture window on it.
                        trace(
                            "capture.user-window.account-verification",
                            provider=self.provider_key or "",
                            url=url_note(final_url),
                        )
                        requested_status = "timed_out"
            if requested_status is not None:
                requested_at = requested_at or now
                # The host can accept a download just before its event reaches this ledger. Give
                # that event one bounded settle window before sealing a zero-receipt route.
                if current_count == 0 and now - requested_at < max(settle, 0.25):
                    time.sleep(min(poll_interval, max(settle, 0.25) - (now - requested_at)))
                    continue
                if pending == 0 and self._finalize_native_downloads_if_idle():
                    status = requested_status
                    break
                if now - requested_at >= termination_grace:
                    # Cancellation is task-owned and lease-scoped. It ends native operations
                    # before this generation is sealed, so Finish, Skip, and timeout remain
                    # bounded even when WebView2 never reports a terminal event on its own.
                    self._cancel_native_downloads()
                    pending, _ = self._drain_native_downloads()
                    if pending > 0:
                        self._abandon_active_native_downloads()
                    status = requested_status
                    break
                time.sleep(poll_interval)
                continue

            if (
                current_count > 0
                and pending == 0
                and now - quiet_since >= auto_finish
                and set(required_formats) <= set(completed_formats)
                and self._finalize_native_downloads_if_idle()
            ):
                status = "completed"
                break
            if (
                current_count > 0
                and pending == 0
                and idle > 0
                and now - quiet_since >= idle
                and self._finalize_native_downloads_if_idle()
            ):
                # Fewer receipts than required formats is the ordinary shape for a provider that
                # ships several formats inside one archive whose contents ingest classifies later.
                # Wait out the long gap rather than finish early and lose a format still coming.
                status = "completed"
                break
            time.sleep(poll_interval)

        final_url = self._current_url(final_url)
        trace(
            "capture.user-window.result",
            provider=self.provider_key or "",
            status=status,
            files=len(broker.receipts),
            url=url_note(final_url),
        )
        return UserCaptureResult(
            status=status,
            files=broker.receipts,
            final_url=final_url,
        )

    def _navigation_state(self, fallback_url: str) -> dict[str, object]:
        """Read only native chrome state, never provider document content."""

        state_reader = getattr(self._native_surface, "state", None)
        if callable(state_reader):
            try:
                state = state_reader()
            except Exception:  # noqa: BLE001 - transient navigation uses safe fallback state
                state = None
            if isinstance(state, dict):
                url = state.get("url")
                loading = state.get("loading")
                navigation_error = state.get("navigation_error")
                can_go_back = state.get("can_go_back")
                can_go_forward = state.get("can_go_forward")
                if (
                    type(url) is str
                    and len(url) <= 4096
                    and type(loading) is bool
                    and type(navigation_error) is str
                    and len(navigation_error) <= 512
                    and type(can_go_back) is bool
                    and type(can_go_forward) is bool
                ):
                    return {
                        "url": url or fallback_url,
                        "loading": loading,
                        "navigation_error": navigation_error,
                        "can_go_back": can_go_back,
                        "can_go_forward": can_go_forward,
                    }
        return {
            "url": self._current_url(fallback_url),
            "loading": False,
            "navigation_error": "",
            "can_go_back": False,
            "can_go_forward": False,
        }

    def _current_url(self, fallback: str) -> str:
        """The surface's own current URL. No provider content is read to obtain it."""

        current_url = getattr(self._native_surface, "current_url", None)
        if not callable(current_url):
            return fallback
        try:
            return str(current_url() or "") or fallback
        except Exception:  # noqa: BLE001 - a navigating document has no stable URL yet
            return fallback

    def _document_signals(self) -> dict[str, object]:
        """The two coarse end-the-route signals, or nothing when they cannot be read.

        This is deliberately not a page reader: it returns booleans the native host already
        computes, and an unreadable document is never treated as either verdict.
        """

        security_state = getattr(self._native_surface, "security_state", None)
        document_state = getattr(self._native_surface, "document_state", None)
        reader = security_state if callable(security_state) else document_state
        if not callable(reader):
            return {}
        try:
            state = reader()
        except Exception:  # noqa: BLE001 - unreadable is never a verdict
            return {}
        if not isinstance(state, dict):
            return {}
        return {
            "provider_error": bool(state.get("provider_error")),
            "account_verification": bool(state.get("account_verification")),
            "navigation_error": str(state.get("navigation_error", "") or ""),
        }

    def _download_progress(self) -> dict[str, object]:
        """Return a path-free progress snapshot for Stockroom's own provider chrome."""

        with self._lock:
            files = [item.copy() for item in self._progress_items.values()]
        known_totals = [
            item["total_bytes"]
            for item in files
            if item["total_bytes"] >= 0
        ]
        return {
            "active": sum(item["state"] in {"in_progress", "unknown"} for item in files),
            "completed": sum(item["state"] == "completed" for item in files),
            "bytes_received": sum(max(0, item["bytes_received"]) for item in files),
            "total_bytes": sum(known_totals) if len(known_totals) == len(files) else -1,
            "files": files,
        }

    def _drain_native_downloads(
        self,
        *,
        finalize_if_idle: bool = False,
    ) -> tuple[int, bool]:
        """Move host-observed files through the exact task broker."""

        self._poll_native_surface_downloads()
        pending = self._drain_native_surface_downloads()
        finalized = pending == 0
        if finalize_if_idle and finalized:
            with self._lock:
                generation = self._active_generation
                if generation > 0:
                    self._finalized_generations.add(generation)
        return pending, finalized

    def _poll_native_surface_downloads(self) -> None:
        """Reconcile the host's download journal into this capture's own ledger."""

        read_events = getattr(self._native_surface, "download_events", None)
        if not callable(read_events):
            return
        try:
            events = tuple(read_events(after_sequence=self._download_cursor))
        except Exception as exc:  # noqa: BLE001 - a broken native ledger is a capture failure
            with self._lock:
                self._download_errors.append(
                    CaptureBrowserError(
                        "the embedded provider download ledger could not be read "
                        f"({type(exc).__name__})"
                    )
                )
            return
        for event in events:
            sequence = getattr(event, "sequence", None)
            operation_id = str(getattr(event, "operation_id", "") or "")
            phase = str(getattr(event, "phase", "") or "")
            state = str(getattr(event, "state", "") or "")
            if type(sequence) is not int or sequence <= self._download_cursor:
                continue
            self._download_cursor = sequence
            if not operation_id or phase not in {"started", "progress", "terminal"}:
                continue
            result_path = Path(str(getattr(event, "result_file_path", "") or ""))
            suggested_name = _safe_filename(
                str(getattr(event, "suggested_file_name", "") or "cad-download")
            )
            source_url = str(getattr(event, "uri", "") or "")
            total_bytes = getattr(event, "total_bytes", -1)
            bytes_received = getattr(event, "bytes_received", 0)
            interrupt_reason = str(getattr(event, "interrupt_reason", "") or "")
            if type(total_bytes) is not int or total_bytes < -1:
                total_bytes = -1
            if type(bytes_received) is not int or bytes_received < 0:
                bytes_received = 0
            with self._lock:
                generation = self._active_generation
                if generation in self._finalized_generations:
                    generation = 0
                broker = self._active_broker if generation > 0 else None
                download = self._downloads.get(operation_id)
                if download is None:
                    download = _NativeSurfaceDownload(
                        operation_id=operation_id,
                        generation=generation,
                        broker=broker,
                        suggested_name=suggested_name,
                        source_url=source_url,
                        result_path=result_path,
                    )
                    self._downloads[operation_id] = download
                if result_path != Path(""):
                    download.result_path = result_path
                if source_url:
                    download.source_url = source_url
                if suggested_name != "cad-download":
                    download.suggested_name = suggested_name
                download.state = state
                download.total_bytes = total_bytes
                download.bytes_received = bytes_received
                download.interrupt_reason = interrupt_reason
                if generation > 0:
                    self._progress_items[operation_id] = {
                        "name": suggested_name,
                        "state": state,
                        "bytes_received": bytes_received,
                        "total_bytes": total_bytes,
                    }
                if broker is None and download.broker is None:
                    self._download_errors.append(
                        CaptureBrowserError(
                            "the native download began without one exact Stockroom task binding"
                        )
                    )

    def _drain_native_surface_downloads(self) -> int:
        """Stage every terminal host path that belongs to the active task."""

        with self._lock:
            generation = self._active_generation
            active = [
                item
                for item in self._downloads.values()
                if item.generation == generation and not item.captured
            ]
        pending = sum(item.state in {"in_progress", "unknown"} for item in active)
        for download in active:
            if download.state == "interrupted":
                raw_reason = download.interrupt_reason.split(maxsplit=1)[0][:48]
                reason = "".join(
                    character
                    for character in raw_reason
                    if character.isalnum() or character in {"_", "-"}
                )
                detail = f" ({reason})" if reason else ""
                with self._lock:
                    self._download_errors.append(
                        CaptureBrowserError(
                            "the provider download was interrupted"
                            f"{detail}; retry the download on this provider page"
                        )
                    )
                download.captured = True
                continue
            if download.state != "completed":
                continue
            source = download.result_path
            if not source.is_file() or source.is_symlink() or source.stat().st_size <= 0:
                pending += 1
                continue

            if download.broker is None:
                download.captured = True
                source.unlink(missing_ok=True)
                continue
            try:
                receipt = download.broker.capture_local_file(
                    source,
                    source_url=download.source_url,
                    transport="webview2-native",
                    suggested_filename=download.suggested_name,
                )
                with self._lock:
                    download.captured = True
                    if all(captured.path != receipt.path for captured in self._captured):
                        self._captured.append(
                            CapturedFile(
                                path=receipt.path,
                                suggested_name=(
                                    download.suggested_name
                                    if download.suggested_name != "cad-download"
                                    else receipt.suggested_name
                                ),
                                url=receipt.source_url,
                            )
                        )
                trace(
                    "capture.download.saved",
                    provider=self.provider_key or "",
                    via="webview2-native",
                    saved=file_note(receipt.path),
                )
            finally:
                source.unlink(missing_ok=True)
        with self._lock:
            self._downloads = {
                operation_id: item
                for operation_id, item in self._downloads.items()
                if not item.captured
            }
        return pending

    def _cancel_native_downloads(self) -> int:
        """Cancel only operations owned by this route's native lease."""

        cancel = getattr(self._native_surface, "cancel_downloads", None)
        if not callable(cancel):
            return 0
        try:
            cancelled = cancel()
        except Exception as exc:  # noqa: BLE001 - the bounded route still must terminate
            with self._lock:
                self._download_errors.append(
                    CaptureBrowserError(
                        "the embedded provider could not cancel its stuck download "
                        f"({type(exc).__name__})"
                    )
                )
            return 0
        return cancelled if type(cancelled) is int and cancelled >= 0 else 0

    def _abandon_active_native_downloads(self) -> None:
        """Seal a timed-out generation after its task-owned cancel command."""

        with self._lock:
            generation = self._active_generation
            abandoned = [
                item for item in self._downloads.values()
                if item.generation == generation and not item.captured
            ]
            for item in abandoned:
                item.captured = True
                progress = self._progress_items.get(item.operation_id)
                if progress is not None:
                    progress["state"] = "interrupted"
            self._finalized_generations.add(generation)
            self._downloads = {
                operation_id: item
                for operation_id, item in self._downloads.items()
                if not item.captured
            }
        for item in abandoned:
            source = item.result_path
            if source.is_file() and not source.is_symlink():
                source.unlink(missing_ok=True)

    def _finalize_native_downloads_if_idle(self) -> bool:
        """Atomically drain and seal the native intake only when no byte stream is in flight."""

        pending, finalized = self._drain_native_downloads(finalize_if_idle=True)
        return pending == 0 and finalized


class PlaywrightCaptureBrowser:
    """A Stockroom-launched browser used to READ a page, and to prove the download broker works.

    NOT the provider surface. Production provider capture goes through ``ProviderSurfaceCapture``
    above, which attaches nothing to anything. This class exists for ``scripts/webread.py`` - the
    one tool that renders a page and reports its text, controls, and links - and for the tests
    that exercise a real Playwright download through the task-bound broker.

    ENGINE IS A PARAMETER, NEVER A SECOND CLASS. ``windows`` is an explicit Chrome-then-Chromium
    compatibility policy; everything else names one Playwright engine. There is one
    browser-launching class - that is the one-tool-per-job rule, and
    ``tests/backend/capture/test_one_tool_per_job.py`` enforces it by listing the modules allowed
    to launch a browser at all.
    """

    # Stockroom launched this window and is responsible for closing it. The de-automated transport
    # in ``capture/handoff.py`` declares the opposite, and that difference is the whole contract:
    # a window Stockroom owns is an automated session, and a person-driven route must not have one.
    owns_window = True

    def __init__(
        self,
        *,
        download_dir: Path,
        profile_dir: Path | None = None,
        headless: bool = False,
        engine: str = "chromium",
        provider_key: str | None = None,
        playwright_runtime: SharedPlaywrightRuntime | None = None,
    ) -> None:
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir = Path(profile_dir) if profile_dir else None
        self.headless = headless
        self.engine = engine
        self._playwright_runtime = playwright_runtime
        self._browser = None
        self.provider_key = (
            _normalise_provider_key(provider_key)
            if provider_key is not None
            else _normalise_provider_key(self.profile_dir.name)
            if self.profile_dir is not None
            else None
        )
        self.launched_browser: str | None = None
        self._captured: list[CapturedFile] = []
        self._download_errors: list[CaptureBrowserError] = []
        self._wired_pages: list[object] = []
        self._page_brokers: list[tuple[object, DownloadBroker]] = []
        self._context = None
        # Playwright's synchronous API may re-enter the download callback while ``save_as`` for
        # the previous file pumps protocol events.  A provider action that emits a symbol,
        # footprint, and model together therefore nests callbacks on the same thread.  A plain
        # Lock deadlocks on the second file; the RLock serializes filename allocation without
        # blocking that legitimate re-entry.
        self._download_lock = threading.RLock()

    @property
    def captured(self) -> list[CapturedFile]:
        return list(self._captured)

    @property
    def download_errors(self) -> tuple[CaptureBrowserError, ...]:
        with self._download_lock:
            return tuple(self._download_errors)

    @property
    def persistent_digikey_session(self) -> bool:
        """Whether this browser owns DigiKey's provider-isolated persistent profile."""

        return self.provider_key == "digikey" and self.profile_dir is not None

    @contextmanager
    def task_page(self, broker: DownloadBroker):
        """Open one page whose downloads can belong to exactly one workflow task.

        A context persists for the run so cookies and sign-in survive, but pages do not cross task
        boundaries. A slow export from part A can therefore never arrive after a mutable global
        binding has moved to part B: A's page stays permanently mapped to A and is closed before B
        gets a new page. Popups inherit the mapping through their opener.
        """
        if type(broker) is not DownloadBroker:
            raise TypeError("broker must be a DownloadBroker")
        with self._download_lock:
            context = self._context
        if context is None:
            raise CaptureBrowserError("the capture browser session is not open")
        # A persistent Playwright context normally starts with one about:blank page. Opening a
        # second page here left that inert first window visible beside the task-bound one, which
        # made Stockroom appear to launch duplicate browsers even though only one could capture.
        # Claim that untouched page for the first task; later tasks still receive fresh pages.
        with self._download_lock:
            bound_pages = {id(wired) for wired, _bound in self._page_brokers}
        pages = list(getattr(context, "pages", ()) or ())
        reusable_pages = [
            candidate
            for candidate in pages
            if id(candidate) not in bound_pages and not _page_is_closed(candidate)
        ]
        page = next(
            (
                candidate
                for candidate in reusable_pages
                if _page_url(candidate, "about:blank") in {"", "about:blank"}
            ),
            None,
        )
        # Claiming a pre-existing page avoids a stray blank window, but that page is the one
        # `session()` yields and keeps for the whole session. Only a page this task actually
        # opened may be closed with it; closing a claimed one ends the session's own surface.
        task_opened_page = page is None
        if page is None:
            page = context.new_page()
        original_page = page
        self._wire_downloads(page)
        with self._download_lock:
            self._page_brokers.append((page, broker))
        try:
            yield page
        finally:
            with self._download_lock:
                context = self._context or context
            # Download actions can open child tabs/windows. They inherit the broker binding
            # through their opener, so they are part of this task and must close with it.
            owned_pages = [page]
            for candidate in list(getattr(context, "pages", ()) or ()):
                if candidate is page:
                    continue
                current = candidate
                seen: set[int] = set()
                while current is not None and id(current) not in seen:
                    seen.add(id(current))
                    opener = getattr(current, "opener", None)
                    try:
                        current = opener() if callable(opener) else None
                    except Exception:  # noqa: BLE001 - an unreadable opener is simply unbound
                        current = None
                    if current is page:
                        owned_pages.append(candidate)
                        break
            closable_pages = [
                owned for owned in owned_pages if owned is not page or task_opened_page
            ]
            for owned in reversed(closable_pages):
                try:
                    owned.close()
                except Exception:  # noqa: BLE001 - teardown is best effort
                    pass
            owned_ids = {id(owned) for owned in owned_pages} | {id(original_page)}
            with self._download_lock:
                self._page_brokers = [
                    (wired, bound)
                    for wired, bound in self._page_brokers
                    if id(wired) not in owned_ids
                ]
                self._wired_pages = [
                    wired for wired in self._wired_pages if id(wired) not in owned_ids
                ]

    @contextmanager
    def session(self):
        """Open a browser, yield a page, and always tear it down.

        Yields the Playwright `Page`. Downloads that land during the session are saved into
        `download_dir` and recorded on `self.captured` - saved EAGERLY, because Playwright deletes
        a context's downloads when the context closes, so a file only "arrived" once it is copied
        out of the temp area.
        """
        lock = (
            ProviderProfileLock(self.profile_dir, self.provider_key)
            if self.profile_dir is not None and self.provider_key is not None
            else None
        )
        if lock is not None:
            lock.acquire()
        try:
            if self._playwright_runtime is not None:
                with self._playwright_session(self._playwright_runtime.get()) as page:
                    yield page
                return

            try:
                from playwright.sync_api import sync_playwright
            except ImportError as exc:  # pragma: no cover - dependency is declared
                raise CaptureBrowserError(
                    "playwright is not installed; it is a declared dependency, run `uv sync`"
                ) from exc
            with sync_playwright() as pw, self._playwright_session(pw) as page:
                yield page
        finally:
            if lock is not None:
                lock.release()

    @contextmanager
    def _playwright_session(self, pw):
        context = None
        browser = None
        try:
            context, browser = self._launch_playwright(pw)
            with self._download_lock:
                self._context = context
                self._browser = browser
            context.on("page", self._wire_downloads)
            page = context.pages[0] if context.pages else context.new_page()
            self._wire_downloads(page)
            yield page
        finally:
            for closable in (context, browser):
                if closable is not None:
                    try:
                        closable.close()
                    except Exception:  # noqa: BLE001 - teardown is best effort
                        pass
            with self._download_lock:
                self._context = None
                self._browser = None
                self._page_brokers.clear()
                self._wired_pages.clear()

    def _launch_playwright(self, pw):
        """Launch the requested browser policy and return ``(context, browser)``.

        ``windows`` is a deterministic policy, not an alias for bundled Chromium: prefer the
        preferred browser already managed on this machine (Chrome), then Stockroom's pinned
        Playwright Chromium. A failed candidate is fully discarded before the next one is
        attempted.
        """

        candidates = _browser_candidates(self.engine)
        failures: list[str] = []
        for candidate in candidates:
            engine = getattr(pw, candidate.browser_type, None)
            if engine is None:
                failures.append(f"{candidate.label}: browser type unavailable")
                continue
            options = {
                "headless": self.headless,
                "accept_downloads": True,
                "timeout": _BROWSER_LAUNCH_TIMEOUT_MS,
            }
            if candidate.channel is not None:
                options["channel"] = candidate.channel
            context = None
            browser = None
            try:
                if self.profile_dir is not None:
                    self.profile_dir.mkdir(parents=True, exist_ok=True)
                    _allow_automatic_downloads(self.profile_dir)
                    context = engine.launch_persistent_context(
                        str(self.profile_dir),
                        **options,
                    )
                else:
                    launch_options = dict(options)
                    launch_options.pop("accept_downloads")
                    browser = engine.launch(**launch_options)
                    context = browser.new_context(accept_downloads=True)
                _disable_webrtc(context)
                self.launched_browser = candidate.label
                return context, browser
            except Exception as exc:  # noqa: BLE001 - each candidate is an independent fallback
                for closable in (context, browser):
                    if closable is not None:
                        try:
                            closable.close()
                        except Exception:  # noqa: BLE001 - failed-launch teardown is best effort
                            pass
                detail = (
                    str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
                )
                failures.append(f"{candidate.label}: {detail}")

        hint = (
            "Install Google Chrome or run `uv run python -m playwright install chromium`."
            if self.engine == "windows"
            else "Run `uv run python -m playwright install chromium` if the bundled browser "
            "is missing."
        )
        raise CaptureBrowserError(f"could not launch {self.engine}: {'; '.join(failures)}. {hint}")

    def _wire_downloads(self, page) -> None:
        with self._download_lock:
            if any(wired is page for wired in self._wired_pages):
                return
            # Keep the object, not id(page): a long-lived browser can collect a closed page and
            # later reuse its numeric id for a new popup. Remembering only the id would silently
            # leave that new page without a download handler.
            self._wired_pages.append(page)

        def record_download(download) -> None:
            try:
                self._on_download(download, page=page)
            except CaptureBrowserError as exc:
                # Event callbacks are a separate control-flow path. Raising here is not observed
                # by the capture wait and used to turn an immediate save failure into a dishonest
                # 120-second "no file arrived" timeout. Keep it for the owning attempt to read.
                with self._download_lock:
                    self._download_errors.append(exc)

        page.on("download", record_download)

    def _broker_for_page(self, page) -> DownloadBroker | None:
        return self._broker_for_page_with_route(page)[0]

    def _broker_for_page_with_route(self, page) -> tuple[DownloadBroker | None, str]:
        """The owning task, AND which of the three paths found it.

        Which path resolved a download's task is exactly the question "the vendor download did
        not produce a file" could never answer: a direct binding, an opener walk, and the
        single-task fallback all end in the same receipt, but only one of them means the provider
        behaved as measured. The route name is diagnostics only - the returned broker is
        unchanged.
        """

        current = page
        depth = 0
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            with self._download_lock:
                broker = next(
                    (bound for wired, bound in self._page_brokers if wired is current),
                    None,
                )
            if broker is not None:
                return broker, ("direct-binding" if depth == 0 else f"opener-walk({depth})")
            opener = getattr(current, "opener", None)
            try:
                current = opener() if callable(opener) else None
            except Exception:  # noqa: BLE001 - an unreadable opener is simply unbound
                current = None
            depth += 1
        # Download controls routinely open rel="noopener" windows, and Chromium reports no opener
        # for those. The walk above can never reach the task page from one, so the file fell
        # through to the legacy directory and left broker.receipts empty. One assisted capture
        # window is exclusive, so a single bound task is unambiguously that file's owner.
        with self._download_lock:
            if len(self._page_brokers) == 1:
                return self._page_brokers[0][1], "single-task-fallback"
        return None, "unbound"

    def _on_download(self, download, *, page=None) -> None:
        """Save every download the moment it lands, and record where it went.

        Saved eagerly and unconditionally: Playwright removes a context's downloads on close, and
        a capture that reported a file it can no longer read is the exact "said downloaded before
        the file landed" failure the owner called out.
        """
        name = download.suggested_filename or "cad-download"
        broker, route = (
            self._broker_for_page_with_route(page) if page is not None else (None, "no-page")
        )
        trace(
            "capture.download.event",
            provider=self.provider_key,
            file=name,
            broker=broker is not None,
            via=route,
        )
        if broker is not None:
            try:
                receipt = broker.capture_playwright(download)
            except DownloadBrokerError as exc:
                trace_warning(
                    "capture.download.refused",
                    provider=self.provider_key,
                    file=name,
                    via=route,
                    why=str(exc),
                )
                raise CaptureBrowserError(str(exc)) from exc
            with self._download_lock:
                if all(captured.path != receipt.path for captured in self._captured):
                    self._captured.append(
                        CapturedFile(
                            path=receipt.path,
                            suggested_name=receipt.suggested_name,
                            url=receipt.source_url,
                        )
                    )
            trace(
                "capture.download.saved",
                provider=self.provider_key,
                via=route,
                saved=file_note(receipt.path),
            )
            return

        with self._download_lock:
            dest = _unique(self.download_dir, _safe_filename(name))
            try:
                download.save_as(str(dest))
                if not dest.is_file() or dest.stat().st_size <= 0:
                    raise OSError("saved file is missing or empty")
            except Exception as exc:  # noqa: BLE001 - failed download is an honest capture error
                dest.unlink(missing_ok=True)
                failure = getattr(download, "failure", None)
                reason = failure() if callable(failure) else exc
                trace_warning(
                    "capture.download.failed",
                    provider=self.provider_key,
                    file=name,
                    via=route,
                    why=str(reason),
                )
                raise CaptureBrowserError(
                    f"the vendor download did not complete ({reason}); nothing was saved for "
                    f"{name!r}"
                ) from exc
            self._captured.append(
                CapturedFile(path=dest, suggested_name=name, url=download.url or "")
            )
            trace(
                "capture.download.saved",
                provider=self.provider_key,
                via=route,
                saved=file_note(dest),
                task_bound=False,
            )


def _browser_candidates(engine: str) -> tuple[_BrowserCandidate, ...]:
    if engine == "windows":
        return (
            _BrowserCandidate("Google Chrome", "chromium", "chrome"),
            _BrowserCandidate("Playwright Chromium", "chromium"),
        )
    if engine in {"chrome", "edge", "msedge"}:
        channel = "chrome" if engine == "chrome" else "msedge"
        label = "Google Chrome" if channel == "chrome" else "Microsoft Edge"
        return (_BrowserCandidate(label, "chromium", channel),)
    if engine in {"chromium", "firefox", "webkit"}:
        return (_BrowserCandidate(f"Playwright {engine.title()}", engine),)
    raise CaptureBrowserError(f"unknown browser engine {engine!r}")


def _safe_filename(name: str) -> str:
    """Make a vendor filename portable to Windows without changing its evidence label."""

    leaf = Path(name).name
    safe = _WINDOWS_INVALID_FILENAME.sub("_", leaf).strip(" .")
    if not safe:
        return "cad-download"
    stem = Path(safe).stem[:160].rstrip(" .") or "cad-download"
    suffix = Path(safe).suffix[:20]
    if stem.casefold() in _WINDOWS_RESERVED_NAMES:
        stem = f"_{stem}"
    return f"{stem}{suffix}"


def _validate_capture_url(url: str) -> None:
    if type(url) is not str or not url or url != url.strip():
        raise CaptureBrowserError("capture URL must be non-empty canonical text")
    parsed = urlsplit(url)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        raise CaptureBrowserError("capture URL must be an absolute HTTP or HTTPS provider URL")


def _bounded_seconds(
    value: float,
    label: str,
    *,
    maximum: float,
    allow_zero: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        valid = False
        seconds = 0.0
    else:
        seconds = float(value)
        valid = 0 <= seconds <= maximum if allow_zero else 0 < seconds <= maximum
    if not valid:
        lower = "zero" if allow_zero else "greater than zero"
        raise ValueError(f"{label} must be {lower} and at most {maximum:g}")
    return seconds


def _page_is_closed(page) -> bool:
    is_closed = getattr(page, "is_closed", None)
    if not callable(is_closed):
        return False
    try:
        return bool(is_closed())
    except Exception:  # noqa: BLE001 - a torn-down page is closed for lifecycle purposes
        return True


def _page_url(page, fallback: str) -> str:
    try:
        current = getattr(page, "url", "")
    except Exception:  # noqa: BLE001 - page closure must not erase the last known provider URL
        return fallback
    return current if isinstance(current, str) and current else fallback


def _unique(directory: Path, name: str) -> Path:
    """A collision-free path inside `directory`.

    Vendors name every export the same (`<MPN>.zip`), so a second format's download would
    otherwise overwrite the first while it is still being read - a failure already observed live
    on 2026-07-23 with the WebView2 path, and worth carrying over rather than re-learning.
    """
    stem = Path(name).stem or "cad-download"
    suffix = Path(name).suffix
    dest = directory / f"{stem}{suffix}"
    counter = 2
    while dest.exists():
        dest = directory / f"{stem}-{counter}{suffix}"
        counter += 1
    return dest


def chromium_unavailable_reason() -> str | None:
    """None when a browser really can launch, else the REAL reason it cannot.

    Returns the reason rather than a bool because the first version of this returned False for
    every cause and its callers all printed "chromium is not installed". That was FALSE: the
    actual failure was `ENOENT ... mkdtemp '/dev/shm/srtest/...'` - a TMPDIR that did not exist -
    and the invented explanation sent the diagnosis in the wrong direction entirely. A check that
    reports a cause it did not establish is worse than one that reports nothing.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        return f"playwright is not importable ({exc})"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            browser.close()
        return None
    except Exception as exc:  # noqa: BLE001 - report whatever actually went wrong
        detail = str(exc).strip().splitlines()[0][:200] if str(exc).strip() else type(exc).__name__
        return f"chromium could not launch: {detail}"


def chromium_available() -> bool:
    """Convenience wrapper. Prefer `chromium_unavailable_reason()` where a message is shown."""
    return chromium_unavailable_reason() is None


def default_profile_dir(app_data: Path) -> Path:
    """Where vendor logins persist, per machine.

    PER-MACHINE ON PURPOSE, and it is the allowed kind: it holds credentials/session cookies only,
    never anything that changes what the library renders, so it cannot break device parity the way
    a per-machine enrich cache does.
    """
    return Path(app_data) / "capture-profile"


def clear_profile(profile_dir: Path) -> bool:
    """Delete the persisted vendor sessions. True when something was removed."""
    profile_dir = Path(profile_dir)
    if not profile_dir.exists():
        return False
    shutil.rmtree(profile_dir, ignore_errors=True)
    return not profile_dir.exists()
