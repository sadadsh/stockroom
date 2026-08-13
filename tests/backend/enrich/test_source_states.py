"""Per-source verdicts for the official distributor APIs.

The explicit-MPN workflow must attempt every enabled official API and report what happened
to each one - success, unavailable, failed, or not_configured - instead of letting a dead
or missing distributor look identical to a part it does not carry.
"""

from __future__ import annotations

from stockroom.api.routers.enrich import _explicit_want, _result_dto
from stockroom.enrich.errors import EnrichError
from stockroom.enrich.pipeline import (
    EnrichmentPipeline,
    _DigiKeySource,
    _MouserSource,
    _result_from_cache,
    _result_to_cache,
)
from stockroom.enrich.registry import DIST_SOURCING, SourceRegistry
from stockroom.enrich.schema import EnrichmentResult, Sourced


class _FakeAdapter:
    """The official-adapter contract: lookup() never raises, classifies into last_status."""

    def __init__(self, result: EnrichmentResult | None = None, status: str = "ok"):
        self._result = result
        self._status = status
        self.enabled = True
        self.last_status = ""
        self.calls = 0

    def lookup(self, mpn: str) -> EnrichmentResult:
        self.calls += 1
        self.last_status = self._status
        return self._result if self._result is not None else EnrichmentResult()


def _answer(mpn: str, vendor: str) -> EnrichmentResult:
    result = EnrichmentResult()
    result.mpn = Sourced(mpn, vendor, "high")
    result.manufacturer = Sourced("ACME", vendor, "high")
    result.description = Sourced(f"{vendor} description", vendor, "high")
    result.dist_urls[vendor] = f"https://example.com/{vendor}"
    return result


def _walk(mouser: _FakeAdapter, digikey: _FakeAdapter, mpn: str = "S1M") -> EnrichmentResult:
    registry = SourceRegistry([_MouserSource(mouser), _DigiKeySource(digikey)])
    return registry.enrich(mpn, "Other", want={"description", DIST_SOURCING})


def test_both_officials_succeed_and_both_report_success():
    mouser = _FakeAdapter(_answer("S1M", "mouser"))
    digikey = _FakeAdapter(_answer("S1M", "digikey"))
    result = _walk(mouser, digikey)
    assert result.source_states == {"mouser": "success", "digikey": "success"}
    assert mouser.calls == 1 and digikey.calls == 1


def test_a_failed_mouser_degrades_visibly_while_digikey_data_survives():
    mouser = _FakeAdapter(EnrichmentResult(), status="error")
    digikey = _FakeAdapter(_answer("S1M", "digikey"))
    result = _walk(mouser, digikey)
    assert result.source_states == {"mouser": "failed", "digikey": "success"}
    assert result.description is not None and result.description.source == "digikey"


def test_a_rate_limited_digikey_is_failed_not_silently_absent():
    mouser = _FakeAdapter(_answer("S1M", "mouser"))
    digikey = _FakeAdapter(EnrichmentResult(), status="rate_limited")
    result = _walk(mouser, digikey)
    assert result.source_states == {"mouser": "success", "digikey": "failed"}


def test_a_clean_miss_is_unavailable_not_failed():
    mouser = _FakeAdapter(EnrichmentResult(), status="not_found")
    digikey = _FakeAdapter(_answer("S1M", "digikey"))
    result = _walk(mouser, digikey)
    assert result.source_states["mouser"] == "unavailable"


def test_a_foreign_mpn_answer_is_unavailable_and_never_contaminates():
    mouser = _FakeAdapter(_answer("OTHER-PART", "mouser"))
    digikey = _FakeAdapter(_answer("S1M", "digikey"))
    result = _walk(mouser, digikey)
    assert result.source_states["mouser"] == "unavailable"
    assert "mouser" not in result.dist_urls


