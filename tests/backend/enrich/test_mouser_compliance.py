"""Country-of-origin + US-import-tariff + real-RoHS extraction from a Mouser product page.

The values are the page's OWN import fields (owner: never a researched or estimated rate):
  - the origin/compliance block is a <dt>label:</dt><dd>value</dd> definition list, the label
    carrying a nested tooltip <button> whose sr-only text must NOT leak into the label;
  - the tariff is the effective % Mouser bakes into its price ladder, DecTariffUnitPrice /
    DecUnitPrice, present in the embedded PriceBreaks JSON, null when the part is not tariffed;
  - the real "RoHS Status: RoHS Compliant" supersedes the useless "RoHS: Details" popup link.
The markup is sliced from the owner's real captured pages (2N7002 China, ERJ Japan)."""

from __future__ import annotations

from pathlib import Path

from stockroom.enrich.sites.mouser_web import (
    MouserWebSite,
    _extract_tariff_rate,
)

_URL = "https://www.mouser.com/en/ProductDetail/onsemi/2N7002"


def _result():
    html = (Path(__file__).parent / "fixtures" / "mouser_compliance.html").read_text(encoding="utf-8")
    return MouserWebSite().extract(html, _URL)


def test_country_of_origin_is_first_class_and_a_spec() -> None:
    r = _result()
    assert r.country_of_origin is not None
    assert r.country_of_origin.value == "China"
    assert r.country_of_origin.source == "mouser_web"
    # also kept as a scannable spec row
    assert r.specs["Country of Origin"].value == "China"


def test_the_tooltip_sentence_does_not_leak_into_the_label() -> None:
    # The <dt> holds "Country of Origin:" + a nested <button><span class="sr-only">The country
    # where a product was manufactured...</span></button>. The label must be "Country of Origin",
    # never the whole tooltip sentence, or the value lookup fails.
    r = _result()
    assert "Country of Origin" in r.specs
    assert not any("manufactured, produced" in k for k in r.specs)


def test_assembly_country_eccn_and_hts_are_specs() -> None:
    r = _result()
    assert r.specs["Assembly Country of Origin"].value == "Not available"
    assert r.specs["ECCN"].value == "EAR99"
    assert r.specs["HTS Code"].value == "8541290095"


def test_real_rohs_status_supersedes_the_details_popup() -> None:
    r = _result()
    # the compliance block's real status wins; a bare "Details" link value never survives
    assert r.specs["RoHS"].value == "RoHS Compliant"


def test_tariff_rate_from_the_price_ladder_json() -> None:
    r = _result()
    assert r.tariff_rate is not None
    # 0.087 / 1.09 * 100 = 7.98%, the effective US import tariff Mouser shows on a China part
    assert r.tariff_rate.value == 7.98
    assert r.tariff_rate.source == "mouser_web"


def test_lifecycle_none_in_the_datalayer_reads_as_active() -> None:
    # Mouser encodes a part with no special status as "lifecycle":"none" in its dataLayer;
    # that is a part in normal production -> Active (so the field fills honestly, not blank).
    r = _result()
    assert r.lifecycle is not None
    assert r.lifecycle.value == "Active"


def test_tariff_zero_when_ladder_present_but_every_break_untariffed() -> None:
    # A page whose ladder shows all-null tariffs (a non-China origin like Japan) is a CONFIRMED
    # zero tariff, not an unknown.
    html = ('<script>{"DecUnitPrice":0.230,"DecTariffUnitPrice":null},'
            '{"DecUnitPrice":0.083,"DecTariffUnitPrice":null}</script>')
    assert _extract_tariff_rate(html) == 0.0


def test_tariff_none_when_no_price_ladder_json() -> None:
    # No ladder at all -> unknown, never a fabricated 0.
    assert _extract_tariff_rate("<html><body>no pricing here</body></html>") is None
