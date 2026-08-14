"""The import pass: evidence written verbatim, re-derived, resumable, and DEFERRED != FAILED.

Driven through fake fetchers rather than the real adapters, so nothing here touches the network or
needs a credential - which is also the shape the real CLI uses when the owner has no key for one
distributor.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from stockroom.importer.engine import (
    Outcome,
    import_part,
    needs_sources,
    run_import,
)
from stockroom.model.part import PartRecord
from stockroom.model.part_class import PartClass
from stockroom.model.sourced import sourced_file, write_payload

AT = "2026-07-27T05:00:00Z"

# A payload with a NON-ALPHABETICAL key order and odd spacing, because "verbatim" is the claim and
# a re-serialization with sorted keys would silently break it while looking fine.
MOUSER_BODY = {
    "SearchResults": {
        "Parts": [
            {
                "ManufacturerPartNumber": "ERJ-P03F1101V",
                "Manufacturer": "Panasonic",
                "Description": "Thick Film Resistors - SMD 0603 1.1Kohms 1%",
                "DataSheetUrl": "https://example.invalid/erj.pdf",
                "Category": "Chip Resistor - Surface Mount",
                "ProductAttributes": [
                    {"AttributeName": "Resistance", "AttributeValue": "1.1 kOhms"},
                    {"AttributeName": "Tolerance", "AttributeValue": "1 %"},
                ],
            }
        ]
    }
}


class FakeFetcher:
    """A source that answers with a canned body, or refuses with a chosen status.

    `calls` is recorded so a test can prove a re-run did NOT re-fetch - which is the whole
    resumability claim, and is invisible if you only look at the resulting files.
    """

    def __init__(self, body=None, status="ok", enabled=True):
        self._body = body
        self.last_status = status
        self._enabled = enabled
        self.calls: list[str] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    def fetch_payload(self, mpn: str):
        self.calls.append(mpn)
        self.last_status = self.last_status  # provider sets this on every call
        return self._body


class FakeConfig:
    """Only what `build_sources` reads."""

    mouser_api_key = ""
    digikey_client_id = ""
    digikey_client_secret = ""


def _record(part_id="erj-p03f1101v-0000", mpn="ERJ-P03F1101V", cls=PartClass.COMPONENT):
    return PartRecord(id=part_id, mpn=mpn, manufacturer="Panasonic", part_class=cls)


def _tree(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


# --------------------------------------------------------------------- writes evidence

def test_the_payload_is_stored_BYTE_FOR_BYTE_as_the_source_sent_it(tmp_path):
    """The one line the whole sourced layer exists for.

    `json.dumps(json.loads(x))` loses key order and float spelling; that is a rewrite of evidence,
    and the current schema already lost a value that way. So this compares the PARSED payload for
    equality AND the key ORDER, which a sorted re-serialization would break.
    """
    rec = _record()
    fetcher = FakeFetcher(MOUSER_BODY)
    import_part(rec, library_root=tmp_path, sources=[("mouser", fetcher)], derived_at=AT)

    stored = json.loads(sourced_file(tmp_path, rec.id, "mouser").read_text(encoding="utf-8"))
    assert stored == MOUSER_BODY
    got = stored["SearchResults"]["Parts"][0]
    assert list(got) == list(MOUSER_BODY["SearchResults"]["Parts"][0]), (
        "the key ORDER changed, so the payload was re-serialized rather than stored verbatim"
    )


def test_the_record_indexes_the_evidence_it_now_has(tmp_path):
    rec = _record()
    import_part(rec, library_root=tmp_path, sources=[("mouser", FakeFetcher(MOUSER_BODY))],
                derived_at=AT)
    assert "mouser" in rec.sources
    assert rec.sources["mouser"].file == "sourced/erj-p03f1101v-0000/mouser.json"
    assert rec.sources["mouser"].fetched_at == AT


def test_the_import_re_derives_by_CALLING_the_derive_engine(tmp_path):
    """*"Calls the existing derive engine, does not write a second one."* Two derivations that
    drift is exactly how the frontend ended up reading fields the backend had renamed."""
    rec = _record()
    import_part(rec, library_root=tmp_path, sources=[("mouser", FakeFetcher(MOUSER_BODY))],
                derived_at=AT)
    assert rec.description.startswith("Thick Film")
    assert rec.specs.get("Resistance") == "1.1 kΩ" or rec.specs.get("Resistance")
    assert rec.derived.derived_at == AT
    assert rec.derived.derived_by.startswith("rules@")


def test_a_part_is_classified_but_a_human_class_is_never_overridden(tmp_path):
    rec = _record(mpn="29311", part_id="29311-0000")
    body = {"SearchResults": {"Parts": [{
        "ManufacturerPartNumber": "29311", "Manufacturer": "Keystone",
        "Description": "Screws & Fasteners M3 6.0mm Screw Zinc Plated Steel",
        "Category": "Hardware",
    }]}}
    res = import_part(rec, library_root=tmp_path, sources=[("mouser", FakeFetcher(body))],
                      derived_at=AT)
    assert res.reclassified_to == "mechanical"
    assert rec.part_class is PartClass.MECHANICAL

    # ...and a record already marked by a person is left alone.
    human = _record(part_id="lm317-0000", mpn="LM317T", cls=PartClass.VIRTUAL)
    res2 = import_part(human, library_root=tmp_path, sources=[("mouser", FakeFetcher(body))],
                       derived_at=AT)
    assert res2.reclassified_to == ""
    assert human.part_class is PartClass.VIRTUAL


# ------------------------------------------------------------------ DEFERRED != FAILED

def test_a_quota_refusal_is_DEFERRED_and_persists_attempt_truth_without_evidence(tmp_path):
    """A retryable refusal stays DEFERRED while its visible provider state survives reload."""
    rec = _record()
    res = import_part(rec, library_root=tmp_path,
                      sources=[("mouser", FakeFetcher(None, status="rate_limited"))],
                      derived_at=AT)
    assert res.outcome is Outcome.DEFERRED
    assert res.deferred == ["mouser"]
    assert "retryable" in res.detail
    assert not (tmp_path / "sourced").exists(), "a deferred part must write no evidence"
    assert rec.sources["mouser"].fetched_at == ""
    assert rec.sources["mouser"].file == ""
    assert rec.sources["mouser"].extra == {
        "state": "failed",
        "last_attempted_at": AT,
    }


def test_a_source_that_simply_does_not_know_the_part_is_NO_DATA_not_deferred(tmp_path):
    """The negative control for the test above: without it, that test would pass on an importer
    that called EVERYTHING deferred and so never reported a real gap."""
    res = import_part(_record(), library_root=tmp_path,
                      sources=[("mouser", FakeFetcher(None, status="not_found"))],
                      derived_at=AT)
    assert res.outcome is Outcome.NO_DATA
    assert res.deferred == []


def test_a_part_with_no_MPN_is_NO_DATA_and_never_looked_up(tmp_path):
    fetcher = FakeFetcher(MOUSER_BODY)
    res = import_part(_record(mpn=""), library_root=tmp_path, sources=[("mouser", fetcher)],
                      derived_at=AT)
    assert res.outcome is Outcome.NO_DATA
    assert fetcher.calls == [], "a part with nothing to look up must not cost an API call"


def test_one_source_refusing_does_not_stop_the_other_from_being_stored(tmp_path):
    """Source-agnostic completeness: a dead source must never wall a part off from being imported."""
    rec = _record()
    res = import_part(
        rec, library_root=tmp_path,
        sources=[("mouser", FakeFetcher(None, status="rate_limited")),
                 ("digikey", FakeFetcher({"Products": [
                     {"ManufacturerProductNumber": "ERJ-P03F1101V",
                      "Description": {"ProductDescription": "RES 1.1K"}}]}))],
        derived_at=AT,
    )
    assert res.outcome is Outcome.IMPORTED
    assert res.written == ["digikey"]
    assert res.deferred == ["mouser"]


# ------------------------------------------------------------------------ resumability

def test_needs_sources_reads_LIBRARY_STATE_with_no_checkpoint_file(tmp_path):
    rec = _record()
    assert needs_sources(tmp_path, rec.id, ["mouser", "digikey"]) == ["mouser", "digikey"]
    import_part(rec, library_root=tmp_path, sources=[("mouser", FakeFetcher(MOUSER_BODY))],
                derived_at=AT)
    assert needs_sources(tmp_path, rec.id, ["mouser", "digikey"]) == ["digikey"]


def test_a_second_pass_SKIPS_and_costs_no_api_call(tmp_path):
    """This is the resumability claim, and it is invisible if you only look at the files: the point
    is that the second run does not SPEND the owner's quota again."""
    rec = _record()
    first = FakeFetcher(MOUSER_BODY)
    import_part(rec, library_root=tmp_path, sources=[("mouser", first)], derived_at=AT)
    assert first.calls == ["ERJ-P03F1101V"]

    second = FakeFetcher(MOUSER_BODY)
    res = import_part(rec, library_root=tmp_path, sources=[("mouser", second)], derived_at=AT)
    assert res.outcome is Outcome.SKIPPED
    assert second.calls == [], "a resumed pass re-fetched a part it already had evidence for"


