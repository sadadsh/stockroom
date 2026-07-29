"""Every device reconciles by itself, on launch.

Owner, 2026-07-26: "all devices should be synced ... automatically and going forward".

`AppContext.auto_push` already pull-rebases and pushes, but ONLY after a local write. A machine
that has not added a part therefore never reconciles at all - which is exactly how this owner's
library came to exist as two diverged checkouts on ONE machine: the one they were adding parts
from pushed happily, while the one their app actually READ sat ten commits behind showing a single
part and looking complete. Nothing was broken; nothing had pulled.

So the launch pulls. It reuses `LibrarySync.sync()` (pull fast-forward, then push if ahead) rather
than reimplementing it, so the automatic path and the Sync button can never drift apart.
"""
from __future__ import annotations


class _FakeSync:
    def __init__(self, boom: Exception | None = None):
        self.calls = 0
        self._boom = boom

    def sync(self):
        self.calls += 1
        if self._boom:
            raise self._boom
        return object()


def test_launch_reconciles_the_library_without_being_asked(app_ctx):
    fake = _FakeSync()
    app_ctx.sync = fake
    app_ctx.sync_on_launch()
    assert fake.calls == 1, "a launch did not reconcile; a device that never writes never syncs"


def test_a_launch_sync_can_never_stop_the_app_starting(app_ctx):
    # Offline, no credential, a rejected fast-forward: every one of these is normal and none of
    # them may keep the window from opening. Same contract `auto_push` already holds.
    app_ctx.sync = _FakeSync(boom=RuntimeError("network unreachable"))
    app_ctx.sync_on_launch()  # must not raise


def test_sync_disabled_means_disabled(app_ctx):
    fake = _FakeSync()
    app_ctx.sync = fake
    app_ctx.config.sync_enabled = False
    app_ctx.sync_on_launch()
    assert fake.calls == 0, "the setting was ignored"


def test_a_real_launch_actually_calls_it(tmp_path, monkeypatch):
    """The half that makes it a FEATURE rather than a method nobody calls.

    A seam no launch invokes is exactly the "half-wired" state the standard forbids, and it would
    have looked done: the unit tests above would all pass while every device stayed stale.
    """
    import threading

    from stockroom.host import run as run_mod

    called = threading.Event()
    looping = threading.Event()

    class _Ctx:
        rendered_dom_fetcher = object()
        token = "t"
        request_restart = None

        def sync_on_launch(self):
            called.set()

        def start_background_sync(self, *a, **k):
            # Asserted too: a one-shot at launch without the loop is the owner's exact complaint
            # ("it shouldnt need to relaunch") only slowed down, not fixed.
            looping.set()
            return threading.Event()

    ctx = _Ctx()
    # `create_app` is imported INSIDE run_windowed, so it is patched on its own module.
    import stockroom.api.app as app_mod
    monkeypatch.setattr(app_mod, "create_app", lambda c: object())
    monkeypatch.setattr(run_mod, "_install_injected_index", lambda *a, **k: None)
    class _Server:
        should_exit = False

    class _Thread:
        def join(self, *a, **k):
            return None

    monkeypatch.setattr(run_mod, "_serve_in_thread", lambda app, port: (_Server(), _Thread()))
    monkeypatch.setattr(run_mod, "_shutdown", lambda *a, **k: None, raising=False)

    run_mod.run_windowed(libraries_root=tmp_path, ctx=ctx, open_window=lambda url, token: None)

    assert called.wait(timeout=5), "launching the app did not reconcile the library"
    assert looping.is_set(), "the launch did not start the background sync loop"


def test_a_pull_refreshes_the_derived_indexes(app_ctx):
    """The half that makes a pull VISIBLE.

    New part records on disk mean a stale SQLite index and a UI still showing the old library.
    `POST /api/sync` has always rebuilt both indexes after a pull; the automatic paths did not, so
    the first version of the launch sync would have pulled a collaborator's part and shown nothing.
    """
    class _Pulled:
        pulled = True

    class _S:
        def sync(self):
            return _Pulled()

    rebuilt = []
    app_ctx.sync = _S()
    app_ctx.rebuild_index = lambda: rebuilt.append("index")
    app_ctx.rebuild_project_index = lambda: rebuilt.append("projects")
    assert app_ctx.reconcile() is True
    assert rebuilt == ["index", "projects"], f"a pull left the indexes stale: {rebuilt}"


def test_nothing_is_rebuilt_when_nothing_came_in(app_ctx):
    class _S:
        def sync(self):
            return type("R", (), {"pulled": False})()

    rebuilt = []
    app_ctx.sync = _S()
    app_ctx.rebuild_index = lambda: rebuilt.append("index")
    assert app_ctx.reconcile() is False
    assert rebuilt == [], "an unchanged sync rebuilt the index for nothing"


def test_it_keeps_reconciling_while_the_app_runs(app_ctx):
    """Owner: "it shouldnt need to relaunch". A launch-only pull leaves a window that has been open
    an hour showing an hour-old library - the same staleness, slower."""
    import time

    calls = []
    app_ctx.reconcile = lambda: calls.append(1)
    stop = app_ctx.start_background_sync(interval_seconds=0.05)
    deadline = time.time() + 5
    while len(calls) < 2 and time.time() < deadline:
        time.sleep(0.02)
    stop.set()
    stop.join(2.0)
    assert len(calls) >= 2, f"the background loop did not keep running (calls={len(calls)})"
    assert not stop.is_alive()


def test_the_loop_stops_when_asked(app_ctx):
    import time

    calls = []
    app_ctx.reconcile = lambda: calls.append(1)
    stop = app_ctx.start_background_sync(interval_seconds=0.05)
    time.sleep(0.2)
    stop.set()
    stop.join(2.0)
    settled = len(calls)
    time.sleep(0.3)
    assert len(calls) == settled, "the loop kept going after stop"
    assert not stop.is_alive()


def test_background_sync_rejects_an_unbounded_interval(app_ctx):
    import pytest

    for value in (0, -1, float("inf"), float("nan"), True):
        with pytest.raises((TypeError, ValueError)):
            app_ctx.start_background_sync(interval_seconds=value)
