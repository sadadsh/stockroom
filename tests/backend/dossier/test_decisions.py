"""The reviewed decisions a person records about one specification.

An override sits at the top of the source precedence order, so these tests hold the price of
that position: it never deletes a source's answer, it says what it displaced, it can be
withdrawn, and it can only ever name a field the specification sheet knows how to show. A
preferred source is the weaker decision beside it - "believe this source" rather than "the answer
is this" - and it has to follow that source rather than freeze a copy of what it said.
"""

from __future__ import annotations

import pytest

from stockroom.dossier.decisions import (
    UnknownSpecification,
    UnpinnableSource,
    canonical_key,
    clear_override,
    clear_preferred_source,
    set_override,
    set_preferred_source,
    sourced_candidates,
    specification_row,
)
from stockroom.model.part import FieldOverride, PartRecord, SourcedValue
from tests.backend.dossier import records


def _contested() -> PartRecord:
    """A resistor whose tolerance two distributors disagree about.

    Mouser deliberately holds the answer computed precedence picks and DigiKey the one it does
    not, because the registry's distributor order is Mouser first (2026-08-05). Every pin test
    below pins DigiKey for that reason: pinning the source that already wins would prove nothing
    about promotion. The two names were swapped here when the order was, so each test still says
    exactly what it said before - only which distributor plays the losing role changed.
    """
    record = records.resistor()
    record.alternates = {
        "Tolerance": [
            SourcedValue(value="1%", source="mouser"),
            SourcedValue(value="2%", source="digikey"),
        ]
    }
    return record


def _row(record: PartRecord, key: str = "tolerance") -> dict:
    row = specification_row(record, key)
    assert row is not None
    return row


def _sources(row: dict) -> list[str]:
    return [candidate["sourceId"] for candidate in row["sourceCandidates"]]


# --------------------------------------------------------------- naming the field


def test_a_spelling_of_a_known_field_resolves_to_its_canonical_key():
    assert canonical_key("Voltage - Supply") == "supply_voltage"
    assert canonical_key("voltage_supply") == "supply_voltage"


def test_a_key_no_canonical_field_claims_is_refused():
    with pytest.raises(UnknownSpecification):
        canonical_key("wibble_factor")


def test_an_override_for_an_unknown_key_writes_nothing():
    record = _contested()
    with pytest.raises(UnknownSpecification):
        set_override(record, "wibble_factor", "9")
    assert record.overrides == {}


# --------------------------------------------------------------- overrides


def test_an_override_is_added_on_top_without_removing_any_candidate():
    record = _contested()
    before = _sources(_row(record))
    set_override(record, "tolerance", "0.5%", reviewed_by="user", reviewed_at="2026-08-05")
    row = _row(record)
    assert _sources(row) == ["manual", *before]
    assert row["preferredValue"] == "0.5%"


def test_an_override_marks_the_disagreement_resolved_rather_than_erasing_it():
    record = _contested()
    assert _row(record)["conflictState"] == "conflicting"
    set_override(record, "tolerance", "0.5%")
    row = _row(record)
    assert row["conflictState"] == "resolved"
    assert len(row["sourceCandidates"]) == 3


def test_an_override_records_the_value_and_source_it_displaced():
    record = _contested()
    set_override(record, "tolerance", "0.5%", reviewed_by="user", reviewed_at="2026-08-05")
    override = _row(record)["override"]
    assert override["replacedValue"] == "1%"
    assert override["replacedSource"] == "mouser"
    assert override["replacedSourceLabel"] == "Mouser"
    assert override["reviewedBy"] == "user"
    assert override["reviewedAt"] == "2026-08-05"


def test_a_second_override_records_what_the_sources_say_not_the_first_override():
    record = _contested()
    set_override(record, "tolerance", "0.5%")
    set_override(record, "tolerance", "0.25%")
    override = _row(record)["override"]
    assert override["replacedValue"] == "1%"
    assert override["replacedSource"] == "mouser"


def test_an_override_on_a_field_nothing_answered_displaces_nothing():
    record = records.resistor()
    set_override(record, "eccn", "EAR99")
    override = _row(record, "eccn")["override"]
    assert override["replacedValue"] is None
    assert override["replacedSource"] == ""


def test_an_override_answers_a_field_no_source_ever_reported():
    record = records.resistor()
    assert _row(record, "temperature_coefficient")["verificationState"] == "not_reported"
    set_override(record, "temperature_coefficient", "100 ppm/°C")
    row = _row(record, "temperature_coefficient")
    assert row["verificationState"] == "verified"
    assert row["displayValue"] == "100 ppm/°C"


def test_clearing_an_override_that_was_never_set_is_not_an_error():
    record = _contested()
    key, changed = clear_override(record, "tolerance")
    assert key == "tolerance"
    assert changed is False
    assert record.overrides == {}


