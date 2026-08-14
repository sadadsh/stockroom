import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from stockroom.enrich.errors import EnrichError
from stockroom.enrich.mouser import (
    MouserAdapter,
    _default_requester,
    _parse_mouser_part,
    parse_mouser_payload,
)

FIX = Path(__file__).parent / "fixtures"


# A real-shaped Mouser part carrying the full field set the API returns (parametric attributes,
# category, compliance, trade origin, image, order quantities) that the parser used to drop.
_FULL_PART = {
    "ManufacturerPartNumber": "TPD6E05U06RVZR",
    "Manufacturer": "Texas Instruments",
    "Description": "ESD Protection Diodes / TVS Diodes 6-CH",
    "Category": "ESD Protection Diodes / TVS Diodes",
    "ImagePath": "https://www.mouser.com/images/ti/tpd6e05.jpg",
    "ROHSStatus": "RoHS Compliant",
    "Min": "1",
    "Mult": "1",
    "SalesMaximumOrderQty": "240",
    "AvailabilityInStock": "12317",
    "ProductDetailUrl": "https://www.mouser.com/x",
    "MouserPartNumber": "595-TPD6E05U06RVZR",
    "UnitWeightKg": {"UnitWeight": 4.2e-05},
    "ProductAttributes": [
        {"AttributeName": "Packaging", "AttributeValue": "Reel"},
        {"AttributeName": "Packaging", "AttributeValue": "Cut Tape"},
        {"AttributeName": "Standard Pack Qty", "AttributeValue": "3000"},
    ],
    "ProductCompliance": [
        {"ComplianceName": "USHTS", "ComplianceValue": "8541100080"},
        {"ComplianceName": "ECCN", "ComplianceValue": "EAR99"},
    ],
    "TradeCompliance": [
        {"ComplianceName": "Country of Origin", "ComplianceValue": "China"},
    ],
    "PriceBreaks": [{"Quantity": 1, "Price": "$0.50"}],
}


def test_parse_captures_parametrics_category_and_compliance():
    r = _parse_mouser_part(_FULL_PART)
    # packaging/parametric attributes flow into specs, grouped by name (distinct values joined)
    assert "Reel" in r.specs["Packaging"].value and "Cut Tape" in r.specs["Packaging"].value
    assert r.specs["Standard Pack Qty"].value == "3000"
    # the distributor category is kept as a spec (also drives the fill_category classifier)
    assert r.specs["Product Category"].value == "ESD Protection Diodes / TVS Diodes"
    assert r.specs["RoHS"].value == "RoHS Compliant"
    assert r.specs["ECCN"].value == "EAR99"
    assert r.specs["HTS Code (US)"].value == "8541100080"
    assert r.specs["Image"].value.startswith("http")
    # country of origin becomes the canonical field AND a spec
    assert r.country_of_origin.value == "China"
    # order quantities
    assert r.specs["Minimum Order Quantity"].value == "1"
    assert r.specs["Maximum Order Quantity"].value == "240"


def test_parse_keeps_every_exact_mouser_catalogue_ladder():
    second = {
        **_FULL_PART,
        "MouserPartNumber": "595-TPD6E05U06RVZR-CT",
        "AvailabilityInStock": "44",
        "PriceBreaks": [
            {"Quantity": 1, "Price": "$0.75", "Currency": "USD"},
            {"Quantity": 100, "Price": "$0.25", "Currency": "USD"},
        ],
    }
    result = parse_mouser_payload(
        {"SearchResults": {"Parts": [_FULL_PART, second]}},
        "TPD6E05U06RVZR",
    )

    offers = result.catalog["mouser"]["offers"]
    assert [offer["product_number"] for offer in offers] == [
        "595-TPD6E05U06RVZR",
        "595-TPD6E05U06RVZR-CT",
    ]
    assert offers[1]["price_breaks"] == [
        {"qty": 1, "price": 0.75, "currency": "USD"},
        {"qty": 100, "price": 0.25, "currency": "USD"},
    ]


def test_parse_never_raises_on_missing_rich_blocks():
    # a lean part (no attributes/compliance/category) must still parse cleanly, never raise
    r = _parse_mouser_part({"ManufacturerPartNumber": "X"})
    assert r.mpn.value == "X"
    assert r.country_of_origin is None and "Product Category" not in r.specs


def test_adapter_is_off_by_default_with_no_key():
    a = MouserAdapter()
    assert a.enabled is False
    r = a.lookup("TPS62130RGTR")
    assert r.filled_fields() == set()  # no network, empty result


