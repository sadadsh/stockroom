"""The endpoints behind inline specification editing and the preferred-source control.

Four addresses, one shape: every mutation answers with the WHOLE recomputed dossier, because the
reader replaces its state wholesale and can never drift by merging a partial response into a
document whose completeness, conflicts, provenance and revisions all moved with the same edit.

The refusals matter as much as the successes. A key the field registry does not define is
refused rather than written, a source that never answered for a field cannot be preferred for it,
and withdrawing a decision that was never made is a success rather than a 404.
"""

from __future__ import annotations

import threading

from stockroom.model.part import PartRecord, SourcedValue

_PART = "erj-p03f1101v"
_OVERRIDE = f"/api/library/parts/{_PART}/specifications/tolerance/override"
_PREFERRED = f"/api/library/parts/{_PART}/specifications/tolerance/preferred-source"


def _add_part(app_ctx) -> str:
    """A resistor two distributors disagree about, so a decision has something to decide.

    Mouser holds the answer computed precedence picks and DigiKey the one it does not, because
    the provider registry's distributor order is Mouser first (2026-08-05). The pin tests below
    pin DigiKey for that reason - pinning the source that already wins would prove nothing about
    promotion - so the two names were swapped here when the order was, and every assertion still
    says exactly what it said before.
    """
    record = PartRecord(
        id=_PART,
        mpn="ERJ-P03F1101V",
        manufacturer="Panasonic",
        display_name="ERJ-P03F1101V",
        category="Resistors",
        description="RES 1.1K OHM 1% 1/5W 0603 thick film",
        specs={"Resistance": "1.1 kOhms", "Tolerance": "1%", "Package / Case": "0603"},
    )
    record.alternates = {
        "Tolerance": [
            SourcedValue(value="1%", source="mouser"),
            SourcedValue(value="2%", source="digikey"),
        ]
    }
    path = app_ctx.profile.library.parts_dir / f"{record.id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.dumps(), encoding="utf-8")
    app_ctx.rebuild_index()
    return record.id


def _row(body: dict, key: str = "tolerance") -> dict:
    rows = [*body["keySpecifications"]]
    for group in body["specificationGroups"]:
        rows.extend(group["specifications"])
    matches = [row for row in rows if row["key"] == key]
    assert matches, f"the dossier serves no {key} row"
    return matches[0]


# --------------------------------------------------------------- access


def test_recording_an_override_requires_a_token(anon_client, app_ctx):
    _add_part(app_ctx)
    assert anon_client.put(_OVERRIDE, json={"value": "0.5%"}).status_code == 401


def test_clearing_an_override_requires_a_token(anon_client, app_ctx):
    _add_part(app_ctx)
    assert anon_client.delete(_OVERRIDE).status_code == 401


def test_preferring_a_source_requires_a_token(anon_client, app_ctx):
    _add_part(app_ctx)
    assert anon_client.put(_PREFERRED, json={"sourceId": "digikey"}).status_code == 401


def test_a_decision_about_an_unknown_part_is_not_found(client, app_ctx):
    _add_part(app_ctx)
    response = client.put(
        "/api/library/parts/nope/specifications/tolerance/override", json={"value": "1%"}
    )
    assert response.status_code == 404


# --------------------------------------------------------------- overrides


def test_recording_an_override_answers_with_the_whole_dossier(client, app_ctx):
    _add_part(app_ctx)
    response = client.put(_OVERRIDE, json={"value": "0.5%"})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == set(client.get(f"/api/library/parts/{_PART}/dossier").json())
    assert _row(body)["preferredValue"] == "0.5%"


def test_an_override_keeps_every_source_candidate_and_settles_the_conflict(client, app_ctx):
    _add_part(app_ctx)
    before = _row(client.get(f"/api/library/parts/{_PART}/dossier").json())
    assert before["conflictState"] == "conflicting"
    after = _row(client.put(_OVERRIDE, json={"value": "0.5%"}).json())
    assert after["conflictState"] == "resolved"
    assert {item["sourceId"] for item in after["sourceCandidates"]} == {
        "manual",
        "mouser",
        "digikey",
    }


def test_an_override_says_which_sourced_answer_it_replaced(client, app_ctx):
    _add_part(app_ctx)
    override = _row(client.put(_OVERRIDE, json={"value": "0.5%"}).json())["override"]
    assert override["replacedValue"] == "1%"
    assert override["replacedSourceLabel"] == "Mouser"
    assert override["reviewedAt"]


