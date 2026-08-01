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

ONE CAPTURE, KEYED BY ITS PART
``capture/browser.py::exclusive_user_capture_window`` permits at most one person-driven window per
process, and the API refuses assisted or collect-all capture for anything but one selected part. An
intent is therefore registered under that one part id for exactly the life of its run, and a signal
naming a part with no running capture is REFUSED rather than remembered: a remembered signal would
silently end the next run the person started, which is precisely the class of bug that makes a
control untrustworthy.

FINISH IS CONSUMED, SKIP IS LATCHED
"I am finished with this route" is answered ONCE, by whichever route is open when it is polled. A
latched finish would end every later route of the same part without the person ever asking again -
one click would close all five DigiKey routes. "Skip this part" is a verdict on the whole part, so
it stays true for the rest of the run and reaches the runner exactly the way a cancellation does.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from stockroom.capture.trace import trace, trace_warning

FINISH_ROUTE = "finish-route"
SKIP_PART = "skip-part"
PERSON_CAPTURE_ACTIONS = frozenset({FINISH_ROUTE, SKIP_PART})


class PersonCaptureIntentError(RuntimeError):
    """A person-driven signal that names no running capture, or a doubly-claimed part."""


class PersonCaptureIntent:
    """One run's record of what the person said about the capture in front of them."""

    def __init__(self, part_id: str | None = None) -> None:
        self.part_id = part_id
        self._guard = threading.Lock()
        self._finish_route = False
        self._skip_part = False

    # -- what the person says ----------------------------------------------------------------

    def finish_route(self) -> None:
        """No more files are coming from the page in front of the person."""

        with self._guard:
            self._finish_route = True

    def skip_part(self) -> None:
        """Stop this part's remaining provider routes and move on."""

        with self._guard:
            self._skip_part = True

    # -- what the running capture polls ------------------------------------------------------

    def take_route_finish(self) -> bool:
        """True once per raised finish, for the route that is open when it is polled.

        Consumed rather than latched on purpose. ``capture_user_downloads`` stops consulting
        ``should_finish`` the moment it fires, so one answer per route is exactly enough - and a
        value left standing would end the NEXT route of the same part with nobody asking it to.
        """

        with self._guard:
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
) -> Iterator[PersonCaptureIntent]:
    """Publish one run's intent under its part id for exactly the life of that run.

    ``part_id`` is None for a library-wide automatic pass, which opens no person-driven window and
    therefore has nothing for a person to finish or skip. Such a run keeps its intent object - the
    runner's predicates read it unconditionally - but never publishes it, so no signal can reach it.
    """

    if part_id is None:
        yield intent
        return
    key = str(part_id)
    with _REGISTRY_GUARD:
        if key in _RUNNING:
            # The same invariant `production_composition.capture_scope` enforces: one exact part
            # owns one capture. Two runs sharing a part id would make "finish the route in front
            # of me" ambiguous, and an ambiguous person-driven control is worse than none.
            raise PersonCaptureIntentError(
                f"a guided capture is already running for part {key!r}"
            )
        intent.part_id = key
        _RUNNING[key] = intent
    try:
        yield intent
    finally:
        with _REGISTRY_GUARD:
            if _RUNNING.get(key) is intent:
                del _RUNNING[key]


def signal_person_capture(part_id: str, action: str) -> str:
    """Record one person-driven decision against the capture running for ``part_id``.

    Raises rather than remembering when no capture is running for that part. The person is
    describing a window they can see; if Stockroom is not running that capture, saying so is the
    only honest answer.
    """

    if type(part_id) is not str or not part_id.strip():
        raise ValueError("part_id must be exact non-empty text")
    if action not in PERSON_CAPTURE_ACTIONS:
        raise ValueError(f"action must be {FINISH_ROUTE!r} or {SKIP_PART!r}")
    with _REGISTRY_GUARD:
        intent = _RUNNING.get(part_id)
    if intent is None:
        trace_warning("capture.person.refused", part=part_id, action=action)
        raise PersonCaptureIntentError(
            "No person-driven capture is running for this component."
        )
    if action == FINISH_ROUTE:
        intent.finish_route()
        trace("capture.person.finish", part=part_id)
    else:
        intent.skip_part()
        trace("capture.person.skip", part=part_id)
    return action


def running_person_captures() -> tuple[str, ...]:
    """Every part id with a published capture intent right now. Diagnostics only."""

    with _REGISTRY_GUARD:
        return tuple(sorted(_RUNNING))


__all__ = [
    "FINISH_ROUTE",
    "PERSON_CAPTURE_ACTIONS",
    "SKIP_PART",
    "PersonCaptureIntent",
    "PersonCaptureIntentError",
    "person_capture_intent",
    "running_person_captures",
    "signal_person_capture",
]
