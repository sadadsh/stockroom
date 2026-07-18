"""Honest per-stage progress for the enrichment pipeline (spec section 8).

A background job hands the pipeline a `progress(dict)` sink; the pipeline and its
sources emit `{"stage", "pct", "message"}` events at the REAL boundaries of the
work: `fetching -> rendering -> extracting -> validating`. Nothing here is
theatrical: a stage fires only when that phase actually begins, the render stage
is signalled by the fetcher/engine (the one phase the pipeline cannot observe from
outside), and `monotonic` keeps the reported pct from rewinding when a later source
in a multi-source walk re-emits a low local pct. A None sink makes every helper a
no-op, so the default synchronous callers are untouched."""

from __future__ import annotations

from typing import Callable, Optional

# A progress sink takes one event dict. The fetcher's render callback is coarser: it
# takes just a stage name, which stage_callback adapts into a full event.
Progress = Callable[[dict], None]
StageSink = Callable[[str], None]


class Stage:
    QUEUED = "queued"
    FETCHING = "fetching"
    RENDERING = "rendering"
    EXTRACTING = "extracting"
    VALIDATING = "validating"
    DONE = "done"


# Where each stage sits on a single fetch->extract->validate operation's bar. For the
# URL path (one operation) this is the global pct; for a per-source leg of the MPN walk
# it is the local pct, which `monotonic` clamps so the overall bar only moves forward.
STAGE_PCT = {
    Stage.QUEUED: 0,
    Stage.FETCHING: 15,
    Stage.RENDERING: 45,
    Stage.EXTRACTING: 80,
    Stage.VALIDATING: 92,
    Stage.DONE: 100,
}


def emit(progress: Optional[Progress], stage: str, message: str = "") -> None:
    """Send one stage event, or nothing when there is no sink."""
    if progress is None:
        return
    data: dict = {"stage": stage, "pct": STAGE_PCT.get(stage, 0)}
    if message:
        data["message"] = message
    progress(data)


def stage_callback(progress: Optional[Progress]) -> Optional[StageSink]:
    """Adapt a progress sink to the fetcher's `on_stage(stage_name)` callback, so the
    render tier can raise the render phase through it. None sink -> None (no callback,
    so the fetcher is called with its original signature)."""
    if progress is None:
        return None
    return lambda stage: emit(progress, stage)


def monotonic(progress: Optional[Progress]) -> Optional[Progress]:
    """Wrap a sink so the reported pct never decreases: a later source re-emitting a low
    local pct (e.g. the datasheet leg's `fetching=15` after the scrape leg reached 92)
    must not rewind the bar, though the stage label and message still update to the
    current activity. None passes through."""
    if progress is None:
        return None
    last = [0]

    def wrapped(data: dict) -> None:
        pct = int(data.get("pct", last[0]))
        if pct < last[0]:
            pct = last[0]
        last[0] = pct
        out = dict(data)
        out["pct"] = pct
        progress(out)

    return wrapped