def test_adapter_enabled_only_with_a_key():
    assert MouserAdapter(api_key="k").enabled is True


def test_lookup_prefers_the_exact_mpn_row_not_parts_zero():
    body = json.loads((FIX / "mouser_partnumber.json").read_text())

    def requester(mpn):
        return body  # the saved API response; no network

    a = MouserAdapter(api_key="k", requester=requester)
    r = a.lookup("TPS62130RGTR")
    # parts[0] is the "-NEAR" near-match; the exact MPN row must win
    assert r.mpn.value == "TPS62130RGTR"
    assert r.manufacturer.value == "Texas Instruments"
    assert r.mpn.confidence == "high"
    assert r.datasheet_url.value == "http://x/exact.pdf"
    assert r.stock.value == 4200
    assert [b.qty for b in r.price_breaks] == [1, 100]
    assert r.price_breaks[0].price == 1.23


def test_lookup_returns_empty_on_no_parts():
    a = MouserAdapter(api_key="k", requester=lambda mpn: {"SearchResults": {"Parts": []}})
    assert a.lookup("NOPE").filled_fields() == set()


def test_lookup_carries_the_procurement_fields(  # M7d: lifecycle / lead / product page / Mouser P/N
):
    body = json.loads((FIX / "mouser_partnumber.json").read_text())
    a = MouserAdapter(api_key="k", requester=lambda mpn: body)
    r = a.lookup("TPS62130RGTR")
    assert r.lifecycle.value == "Active"
    assert r.lead_time.value == "16 Weeks"
    assert r.product_url.value == "http://x/exact"
    assert r.dist_pns == {"mouser": "595-TPS62130RGTR"}


# --- Phase-1b-2b: last_status circuit-breaker signal ------------------------------


def test_last_status_is_rate_limited_on_a_429():
    def boom(mpn):
        raise EnrichError("throttled", status_code=429)

    a = MouserAdapter(api_key="k", requester=boom)
    r = a.lookup("X")
    assert a.last_status == "rate_limited"
    assert r.filled_fields() == set()  # a failed lookup still returns an empty result


def test_last_status_is_auth_error_on_a_401():
    def boom(mpn):
        raise EnrichError("unauthorized", status_code=401)

    a = MouserAdapter(api_key="k", requester=boom)
    r = a.lookup("X")
    assert a.last_status == "auth_error"
    assert r.filled_fields() == set()


def test_last_status_is_auth_error_on_a_403():
    def boom(mpn):
        raise EnrichError("forbidden", status_code=403)

    a = MouserAdapter(api_key="k", requester=boom)
    r = a.lookup("X")
    assert a.last_status == "auth_error"
    assert r.filled_fields() == set()


def test_last_status_is_error_on_a_generic_failure():
    def boom(mpn):
        raise EnrichError("transport blip")  # no status_code: not HTTP-coded

    a = MouserAdapter(api_key="k", requester=boom)
    r = a.lookup("X")
    assert a.last_status == "error"
    assert r.filled_fields() == set()


def test_last_status_is_ok_on_a_matching_part():
    body = json.loads((FIX / "mouser_partnumber.json").read_text())
    a = MouserAdapter(api_key="k", requester=lambda mpn: body)
    a.lookup("TPS62130RGTR")
    assert a.last_status == "ok"


def test_last_status_is_not_found_on_no_parts():
    a = MouserAdapter(api_key="k", requester=lambda mpn: {"SearchResults": {"Parts": []}})
    a.lookup("NOPE")
    assert a.last_status == "not_found"


def test_last_status_defaults_to_empty_before_any_lookup():
    assert MouserAdapter(api_key="k").last_status == ""


# ------------------------------------------------------------------------ fetch_payload
#
# Regression pin for cold-eyes finding 1 (2026-07-27). `fetch_payload` exists to store the RAW
# body for a re-derive, and its first version used HTTP-level truthiness ("ok" if body else
# "not_found") to decide whether a lookup succeeded - but a genuine "no such part" answer from
# Mouser is HTTP 200 with an EMPTY Parts list, which IS a truthy dict. So every not-found lookup
# was reported "ok", the importer wrote the empty-results response as evidence, indexed it, and
# counted the part `imported`. A fabricated MPN was indistinguishable from a real hit.

def test_fetch_payload_is_ok_on_a_real_hit():
    body = json.loads((FIX / "mouser_partnumber.json").read_text())
    a = MouserAdapter(api_key="k", requester=lambda mpn: body)
    got = a.fetch_payload("TPS62130RGTR")
    assert got is not None
    assert a.last_status == "ok"


