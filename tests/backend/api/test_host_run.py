"""The windowed host entry (stockroom.host.run): the glue that starts the real API
server on a thread, opens the WebView2 window onto it, and shuts the server down when
the window closes. The window is injected here so the whole seam is integration-tested
on Linux with a REAL uvicorn server (token guard enforced, clean shutdown); only the
actual WebView2 window is Windows-verified."""

import httpx
import pytest

from stockroom.host.run import run_windowed


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


def test_run_windowed_returns_true_when_a_restart_is_requested(app_ctx):
    # The self-updater calls ctx.request_restart() after a git pull + uv sync; run_windowed
    # must report that so main() exits EXIT_RESTART and the launcher relaunches (M9d).
    def window_requests_restart(base_url: str, token: str) -> None:
        app_ctx.request_restart()

    assert run_windowed(ctx=app_ctx, open_window=window_requests_restart) is True


def test_run_windowed_returns_false_on_a_normal_close(app_ctx):
    assert run_windowed(ctx=app_ctx, open_window=lambda base_url, token: None) is False


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