def test_clearing_an_override_returns_the_field_to_its_sources():
    record = _contested()
    set_override(record, "tolerance", "0.5%")
    assert clear_override(record, "tolerance")[1] is True
    row = _row(record)
    assert row["preferredValue"] == "1%"
    assert row["conflictState"] == "conflicting"
    assert row["override"] is None


def test_clearing_an_override_twice_is_still_a_success():
    record = _contested()
    set_override(record, "tolerance", "0.5%")
    clear_override(record, "tolerance")
    assert clear_override(record, "tolerance")[1] is False


def test_an_entry_that_decides_nothing_is_not_kept_on_the_record():
    record = _contested()
    set_override(record, "tolerance", "0.5%")
    clear_override(record, "tolerance")
    assert record.overrides == {}


# --------------------------------------------------------------- preferred source


def test_a_preferred_source_must_be_one_of_the_fields_own_candidates():
    record = _contested()
    with pytest.raises(UnpinnableSource):
        set_preferred_source(record, "tolerance", "arrow")
    assert record.overrides == {}


def test_a_field_nothing_answered_can_have_no_preferred_source():
    record = records.resistor()
    with pytest.raises(UnpinnableSource):
        set_preferred_source(record, "eccn", "mouser")


def test_a_persons_own_earlier_answer_is_not_offered_as_a_source_to_prefer():
    record = _contested()
    set_override(record, "tolerance", "0.5%")
    assert "manual" not in {item["sourceId"] for item in sourced_candidates(record, "tolerance")}
    with pytest.raises(UnpinnableSource):
        set_preferred_source(record, "tolerance", "manual")


def test_a_preferred_source_promotes_that_source_without_dropping_the_others():
    record = _contested()
    assert _row(record)["preferredSource"]["sourceId"] == "mouser"
    set_preferred_source(record, "tolerance", "digikey", reviewed_by="user")
    row = _row(record)
    assert row["preferredSource"]["sourceId"] == "digikey"
    assert row["preferredValue"] == "2%"
    assert set(_sources(row)) == {"mouser", "digikey"}


def test_a_pinned_field_reports_the_disagreement_as_settled_rather_than_open():
    record = _contested()
    set_preferred_source(record, "tolerance", "digikey")
    row = _row(record)
    assert row["conflictState"] == "resolved"
    assert row["preferredSourcePin"]["inForce"] is True


def test_a_pin_follows_its_source_rather_than_copying_what_it_said():
    record = _contested()
    set_preferred_source(record, "tolerance", "digikey")
    record.alternates["Tolerance"][1] = SourcedValue(value="5%", source="digikey")
    assert _row(record)["preferredValue"] == "5%"


def test_a_pin_never_becomes_an_empty_manual_answer():
    record = _contested()
    set_preferred_source(record, "tolerance", "digikey")
    row = _row(record)
    assert "manual" not in _sources(row)
    assert row["override"] is None


def test_a_pin_whose_source_no_longer_answers_is_reported_not_obeyed():
    record = _contested()
    set_preferred_source(record, "tolerance", "digikey")
    record.alternates["Tolerance"] = [SourcedValue(value="1%", source="mouser")]
    row = _row(record)
    assert row["preferredSource"]["sourceId"] == "mouser"
    assert row["preferredSourcePin"]["inForce"] is False


def test_a_reviewed_value_outranks_a_pin_and_the_pin_says_it_is_not_in_force():
    record = _contested()
    set_preferred_source(record, "tolerance", "digikey")
    set_override(record, "tolerance", "0.5%")
    row = _row(record)
    assert row["preferredValue"] == "0.5%"
    assert row["preferredSourcePin"]["inForce"] is False


def test_clearing_the_override_hands_the_field_back_to_the_pin():
    record = _contested()
    set_preferred_source(record, "tolerance", "digikey")
    set_override(record, "tolerance", "0.5%")
    clear_override(record, "tolerance")
    row = _row(record)
    assert row["preferredValue"] == "2%"
    assert row["preferredSourcePin"]["inForce"] is True


def test_clearing_a_preferred_source_returns_the_field_to_computed_precedence():
    record = _contested()
    set_preferred_source(record, "tolerance", "digikey")
    assert clear_preferred_source(record, "tolerance")[1] is True
    row = _row(record)
    assert row["preferredSource"]["sourceId"] == "mouser"
    assert row["conflictState"] == "conflicting"
    assert row["preferredSourcePin"] is None


def test_clearing_a_preferred_source_that_was_never_set_is_not_an_error():
    record = _contested()
    key, changed = clear_preferred_source(record, "tolerance")
    assert key == "tolerance"
    assert changed is False
    assert record.overrides == {}


