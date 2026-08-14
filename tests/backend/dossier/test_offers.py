"""Normalized distributor offers: the frontend never parses a vendor payload."""

from __future__ import annotations

from stockroom.dossier import component_dossier
from stockroom.dossier.offers import (
    build_offers,
    manufacturer_status,
    staleness,
    supply_summary,
)
from stockroom.model.part import Purchase
from stockroom.model.sourced import SourceEntry
from tests.backend.dossier import records

_NOW = "2026-08-05T12:00:00+00:00"


def _sourced_record():
    record = records.microcontroller()
    record.purchase = [
        Purchase(
            vendor="Mouser",
            url="https://www.mouser.com/ProductDetail/511-STM32H743",
            part_number="511-STM32H743VIT6",
            stock=1240,
            currency="USD",
            price_breaks=[{"qty": 10, "price": 11.92}, {"qty": 1, "price": 12.48}],
            fetched_at="2026-08-05T09:00:00+00:00",
        ),
        Purchase(
            vendor="DigiKey",
            url="https://www.digikey.com/en/products/detail/497-STM32H743",
            part_number="497-STM32H743VIT6",
            stock=3105,
            currency="USD",
            price_breaks=[{"qty": 1, "price": 13.10}],
            fetched_at="2026-05-01T09:00:00+00:00",
        ),
    ]
    record.specs["Lead Time"] = "12 weeks"
    record.specs["Factory Lead Time"] = "20 weeks"
    record.specs["lifecycle"] = "normal"
    return record


def test_an_offer_carries_every_declared_field():
    offer = build_offers(_sourced_record(), now=_NOW)[0]
    assert set(offer) == {
        "provider",
        "providerLabel",
        "sku",
        "stock",
        "currency",
        "unitPrice",
        "priceBreaks",
        "moq",
        "leadTime",
        "factoryLeadTime",
        "lifecycle",
        "offerUrl",
        "lastCheckedAt",
        "staleness",
        "failureState",
    }


def test_normalized_offer_order_puts_mouser_before_digikey():
    assert [item["provider"] for item in build_offers(_sourced_record(), now=_NOW)] == [
        "mouser",
        "digikey",
    ]


def test_the_price_ladder_is_sorted_and_the_unit_price_is_its_first_break():
    offers = {item["provider"]: item for item in build_offers(_sourced_record(), now=_NOW)}
    assert offers["mouser"]["priceBreaks"] == [
        {"qty": 1, "price": 12.48},
        {"qty": 10, "price": 11.92},
    ]
    assert offers["mouser"]["unitPrice"] == 12.48
    assert offers["mouser"]["moq"] == 1


def test_digikey_catalog_projects_every_exact_package_ladder_without_duplicate_purchase():
    record = _sourced_record()
    record.catalog["digikey"] = {
        "product_url": "https://www.digikey.com/en/products/detail/497-STM32H743",
        "pricing_options": [
            {
                "product_number": "497-STM32H743CT-ND",
                "packaging": "Cut Tape",
                "quantity": 1,
                "unit_price": 13.10,
                "currency": "USD",
            },
            {
                "product_number": "497-STM32H743CT-ND",
                "packaging": "Cut Tape",
                "quantity": 10,
                "unit_price": 12.30,
                "currency": "USD",
            },
            {
                "product_number": "497-STM32H743TR-ND",
                "packaging": "Tape & Reel",
                "quantity": 1000,
                "unit_price": 8.40,
                "currency": "USD",
            },
        ],
    }
    record.sources["digikey"] = SourceEntry(
        fetched_at="2026-08-05T10:00:00+00:00", extra={"state": "success"}
    )

    digikey = [offer for offer in build_offers(record, now=_NOW) if offer["provider"] == "digikey"]
    assert [offer["sku"] for offer in digikey] == [
        "497-STM32H743CT-ND · Cut Tape",
        "497-STM32H743TR-ND · Tape & Reel",
    ]
    assert digikey[0]["priceBreaks"] == [
        {"qty": 1, "price": 13.10},
        {"qty": 10, "price": 12.30},
    ]
    assert digikey[1]["priceBreaks"] == [{"qty": 1000, "price": 8.40}]


def test_mouser_catalog_projects_every_exact_stock_number_without_duplicate_purchase():
    record = _sourced_record()
    record.catalog["mouser"] = {
        "offers": [
            {
                "product_number": "511-STM32H743VIT6",
                "stock": "1240",
                "product_url": "https://www.mouser.com/ProductDetail/511-STM32H743",
                "price_breaks": [
                    {"qty": 1, "price": 12.48, "currency": "USD"},
                    {"qty": 10, "price": 11.92, "currency": "USD"},
                ],
            },
            {
                "product_number": "511-STM32H743VIT6-CT",
                "stock": "120",
                "product_url": "https://www.mouser.com/ProductDetail/511-STM32H743-CT",
                "price_breaks": [{"qty": 1, "price": 13.25, "currency": "USD"}],
            },
        ]
    }
    record.sources["mouser"] = SourceEntry(
        fetched_at="2026-08-05T09:00:00+00:00", extra={"state": "success"}
    )

    mouser = [offer for offer in build_offers(record, now=_NOW) if offer["provider"] == "mouser"]

    assert [offer["sku"] for offer in mouser] == [
        "511-STM32H743VIT6",
        "511-STM32H743VIT6-CT",
    ]
    assert mouser[0]["priceBreaks"] == [
        {"qty": 1, "price": 12.48},
        {"qty": 10, "price": 11.92},
    ]


