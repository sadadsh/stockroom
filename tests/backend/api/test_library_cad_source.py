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


# ------------------------------------------------- every vendor, not just the one that aggregates
#
# Owner, 2026-07-27, on where CAD may come from: *"yes rebuild guided capture, digikey UL snapmagic
# and samacsys"*, with Ultra Librarian and SamacSys the ones they TRUST (manufacturer-verified) and
# SnapMagic disqualified as a PRIMARY source because it blends automatically generated models.
#
# `enrich/cad_sources.py` has held all four -- with each vendor's URL, the tools it can export for,
# whether it merely aggregates, and a per-vendor instruction -- since it was written, and NOTHING
# consumed it: this route resolved a single DigiKey link. A module that is written, tested and
# wired to nothing is a half-shipped feature, and the guided flow could only ever open one page.


def test_cad_source_offers_every_vendor_in_trust_order(client, app_ctx):
    part_id = _land_bare_part(app_ctx)
    body = client.get(f"/api/library/parts/{part_id}/cad-source").json()

    assert [s["key"] for s in body["sources"]] == [
        "digikey", "ultralibrarian", "samacsys", "snapmagic"
    ]


def test_cad_source_distinguishes_a_page_link_from_an_implemented_capture_adapter(
    client, app_ctx
):
    part_id = _land_bare_part(app_ctx)
    by_key = {
        source["key"]: source
        for source in client.get(f"/api/library/parts/{part_id}/cad-source").json()["sources"]
    }

    assert by_key["ultralibrarian"]["capture_available"] is True
    assert by_key["snapmagic"]["capture_available"] is True
    assert by_key["digikey"]["capture_available"] is False
    assert by_key["samacsys"]["capture_available"] is False


def test_each_vendor_carries_a_real_url_for_this_part(client, app_ctx):
    """A vendor entry with no URL is a dead end the UI would still render."""
    part_id = _land_bare_part(app_ctx)
    body = client.get(f"/api/library/parts/{part_id}/cad-source").json()

    for source in body["sources"]:
        assert source["url"].startswith("https://"), source
        # The MPN reaches the vendor, percent-encoded. `+`, `/` and `#` are all real characters in
        # real part numbers, and an unencoded one lands the user on a search for the WRONG part.
        assert "BQ24074RGWR" in source["url"].replace("%2B", "+"), source


def test_each_vendor_states_which_tools_it_can_export_for(client, app_ctx):
    """The owner needs BOTH KiCad and Altium. A vendor that cannot emit Altium must say so rather
    than send someone to a page that can never satisfy the requirement they are working on."""
    part_id = _land_bare_part(app_ctx)
    body = client.get(f"/api/library/parts/{part_id}/cad-source").json()

    for source in body["sources"]:
        assert set(source["tools"]) == {"kicad", "altium"}, source
        assert source["instruction"], source
        assert isinstance(source["aggregator"], bool)


def test_implemented_capture_providers_explain_the_automated_finish_contract(client, app_ctx):
    part_id = _land_bare_part(app_ctx)
    sources = client.get(f"/api/library/parts/{part_id}/cad-source").json()["sources"]
    implemented = [source for source in sources if source["capture_available"]]

    assert implemented
    for source in implemented:
        instruction = source["instruction"].lower()
        assert "automatic sources first" in instruction
        assert "opens the exact result" in instruction
        assert "chooses the required formats" in instruction
        assert "validates" in instruction
        assert "attaches" in instruction
        assert "security check" in instruction

    vendors = client.get("/api/library/capture/vendors").json()["vendors"]
    assert vendors
    implemented_by_key = {source["key"]: source for source in implemented}
    for vendor in vendors:
        assert vendor["instruction"] == implemented_by_key[vendor["key"]]["instruction"]
    ultra = next(vendor for vendor in vendors if vendor["key"] == "ultralibrarian")
    assert "altium designer (native)" in ultra["instruction"].lower()


def test_user_driven_capture_route_requires_one_part_and_one_provider(client, app_ctx):
    part_id = _land_bare_part(app_ctx)
    cases = (
        ({"mode": "assisted"}, "exactly one selected part"),
        ({"mode": "assisted", "part_ids": [part_id, "another-part"], "vendor": "snapmagic"},
         "exactly one selected part"),
        ({"mode": "assisted", "part_ids": [part_id]}, "one selected provider"),
        ({"mode": "assisted", "part_ids": [part_id], "vendor": "snapmagic", "limit": 1},
         "does not accept a batch limit"),
        ({"mode": "assisted", "part_ids": [part_id], "vendor": "not-a-provider"},
         "no network capture adapter"),
        ({"mode": "assisted", "part_ids": [part_id], "vendor": "snapmagic",
          "background": "yes"},
         "background must be a boolean"),
    )

    for payload, detail in cases:
        response = client.post("/api/library/capture/run", json=payload)
        assert response.status_code == 400, (payload, response.text)
        assert detail in response.json()["detail"]


def test_digikey_is_marked_an_AGGREGATOR_and_the_model_libraries_are_not(client, app_ctx):
    """DigiKey HOSTS models the other three authored; it is not a fourth library. Carried as data
    so a surface can order and label it honestly instead of implying one."""
    part_id = _land_bare_part(app_ctx)
    by_key = {s["key"]: s for s in client.get(
        f"/api/library/parts/{part_id}/cad-source"
    ).json()["sources"]}

    assert by_key["digikey"]["aggregator"] is True
    assert by_key["ultralibrarian"]["aggregator"] is False
    assert by_key["samacsys"]["aggregator"] is False
    assert by_key["snapmagic"]["aggregator"] is False


def test_a_part_with_no_mpn_offers_NOWHERE_rather_than_four_dead_searches(client, app_ctx):
    """Sending someone to a search for "" is worse than telling them there is nowhere to go.

    The record is written STRAIGHT TO DISK because the complete-to-add gate refuses a blank MPN --
    correctly, so this state cannot be reached through `add_reference_part`. It is still reachable
    on a real library: a record migrated from an older schema, or edited by hand, can carry one.
    Going around the gate here is the only way to exercise the guard rather than the gate.
    """
    record = PartRecord(
        id="nompn-0000", display_name="NOMPN", category="ICs", description="no mpn",
        mpn="", manufacturer="Acme",
    )
    (app_ctx.ops.lib.parts_dir / "nompn-0000.json").write_text(
        record.dumps(), encoding="utf-8"
    )
    app_ctx.rebuild_index()

    body = client.get("/api/library/parts/nompn-0000/cad-source").json()

    assert body["sources"] == []
    # And the flattened default is honestly empty rather than a link to nowhere.
    assert body["url"] is None
