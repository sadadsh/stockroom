import threading

from stockroom.api.jobs import JobRunner, JobStatus


def test_run_sync_captures_a_result_and_emits_done():
    runner = JobRunner()

    def work(progress):
        progress({"pct": 50, "message": "halfway"})
        return {"added": 3}

    job = runner.run_sync(work)
    assert job.status == JobStatus.DONE
    assert job.result == {"added": 3}
    kinds = [e.kind for e in runner.drain(job.id)]
    assert "progress" in kinds
    assert kinds[-1] == "done"


def test_run_sync_captures_an_error_and_still_terminates():
    runner = JobRunner()

    def boom(progress):
        raise ValueError("kaboom")

    job = runner.run_sync(boom)
    assert job.status == JobStatus.ERROR
    assert "kaboom" in job.error
    kinds = [e.kind for e in runner.drain(job.id)]
    assert "error" in kinds
    assert kinds[-1] == "done"  # a failed job still ends cleanly for the SSE consumer


def test_submit_runs_on_a_worker_thread_and_completes():
    runner = JobRunner()

    def work(progress):
        progress({"pct": 100})
        return 42

    job_id = runner.submit(work)
    # events() blocks until the terminal 'done' event, so draining it waits for the thread
    events = list(runner.events(job_id))
    assert events[-1].kind == "done"
    assert runner.get(job_id).result == 42


def test_unknown_job_id_raises_keyerror():
    runner = JobRunner()
    try:
        runner.get("nope")
        assert False, "expected KeyError"
    except KeyError:
        pass


def test_read_jobs_run_concurrently():
    # An interactive enrich lookup (a READ job) must not sit "queued" behind a long
    # bulk enrich (another READ job). Two read jobs share a rendezvous barrier that only
    # releases when BOTH are running at once; if reads were serialized the lone first job
    # would wait for a partner that never comes, time out, and error.
    runner = JobRunner()
    both_running = threading.Barrier(2, timeout=5)

    def read_work(progress):
        both_running.wait()  # passes only if a second read is running concurrently
        return "ok"

    id1 = runner.submit(read_work)
    id2 = runner.submit(read_work)
    list(runner.events(id1))
    list(runner.events(id2))
    assert runner.get(id1).result == "ok"
    assert runner.get(id2).result == "ok"


def test_a_read_runs_while_a_write_is_in_flight():
    # The core of the finding: a READ (enrich lookup) started while a WRITE (a project
    # prepare / KiCad wiring commit) is mid-flight must run immediately on the read lane,
    # never queue behind the mutating job. The barrier proves they overlap.
    runner = JobRunner()
    together = threading.Barrier(2, timeout=5)

    def write_work(progress):
        together.wait()
        return "write"

    def read_work(progress):
        together.wait()
        return "read"

    wid = runner.submit(write_work, write=True)
    rid = runner.submit(read_work)
    list(runner.events(wid))
    list(runner.events(rid))
    assert runner.get(wid).result == "write"
    assert runner.get(rid).result == "read"


def test_write_jobs_are_serialized():
    # Guard the unsafe naive fix: git-mutating jobs must NEVER overlap (two concurrent
    # git Transactions race on the index lock). Two write jobs meet at a barrier that,
    # if they were parallel, would release and set the overlap flag; serialized, each
    # waits alone, times out, and the flag stays down.
    runner = JobRunner()
    barrier = threading.Barrier(2, timeout=1)
    overlapped = {"flag": False}

    def write_work(progress):
        try:
            barrier.wait()
            overlapped["flag"] = True  # both reached it -> they overlapped
        except threading.BrokenBarrierError:
            pass  # timed out alone -> correctly serialized
        return "ok"

    ids = [runner.submit(write_work, write=True) for _ in range(2)]
    for job_id in ids:
        list(runner.events(job_id))
    assert overlapped["flag"] is False


def test_progress_never_blocks_when_the_consumer_stops_draining():
    # A disconnected SSE consumer stops draining the bounded per-job queue. A blocking put()
    # would then wedge the producer forever - and once the S6 render stage emits from the
    # shared scrape-runtime loop thread, that would freeze every concurrent render. So a
    # producer must never block: excess advisory progress is dropped, but the terminal
    # result/done still make it in so a (re)attaching consumer terminates cleanly.
    runner = JobRunner()
    cap = 1000  # the Job queue maxsize

    def flood(progress):
        for i in range(cap * 3):  # far more than the queue can hold, and nobody is draining
            progress({"pct": i})
        return "finished"

    # run_sync drives it inline on THIS thread; if put() blocked, this call would hang forever.
    job = runner.run_sync(flood)
    assert job.status == JobStatus.DONE
    assert job.result == "finished"
    kinds = [e.kind for e in runner.drain(job.id)]
    # the terminal events survived the backpressure (never dropped to make room)
    assert "result" in kinds
    assert kinds[-1] == "done"