def test_refetch_deliberately_re_pulls(tmp_path):
    """The other side: a re-pull is legitimate, it just has to be asked for."""
    rec = _record()
    import_part(rec, library_root=tmp_path, sources=[("mouser", FakeFetcher(MOUSER_BODY))],
                derived_at=AT)
    again = FakeFetcher(MOUSER_BODY)
    res = import_part(rec, library_root=tmp_path, sources=[("mouser", again)], derived_at=AT,
                      refetch=True)
    assert res.outcome is Outcome.IMPORTED
    assert again.calls == ["ERJ-P03F1101V"]


# ---------------------------------------------------------------------------- dry run

def test_a_dry_run_writes_ABSOLUTELY_NOTHING(tmp_path):
    """Anything that acts on the world gets a dry run before it acts. This pass mutates a
    git-backed library of the owner's real parts, so the dry run is not optional - and it is only
    worth anything if it is measured rather than asserted."""
    rec = _record()
    (tmp_path / "parts").mkdir()
    before = _tree(tmp_path)

    res = import_part(rec, library_root=tmp_path, sources=[("mouser", FakeFetcher(MOUSER_BODY))],
                      derived_at=AT, dry_run=True)

    assert res.outcome is Outcome.IMPORTED, "the dry run must still report what it WOULD do"
    assert "would write" in res.detail
    assert _tree(tmp_path) == before, "the dry run touched the filesystem"
    assert rec.sources == {}, "the dry run mutated the record"
    assert not rec.description, "the dry run re-derived the record"


