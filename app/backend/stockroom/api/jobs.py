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
import math
import queue as queue_module
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Iterator


class JobStatus:
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class JobRunnerUnavailable(RuntimeError):
    """The managed generation is not accepting new background work."""


class JobRunnerQuiescenceTimeout(RuntimeError):
    """A managed generation still owns work at its transfer deadline."""


@dataclass
class JobEvent:
    kind: str
    data: dict = field(default_factory=dict)


_SENTINEL = JobEvent("done")


@dataclass
class Job:
    id: str
    generation: int | None = None
    status: str = JobStatus.QUEUED
    result: object | None = None
    error: str = ""
    queue: queue_module.Queue[JobEvent] = field(
        default_factory=lambda: queue_module.Queue(maxsize=1000)
    )
    # Set by request_stop; READ by the worker, which decides where stopping is safe. A plain
    # bool needs no lock: one writer, one reader, and a missed flip is seen on the next check.
    stop_requested: bool = False


def to_sse(event: JobEvent) -> dict:
    return {"event": event.kind, "data": json.dumps(event.data)}


def _offer(q: queue_module.Queue[JobEvent], event: JobEvent) -> None:
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
        except queue_module.Full:
            try:
                q.get_nowait()  # drop the oldest queued (advisory) event, then retry
            except queue_module.Empty:
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
        if type(max_workers) is not int or max_workers <= 0:
            raise ValueError("max_workers must be a positive integer")
        self._max_workers = max_workers
        self._jobs: dict[str, Job] = {}
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._managed = False
        self._accepting = True
        self._generation: int | None = None
        self._futures: set[Future[object]] = set()
        self._inline_active = 0
        self._pools_shutdown = False
        self._create_pools()

    def _create_pools(self) -> None:
        self._read_pool = ThreadPoolExecutor(
            max_workers=self._max_workers, thread_name_prefix="job-read"
        )
        self._write_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="job-write")
        self._pools_shutdown = False

    @property
    def managed_generation(self) -> int | None:
        with self._condition:
            return self._generation

    @property
    def accepting(self) -> bool:
        with self._condition:
            return self._accepting

    def require_managed_generation(self) -> None:
        """Make submission contingent on lifecycle-owned generation activation.

        Context construction calls this before a managed shadow is exposed.  It
        is intentionally effect-free outside this process: no executor thread is
        started until a later accepted submission.
        """

        with self._condition:
            if self._managed:
                return
            if self._futures or self._inline_active:
                raise JobRunnerUnavailable(
                    "cannot enter managed mode while background work is active"
                )
            self._managed = True
            self._accepting = False
            self._generation = None

    def activate_generation(self, generation: int) -> None:
        """Open fresh executor lanes for one exact coordinator generation."""

        if type(generation) is not int or generation <= 0:
            raise ValueError("generation must be a positive integer")
        with self._condition:
            if not self._managed:
                raise JobRunnerUnavailable("job runner is not generation managed")
            if self._accepting:
                if self._generation == generation:
                    return
                raise JobRunnerUnavailable(
                    "another managed generation is already accepting work"
                )
            if self._futures or self._inline_active:
                raise JobRunnerUnavailable(
                    "prior generation background work is still active"
                )
            if self._generation is not None and generation <= self._generation:
                raise JobRunnerUnavailable(
                    "managed job generations must advance monotonically"
                )
            if self._pools_shutdown:
                self._create_pools()
            self._generation = generation
            self._accepting = True

    def _require_accepting_locked(self) -> int | None:
        if not self._accepting:
            raise JobRunnerUnavailable(
                "background work is unavailable during service transfer"
            )
        return self._generation

    def _new_job_locked(self, generation: int | None) -> Job:
        job = Job(id=uuid.uuid4().hex, generation=generation)
        self._jobs[job.id] = job
        return job

    def _future_done(self, future: Future[object]) -> None:
        with self._condition:
            self._futures.discard(future)
            self._condition.notify_all()

    def _submit_locked(
        self,
        pool: ThreadPoolExecutor,
        fn: Callable[[], object],
    ) -> Future[object]:
        future = pool.submit(fn)
        self._futures.add(future)
        future.add_done_callback(self._future_done)
        return future

    def get(self, job_id: str) -> Job:
        with self._condition:
            return self._jobs[job_id]

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
        with self._condition:
            generation = self._require_accepting_locked()
            job = self._new_job_locked(generation)
            self._inline_active += 1
        try:
            self._drive(job, fn)
        finally:
            with self._condition:
                self._inline_active -= 1
                self._condition.notify_all()
        return job

    def submit(self, fn, *, write: bool = False) -> str:
        """Queue a job. `write=True` routes a git/config-mutating job to the serialized
        write lane; the default read lane runs jobs concurrently."""
        with self._condition:
            generation = self._require_accepting_locked()
            job = self._new_job_locked(generation)
            pool = self._write_pool if write else self._read_pool
            self._submit_locked(pool, lambda: self._drive(job, fn))
        return job.id

    def submit_cancellable(self, fn, *, write: bool = False) -> str:
        """Queue a job that can be asked to stop. `fn(progress, should_stop)`.

        The job is REGISTERED before it is scheduled, so its id exists the instant this
        returns and a stop issued in the first moments of a slow-starting run cannot fall
        into a gap. Stopping is cooperative: the worker chooses the safe point, which for a
        library-wide run means between two parts, never inside one.
        """
        with self._condition:
            generation = self._require_accepting_locked()
            job = self._new_job_locked(generation)
            pool = self._write_pool if write else self._read_pool
            self._submit_locked(
                pool,
                lambda: self._drive(
                    job,
                    lambda progress: fn(progress, lambda: job.stop_requested),
                ),
            )
        return job.id

    def request_stop(self, job_id: str) -> None:
        """Ask a running job to stop at its next safe point. A job that already finished (or
        never existed) is not an error: the UI legitimately races a run that just ended."""
        with self._condition:
            job = self._jobs.get(job_id)
        if job is not None:
            job.stop_requested = True

    def run_write(self, fn):
        """Run fn() on the serialized write lane and BLOCK until it returns, propagating its result
        or exception. Lets a long READ-lane job (a bulk rescan doing slow network lookups) push each
        individual git commit onto the write lane - so commits stay serialized against every other
        writer WITHOUT the network I/O ever occupying the single write worker. No deadlock: the read
        pool and write pool are independent, so a read-lane thread blocking on a write future frees
        no write capacity it needs."""
        with self._condition:
            self._require_accepting_locked()
            future = self._submit_locked(self._write_pool, fn)
        return future.result()

    def begin_generation_quiescence(self, generation: int) -> None:
        """Reject new work and request cooperative cancellation for one generation."""

        if type(generation) is not int or generation <= 0:
            raise ValueError("generation must be a positive integer")
        with self._condition:
            if not self._managed or self._generation != generation:
                raise JobRunnerUnavailable("managed job generation is stale")
            self._accepting = False
            for job in self._jobs.values():
                if (
                    job.generation == generation
                    and job.status in {JobStatus.QUEUED, JobStatus.RUNNING}
                ):
                    job.stop_requested = True
            if not self._pools_shutdown:
                # Do not cancel queued futures blindly: doing so would strand
                # their registered SSE jobs without a terminal event.  Their
                # cooperative stop flag is already set, and the bounded wait
                # below retains the service fence until every future exits.
                self._read_pool.shutdown(wait=False, cancel_futures=False)
                self._write_pool.shutdown(wait=False, cancel_futures=False)
                self._pools_shutdown = True

    def await_generation_quiescence(
        self,
        generation: int,
        *,
        timeout: float | None,
    ) -> None:
        """Join every executor task or fail while the caller still owns its fence."""

        if timeout is not None and (
            type(timeout) not in {int, float}
            or not math.isfinite(float(timeout))
            or float(timeout) <= 0
        ):
            raise ValueError("timeout must be positive and finite")
        deadline = None if timeout is None else time.monotonic() + float(timeout)
        with self._condition:
            if not self._managed or self._generation != generation:
                raise JobRunnerUnavailable("managed job generation is stale")
            if self._accepting:
                raise JobRunnerUnavailable(
                    "managed job generation has not begun quiescing"
                )
            while self._futures or self._inline_active:
                remaining = (
                    None
                    if deadline is None
                    else deadline - time.monotonic()
                )
                if remaining is not None and remaining <= 0:
                    raise JobRunnerQuiescenceTimeout(
                        "background jobs did not stop before service transfer"
                    )
                self._condition.wait(remaining)
            # `wait=True` after the tracked futures reach zero joins the actual
            # executor threads as well; a completed Future alone is not proof
            # that its worker thread has left the old generation.
            self._read_pool.shutdown(wait=True, cancel_futures=False)
            self._write_pool.shutdown(wait=True, cancel_futures=False)

    def quiesce_generation(self, generation: int, *, timeout: float) -> None:
        self.begin_generation_quiescence(generation)
        self.await_generation_quiescence(generation, timeout=timeout)

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
            except queue_module.Empty:
                return out


def _jsonable(value: object) -> object:
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)
