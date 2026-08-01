"""The DE-AUTOMATED provider transport: the person's OWN browser, with nothing attached to it.

WHY THIS MODULE EXISTS
DigiKey sits behind Cloudflare. Person-driven capture used to open the provider page in a
Playwright-controlled Camoufox session, so ``navigator.webdriver``, a CDP endpoint and automation
launch flags were all present while a PERSON did the clicking. Cloudflare read that, correctly, as
an automated session and put the owner in an endless verification loop.

THE FIX IS REMOVAL, NOT DISGUISE. There is no fingerprint spoofing, stealth patch, UA/canvas/WebGL
mask or CAPTCHA handling anywhere in this module, and there must never be. On a person-driven route
Stockroom hands the already-validated https URL to the operating system's default handler and walks
away. The session that reaches DigiKey is the owner's real browser, with their real profile,
cookies and history, because it IS their browser - nothing here would survive a bot check being
deceived, and nothing here depends on one.

WHAT IS GIVEN UP, AND WHAT REPLACES IT

  * *The HUD.* Stockroom cannot draw an overlay in a window it does not own, and will not try.
    ``handoff_guidance`` produces the same ordered required-file checklist and provider instruction
    as structured data for STOCKROOM'S OWN UI, which the person can read while they are away.
  * *Provider control.* Nothing here clicks, fills, selects a format or accepts terms. That was
    already the person's job on these routes and it stays exactly that.
  * *The task-bound ``save_as``.* Playwright's download API cannot exist here, so the person's
    Downloads directory is snapshotted BEFORE the handoff and only entries that appear afterwards
    are eligible.

THE DOWNLOADS WATCHER, AND THE FAILURE IT MUST NOT REPEAT
The pre-rewrite implementation was deleted because a global Downloads watcher "could not bind a
downloaded file reliably to the task that requested it" (see the note at the top of
``capture/browser.py``). Three things keep that from happening again, and none of them is a guess:

  1. **Nothing pre-existing is ever swept.** The baseline is every entry present at the instant
     before the browser opens; a path in the baseline is permanently ineligible.
  2. **Nothing half-written is ever taken.** A ``.crdownload``/``.part``/``.tmp``-class suffix is
     never a landed file, and a candidate must present the same size AND mtime across a bounded
     stability window before it is even a candidate.
  3. **Every adoption is EXPLICIT and REVERSIBLE.** The original is COPIED, never moved, so the
     person's own file stays exactly where their browser put it. Each adoption appends one line to
     ``handoff-adoptions.jsonl`` naming the part, the route, the original path, the staged path and
     the digest - so "undo this" is: delete the staged path named on that line. The bytes then go
     through the UNCHANGED inspection and identity gates in ``guided.py``, which is what actually
     decides whether a file is attached; a filename never attaches anything.

TRANSPORT SELECTION IS CAPABILITY DATA
``select_transport`` reads ``VendorCapability``, never a provider name. A route Stockroom is
authorized to drive keeps Playwright; a person-driven route gets this. The decision is emitted as
one ``capture.transport`` trace line at the point of use.

NOT A REGISTERED BROWSER LAUNCHER
``tests/backend/capture/test_one_tool_per_job.py`` registers modules that LAUNCH a browser -
profiles, engines, download handling, teardown. This module launches nothing: it asks the operating
system to open a URL and owns none of the resulting window's lifecycle, which is precisely the
property that makes the session a person's rather than a robot's.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from stockroom.capture.browser import (
    ProviderHudSpec,
    UserCaptureResult,
    UserCaptureStatus,
    exclusive_user_capture_window,
)
from stockroom.capture.download_broker import DownloadBroker, DownloadBrokerError
from stockroom.capture.identity import provider_url_allowed
from stockroom.capture.trace import file_note, trace, trace_debug, trace_warning, url_note

TransportName = Literal["playwright", "default-browser"]

TRANSPORT_PLAYWRIGHT: TransportName = "playwright"
TRANSPORT_DEFAULT_BROWSER: TransportName = "default-browser"

# Suffixes every mainstream browser and download manager uses for a file it is still writing.
# A name ending in one of these is NEVER a landed file, whatever its size looks like.
_PARTIAL_SUFFIXES = frozenset(
    {
        ".crdownload",
        ".download",
        ".opdownload",
        ".part",
        ".partial",
        ".tmp",
        ".temp",
        ".!ut",
        ".bc!",
    }
)

# The Downloads known folder, so a person who moved theirs off the home directory still works.
_DOWNLOADS_GUID = "{374DE290-123F-4565-9164-39C4925E467B}"
_SHELL_FOLDERS = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"

_LEDGER_NAME = "handoff-adoptions.jsonl"


class HandoffError(RuntimeError):
    """Something the caller must fix, phrased so the message names the actual blocker."""


# --- transport selection -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TransportChoice:
    """WHICH transport one route gets, and the capability fact that decided it."""

    name: TransportName
    why: str

    def __post_init__(self) -> None:
        if self.name not in (TRANSPORT_PLAYWRIGHT, TRANSPORT_DEFAULT_BROWSER):
            raise ValueError("transport name must be a declared transport")
        if type(self.why) is not str or not self.why or self.why != self.why.strip():
            raise ValueError("transport reason must be exact non-empty text")


def select_transport(capability, *, person_driven: bool) -> TransportChoice:
    """Pick a transport from CAPABILITY DATA. Never from a provider name or a URL.

    Two facts decide it, in this order:

      * ``browser_access == "machine_allowed"`` means this route was separately reviewed and
        Stockroom is permitted to operate its controls. Stockroom needs a page it owns, so it keeps
        Playwright regardless of which lane the run is in.
      * otherwise, whether STOCKROOM or the PERSON is working the page. In the explicit
        operator-authorized lane Stockroom itself drives ordinary export controls, which again
        needs a page it owns. Only when the person is doing the clicking does the automation come
        off entirely - which is the whole point: the session must genuinely not be
        automation-controlled, because a real person is in it.
    """

    access = str(getattr(capability, "browser_access", "") or "")
    if access == "machine_allowed":
        return TransportChoice(
            TRANSPORT_PLAYWRIGHT,
            "browser_access=machine_allowed; stockroom is authorized to drive this route",
        )
    if not person_driven:
        return TransportChoice(
            TRANSPORT_PLAYWRIGHT,
            "operator-authorized lane; stockroom operates this route's export controls",
        )
    return TransportChoice(
        TRANSPORT_DEFAULT_BROWSER,
        "browser_access=user_driven; the person drives this route, so no automation is attached",
    )


def trace_transport(choice: TransportChoice, *, provider_key: str, engine: str = "") -> None:
    """One durable line naming the transport and why, at the point the choice is acted on."""

    trace(
        "capture.transport",
        provider=provider_key,
        transport=choice.name,
        why=choice.why,
        engine=engine or "none",
        automation_attached=choice.name == TRANSPORT_PLAYWRIGHT,
    )


# --- the origin gate, which runs BEFORE anything is handed to the operating system --------------


def validated_provider_url(provider_key: str, url: str) -> str:
    """Return ``url`` only if it is an exact https URL on this provider's OFFICIAL origin.

    Handing a string to the operating system's handler is handing it to whatever program claims
    that scheme, so this is deliberately narrower than "looks like a link": https only, an
    allow-listed provider host only, no embedded credentials. Everything else raises, and the
    caller never reaches the launch.
    """

    if type(url) is not str or not url or url != url.strip():
        raise HandoffError("the provider URL must be exact non-empty text")
    try:
        parsed = urlsplit(url)
    except Exception as exc:  # noqa: BLE001 - an unparseable URL is refused, never opened
        raise HandoffError("the provider URL could not be read") from exc
    if parsed.scheme.casefold() != "https":
        raise HandoffError(
            "only an https provider URL may be opened in the person's browser; "
            f"{parsed.scheme or 'a scheme-less URL'} was refused"
        )
    if not provider_url_allowed(provider_key, url):
        raise HandoffError(
            f"the resolved URL is outside {provider_key!r}'s official provider origin; "
            "the handoff was refused"
        )
    return url


def _hand_to_operating_system(url: str) -> None:
    """Ask the OS to open an ALREADY VALIDATED https URL in the person's default browser.

    No shell string is built, so there is nothing to quote or escape wrong. ``os.startfile`` is the
    Windows shell handler; everywhere else ``webbrowser`` resolves the desktop's default and
    invokes it with an argument list.
    """

    starter = getattr(os, "startfile", None)
    if starter is not None:
        starter(url)
        return
    import webbrowser

    if not webbrowser.open(url, new=2, autoraise=True):
        raise HandoffError("the operating system reported no default browser for this URL")


# --- the person's Downloads directory ------------------------------------------------------------


def downloads_directory() -> Path:
    """Where the person's own browser puts files. Overridable, and never guessed twice."""

    override = str(os.environ.get("STOCKROOM_DOWNLOADS_DIR", "") or "").strip()
    if override:
        return Path(override)
    known = _windows_downloads_folder()
    if known is not None:
        return known
    return Path.home() / "Downloads"