def test_an_override_is_persisted_on_the_record(client, app_ctx):
    _add_part(app_ctx)
    client.put(_OVERRIDE, json={"value": "0.5%"})
    stored = client.get(f"/api/library/parts/{_PART}").json()
    assert stored["overrides"]["tolerance"]["value"] == "0.5%"


def test_an_override_for_a_key_no_field_registry_claims_is_refused(client, app_ctx):
    _add_part(app_ctx)
    response = client.put(
        f"/api/library/parts/{_PART}/specifications/wibble_factor/override",
        json={"value": "9"},
    )
    assert response.status_code == 404
    assert "wibble_factor" in response.json()["detail"]


def test_a_refused_override_writes_no_ghost_field(client, app_ctx):
    _add_part(app_ctx)
    client.put(
        f"/api/library/parts/{_PART}/specifications/wibble_factor/override", json={"value": "9"}
    )
    assert "overrides" not in client.get(f"/api/library/parts/{_PART}").json()


def test_a_blank_override_is_refused_rather_than_stored_as_an_empty_answer(client, app_ctx):
    _add_part(app_ctx)
    assert client.put(_OVERRIDE, json={"value": "   "}).status_code == 422


def test_clearing_an_override_returns_the_field_to_its_sources(client, app_ctx):
    _add_part(app_ctx)
    client.put(_OVERRIDE, json={"value": "0.5%"})
    body = client.delete(_OVERRIDE).json()
    row = _row(body)
    assert row["preferredValue"] == "1%"
    assert row["override"] is None
    assert row["conflictState"] == "conflicting"


def test_clearing_an_override_that_was_never_set_is_not_an_error(client, app_ctx):
    _add_part(app_ctx)
    response = client.delete(_OVERRIDE)
    assert response.status_code == 200
    assert _row(response.json())["preferredValue"] == "1%"


def test_clearing_an_override_twice_leaves_the_same_dossier(client, app_ctx):
    _add_part(app_ctx)
    client.put(_OVERRIDE, json={"value": "0.5%"})
    first = client.delete(_OVERRIDE).json()
    second = client.delete(_OVERRIDE).json()
    for body in (first, second):
        body.pop("distributorOffers")
        body.pop("supplySummary")
    assert first == second


def test_clearing_an_override_for_an_unknown_key_is_still_refused(client, app_ctx):
    _add_part(app_ctx)
    response = client.delete(
        f"/api/library/parts/{_PART}/specifications/wibble_factor/override"
    )
    assert response.status_code == 404


# --------------------------------------------------------------- preferred source


def test_preferring_a_source_promotes_it_without_dropping_the_others(client, app_ctx):
    _add_part(app_ctx)
    row = _row(client.put(_PREFERRED, json={"sourceId": "digikey"}).json())
    assert row["preferredValue"] == "2%"
    assert row["preferredSource"]["sourceId"] == "digikey"
    assert {item["sourceId"] for item in row["sourceCandidates"]} == {"mouser", "digikey"}
    assert row["preferredSourcePin"]["inForce"] is True


def test_a_source_that_never_answered_for_the_field_cannot_be_preferred(client, app_ctx):
    _add_part(app_ctx)
    response = client.put(_PREFERRED, json={"sourceId": "arrow"})
    assert response.status_code == 422
    assert "overrides" not in client.get(f"/api/library/parts/{_PART}").json()


def test_a_preferred_source_must_name_a_source(client, app_ctx):
    _add_part(app_ctx)
    assert client.put(_PREFERRED, json={"sourceId": ""}).status_code == 422


def test_preferring_a_source_for_an_unknown_key_is_refused(client, app_ctx):
    _add_part(app_ctx)
    response = client.put(
        f"/api/library/parts/{_PART}/specifications/wibble_factor/preferred-source",
        json={"sourceId": "digikey"},
    )
    assert response.status_code == 404


def test_clearing_a_preferred_source_returns_the_field_to_computed_precedence(client, app_ctx):
    _add_part(app_ctx)
    client.put(_PREFERRED, json={"sourceId": "digikey"})
    row = _row(client.delete(_PREFERRED).json())
    assert row["preferredSource"]["sourceId"] == "mouser"
    assert row["preferredSourcePin"] is None
    assert row["conflictState"] == "conflicting"


