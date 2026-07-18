"""In-process background jobs with SSE progress (spec section 2.2: any operation
over ~100ms runs off the request path with SSE progress; the window never blocks).

A job is a callable that takes a `progress(dict)` callback; it runs on a worker
thread, its return value becomes a terminal `result` event and any exception a
terminal `error` event, and EITHER way a final `done` event is emitted so an SSE
consumer always terminates cleanly (honest degradation: a failed job is a labeled
error event, never a dropped stream). run_sync is the test path: no thread, fully
deterministic."""

from __future__ import annotations

import json
import queue
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Iterator


class JobStatus:
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass
class JobEvent:
    kind: str
    data: dict = field(default_factory=dict)


_SENTINEL = JobEvent("done")


@dataclass
class Job:
    id: str
    status: str = JobStatus.QUEUED
    result: object | None = None
    error: str = ""
    queue: "queue.Queue[JobEvent]" = field(default_factory=lambda: queue.Queue(maxsize=1000))


def to_sse(event: JobEvent) -> dict:
    return {"event": event.kind, "data": json.dumps(event.data)}


def _offer(q: "queue.Queue[JobEvent]", event: JobEvent) -> None:
    """Enqueue without ever blocking the producer. A disconnected SSE consumer stops draining
    the bounded queue; a plain blocking put() would then wedge the producer forever (and once
    the S6 render stage emits from the shared scrape-runtime loop thread, a stalled producer
    would freeze every concurrent render). On a full queue we drop the OLDEST event to make room
    for the newest. Progress is advisory, so dropping a stale mid-stage event is harmless; the
    terminal result/error/done are always the LAST puts (no progress follows them), so make-room
    only ever discards old progress and never a terminal - a consumer that (re)attaches still
    sees the outcome and the closing 'done', so the stream always terminates cleanly."""
    while True:
        try:
            q.put_nowait(event)
            return
        except queue.Full:
            try:
                q.get_nowait()  # drop the oldest queued (advisory) event, then retry
            except queue.Empty:
                # drained to empty between the Full and here; the retry will now succeed
                pass


class JobRunner:
    """Two independent lanes so an interactive lookup never queues behind a long job.

    READ jobs (enrich lookup/bulk, ingest inspect/enrich, project checks/BOM) touch no
    git working tree, so they run concurrently on a small pool: a bulk enrich or a project
    prepare in flight never makes an Add-A-Part lookup sit "queued".

    WRITE jobs (project prepare -> an atomic commit on the project's git; doctor wire-kicad
    -> a rewrite of the shared KiCad config) run on a dedicated single-worker pool, so two
    git Transactions can never overlap and race on the index lock. A naive `max_workers`
    bump on ONE pool would have let them - hence the split rather than a shared pool.

    The two lanes are not mutually exclusive: a read may run alongside a write (they touch
    disjoint state - the enrich cache vs. a project's git). The one narrow overlap left is
    a `checks`/`bom` READ against a `prepare` WRITE on the SAME project; prepare evicts
    those caches anyway, so a rare same-instant race only risks a stale advisory cache
    entry, never a corrupt commit. Revisit only if that ever bites."""

    def __init__(self, max_workers: int = 4):
        self._jobs: dict[str, Job] = {}
        self._read_pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="job-read"
        )
        self._write_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="job-write")
        self._lock = threading.Lock()

    def get(self, job_id: str) -> Job:
        with self._lock:
            return self._jobs[job_id]

    def _new_job(self) -> Job:
        job = Job(id=uuid.uuid4().hex)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def _drive(self, job: Job, fn: Callable[[Callable[[dict], None]], object]) -> None:
        job.status = JobStatus.RUNNING

        def progress(data: dict) -> None:
            _offer(job.queue, JobEvent("progress", dict(data)))

        try:
            result = fn(progress)
            job.result = result
            job.status = JobStatus.DONE
            _offer(job.queue, JobEvent("result", {"result": _jsonable(result)}))
        except Exception as exc:  # noqa: BLE001 - a job failure is a labeled event
            job.error = str(exc)
            job.status = JobStatus.ERROR
            _offer(job.queue, JobEvent("error", {"detail": str(exc), "error": type(exc).__name__}))
        finally:
            _offer(job.queue, _SENTINEL)

    def run_sync(self, fn) -> Job:
        job = self._new_job()
        self._drive(job, fn)
        return job

    def submit(self, fn, *, write: bool = False) -> str:
        """Queue a job. `write=True` routes a git/config-mutating job to the serialized
        write lane; the default read lane runs jobs concurrently."""
        job = self._new_job()
        pool = self._write_pool if write else self._read_pool
        pool.submit(self._drive, job, fn)
        return job.id

    def run_write(self, fn):
        """Run fn() on the serialized write lane and BLOCK until it returns, propagating its result
        or exception. Lets a long READ-lane job (a bulk rescan doing slow network lookups) push each
        individual git commit onto the write lane - so commits stay serialized against every other
        writer WITHOUT the network I/O ever occupying the single write worker. No deadlock: the read
        pool and write pool are independent, so a read-lane thread blocking on a write future frees
        no write capacity it needs."""
        return self._write_pool.submit(fn).result()

    def events(self, job_id: str) -> Iterator[JobEvent]:
        job = self.get(job_id)
        while True:
            event = job.queue.get()
            yield event
            if event is _SENTINEL or event.kind == "done":
                return

    def drain(self, job_id: str) -> list[JobEvent]:
        """Non-blocking snapshot of everything queued so far, for run_sync tests."""
        job = self.get(job_id)
        out: list[JobEvent] = []
        while True:
            try:
                out.append(job.queue.get_nowait())
            except queue.Empty:
                return out


def _jsonable(value: object) -> object:
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)
