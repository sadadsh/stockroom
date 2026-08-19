"""What the PERSON told Stockroom about the person-driven capture in front of them.

WHY THIS MODULE EXISTS
De-automation removed the provider HUD, and with it the only control a person had for saying "I am
done with this page" or "skip this one". A person-driven route then ended on exactly three things:
Stockroom's global Cancel, roughly 25 seconds of quiet after at least one file had landed, or the
600-second timeout. DigiKey fans out to FIVE author routes, so a part where nothing downloads held
the owner for five timeouts in a row, which is the opposite of what de-automation was for.

WHAT THIS IS, AND WHAT IT IS NOT
Every value here is a statement of the PERSON'S OWN intent, made to Stockroom's own window. Nothing
in this module touches a provider page: no click, no navigation, no read, ever. The seams it feeds
already exist - ``capture/handoff.py`` accepts ``should_finish`` beside ``should_cancel``, and
``capture/guided.py`` carries a ``user_finished`` callback - so this is only the place an answer is
kept until the running capture polls for it, on the SAME polled-predicate channel that cancellation
already reaches the runner through.

ONE CAPTURE, KEYED BY ITS DURABLE GENERATION
``capture/browser.py::exclusive_user_capture_window`` permits at most one person-driven window per
process, and the API refuses assisted or collect-all capture for anything but one selected part. An
intent is registered under its opaque workflow item id for exactly the life of its run, and a
signal naming the wrong generation is REFUSED rather than remembered: a remembered signal would
silently end the next run the person started, which is precisely the class of bug that makes a
control untrustworthy.

FINISH IS CONSUMED, SKIP IS LATCHED
"I am finished with this route" is answered ONCE, by whichever route is open when it is polled. A
latched finish would end every later route of the same part without the person ever asking again -
one click would close all five DigiKey routes. "Skip this part" is a verdict on the whole part, so
it stays true for the rest of the run and reaches the runner exactly the way a cancellation does.
"""

from __future__ import annotations

import secrets
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TypedDict, cast

from stockroom.capture.trace import trace, trace_warning

FINISH_ROUTE = "finish-route"
SKIP_PART = "skip-part"
PERSON_CAPTURE_ACTIONS = frozenset({FINISH_ROUTE, SKIP_PART})


class _DownloadProgressFile(TypedDict):
    name: str
    state: str
    bytes_received: int
    total_bytes: int


class _DownloadProgress(TypedDict):
    active: int
    completed: int
    bytes_received: int
    total_bytes: int
    files: list[_DownloadProgressFile]


class PersonCaptureIntentError(RuntimeError):
    """A person-driven signal that names no running capture, or a doubly-claimed part."""


