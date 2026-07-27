"""A purchase row must name the DISTRIBUTOR, never the mechanism that found it.

MEASURED on the owner's real 158-part library, 2026-07-27: 85 records carried a `Purchase` whose
vendor was the literal string `"scrape"`, with an EMPTY part number, even when the url was an
LCSC product page with the C-number right there in it. The link, the price breaks and the live
stock were all correct and all filed under a name no user has ever heard of, so every surface
that groups or filters by vendor reported LCSC as zero. The owner's question was
*"why are all these missing their digikey and lcsc sourcing"*.

This is the "name things by what people recognise, never by how the system is built" rule,
violated in the DATA MODEL rather than in copy.
"""

from stockroom.enrich.distributor_url import (
    distributor_part_number_from_url,
    vendor_from_url,
)


class TestVendorFromUrl:
    def test_names_the_real_distributor_for_a_known_host(self):
        assert vendor_from_url("https://www.lcsc.com/product-detail/C3034813.html") == "LCSC"
        assert vendor_from_url("https://www.mouser.com/ProductDetail/TI/TPS62130RGTR") == "Mouser"
        assert vendor_from_url("https://www.digikey.com/en/products/detail/ti/X/123") == "DigiKey"

    def test_never_returns_the_mechanism_name(self):
        # The whole point. "scrape" is how the value was obtained, not who sells the part.
        for url in (
            "https://www.lcsc.com/product-detail/C3034813.html",
            "https://www.mouser.com/ProductDetail/TI/TPS62130RGTR",
        ):
            assert vendor_from_url(url) != "scrape"

    def test_an_unknown_shop_is_named_by_its_host_not_discarded(self):
        assert vendor_from_url("https://shop.example.com/p/1") == "shop.example.com"
        assert vendor_from_url("https://www.arrow.com/p/1") == "arrow.com"

    def test_a_non_url_is_a_manual_entry(self):
        assert vendor_from_url("") == "manual"
        assert vendor_from_url("typed by hand") == "manual"

    def test_the_api_router_helper_is_the_same_function_not_a_second_copy(self):
        """Two host maps drift. This one lived in the FastAPI router, where the Qt-free enrich
        pipeline could not reach it, which is exactly why the pipeline hardcoded a string
        instead."""
        from stockroom.api.routers.ingest import vendor_from_url as router_version

        assert router_version is vendor_from_url


class TestPartNumberFromUrl:
    def test_reads_the_lcsc_part_number_out_of_a_product_url(self):
        # Sitting in the url of 46 of the owner's records, never once stored.
        assert distributor_part_number_from_url(
            "https://www.lcsc.com/product-detail/C3034813.html"
        ) == "C3034813"

    def test_handles_an_lcsc_url_with_a_descriptive_slug(self):
        assert distributor_part_number_from_url(
            "https://www.lcsc.com/product-detail/Thermistors_Semitec-103AT-2_C3034813.html"
        ) == "C3034813"

    def test_a_search_url_carries_no_part_number(self):
        # 20 of the owner's records only ever resolved to a search page. Inventing a number
        # from one would be worse than leaving it empty.
        assert distributor_part_number_from_url(
            "https://www.lcsc.com/search?q=09454522912"
        ) == ""

    def test_reads_the_mouser_and_digikey_part_numbers_through_the_existing_parser(self):
        assert distributor_part_number_from_url(
            "https://www.mouser.com/ProductDetail/Texas-Instruments/TPS62130RGTR"
        ) == "TPS62130RGTR"
        assert distributor_part_number_from_url(
            "https://www.digikey.com/en/products/detail/ti/TPS62130RGTR/4window"
        ) == "TPS62130RGTR"

    def test_an_unrecognised_url_yields_nothing_rather_than_a_guess(self):
        assert distributor_part_number_from_url("https://shop.example.com/p/1") == ""
        assert distributor_part_number_from_url("") == ""


class TestPipelineFilesTheRealVendor:
    def test_a_scraped_lcsc_page_is_filed_as_lcsc_with_its_part_number(self):
        """The end-to-end assertion: the pipeline's own purchase-building step, given exactly
        the shape the owner's records were built from, now names LCSC and keeps C3034813."""
        from stockroom.enrich.pipeline import purchase_from_product_url

        purchase = purchase_from_product_url(
            "https://www.lcsc.com/product-detail/C3034813.html",
            price_breaks=[{"qty": 1, "price": 0.5}],
            stock=2151,
        )
        assert purchase.vendor == "LCSC"
        assert purchase.part_number == "C3034813"
        assert purchase.stock == 2151
        assert purchase.price_breaks == [{"qty": 1, "price": 0.5}]

    def test_a_search_page_still_files_the_vendor_and_leaves_the_number_empty(self):
        from stockroom.enrich.pipeline import purchase_from_product_url

        purchase = purchase_from_product_url(
            "https://www.lcsc.com/search?q=09454522912", price_breaks=[], stock=69
        )
        assert purchase.vendor == "LCSC"
        assert purchase.part_number == ""
