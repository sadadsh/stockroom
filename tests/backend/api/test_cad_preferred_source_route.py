"""Choosing which provider supplies a component's CAD, over HTTP.

Four addresses: the whole set and one asset, each set and cleared. All four answer with the WHOLE
recomputed dossier, because a preferred source moves the three asset modules, the coverage
comparison and the revision timeline together and a reader that merged a partial response would
be holding a document whose parts disagree.

The refusals are the point of the endpoint, not an edge case. A provider that cannot supply an
artifact is a 422; an asset kind that does not exist is a 404; and a per-asset pin that would
leave two providers in force is a 422 whose message names what it would collide with - because
the alternative is writing a preference the coherence gate will later refuse to honour.
"""

from __future__ import annotations

from stockroom.model.asset import Asset, AssetOrigin, AssetRef
from stockroom.model.part import PartRecord


def _add_part(app_ctx, *, vendor: str = "") -> str:
    record = PartRecord(
        id="stm32h743vit6",
        mpn="STM32H743VIT6",
        manufacturer="STMicroelectronics",
        display_name="STM32H743VIT6",
        category="ICs",
        description="Arm Cortex-M7 microcontroller",
        specs={"package": "LQFP100", "pin_count": "100"},
    )
    if vendor:
        bundle = record.assets_for("kicad")
        bundle.symbol = Asset(
            ref=AssetRef(lib="SR-ICs", name="STM32H743VIT6"),
            origin=AssetOrigin(vendor=vendor),
        )
        bundle.footprint = Asset(
            ref=AssetRef(lib="SR-ICs", name="LQFP100"), origin=AssetOrigin(vendor=vendor)
        )
        bundle.model = Asset(
            ref=AssetRef(file="models/LQFP100.step"), origin=AssetOrigin(vendor=vendor)
        )
    path = app_ctx.profile.library.parts_dir / f"{record.id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.dumps(), encoding="utf-8")
    app_ctx.rebuild_index()
    return record.id


def _preference(body: dict) -> dict:
    return body["cadAssets"]["preference"]


def test_the_preferred_source_requires_a_token(anon_client, app_ctx):
    part_id = _add_part(app_ctx)
    response = anon_client.put(
        f"/api/library/parts/{part_id}/cad/preferred-source",
        json={"provider": "ultralibrarian"},
    )
    assert response.status_code == 401


def test_the_dossier_publishes_a_choosable_option_for_every_provider(client, app_ctx):
    part_id = _add_part(app_ctx)
    body = client.get(f"/api/library/parts/{part_id}/dossier").json()
    options = _preference(body)["options"]
    assert {option["provider"] for option in options} == {
        row["id"] for row in body["cadSourceCoverage"]["rows"]
    }
    # Every option carries what choosing it would do, planned rather than reported afterwards.
    assert all("changes" in option["set"] and "allowed" in option["set"] for option in options)


def test_preferring_a_provider_that_supplies_the_whole_set_answers_with_the_dossier(
    client, app_ctx
):
    part_id = _add_part(app_ctx, vendor="ultralibrarian")
    response = client.put(
        f"/api/library/parts/{part_id}/cad/preferred-source",
        json={"provider": "ultralibrarian"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["identity"]["mpn"] == "STM32H743VIT6"
    preference = _preference(body)
    assert preference["pinned"] is True
    assert preference["provider"] == "ultralibrarian"
    assert preference["mixed"] is False


def test_a_provider_that_does_not_supply_an_artifact_is_refused(client, app_ctx):
    part_id = _add_part(app_ctx)
    response = client.put(
        f"/api/library/parts/{part_id}/cad/preferred-source",
        json={"provider": "ultralibrarian"},
    )
    assert response.status_code == 422
    assert "Ultra Librarian" in response.json()["detail"]
    # Nothing was written: the record still prefers nothing.
    after = client.get(f"/api/library/parts/{part_id}/dossier").json()
    assert _preference(after)["pinned"] is False


def test_an_unnamed_provider_is_rejected_by_the_request_shape(client, app_ctx):
    part_id = _add_part(app_ctx)
    response = client.put(
        f"/api/library/parts/{part_id}/cad/preferred-source", json={"provider": "  "}
    )
    assert response.status_code == 422


def test_clearing_the_preference_returns_the_assets_to_their_attached_files(client, app_ctx):
    part_id = _add_part(app_ctx, vendor="ultralibrarian")
    client.put(
        f"/api/library/parts/{part_id}/cad/preferred-source",
        json={"provider": "ultralibrarian"},
    )
    response = client.delete(f"/api/library/parts/{part_id}/cad/preferred-source")
    assert response.status_code == 200
    preference = _preference(response.json())
    assert preference["pinned"] is False
    assert preference["assets"]["symbol"]["origin"] == "installed"


def test_clearing_a_preference_that_was_never_recorded_is_a_success(client, app_ctx):
    part_id = _add_part(app_ctx)
    assert client.delete(f"/api/library/parts/{part_id}/cad/preferred-source").status_code == 200


def test_one_asset_can_be_pinned_to_the_provider_already_in_force(client, app_ctx):
    part_id = _add_part(app_ctx, vendor="ultralibrarian")
    response = client.put(
        f"/api/library/parts/{part_id}/cad/footprint/preferred-source",
        json={"provider": "ultralibrarian"},
    )
    assert response.status_code == 200
    preference = _preference(response.json())
    assert preference["assets"]["footprint"]["origin"] == "asset_preference"
    assert preference["mixed"] is False


def test_a_per_asset_pin_to_a_provider_with_nothing_recorded_is_refused(client, app_ctx):
    """The refusal that keeps the set coherent, at the first gate it can be caught.

    With Ultra Librarian's files attached and nothing at all recorded for SamacSys, the pin is
    refused for the earlier of the two reasons - the provider has no footprint for this part -
    and the message names the artifact rather than lecturing about the set. The mixing rule
    itself is exercised in `tests/backend/dossier/test_cad_preference.py`, where the coverage
    evidence can be stated exactly.
    """
    part_id = _add_part(app_ctx, vendor="ultralibrarian")
    response = client.put(
        f"/api/library/parts/{part_id}/cad/footprint/preferred-source",
        json={"provider": "samacsys"},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "SamacSys" in detail and "Footprint" in detail
    assert "all three" not in detail


def test_an_asset_kind_this_component_does_not_have_is_a_404(client, app_ctx):
    part_id = _add_part(app_ctx, vendor="ultralibrarian")
    response = client.put(
        f"/api/library/parts/{part_id}/cad/schematic/preferred-source",
        json={"provider": "ultralibrarian"},
    )
    assert response.status_code == 404


def test_clearing_one_asset_pin_leaves_the_set_preference_standing(client, app_ctx):
    part_id = _add_part(app_ctx, vendor="ultralibrarian")
    client.put(
        f"/api/library/parts/{part_id}/cad/preferred-source",
        json={"provider": "ultralibrarian"},
    )
    client.put(
        f"/api/library/parts/{part_id}/cad/model/preferred-source",
        json={"provider": "ultralibrarian"},
    )
    response = client.delete(f"/api/library/parts/{part_id}/cad/model/preferred-source")
    assert response.status_code == 200
    preference = _preference(response.json())
    assert preference["pinned"] is True
    assert preference["assets"]["model"]["origin"] == "set_preference"


def test_a_part_that_does_not_exist_is_a_404(client):
    response = client.put(
        "/api/library/parts/nothing-here/cad/preferred-source",
        json={"provider": "ultralibrarian"},
    )
    assert response.status_code == 404