def _windows_downloads_folder() -> Path | None:
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _SHELL_FOLDERS) as key:
            value, _kind = winreg.QueryValueEx(key, _DOWNLOADS_GUID)
    except OSError:
        return None
    expanded = os.path.expandvars(str(value or "")).strip()
    return Path(expanded) if expanded else None


@dataclass(frozen=True, slots=True)
class HandoffCandidate:
    """One file that appeared after the handoff and has finished being written."""

    path: Path
    size_bytes: int


class DownloadsHandoff:
    """Watch ONE directory for files that appear after a snapshot and settle.

    Deliberately dumb about content: it decides only *did a new file finish landing*. Whether that
    file has anything to do with the requested part is decided later, by the unchanged inspection
    and identity gates - which is the split the retired implementation did not have.
    """

    def __init__(
        self,
        directory,
        *,
        stable_seconds: float = 1.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            isinstance(stable_seconds, bool)
            or not isinstance(stable_seconds, (int, float))
            or not 0 < float(stable_seconds) <= 60
        ):
            raise ValueError("stable_seconds must be between zero and 60")
        self._directory = Path(directory)
        self._stable_seconds = float(stable_seconds)
        self._monotonic = monotonic
        self._baseline: frozenset[str] = frozenset()
        self._snapshotted = False
        self._observed: dict[str, tuple[int, int]] = {}
        self._observed_at: dict[str, float] = {}
        self._reported: set[str] = set()

    @property
    def directory(self) -> Path:
        return self._directory

    def snapshot(self) -> int:
        """Freeze what is ALREADY there. Everything in it is permanently ineligible."""

        self._baseline = frozenset(self._entries())
        self._snapshotted = True
        trace_debug(
            "capture.handoff.snapshot",
            existing=len(self._baseline),
            directory=self._directory.name,
        )
        return len(self._baseline)

    def pending(self) -> int:
        """How many new files have been sighted but have not settled yet."""

        return sum(1 for key in self._observed if key not in self._reported)

    def settling(self) -> bool:
        """Is a new file still ARRIVING - either part-written, or sighted but not yet stable?

        The completeness rule finishes a person-driven capture without a click, so it must never
        fire while the person's browser is mid-write. Two sightings answer that, and both are the
        watcher's existing facts rather than a new guess: a ``.crdownload``-class name that is not
        in the baseline is a download in progress, and a sighted file whose size or mtime is still
        moving is the same download one step later. Either one means WAIT.
        """

        if any(key not in self._reported for key in self._observed):
            return True
        for key in self._entries():
            if key in self._baseline:
                continue
            if Path(key).suffix.casefold() in _PARTIAL_SUFFIXES:
                return True
        return False

    def collect(self) -> tuple[HandoffCandidate, ...]:
        """Every new file that has settled since the last call. Each is reported exactly once."""

        if not self._snapshotted:
            raise HandoffError("the Downloads directory must be snapshotted before it is watched")
        now = self._monotonic()
        landed: list[HandoffCandidate] = []
        for key in self._entries():
            if key in self._baseline or key in self._reported:
                continue
            path = Path(key)
            if path.suffix.casefold() in _PARTIAL_SUFFIXES:
                continue
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                stat = path.stat()
            except OSError:
                continue
            if stat.st_size <= 0:
                continue
            fingerprint = (int(stat.st_size), int(stat.st_mtime_ns))
            if self._observed.get(key) != fingerprint:
                self._observed[key] = fingerprint
                self._observed_at[key] = now
                continue
            if now - self._observed_at[key] < self._stable_seconds:
                continue
            self._reported.add(key)
            landed.append(HandoffCandidate(path=path, size_bytes=fingerprint[0]))
        return tuple(landed)

    def _entries(self) -> Iterable[str]:
        try:
            return [str(entry) for entry in self._directory.iterdir()]
        except OSError:
            return []


