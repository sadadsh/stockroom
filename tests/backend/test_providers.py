"""The provider registry is the one authority for provider identity.

These tests pin the registry's shape: stable keys and order, honest expectations, measured
search URLs only, and recognition parity for distributor catalogue media entries.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from stockroom.providers import (
    PROVIDERS,
    all_providers,
    provider,
    provider_for_host,
    provider_for_media,
    provider_label,
    search_url,
)


def test_every_provider_has_a_unique_stable_key_and_label():
    keys = [record.key for record in PROVIDERS]
    assert len(keys) == len(set(keys))
    assert all(key == key.strip().lower() for key in keys)
    assert all(record.label.strip() for record in PROVIDERS)


def test_the_registry_covers_every_provider_the_workflow_names():
    # `lcsc` joined 2026-08-05. It was already a live enrich source (`enrich/registry.py`,
    # `enrich/pipeline.py::LcscSource`, `scrape/extract/sites/lcsc.py`) while the registry did
    # not know it, so `dossier/precedence.py::source_tier("lcsc")` fell through to `parsed` -
    # the WEAKEST tier - and LCSC data lost to every CAD provider and read as `Parsed Or
    # Inferred` instead of as the distributor answer it is.
    assert {record.key for record in PROVIDERS} == {
        "mouser",
        "digikey",
        "lcsc",
        "ultralibrarian",
        "samacsys",
        "snapmagic",
        "manufacturer",
        "traceparts",
        "cadenas",
    }


def test_registry_order_is_stable_and_distributors_lead():
    keys = [record.key for record in PROVIDERS]
    # Mouser first, DigiKey second, LCSC third: the owner's distributor trust order, stated
    # 2026-08-05 (it used to read digikey, mouser). This order is not decoration - the three
    # distributors share one precedence tier and `dossier/precedence.py` breaks a tie inside a
    # tier by registry position, so this list IS which distributor's answer a reader sees.
    assert keys[:3] == ["mouser", "digikey", "lcsc"]
    # The owner's model-author trust ranking is a separate decision and survives untouched.
    authors = [k for k in keys if k in {"ultralibrarian", "samacsys", "snapmagic"}]
    assert authors == ["ultralibrarian", "samacsys", "snapmagic"]
    assert [provider(k).order for k in keys] == sorted(provider(k).order for k in keys)


def test_every_distributor_is_declared_before_every_model_author():
    keys = [record.key for record in PROVIDERS]
    distributors = [i for i, record in enumerate(PROVIDERS) if record.distributor]
    others = [i for i, record in enumerate(PROVIDERS) if not record.distributor]
    assert distributors and others
    assert max(distributors) < min(others), keys


def test_unknown_provider_key_is_loud():
    try:
        provider("eagle")
    except KeyError as exc:
        assert "eagle" in str(exc)
    else:
        raise AssertionError("an unknown provider key must raise")


def test_search_urls_are_https_and_percent_encode_hostile_mpns():
    for record in PROVIDERS:
        url = search_url(record.key, "MAX6817EUT+T")
        if not record.search_template:
            assert url == ""
            continue
        parts = urlsplit(url)
        assert parts.scheme == "https"
        assert "MAX6817EUT+T" not in url
        assert "MAX6817EUT%2BT" in url


def test_providers_without_a_measured_search_surface_stay_honestly_blank():
    # LCSC joins the blank list rather than gaining an invented template: measured 2026-08-05,
    # https://www.lcsc.com/search?<param>=S1M returns the same JavaScript shell titled
    # `Search by ""` for every candidate parameter, so no parameter can be shown to search.
    for key in ("lcsc", "manufacturer", "traceparts", "cadenas"):
        assert search_url(key, "S1M") == ""


def test_expectations_are_consistent_with_tool_support():
    for record in PROVIDERS:
        if record.kicad or record.altium:
            assert record.symbols and record.footprints, record.key


def test_a_provider_offers_cad_or_earns_its_row_as_a_distributor():
    # Every provider used to have to offer at least one artifact, because every provider was a
    # CAD surface. LCSC is the first that is not: it is registered for its catalogue, and its
    # EasyEDA-derived geometry is explicitly refused elsewhere (`api/routers/ingest.py`,
    # `capture/runner.py`), so claiming an artifact would open a coverage column no honest
    # capture could fill. A provider that offers no CAD must therefore be a distributor - a row
    # that neither supplies CAD nor sells the part still has no reason to exist.
    for record in PROVIDERS:
        offers_cad = record.symbols or record.footprints or record.models
        if not (offers_cad or record.distributor):
            raise AssertionError(f"{record.key} offers nothing and sells nothing")
    lcsc = provider("lcsc")
    assert not (lcsc.symbols or lcsc.footprints or lcsc.models or lcsc.kicad or lcsc.altium)
    assert lcsc.distributor is True
    assert lcsc.aggregator is False


def test_host_recognition_matches_subdomains_and_rejects_lookalikes():
    assert provider_for_host("app.ultralibrarian.com").key == "ultralibrarian"
    assert provider_for_host("www.digikey.com").key == "digikey"
    assert provider_for_host("componentsearchengine.com").key == "samacsys"
    assert provider_for_host("b2b.partcommunity.com").key == "cadenas"
    assert provider_for_host("www.lcsc.com").key == "lcsc"
    assert provider_for_host("lcsc.com").key == "lcsc"
    # EasyEDA is a separate surface whose geometry this product refuses; LCSC does not claim it.
    assert provider_for_host("easyeda.com") is None
    assert provider_for_host("notdigikey.com.evil.example") is None
    assert provider_for_host("fakedigikey.com") is None
    assert provider_for_host("") is None


def test_media_recognition_covers_every_catalogue_author():
    cases = {
        ("Ultra Librarian model", "https://x/ul"): "ultralibrarian",
        ("Download from SnapEDA", "https://x/se"): "snapmagic",
        ("SamacSys model", "https://componentsearchengine.com/p"): "samacsys",
        ("TraceParts 3D", "https://x/tp"): "traceparts",
        ("CADENAS model", "https://x/cd"): "cadenas",
        ("Manufacturer Provided STEP", "https://x/mf"): "manufacturer",
    }
    for (title, url), expected in cases.items():
        record = provider_for_media(title, url)
        assert record is not None and record.key == expected, (title, expected)
    assert provider_for_media("Datasheet", "https://x/ds") is None


def test_labels_degrade_honestly_for_unregistered_surfaces():
    assert provider_label("ultralibrarian") == "Ultra Librarian"
    assert provider_label("digikey-ultralibrarian") == "digikey-ultralibrarian"


def test_enabled_filter_is_a_subset_in_registry_order():
    enabled = all_providers(enabled_only=True)
    assert set(enabled) <= set(PROVIDERS)
    assert [record.key for record in enabled] == [
        record.key for record in PROVIDERS if record.enabled
    ]
