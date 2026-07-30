from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

import stockroom.host.window as window_module
from stockroom.host.run import _reload_active_window


class _LoadedEvent:
    def __init__(self) -> None:
        self._handlers: list[Callable[[], None]] = []

    def __iadd__(self, handler: Callable[[], None]):
        self._handlers.append(handler)
        return self

    def __isub__(self, handler: Callable[[], None]):
        self._handlers.remove(handler)
        return self

    def fire(self) -> None:
        for handler in tuple(self._handlers):
            handler()


class _Window:
    def __init__(self, current_url: str) -> None:
        self.current_url = current_url
        self.loaded = _LoadedEvent()
        self.events = SimpleNamespace(loaded=self.loaded)
        self.navigations: list[str] = []

    def get_current_url(self) -> str:
        return self.current_url

    def load_url(self, url: str) -> None:
        self.current_url = url
        self.navigations.append(url)
        self.loaded.fire()


def test_adoption_and_rollback_reload_preserve_the_active_same_origin_route(
    monkeypatch,
) -> None:
    window = _Window(
        "http://127.0.0.1:43210/settings/providers?source=ultra#credentials"
    )
    monkeypatch.setattr(window_module, "active_window", lambda: window)

    _reload_active_window("http://127.0.0.1:43210")
    _reload_active_window("http://127.0.0.1:43210")

    assert window.navigations == [
        "http://127.0.0.1:43210/settings/providers?source=ultra#credentials",
        "http://127.0.0.1:43210/settings/providers?source=ultra#credentials",
    ]


def test_update_reload_does_not_carry_a_cross_origin_route(monkeypatch) -> None:
    window = _Window("https://provider.example/download?session=private#gate")
    monkeypatch.setattr(window_module, "active_window", lambda: window)

    _reload_active_window("http://127.0.0.1:43210")

    assert window.navigations == ["http://127.0.0.1:43210"]
