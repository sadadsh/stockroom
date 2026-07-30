from __future__ import annotations

import json

import pytest

from stockroom.store import ui_session
from stockroom.store.ui_session import (
    MAX_SESSION_BYTES,
    bootstrap_script,
    create_draft,
    default_snapshot,
    load_draft,
    load_snapshot,
    persist_export_envelope,
    save_snapshot,
    snapshot_path,
    update_draft,
)


def _draft_body(value: str = "TPS62130") -> dict:
    network_input = {"kind": "mpn", "value": value}
    return {
        "network_input": network_input,
        "review": {
            "lookup_input": network_input,
            "enrichment_result": None,
            "candidates": [],
        },
    }


def test_snapshot_defaults_then_survives_a_fresh_store_read() -> None:
    assert load_snapshot() == default_snapshot()

    document = default_snapshot()
    document["route"] = "settings"
    document["settings_group"] = "sources"
    document["selected_ids"]["workflow_batch"] = "batch-42"
    document["event_sequence"] = 918
    saved = save_snapshot(document)

    assert load_snapshot() == saved
    assert json.loads(snapshot_path().read_text(encoding="utf-8")) == saved


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update({"unknown": "value"}),
        lambda d: d["selected_ids"].update({"password": "not-allowed"}),
        lambda d: d["search_filters"]["options"].append(
            {"key": "Package", "values": ["0402"], "extra": True}
        ),
        lambda d: d.update({"route": "https://outside.example"}),
        lambda d: d.update({"event_sequence": -1}),
        lambda d: d["search_sort"].update({"kind": "spec", "key": "R"}),
    ],
)
def test_snapshot_rejects_unknown_and_hostile_shapes_without_writing(mutate) -> None:
    document = default_snapshot()
    mutate(document)

    with pytest.raises(ValueError):
        save_snapshot(document)

    assert not snapshot_path().exists()


def test_snapshot_rejects_oversize_and_corrupt_persisted_documents() -> None:
    snapshot_path().parent.mkdir(parents=True)
    snapshot_path().write_bytes(b"{" + b"x" * MAX_SESSION_BYTES + b"}")
    with pytest.raises(ValueError):
        load_snapshot()

    snapshot_path().write_text(
        '{"schema":"stockroom.ui-session","schema":"duplicate"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_snapshot()


def test_atomic_replace_failure_preserves_the_previous_snapshot(
    monkeypatch,
) -> None:
    original = default_snapshot()
    original["route"] = "settings"
    save_snapshot(original)
    before = snapshot_path().read_bytes()

    changed = default_snapshot()
    changed["route"] = "stm"

    def fail_replace(_source, _target):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(ui_session.os, "replace", fail_replace)
    with pytest.raises(OSError):
        save_snapshot(changed)

    assert snapshot_path().read_bytes() == before
    assert not list(snapshot_path().parent.glob(".ui-session.json.*.tmp"))


def test_failed_snapshot_replace_after_draft_stage_keeps_old_pair_restorable(
    monkeypatch,
) -> None:
    first = create_draft(_draft_body("TPS62130"))
    snapshot = default_snapshot()
    snapshot["open_surface"] = "add_part"
    snapshot["intake_draft_ref"] = {
        "draft_id": first["draft_id"],
        "revision": first["revision"],
    }
    save_snapshot(snapshot)
    real_replace = ui_session.os.replace

    def fail_only_snapshot(source, target):
        if target == snapshot_path():
            raise OSError("simulated snapshot replace failure")
        return real_replace(source, target)

    monkeypatch.setattr(ui_session.os, "replace", fail_only_snapshot)
    with pytest.raises(OSError):
        persist_export_envelope(
            {
                "snapshot": snapshot,
                "intake_draft": {
                    "draft_id": first["draft_id"],
                    "revision": first["revision"],
                    **_draft_body("TPS62130A"),
                },
            }
        )

    restored = load_snapshot()
    assert restored["intake_draft_ref"] == snapshot["intake_draft_ref"]
    assert load_draft(first["draft_id"], 1)["network_input"]["value"] == "TPS62130"
    # The immutable staged revision may be orphaned, but cannot invalidate the
    # previous revision the unchanged snapshot still names.
    assert load_draft(first["draft_id"], 2)["network_input"]["value"] == "TPS62130A"


def test_draft_revisions_are_immutable_and_snapshot_ref_resolves_exactly() -> None:
    first = create_draft(_draft_body())
    second = update_draft(
        first["draft_id"],
        {
            **_draft_body("TPS62130A"),
            "revision": first["revision"],
        },
    )

    assert second["revision"] == 2
    assert load_draft(first["draft_id"], 1)["network_input"]["value"] == "TPS62130"
    assert load_draft(first["draft_id"], 2)["network_input"]["value"] == "TPS62130A"

    snapshot = default_snapshot()
    snapshot["open_surface"] = "add_part"
    snapshot["intake_draft_ref"] = {
        "draft_id": second["draft_id"],
        "revision": second["revision"],
    }
    save_snapshot(snapshot)
    assert load_snapshot()["intake_draft_ref"] == snapshot["intake_draft_ref"]


def test_snapshot_with_a_dangling_draft_reference_fails_closed() -> None:
    snapshot = default_snapshot()
    snapshot["intake_draft_ref"] = {
        "draft_id": "b97e72b7-2110-4d43-9974-d192f296cf9d",
        "revision": 1,
    }
    with pytest.raises(FileNotFoundError):
        save_snapshot(snapshot)
    assert not snapshot_path().exists()


def test_draft_sanitizes_urls_and_rejects_secret_shaped_dynamic_fields() -> None:
    body = _draft_body()
    body["network_input"] = {
        "kind": "product_url",
        "value": "https://www.digikey.com/en/products/detail/x?session=private#gate",
    }
    body["review"]["lookup_input"] = body["network_input"]
    draft = create_draft(body)
    assert draft["network_input"]["value"] == (
        "https://www.digikey.com/en/products/detail/x"
    )

    hostile = _draft_body()
    hostile["review"]["enrichment_result"] = {
        "category": "ICs",
        "mpn": None,
        "manufacturer": None,
        "description": None,
        "datasheet_url": None,
        "stock": None,
        "package": None,
        "price_breaks": [],
        "specs": {"github_token": "do-not-reflect"},
        "schema_version": 1,
    }
    with pytest.raises(ValueError) as error:
        create_draft(hostile)
    assert "do-not-reflect" not in str(error.value)


def test_bootstrap_script_cannot_close_its_script_element() -> None:
    document = default_snapshot()
    document["component_filters"]["query"] = "</script><script>hostile()</script>"
    script = bootstrap_script(document)

    assert "window.__STOCKROOM_SESSION__" in script
    assert "</script>" not in script
