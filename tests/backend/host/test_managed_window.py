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

    assert provider_window.loaded_urls == [
        "https://www.snapeda.com/parts/ABC/Maker/view-part/",
        "about:blank",
    ]
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

    identity = {
        "componentId": "part-1",
        "providerId": "mouser",
        "routeId": "manual:mouser",
        "sessionId": "session-1",
    }
    with surface.lease(component_id="part-1", provider_id="mouser"):
        assert (
            surface.set_provider_viewport(
                {
                    **identity,
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
        assert provider_window.focus_calls == 0, "layout updates must not steal a React drag"
        assert surface.set_provider_viewport({
            **identity,
            "visible": True,
            "x": 128,
            "y": 114,
            "width": 1024,
            "height": 570,
        }) is True
        assert provider_window.move_calls == [(228, 174)]
        assert provider_window.resize_calls == [(1024, 570)]
        app_window.x = 300
        app_window.y = 180
        assert surface.reapply_provider_viewport() is True
        assert provider_window.move_calls[-1] == (428, 294)
        surface.provider_command({**identity, "command": "back"})
        assert provider_window.evaluations[-1] == "history.back()"
        surface.provider_command(
            {
                **identity,
                "command": "navigate",
                "url": "https://www.mouser.com/c/?q=LM358",
            }
        )
        assert provider_window.loaded_urls[-1] == "https://www.mouser.com/c/?q=LM358"
        assert not surface.provider_command(
            {
                **identity,
                "command": "navigate",
                "url": "file:///C:/Windows/System32/calc.exe",
            }
        )
        surface.provider_command({**identity, "command": "close"})
        assert provider_window.hidden_calls == 1

        assert (
            surface.set_provider_viewport(
                {
                    **identity,
                    "componentId": "part-2",
                    "visible": True,
                    "x": 128,
                    "y": 114,
                    "width": 1024,
                    "height": 570,
                }
            )
            is True
        )
        assert provider_window.hidden_calls == 2


def test_native_provider_is_embedded_in_client_coordinates_without_activation(monkeypatch) -> None:
    app = SimpleNamespace(native=SimpleNamespace(_scale=1.5))
    provider = SimpleNamespace()
    monkeypatch.setattr(W, "_is_windows", lambda: True)
    monkeypatch.setattr(
        W,
        "_current_process_window_handle",
        lambda window: 101 if window is app else 202,
    )

    class _User32:
        def __init__(self) -> None:
            self.parent_calls: list[tuple[int, int]] = []
            self.style_calls: list[tuple[int, int, int]] = []
            self.position_calls: list[tuple[int, int, int, int, int, int, int]] = []

        def GetWindowLongW(self, hwnd, index) -> int:
            assert (hwnd, index) == (202, -16)
            return 0x80000000

        def SetWindowLongW(self, hwnd, index, style) -> int:
            self.style_calls.append((hwnd, index, style))
            return 0

        def SetParent(self, child, parent) -> int:
            self.parent_calls.append((child, parent))
            return 0

        def SetWindowPos(self, hwnd, after, x, y, width, height, flags) -> int:
            self.position_calls.append((hwnd, after, x, y, width, height, flags))
            return 1

    user32 = _User32()
    assert W._place_provider_window_over_client(
        app,
        provider,
        100,
        80,
        900,
        560,
        user32=user32,
    )
    assert user32.parent_calls == [(202, 101)]
    assert user32.style_calls == [(202, -16, 0x46000000)]
    assert user32.position_calls == [
        (202, 0, 150, 120, 1350, 840, 0x0010 | 0x0020 | 0x0040)
    ]


def test_hidden_prelease_viewport_releases_component_identity(monkeypatch) -> None:
    app_window = _Window("http://127.0.0.1:8123/components")
    provider_window = _Window("about:blank#stockroom-provider-proof")
    monkeypatch.setattr(W, "_ACTIVE_WINDOW", app_window)
    surface = W.InAppProviderBrowserSurface(
        "http://127.0.0.1:8123",
        provider_window=lambda: provider_window,
    )
    first = {
        "componentId": "part-1",
        "providerId": "mouser",
        "routeId": "manual:mouser",
        "sessionId": "session-1",
        "visible": True,
        "x": 100,
        "y": 80,
        "width": 900,
        "height": 560,
    }
    assert surface.set_provider_viewport(first) is True
    assert surface.set_provider_viewport(
        {**first, "visible": False, "x": 0, "y": 0, "width": 0, "height": 0}
    ) is True
    assert surface.set_provider_viewport({
        **first,
        "componentId": "part-2",
        "providerId": "lcsc",
        "routeId": "manual:lcsc",
        "sessionId": "session-2",
    }) is True


def test_in_app_provider_surface_retains_modal_viewport_until_lease_is_ready(monkeypatch) -> None:
    """React can measure the modal before the backend has opened its native lease."""

    app_window = _Window("http://127.0.0.1:8123/components")
    app_window.x = 40
    app_window.y = 30
    provider_window = _Window("about:blank#stockroom-provider-proof")
    monkeypatch.setattr(W, "_ACTIVE_WINDOW", app_window)
    surface = W.InAppProviderBrowserSurface(
        "http://127.0.0.1:8123",
        provider_window=lambda: provider_window,
    )
    viewport = {
        "componentId": "part-1",
        "providerId": "mouser",
        "routeId": "manual:mouser",
        "sessionId": "session-1",
        "visible": True,
        "x": 100,
        "y": 80,
        "width": 900,
        "height": 560,
    }

    assert surface.set_provider_viewport(viewport) is True
    assert provider_window.show_calls == 0

    with surface.lease(component_id="part-1", provider_id="mouser") as lease:
        lease.navigate("https://www.mouser.com/c/?q=LM358")
        assert provider_window.move_calls == [(140, 110)]
        assert provider_window.resize_calls == [(900, 560)]
        assert provider_window.show_calls == 1


def test_renderer_cannot_open_a_provider_without_a_broker_lease(monkeypatch) -> None:
    app_window = _Window("http://127.0.0.1:8123/assets")
    provider_window = _Window("about:blank#stockroom-provider-proof")
    monkeypatch.setattr(W, "_ACTIVE_WINDOW", app_window)
    surface = W.InAppProviderBrowserSurface(
        "http://127.0.0.1:8123",
        provider_window=lambda: provider_window,
    )
    identity = {
        "componentId": "part-1",
        "providerId": "mouser",
        "routeId": "manual:mouser",
        "sessionId": "session-1",
    }
    assert surface.set_provider_viewport({
        **identity,
        "visible": True,
        "x": 100,
        "y": 80,
        "width": 900,
        "height": 560,
    }) is True

    assert surface.provider_command({
        **identity,
        "command": "navigate",
        "url": "https://www.mouser.com/c/?q=LM358",
    }) is False
    assert provider_window.loaded_urls == []
    assert provider_window.move_calls == []
    assert provider_window.resize_calls == []
    assert app_window.loaded_urls == []


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