def test_clearing_a_preferred_source_never_resurrects_a_cleared_override():
    record = _contested()
    set_override(record, "tolerance", "0.5%")
    set_preferred_source(record, "tolerance", "digikey")
    clear_override(record, "tolerance")
    clear_preferred_source(record, "tolerance")
    assert record.overrides == {}
    assert _row(record)["preferredValue"] == "1%"


# --------------------------------------------------------------- storage


def test_a_decision_survives_a_record_round_trip():
    record = _contested()
    set_override(record, "tolerance", "0.5%", reviewed_by="user", reviewed_at="2026-08-05")
    set_preferred_source(record, "tolerance", "digikey", reviewed_by="user")
    restored = PartRecord.loads(record.dumps())
    stored = restored.overrides["tolerance"]
    assert stored.value == "0.5%"
    assert stored.preferred_source == "digikey"
    assert stored.replaced_value == "1%"
    assert stored.replaced_source == "mouser"


def test_an_override_written_before_pins_existed_is_still_a_value_override():
    stored = FieldOverride.from_dict(
        {"value": "0.5%", "note": "", "reviewed_by": "user", "reviewed_at": "2026-01-01"}
    )
    assert stored.has_value is True
    assert stored.preferred_source == ""


def test_an_ordinary_override_serializes_exactly_as_it_always_did():
    stored = FieldOverride(value="0.5%", note="n", reviewed_by="user", reviewed_at="2026-01-01")
    assert stored.to_dict() == {
        "value": "0.5%",
        "note": "n",
        "reviewed_by": "user",
        "reviewed_at": "2026-01-01",
    }


def test_a_pin_only_entry_says_it_holds_no_value():
    record = _contested()
    set_preferred_source(record, "tolerance", "digikey")
    assert record.overrides["tolerance"].to_dict()["has_value"] is False


def test_a_decision_is_the_only_thing_the_record_gains():
    record = _contested()
    before = set(PartRecord.loads(record.dumps()).to_dict())
    set_override(record, "tolerance", "0.5%")
    assert set(record.to_dict()) - before == {"overrides"}


def test_pinning_the_source_already_pinned_never_records_it_as_overriding_itself():
    record = _contested()
    set_preferred_source(record, "tolerance", "digikey")
    set_preferred_source(record, "tolerance", "digikey")
    pin = _row(record)["preferredSourcePin"]
    assert pin["replacedSource"] == "mouser"


def test_repinning_to_another_source_records_the_one_it_took_over_from():
    record = _contested()
    set_preferred_source(record, "tolerance", "digikey")
    set_preferred_source(record, "tolerance", "mouser")
    pin = _row(record)["preferredSourcePin"]
    assert pin["sourceId"] == "mouser"
    assert pin["replacedSource"] == "digikey"


# ------------------------------------------- the reason, and whether it was checked


def test_a_reviewed_value_carries_the_reason_it_was_recorded_for():
    record = _contested()
    set_override(record, "tolerance", "0.5%", note="measured on the reel label")
    assert _row(record)["override"]["note"] == "measured on the reel label"


def test_a_value_the_reviewer_has_not_confirmed_reads_as_unverified():
    # A manual decision outranks every source. Reporting one as `Verified` when the person
    # entering it said they had not checked it would put our own word above the manufacturer's
    # on the strength of an admission that it was a guess.
    record = _contested()
    set_override(record, "tolerance", "0.5%", verified=False)
    row = _row(record)
    assert row["verificationState"] == "unverified"
    assert row["override"]["verified"] is False
    assert row["override"]["value"] == "0.5%"


def test_a_confirmed_reviewed_value_still_reads_as_verified():
    record = _contested()
    set_override(record, "tolerance", "0.5%")
    row = _row(record)
    assert row["verificationState"] == "verified"
    assert row["override"]["verified"] is True


def test_a_confirmed_override_serializes_exactly_as_an_override_always_did():
    # Every override on disk predates this field and meant a reviewed decision, so the default
    # must add nothing to the JSON: adopting it rewrites no record already written.
    stored = FieldOverride(value="0.5%", note="n", reviewed_by="user", reviewed_at="2026-01-01")
    assert "verified" not in stored.to_dict()
    assert FieldOverride.from_dict({"value": "1%"}).verified is True


def test_an_unconfirmed_override_says_so_on_disk_and_reads_back():
    stored = FieldOverride(value="0.5%", verified=False)
    assert stored.to_dict()["verified"] is False
    assert FieldOverride.from_dict(stored.to_dict()).verified is False


def test_withdrawing_a_value_takes_its_reason_and_its_confidence_with_it():
    record = _contested()
    set_override(record, "tolerance", "0.5%", note="reel label", verified=False)
    set_preferred_source(record, "tolerance", "digikey")
    clear_override(record, "tolerance")
    entry = record.overrides["tolerance"]
    assert entry.note == ""
    assert entry.verified is True
    assert entry.preferred_source == "digikey"