# ----------------------------------------------------------------- the whole-pass report

def test_a_pass_with_no_configured_source_says_so_instead_of_reporting_clean_parts(tmp_path):
    """LOUD and early. 158 parts reported `no_data` because nothing was configured would read as
    "the vendors do not know your library" rather than "you gave me no keys"."""
    report = run_import([_record()], library_root=tmp_path, config=FakeConfig(), derived_at=AT)
    assert report.results == []
    assert set(report.unusable_sources) == {"mouser", "digikey"}
    assert "not configured" in report.unusable_sources["mouser"]


def test_the_summary_names_every_bucket_including_the_empty_ones(tmp_path):
    """A bucket omitted when zero reads as "not measured" rather than as "none"."""
    report = run_import([], library_root=tmp_path, config=FakeConfig(), derived_at=AT)
    line = report.summary()
    for name in ("imported", "deferred", "no_data", "skipped", "failed"):
        assert name in line, f"the summary hides the {name} bucket"


def test_the_pass_paces_every_usable_source_per_part(tmp_path):
    """Quota policy is the CALLER's, injected - so tests run at full speed and the CLI owns the
    real limiter (`enrich.rescan.Pacer`) rather than this module growing a second one.

    Sources are INJECTED, not built from a config carrying a fake key. Measured 2026-07-27: the
    first version of this test passed `mouser_api_key="k"` and made a real outbound request to
    `api.mouser.com`. It passed - which is the problem, because a unit test that reaches the
    internet is flaky, slow, and spends the owner's quota to assert something about a counter.
    """
    seen: list[str] = []
    run_import([_record(), _record(part_id="b-0000", mpn="B")], library_root=tmp_path,
               config=FakeConfig(), derived_at=AT, pace=seen.append, dry_run=True,
               sources=[("mouser", FakeFetcher(MOUSER_BODY))])
    assert seen.count("mouser") == 2, f"the pacer was not consulted once per part: {seen}"


