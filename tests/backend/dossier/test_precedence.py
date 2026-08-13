"""Source precedence, and the rule that a losing answer is never discarded."""

from __future__ import annotations

from itertools import permutations

from stockroom.dossier.precedence import (
    SOURCE_TIERS,
    TIER_RANK,
    Candidate,
    resolve,
    source_tier,
)
from stockroom.dossier.units import normalize


def _candidate(value: str, source: str) -> Candidate:
    return Candidate(
        value=value,
        normalized=normalize(value),
        source=source,
        tier=source_tier(source),
    )


def test_the_declared_order_is_the_owners_order():
    assert [key for key, _ in SOURCE_TIERS] == [
        "manual_override",
        "manufacturer_datasheet",
        "manufacturer_official",
        "authorized_distributor",
        "cad_provider",
        "parsed",
    ]


def test_each_source_lands_in_its_declared_tier():
    assert source_tier("manual") == "manual_override"
    assert source_tier("datasheet") == "manufacturer_datasheet"
    assert source_tier("manufacturer") == "manufacturer_official"
    assert source_tier("digikey") == "authorized_distributor"
    assert source_tier("mouser") == "authorized_distributor"
    assert source_tier("ultralibrarian") == "cad_provider"
    assert source_tier("snapmagic") == "cad_provider"


def test_lcsc_is_a_distributor_answer_and_not_parsed_data():
    # LCSC was a live enrich source the provider registry did not know, so this fell through to
    # `parsed` - the WEAKEST tier - and an LCSC value lost even to SnapMagic while reading as
    # `Parsed Or Inferred` rather than as the distributor answer it is.
    assert source_tier("lcsc") == "authorized_distributor"
    assert TIER_RANK[source_tier("lcsc")] < TIER_RANK["cad_provider"]
    assert TIER_RANK[source_tier("lcsc")] < TIER_RANK["parsed"]


def test_an_lcsc_answer_outranks_every_cad_provider():
    resolution = resolve(
        [_candidate("3", "snapmagic"), _candidate("2", "ultralibrarian"), _candidate("1", "lcsc")]
    )
    assert resolution.preferred.source == "lcsc"


def test_a_scraped_lcsc_page_is_still_parsed_data():
    assert source_tier("lcsc-scrape") == "parsed"


def test_a_scraped_page_is_parsed_data_whoever_the_page_belonged_to():
    assert source_tier("mouser-scrape") == "parsed"
    assert source_tier("mouser_scrape") == "parsed"


def test_an_unknown_source_can_never_outrank_the_manufacturer():
    assert TIER_RANK[source_tier("some-new-vendor")] > TIER_RANK["manufacturer_datasheet"]


def test_an_unattributed_value_is_the_weakest_tier_not_an_override():
    assert source_tier("") == "parsed"


def test_mouser_beats_the_datasheet_which_beats_a_cad_provider():
    resolution = resolve(
        [
            _candidate("3", "ultralibrarian"),
            _candidate("1", "mouser"),
            _candidate("2", "datasheet"),
        ]
    )
    assert resolution.preferred.source == "mouser"
    assert [item.source for item in resolution.candidates] == [
        "mouser",
        "datasheet",
        "ultralibrarian",
    ]


def test_a_reviewed_override_beats_the_manufacturers_own_datasheet():
    resolution = resolve([_candidate("2", "datasheet"), _candidate("1", "manual")])
    assert resolution.preferred.source == "manual"


def test_a_conflicting_value_is_kept_with_its_source_never_dropped():
    resolution = resolve([_candidate("1", "mouser"), _candidate("2", "digikey")])
    assert resolution.conflict_state == "conflicting"
    assert len(resolution.candidates) == 2


def test_agreeing_sources_are_not_a_conflict():
    assert resolve([_candidate("1", "mouser"), _candidate("1", "digikey")]).conflict_state == "none"


def test_agreement_survives_a_difference_of_engineering_scale():
    resolution = resolve([_candidate("0.5 V", "mouser"), _candidate("500 mV", "digikey")])
    assert resolution.conflict_state == "none"


def test_an_override_marks_a_disagreement_resolved_rather_than_open():
    resolution = resolve(
        [_candidate("1", "mouser"), _candidate("2", "digikey"), _candidate("3", "manual")]
    )
    assert resolution.conflict_state == "resolved"
    assert len(resolution.candidates) == 3


def test_a_tie_inside_one_tier_is_settled_by_the_registrys_own_order():
    # `mouser`, not `digikey`, since 2026-08-05: the owner's distributor trust order is Mouser
    # first, and the registry now declares it that way. The mechanism is unchanged - registry
    # position still settles a tie inside a tier - only the order it reads has moved.
    resolution = resolve([_candidate("1", "mouser"), _candidate("2", "digikey")])
    assert resolution.preferred.source == "mouser"


