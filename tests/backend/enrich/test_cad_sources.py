"""Where a part's CAD files can be fetched, across every vendor the owner trusts.

Owner, 2026-07-27: *"yes rebuild guided capture, digikey UL snapmagic and samacsys"*, after every
AUTOMATED route was closed off — Nexar is $1,000/month, Ultra Librarian's terms forbid robots,
SnapMagic blends AI-generated models, and Mouser's API carries no CAD at all. What remains is the
human clicking Download in a real browser session, with the app doing everything either side of
that click. So this module's whole job is: given a part, open exactly the right page, on each
vendor, first try.

It resolves URLs. It downloads nothing and automates no vendor site, which is what keeps the
guided flow inside every one of those vendors' terms.
"""

import pytest

from stockroom.enrich.cad_sources import (
    CadSource,
    all_cad_sources,
    resolve_cad_sources,
)


class FakeDigiKey:
    """The DigiKey adapter seam: `enabled` plus a `lookup` returning a product_url Sourced."""

    vendor = "DigiKey"

    def __init__(self, url="", enabled=True):
        self.enabled = enabled
        self._url = url
        self.calls = []

    def lookup(self, mpn):
        self.calls.append(mpn)

        class R:
            product_url = type("S", (), {"value": self._url})() if self._url else None

        return R()


# --- the vendor set ------------------------------------------------------------------------


def test_every_vendor_the_owner_named_is_present():
    keys = {s.key for s in all_cad_sources()}
    assert keys == {"digikey", "ultralibrarian", "snapmagic", "samacsys"}


def test_each_vendor_declares_which_tools_it_can_supply():
    # The owner needs BOTH KiCad and Altium. A vendor that cannot emit Altium must say so, or the
    # guided flow will send someone to a page that can never satisfy the requirement they are on.
    by_key = {s.key: s for s in all_cad_sources()}
    for key in ("ultralibrarian", "snapmagic", "samacsys"):
        assert "kicad" in by_key[key].tools
        assert "altium" in by_key[key].tools


def test_digikey_is_marked_as_an_aggregator_not_a_model_author():
    # DigiKey hosts whatever SnapEDA/UL/SamacSys built for that part; it authors nothing itself.
    # Worth carrying as data so the UI can order it honestly rather than implying a fourth library.
    by_key = {s.key: s for s in all_cad_sources()}
    assert by_key["digikey"].aggregator is True
    assert by_key["ultralibrarian"].aggregator is False


def test_vendor_order_is_stable_and_puts_the_trusted_authors_first():
    # Owner's trust ordering, 2026-07-27: UL is manufacturer-verified and built from source;
    # SnapMagic blends community + AI-generated content and comes last of the authors.
    keys = [s.key for s in all_cad_sources()]
    assert keys.index("ultralibrarian") < keys.index("snapmagic")


# --- resolving one part --------------------------------------------------------------------


def test_a_part_resolves_to_one_url_per_vendor():
    got = resolve_cad_sources("TPS62130RGTR", digikey=FakeDigiKey())
    assert {s.key for s in got} == {"digikey", "ultralibrarian", "snapmagic", "samacsys"}
    assert all(s.url for s in got)


def test_an_mpn_with_url_hostile_characters_cannot_break_out_of_the_query():
    # Real MPNs contain +, /, # and spaces. `MAX6817EUT+T` and `MCP4728-E/UN` are both in the
    # owner's library, and an unencoded + silently becomes a space on the vendor's side.
    got = {s.key: s.url for s in resolve_cad_sources("MAX6817EUT+T", digikey=FakeDigiKey())}
    for url in got.values():
        assert "+T" not in url.split("?", 1)[-1] or "%2B" in url
    assert all(" " not in u for u in got.values())


def test_a_blank_mpn_resolves_to_nothing_rather_than_a_vendor_home_page():
    # Sending someone to a search page for "" is worse than saying there is nowhere to go.
    assert resolve_cad_sources("", digikey=FakeDigiKey()) == []
    assert resolve_cad_sources("   ", digikey=FakeDigiKey()) == []


def test_digikey_prefers_the_exact_product_page_when_the_api_resolves_one():
    dk = FakeDigiKey(url="https://www.digikey.com/en/products/detail/ti/TPS62130RGTR/123")
    got = {s.key: s.url for s in resolve_cad_sources("TPS62130RGTR", digikey=dk)}
    assert got["digikey"].endswith("/123")
    assert dk.calls == ["TPS62130RGTR"]


def test_digikey_falls_back_to_search_when_there_are_no_credentials():
    got = {s.key: s.url for s in resolve_cad_sources("TPS62130RGTR", digikey=FakeDigiKey(enabled=False))}
    assert "digikey.com" in got["digikey"]
    assert "TPS62130RGTR" in got["digikey"]


def test_a_digikey_lookup_that_raises_still_yields_every_other_vendor():
    """One vendor's outage must not cost the user the other three. This is the guided flow's
    equivalent of 'one bad part never aborts the batch'."""

    class Exploding:
        enabled = True

        def lookup(self, mpn):
            raise RuntimeError("digikey api down")

    got = {s.key for s in resolve_cad_sources("TPS62130RGTR", digikey=Exploding())}
    assert got == {"digikey", "ultralibrarian", "snapmagic", "samacsys"}


def test_resolution_needs_no_adapter_at_all():
    # Three of the four vendors are pure URL construction, so a machine with zero credentials
    # still gets a working guided capture.
    got = resolve_cad_sources("TPS62130RGTR")
    assert len(got) == 4


@pytest.mark.parametrize(
    "key,host",
    [
        ("ultralibrarian", "ultralibrarian.com"),
        ("snapmagic", "snapeda.com"),
        ("samacsys", "componentsearchengine.com"),
        ("digikey", "digikey.com"),
    ],
)
def test_each_url_points_at_that_vendor(key, host):
    got = {s.key: s.url for s in resolve_cad_sources("TPS62130RGTR", digikey=FakeDigiKey())}
    assert host in got[key]


def test_the_part_number_actually_appears_in_every_url():
    # A vendor link that drops the MPN lands on a home page and the user has to search by hand,
    # which is exactly the manual work this flow exists to remove.
    got = resolve_cad_sources("TPS62130RGTR", digikey=FakeDigiKey())
    for source in got:
        assert "TPS62130RGTR" in source.url


def test_a_source_carries_what_the_user_must_do_there():
    # The guided window shows this, so it must be per-vendor rather than one generic instruction.
    for source in resolve_cad_sources("TPS62130RGTR"):
        assert source.instruction
        assert isinstance(source, CadSource)
