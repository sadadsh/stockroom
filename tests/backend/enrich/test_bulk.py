from pathlib import Path

from stockroom.enrich.bulk import (
    BulkReport,
    bulk_enrich,
    parse_bom_csv,
    parse_mpn_list,
)
from stockroom.enrich.schema import EnrichmentResult, Sourced
from stockroom.ingest.staging import StagingCandidate

FIX = Path(__file__).parent / "fixtures"


def test_parse_mpn_list_drops_blanks_comments_and_dupes():
    text = "TPS62130RGTR\n\n# a comment\nLM358\nTPS62130RGTR\n"
    assert parse_mpn_list(text) == ["TPS62130RGTR", "LM358"]


def test_parse_bom_csv_finds_the_mpn_column():
    mpns = parse_bom_csv((FIX / "sample_bom.csv").read_text())
    assert mpns == ["RC0402FR-0710KL", "CL05B104KO5NNNC", "TPS62130RGTR"]


class _FakePipeline:
    """Returns a canned result per MPN and fills the candidate like the real one."""
    def __init__(self, results):
        self._results = results

    def enrich_candidate(self, candidate, overwrite=None):
        r = self._results.get(candidate.mpn)
        if r and r.manufacturer:
            candidate.manufacturer = r.manufacturer.value
        if r and r.description:
            candidate.description = r.description.value
        return candidate


def test_bulk_enrich_reports_complete_and_incomplete_per_part():
    results = {
        "TPS62130RGTR": _full_result(),
        "MYSTERY": EnrichmentResult(category="ICs"),  # nothing found
    }
    report = bulk_enrich(["TPS62130RGTR", "MYSTERY"], _FakePipeline(results), category="ICs")
    assert isinstance(report, BulkReport)
    by_mpn = {i.mpn: i for i in report.items}
    # the fully-enriched-but-assetless part is still incomplete (no symbol/footprint/etc)
    assert by_mpn["MYSTERY"].complete is False
    assert by_mpn["MYSTERY"].missing  # names what is still missing
    # the batch never aborts on a miss
    assert len(report.items) == 2


def _full_result():
    r = EnrichmentResult(category="ICs")
    r.manufacturer = Sourced("TI", "scrape", "high")
    r.description = Sourced("buck", "scrape", "high")
    return r