def test_the_owners_distributor_order_is_mouser_then_digikey_then_lcsc():
    resolution = resolve(
        [_candidate("3", "lcsc"), _candidate("2", "digikey"), _candidate("1", "mouser")]
    )
    assert resolution.preferred.source == "mouser"
    assert [item.source for item in resolution.candidates] == ["mouser", "digikey", "lcsc"]
    # One answer is SHOWN; none is thrown away.
    assert [item.value for item in resolution.candidates] == ["1", "2", "3"]


def test_a_field_only_one_distributor_reports_is_still_shown_and_attributed_to_it():
    for source in ("mouser", "digikey", "lcsc"):
        resolution = resolve([_candidate("only", source)])
        assert resolution.preferred is not None
        assert resolution.preferred.source == source
        assert resolution.preferred.tier == "authorized_distributor"
        assert resolution.preferred.value == "only"
        assert resolution.conflict_state == "none"


def test_mouser_is_the_fixed_winner_over_digikey_lcsc_and_the_datasheet():
    resolution = resolve(
        [
            _candidate("1", "mouser"),
            _candidate("2", "digikey"),
            _candidate("3", "lcsc"),
            _candidate("4", "datasheet"),
        ]
    )
    assert resolution.preferred.source == "mouser"
    assert [item.source for item in resolution.candidates] == [
        "mouser",
        "digikey",
        "datasheet",
        "lcsc",
    ]


def test_a_mouser_digikey_disagreement_still_reports_conflicting_while_showing_mouser():
    resolution = resolve([_candidate("100 kΩ", "digikey"), _candidate("10 kΩ", "mouser")])
    assert resolution.preferred.source == "mouser"
    assert resolution.preferred.value == "10 kΩ"
    # Merging to one displayed value may never paper the disagreement over.
    assert resolution.conflict_state == "conflicting"
    assert resolution.distinct_values == 2
    assert {item.source for item in resolution.candidates} == {"mouser", "digikey"}


def test_the_answer_does_not_depend_on_the_order_the_sources_arrived_in():
    forward = resolve([_candidate("1", "mouser"), _candidate("2", "digikey")])
    backward = resolve([_candidate("2", "digikey"), _candidate("1", "mouser")])
    assert forward.preferred.source == backward.preferred.source


def test_the_distributor_order_is_the_same_whichever_way_three_sources_arrive():
    made = {"mouser": "1", "digikey": "2", "lcsc": "3"}
    for arrival in permutations(made):
        resolution = resolve([_candidate(made[source], source) for source in arrival])
        assert resolution.preferred.source == "mouser", arrival
        assert [item.source for item in resolution.candidates] == [
            "mouser",
            "digikey",
            "lcsc",
        ], arrival


def test_nothing_at_all_resolves_to_nothing_rather_than_raising():
    resolution = resolve([])
    assert resolution.preferred is None
    assert resolution.conflict_state == "none"


# --------------------------------------------------------------- a preferred source


def test_a_pinned_source_is_preferred_without_any_candidate_being_dropped():
    resolution = resolve(
        [_candidate("1", "digikey"), _candidate("2", "mouser"), _candidate("3", "datasheet")],
        pinned_source="mouser",
    )
    assert resolution.preferred.source == "mouser"
    assert len(resolution.candidates) == 3
    assert {item.source for item in resolution.candidates} == {"digikey", "mouser", "datasheet"}


def test_a_pin_settles_a_disagreement_rather_than_leaving_it_open():
    resolution = resolve(
        [_candidate("1", "snapeda"), _candidate("2", "ultralibrarian")],
        pinned_source="snapeda",
    )
    assert resolution.conflict_state == "resolved"
    assert resolution.pinned_source == "snapeda"


def test_a_pin_on_agreeing_sources_is_still_not_a_conflict():
    resolution = resolve(
        [_candidate("1", "digikey"), _candidate("1", "mouser")], pinned_source="mouser"
    )
    assert resolution.conflict_state == "none"


def test_a_pin_no_candidate_answers_is_reported_as_not_in_force():
    resolution = resolve(
        [_candidate("1", "digikey"), _candidate("2", "mouser")], pinned_source="arrow"
    )
    # Falls back to the computed order, which is Mouser-first since 2026-08-05.
    assert resolution.preferred.source == "mouser"
    assert resolution.pinned_source == ""
    assert resolution.conflict_state == "conflicting"


def test_a_reviewed_value_still_outranks_a_pinned_source():
    resolution = resolve(
        [_candidate("1", "mouser"), _candidate("2", "manual")], pinned_source="mouser"
    )
    assert resolution.preferred.source == "manual"


def test_a_pin_beats_the_manufacturers_own_datasheet_because_a_person_chose_it():
    resolution = resolve(
        [_candidate("1", "datasheet"), _candidate("2", "mouser")], pinned_source="mouser"
    )
    assert resolution.preferred.source == "mouser"