def test_the_provider_comes_from_the_offer_url_not_from_a_free_text_vendor():
    offers = {item["provider"]: item for item in build_offers(_sourced_record(), now=_NOW)}
    assert offers["digikey"]["providerLabel"] == "DigiKey"
    assert offers["digikey"]["sku"] == "497-STM32H743VIT6"


def test_lead_time_and_factory_lead_time_are_separate_fields():
    offer = build_offers(_sourced_record(), now=_NOW)[0]
    assert offer["leadTime"] == "12 weeks"
    assert offer["factoryLeadTime"] == "20 weeks"


def test_the_lifecycle_token_is_normalized_rather_than_shown_raw():
    assert build_offers(_sourced_record(), now=_NOW)[0]["lifecycle"] == "Active"


def test_freshness_is_a_field_and_an_old_reading_says_so():
    offers = {item["provider"]: item for item in build_offers(_sourced_record(), now=_NOW)}
    assert offers["mouser"]["staleness"] == "fresh"
    assert offers["digikey"]["staleness"] == "stale"


def test_with_no_clock_the_freshness_is_unknown_rather_than_guessed():
    assert build_offers(_sourced_record())[0]["staleness"] == "unknown"


def test_staleness_thresholds_are_measured_from_the_reading():
    assert staleness("2026-08-05T09:00:00+00:00", _NOW) == "fresh"
    assert staleness("2026-08-01T09:00:00+00:00", _NOW) == "aging"
    assert staleness("2026-01-01T09:00:00+00:00", _NOW) == "stale"
    assert staleness("", _NOW) == "unknown"


def test_a_failed_source_is_reported_without_freshening_its_old_offer():
    record = _sourced_record()
    record.sources = {
        "digikey": SourceEntry(
            fetched_at="2026-05-01T09:00:00+00:00",
            extra={"state": "failed", "last_attempted_at": _NOW},
        )
    }
    offers = {item["provider"]: item for item in build_offers(record, now=_NOW)}
    assert offers["digikey"]["failureState"] == "failed"
    assert offers["digikey"]["lastCheckedAt"] == "2026-05-01T09:00:00+00:00"
    assert offers["digikey"]["staleness"] == "stale"
    assert offers["mouser"]["failureState"] == ""


def test_the_supply_summary_names_the_cheapest_offer_and_its_provider():
    summary = supply_summary(build_offers(_sourced_record(), now=_NOW))
    assert summary["bestUnitPrice"] == 12.48
    assert summary["bestUnitPriceProvider"] == "mouser"
    assert summary["bestUnitPriceCurrency"] == "USD"
    assert summary["totalStock"] == 4345
    assert set(summary["providersInStock"]) == {"mouser", "digikey"}


def test_nobody_reporting_stock_is_not_the_same_as_nothing_in_stock():
    record = records.microcontroller()
    record.purchase = [Purchase(vendor="Mouser", url="https://www.mouser.com/x")]
    summary = supply_summary(build_offers(record, now=_NOW))
    assert summary["totalStock"] is None
    assert summary["providersInStock"] == []


def test_a_part_with_no_offers_reports_an_empty_supply_rather_than_absent():
    summary = component_dossier(records.resistor())["supplySummary"]
    assert summary["offerCount"] == 0
    assert summary["bestUnitPrice"] is None


def test_the_dossier_serves_the_offers_already_normalized():
    dossier = component_dossier(_sourced_record(), now=_NOW)
    assert [item["provider"] for item in dossier["distributorOffers"]] == ["mouser", "digikey"]
    assert dossier["supplySummary"]["staleness"] == "stale"


def test_the_manufacturers_own_status_is_kept_apart_from_the_lifecycle():
    """A manufacturer and a distributor are allowed to disagree about a part's life.

    `lifecycle` is the library's canonical state, normalized from whatever token a distributor
    used. `manufacturerStatus` is the manufacturer's own wording, untouched. Collapsing them
    would settle a disagreement the reader is the one qualified to settle.
    """
    record = _sourced_record()
    record.specs["Manufacturer Part Status"] = "Not Recommended For New Designs"
    summary = supply_summary(
        build_offers(record, now=_NOW), manufacturer_status=manufacturer_status(record)
    )
    assert summary["lifecycle"] == "Active"
    assert summary["manufacturerStatus"] == "Not Recommended For New Designs"


def test_a_manufacturer_status_nobody_stated_is_empty_rather_than_assumed_active():
    assert manufacturer_status(records.resistor()) == ""
    assert component_dossier(records.resistor())["supplySummary"]["manufacturerStatus"] == ""


def test_a_manufacturer_status_is_read_from_any_of_the_names_sources_give_it():
    record = records.resistor()
    record.specs["Product Status"] = "Obsolete"
    assert manufacturer_status(record) == "Obsolete"


def test_a_failure_names_the_distributor_rather_than_keying_it():
    """"digikey could not be read (not_configured)" is two storage identifiers, not a sentence."""
    record = _sourced_record()
    record.sources = {"mouser": SourceEntry(extra={"state": "not_configured"})}
    failure = supply_summary(build_offers(record, now=_NOW))["failures"][0]
    assert failure == {"provider": "mouser", "providerLabel": "Mouser", "state": "not_configured"}
