"""The windowed host entry (stockroom.host.run): the glue that starts the real API
server on a thread, opens the WebView2 window onto it, and shuts the server down when
the window closes. The window is injected here so the whole seam is integration-tested
on Linux with a REAL uvicorn server (token guard enforced, clean shutdown); only the
actual WebView2 window is Windows-verified."""

import httpx
import pytest
from fastapi.testclient import TestClient

from stockroom.api.app import create_app
from stockroom.host.run import _install_injected_index, run_windowed


def test_run_windowed_serves_a_live_token_guarded_api_then_shuts_down(app_ctx):
    seen: dict = {}

    def fake_window(base_url: str, token: str) -> None:
        # the server is live in a thread; prove the token guard end to end
        seen["base"] = base_url
        seen["token"] = token
        seen["authed"] = httpx.get(
            f"{base_url}/api/system/info", headers={"X-Stockroom-Token": token}
        ).status_code
        seen["anon"] = httpx.get(f"{base_url}/api/system/info").status_code
        # the M4 seam is closed at runtime: the WebView2 fetcher is wired onto the ctx
        seen["fetcher_wired"] = app_ctx.rendered_dom_fetcher is not None

    run_windowed(ctx=app_ctx, open_window=fake_window)

    assert seen["base"].startswith("http://127.0.0.1:")
    assert seen["token"] == "testtoken"
    assert seen["authed"] == 200
    assert seen["anon"] == 401
    assert seen["fetcher_wired"] is True
    # after run_windowed returns the server is stopped: a fresh connect is refused
    with pytest.raises(httpx.HTTPError):
        httpx.get(
            f"{seen['base']}/api/system/info",
            headers={"X-Stockroom-Token": seen["token"]},
            timeout=1.0,
        )


def test_run_windowed_wires_the_default_webview2_fetcher_when_absent(app_ctx):
    assert app_ctx.rendered_dom_fetcher is None
    captured: dict = {}

    def fake_window(base_url: str, token: str) -> None:
        from stockroom.host.webview_fetch import WebViewRenderedDomFetcher

        captured["is_webview"] = isinstance(
            app_ctx.rendered_dom_fetcher, WebViewRenderedDomFetcher
        )

    run_windowed(ctx=app_ctx, open_window=fake_window)
    assert captured["is_webview"] is True


def test_run_windowed_serves_index_with_the_token_injected(app_ctx):
    # The SPA must be authenticated from its FIRST byte, not only via the on-loaded evaluate_js
    # (which lands after the initial queries and would 401 a no-retry query like onboarding,
    # hiding the first-run screen). The served index carries the base + token globals.
    seen: dict = {}

    def fake_window(base_url: str, token: str) -> None:
        seen["index"] = httpx.get(f"{base_url}/").text

    run_windowed(ctx=app_ctx, open_window=fake_window)
    assert "__STOCKROOM_TOKEN__" in seen["index"]
    assert "testtoken" in seen["index"]
    assert "__API_BASE__" in seen["index"]


def test_native_header_host_serves_bootstrap_without_renderer_token(app_ctx):
    app = create_app(app_ctx)
    _install_injected_index(
        app,
        "http://127.0.0.1:5123",
        app_ctx.token,
        app_ctx.config,
        expose_token_to_renderer=False,
    )

    index = TestClient(app).get("/").text

    assert "__API_BASE__" in index
    assert "__STOCKROOM_SESSION__" in index
    assert "__STOCKROOM_TOKEN__" not in index
    assert app_ctx.token not in index


def test_run_windowed_returns_true_when_a_restart_is_requested(app_ctx):
    # The self-updater calls ctx.request_restart() after a git pull + uv sync; run_windowed
    # must report that so main() exits EXIT_RESTART and the launcher relaunches (M9d).
    def window_requests_restart(base_url: str, token: str) -> None:
        app_ctx.request_restart()

    assert run_windowed(ctx=app_ctx, open_window=window_requests_restart) is True


def test_run_windowed_returns_false_on_a_normal_close(app_ctx):
    assert run_windowed(ctx=app_ctx, open_window=lambda base_url, token: None) is False


def test_run_windowed_leaves_an_injected_context_open(app_ctx):
    app_ctx.close = lambda: pytest.fail("run_windowed closed a caller-owned context")

    run_windowed(ctx=app_ctx, open_window=lambda _base_url, _token: None)


def test_app_context_close_releases_every_index_once():
    from unittest.mock import Mock

    from stockroom.api.context import AppContext

    ctx = object.__new__(AppContext)
    ctx._closed = False
    stm_index = Mock()
    library_index = Mock()
    project_index = Mock()
    ctx.stm_index = stm_index
    ctx.index = library_index
    ctx.project_index = project_index

    ctx.close()
    ctx.close()

    stm_index.close.assert_called_once_with()
    library_index.close.assert_called_once_with()
    project_index.close.assert_called_once_with()
    assert ctx.stm_index is None


def test_run_windowed_stops_the_server_even_if_the_window_raises(app_ctx):
    base = {}

    def boom(base_url: str, token: str) -> None:
        base["url"] = base_url
        raise RuntimeError("window crashed")

    with pytest.raises(RuntimeError):
        run_windowed(ctx=app_ctx, open_window=boom)
    # the server was still torn down (no orphaned listener)
    with pytest.raises(httpx.HTTPError):
        httpx.get(f"{base['url']}/api/system/info", timeout=1.0)


