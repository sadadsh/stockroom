"""Revision history: the dated events the record can prove, and nothing it cannot."""

from __future__ import annotations

from stockroom.dossier import component_dossier
from stockroom.dossier.revisions import REVISION_LABELS, build_revisions
from stockroom.model.asset import Asset, AssetOrigin, AssetRef
from stockroom.model.part import Datasheet, FieldOverride, PartDocument, Provenance
from stockroom.model.sourced import SourceEntry
from tests.backend.dossier import records


def _record():
    record = records.resistor()
    record.provenance = Provenance(
        source="ultralibrarian",
        source_url="https://ul.test/p",
        original_zip_sha256="abc",
        ingested_at="2026-01-01T00:00:00+00:00",
    )
    record.sources = {"mouser": SourceEntry(fetched_at="2026-03-01T00:00:00+00:00",
                                            file="sourced/x/mouser.json")}
    record.datasheet = Datasheet(
        source_url="https://industrial.panasonic.com/ds.pdf",
        fetched_at="2026-02-01T00:00:00+00:00",
    )
    record.documents = [
        PartDocument(
            document_type="package_drawing",
            title="Outline",
            remote_url="https://industrial.panasonic.com/drawing.pdf",
            retrieved_at="2026-04-01T00:00:00+00:00",
            verified_at="2026-04-02T00:00:00+00:00",
        )
    ]
    record.overrides = {
        "resistance": FieldOverride(
            value="1.1 kOhms", reviewed_by="owner", reviewed_at="2026-05-01T00:00:00+00:00"
        )
    }
    record.assets_for("kicad").symbol = Asset(
        ref=AssetRef(lib="SR-Resistors", name="R"),
        origin=AssetOrigin(vendor="ultralibrarian", captured_at="2026-06-01T00:00:00+00:00"),
    )
    record.derived_at = "2026-07-01T00:00:00+00:00"
    record.derived_by = "derive/3"
    return record


def _kinds(record) -> list[str]:
    return [item["kind"] for item in component_dossier(record)["revisions"]]


def test_every_kind_of_event_the_record_proves_is_on_the_timeline():
    assert set(_kinds(_record())) == {
        "imported",
        "source_fetched",
        "document_retrieved",
        "document_verified",
        "manual_override",
        "cad_captured",
        "derived",
    }


def test_the_timeline_reads_newest_first():
    dates = [item["at"] for item in component_dossier(_record())["revisions"] if item["at"]]
    assert dates == sorted(dates, reverse=True)


def test_an_undated_event_is_kept_and_sorts_last_rather_than_claiming_to_be_oldest():
    record = _record()
    record.sources["digikey"] = SourceEntry(fetched_at="", file="sourced/x/digikey.json")
    events = component_dossier(record)["revisions"]
    assert events[-1]["at"] == ""
    assert any(item["kind"] == "source_fetched" and item["at"] == "" for item in events)


def test_every_event_carries_a_readable_kind_label():
    for item in component_dossier(_record())["revisions"]:
        assert item["kindLabel"] == REVISION_LABELS[item["kind"]]
        assert item["summary"]


def test_a_manual_override_appears_on_the_timeline_with_its_reviewer():
    override = next(
        item for item in component_dossier(_record())["revisions"]
        if item["kind"] == "manual_override"
    )
    assert "owner" in override["summary"]


def test_a_record_with_no_history_reports_an_empty_timeline_rather_than_inventing_one():
    assert build_revisions(records.resistor(), []) == []


def test_a_pinned_source_is_reported_as_a_pin_rather_than_as_a_typed_value():
    record = _record()
    record.overrides = {
        "resistance": FieldOverride(
            has_value=False,
            preferred_source="mouser",
            reviewed_by="owner",
            reviewed_at="2026-05-01T00:00:00+00:00",
        )
    }
    dossier = component_dossier(record)
    entry = dossier["provenance"]["manualOverrides"][0]
    assert entry["hasValue"] is False
    assert entry["preferredSourceLabel"] == "Mouser"
    event = next(item for item in dossier["revisions"] if item["kind"] == "manual_override")
    assert "pinned to Mouser" in event["summary"]


def test_a_reviewed_value_reports_the_sourced_answer_it_displaced():
    record = _record()
    record.overrides = {
        "resistance": FieldOverride(
            value="1.2 kOhms",
            replaced_value="1.1 kOhms",
            replaced_source="digikey",
            reviewed_by="owner",
            reviewed_at="2026-05-01T00:00:00+00:00",
        )
    }
    entry = component_dossier(record)["provenance"]["manualOverrides"][0]
    assert entry["replacedValue"] == "1.1 kOhms"
    assert entry["replacedSourceLabel"] == "DigiKey"


def test_every_event_belongs_to_exactly_one_history():
    """Two questions live in one timeline: how the data got here, and what changed since.

    Splitting them in the projection rather than in a surface means both histories are the same
    answer everywhere, and a new event kind cannot land in neither.
    """
    events = component_dossier(_record())["revisions"]
    assert events, "the record proves several dated events"
    for item in events:
        assert item["section"] in {"intake", "changes"}
        assert item["sectionLabel"] in {
            "Import and Enrichment History",
            "Revision History",
        }
    by_kind = {item["kind"]: item["section"] for item in events}
    assert by_kind["imported"] == "intake"
    assert by_kind["source_fetched"] == "intake"
    assert by_kind["derived"] == "intake"
    assert by_kind["manual_override"] == "changes"
    assert by_kind["document_retrieved"] == "changes"


def test_a_source_being_read_is_described_as_supplying_data():
    """"Answered" is a word about a request. It said nothing about whether anything useful came
    back, and it is not a word this product uses about a source any more."""
    event = next(
        item for item in component_dossier(_record())["revisions"]
        if item["kind"] == "source_fetched"
    )
    assert event["kindLabel"] == "Source Read"
    assert "supplied data" in event["summary"]
    assert "answered" not in event["summary"].casefold()
