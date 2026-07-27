"""Assemble the completion engine for a live app context.

This is the ONE place that knows which sources exist, how they are paced, and what a run
costs. Keeping it here means a route stays four lines and the numbers below sit next to the
measurement that produced them, rather than being scattered as literals across the API.

**The pacing numbers are MEASURED, not chosen.** 2026-07-27, against the real catalogue:

* `--full` conversion costs roughly TWO EasyEDA API calls per part (component data, then the
  STEP model).
* A cold probe at one call every two seconds got 19 through and was blocked on the 20th, at
  t=44s. An earlier unpaced run got ~11 PARTS through before blocking. Both point at the same
  ceiling: about 20 calls per 60-second window.
* The block cleared on its own in about 60 seconds, so it is a cooldown, not a ban.

So `_PARTS_PER_WINDOW = 8` per 60s leaves headroom under a ~10-parts/minute ceiling. The
honest consequence, stated rather than buried: 10,000 parts is roughly 21 hours of wall clock.
That is exactly why the run is stoppable and why resuming is free.
"""

from __future__ import annotations

from pathlib import Path

from stockroom.capture.complete import complete_library, iter_incomplete, sourceable_needs
from stockroom.capture.pacing import CircuitBreaker, PacedSource
from stockroom.capture.sources import LcscSource
from stockroom.enrich.ratelimit import SlidingWindowLimiter

# See the module docstring: 8 parts x ~2 calls = ~16 calls per 60s, under the measured ~20.
_PARTS_PER_WINDOW = 8
_WINDOW_SECONDS = 60.0
# Two retries at 15s then 30s spans the ~60s cooldown without pinning a worker for minutes.
_RETRIES = 2
_RETRY_BACKOFF = 15.0
# Five parts in a row all blocked is the catalogue having closed the door, not a burst edge.
_BREAKER_THRESHOLD = 5


def build_sources(ctx, *, run_write=None, paced: bool = True):
    """The asset sources for this context, cheapest first.

    Order is the policy: an offline answer must always be tried before a network one, because
    at 10,000 parts the difference is hours. `paced=False` is for a single part, where the
    limiter would add a pointless wait.
    """
    from stockroom.ingest.pipeline import IngestPipeline

    def make_pipeline():
        # A fresh pipeline per part: it owns its sandbox and tears it down, so a long run
        # holds one tree at a time rather than one per part.
        return IngestPipeline(ctx.profile, ctx.repo, ctx.cli)

    def resolve_online(mpn: str) -> str:
        """The free, keyless jlcsearch catalogue: MPN -> LCSC part number. Only reached when
        the record itself carries no id, which is 20 of the owner's 66 file-less parts."""
        from stockroom.enrich.fetch import HttpFetcher
        from stockroom.enrich.jlcsearch import JlcSearchClient

        hit = JlcSearchClient(HttpFetcher()).search(mpn)
        return (getattr(hit, "lcsc", "") or "") if hit is not None else ""

    lcsc = LcscSource(make_pipeline, resolve_online=resolve_online, run_write=run_write)
    if not paced:
        return [lcsc]
    return [
        PacedSource(
            lcsc,
            limiter=SlidingWindowLimiter(_PARTS_PER_WINDOW, _WINDOW_SECONDS),
            retries=_RETRIES,
            backoff=_RETRY_BACKOFF,
        )
    ]


def coverage(ctx) -> dict:
    """What the library still needs, answered from the RECORDS ON DISK.

    This is the owner's central question -- *"is my library complete"* -- and until now it
    could only be answered by a script outside the app. It reads the parts directory rather
    than the derived index for the same reason the Altium emitter does: the index is rebuilt
    in the background, and a coverage number that disagrees with the files is a number that
    lies.

    Two different totals are reported on purpose. `needs_files` counts what some registered
    source could act on right now; `unsourced` counts parts with a real gap that NOTHING
    registered can fill. Collapsing them would either hide 16 genuinely stuck parts or report
    them as pending work forever.
    """
    sources = build_sources(ctx, paced=False)
    can_provide = set()
    for source in sources:
        can_provide |= set(source.provides())

    total = 0
    complete = 0
    needs_files = 0
    unsourced = 0
    by_requirement: dict[str, int] = {}
    for path in sorted(ctx.profile.library.parts_dir.glob("*.json")):
        total += 1
        try:
            record = ctx.ops.load_record(path.stem)
        except Exception:  # noqa: BLE001 - a corrupt record is counted, never fatal
            continue
        from stockroom.capture.requirements import capture_needs

        needs = capture_needs(record)
        if not needs:
            complete += 1
            continue
        for need in needs:
            by_requirement[need.value] = by_requirement.get(need.value, 0) + 1
        if sourceable_needs(record, sources):
            needs_files += 1
        else:
            unsourced += 1
    return {
        "total": total,
        "complete": complete,
        "needs_files": needs_files,
        "unsourced": unsourced,
        "by_requirement": dict(sorted(by_requirement.items())),
        "sources": [s.key for s in sources],
        "can_provide": sorted(r.value for r in can_provide),
    }


