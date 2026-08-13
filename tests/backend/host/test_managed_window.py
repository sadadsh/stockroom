from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from stockroom.host import window as W


class _Event:
    def __init__(self) -> None:
        self.handlers: list[Callable[[], None]] = []

    def __iadd__(self, handler: Callable[[], None]):
        self.handlers.append(handler)
        return self

    def fire(self) -> None:
        for handler in tuple(self.handlers):
            handler()


class _Window:
    def __init__(self, current_url: str) -> None:
        self.current_url = current_url
        self.events = SimpleNamespace(loaded=_Event())
        self.hidden_calls = 0
        self.show_calls = 0
        self.restore_calls = 0
        self.focus_calls = 0
        self.destroy_calls = 0
        self.destroyed = threading.Event()
        self.evaluations: list[str] = []
        self.loaded_urls: list[str] = []
        self.move_calls: list[tuple[int, int]] = []
        self.resize_calls: list[tuple[int, int]] = []
        self.session = {"route": "components", "event_sequence": 17}

    def get_current_url(self) -> str:
        return self.current_url

    def hide(self) -> None:
        self.hidden_calls += 1

    def show(self) -> None:
        self.show_calls += 1

    def restore(self) -> None:
        self.restore_calls += 1

    def focus(self) -> None:
        self.focus_calls += 1

    def load_url(self, url: str) -> None:
        self.current_url = url
        self.loaded_urls.append(url)

    def evaluate_js(self, script: str) -> object:
        self.evaluations.append(script)
        return self.session

    def move(self, x: int, y: int) -> None:
        self.move_calls.append((x, y))

    def resize(self, width: int, height: int) -> None:
        self.resize_calls.append((width, height))

    def destroy(self) -> None:
        self.destroy_calls += 1
        self.destroyed.set()


def test_in_app_provider_surface_never_navigates_the_stockroom_window(monkeypatch) -> None:
    app_window = _Window("http://127.0.0.1:8123/components")
    provider_window = _Window("about:blank#stockroom-provider-proof")
    monkeypatch.setattr(W, "_ACTIVE_WINDOW", app_window)
    surface = W.InAppProviderBrowserSurface(
        "http://127.0.0.1:8123",
        provider_window=lambda: provider_window,
    )

    with surface.lease() as lease:
        # The in-app surface exposes no debugging endpoint either; the lease is commands only.
        assert not hasattr(lease, "endpoint")
        lease.show()
        assert provider_window.show_calls == 0
        assert provider_window.focus_calls == 0
        assert app_window.loaded_urls == []
        lease.navigate("https://www.snapeda.com/parts/ABC/Maker/view-part/")
        state = lease.document_state(
            ready_selectors=('a[name="download-modal"]',),
            ready_texts=("request 3d model",),
        )
        assert state == {
            "ready": False,
            "challenge": False,
            "account_verification": False,
            "provider_error": False,
            "provider_ready": False,
        }
        assert "getBoundingClientRect" in provider_window.evaluations[-1]
        assert 'a[name=\\"download-modal\\"]' in provider_window.evaluations[-1]
        assert '"verify your phone number"' in provider_window.evaluations[-1]
        assert '"phone verification is required"' in provider_window.evaluations[-1]
        assert '"oh snap! we' in provider_window.evaluations[-1]
        lease.hide()
        assert provider_window.hidden_calls == 1
        assert app_window.loaded_urls == []
        surface.show_active_provider_browser()
        assert provider_window.show_calls == 0

    assert provider_window.loaded_urls == ["https://www.snapeda.com/parts/ABC/Maker/view-part/"]
    assert provider_window.hidden_calls == 2
    assert app_window.loaded_urls == []


def test_in_app_provider_surface_applies_modal_viewport_and_commands(monkeypatch) -> None:
    app_window = _Window("http://127.0.0.1:8123/components")
    app_window.x = 100
    app_window.y = 60
    provider_window = _Window("https://www.snapeda.com/parts/ABC/Maker/view-part/")
    monkeypatch.setattr(W, "_ACTIVE_WINDOW", app_window)
    surface = W.InAppProviderBrowserSurface(
        "http://127.0.0.1:8123",
        provider_window=lambda: provider_window,
    )

    with surface.lease():
        assert (
            surface.set_provider_viewport(
                {
                    "componentId": "part-1",
                    "visible": True,
                    "x": 128,
                    "y": 114,
                    "width": 1024,
                    "height": 570,
                }
            )
            is True
        )
        assert provider_window.move_calls == [(228, 174)]
        assert provider_window.resize_calls == [(1024, 570)]
        app_window.x = 300
        app_window.y = 180
        assert surface.reapply_provider_viewport() is True
        assert provider_window.move_calls[-1] == (428, 294)
        surface.provider_command({"componentId": "part-1", "command": "back"})
        assert provider_window.evaluations[-1] == "history.back()"
        surface.provider_command({"componentId": "part-1", "command": "close"})
        assert provider_window.hidden_calls == 1

        assert (
            surface.set_provider_viewport(
                {
                    "componentId": "part-2",
                    "visible": True,
                    "x": 128,
                    "y": 114,
                    "width": 1024,
                    "height": 570,
                }
            )
            is False
        )
        assert provider_window.hidden_calls == 2


class _Webview:
    def __init__(self, window: _Window) -> None:
        self.window = window
        self.settings: dict[str, object] = {}
        self.create_kwargs: dict[str, object] = {}
        self.start_kwargs: dict[str, object] = {}

    def create_window(self, _title: str, **kwargs):
        self.create_kwargs = kwargs
        return self.window

    def start(self, **kwargs) -> None:
        self.start_kwargs = kwargs
        self.window.events.loaded.fire()
        assert self.window.destroyed.wait(timeout=2)


