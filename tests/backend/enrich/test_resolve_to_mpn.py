"""RED first: a distributor stock number must resolve to the manufacturer part number
before enrichment, or every non-Mouser source is handed a token it cannot match."""
from stockroom.enrich.pipeline import EnrichmentPipeline
from stockroom.enrich.schema import EnrichmentResult, Sourced


class _Adapter:
    enabled = True

    def __init__(self, by_query):
        self._by = by_query
        self.queries = []

    def lookup(self, q):
        self.queries.append(q)
        return self._by.get(q, EnrichmentResult())


def _res(mpn, url=""):
    r = EnrichmentResult()
    r.mpn = Sourced(mpn, "mouser", "high")
    if url:
        r.product_url = Sourced(url, "mouser", "high")
    return r


def test_a_mouser_stock_number_resolves_to_the_manufacturer_part(tmp_path):
    mouser = _Adapter({"595-TPD6E05U06RVZR": _res("TPD6E05U06RVZR", "https://m/x")})
    p = EnrichmentPipeline(tmp_path, mouser=mouser)
    r = p.resolve_to_mpn("595-TPD6E05U06RVZR")
    assert r.mpn == "TPD6E05U06RVZR"
    assert r.vendor == "mouser"
    assert r.product_url == "https://m/x"


def test_a_digikey_part_number_resolves_through_the_digikey_adapter(tmp_path):
    dk = _Adapter({"296-11601-1-ND": _res("SN74LVC1G08DBVR")})
    p = EnrichmentPipeline(tmp_path, digikey=dk)
    r = p.resolve_to_mpn("296-11601-1-ND")
    assert r.mpn == "SN74LVC1G08DBVR"
    assert r.vendor == "digikey"


def test_a_plain_mpn_is_returned_untouched_and_costs_no_call(tmp_path):
    mouser = _Adapter({})
    p = EnrichmentPipeline(tmp_path, mouser=mouser)
    r = p.resolve_to_mpn("TPD6E05U06RVZR")
    assert r.mpn == "TPD6E05U06RVZR"
    assert r.vendor == ""
    assert mouser.queries == []


def test_an_unresolvable_stock_number_keeps_the_query_and_says_so(tmp_path):
    mouser = _Adapter({})
    p = EnrichmentPipeline(tmp_path, mouser=mouser)
    r = p.resolve_to_mpn("999-NOTHING")
    assert r.mpn == "999-NOTHING"
    assert r.vendor == ""
    assert r.resolved is False


def _cat_result(category):
    r = EnrichmentResult()
    r.category = category
    r.mpn = Sourced("TPD6E05U06RVZR", "mouser", "high")
    return r


class _CatPipeline(EnrichmentPipeline):
    """Stubs the registry walk so only the candidate hand-off is under test."""

    def enrich(self, mpn, category, want=None, progress=None):
        return _cat_result("Diodes")


def test_the_derived_category_reaches_the_candidate(tmp_path):
    """The enrich ROUTE returns `category` and the frontend applies it, so the Add form works -
    but the backend seam never copied it, so any headless caller (a bulk import) filed every
    part under "Other" no matter what the distributors said."""
    from stockroom.ingest.staging import StagingCandidate

    p = _CatPipeline(tmp_path)
    c = StagingCandidate(vendor="bulk", symbol_lib_path=None, symbol_name="",
                         footprint_variants=[], category="Other",
                         mpn="TPD6E05U06RVZR", display_name="x", entry_name="x")
    p.enrich_candidate(c)
    assert c.category == "Diodes"


def test_a_category_the_user_already_chose_is_never_overwritten(tmp_path):
    """"Other" is the form's default, i.e. "unfiled". A real filing is a decision and stands."""
    from stockroom.ingest.staging import StagingCandidate

    p = _CatPipeline(tmp_path)
    c = StagingCandidate(vendor="bulk", symbol_lib_path=None, symbol_name="",
                         footprint_variants=[], category="Connectors & Sockets",
                         mpn="TPD6E05U06RVZR", display_name="x", entry_name="x")
    p.enrich_candidate(c)
    assert c.category == "Connectors & Sockets"


def test_a_resolved_stock_number_is_cached_so_a_re_run_costs_nothing(tmp_path):
    """Mouser's Search API is capped at 1000 calls/DAY (practitioner-documented; the 30/minute
    figure is already hardcoded in the limiter). A register import spends up to two Mouser calls
    per part, so 166 parts is ~332 - and an uncached resolve makes every re-run, and every
    preview-then-import pair, pay that half again. Two full runs would be most of a day's budget.

    The enrich leg is already TTL-cached; this closes the other half.
    """
    mouser = _Adapter({"595-TPD6E05U06RVZR": _res("TPD6E05U06RVZR", "https://m/x")})
    p = EnrichmentPipeline(tmp_path, mouser=mouser)
    first = p.resolve_to_mpn("595-TPD6E05U06RVZR")
    second = p.resolve_to_mpn("595-TPD6E05U06RVZR")
    assert first.mpn == second.mpn == "TPD6E05U06RVZR"
    assert second.vendor == "mouser" and second.resolved is True
    assert second.product_url == "https://m/x"
    assert mouser.queries == ["595-TPD6E05U06RVZR"], "the second call must not hit the API"


def test_a_second_pipeline_reads_the_same_cache(tmp_path):
    """The preview and the import are separate pipeline objects built per request, so an
    in-memory memo would have cached nothing across them - the exact pair this is for."""
    mouser = _Adapter({"595-X": _res("REALPART")})
    EnrichmentPipeline(tmp_path, mouser=mouser).resolve_to_mpn("595-X")
    again = EnrichmentPipeline(tmp_path, mouser=mouser).resolve_to_mpn("595-X")
    assert again.mpn == "REALPART"
    assert mouser.queries == ["595-X"]


def test_a_failed_resolve_is_not_cached(tmp_path):
    """A miss is usually a transient network or rate-limit failure, and caching it would make one
    bad minute stick for the whole TTL. Only a real answer is worth remembering."""
    mouser = _Adapter({})
    p = EnrichmentPipeline(tmp_path, mouser=mouser)
    p.resolve_to_mpn("999-NOTHING")
    p.resolve_to_mpn("999-NOTHING")
    assert mouser.queries == ["999-NOTHING", "999-NOTHING"]