class PersonCaptureIntent:
    """One run's record of what the person said about the capture in front of them."""

    def __init__(self, part_id: str | None = None) -> None:
        self.part_id = part_id
        self.capture_id: str | None = None
        self._guard = threading.Lock()
        self._finish_route = False
        self._skip_part = False
        self._active_route: dict[str, str] | None = None
        self._selected_files: tuple[Path, ...] | None = None
        self._download_progress: _DownloadProgress | None = None
        self._browser_state: dict[str, object] | None = None
        self._attachment_proposal: dict[str, object] | None = None
        self._attachment_apply = False
        self._route_intake_closed = True

    # -- what the person says ----------------------------------------------------------------

    def finish_route(self, route_token: str) -> None:
        """Finish only the exact provider route the person can currently see."""

        with self._guard:
            if (
                self._active_route is None
                or self._route_intake_closed
                or route_token != self._active_route["route_token"]
            ):
                raise PersonCaptureIntentError(
                    "The provider route changed before Finish was received."
                )
            self._finish_route = True

    def skip_part(self) -> None:
        """Stop this part's remaining provider routes and move on."""

        with self._guard:
            self._skip_part = True

    def set_active_route(
        self,
        vendor: str,
        detail_url: str,
        evidence_provider_key: str,
    ) -> str:
        """Publish the exact provider context visible for recovery-file binding."""

        with self._guard:
            route_token = secrets.token_urlsafe(24)
            self._active_route = {
                "vendor": vendor,
                "detail_url": detail_url,
                "evidence_provider_key": evidence_provider_key,
                "route_token": route_token,
            }
            self._selected_files = None
            self._download_progress = None
            self._browser_state = None
            self._route_intake_closed = False
            self._finish_route = False
            return route_token

    def clear_active_route(
        self,
        vendor: str,
        detail_url: str,
        evidence_provider_key: str,
        route_token: str,
    ) -> None:
        with self._guard:
            expected = {
                "vendor": vendor,
                "detail_url": detail_url,
                "evidence_provider_key": evidence_provider_key,
                "route_token": route_token,
            }
            if self._active_route == expected:
                self._active_route = None
                self._selected_files = None
                self._download_progress = None
                self._browser_state = None
                self._route_intake_closed = True

    def active_route(self) -> dict[str, object] | None:
        with self._guard:
            if self._active_route is None:
                return None
            progress = self._download_progress
            return {
                "vendor": self._active_route["vendor"],
                "detail_url": self._active_route["detail_url"],
                "evidence_provider_key": self._active_route["evidence_provider_key"],
                "route_token": self._active_route["route_token"],
                "download_progress": (
                    None if progress is None else {
                        **progress,
                        "files": [dict(item) for item in progress["files"]],
                    }
                ),
                "browser_state": (
                    None if self._browser_state is None else dict(self._browser_state)
                ),
            }

    def set_download_progress(self, progress: dict[str, object]) -> None:
        """Publish path-free native download progress for the active route."""

        expected = {"active", "completed", "bytes_received", "total_bytes", "files"}
        if type(progress) is not dict or set(progress) != expected:
            raise ValueError("download progress fields are invalid")
        counts: dict[str, int] = {}
        for key in ("active", "completed", "bytes_received"):
            value = progress[key]
            if type(value) is not int or value < 0:
                raise ValueError("download progress counts are invalid")
            counts[key] = value
        total_bytes = progress["total_bytes"]
        if type(total_bytes) is not int or total_bytes < -1:
            raise ValueError("download progress total is invalid")
        files = progress["files"]
        if type(files) is not list or len(files) > 100:
            raise ValueError("download progress files are invalid")
        copied_files: list[_DownloadProgressFile] = []
        file_keys = {"name", "state", "bytes_received", "total_bytes"}
        for raw_item in files:
            if type(raw_item) is not dict or set(raw_item) != file_keys:
                raise ValueError("download progress file fields are invalid")
            item = cast(dict[str, object], raw_item)
            name = item["name"]
            state = item["state"]
            received = item["bytes_received"]
            total = item["total_bytes"]
            if (
                type(name) is not str
                or not name
                or len(name) > 255
                or any(ord(character) < 32 or ord(character) == 127 for character in name)
                or type(state) is not str
                or state not in {"in_progress", "completed", "interrupted", "unknown"}
                or type(received) is not int
                or received < 0
                or type(total) is not int
                or total < -1
            ):
                raise ValueError("download progress file values are invalid")
            copied_files.append({
                "name": name,
                "state": state,
                "bytes_received": received,
                "total_bytes": total,
            })
        with self._guard:
            if self._active_route is None or self._route_intake_closed:
                return
            self._download_progress = {
                "active": counts["active"],
                "completed": counts["completed"],
                "bytes_received": counts["bytes_received"],
                "total_bytes": total_bytes,
                "files": copied_files,
            }

    def set_browser_state(self, state: dict[str, object]) -> None:
        """Publish bounded native navigation state without provider document content."""

        expected = {
            "url",
            "loading",
            "navigation_error",
            "can_go_back",
            "can_go_forward",
        }
        if type(state) is not dict or set(state) != expected:
            raise ValueError("provider browser state fields are invalid")
        url = state["url"]
        loading = state["loading"]
        navigation_error = state["navigation_error"]
        can_go_back = state["can_go_back"]
        can_go_forward = state["can_go_forward"]
        if (
            type(url) is not str
            or len(url) > 4096
            or any(ord(character) < 32 or ord(character) == 127 for character in url)
            or type(loading) is not bool
            or type(navigation_error) is not str
            or len(navigation_error) > 512
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in navigation_error
            )
            or type(can_go_back) is not bool
            or type(can_go_forward) is not bool
        ):
            raise ValueError("provider browser state values are invalid")
        with self._guard:
            if self._active_route is None or self._route_intake_closed:
                return
            self._browser_state = {
                "url": url,
                "loading": loading,
                "navigation_error": navigation_error,
                "can_go_back": can_go_back,
                "can_go_forward": can_go_forward,
            }

    def set_attachment_proposal(self, proposal: dict[str, object]) -> str:
        """Publish one validated, non-activating selected-tool mapping proposal."""

        required = {"part_id", "provider", "primary_tool", "attachments", "inactive_evidence"}
        if type(proposal) is not dict or set(proposal) != required:
            raise ValueError("attachment proposal fields are invalid")
        part_id = proposal["part_id"]
        provider = proposal["provider"]
        primary_tool = proposal["primary_tool"]
        attachments = proposal["attachments"]
        inactive = proposal["inactive_evidence"]
        if (
            type(part_id) is not str
            or part_id != self.part_id
            or type(provider) is not str
            or not provider
            or primary_tool not in {"kicad", "altium", "both"}
            or type(attachments) is not list
            or not attachments
            or len(attachments) > 8
            or type(inactive) is not list
            or len(inactive) > 32
        ):
            raise ValueError("attachment proposal values are invalid")
        item_keys = {"role", "file_name", "target"}
        copied_attachments: list[dict[str, str]] = []
        for raw in attachments:
            if type(raw) is not dict or set(raw) != item_keys:
                raise ValueError("attachment proposal item fields are invalid")
            item = cast(dict[str, object], raw)
            if any(type(item[key]) is not str or not item[key] for key in item_keys):
                raise ValueError("attachment proposal item values are invalid")
            copied_attachments.append(cast(dict[str, str], dict(item)))
        copied_inactive: list[dict[str, str]] = []
        for raw in inactive:
            if type(raw) is not dict or set(raw) != {"tool", "file_name"}:
                raise ValueError("inactive attachment evidence fields are invalid")
            item = cast(dict[str, object], raw)
            if (
                item["tool"] not in {"kicad", "altium"}
                or type(item["file_name"]) is not str
                or not item["file_name"]
            ):
                raise ValueError("inactive attachment evidence values are invalid")
            copied_inactive.append(cast(dict[str, str], dict(item)))
        proposal_token = secrets.token_urlsafe(24)
        with self._guard:
            self._attachment_proposal = {
                "proposal_token": proposal_token,
                "part_id": part_id,
                "provider": provider,
                "primary_tool": primary_tool,
                "attachments": copied_attachments,
                "inactive_evidence": copied_inactive,
            }
            self._attachment_apply = False
        return proposal_token

    def attachment_proposal(self) -> dict[str, object] | None:
        with self._guard:
            proposal = self._attachment_proposal
            if proposal is None:
                return None
            return {
                **proposal,
                "attachments": [dict(item) for item in cast(list[dict], proposal["attachments"])],
                "inactive_evidence": [
                    dict(item) for item in cast(list[dict], proposal["inactive_evidence"])
                ],
            }

    def apply_attachment_proposal(self, proposal_token: str) -> None:
        with self._guard:
            if (
                self._attachment_proposal is None
                or proposal_token != self._attachment_proposal["proposal_token"]
            ):
                raise PersonCaptureIntentError(
                    "The attachment proposal changed before Apply was received."
                )
            self._attachment_apply = True

    def take_attachment_apply(self, proposal_token: str) -> bool:
        with self._guard:
            if (
                not self._attachment_apply
                or self._attachment_proposal is None
                or proposal_token != self._attachment_proposal["proposal_token"]
            ):
                return False
            self._attachment_apply = False
            return True

    def clear_attachment_proposal(self, proposal_token: str) -> None:
        with self._guard:
            if (
                self._attachment_proposal is not None
                and proposal_token == self._attachment_proposal["proposal_token"]
            ):
                self._attachment_proposal = None
                self._attachment_apply = False

    def queue_selected_files(
        self,
        *,
        vendor: str,
        detail_url: str,
        route_token: str,
        paths: tuple[Path, ...],
    ) -> None:
        """Queue native-picker paths for the exact route owned by this capture generation."""

        with self._guard:
            if self._active_route is None:
                raise PersonCaptureIntentError("The provider route is no longer active.")
            if (
                vendor != self._active_route["vendor"]
                or detail_url != self._active_route["detail_url"]
                or route_token != self._active_route["route_token"]
            ):
                raise PersonCaptureIntentError(
                    "The provider page changed before these files were selected."
                )
            if self._route_intake_closed or self._selected_files is not None:
                raise PersonCaptureIntentError(
                    "Selected files are already queued for this provider route."
                )
            self._selected_files = paths

    def take_selected_files(
        self,
        vendor: str,
        detail_url: str,
        evidence_provider_key: str,
        route_token: str,
    ) -> tuple[Path, ...]:
        """Consume the paths only inside the exact author route that published the inbox."""

        with self._guard:
            expected = {
                "vendor": vendor,
                "detail_url": detail_url,
                "evidence_provider_key": evidence_provider_key,
                "route_token": route_token,
            }
            if self._active_route != expected:
                return ()
            paths = self._selected_files or ()
            self._selected_files = None
            # This is the route's one atomic drain boundary. Closing even an empty inbox means a
            # request racing after this point is refused instead of accepted and then discarded
            # by route cleanup.
            self._route_intake_closed = True
            return paths

    # -- what the running capture polls ------------------------------------------------------

    def take_route_finish(self) -> bool:
        """True once per raised finish, for the route that is open when it is polled.

        Consumed rather than latched on purpose. ``capture_user_downloads`` stops consulting
        ``should_finish`` the moment it fires, so one answer per route is exactly enough - and a
        value left standing would end the NEXT route of the same part with nobody asking it to.
        """

        with self._guard:
            if self._selected_files is not None:
                self._finish_route = False
                return True
            if not self._finish_route:
                return False
            self._finish_route = False
        trace("capture.person.finish.applied", part=self.part_id or "")
        return True

    def part_skipped(self) -> bool:
        """Whether the person has stopped this part. Latched for the rest of the run."""

        with self._guard:
            return self._skip_part


