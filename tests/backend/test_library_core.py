"""library_core: the pure, Qt-free, contract-agnostic KiCad name helpers.

These helpers know nothing about which library a name belongs to: the caller supplies
the KiCad nickname (in Stockroom that is ``category_nickname(cat)`` -> ``SR-<slug>``, from
model/category.py + kicad/wiring.py). The naming behavior is copied by-behavior out of
the retired PyQt LibraryManager (never imported: it drags PyQt5); the retired app's flat
``MySymbols``/``MyFootprints`` contract is deliberately NOT encoded here.
"""

from pathlib import Path

from stockroom import library_core as lc

# A realistic Stockroom per-category nickname (category_nickname("Resistors")).
NICK = "SR-resistors"


# -- symbol lib_id qualification (caller supplies the nickname) ----------------


def test_qualify_symbol_prefixes_the_supplied_nickname():
    assert lc.qualify_symbol("R_10k", NICK) == "SR-resistors:R_10k"


def test_qualify_symbol_is_idempotent_on_an_already_qualified_name():
    assert lc.qualify_symbol("SR-resistors:R_10k", NICK) == "SR-resistors:R_10k"


def test_qualify_symbol_requalifies_a_foreign_nickname_to_the_supplied_one():
    # A vendor-nicknamed lib_id gets repointed at the target library.
    assert lc.qualify_symbol("Device:R", NICK) == "SR-resistors:R"


def test_qualify_symbol_of_empty_is_empty():
    assert lc.qualify_symbol("", NICK) == ""
    assert lc.qualify_symbol("   ", NICK) == ""


def test_symbol_name_ref_strips_the_nickname():
    assert lc.symbol_name_ref("SR-resistors:R_10k") == "R_10k"
    assert lc.symbol_name_ref("R_10k") == "R_10k"
    assert lc.symbol_name_ref("") == ""


# -- footprint name qualification (caller supplies the nickname) ---------------


def test_footprint_name_strips_any_library_nickname():
    assert lc.footprint_name("STUSB4500QTR:QFN50") == "QFN50"
    assert lc.footprint_name("RM_10_ADI") == "RM_10_ADI"  # bare name is unchanged
    assert lc.footprint_name("") == ""
    assert lc.footprint_name("  Lib:Name  ") == "Name"


def test_qualify_footprint_prefixes_the_supplied_nickname():
    assert lc.qualify_footprint("R0805", NICK) == "SR-resistors:R0805"


def test_qualify_footprint_is_idempotent():
    assert lc.qualify_footprint("SR-resistors:R0805", NICK) == "SR-resistors:R0805"


def test_qualify_footprint_requalifies_a_vendor_nickname():
    assert lc.qualify_footprint("STUSB4500QTR:QFN50", "SR-ics") == "SR-ics:QFN50"


def test_qualify_footprint_of_empty_is_empty():
    assert lc.qualify_footprint("", NICK) == ""


def test_qualify_helpers_do_not_encode_the_retired_flat_library_contract():
    # library_core must NOT re-export the retired app's flat MySymbols/MyFootprints/
    # MY3DMODELS nicknames (Stockroom resolves per category via SR-<slug> + SR_LIB).
    for gone in ("FP_NICKNAME", "SYM_NICKNAME", "MODEL_VAR", "MODEL_VAR_REF"):
        assert not hasattr(lc, gone), f"library_core must not export {gone}"


# -- 3D model matching --------------------------------------------------------


def _models(*names):
    return [Path(n) for n in names]


def test_match_model_matches_a_model_name_contained_in_the_footprint():
    models = _models("TPS2121RUXR.step", "OTHER.step")
    got = lc.match_model_for_footprint("IC_TPS2121RUXR", models)
    assert got == Path("TPS2121RUXR.step")


def test_match_model_prefers_an_exact_normalized_match_over_a_longer_containing_name():
    # The exact model must win over a longer name that merely contains the token,
    # else the wrong (less specific) 3D model is wired into the footprint.
    models = _models("R_0603.step", "XR_0603_CONNECTOR.step")
    got = lc.match_model_for_footprint("R_0603", models)
    assert got == Path("R_0603.step")


def test_match_model_matches_a_substring_either_direction():
    # footprint stem contains the model name.
    assert lc.match_model_for_footprint("IC_TPS2121RUXR", _models("TPS2121RUXR.step")) == Path(
        "TPS2121RUXR.step"
    )
    # model name contains the footprint stem.
    assert lc.match_model_for_footprint("TPS2121", _models("IC_TPS2121RUXR.step")) == Path(
        "IC_TPS2121RUXR.step"
    )


def test_match_model_returns_the_longest_match_when_several_are_contained():
    # Both normalize to a substring of "ictps2121ruxr"; the longer, more specific name
    # wins so a generic "tps2121" does not shadow the exact model.
    models = _models("TPS2121.step", "TPS2121RUXR.step")
    got = lc.match_model_for_footprint("IC_TPS2121RUXR", models)
    assert got == Path("TPS2121RUXR.step")


def test_match_model_ignores_models_shorter_than_four_normalized_chars():
    # "R_10" normalizes to "r10" (len 3) so it can never match, avoiding noise.
    assert lc.match_model_for_footprint("R_10k", _models("R_10.step")) is None


def test_match_model_ignores_a_footprint_stem_shorter_than_four_normalized_chars():
    # A short footprint token ("R10" -> "r10") must not grab an unrelated long model.
    assert lc.match_model_for_footprint("R10", _models("VAR100.step")) is None
    assert lc.match_model_for_footprint("C_1", _models("IC_100_HOUSING.step")) is None


def test_match_model_treats_a_none_or_blank_stem_as_no_match():
    assert lc.match_model_for_footprint(None, _models("nonexistent.step")) is None
    assert lc.match_model_for_footprint("", _models("TPS2121RUXR.step")) is None
    assert lc.match_model_for_footprint("IC_TPS2121RUXR", []) is None


def test_match_model_is_deterministic_regardless_of_candidate_order():
    # Two equally-good candidates (same normalized stem): the choice must not depend on
    # the order the caller happened to enumerate the directory in.
    a = lc.match_model_for_footprint("TPS2121", _models("TPS2121.wrl", "TPS2121.step"))
    b = lc.match_model_for_footprint("TPS2121", _models("TPS2121.step", "TPS2121.wrl"))
    assert a == b
