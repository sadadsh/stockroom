import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from stockroom.enrich.errors import EnrichError
from stockroom.enrich.mouser import MouserAdapter, _default_requester

FIX = Path(__file__).parent / "fixtures"


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