_REGISTRY_GUARD = threading.Lock()
_RUNNING: dict[str, PersonCaptureIntent] = {}


@contextmanager
def person_capture_intent(
    part_id: str | None,
    intent: PersonCaptureIntent,
    *,
    capture_id: str | None = None,
) -> Iterator[PersonCaptureIntent]:
    """Publish one run's intent under its capture generation for exactly the life of that run.

    ``part_id`` is None for a library-wide automatic pass, which opens no person-driven window and
    therefore has nothing for a person to finish or skip. Such a run keeps its intent object - the
    runner's predicates read it unconditionally - but never publishes it, so no signal can reach it.
    """

    if part_id is None:
        yield intent
        return
    key = str(capture_id or part_id)
    with _REGISTRY_GUARD:
        if key in _RUNNING or any(
            running.part_id == str(part_id) for running in _RUNNING.values()
        ):
            # The same invariant `production_composition.capture_scope` enforces: one exact part
            # owns one capture. Two runs sharing a part id would make "finish the route in front
            # of me" ambiguous, and an ambiguous person-driven control is worse than none.
            raise PersonCaptureIntentError(
                f"a guided capture is already running for part {part_id!r}"
            )
        intent.part_id = str(part_id)
        intent.capture_id = key
        _RUNNING[key] = intent
    try:
        yield intent
    finally:
        with _REGISTRY_GUARD:
            if _RUNNING.get(key) is intent:
                del _RUNNING[key]


