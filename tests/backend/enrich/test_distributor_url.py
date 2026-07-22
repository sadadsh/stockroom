from stockroom.enrich.distributor_url import distributor_mpn_from_url


def test_mouser_product_url_yields_vendor_and_mpn():
    # the owner's reported link: the MPN is the last path segment, the qs token is ignored
    v = distributor_mpn_from_url(
        "https://www.mouser.com/en/ProductDetail/Texas-Instruments/TPD6E05U06RVZR?qs=abc%3D%3D"
    )
    assert v == ("mouser", "TPD6E05U06RVZR")


def test_mouser_url_with_only_a_manufacturer_part_segment_still_yields_a_token():
    # the shorter /ProductDetail/<part> form (a Mouser part number) is still a searchable token
    v = distributor_mpn_from_url("https://www.mouser.com/ProductDetail/595-TPD6E05U06RVZR")
    assert v == ("mouser", "595-TPD6E05U06RVZR")


def test_mouser_url_without_a_part_segment_is_unrecognized():
    # the older query-only Mouser link carries no MPN in the path -> None (render fallback)
    assert distributor_mpn_from_url("https://www.mouser.com/ProductDetail/?qs=abc") is None


def test_digikey_product_url_yields_the_middle_path_mpn():
    # DigiKey path is /products/detail/<mfr-slug>/<MPN>/<digikey-pn>: the MPN is the middle segment
    v = distributor_mpn_from_url(
        "https://www.digikey.com/en/products/detail/texas-instruments/TPD6E05U06RVZR/2094564"
    )
    assert v == ("digikey", "TPD6E05U06RVZR")


def test_a_manufacturer_url_is_not_a_distributor_url():
    assert distributor_mpn_from_url("https://www.ti.com/product/TPD6E05U06RVZR") is None


def test_an_lcsc_url_is_left_for_the_render_path():
    # LCSC is not Akamai-blocked and has no official-API adapter here, so it is not claimed
    assert distributor_mpn_from_url("https://www.lcsc.com/product-detail/C2040.html") is None


def test_blank_and_garbage_urls_are_none():
    assert distributor_mpn_from_url("") is None
    assert distributor_mpn_from_url("not a url") is None