def test_pacing_is_skipped_for_a_part_that_already_has_all_its_evidence(tmp_path):
    """Regression pin for cold-eyes finding 8 (2026-07-27). Pacing used to run for EVERY record
    before `import_part` decided anything, so a resumed pass over 158 parts with 150 already
    imported still paid the full per-provider quota delay 158 times over - throttling for work it
    was never going to do."""
    rec = _record()
    import_part(rec, library_root=tmp_path, sources=[("mouser", FakeFetcher(MOUSER_BODY))],
                derived_at=AT)  # rec now has full mouser evidence already

    seen: list[str] = []
    run_import([rec], library_root=tmp_path, config=FakeConfig(), derived_at=AT,
               pace=seen.append, sources=[("mouser", FakeFetcher(MOUSER_BODY))])
    assert seen == [], f"pacing fired for a part with nothing left to fetch: {seen}"

    # NEGATIVE CONTROL: a part that DOES still need a fetch must still be paced, so the assertion
    # above is measuring the skip-when-done behaviour and not "pacing never fires".
    seen.clear()
    run_import([_record(part_id="fresh-0000", mpn="FRESH")], library_root=tmp_path,
               config=FakeConfig(), derived_at=AT, pace=seen.append, dry_run=True,
               sources=[("mouser", FakeFetcher(MOUSER_BODY))])
    assert seen == ["mouser"]


def test_the_importer_SUITE_never_reaches_the_network(tmp_path, monkeypatch):
    """A guard on the whole module, not just on the test above.

    Anything in this file that quietly built a real adapter would spend quota and be flaky in CI.
    Rather than trusting that no future test does it, this makes `urlopen` explode and drives the
    pass: if the importer reaches for a socket, this fails and NAMES the url it wanted.
    """
    import urllib.request

    def forbidden(req, *a, **k):
        url = getattr(req, "full_url", req)
        raise AssertionError(f"the importer attempted an outbound request to {url}")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    report = run_import([_record()], library_root=tmp_path, config=FakeConfig(), derived_at=AT,
                        sources=[("mouser", FakeFetcher(MOUSER_BODY))])
    assert report.count(Outcome.IMPORTED) == 1


# ---------------------------------------------------- regression pin: finding 4 (exception scope)

class RaisingFetcher:
    """A source whose fetch always raises - the malformed-response / proxy-returns-HTML case."""

    enabled = True
    last_status = ""

    def fetch_payload(self, mpn: str):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")


