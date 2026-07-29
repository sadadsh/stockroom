"""Trust: STORE THE EVIDENCE, DERIVE THE VERDICT (spec decision D2).

An asset records what checks RAN and what each MEASURED. PASS / FAIL / UNKNOWN is computed
from those facts on read and is NEVER stored, so tightening a check re-judges the whole
library with no re-audit and a verdict can never disagree with its own evidence.

UNKNOWN is mandatory: a check that could not run must never claim either outcome. The
measured cost of getting that wrong is on record - a package-vs-pad-count check reported 16
mismatches on the owner's library and ALL 16 were false positives.
"""

import json

from stockroom.model.asset import Asset, AssetOrigin, AssetRef
from stockroom.model.part import PartRecord
from stockroom.model.trust import (
    AssetCheck,
    Verdict,
    asset_verdict,
    check_verdict,
    record_verdict,
    tool_verdict,
    verdict_for,
)


def _check(**kw) -> AssetCheck:
    kw.setdefault("check", "pins_vs_datasheet")
    kw.setdefault("against", "rev C")
    return AssetCheck(**kw)


# ------------------------------------------------- one check


def test_a_check_whose_measurement_matches_passes():
    assert check_verdict(_check(measured=16, expected=16)) is Verdict.PASS


def test_a_check_whose_measurement_disagrees_fails():
    assert check_verdict(_check(measured=14, expected=16)) is Verdict.FAIL


def test_a_check_that_could_not_MEASURE_is_unknown_never_pass_and_never_fail():
    assert check_verdict(_check(measured=None, expected=16)) is Verdict.UNKNOWN


def test_a_check_with_no_AUTHORITY_to_compare_against_is_unknown():
    assert check_verdict(_check(measured=16, expected=None)) is Verdict.UNKNOWN


def test_zero_is_a_real_measurement_and_not_a_missing_one():
    assert check_verdict(_check(measured=0, expected=0)) is Verdict.PASS
    assert check_verdict(_check(measured=0, expected=16)) is Verdict.FAIL


def test_a_numeric_check_honours_its_declared_tolerance():
    # The tolerance is a FACT about how the check was run (a courtyard bbox is measured in
    # mm), not a verdict, so it is stored with the evidence.
    assert check_verdict(_check(measured=4.02, expected=4.0, tolerance=0.05)) is Verdict.PASS
    assert check_verdict(_check(measured=4.2, expected=4.0, tolerance=0.05)) is Verdict.FAIL


def test_malformed_or_non_finite_numeric_evidence_fails_closed():
    malformed = AssetCheck.from_dict(
        {
            "check": "courtyard_vs_body",
            "measured": 4.0,
            "expected": 4.0,
            "tolerance": "not-a-number",
        }
    )
    assert check_verdict(malformed) is Verdict.UNKNOWN
    assert check_verdict(_check(measured=float("nan"), expected=4.0)) is Verdict.UNKNOWN
    assert check_verdict(_check(measured=4.0, expected=float("inf"))) is Verdict.UNKNOWN
    assert check_verdict(_check(measured=4.02, expected=4.0)) is Verdict.FAIL


def test_a_string_check_compares_exactly():
    assert check_verdict(_check(measured="QFN-16", expected="QFN-16")) is Verdict.PASS
    assert check_verdict(_check(measured="SOT-23", expected="SOT-23-5")) is Verdict.FAIL


# ------------------------------------------------- rolling up


def test_no_evidence_is_UNKNOWN_never_pass():
    # "Trust is not presence." An asset nobody has checked is not a trusted asset.
    assert verdict_for([]) is Verdict.UNKNOWN


def test_every_check_passing_is_a_pass():
    assert verdict_for([_check(measured=1, expected=1), _check(measured=2, expected=2)]) is Verdict.PASS


def test_one_failure_outranks_every_pass():
    assert verdict_for([_check(measured=1, expected=1), _check(measured=2, expected=3)]) is Verdict.FAIL


def test_one_failure_outranks_an_unknown_too():
    assert verdict_for([_check(measured=None, expected=3), _check(measured=2, expected=3)]) is Verdict.FAIL