def test_run_windowed_closes_only_the_context_it_builds_even_if_the_window_raises(
    tmp_path, monkeypatch
):
    """The host owns contexts it constructs, including their SQLite handles and sync loop.

    This is the seam the isolated UI harness exercises on Windows: after run_windowed returns,
    its temporary APPDATA and library must be removable immediately, not eventually at GC.
    """
    import threading

    from stockroom.api import app as app_mod
    from stockroom.api import serve as serve_mod
    from stockroom.host import run as run_mod

    class _Context:
        token = "owned"
        rendered_dom_fetcher = object()
        request_restart = None

        def __init__(self):
            self.stop = threading.Event()
            self.closed = False

        def sync_on_launch(self):
            return None

        def start_background_sync(self):
            return self.stop

        def close(self):
            self.closed = True

    class _Server:
        should_exit = False

    class _ServerThread:
        def join(self, timeout=None):
            return None

    ctx = _Context()
    server = _Server()
    monkeypatch.setattr(serve_mod, "build_context", lambda *args, **kwargs: ctx)
    monkeypatch.setattr(serve_mod, "pick_free_port", lambda: 12345)
    monkeypatch.setattr(app_mod, "create_app", lambda _ctx: object())
    monkeypatch.setattr(run_mod, "_install_injected_index", lambda *args: None)
    monkeypatch.setattr(
        run_mod, "_serve_in_thread", lambda app, port: (server, _ServerThread())
    )

    with pytest.raises(RuntimeError, match="window crashed"):
        run_mod.run_windowed(
            libraries_root=tmp_path,
            open_window=lambda _url, _token: (_ for _ in ()).throw(RuntimeError("window crashed")),
        )

    assert server.should_exit is True
    assert ctx.stop.is_set()
    assert ctx.closed is True


def test_production_host_uses_signed_runtime_and_never_touches_git_fallback(
    app_ctx,
    monkeypatch,
):
    from stockroom.host import release_runtime

    class _NoGitFallback:
        def __getattr__(self, name):
            raise AssertionError(f"production touched legacy Git updater field {name}")

    class _SignedRuntime:
        def __init__(self):
            self.started = False
            self.closed = False
            self.owns_native_window = False

        def start(self):
            self.started = True

        def close(self):
            self.closed = True

        def status(self):
            return {
                "update_available": False,
                "state": "up_to_date",
                "current_revision": "release-1",
                "target_revision": "release-1",
                "channel": "production",
            }

    signed = _SignedRuntime()
    runtime_arguments = {}
    app_ctx.app_repo = _NoGitFallback()
    monkeypatch.setenv("STOCKROOM_UPDATE_MODE", "production")

    def create_signed_runtime(*args, **kwargs):
        del args
        runtime_arguments.update(kwargs)
        return signed

    monkeypatch.setattr(
        release_runtime,
        "create_production_update_runtime",
        create_signed_runtime,
    )

    observed = {}

    def window(base_url: str, token: str) -> None:
        observed.update(
            httpx.get(
                f"{base_url}/api/update/check",
                headers={"X-Stockroom-Token": token},
            ).json()
        )

    run_windowed(ctx=app_ctx, open_window=window)

    assert signed.started
    assert signed.closed
    assert runtime_arguments["manage_native_window"] is False
    assert observed["channel"] == "production"
    assert observed["current_revision"] == "release-1"


def test_production_bootstrap_failure_keeps_packaged_identity_and_fences_writes(
    app_ctx,
    monkeypatch,
):
    from unittest.mock import Mock

    from stockroom.host import release_runtime

    sync_on_launch = Mock(side_effect=AssertionError("unmanaged launch sync started"))
    background_sync = Mock(
        side_effect=AssertionError("unmanaged background sync started")
    )
    app_ctx.sync_on_launch = sync_on_launch
    app_ctx.start_background_sync = background_sync
    monkeypatch.setenv("STOCKROOM_UPDATE_MODE", "production")
    monkeypatch.setattr(
        release_runtime,
        "create_production_update_runtime",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("synthetic bootstrap failure")
        ),
    )
    monkeypatch.setattr(
        release_runtime,
        "verified_packaged_release_identity",
        lambda: "release-packaged",
    )
    observed: dict = {}

    def window(base_url: str, token: str) -> None:
        headers = {"X-Stockroom-Token": token}
        health = httpx.get(f"{base_url}/api/health")
        mutation = httpx.post(f"{base_url}/api/sync", headers=headers)
        update = httpx.get(f"{base_url}/api/update/check", headers=headers)
        observed["health_status"] = health.status_code
        observed["health"] = health.json()
        observed["mutation_status"] = mutation.status_code
        observed["update"] = update.json()

    run_windowed(ctx=app_ctx, open_window=window)

    assert sync_on_launch.call_count == 0
    assert background_sync.call_count == 0
    assert observed["health_status"] == 503
    assert observed["health"] == {
        "status": "degraded",
        "release_id": "release-packaged",
        "service_generation": 0,
        "service_mode": "shadow",
        "coordinator_status": "unavailable",
        "blocking_reason": "production_service_bootstrap_failed",
    }
    assert observed["mutation_status"] == 503
    assert observed["update"]["current_release_id"] == "release-packaged"
    assert observed["update"]["blocking_reason"] == (
        "production_service_bootstrap_failed"
    )
