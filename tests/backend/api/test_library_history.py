"""M6k: per-part git timeline + structured diff over the part's canonical JSON,
read from git blobs with no working-tree checkout."""

from __future__ import annotations

from stockroom.model.part import LibRef, PartRecord


def _history(client, part_id):
    r = client.get(f"/api/library/parts/{part_id}/history")
    assert r.status_code == 200, r.text
    return r.json()


def test_history_lists_commits_newest_first(client):
    # a manufacturer edit adds a second commit on top of the seed
    assert client.patch(
        "/api/library/parts/tps62130", json={"field": "manufacturer", "value": "NewCo"}
    ).status_code == 200
    body = _history(client, "tps62130")
    subjects = [c["subject"] for c in body["commits"]]
    assert body["count"] == len(body["commits"])
    assert subjects[0] == "Edit tps62130: manufacturer"
    assert subjects[-1] == "seed fixture parts and category libraries"
    for c in body["commits"]:
        assert len(c["sha"]) == 40
        assert c["author"]
        assert c["iso_date"]


def test_history_404_for_unknown_part(client):
    assert client.get("/api/library/parts/nope/history").status_code == 404


def test_history_is_empty_for_an_uncommitted_part(client, app_ctx):
    # a part present in the index but never committed has no timeline yet: an honest
    # empty list, not an error.
    rec = PartRecord(id="ghost", display_name="GHOST", category="ICs")
    rec.symbol = LibRef(lib="SR-ICs", name="GHOST")
    (app_ctx.profile.library.parts_dir / "ghost.json").write_text(rec.dumps(), encoding="utf-8")
    app_ctx.rebuild_index()
    body = _history(client, "ghost")
    assert body["commits"] == []
    assert body["count"] == 0


def test_diff_reports_field_changes_between_two_revs(client):
    seed = _history(client, "tps62130")["commits"][0]["sha"]
    assert client.patch(
        "/api/library/parts/tps62130", json={"field": "manufacturer", "value": "NewCo"}
    ).status_code == 200
    edit = _history(client, "tps62130")["commits"][0]["sha"]
    r = client.get(f"/api/library/parts/tps62130/diff", params={"a": seed, "b": edit})
    assert r.status_code == 200, r.text
    body = r.json()
    changes = {f["key"]: f for f in body["fields"]}
    assert changes["manufacturer"]["before"] == "TI"
    assert changes["manufacturer"]["after"] == "NewCo"
    assert changes["manufacturer"]["status"] == "changed"


def test_diff_first_version_is_all_added(client):
    seed = _history(client, "tps62130")["commits"][0]["sha"]
    # a="" means the part did not exist before this rev: every field reads as added
    r = client.get(f"/api/library/parts/tps62130/diff", params={"a": "", "b": seed})
    assert r.status_code == 200, r.text
    changes = {f["key"]: f for f in r.json()["fields"]}
    assert changes["mpn"]["status"] == "added"
    assert changes["mpn"]["before"] is None
    assert changes["manufacturer"]["after"] == "TI"


def test_diff_detects_a_symbol_change_but_not_footprint(client):
    # editing manufacturer mirrors the Manufacturer property into the symbol lib but
    # never touches the footprint file
    seed = _history(client, "tps62130")["commits"][0]["sha"]
    assert client.patch(
        "/api/library/parts/tps62130", json={"field": "manufacturer", "value": "NewCo"}
    ).status_code == 200
    edit = _history(client, "tps62130")["commits"][0]["sha"]
    body = client.get(
        f"/api/library/parts/tps62130/diff", params={"a": seed, "b": edit}
    ).json()
    assert body["assets"]["symbol"] is True
    assert body["assets"]["footprint"] is False


def test_diff_404_for_unknown_part(client):
    r = client.get("/api/library/parts/nope/diff", params={"a": "", "b": "HEAD"})
    assert r.status_code == 404


def test_diff_rejects_a_rev_outside_the_parts_history(client):
    seed = _history(client, "tps62130")["commits"][0]["sha"]
    r = client.get(
        "/api/library/parts/tps62130/diff", params={"a": "deadbeefdeadbeef", "b": seed}
    )
    assert r.status_code == 400
