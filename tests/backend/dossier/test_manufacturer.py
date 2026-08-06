"""The manufacturer page, and the offer it must never be taken from."""

from __future__ import annotations

from stockroom.dossier import component_dossier
from stockroom.dossier.manufacturer import manufacturer_page
from stockroom.dossier.urls import matches_manufacturer
from stockroom.model.part import ManufacturerPage, Purchase
from tests.backend.dossier import records


def test_a_manufacturer_domain_is_recognised_from_the_manufacturers_own_name():
    assert matches_manufacturer("https://www.st.com/x", "STMicroelectronics")
    assert matches_manufacturer("https://www.ti.com/x", "Texas Instruments")
    assert matches_manufacturer("https://industrial.panasonic.com/x", "Panasonic")
    assert matches_manufacturer("https://www.we-online.com/x", "Wurth Elektronik") is False


def test_a_registered_distributor_host_is_never_a_manufacturer_host():
    assert matches_manufacturer("https://www.mouser.com/x", "Mouser") is False
    assert matches_manufacturer("https://www.digikey.com/x", "DigiKey") is False


def test_the_official_page_is_verified_when_the_host_is_the_manufacturers_own():
    record = records.microcontroller()
    record.manufacturer_page = ManufacturerPage(url="https://www.st.com/stm32h743", source="user")
    page = manufacturer_page(record)
    assert page["state"] == "verified"
    assert page["verified"] is True
    assert page["url"] == "https://www.st.com/stm32h743"


def test_source_metadata_can_verify_a_page_a_domain_cannot():
    record = records.microcontroller()
    record.catalog = {"manufacturer": {"manufacturer_page": "https://example-mcu.test/part"}}
    page = manufacturer_page(record)
    assert page["state"] == "verified"
    assert page["reason"] == "the source supplied it as the official page"


def test_a_page_nothing_proves_is_shown_but_never_called_official():
    record = records.microcontroller()
    record.catalog = {"lcsc": {"manufacturer_page": "https://unrelated.test/part"}}
    page = manufacturer_page(record)
    assert page["state"] == "unverified"
    assert page["verified"] is False
    assert page["url"] == "https://unrelated.test/part"


def test_the_manufacturer_page_is_never_taken_from_a_sourcing_offer():
    record = records.microcontroller()
    record.purchase = [
        Purchase(vendor="Mouser", url="https://www.mouser.com/ProductDetail/511-STM32H743"),
        Purchase(vendor="DigiKey", url="https://www.digikey.com/en/products/detail/497"),
    ]
    page = manufacturer_page(record)
    assert page["url"] == ""
    assert page["state"] == "absent"


def test_a_distributor_listing_offered_as_the_official_page_is_refused_with_a_reason():
    record = records.microcontroller()
    record.manufacturer_page = ManufacturerPage(
        url="https://www.mouser.com/ProductDetail/511-STM32H743", source="mouser"
    )
    page = manufacturer_page(record)
    assert page["state"] == "rejected"
    assert page["url"] == ""
    assert page["rejectedCandidates"][0]["reason"].startswith("Mouser hosts")


def test_a_distributors_product_url_is_not_treated_as_the_manufacturer_page():
    record = records.microcontroller()
    record.catalog = {"digikey": {"product_url": "https://www.digikey.com/en/products/detail/497"}}
    assert manufacturer_page(record)["state"] == "absent"


def test_no_page_at_all_is_a_complete_answer():
    page = manufacturer_page(records.resistor())
    assert page["state"] == "absent"
    assert page["rejectedCandidates"] == []


def test_the_dossier_carries_the_manufacturer_page_on_identity():
    record = records.microcontroller()
    record.manufacturer_page = ManufacturerPage(url="https://www.st.com/stm32h743")
    identity = component_dossier(record)["identity"]
    assert identity["manufacturerPage"]["verified"] is True


def test_a_distributor_offer_still_carries_its_own_provider_label():
    record = records.microcontroller()
    record.purchase = [Purchase(vendor="Mouser", url="https://www.mouser.com/x")]
    offer = component_dossier(record)["distributorOffers"][0]
    assert offer["providerLabel"] == "Mouser"
    assert offer["provider"] == "mouser"
