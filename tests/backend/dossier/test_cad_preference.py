"""The preferred CAD source: one provider for the whole set, and the refusals that keep it one.

The control this covers writes a DECISION into the record, so these tests hold the price of that
position. It has to name a provider that actually supplies the artifact, it has to refuse a
per-asset pin that would leave two providers in force across the three assets, and it has to say
what a change would replace BEFORE the change - because a confirmation that describes a different
outcome from the one that happens is worse than no confirmation.

The coherence gate itself (`cad_variants.same_cad_evidence_set`) is not relaxed anywhere here and
is not re-tested here; what is tested is that nothing this module writes can reach it in a state
it would reject.
"""

from __future__ import annotations

import pytest

from stockroom.dossier import component_dossier
from stockroom.dossier.cad_preference import (
    MixedCadSourceRefused,
    UnknownCadAsset,
    UnofferedCadSource,
    clear_asset_preferred_source,
    clear_preferred_source,
    current_sources,
    plan,
    set_asset_preferred_source,
    set_preferred_source,
)
from stockroom.model.asset import Asset, AssetOrigin, AssetRef
from stockroom.model.part import PartRecord
from tests.backend.dossier import records


def _coverage(**providers: dict[str, str]) -> dict:
    """A coverage document naming exactly what each provider supplies, in the real vocabulary."""
    return {
        "artifacts": ["symbol", "footprint", "model"],
        "rows": [
            {
                "id": key,
                "label": key.title(),
                **{
                    artifact: {"status": statuses.get(artifact, "unknown"), "origin": ""}
                    for artifact in ("symbol", "footprint", "model")
                },
            }
            for key, statuses in providers.items()
        ],
    }


_WHOLE_SET = {"symbol": "validated", "footprint": "downloaded", "model": "available"}


def _attached(record: PartRecord, vendor: str, kinds=("symbol", "footprint", "model")):
    bundle = record.assets_for("kicad")
    for kind in kinds:
        ref = AssetRef(file=f"models/{record.mpn}.step") if kind == "model" else AssetRef(
            lib="SR-ICs", name=record.mpn
        )
        setattr(bundle, kind, Asset(ref=ref, origin=AssetOrigin(vendor=vendor)))
    return record


# --------------------------------------------------------------- what is in force now


def test_with_nothing_attached_no_asset_names_a_source():
    sources = current_sources(records.microcontroller())
    assert [entry["provider"] for entry in sources.values()] == ["", "", ""]
    assert [entry["origin"] for entry in sources.values()] == ["", "", ""]


def test_an_attached_file_names_its_provider_as_installed_not_as_a_decision():
    sources = current_sources(_attached(records.microcontroller(), "ultralibrarian"))
    assert sources["symbol"] == {
        "provider": "ultralibrarian",
        "label": "Ultra Librarian",
        "origin": "installed",
    }


def test_a_recorded_preference_outranks_the_file_that_is_attached():
    record = _attached(records.microcontroller(), "samacsys")
    set_preferred_source(record, _coverage(ultralibrarian=_WHOLE_SET), "ultralibrarian")
    sources = current_sources(record)
    assert {entry["provider"] for entry in sources.values()} == {"ultralibrarian"}
    assert {entry["origin"] for entry in sources.values()} == {"set_preference"}


# --------------------------------------------------------------- the plan comes first


def test_a_plan_names_every_asset_that_would_move_and_what_would_supply_it():
    record = _attached(records.microcontroller(), "samacsys")
    decided = plan(record, _coverage(ultralibrarian=_WHOLE_SET), provider="ultralibrarian")
    assert decided["allowed"] is True
    assert {change["asset"] for change in decided["changes"]} == {"symbol", "footprint", "model"}
    first = decided["changes"][0]
    assert first["fromLabel"] == "SamacSys"
    assert first["toLabel"] == "Ultra Librarian"
    assert first["assetLabel"] == "Symbol"