# --- the transport itself ------------------------------------------------------------------------


class DefaultBrowserCapture:
    """Open one validated provider URL in the PERSON'S browser and adopt what they downloaded.

    Interface-compatible with ``PlaywrightCaptureBrowser.capture_user_downloads`` so the guided
    source needs no per-transport branch at the call site. What it deliberately does NOT share is
    ownership: there is no window to close, no page to read, and no control to operate.
    """

    launched_browser = "the person's own default browser"
    owns_window = False

    def __init__(
        self,
        *,
        provider_key: str,
        downloads_dir=None,
        open_url: Callable[[str], None] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        stable_seconds: float = 1.0,
        ledger_path=None,
    ) -> None:
        if type(provider_key) is not str or not provider_key.strip():
            raise ValueError("provider_key must be exact non-empty text")
        self._provider_key = provider_key.strip().casefold()
        self._downloads_dir = Path(downloads_dir) if downloads_dir is not None else None
        self._open_url = open_url or _hand_to_operating_system
        self._monotonic = monotonic
        self._sleep = sleep
        self._stable_seconds = float(stable_seconds)
        self._ledger_path = Path(ledger_path) if ledger_path is not None else None
        self.closed_windows = 0

    @property
    def downloads_dir(self) -> Path:
        if self._downloads_dir is None:
            self._downloads_dir = downloads_directory()
        return self._downloads_dir

    def close(self) -> None:
        """A no-op, ON PURPOSE. The window belongs to the person; Stockroom never closes it."""

    def capture_user_downloads(
        self,
        url: str,
        broker: DownloadBroker,
        *,
        hud: ProviderHudSpec | None = None,
        should_finish: Callable[[], bool] | None = None,
        should_cancel: Callable[[], bool] | None = None,
        timeout_s: float = 600.0,
        poll_interval_s: float = 0.5,
        settle_seconds: float = 0.75,
        auto_finish_seconds: float = 2.0,
        auto_finish_idle_seconds: float = 25.0,
        **_ignored_playwright_options: object,
    ) -> UserCaptureResult:
        """Hand the page over, watch Downloads for the window, and adopt what settles.

        HOW THIS ENDS WITHOUT A CLICK, AND WHY THAT IS SAFE
        The Playwright path already answers this shape: the HUD names how many files a route must
        come home with, and capture finishes once that many have landed and a short quiet period
        passes, with a longer idle gap as the backstop for a provider that packs several formats
        into one archive. The rule here is the SAME one, reused rather than reinvented - but it is
        deliberately more conservative in two places, because this transport knows less:

          * It adopts FILES out of the person's Downloads directory and cannot tell which format
            any of them holds until ingest classifies them, so the count is the only completeness
            signal available. A route with no ``hud`` therefore declares nothing to be complete
            against and never finishes early at all.
          * ``settling`` must be quiet too. A part-written download, or one whose bytes are still
            moving, holds the rule open - finishing while the person's browser is mid-write is the
            one failure that would lose a format they were still fetching.

        THE IDLE BACKSTOP STAYS DOMINANT. Fewer receipts than labels is the normal case for an
        archive provider and can never satisfy the count, so anything short of the full count still
        waits out ``auto_finish_idle_seconds`` exactly as before. ``should_finish`` - the person's
        own Finish Route - remains the explicit override; this removes the NEED to press it, never
        the ability.
        """

        if type(broker) is not DownloadBroker:
            raise HandoffError("a task-bound DownloadBroker is required")
        if hud is not None and type(hud) is not ProviderHudSpec:
            raise HandoffError("hud must be a ProviderHudSpec")
        if hud is not None and (
            hud.manufacturer != broker.task.manufacturer_key
            or hud.mpn != broker.task.mpn_canonical
        ):
            raise HandoffError("provider guidance identity must exactly match its download task")
        timeout = _bounded(timeout_s, "timeout_s", maximum=3600.0)
        poll = _bounded(poll_interval_s, "poll_interval_s", maximum=5.0)
        settle = _bounded(settle_seconds, "settle_seconds", maximum=30.0)
        complete_quiet = _bounded(auto_finish_seconds, "auto_finish_seconds", maximum=30.0)
        idle = _bounded(auto_finish_idle_seconds, "auto_finish_idle_seconds", maximum=600.0)

        # The gate runs FIRST, so a refused URL never reaches the operating system.
        open_url = validated_provider_url(self._provider_key, url)

        if should_cancel is not None and should_cancel():
            trace(
                "capture.handoff.result",
                provider=self._provider_key,
                status="cancelled",
                why="cancelled",
                files=0,
                opened=False,
            )
            return UserCaptureResult(status="cancelled", files=(), final_url=open_url)

        # The SAME process-wide exclusion the Playwright person-driven path takes. One person works
        # one provider page at a time, and two concurrent watchers over one Downloads directory is
        # exactly how the retired implementation bound a file to the wrong task.
        with exclusive_user_capture_window():
            return self._watch_and_adopt(
                open_url,
                broker,
                hud=hud,
                should_finish=should_finish,
                should_cancel=should_cancel,
                timeout=timeout,
                poll=poll,
                settle=settle,
                complete_quiet=complete_quiet,
                idle=idle,
            )

    def _watch_and_adopt(
        self,
        open_url: str,
        broker: DownloadBroker,
        *,
        hud: ProviderHudSpec | None,
        should_finish: Callable[[], bool] | None,
        should_cancel: Callable[[], bool] | None,
        timeout: float,
        poll: float,
        settle: float,
        complete_quiet: float,
        idle: float,
    ) -> UserCaptureResult:
        watch = DownloadsHandoff(
            self.downloads_dir,
            stable_seconds=self._stable_seconds,
            monotonic=self._monotonic,
        )
        existing = watch.snapshot()
        trace(
            "capture.handoff.open",
            provider=self._provider_key,
            route=broker.task.evidence_provider_key,
            task=broker.task.task_id,
            url=url_note(open_url),
            downloads_existing=existing,
            required_files=len(hud.required_file_labels) if hud is not None else 0,
            automation_attached=False,
        )
        self._open_url(open_url)

        # How many files this route declared it must come home with. Without a HUD there is nothing
        # to be complete against, so the count rule below is switched off entirely and the idle
        # backstop is the only automatic ending - the same shape the Playwright path takes.
        expected = len(hud.required_file_labels) if hud is not None else 0

        deadline = self._monotonic() + timeout
        drain_deadline: float | None = None
        last_landing: float | None = None
        status: UserCaptureStatus = "timed_out"
        why = "timeout"
        while True:
            now = self._monotonic()
            if should_cancel is not None and should_cancel():
                status = "cancelled"
                why = "cancelled"
                break
            for candidate in watch.collect():
                if self._adopt(candidate, broker):
                    last_landing = now
            if drain_deadline is not None:
                if watch.pending() == 0 or now >= drain_deadline:
                    status = "completed"
                    why = "person-finished"
                    break
            elif should_finish is not None and should_finish():
                # The person said they are done, but a file they started may still be landing.
                drain_deadline = now + self._stable_seconds + settle
                continue
            elif last_landing is not None and broker.receipts:
                quiet = now - last_landing
                if (
                    expected > 0
                    and len(broker.receipts) >= expected
                    and not watch.settling()
                    and quiet >= complete_quiet
                ):
                    # Everything this route asked for has landed, nothing else is part-way through,
                    # and the directory has been still for a moment. The person does not have to
                    # press Finish Route to say what Stockroom can already see.
                    status = "completed"
                    why = "required-files-landed"
                    break
                if quiet >= idle:
                    # Fewer files than labels is the ordinary shape for a provider that ships
                    # several required formats inside one archive, and a filename tells this
                    # transport nothing about which formats it holds. Wait out the long gap rather
                    # than finish early and lose a format the person was still fetching.
                    status = "completed"
                    why = "downloads-idle"
                    break
            if now >= deadline:
                status = "timed_out"
                why = "timeout"
                break
            self._sleep(poll)

        files = broker.receipts
        trace(
            "capture.handoff.result",
            provider=self._provider_key,
            route=broker.task.evidence_provider_key,
            status=status,
            why=why,
            files=len(files),
            required_files=expected,
            names=[file_note(receipt.path) for receipt in files],
            window_owned=False,
        )
        return UserCaptureResult(status=status, files=files, final_url=open_url)

    def _adopt(self, candidate: HandoffCandidate, broker: DownloadBroker) -> bool:
        """COPY one settled file into the task's staging directory and ledger the adoption.

        The original is never moved and never deleted, which is what makes this reversible: the
        person's own download stays where their browser put it, and the ledger line names the
        staged copy that undoing an adoption removes.
        """

        try:
            receipt = broker.capture_local_file(
                candidate.path,
                transport=TRANSPORT_DEFAULT_BROWSER,
            )
        except (DownloadBrokerError, OSError) as exc:
            trace_warning(
                "capture.handoff.rejected",
                provider=self._provider_key,
                file=file_note(candidate.path),
                why=type(exc).__name__,
            )
            return False
        self._ledger(broker, candidate, receipt)
        trace(
            "capture.handoff.adopted",
            provider=self._provider_key,
            route=broker.task.evidence_provider_key,
            task=broker.task.task_id,
            file=file_note(receipt.path),
            source=candidate.path.name,
            bytes=receipt.size_bytes,
            reversible=True,
        )
        return True

    def _ledger_destination(self, broker: DownloadBroker) -> Path:
        if self._ledger_path is not None:
            return self._ledger_path
        return Path(broker.task.staging_root) / _LEDGER_NAME

    def _ledger(
        self,
        broker: DownloadBroker,
        candidate: HandoffCandidate,
        receipt,
    ) -> None:
        """Append the one durable, human-readable record of what was taken and from where."""

        entry = {
            "adopted_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
            "task_id": broker.task.task_id,
            "manufacturer": broker.task.manufacturer_key,
            "mpn": broker.task.mpn_canonical,
            "surface": broker.task.surface_key,
            "route": broker.task.evidence_provider_key,
            "original_path": str(candidate.path),
            "staged_path": str(receipt.path),
            "sha256": receipt.sha256,
            "size_bytes": receipt.size_bytes,
            "transport": receipt.transport,
            "reverse": "delete staged_path; original_path was copied, never moved",
        }
        destination = self._ledger_destination(broker)
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("a", encoding="utf-8") as ledger:
                ledger.write(json.dumps(entry, sort_keys=True) + "\n")
        except OSError:
            # A ledger that cannot be written is a diagnostic loss, never a reason to lose the
            # file the person already downloaded. The trace line above still records the adoption.
            trace_warning(
                "capture.handoff.ledger-unwritable",
                provider=self._provider_key,
                task=broker.task.task_id,
            )