def test_a_gap_in_the_evidence_downgrades_a_pass_to_unknown():
    assert verdict_for([_check(measured=1, expected=1), _check(measured=None, expected=3)]) is Verdict.UNKNOWN


# ------------------------------------------------- assets and records


def _rec(**kw) -> PartRecord:
    return PartRecord(id="x", display_name="n", category="ICs", **kw)


def test_an_assets_verdict_comes_from_its_own_checks():
    a = Asset(ref=AssetRef(lib="SR-ICs", name="A"), checks=[_check(measured=16, expected=16)])
    assert asset_verdict(a) is Verdict.PASS
    a.checks.append(_check(check="footprint_pads", measured=14, expected=16))
    assert asset_verdict(a) is Verdict.FAIL, "adding evidence must re-judge with no re-audit"


def test_a_tools_verdict_is_the_worst_of_the_assets_it_actually_HAS():
    rec = _rec()
    kicad = rec.assets_for("kicad")
    kicad.symbol = Asset(ref=AssetRef(lib="SR-ICs", name="A"), checks=[_check(measured=16, expected=16)])
    assert tool_verdict(rec, "kicad") is Verdict.PASS
    kicad.footprint = Asset(
        ref=AssetRef(lib="SR-ICs", name="A"),
        checks=[_check(check="pads_vs_package", measured=14, expected=16)],
    )
    assert tool_verdict(rec, "kicad") is Verdict.FAIL


def test_an_ABSENT_asset_is_a_presence_question_not_a_trust_one():
    # Section 3 of the spec is titled "TRUST IS NOT PRESENCE". A part with nothing attached
    # is not UNTRUSTED, it is incomplete - and `missing_assets` is what answers that.
    rec = _rec()
    assert tool_verdict(rec, "kicad") is Verdict.UNKNOWN
    assert record_verdict(rec) is Verdict.UNKNOWN


def test_a_record_verdict_spans_every_tool():
    rec = _rec()
    rec.assets_for("kicad").symbol = Asset(
        ref=AssetRef(lib="SR-ICs", name="A"), checks=[_check(measured=16, expected=16)]
    )
    assert record_verdict(rec) is Verdict.PASS
    rec.assets_for("altium").symbol = Asset(
        ref=AssetRef(lib="a.SchLib", name="A"),
        checks=[_check(measured=2, expected=16)],
    )
    assert record_verdict(rec) is Verdict.FAIL


# ------------------------------------------------- the verdict is never persisted


def test_no_verdict_is_ever_written_to_the_record():
    rec = _rec()
    rec.assets_for("kicad").symbol = Asset(
        ref=AssetRef(lib="SR-ICs", name="A"),
        origin=AssetOrigin(vendor="ultralibrarian", url="u", captured_at="2026-07-27T00:00:00Z"),
        checks=[_check(measured=16, expected=16)],
    )
    blob = json.loads(rec.dumps())
    symbol = blob["assets"]["kicad"]["symbol"]
    assert set(symbol) == {"ref", "origin", "checks"}
    assert "verdict" not in json.dumps(symbol)
    assert "trust" not in json.dumps(symbol)


def test_checks_round_trip_as_facts():
    rec = _rec()
    rec.assets_for("kicad").symbol = Asset(
        ref=AssetRef(lib="SR-ICs", name="A"),
        checks=[_check(measured=16, expected=16, checked_at="2026-07-27T00:00:00Z")],
    )
    back = PartRecord.loads(rec.dumps())
    got = back.assets_for("kicad").symbol.checks[0]
    assert got.check == "pins_vs_datasheet"
    assert got.measured == 16 and got.expected == 16
    assert got.against == "rev C" and got.checked_at == "2026-07-27T00:00:00Z"
    assert asset_verdict(back.assets_for("kicad").symbol) is Verdict.PASS


def test_a_check_key_from_a_newer_build_survives_a_round_trip():
    c = AssetCheck.from_dict({"check": "x", "measured": 1, "expected": 1, "confidence": "high"})
    assert c.to_dict()["confidence"] == "high"
