"""A long job has to be stoppable.

A completion run over 10,000 parts is hours of work. Without a stop, starting one is a
commitment the user cannot take back, and the only way out is killing the app -- which on a
git-backed library is the one thing that must never be the answer.

The stop is COOPERATIVE by design: the worker decides where it is safe to stop (between two
parts, never inside one), so a stopped run leaves the library in exactly the state a finished
one would, just with fewer parts done.
"""

import threading

from stockroom.api.jobs import JobRunner, JobStatus


def test_a_cancellable_job_sees_the_stop_flag_and_finishes_cleanly():
    runner = JobRunner()
    seen = []
    # The worker can begin before submit_cancellable() has even returned, so it must not read
    # `job_id` until the main thread has bound it. Without this gate the test races its own
    # harness and reports a bug in the runner that is not there.
    have_id = threading.Event()

    def work(progress, should_stop):
        have_id.wait(5)
        for i in range(100):
            if should_stop():
                return {"did": i, "stopped": True}
            seen.append(i)
            if i == 2:
                runner.request_stop(job_id)
        return {"did": 100, "stopped": False}

    job_id = runner.submit_cancellable(work)
    have_id.set()
    # Drain to completion; the SSE consumer does exactly this.
    list(runner.events(job_id))
    job = runner.get(job_id)
    assert job.status == JobStatus.DONE
    assert job.result["stopped"] is True
    # It stopped where the WORKER chose, not wherever the flag happened to flip.
    assert job.result["did"] == 3


def test_a_job_nobody_stops_runs_to_the_end():
    # The stop must not fire by accident: a detector that always trips is worse than none.
    runner = JobRunner()

    def work(progress, should_stop):
        return {"stopped": should_stop()}

    job_id = runner.submit_cancellable(work)
    list(runner.events(job_id))
    assert runner.get(job_id).result == {"stopped": False}


def test_the_stop_flag_is_readable_before_the_job_is_even_scheduled():
    """The job id must exist BEFORE the work starts, or a stop issued in the first moments of
    a run is silently lost -- exactly the window a user clicking Stop on a slow start hits."""
    runner = JobRunner()
    started = []

    def work(progress, should_stop):
        started.append(should_stop())
        return None

    job_id = runner.submit_cancellable(work)
    assert isinstance(job_id, str) and job_id
    list(runner.events(job_id))
    assert started == [False]


def test_requesting_a_stop_on_an_unknown_job_is_not_an_error():
    # The UI can race a job that already finished; that is normal, not a failure.
    JobRunner().request_stop("no-such-job")