def test_a_plan_that_changes_nothing_reports_no_changes_and_is_still_allowed():
    record = _attached(records.microcontroller(), "ultralibrarian")
    decided = plan(record, _coverage(ultralibrarian=_WHOLE_SET), provider="ultralibrarian")
    assert decided["allowed"] is True
    assert decided["changes"] == []


def test_planning_does_not_write_anything():
    record = _attached(records.microcontroller(), "samacsys")
    before = record.dumps()
    plan(record, _coverage(ultralibrarian=_WHOLE_SET), provider="ultralibrarian")
    assert record.dumps() == before


def test_a_refused_plan_carries_the_reason_the_reader_will_be_shown():
    record = records.microcontroller()
    decided = plan(
        record,
        _coverage(snapmagic={"symbol": "available", "footprint": "available"}),
        provider="snapmagic",
    )
    assert decided["allowed"] is False
    assert "3D Model" in decided["reason"]


# --------------------------------------------------------------- the whole-set decision


def test_preferring_a_provider_that_supplies_all_three_is_recorded():
    record = records.microcontroller()
    set_preferred_source(
        record, _coverage(ultralibrarian=_WHOLE_SET), "ultralibrarian", reviewed_at="2026-08-05"
    )
    assert record.cad_preference.provider == "ultralibrarian"
    assert record.cad_preference.reviewed_at == "2026-08-05"


def test_a_provider_that_cannot_supply_one_artifact_is_refused_for_the_whole_set():
    record = records.microcontroller()
    with pytest.raises(UnofferedCadSource) as caught:
        set_preferred_source(
            record,
            _coverage(snapmagic={"symbol": "validated", "footprint": "validated"}),
            "snapmagic",
        )
    assert "3D Model" in str(caught.value)
    assert record.cad_preference.is_empty()


def test_a_provider_nothing_has_said_anything_about_is_refused():
    record = records.microcontroller()
    with pytest.raises(UnofferedCadSource):
        set_preferred_source(record, _coverage(traceparts={}), "traceparts")


def test_a_provider_the_registry_does_not_know_is_refused_without_a_write():
    record = records.microcontroller()
    with pytest.raises(UnofferedCadSource):
        set_preferred_source(record, _coverage(ultralibrarian=_WHOLE_SET), "not-a-provider")
    assert record.cad_preference.is_empty()


def test_a_refusal_carries_a_code_so_the_wording_can_change_without_changing_behaviour():
    coverage = _coverage(ultralibrarian=_WHOLE_SET, samacsys=_WHOLE_SET)
    record = records.microcontroller()
    set_preferred_source(record, coverage, "ultralibrarian")
    assert plan(record, coverage, provider="samacsys", asset="model")["refusal"] == "mixed"
    assert plan(record, _coverage(snapmagic={}), provider="snapmagic")["refusal"] == "unsupplied"
    assert plan(record, coverage, provider="nope")["refusal"] == "unknown_provider"
    assert plan(record, coverage, provider="ultralibrarian")["refusal"] == ""


def test_choosing_a_set_source_clears_the_per_asset_exceptions_it_replaces():
    coverage = _coverage(ultralibrarian=_WHOLE_SET, samacsys=_WHOLE_SET)
    record = records.microcontroller()
    set_asset_preferred_source(record, coverage, "footprint", "samacsys")
    set_preferred_source(record, coverage, "ultralibrarian")
    assert record.cad_preference.assets == {}
    assert {entry["provider"] for entry in current_sources(record).values()} == {"ultralibrarian"}


def test_clearing_the_set_preference_returns_every_asset_to_the_attached_files():
    record = _attached(records.microcontroller(), "samacsys")
    set_preferred_source(record, _coverage(ultralibrarian=_WHOLE_SET), "ultralibrarian")
    clear_preferred_source(record)
    assert record.cad_preference.is_empty()
    assert {entry["origin"] for entry in current_sources(record).values()} == {"installed"}


def test_clearing_a_preference_that_was_never_recorded_is_a_success():
    record = records.microcontroller()
    decided = clear_preferred_source(record)
    assert decided["allowed"] is True
    assert record.cad_preference.is_empty()