def test_a_source_that_raises_is_failed_and_never_blocks_the_walk():
    class _Raising:
        name = "mouser"
        vendor_key = "mouser"

        def enrich(self, mpn, category, remaining):
            raise EnrichError("boom")

    digikey = _FakeAdapter(_answer("S1M", "digikey"))
    registry = SourceRegistry([_Raising(), _DigiKeySource(digikey)])
    result = registry.enrich("S1M", "Other", want={"description", DIST_SOURCING})
    assert result.source_states == {"mouser": "failed", "digikey": "success"}


def test_both_officials_are_attempted_even_when_everything_is_already_filled():
    class _FillsEverything:
        name = "first"

        def enrich(self, mpn, category, remaining):
            return _answer(mpn, "first")

    mouser = _FakeAdapter(_answer("S1M", "mouser"))
    digikey = _FakeAdapter(_answer("S1M", "digikey"))
    registry = SourceRegistry(
        [_FillsEverything(), _MouserSource(mouser), _DigiKeySource(digikey)]
    )
    result = registry.enrich("S1M", "Other", want={"description", DIST_SOURCING})
    assert mouser.calls == 1 and digikey.calls == 1
    assert result.source_states == {"mouser": "success", "digikey": "success"}


def test_unconfigured_officials_are_reported_not_configured(tmp_path):
    pipeline = EnrichmentPipeline(tmp_path, mouser=None, digikey=None)
    result = EnrichmentResult()
    pipeline._record_unconfigured_officials(result)
    assert result.source_states == {
        "mouser": "not_configured",
        "digikey": "not_configured",
    }


def test_a_disabled_adapter_counts_as_not_configured(tmp_path):
    disabled = _FakeAdapter()
    disabled.enabled = False
    pipeline = EnrichmentPipeline(tmp_path, mouser=disabled, digikey=None)
    result = EnrichmentResult()
    pipeline._record_unconfigured_officials(result)
    assert result.source_states == {
        "mouser": "not_configured",
        "digikey": "not_configured",
    }


def test_a_consulted_verdict_is_never_overwritten_by_the_unconfigured_default(tmp_path):
    pipeline = EnrichmentPipeline(tmp_path, mouser=None, digikey=None)
    result = EnrichmentResult()
    result.source_states["mouser"] = "failed"
    pipeline._record_unconfigured_officials(result)
    assert result.source_states["mouser"] == "failed"
    assert result.source_states["digikey"] == "not_configured"


def test_source_states_survive_the_cache_round_trip():
    result = EnrichmentResult()
    result.source_states = {"mouser": "success", "digikey": "failed"}
    restored = _result_from_cache(_result_to_cache(result), "Other")
    assert restored.source_states == {"mouser": "success", "digikey": "failed"}


def test_configuring_a_new_distributor_refreshes_a_stale_cached_part(tmp_path):
    """A cache written before DigiKey setup must not hide DigiKey until its TTL expires."""

    from stockroom.enrich.pipeline import _result_to_cache

    mouser = _FakeAdapter(_answer("S1M", "mouser"))
    digikey = _FakeAdapter(_answer("S1M", "digikey"))
    pipeline = EnrichmentPipeline(tmp_path, mouser=mouser, digikey=digikey)
    pipeline.registry = SourceRegistry([_MouserSource(mouser), _DigiKeySource(digikey)])
    stale = _answer("S1M", "mouser")
    stale.source_states = {"mouser": "success", "digikey": "not_configured"}
    pipeline.cache.put("S1M", _result_to_cache(stale))

    result = pipeline.enrich("S1M", "Other")

    assert mouser.calls == 1 and digikey.calls == 1
    assert result.source_states == {"mouser": "success", "digikey": "success"}


def test_source_states_reach_the_result_dto():
    result = EnrichmentResult()
    result.source_states = {"mouser": "unavailable", "digikey": "success"}
    dto = _result_dto(result)
    assert dto["source_states"] == {"mouser": "unavailable", "digikey": "success"}


def test_the_explicit_mpn_route_always_keeps_the_distributor_token():
    assert _explicit_want(None) is None
    assert _explicit_want([]) is None
    assert DIST_SOURCING in _explicit_want(["description"])
    assert _explicit_want(["description", DIST_SOURCING]) == {"description", DIST_SOURCING}