def test_fetch_payload_is_NOT_FOUND_and_returns_NONE_on_empty_results():
    """THE bug. An empty Parts list is a genuine not-found, not a hit - and must return None so
    the importer never stores it as evidence."""
    a = MouserAdapter(api_key="k", requester=lambda mpn: {"SearchResults": {"Parts": []}})
    got = a.fetch_payload("ZZZNOTAREALPART123")
    assert got is None
    assert a.last_status == "not_found"


def test_a_fabricated_mpn_is_distinguishable_from_a_real_one():
    """The negative control, run directly against the two cases side by side: a fake MPN must
    produce a DIFFERENT observable outcome than a real one, or fetch_payload is not measuring
    anything."""
    real = MouserAdapter(api_key="k", requester=lambda mpn: json.loads(
        (FIX / "mouser_partnumber.json").read_text()
    ))
    fake = MouserAdapter(api_key="k", requester=lambda mpn: {"SearchResults": {"Parts": []}})
    real_body = real.fetch_payload("TPS62130RGTR-NEAR")
    fake_body = fake.fetch_payload("ZZZNOTAREALPART123")
    assert (real_body is not None) != (fake_body is not None)
    assert real.last_status != fake.last_status


def test_default_requester_raises_enricherror_with_status_code_on_http_error(monkeypatch):
    def _boom(req, timeout=8):
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", None, None)

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    with pytest.raises(EnrichError) as exc_info:
        _default_requester("key")("X")
    assert exc_info.value.status_code == 429


def test_default_requester_raises_plain_enricherror_on_transport_failure(monkeypatch):
    def _boom(req, timeout=8):
        raise OSError("network down")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    with pytest.raises(EnrichError) as exc_info:
        _default_requester("key")("X")
    assert exc_info.value.status_code is None


def test_lookup_by_mouser_stock_number_picks_that_row_at_full_confidence():
    """The endpoint is `search/partnumber` with `mouserPartNumber`, so a Mouser STOCK NUMBER
    is a first-class query - and the owner's Component Register names parts that way for 164
    of its 169 orderable line items. Matching only ManufacturerPartNumber made every such
    lookup a non-match: the adapter fell back to parts[0], which is a DIFFERENT part, and
    stamped it `low` instead of flagging it. Wrong part, quietly."""
    body = json.loads((FIX / "mouser_partnumber.json").read_text())
    a = MouserAdapter(api_key="k", requester=lambda mpn: body)
    r = a.lookup("595-TPS62130RGTR")
    assert r.mpn.value == "TPS62130RGTR"
    assert r.mpn.confidence == "high"
    assert r.dist_pns["mouser"] == "595-TPS62130RGTR"


def test_a_genuine_non_match_is_still_downgraded():
    """The guard above must not become a rubber stamp: a query matching NEITHER the
    manufacturer part nor the stock number still falls back and still says `low`."""
    body = json.loads((FIX / "mouser_partnumber.json").read_text())
    a = MouserAdapter(api_key="k", requester=lambda mpn: body)
    r = a.lookup("SOMETHING-ELSE")
    assert r.mpn.confidence == "low"