def run_completion(ctx, *, progress=None, should_stop=None, part_ids=None, limit=None) -> dict:
    """Complete every part that a registered source can help, streaming.

    `part_ids` narrows the run to a chosen set (one part, or a filtered list); omitted, the
    worklist is DERIVED from the library, which is what makes a stopped run resumable by
    simply running it again.
    """
    def run_write(fn):
        # Each git commit goes onto the serialized write lane while the slow network work
        # stays on the read lane -- the same split bulk_import uses, so commits can never
        # interleave with another writer.
        return ctx.jobs.run_write(fn)

    sources = build_sources(ctx, run_write=run_write)
    load_record = ctx.ops.load_record

    if part_ids is None:
        work = iter_incomplete(
            ctx.profile.library.parts_dir, load_record=load_record, sources=sources
        )
        total = None
    else:
        work = list(part_ids)
        total = len(work)
    if limit is not None:
        work = _take(work, limit)
        total = min(total, limit) if total is not None else None

    report = complete_library(
        work,
        load_record=load_record,
        sources=sources,
        on_progress=progress,
        should_stop=should_stop,
        total=total,
        breaker=CircuitBreaker(threshold=_BREAKER_THRESHOLD),
    )
    if report.of("completed", "improved"):
        # Only rebuild and push when something actually changed. A no-op run over a complete
        # 10,000-part library must cost nothing.
        ctx.jobs.run_write(ctx.rebuild_index)
        ctx.jobs.run_write(ctx.auto_push)
    return report.to_dict()


def run_guided_capture(
    ctx,
    *,
    part_ids=None,
    vendor: str = "ultralibrarian",
    progress=None,
    should_stop=None,
    limit=None,
    headless: bool = False,
    engine: str = "camoufox",
) -> dict:
    """Capture from a trusted vendor through a real browser: ONE component, or the whole library.

    Owner, 2026-07-27: *"i also need guided capture per component"*. `part_ids=[one]` is the
    per-component run and `part_ids=None` is the whole library - the SAME path, so whichever one is
    verified verifies the other. That is also why this shares `complete_library` with the offline
    sources rather than being its own flow.

    The browser is opened lazily by the source (a run with nothing to do never flashes a window)
    and ALWAYS closed here, so a stopped, failed or completed run leaves no window behind.
    """
    from stockroom.capture.guided import GuidedCaptureSource
    from stockroom.ingest.pipeline import IngestPipeline

    def make_pipeline():
        return IngestPipeline(ctx.profile, ctx.repo, ctx.cli)

    source = GuidedCaptureSource(
        make_pipeline,
        vendor=vendor,
        download_root=_capture_downloads(ctx),
        profile_dir=_capture_profile(ctx),
        headless=headless,
        # THE engine for real vendors, named HERE at the production call site rather than as a
        # constructor default. Stated where it ships means a test that forgets to choose gets the
        # fast engine instead of silently launching a full Firefox and hanging the suite - which is
        # exactly what a camoufox constructor default did on 2026-07-27.
        engine=engine,
        run_write=ctx.jobs.run_write,
        now_iso=_utc_now_iso,
    )
    load_record = ctx.ops.load_record

    if part_ids is None:
        work = iter_incomplete(
            ctx.profile.library.parts_dir, load_record=load_record, sources=[source]
        )
        total = None
    else:
        work = list(part_ids)
        total = len(work)
    if limit is not None:
        work = _take(work, limit)
        total = min(total, limit) if total is not None else None

    try:
        report = complete_library(
            work,
            load_record=load_record,
            sources=[source],
            on_progress=progress,
            should_stop=should_stop,
            total=total,
            breaker=CircuitBreaker(threshold=_BREAKER_THRESHOLD),
        )
    finally:
        source.close()

    if report.of("completed", "improved"):
        ctx.jobs.run_write(ctx.rebuild_index)
        ctx.jobs.run_write(ctx.auto_push)
    return report.to_dict()


def _utc_now_iso() -> str:
    """Stamped by the SERVER. A timestamp a caller can set is not evidence of when a file landed."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _capture_downloads(ctx) -> Path:
    """Where captured files land before they are attached. Beside the library, never inside it:
    an un-attached download is not library data and must never be committed."""
    root = Path(ctx.profile.library.root).parent / ".stockroom-capture" / "downloads"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _capture_profile(ctx) -> Path:
    """The persistent browser profile holding vendor sign-ins.

    PER-MACHINE, and it is the permitted kind: it holds session cookies only, so it cannot change
    what the library renders the way a per-machine enrich cache can. It is what makes a 90-part
    sitting cost ONE sign-in.
    """
    root = Path(ctx.profile.library.root).parent / ".stockroom-capture" / "profile"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _take(iterable, n: int):
    """islice that keeps the source lazy -- a limited run over a 10,000-part library must not
    walk all 10,000 first."""
    for i, item in enumerate(iterable):
        if i >= n:
            return
        yield item
