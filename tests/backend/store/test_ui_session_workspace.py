"""The durable half of the opened-component workspace.

Tab state has to survive a host restart, so it lives in the same durable session document as
the route and the picker anchor. These tests hold the v1 upgrade path and the bounds that keep
the document small and honest.
"""

from __future__ import annotations

import pytest

from stockroom.store.ui_session import (
    SESSION_SCHEMA,
    SESSION_VERSION,
    default_snapshot,
    normalize_snapshot,
)


def _v1() -> dict:
    """A stored v1 document: the current default, minus the v2 keys, at version 1."""
    snapshot = default_snapshot()
    for key in ("open_components", "active_component", "component_views"):
        snapshot.pop(key)
    snapshot["version"] = 1
    return snapshot


def _view(**overrides) -> dict:
    view = {
        "info_tab": "overview",
        "representation_layout": "all",
        "representation_tool": {"symbol": "kicad", "footprint": "kicad", "model": "kicad"},
    }
    view.update(overrides)
    return view


def test_the_default_snapshot_is_the_current_version_with_no_open_tabs():
    snapshot = default_snapshot()
    assert snapshot["version"] == SESSION_VERSION == 2
    assert snapshot["open_components"] == []
    assert snapshot["active_component"] is None
    assert snapshot["component_views"] == {}


def test_a_stored_v1_document_upgrades_instead_of_being_discarded():
    stored = _v1()
    stored["route"] = "projects"
    stored["component_filters"]["query"] = "stm32"
    upgraded = normalize_snapshot(stored)
    assert upgraded["version"] == 2
    # Everything the person had is still there.
    assert upgraded["route"] == "projects"
    assert upgraded["component_filters"]["query"] == "stm32"


def test_the_v1_selected_component_becomes_its_open_tab():
    stored = _v1()
    stored["selected_ids"]["component"] = "stm32h743vit6"
    upgraded = normalize_snapshot(stored)
    assert upgraded["open_components"] == ["stm32h743vit6"]
    assert upgraded["active_component"] == "stm32h743vit6"
    assert upgraded["selected_ids"]["component"] == "stm32h743vit6"


def test_a_v1_document_with_no_selection_upgrades_to_no_tabs():
    upgraded = normalize_snapshot(_v1())
    assert upgraded["open_components"] == []
    assert upgraded["active_component"] is None


def test_a_document_from_a_newer_build_is_never_silently_downgraded():
    newer = default_snapshot()
    newer["version"] = SESSION_VERSION + 1
    with pytest.raises(ValueError):
        normalize_snapshot(newer)


def test_a_foreign_schema_is_rejected_even_at_version_one():
    stored = _v1()
    stored["schema"] = "something.else"
    with pytest.raises(ValueError):
        normalize_snapshot(stored)


def test_open_tabs_round_trip_with_their_view_state():
    snapshot = default_snapshot()
    snapshot["open_components"] = ["a", "b"]
    snapshot["active_component"] = "b"
    snapshot["component_views"] = {
        "a": _view(info_tab="sourcing", representation_layout="symbol"),
        "b": _view(),
    }
    result = normalize_snapshot(snapshot)
    assert result["open_components"] == ["a", "b"]
    assert result["active_component"] == "b"
    assert result["component_views"]["a"]["info_tab"] == "sourcing"
    assert result["component_views"]["a"]["representation_layout"] == "symbol"


def test_an_active_tab_that_is_not_open_is_dropped_without_losing_the_session():
    snapshot = default_snapshot()
    snapshot["open_components"] = ["a"]
    snapshot["active_component"] = "ghost"
    snapshot["route"] = "settings"
    result = normalize_snapshot(snapshot)
    assert result["active_component"] is None
    assert result["open_components"] == ["a"]
    assert result["route"] == "settings"


def test_view_state_for_a_closed_tab_is_pruned():
    snapshot = default_snapshot()
    snapshot["open_components"] = ["a"]
    snapshot["component_views"] = {"a": _view(), "closed": _view()}
    result = normalize_snapshot(snapshot)
    assert set(result["component_views"]) == {"a"}


def test_more_than_twelve_open_tabs_is_rejected():
    snapshot = default_snapshot()
    snapshot["open_components"] = [f"part-{n}" for n in range(13)]
    with pytest.raises(ValueError):
        normalize_snapshot(snapshot)


def test_a_duplicate_tab_is_rejected():
    snapshot = default_snapshot()
    snapshot["open_components"] = ["a", "a"]
    with pytest.raises(ValueError):
        normalize_snapshot(snapshot)


@pytest.mark.parametrize(
    "view",
    [
        _view(info_tab="identity"),
        _view(representation_layout="everything"),
        _view(representation_tool={"symbol": "kicad"}),
    ],
)
def test_off_vocabulary_view_state_is_rejected(view):
    snapshot = default_snapshot()
    snapshot["open_components"] = ["a"]
    snapshot["component_views"] = {"a": view}
    with pytest.raises(ValueError):
        normalize_snapshot(snapshot)


def test_the_workspace_keys_are_part_of_the_exact_contract():
    snapshot = default_snapshot()
    snapshot.pop("open_components")
    with pytest.raises(ValueError):
        normalize_snapshot(snapshot)


def test_normalizing_is_stable():
    snapshot = default_snapshot()
    snapshot["open_components"] = ["a", "b"]
    snapshot["active_component"] = "a"
    snapshot["component_views"] = {"a": _view()}
    once = normalize_snapshot(snapshot)
    assert normalize_snapshot(once) == once
    assert once["schema"] == SESSION_SCHEMA
