import threading

import pytest

from stockroom.api.jobs import JobRunner


def test_run_write_returns_the_result_on_a_write_thread():
    runner = JobRunner()
    name = runner.run_write(lambda: threading.current_thread().name)
    assert name.startswith("job-write")


def test_run_write_propagates_exceptions():
    runner = JobRunner()
    with pytest.raises(ValueError, match="boom"):
        runner.run_write(lambda: (_ for _ in ()).throw(ValueError("boom")))


def test_run_write_serializes_calls_on_the_single_worker():
    runner = JobRunner()
    order = []
    lock = threading.Lock()

    def make(tag):
        def fn():
            with lock:
                order.append(f"start-{tag}")
            order.append(f"end-{tag}")
            return tag
        return fn

    # two run_writes from two threads: the single write worker must never interleave their bodies
    results = {}
    threads = [threading.Thread(target=lambda t=t: results.__setitem__(t, runner.run_write(make(t))))
               for t in ("a", "b")]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    # each task's start is immediately followed by its own end (no interleave)
    assert order.index("start-a") in (0, 2) and order[order.index("start-a") + 1] == "end-a"
    assert order.index("start-b") in (0, 2) and order[order.index("start-b") + 1] == "end-b"
    assert results == {"a": "a", "b": "b"}