def _running_capture(capture_id: str, part_id: str) -> PersonCaptureIntent:
    with _REGISTRY_GUARD:
        intent = _RUNNING.get(capture_id)
    if intent is None or intent.part_id != part_id:
        raise PersonCaptureIntentError(
            "No matching person-driven capture generation is running for this component."
        )
    return intent


def signal_person_capture(
    part_id: str,
    action: str,
    *,
    capture_id: str | None = None,
    route_token: str | None = None,
) -> str:
    """Record one person-driven decision against the capture running for ``part_id``.

    Raises rather than remembering when no capture is running for that part. The person is
    describing a window they can see; if Stockroom is not running that capture, saying so is the
    only honest answer.
    """

    if type(part_id) is not str or not part_id.strip():
        raise ValueError("part_id must be exact non-empty text")
    if action not in PERSON_CAPTURE_ACTIONS:
        raise ValueError(f"action must be {FINISH_ROUTE!r} or {SKIP_PART!r}")
    try:
        intent = _running_capture(capture_id or part_id, part_id)
    except PersonCaptureIntentError:
        trace_warning("capture.person.refused", part=part_id, action=action)
        raise
    if action == FINISH_ROUTE:
        if type(route_token) is not str or not route_token:
            raise ValueError("route_token must name the exact provider route")
        intent.finish_route(route_token)
        trace("capture.person.finish", part=part_id)
    else:
        intent.skip_part()
        trace("capture.person.skip", part=part_id)
    return action


