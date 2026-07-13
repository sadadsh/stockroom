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
