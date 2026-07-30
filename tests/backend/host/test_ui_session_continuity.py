from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

import stockroom.host.window as window_module
from stockroom.host.run import _persist_active_window_session, _reload_active_window
from stockroom.store.ui_session import (
    create_draft,
    default_snapshot,
    load_draft,
    load_snapshot,
)


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
    def __init__(self, exported: object) -> None:
        self.exported = exported
        self.current_url = "http://127.0.0.1:43210/#route=components"
        self.loaded = _LoadedEvent()
        self.events = SimpleNamespace(loaded=self.loaded)
        self.navigations: list[str] = []

    def evaluate_js(self, _script: str):
        return self.exported

    def get_current_url(self) -> str:
        return self.current_url

    def load_url(self, url: str) -> None:
        self.navigations.append(url)
        self.loaded.fire()


def _review(value: str) -> dict:
    network = {"kind": "mpn", "value": value}
    return {
        "network_input": network,
        "review": {
            "lookup_input": network,
            "enrichment_result": None,
            "candidates": [],
        },
    }


def test_reload_stages_last_keystroke_draft_then_snapshot_before_navigation(
    monkeypatch,
) -> None:
    draft = create_draft(_review("TPS62130"))
    snapshot = default_snapshot()
    snapshot["open_surface"] = "add_part"
    snapshot["event_sequence"] = 77
    snapshot["selected_ids"]["workflow_batch"] = "batch-live"
    window = _Window(
        {
            "snapshot": snapshot,
            "intake_draft": {
                "draft_id": draft["draft_id"],
                "revision": draft["revision"],
                **_review("TPS62130A"),
            },
        }
    )
    monkeypatch.setattr(window_module, "active_window", lambda: window)

    _reload_active_window("http://127.0.0.1:43210")

    navigation = urlsplit(window.navigations[0])
    assert navigation.scheme == "http"
    assert navigation.netloc == "127.0.0.1:43210"
    assert navigation.fragment == "route=components"
    assert parse_qs(navigation.query)["__stockroom_reload"]
    restored = load_snapshot()
    assert restored["event_sequence"] == 77
    assert restored["selected_ids"]["workflow_batch"] == "batch-live"
    ref = restored["intake_draft_ref"]
    assert ref == {"draft_id": draft["draft_id"], "revision": 2}
    assert load_draft(ref["draft_id"], ref["revision"])["network_input"]["value"] == (
        "TPS62130A"
    )


def test_invalid_export_aborts_navigation_and_preserves_previous_state(
    monkeypatch,
) -> None:
    previous = default_snapshot()
    previous["route"] = "settings"
    from stockroom.store.ui_session import save_snapshot

    save_snapshot(previous)
    invalid = default_snapshot()
    invalid["password"] = "must-not-persist"
    window = _Window({"snapshot": invalid})
    monkeypatch.setattr(window_module, "active_window", lambda: window)

    with pytest.raises(RuntimeError, match="export was invalid"):
        _reload_active_window("http://127.0.0.1:43210")

    assert window.navigations == []
    assert load_snapshot() == previous


def test_invalid_export_cannot_veto_a_full_process_restart() -> None:
    previous = default_snapshot()
    previous["route"] = "settings"
    from stockroom.store.ui_session import save_snapshot

    save_snapshot(previous)
    invalid = default_snapshot()
    invalid["password"] = "must-not-persist"
    window = _Window({"snapshot": invalid})

    assert _persist_active_window_session(window, required=False) is False
    assert load_snapshot() == previous
