"""Where a part's CAD files can be fetched, across every vendor the owner trusts.

Owner, 2026-07-27: *"yes rebuild guided capture, digikey UL snapmagic and samacsys"*, after every
AUTOMATED route was closed off — Nexar is $1,000/month, Ultra Librarian's terms forbid robots,
SnapMagic blends automatically generated models, and Mouser's API carries no CAD at all. What remains is the
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
    # SnapMagic blends community + automatically generated content and comes last of the authors.
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


def test_ultra_librarian_search_lives_on_the_app_subdomain_not_www():
    """MEASURED on the owner's machine 2026-07-27, driving the real page with `scripts/webread.py` (then named vendorprobe.py, since merged).

    `https://www.ultralibrarian.com/search?queryText=<MPN>` returns a 404 "PAGE NOT FOUND" - the
    site is now part of Cadence and the search app moved to the `app.` subdomain. Every guided
    capture that picked Ultra Librarian, the owner's FIRST-choice vendor, opened a dead page.

    The host is the fact under test, and the old test could not catch this: it asserted only that
    `"ultralibrarian.com" in url`, which is true of the 404 host too. An assertion that passes for
    the broken value is not a test.

    NEGATIVE CONTROL for the corrected URL, run the same session: the real MPN returns 4 result
    links with saysNoResults=false, an invented `ZZZNOTAREALPART123` returns 0 with
    saysNoResults=true. So a 200 here means a real hit, not "the host answers".
    """
    url = {s.key: s.url for s in resolve_cad_sources("TPD6E05U06RVZR")}["ultralibrarian"]
    assert url.startswith("https://app.ultralibrarian.com/search?queryText=")
    assert "//www.ultralibrarian.com" not in url


def test_samacsys_search_is_a_query_parameter_not_a_path_segment():
    """MEASURED on the owner's machine 2026-07-27, same session.

    `componentsearchengine.com/search/<MPN>` does NOT search. It is parsed as a part page for a
    part literally named "search", redirects to `/model-request/search/<MPN>`, and renders
    "ECAD model is currently unavailable for this part" - for EVERY part, including parts SamacSys
    actually has. Read off their own search form: `action="/search"`, `method="get"`, `name="term"`.

    Verified with the corrected URL: the same MPN returns "TPD6E05U06RVZR Model Download Search
    Results", "Showing 2 of 2 results", with a live Download Model button. So the old URL was
    reporting a part as unavailable while the vendor had it.
    """
    url = {s.key: s.url for s in resolve_cad_sources("TPD6E05U06RVZR")}["samacsys"]
    assert url.startswith("https://componentsearchengine.com/search?term=")
    assert "/search/TPD6E05U06RVZR" not in url


# --- the DigiKey models deep link ------------------------------------------------------------


def test_digikey_prefers_the_models_page_once_the_person_has_been_there():
    """The exact product page still costs a scroll to CAD Models and a tab click. The models
    page IS that surface, and its opaque id can only come from the person's own navigation."""

    dk = FakeDigiKey(url="https://www.digikey.com/en/products/detail/ti/TPS62130RGTR/123")
    got = {
        s.key: s.url
        for s in resolve_cad_sources("TPS62130RGTR", digikey=dk, digikey_models_id="6695662")
    }
    assert got["digikey"] == "https://www.digikey.com/en/models/6695662"
    # One vendor's deep link must not disturb the other three.
    assert "TPS62130RGTR" in got["ultralibrarian"]


def test_no_known_models_id_leaves_every_url_exactly_as_it_was():
    baseline = {s.key: s.url for s in resolve_cad_sources("TPS62130RGTR", digikey=FakeDigiKey())}
    assert {
        s.key: s.url
        for s in resolve_cad_sources("TPS62130RGTR", digikey=FakeDigiKey(), digikey_models_id="")
    } == baseline


def test_digikey_media_replaces_provider_searches_with_exact_model_links():
    catalog = {
        "media": [
            {
                "media_type": "EDA Models",
                "title": "Ultra Librarian CAD Models",
                "url": "https://app.ultralibrarian.com/details/acme/x",
            },
            {
                "media_type": "EDA Models",
                "title": "SnapEDA CAD Models",
                "url": "https://www.snapeda.com/parts/X/Acme/view-part/",
            },
        ]
    }
    got = {
        source.key: source.url
        for source in resolve_cad_sources("X", digikey=FakeDigiKey(), digikey_catalog=catalog)
    }
    assert got["ultralibrarian"] == "https://app.ultralibrarian.com/details/acme/x"
    assert got["snapmagic"] == "https://www.snapeda.com/parts/X/Acme/view-part/"
    assert "componentsearchengine.com/search" in got["samacsys"]


@pytest.mark.parametrize(
    "models_id",
    ["abc", "../evil", "6695662/../evil", "6695662?tab=evil", "0123", "6695662 ", None, 6695662],
)
def test_a_malformed_models_id_falls_back_instead_of_being_interpolated(models_id):
    baseline = {s.key: s.url for s in resolve_cad_sources("TPS62130RGTR", digikey=FakeDigiKey())}
    got = {
        s.key: s.url
        for s in resolve_cad_sources(
            "TPS62130RGTR",
            digikey=FakeDigiKey(),
            digikey_models_id=models_id,
        )
    }
    assert got == baseline
    assert "evil" not in got["digikey"]


def test_a_source_carries_what_the_user_must_do_there():
    # The guided window shows this, so it must be per-vendor rather than one generic instruction.
    for source in resolve_cad_sources("TPS62130RGTR"):
        assert source.instruction
        assert isinstance(source, CadSource)