def _bounded(value: object, label: str, *, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HandoffError(f"{label} must be a number")
    number = float(value)
    if not 0 < number <= maximum:
        raise HandoffError(f"{label} must be between zero and {maximum}")
    return number


# --- the guidance Stockroom's OWN ui shows while the person is away -------------------------------


def handoff_guidance(
    vendor_key: str,
    *,
    needs: Sequence[str],
    manufacturer: str = "",
    mpn: str = "",
) -> dict | None:
    """The ordered required-file checklist and provider instruction, as plain data.

    This is the HUD's content without the HUD. Stockroom cannot draw an overlay inside a browser it
    does not control and will not try, so the same facts are published here for Stockroom's own
    window: which provider page opened, which CAD author route it belongs to, what the provider
    asks the person to do, and - in the order the person works through them - the exact file
    choices this part still needs.

    Returns ``None`` for a provider with no capture adapter, so a surface can never render guidance
    for a route that has no implementation behind it.
    """

    # Imported here on purpose: `guided` imports this module for the transport, so reusing its
    # route/label helpers at module scope would be a cycle. Reusing them is the point - the
    # checklist a person reads must be produced by the SAME code that built the HUD's.
    from stockroom.capture.guided import (
        _author_key,
        _capture_routes,
        _provider_formats,
        _provider_hud_author_route,
        _provider_hud_labels,
    )
    from stockroom.capture.requirements import Requirement
    from stockroom.capture.vendors import get_adapter

    adapter = get_adapter(vendor_key)
    if adapter is None:
        return None
    requirements = []
    for value in needs or ():
        try:
            requirements.append(Requirement(value))
        except ValueError:
            continue
    capability = adapter.capability
    choice = select_transport(capability, person_driven=True)
    person_driven = choice.name == TRANSPORT_DEFAULT_BROWSER
    routes = []
    for route in _capture_routes(adapter):
        formats = _provider_formats(route, requirements)
        if not formats:
            continue
        routes.append(
            {
                "route": f"{capability.key}:{_author_key(capability.key, route)}",
                "label": route.capability.label,
                "author_route": _provider_hud_author_route(route),
                "instruction": route.capability.instruction,
                "required_files": list(_provider_hud_labels(route, formats)),
            }
        )
    return {
        "provider": capability.key,
        "provider_label": capability.label,
        "instruction": capability.instruction,
        "manufacturer": manufacturer,
        "mpn": mpn,
        "transport": choice.name,
        "why": choice.why,
        "opens_in": (
            "your own default browser" if person_driven else "a Stockroom-controlled window"
        ),
        "downloads_dir": str(downloads_directory()) if person_driven else "",
        "routes": routes,
    }


__all__ = [
    "TRANSPORT_DEFAULT_BROWSER",
    "TRANSPORT_PLAYWRIGHT",
    "DefaultBrowserCapture",
    "DownloadsHandoff",
    "HandoffCandidate",
    "HandoffError",
    "TransportChoice",
    "TransportName",
    "downloads_directory",
    "handoff_guidance",
    "select_transport",
    "trace_transport",
    "validated_provider_url",
]