# --------------------------------------------------------------- the per-asset decision


def test_a_per_asset_pin_is_accepted_when_it_leaves_one_provider_in_force():
    record = records.microcontroller()
    set_asset_preferred_source(
        record, _coverage(ultralibrarian=_WHOLE_SET), "footprint", "ultralibrarian"
    )
    assert record.cad_preference.assets == {"footprint": "ultralibrarian"}


def test_a_per_asset_pin_that_would_mix_two_providers_is_refused():
    coverage = _coverage(ultralibrarian=_WHOLE_SET, samacsys=_WHOLE_SET)
    record = records.microcontroller()
    set_preferred_source(record, coverage, "ultralibrarian")
    with pytest.raises(MixedCadSourceRefused) as caught:
        set_asset_preferred_source(record, coverage, "footprint", "samacsys")
    assert "Ultra Librarian" in str(caught.value)
    assert record.cad_preference.assets == {}


def test_a_per_asset_pin_that_would_mix_with_an_attached_file_is_refused():
    record = _attached(records.microcontroller(), "ultralibrarian")
    with pytest.raises(MixedCadSourceRefused):
        set_asset_preferred_source(
            record, _coverage(samacsys=_WHOLE_SET), "footprint", "samacsys"
        )


def test_a_per_asset_pin_names_the_asset_and_is_refused_when_the_provider_lacks_it():
    record = records.microcontroller()
    with pytest.raises(UnofferedCadSource) as caught:
        set_asset_preferred_source(
            record, _coverage(snapmagic={"symbol": "available"}), "model", "snapmagic"
        )
    assert "3D Model" in str(caught.value)


def test_an_asset_kind_this_component_does_not_have_is_refused_as_unknown():
    record = records.microcontroller()
    with pytest.raises(UnknownCadAsset):
        set_asset_preferred_source(record, _coverage(), "schematic", "ultralibrarian")


def test_clearing_one_asset_pin_leaves_the_whole_set_preference_standing():
    coverage = _coverage(ultralibrarian=_WHOLE_SET)
    record = records.microcontroller()
    set_preferred_source(record, coverage, "ultralibrarian")
    set_asset_preferred_source(record, coverage, "model", "ultralibrarian")
    clear_asset_preferred_source(record, "model")
    assert record.cad_preference.provider == "ultralibrarian"
    assert record.cad_preference.assets == {}


# --------------------------------------------------------------- the projection


def test_the_dossier_publishes_one_choosable_option_per_provider_row():
    dossier = component_dossier(records.microcontroller())
    preference = dossier["cadAssets"]["preference"]
    coverage_rows = {row["id"] for row in dossier["cadSourceCoverage"]["rows"]}
    assert {option["provider"] for option in preference["options"]} == coverage_rows


def test_an_option_carries_the_plan_the_write_would_refuse_with():
    record = _attached(records.microcontroller(), "ultralibrarian")
    dossier = component_dossier(record, coverage=_coverage(ultralibrarian=_WHOLE_SET))
    option = dossier["cadAssets"]["preference"]["options"][0]
    assert option["provider"] == "ultralibrarian"
    assert option["set"]["allowed"] is True
    assert option["coverage"] == _WHOLE_SET


def test_three_providers_across_three_assets_is_reported_as_mixed():
    record = records.microcontroller()
    _attached(record, "ultralibrarian", ("symbol",))
    _attached(record, "samacsys", ("footprint",))
    preference = component_dossier(record)["cadAssets"]["preference"]
    assert preference["mixed"] is True
    assert preference["provider"] == ""


def test_a_preference_that_decides_nothing_is_not_written_to_disk():
    record = records.microcontroller()
    assert "cad_preference" not in record.to_dict()


def test_a_recorded_preference_round_trips_through_the_record():
    record = records.microcontroller()
    set_preferred_source(record, _coverage(ultralibrarian=_WHOLE_SET), "ultralibrarian")
    reloaded = PartRecord.from_dict(record.to_dict())
    assert reloaded.cad_preference.provider == "ultralibrarian"