# --------------------------------------------------------------------- description hygiene
#
# Mouser's Search API appends its own alternate-packaging catalogue numbers to the
# `Description` field, behind a bare "A" marker, and mangles them with inserted spaces
# ("59 5-TPD1E10B06DPYT", "595- DRV2605LDGST"). MEASURED on the owner's real library,
# 2026-07-27: 13 of 158 parts derived a description ending in that noise, e.g.
#
#     Analog Comparators Window Comp for Over & Under Vltg Det A A 595-TPS3700DDCR
#
# Every string below is a VERBATIM `Description` value from a stored `sourced/<id>/mouser.json`
# payload in `libraries/Stockroom`, so these are not invented shapes.
_REAL_POLLUTED = [
    # (MouserPartNumber, raw Description, what a person should read)
    (
        "595-TPS3700DDCT",
        "Analog Comparators Window Comp for Over & Under Vltg Det A A 595-TPS3700DDCR",
        "Analog Comparators Window Comp for Over & Under Vltg Det",
    ),
    (
        "595-TPD1E10B06DPYR",
        "ESD Protection Diodes / TVS Diodes Sgl Channel ESD A 59 5-TPD1E10B06DPYT A A "
        "595-TPD1E10B06DPYT",
        "ESD Protection Diodes / TVS Diodes Sgl Channel ESD",
    ),
    (
        "595-SN74LVC1G04DBVR",
        "Inverters Single A 595-SN74LVC 1G04DBVT A 595-SN74 A 595-SN74LVC1G04DBVT",
        "Inverters Single",
    ),
    (
        "595-SN74LVC1G08DBVR",
        "Logic Gates Single 2 Input A 595 -SN74LVC1G08DBVT A A 595-SN74LVC1G08DBVT",
        "Logic Gates Single 2 Input",
    ),
    (
        "595-BQ24074RGTR",
        "Battery Management Li-Ion Batt Chrgr & Pwr-Path Mgmt IC A 5 A 595-BQ24074RGTT",
        "Battery Management Li-Ion Batt Chrgr & Pwr-Path Mgmt IC",
    ),
    (
        "595-DRV2605LDGSR",
        "Motor / Motion / Ignition Controllers & Drivers Haptic Driver A 595- DRV2605LDGST "
        "A 595- A 595-DRV2605LDGST",
        "Motor / Motion / Ignition Controllers & Drivers Haptic Driver",
    ),
    (
        "595-TS3A5018DR",
        "Analog Switch ICs 10-Ohm Quad SPDT Ana log Switch A 595-TS A 595-TS3A5018D",
        "Analog Switch ICs 10-Ohm Quad SPDT Ana log Switch",
    ),
    (
        "581-12063D226KAT2A",
        "Multilayer Ceramic Capacitors MLCC - SMD/SMT KGM31HR51E226KU NEW GLOBAL PN 25V "
        "22uF X A 581-KGM31HR51E226KU",
        "Multilayer Ceramic Capacitors MLCC - SMD/SMT KGM31HR51E226KU NEW GLOBAL PN 25V 22uF X",
    ),
]


@pytest.mark.parametrize("mouser_pn,raw,expected", _REAL_POLLUTED)
def test_the_catalogue_tail_is_cut_off_a_real_mouser_description(mouser_pn, raw, expected):
    part = {"ManufacturerPartNumber": "X", "Description": raw, "MouserPartNumber": mouser_pn}
    assert _parse_mouser_part(part).description.value == expected


# NEGATIVE CONTROLS. A stripper that cuts a description short is worse than the noise it
# removes, so each of these must survive UNTOUCHED. They are real descriptions from the same
# library except where noted.
_REAL_CLEAN = [
    ("595-BSS138", "MOSFETs SOT-23 N-CH LOGIC"),
    ("581-GRM155R71A474KE01D", "Multilayer Ceramic Capacitors MLCC - SMD/SMT 0.47 uF 10 VDC 10% 0402 X7R"),
    ("652-RC0402FR-0712K4L", "Thick Film Resistors - SMD General Purpose Chip Resistor 0402, 12.4kOhms, 1%, 1/16W"),
    ("200-TSW-120-07-G-D", "Headers & Wire Housings Classic PCB Header Strips"),
    # A description that legitimately ENDS in a bare "A" (an amp rating): the marker alone is
    # not a catalogue tail, because no Mouser part number follows it.
    ("595-TPS2121RUXR", "Power Switch ICs 4.5-A"),
    # A description whose last word merely STARTS with A. The marker is a standalone "A".
    ("595-INA226AIDGST", "Current & Power Monitors Bi-Dir Current/Pwr Mon Amplifier"),
    # No Mouser part number at all -> nothing is known to strip, so nothing is stripped.
    ("", "Analog Comparators Window Comp A A 595-TPS3700DDCR"),
]


@pytest.mark.parametrize("mouser_pn,desc", _REAL_CLEAN)
def test_a_clean_mouser_description_is_left_exactly_as_it_came(mouser_pn, desc):
    part = {"ManufacturerPartNumber": "X", "Description": desc, "MouserPartNumber": mouser_pn}
    assert _parse_mouser_part(part).description.value == desc


def test_an_html_entity_in_a_mouser_description_reads_as_the_character_it_encodes():
    # VERBATIM from libraries/Stockroom/sourced/tps2121ruxr-8f51/mouser.json.
    part = {
        "ManufacturerPartNumber": "TPS2121RUXR",
        "MouserPartNumber": "595-TPS2121RUXR",
        "Description": (
            "Power Switch ICs - Power Distribution 2.7-V&nbsp;to 22-V 5 6-m? 4.5-A power "
            "A A 595-TPS2121RUXT"
        ),
    }
    got = _parse_mouser_part(part).description.value
    assert "&nbsp;" not in got
    assert " " not in got  # the entity decodes to a NBSP; a NBSP is not a space to a reader
    assert got == "Power Switch ICs - Power Distribution 2.7-V to 22-V 5 6-m? 4.5-A power"
