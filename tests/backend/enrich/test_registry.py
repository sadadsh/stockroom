import pytest

from stockroom.enrich.errors import EnrichError
from stockroom.enrich.registry import SourceRegistry
from stockroom.enrich.schema import EnrichmentResult, Sourced


class _FakeSource:
    def __init__(self, name, fields, raises=False):
        self.name = name
        self._fields = fields  # {field: value}
        self._raises = raises
        self.was_called_with = None

    def enrich(self, mpn, category, remaining):
        self.was_called_with = set(remaining)
        if self._raises:
            raise EnrichError(f"{self.name} down")
        r = EnrichmentResult(category=category)
        for f, v in self._fields.items():
            setattr(r, f, Sourced(v, self.name, "high"))
        return r


def test_first_source_wins_and_second_fills_only_the_rest():
    s1 = _FakeSource("lcsc", {"mpn": "M1", "manufacturer": "MAN1"})
    s2 = _FakeSource("scrape", {"manufacturer": "MAN2", "description": "D2"})
    reg = SourceRegistry([s1, s2])
    r = reg.enrich("M1", "ICs")
    assert r.mpn.value == "M1" and r.mpn.source == "lcsc"
    # manufacturer already filled by lcsc; scrape must not overwrite it
    assert r.manufacturer.value == "MAN1"
    # description was still missing after lcsc, so scrape filled it
    assert r.description.value == "D2"
    # scrape was only asked for what lcsc left missing
    assert "manufacturer" not in s2.was_called_with


def test_a_source_that_raises_is_skipped_and_the_walk_continues():
    dead = _FakeSource("scrape", {}, raises=True)
    alive = _FakeSource("mouser", {"mpn": "M1"})
    reg = SourceRegistry([dead, alive])
    r = reg.enrich("M1", "ICs")
    assert r.mpn.value == "M1" and r.mpn.source == "mouser"  # dead source never blocked


def test_walk_stops_early_once_nothing_remains():
    s1 = _FakeSource("lcsc", {"mpn": "M1", "manufacturer": "M", "description": "d",
                              "datasheet_url": "u", "stock": 1, "package": "QFN"})
    s2 = _FakeSource("scrape", {"mpn": "SHOULD-NOT-RUN"})
    reg = SourceRegistry([s1, s2])
    reg.enrich("M1", "ICs", want={"mpn", "manufacturer", "description",
                                  "datasheet_url", "stock", "package"})
    assert s2.was_called_with is None  # s1 satisfied everything; s2 never called


# -- Per-vendor sourcing (Batch 3, punch 4). Two defects lived here. The walk kept only the
# FIRST source's price ladder, so a second distributor's prices were fetched and thrown away
# (its Sourcing row then rendered with no price and no stock). And the remaining-set
# fall-through stopped the walk as soon as the canonical fields were full, so once LCSC or a
# scrape answered, the DigiKey / Mouser legs were never called AT ALL.


class _VendorSource(_FakeSource):
    """A distributor source: it declares a `vendor_key`, which is what makes its price ladder,
    live stock and product page per-vendor DATA rather than a nameless contribution."""

    def __init__(self, name, fields=None, breaks=None, stock=None, url="", raises=False):
        super().__init__(name, fields or {}, raises=raises)
        self.vendor_key = name
        self._breaks = breaks or []
        self._stock = stock
        self._url = url

    def enrich(self, mpn, category, remaining):
        r = super().enrich(mpn, category, remaining)
        if self._breaks:
            r.price_breaks = list(self._breaks)
        if self._stock is not None:
            r.stock = Sourced(self._stock, self.name, "high")
        if self._url:
            r.product_url = Sourced(self._url, self.name, "high")
        return r


def test_each_distributor_keeps_its_own_ladder_stock_and_link():
    from stockroom.enrich.schema import PriceBreak

    mouser = _VendorSource("mouser", breaks=[PriceBreak(qty=1, price=1.50)], stock=1200,
                           url="https://mouser.com/p")
    digikey = _VendorSource("digikey", breaks=[PriceBreak(qty=1, price=1.42)], stock=48,
                            url="https://digikey.com/p")
    r = SourceRegistry([mouser, digikey]).enrich("M1", "ICs")
    assert r.dist_price_breaks["mouser"][0].price == 1.50
    assert r.dist_price_breaks["digikey"][0].price == 1.42
    assert r.dist_stock == {"mouser": 1200, "digikey": 48}
    assert r.dist_urls == {"mouser": "https://mouser.com/p", "digikey": "https://digikey.com/p"}
    # the merged primary still follows first-source-wins, unchanged
    assert r.stock.value == 1200


