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
    def __init__(self, max_workers: int = 1):
        self._jobs: dict[str, Job] = {}
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
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

    def submit(self, fn) -> str:
        job = self._new_job()
        self._pool.submit(self._drive, job, fn)
        return job.id

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