def test_clearing_a_preferred_source_that_was_never_set_is_not_an_error(client, app_ctx):
    _add_part(app_ctx)
    assert client.delete(_PREFERRED).status_code == 200


def test_a_reviewed_value_outranks_a_preferred_source(client, app_ctx):
    _add_part(app_ctx)
    client.put(_PREFERRED, json={"sourceId": "digikey"})
    row = _row(client.put(_OVERRIDE, json={"value": "0.5%"}).json())
    assert row["preferredValue"] == "0.5%"
    assert row["preferredSourcePin"]["inForce"] is False


def test_clearing_the_override_hands_the_field_back_to_the_preferred_source(client, app_ctx):
    _add_part(app_ctx)
    client.put(_PREFERRED, json={"sourceId": "digikey"})
    client.put(_OVERRIDE, json={"value": "0.5%"})
    row = _row(client.delete(_OVERRIDE).json())
    assert row["preferredValue"] == "2%"
    assert row["preferredSourcePin"]["inForce"] is True


# --------------------------------------------------------------- durability


def test_a_decision_is_committed_rather_than_left_in_the_working_tree(client, app_ctx):
    _add_part(app_ctx)
    path = app_ctx.profile.library.parts_dir / f"{_PART}.json"
    app_ctx.repo.commit("seed the part", [path])
    client.put(_OVERRIDE, json={"value": "0.5%"})
    assert app_ctx.repo.is_clean([path])
    assert "0.5%" in (app_ctx.repo.show_file("HEAD", path) or "")


def test_a_refused_decision_leaves_the_record_untouched_on_disk(client, app_ctx):
    _add_part(app_ctx)
    path = app_ctx.profile.library.parts_dir / f"{_PART}.json"
    app_ctx.repo.commit("seed the part", [path])
    before = path.read_text(encoding="utf-8")
    client.put(_PREFERRED, json={"sourceId": "arrow"})
    assert path.read_text(encoding="utf-8") == before
    assert app_ctx.repo.is_clean([path])


def test_two_decisions_landing_at_once_both_survive(app_ctx):
    """The read-modify-write happens under the repository's own write lock.

    Loading outside the transaction would let each writer build its record from a snapshot taken
    before the other's change, and the second commit would silently drop the first field.
    """
    _add_part(app_ctx)
    errors: list[Exception] = []

    def decide(key: str, value: str) -> None:
        try:
            app_ctx.ops.set_specification_override(
                _PART, key, value, reviewed_by="user", reviewed_at="2026-08-05"
            )
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            errors.append(exc)

    threads = [
        threading.Thread(target=decide, args=("tolerance", "0.5%")),
        threading.Thread(target=decide, args=("resistance", "1.2 kOhms")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    overrides = app_ctx.ops.load_record(_PART).overrides
    assert set(overrides) == {"tolerance", "resistance"}


# --------------------------------------------- the reason, and whether it was checked


def test_an_override_carries_the_reason_it_was_recorded_for(client, app_ctx):
    _add_part(app_ctx)
    body = client.put(
        _OVERRIDE, json={"value": "0.5%", "note": "measured on the reel label"}
    ).json()
    assert _row(body)["override"]["note"] == "measured on the reel label"


def test_an_override_the_reviewer_did_not_confirm_comes_back_unverified(client, app_ctx):
    _add_part(app_ctx)
    body = client.put(_OVERRIDE, json={"value": "0.5%", "verified": False}).json()
    row = _row(body)
    assert row["verificationState"] == "unverified"
    assert row["override"]["verified"] is False
    # And the value itself still stands: not confirming it is not withdrawing it.
    assert row["displayValue"] == "0.5%"


def test_an_override_with_neither_stated_is_a_confirmed_one_with_no_reason(client, app_ctx):
    # Which is exactly what every override written before those two fields existed meant.
    _add_part(app_ctx)
    row = _row(client.put(_OVERRIDE, json={"value": "0.5%"}).json())
    assert row["verificationState"] == "verified"
    assert row["override"] == {
        "value": "0.5%",
        "note": "",
        "verified": True,
        "reviewedBy": "user",
        "reviewedAt": row["override"]["reviewedAt"],
        "replacedValue": "1%",
        "replacedSource": "mouser",
        "replacedSourceLabel": "Mouser",
    }