def test_a_source_that_is_not_a_distributor_never_fakes_a_vendor_row():
    """`scrape` and `datasheet` carry a product URL and sometimes a price, but they are not
    places to buy from. Keying per-vendor data off the source NAME would have put a "Scrape"
    row in the Sourcing list; it is keyed off a declared `vendor_key` instead."""
    scrape = _FakeSource("scrape", {"product_url": "https://example.com/p", "stock": 5})
    r = SourceRegistry([scrape]).enrich("M1", "ICs")
    assert r.dist_urls == {} and r.dist_stock == {} and r.dist_price_breaks == {}


class _FillsEverythingSource(_FakeSource):
    """A source that satisfies EVERY field in DEFAULT_WANT on its own - which is the ordinary
    case for LCSC on a catalogued part, and is what emptied the remaining-set and ended the
    walk before the distributor legs were ever reached."""

    def enrich(self, mpn, category, remaining):
        from stockroom.enrich.schema import PriceBreak

        r = super().enrich(mpn, category, remaining)
        r.price_breaks = [PriceBreak(qty=1, price=9.99)]
        r.specs["Package Type"] = Sourced("Reel", self.name, "high")
        return r


def test_a_distributor_is_still_consulted_after_every_wanted_field_is_full():
    from stockroom.enrich.registry import DEFAULT_WANT
    from stockroom.enrich.schema import PriceBreak

    everything = _FillsEverythingSource(
        "lcsc", {"mpn": "M1", "manufacturer": "M", "description": "d", "datasheet_url": "u",
                 "stock": 1, "package": "QFN"})
    digikey = _VendorSource("digikey", breaks=[PriceBreak(qty=1, price=1.42)], stock=48)
    reg = SourceRegistry([everything, digikey])
    # sanity: the first source really does satisfy every OTHER want, so this test is
    # reproducing the skip rather than passing because something was left unfilled
    r = reg.enrich("M1", "ICs")
    assert (DEFAULT_WANT - {"dist_sourcing"}) <= r.filled_fields()
    assert digikey.was_called_with is not None, "the DigiKey leg was skipped entirely"
    assert r.dist_price_breaks["digikey"][0].price == 1.42


def test_a_caller_can_still_opt_out_of_the_extra_distributor_round_trip():
    """The token is what keeps the walk open, so a caller that does not ask for per-vendor
    sourcing keeps the cheap early stop (a bulk price refresh does not need a second API leg
    per part)."""
    everything = _FillsEverythingSource(
        "lcsc", {"mpn": "M1", "manufacturer": "M", "description": "d", "datasheet_url": "u",
                 "stock": 1, "package": "QFN"})
    digikey = _VendorSource("digikey", stock=48)
    SourceRegistry([everything, digikey]).enrich(
        "M1", "ICs", want={"mpn", "manufacturer", "description", "datasheet_url", "stock",
                           "package", "price_breaks", "specs"})
    assert digikey.was_called_with is None


def test_a_dead_distributor_does_not_hold_the_walk_open():
    """Asking counts, even when the answer is a failure: a distributor that raises HAS been
    consulted. Otherwise its token would never clear and every later source would be walked
    forever after, waiting on an answer that is not coming - observable here as `never`
    being called even though everything was already satisfied before it."""
    dead = _VendorSource("digikey", raises=True)
    everything = _FillsEverythingSource(
        "lcsc", {"mpn": "M1", "manufacturer": "M", "description": "d", "datasheet_url": "u",
                 "stock": 1, "package": "QFN"})
    never = _FakeSource("scrape", {"mpn": "SHOULD-NOT-RUN"})
    r = SourceRegistry([dead, everything, never]).enrich("M1", "ICs")
    assert r.mpn.value == "M1" and r.mpn.source == "lcsc"  # the dead source never blocked
    assert never.was_called_with is None
    assert r.dist_price_breaks == {}  # a failed lookup contributes no prices


def test_a_display_cased_vendor_key_still_lands_in_the_lowercase_map():
    """Every other writer and reader of these maps uses the lowercase form, including the
    frontend's `dist_price_breaks[key]` lookup. A "Mouser" key would sit beside "mouser"
    instead of in it, and the row would show no prices - the very symptom being fixed."""
    from stockroom.enrich.schema import PriceBreak

    shouty = _VendorSource("Mouser", breaks=[PriceBreak(qty=1, price=2.0)], stock=7)
    shouty.vendor_key = "Mouser"
    r = SourceRegistry([shouty]).enrich("M1", "ICs")
    assert list(r.dist_price_breaks) == ["mouser"]
    assert r.dist_stock == {"mouser": 7}