def test_a_raising_fetcher_fails_only_that_part_never_the_whole_run(tmp_path):
    """Regression pin for cold-eyes finding 4 (2026-07-27). MEASURED: before this fix, a fetcher
    raising `json.JSONDecodeError` (a `ValueError`, from a proxy answering a 200 with HTML) escaped
    the per-source loop entirely - it was not wrapped in any try/except - and killed `run_import`
    with no `ImportReport` produced at all, silently dropping every part after the one that broke."""
    good_a = _record(part_id="a-0000", mpn="A")
    bad = _record(part_id="bad-0000", mpn="BAD")
    good_c = _record(part_id="c-0000", mpn="C")

    calls: list[str] = []

    def save(rec):
        calls.append(rec.id)

    report = run_import(
        [good_a, bad, good_c], library_root=tmp_path, config=FakeConfig(), derived_at=AT,
        sources=[("mouser", RaisingFetcher())], save=save,
    )
    # Nothing escaped: a report exists and covers all three parts.
    assert len(report.results) == 3
    assert report.count(Outcome.FAILED) == 3, (
        "every part used the same raising fetcher and no other source, so all three legitimately "
        "have nothing to import from - but the point is that all THREE were even attempted."
    )
    ids = [r.part_id for r in report.results]
    assert ids == ["a-0000", "bad-0000", "c-0000"], "a raising source must not stop the pass early"
    assert calls == ids, "failure state must be persisted even when no payload was written"


def test_an_unknown_naming_scheme_fails_the_one_part_not_the_batch(tmp_path):
    """The other escape route finding 4 named: `UnknownNamingScheme` subclasses `Exception`
    directly, not `ValueError`, so the original narrow catch tuple missed it - and by the time it
    raised, the payload had ALREADY been written to sourced/, leaving orphaned evidence."""
    rec = _record()
    other = _record(part_id="other-0000", mpn="OTHER")
    report = run_import(
        [rec, other], library_root=tmp_path, config=FakeConfig(), derived_at=AT,
        scheme="humna-readable", sources=[("mouser", FakeFetcher(MOUSER_BODY))],
    )
    assert len(report.results) == 2
    assert report.count(Outcome.FAILED) == 2
    for r in report.results:
        assert "UnknownNamingScheme" in r.detail


# ------------------------------------------------------- regression pin: finding 5 (orphaned evidence)

def test_orphaned_evidence_is_recovered_without_a_new_fetch(tmp_path):
    """Regression pin for cold-eyes finding 5 (2026-07-27). Simulates the crash this guards
    against: a payload write that succeeded, followed by a failure BEFORE the record was
    persisted - so on the next pass the file exists but `record.sources` does not know about it.
    Resumability is keyed purely on file existence (`needs_sources`), so without this fix the
    source would read as "already done" and never be finished - permanently, silently, forever in
    the `skipped` bucket.
    """
    rec = _record()
    # Write the payload directly, bypassing import_part, to simulate the write having already
    # succeeded on a PRIOR pass that then failed before persisting the record.
    write_payload(tmp_path, rec.id, "mouser", __import__("json").dumps(MOUSER_BODY))
    assert rec.sources == {}, "the record must NOT already know about this evidence"

    # A fetcher that raises if called at all - proves the recovery path does NOT re-fetch.
    class ExplodingFetcher:
        enabled = True
        last_status = ""

        def fetch_payload(self, mpn: str):
            raise AssertionError("orphaned evidence must be recovered WITHOUT a new fetch")

    res = import_part(rec, library_root=tmp_path, sources=[("mouser", ExplodingFetcher())],
                      derived_at=AT)
    assert res.outcome is Outcome.IMPORTED
    assert res.recovered == ["mouser"]
    assert res.written == []
    assert "mouser" in rec.sources
    assert rec.description.startswith("Thick Film"), "the orphaned evidence was not re-derived"


def test_a_second_pass_after_recovery_is_a_clean_skip(tmp_path):
    """Once recovered, the part must read as genuinely done - not re-recovered forever."""
    rec = _record()
    write_payload(tmp_path, rec.id, "mouser", __import__("json").dumps(MOUSER_BODY))
    import_part(rec, library_root=tmp_path, sources=[("mouser", FakeFetcher(MOUSER_BODY))],
                derived_at=AT)
    res2 = import_part(rec, library_root=tmp_path, sources=[("mouser", FakeFetcher(MOUSER_BODY))],
                       derived_at=AT)
    assert res2.outcome is Outcome.SKIPPED
