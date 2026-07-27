"""The part id scheme: `slug(mpn) + "-" + sha256(mpn)[:4]`.

Decided in `docs/specs/2026-07-27-owner-spec-complete-trusted-library.md` section 9. The id
is a FILENAME and a git path, so it must be stable forever, unique, Windows-safe, and a PURE
function of something immutable.

The collision it exists to prevent is REAL and in the owner's own library: `MAX6817EUT+T` and
`MAX6817EUT-T` both slug to the same stem, and a filename collision silently MERGES two parts.
"""

import hashlib

import pytest

from stockroom.model.part_id import (
    FINGERPRINT_LEN,
    WINDOWS_RESERVED_STEMS,
    is_reserved_stem,
    is_valid_part_id,
    make_part_id,
    mpn_fingerprint,
    part_id_matches,
    slug_mpn,
)


def test_the_id_is_the_slug_plus_a_four_hex_fingerprint_of_the_exact_mpn():
    assert make_part_id("TPS62130RGTR") == "tps62130rgtr-" + hashlib.sha256(
        b"TPS62130RGTR"
    ).hexdigest()[:4]


def test_the_fingerprint_is_four_lowercase_hex_characters():
    fp = mpn_fingerprint("TPS62130RGTR")
    assert len(fp) == FINGERPRINT_LEN == 4
    assert all(c in "0123456789abcdef" for c in fp)


def test_the_owners_real_collision_produces_two_different_ids():
    # This is the measured case from the spec: slugging is LOSSY, `+` and `-` both fold to
    # the same separator, and the owner OWNS MAX6817EUT+T.
    plus = make_part_id("MAX6817EUT+T")
    dash = make_part_id("MAX6817EUT-T")
    assert slug_mpn("MAX6817EUT+T") == slug_mpn("MAX6817EUT-T"), "the stems really do collide"
    assert plus != dash, "the fingerprint must separate two parts a bare slug would merge"
    assert plus.startswith("max6817eut-t-") and dash.startswith("max6817eut-t-")


def test_the_id_is_a_pure_function_of_the_mpn_and_never_drifts():
    assert make_part_id("TPS62130RGTR") == make_part_id("TPS62130RGTR")
    # Manufacturer is deliberately NOT in the id ("Texas Instruments" vs "TI" varies by
    # source), so nothing but the MPN can move it.
    assert make_part_id("TPS62130RGTR") != make_part_id("tps62130rgtr")


def test_the_id_is_lowercase_a_to_z_0_to_9_and_hyphen_only():
    for mpn in ("TPS62130RGTR", "MAX6817EUT+T", "ERJ-P03F1101V", "M3x8", "103AT-2", "C_0402"):
        part_id = make_part_id(mpn)
        assert set(part_id) <= set("abcdefghijklmnopqrstuvwxyz0123456789-"), part_id
        assert is_valid_part_id(part_id), part_id


def test_an_mpn_that_slugs_to_nothing_still_gets_a_unique_id():
    # Unicode-only or punctuation-only input must not produce an empty filename, and two
    # different such MPNs must not collide on the fallback stem.
    a, b = make_part_id("+++"), make_part_id("///")
    assert a.startswith("part-") and b.startswith("part-")
    assert a != b
    assert is_valid_part_id(a)


# ------------------------------------------------- Windows reserved stems


def test_the_reserved_stem_set_is_the_documented_windows_one():
    assert {"con", "prn", "aux", "nul"} <= WINDOWS_RESERVED_STEMS
    for n in range(10):
        assert f"com{n}" in WINDOWS_RESERVED_STEMS
        assert f"lpt{n}" in WINDOWS_RESERVED_STEMS
    assert is_reserved_stem("CON") and is_reserved_stem("com1") and is_reserved_stem("LPT9")
    assert not is_reserved_stem("con1") and not is_reserved_stem("connector")


def test_a_reserved_stem_can_never_reach_a_filename():
    # The library is a Windows-first git checkout, so `CON.json` is unopenable there.
    for mpn in ("CON", "PRN", "AUX", "NUL", "COM1", "LPT9"):
        part_id = make_part_id(mpn)
        assert not is_reserved_stem(part_id.split("-")[0]), part_id
        assert is_valid_part_id(part_id)


def test_is_valid_part_id_rejects_what_a_filename_cannot_carry():
    assert not is_valid_part_id("")
    assert not is_valid_part_id("TPS62130")  # uppercase
    assert not is_valid_part_id("tps_62130")  # underscore is not in the alphabet
    assert not is_valid_part_id("tps/62130")
    assert not is_valid_part_id("-tps62130")
    assert not is_valid_part_id("tps62130-")
    assert not is_valid_part_id("con")  # a bare reserved stem
    assert not is_valid_part_id("..")


# ------------------------------------------------- verification


def test_part_id_matches_detects_an_id_that_no_longer_derives_from_its_mpn():
    assert part_id_matches(make_part_id("TPS62130RGTR"), "TPS62130RGTR")
    assert not part_id_matches(make_part_id("TPS62130RGTR"), "TPS62130RGT")


def test_a_hand_edited_fingerprint_is_caught():
    real = make_part_id("TPS62130RGTR")
    tampered = real[:-1] + ("0" if real[-1] != "0" else "1")
    assert not part_id_matches(tampered, "TPS62130RGTR")


def test_make_part_id_refuses_a_blank_mpn():
    # A part with no MPN has no stable identity, so silently inventing one would hand out an
    # id that changes the moment the MPN arrives.
    with pytest.raises(ValueError):
        make_part_id("")
    with pytest.raises(ValueError):
        make_part_id("   ")
