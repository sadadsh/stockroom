"""Fail-closed provider identity and URL resolution.

Everything a person does on the provider page - searching, signing in, clearing a challenge,
picking a format, downloading - is theirs. What Stockroom still owns, and what is asserted here,
is the identity it derives from a URL and the exact capture routes it offers.
"""

from __future__ import annotations

from stockroom.capture.vendors import (
    DigiKeyCadenasRouteAdapter,
    DigiKeyManufacturerProvidedRouteAdapter,
    DigiKeySnapMagicRouteAdapter,
    DigiKeyTracePartsRouteAdapter,
    DigiKeyUltraLibrarianAdapter,
    SamacSysAssistedAdapter,
    SnapMagicAdapter,
    UltraLibrarianAdapter,
    _href_demonstrates_mpn,
    _requested_mpn,
)


def test_requested_mpn_is_recovered_without_losing_identity_punctuation():
    assert (
        _requested_mpn(
            "https://app.ultralibrarian.com/search?queryText=MCP4728-E%2FUN",
            ("queryText",),
        )
        == "MCP4728-E/UN"
    )
    assert (
        _requested_mpn("https://www.snapeda.com/search/?q=MAX6817EUT%2BT", ("q",)) == "MAX6817EUT+T"
    )
    assert (
        _requested_mpn(
            "https://www.digikey.com/en/products/result?keywords=MAX6817EUT%2BT",
            ("keywords",),
        )
        == "MAX6817EUT+T"
    )


def test_digikey_enumerates_distinct_measured_author_routes() -> None:
    adapter = DigiKeyUltraLibrarianAdapter()
    routes = adapter.capture_routes()

    assert adapter.capability.key == "digikey"
    assert adapter.evidence_provider_key == "digikey-ultralibrarian"
    assert routes[0] is adapter
    assert isinstance(routes[1], DigiKeySnapMagicRouteAdapter)
    assert isinstance(routes[2], DigiKeyTracePartsRouteAdapter)
    assert isinstance(routes[3], DigiKeyManufacturerProvidedRouteAdapter)
    assert isinstance(routes[4], DigiKeyCadenasRouteAdapter)
    assert [route.evidence_provider_key for route in routes] == [
        "digikey-ultralibrarian",
        "digikey-snapmagic",
        "digikey-traceparts",
        "digikey-manufacturer",
        "digikey-cadenas",
    ]
    assert [route.capability.label for route in routes] == [
        "DigiKey CAD Models",
        "DigiKey · SnapMagic",
        "DigiKey · TraceParts",
        "DigiKey · Manufacturer Provided",
        "DigiKey · CADENAS",
    ]
    assert adapter.capability.supported_formats == {"kicad", "model", "altium"}
    assert routes[0].capability.supported_formats == {"kicad", "model", "altium"}
    assert routes[1].capability.supported_formats == {"kicad", "model", "altium"}
    assert routes[2].capability.supported_formats == {"model"}
    assert routes[3].capability.supported_formats == {"model"}
    assert routes[4].capability.supported_formats == {"model"}
    assert routes[2].supplementary_only is True
    assert routes[3].supplementary_only is True
    assert routes[4].supplementary_only is True
    assert adapter.resolve_url("MCP4728-E/UN").endswith("keywords=MCP4728-E%2FUN")


def test_samacsys_is_a_supported_route_with_an_implemented_validation_seam() -> None:
    adapter = SamacSysAssistedAdapter()

    assert adapter.capability.supported_formats == {"kicad", "model", "altium"}
    assert adapter.resolve_url("MAX6817EUT+T").endswith("term=MAX6817EUT%2BT")


def test_result_navigation_requires_a_whole_exact_mpn_component():
    assert _href_demonstrates_mpn("/parts/analog-devices/MAX6817EUT%2BT/view-part/", "MAX6817EUT+T")
    assert not _href_demonstrates_mpn("/parts/analog-devices/ABC-1/view-part/", "ABC")
    assert not _href_demonstrates_mpn("/details/id/vendor/MCP4728-E/UN", "MCP4728-E/UN")
    assert not _href_demonstrates_mpn(
        "/parts/WP10-S002VA10-R15000/JAE/view-part/?t=IC51-0484-806",
        "IC51-0484-806",
    )


def test_every_vendor_names_the_exact_export_the_person_must_take():
    """A wrong version pick fails much later, far from the cause, so the choice is named.

    Ultra Librarian lists KiCAD v5 one row above v6+, and SnapMagic's KiCad chooser offers
    "V3 & Prior" / "V4 & Later" / "V6 & Later". KiCad 5 emits `(module ...)` footprints that
    `Footprint.load` REFUSES.
    """

    ultra = UltraLibrarianAdapter.capability.user_format_labels
    assert ultra["kicad"] == "KiCad 6 or later"
    assert ultra["model"] == "STEP"

    snap = SnapMagicAdapter.capability.user_format_labels
    assert snap["kicad"] == "KiCad V6 & Later"
    assert snap["model"] == "STEP model"
    assert snap["altium"] == "Altium native"


def test_ultra_hints_the_current_live_model_control_and_its_measured_legacy_alias():
    hints = {hint.label: hint.selectors for hint in UltraLibrarianAdapter.capability.control_hints}

    assert hints["3D STEP model export"] == (
        'input[name="exports"][id="ThreeDModel"]',
        'input[name="exports"][id="MfrThreeDModel"]',
    )
