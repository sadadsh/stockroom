from __future__ import annotations

from stockroom.model.part import Datasheet, PartRecord, Purchase


def _land_bare_part(app_ctx) -> str:
    """Identity + sourcing only, no KiCad/Altium assets attached."""
    record = PartRecord(
        id="",
        display_name="TESTPART",
        category="ICs",
        description="a test part",
        mpn="BQ24074RGWR",
        manufacturer="Texas Instruments",
        datasheet=Datasheet(source_url="https://example.com/testpart.pdf"),
        purchase=[Purchase(vendor="Mouser", url="https://mouser.com/p/1")],
    )
    landed = app_ctx.ops.add_reference_part(record)
    app_ctx.rebuild_index()
    return landed.id


def test_cad_source_resolves_digikey_and_reports_needs(client, app_ctx):
    part_id = _land_bare_part(app_ctx)
    resp = client.get(f"/api/library/parts/{part_id}/cad-source")
    assert resp.status_code == 200
    body = resp.json()
    assert body["vendor"] == "DigiKey"
    assert "digikey.com" in body["url"]
    assert body["mpn"] == "BQ24074RGWR"
    needs = body["needs"]
    assert "kicad_symbol" in needs
    assert "kicad_footprint" in needs
    assert "altium_symbol" in needs
    assert "altium_footprint" in needs


def test_cad_source_unknown_part_is_404(client):
    assert client.get("/api/library/parts/does-not-exist/cad-source").status_code == 404