def test_managed_controller_exports_only_non_secret_health_and_session(
    monkeypatch,
) -> None:
    monkeypatch.setattr(W, "_is_windows", lambda: False)
    window = _Window("http://127.0.0.1:8123/components")
    controller = W.ManagedWindowController(
        window=window,
        base_url="http://127.0.0.1:8123",
        api_credential="do-not-render-this",
        window_handle=9123,
    )

    controller.prepare_hidden(deadline_unix_ms=time.time_ns() // 1_000_000 + 1_000)
    with pytest.raises(RuntimeError, match="hidden"):
        controller.focus()

    controller.show()
    controller.focus()
    assert controller.health() == {
        "hwnd": 9123,
        "current_url": "http://127.0.0.1:8123/components",
        "hidden": False,
        "visible": True,
        "renderer": "edgechromium",
    }
    assert "do-not-render-this" not in repr(controller.health())
    assert controller.export_session() == window.session
    assert window.evaluations == [
        "window.__STOCKROOM_EXPORT_UI_SESSION__ ? window.__STOCKROOM_EXPORT_UI_SESSION__() : null"
    ]

    controller.shutdown()
    controller.shutdown()
    assert controller._api_credential == bytearray()
    assert window.destroy_calls == 1
    with pytest.raises(RuntimeError, match="shut down"):
        controller.health()


def test_managed_controller_rejects_expired_deadline_and_remote_navigation() -> None:
    window = _Window("http://127.0.0.1:8123/components")
    controller = W.ManagedWindowController(
        window=window,
        base_url="http://127.0.0.1:8123",
        api_credential="secret",
        window_handle=55,
    )

    with pytest.raises(TimeoutError, match="expired"):
        controller.prepare_hidden(deadline_unix_ms=1)
    window.current_url = "https://example.com/"
    with pytest.raises(RuntimeError, match="left the Stockroom origin"):
        controller.health()
    controller.shutdown()


def test_saved_window_geometry_is_applied_hidden_before_candidate_commands(
    monkeypatch,
) -> None:
    from stockroom.host import window_geometry

    saved = object()
    resolution = object()
    calls: list[tuple[object, ...]] = []
    config = SimpleNamespace(window={"schema": "test"})
    monkeypatch.setattr(
        window_geometry,
        "window_geometry_from_machine_config",
        lambda candidate: calls.append(("decode", candidate)) or saved,
    )
    monkeypatch.setattr(
        window_geometry,
        "apply_window_geometry",
        lambda hwnd, geometry, *, show: calls.append(("apply", hwnd, geometry, show)) or resolution,
    )

    assert W._apply_saved_window_geometry(9123, config) is resolution
    assert calls == [
        ("decode", config),
        ("apply", 9123, saved, False),
    ]


def test_run_managed_window_is_hidden_first_and_starts_commands_after_hwnd(
    monkeypatch,
    tmp_path: Path,
) -> None:
    window = _Window("http://127.0.0.1:8123/")
    webview = _Webview(window)
    monkeypatch.setitem(sys.modules, "webview", webview)
    order: list[str] = []
    monkeypatch.setattr(
        W,
        "_configure_windows_process_identity",
        lambda: order.append("identity"),
    )
    monkeypatch.setattr(
        W,
        "_current_process_window_handle",
        lambda candidate: order.append("hwnd") or 4545,
    )
    monkeypatch.setattr(
        W,
        "_apply_saved_window_geometry",
        lambda hwnd: order.append(f"geometry:{hwnd}"),
    )
    monkeypatch.setattr(W, "_apply_window_icon", lambda candidate: True)
    monkeypatch.setattr(W, "_release_window_icons", lambda candidate: None)
    controllers: list[W.ManagedWindowController] = []

    def command_loop(controller: W.ManagedWindowController) -> None:
        order.append("command")
        controllers.append(controller)
        assert controller.health()["hidden"] is True
        controller.shutdown()

    profile = tmp_path / "WebView Profile"
    W.run_managed_window(
        base_url="http://127.0.0.1:8123",
        api_credential="native-only-secret",
        profile_dir=profile,
        command_loop=command_loop,
    )

    assert order == ["identity", "hwnd", "geometry:4545", "command"]
    assert webview.create_kwargs["hidden"] is True
    assert webview.start_kwargs == {
        "gui": "edgechromium",
        "private_mode": False,
        "storage_path": str(profile.resolve()),
    }
    assert "native-only-secret" not in repr(webview.create_kwargs)
    assert "native-only-secret" not in repr(webview.start_kwargs)
    assert window.evaluations == []
    assert controllers[0]._api_credential == bytearray()


def test_run_managed_window_fails_closed_before_command_loop_off_origin(
    monkeypatch,
    tmp_path: Path,
) -> None:
    window = _Window("https://example.com/")
    webview = _Webview(window)
    monkeypatch.setitem(sys.modules, "webview", webview)
    monkeypatch.setattr(W, "_configure_windows_process_identity", lambda: None)
    monkeypatch.setattr(W, "_release_window_icons", lambda candidate: None)
    commands: list[object] = []

    with pytest.raises(RuntimeError, match="failed to become ready"):
        W.run_managed_window(
            base_url="http://127.0.0.1:8123",
            api_credential="native-only-secret",
            profile_dir=tmp_path,
            command_loop=commands.append,
        )

    assert commands == []
    assert window.destroy_calls == 1
