"""The provider coverage endpoint: see every provider, and correct what Stockroom got wrong.

The owner's requirement is that a person can reach every provider and use whichever one supplies
a complete set. That means the route must list all of them, must link the ones it can honestly
link, and must let a person say what they know - without that claim ever displacing a file
Stockroom is already holding.
"""

from __future__ import annotations

import json

from stockroom.model.part import Datasheet, PartRecord, Purchase
from stockroom.providers import all_providers


def _add_part(app_ctx, **overrides) -> str:
    record = PartRecord(
        id="stm32h743vit6",
        mpn="STM32H743VIT6",
        manufacturer="STMicroelectronics",
        display_name="STM32H743VIT6",
        category="ICs",
        description="Arm Cortex-M7 microcontroller",
        datasheet=Datasheet(source_url="https://example.test/ds.pdf"),
        purchase=[Purchase(vendor="DigiKey", url="https://www.digikey.com/en/products/detail/1")],
        **overrides,
    )
    path = app_ctx.profile.library.parts_dir / f"{record.id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.dumps(), encoding="utf-8")
    app_ctx.rebuild_index()
    return record.id


def test_provider_coverage_requires_a_token(anon_client, app_ctx):
    part_id = _add_part(app_ctx)
    assert anon_client.get(f"/api/library/parts/{part_id}/providers").status_code == 401


def test_every_registered_provider_is_reachable_for_a_component(client, app_ctx):
    part_id = _add_part(app_ctx)
    body = client.get(f"/api/library/parts/{part_id}/providers").json()
    assert [row["id"] for row in body["rows"]] == [p.key for p in all_providers()]
    rows = {row["id"]: row for row in body["rows"]}
    assert rows["digikey"]["url"] == "https://www.digikey.com/en/products/detail/1"
    assert "STM32H743VIT6" in rows["ultralibrarian"]["url"]
    # No measured search surface and no exact page: no link is the honest answer.
    assert rows["traceparts"]["url"] == ""


def test_the_workspace_carries_the_same_coverage(client, app_ctx):
    part_id = _add_part(app_ctx)
    workspace = client.get(f"/api/library/parts/{part_id}/workspace").json()
    coverage = client.get(f"/api/library/parts/{part_id}/providers").json()
    assert workspace["providers"] == coverage


def test_a_person_can_record_and_withdraw_what_they_know(client, app_ctx):
    part_id = _add_part(app_ctx)
    response = client.post(
        f"/api/library/parts/{part_id}/providers",
        json={"provider": "snapmagic", "artifact": "model", "status": "available"},
    )
    assert response.status_code == 200
    rows = {row["id"]: row for row in response.json()["rows"]}
    assert rows["snapmagic"]["model"]["status"] == "available"
    assert rows["snapmagic"]["model"]["origin"] == "user"
    assert rows["snapmagic"]["model"]["userAssertion"]["notedAt"]

    stored = json.loads(
        (app_ctx.profile.library.parts_dir / f"{part_id}.json").read_text(encoding="utf-8")
    )
    assert stored["provider_assertions"]["snapmagic"]["model"]["origin"] == "user"

    client.post(
        f"/api/library/parts/{part_id}/providers",
        json={"provider": "snapmagic", "artifact": "model", "status": ""},
    )
    reloaded = json.loads(
        (app_ctx.profile.library.parts_dir / f"{part_id}.json").read_text(encoding="utf-8")
    )
    assert "provider_assertions" not in reloaded


def test_a_person_cannot_assert_a_status_only_bytes_can_prove(client, app_ctx):
    part_id = _add_part(app_ctx)
    response = client.post(
        f"/api/library/parts/{part_id}/providers",
        json={"provider": "snapmagic", "artifact": "model", "status": "validated"},
    )
    assert response.status_code == 422


def test_an_unknown_provider_is_refused_rather_than_stored(client, app_ctx):
    part_id = _add_part(app_ctx)
    response = client.post(
        f"/api/library/parts/{part_id}/providers",
        json={"provider": "not-a-provider", "artifact": "model", "status": "available"},
    )
    assert response.status_code == 422


def test_an_unknown_part_is_not_found(client, app_ctx):
    _add_part(app_ctx)
    assert client.get("/api/library/parts/nope/providers").status_code == 404