def running_person_captures() -> tuple[str, ...]:
    """Every part id with a published capture intent right now. Diagnostics only."""

    with _REGISTRY_GUARD:
        return tuple(sorted(intent.part_id or "" for intent in _RUNNING.values()))


def active_person_capture(capture_id: str, *, part_id: str) -> dict[str, object] | None:
    """Return the provider route currently visible for one running capture."""

    try:
        return _running_capture(capture_id, part_id).active_route()
    except PersonCaptureIntentError:
        return None


def active_attachment_proposal(
    capture_id: str,
    *,
    part_id: str,
) -> dict[str, object] | None:
    try:
        return _running_capture(capture_id, part_id).attachment_proposal()
    except PersonCaptureIntentError:
        return None


def apply_person_capture_attachments(
    capture_id: str,
    *,
    part_id: str,
    proposal_token: str,
) -> None:
    _running_capture(capture_id, part_id).apply_attachment_proposal(proposal_token)


def queue_person_capture_files(
    capture_id: str,
    *,
    part_id: str,
    vendor: str,
    detail_url: str,
    route_token: str,
    paths: tuple[Path, ...],
) -> None:
    """Wake one exact durable capture route with person-selected local files."""

    _running_capture(capture_id, part_id).queue_selected_files(
        vendor=vendor,
        detail_url=detail_url,
        route_token=route_token,
        paths=paths,
    )


__all__ = [
    "FINISH_ROUTE",
    "PERSON_CAPTURE_ACTIONS",
    "SKIP_PART",
    "PersonCaptureIntent",
    "PersonCaptureIntentError",
    "active_attachment_proposal",
    "active_person_capture",
    "apply_person_capture_attachments",
    "person_capture_intent",
    "queue_person_capture_files",
    "running_person_captures",
    "signal_person_capture",
]
