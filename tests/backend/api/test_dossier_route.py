"""The component dossier endpoint.

The opened component reads this route. It must be authenticated, must serve the normalized
projection rather than the canonical record, must answer identically under its historical
`/workspace` path, and must not have replaced the raw record endpoint that diagnostics and
compatibility still depend on.
"""

from __future__ import annotations

from stockroom.model.part import PartRecord
from stockroom.workspace import WORKSPACE_SCHEMA_VERSION


def _add_part(app_ctx) -> str:
    record = PartRecord(
        id="stm32h743vit6",
        mpn="STM32H743VIT6",
        manufacturer="STMicroelectronics",
        display_name="STM32H743VIT6",
        category="ICs",
        description="Arm Cortex-M7 microcontroller",
        specs={"package": "LQFP100", "pin_count": "100"},
    )
    path = app_ctx.profile.library.parts_dir / f"{record.id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.dumps(), encoding="utf-8")
    app_ctx.rebuild_index()
    return record.id


def test_workspace_requires_a_token(anon_client, app_ctx):
    part_id = _add_part(app_ctx)
    assert anon_client.get(f"/api/library/parts/{part_id}/workspace").status_code == 401


def test_dossier_requires_a_token(anon_client, app_ctx):
    part_id = _add_part(app_ctx)
    assert anon_client.get(f"/api/library/parts/{part_id}/dossier").status_code == 401


def test_the_dossier_serves_the_normalized_projection(client, app_ctx):
    part_id = _add_part(app_ctx)
    response = client.get(f"/api/library/parts/{part_id}/dossier")
    assert response.status_code == 200
    body = response.json()
    assert body["schemaVersion"] == WORKSPACE_SCHEMA_VERSION
    assert body["identity"]["mpn"] == "STM32H743VIT6"
    assert body["identity"]["package"] == "LQFP100"
    assert body["identity"]["categorySchema"]["key"] == "microcontroller"
    assert set(body["cadAssets"]["kinds"]) == {"symbol", "footprint", "model"}
    # The projection is the product shape, not the storage shape.
    assert "schema_version" not in body
    assert "assets" not in body


def test_the_historical_path_answers_with_the_same_document(client, app_ctx):
    part_id = _add_part(app_ctx)
    dossier = client.get(f"/api/library/parts/{part_id}/dossier").json()
    workspace = client.get(f"/api/library/parts/{part_id}/workspace").json()
    # `now` moves between the two calls, so freshness is compared as a field rather than as a
    # timestamp; everything else must be byte-identical or there are two projections again.
    for body in (dossier, workspace):
        body.pop("distributorOffers")
        body.pop("supplySummary")
    assert dossier == workspace


def test_the_route_supplies_the_clock_so_offer_freshness_is_answerable(client, app_ctx):
    part_id = _add_part(app_ctx)
    body = client.get(f"/api/library/parts/{part_id}/dossier").json()
    assert body["supplySummary"]["staleness"] in {"fresh", "aging", "stale", "unknown"}


def test_the_raw_record_endpoint_still_answers_for_diagnostics(client, app_ctx):
    part_id = _add_part(app_ctx)
    body = client.get(f"/api/library/parts/{part_id}").json()
    assert body["mpn"] == "STM32H743VIT6"
    assert "schema_version" in body


def test_an_unknown_part_is_not_found(client, app_ctx):
    _add_part(app_ctx)
    assert client.get("/api/library/parts/nope/workspace").status_code == 404
    assert client.get("/api/library/parts/nope/dossier").status_code == 404
