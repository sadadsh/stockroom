"""A number and its noun agree, in the messages the backend writes for a person to read.

The frontend already has this (`app/frontend/src/lib/plural.ts`) after the status bar shipped
"1 Components" on 10 of 12 captured screens. The backend then wrote `10 component(s)` into the
project Buildability warning, `library(s)` into the Altium install result, and `copper layer(s)`
into a fab preset error - the same carelessness, in the half nobody had checked.
"""
from __future__ import annotations

import pytest

from stockroom.text import counted, fullest_name, is_abbreviation_of, plural


@pytest.mark.parametrize(
    "count, one, many, expect",
    [
        (1, "component", None, "component"),
        (0, "component", None, "components"),
        (2, "component", None, "components"),
        (1, "library", "libraries", "library"),
        (3, "library", "libraries", "libraries"),
    ],
)
def test_plural_agrees_with_its_count(count, one, many, expect):
    assert plural(count, one, many) == expect


def test_counted_puts_the_number_in_front_of_the_agreeing_noun():
    assert counted(1, "component") == "1 component"
    assert counted(2, "component") == "2 components"
    assert counted(0, "board") == "0 boards"


def test_counted_groups_a_big_number_because_an_ungrouped_one_reads_as_a_part_number():
    # Same reasoning as the frontend helper: a four-digit library is reachable and `1204` sitting
    # in a line full of MPNs reads as another MPN.
    assert counted(1204, "component") == "1,204 components"


def test_an_irregular_plural_is_passed_explicitly_never_guessed():
    # Deliberately NOT a general English inflector. This app counts a small known set of nouns.
    assert counted(2, "library", "libraries") == "2 libraries"


# --- manufacturer name forms -------------------------------------------------------------
#
# There is NO industry standard for manufacturer names: Texas Instruments is written TI, T.I.,
# TXN, Texas, Tex and TexasInst across databases, and every component search engine truncates
# differently. So this never INVENTS a name - it only decides, between two answers real sources
# actually gave, whether one is a shorter spelling of the other.

def test_initials_are_an_abbreviation_of_the_name_they_stand_for():
    assert is_abbreviation_of("TI", "Texas Instruments")
    assert is_abbreviation_of("t.i.", "Texas Instruments")  # punctuation and case ignored


def test_a_leading_fragment_INSIDE_THE_FIRST_WORD_is_an_abbreviation():
    assert is_abbreviation_of("ST", "STMicroelectronics")


def test_a_name_plus_a_separate_word_is_NOT_treated_as_an_abbreviation():
    """The case this rule deliberately declines to judge.

    "NXP" is the whole first word of "NXP Semiconductors", exactly as "Yageo" is of "Yageo
    Corporation". One of those trailing words reads as a category and one as a legal suffix,
    and NOTHING in the data distinguishes them - the external research found no standard to
    appeal to. So neither is folded, and the documented slot rule (first source wins) stands.

    This assertion started out the other way round, asserting NXP SHOULD fold. That was an
    opinion with no evidence behind it, and writing the Yageo case is what exposed it.
    """
    assert not is_abbreviation_of("NXP", "NXP Semiconductors")
    assert not is_abbreviation_of("Yageo", "Yageo Corporation")


def test_two_genuinely_different_makers_are_never_folded_together():
    assert not is_abbreviation_of("TI", "Toshiba")
    assert not is_abbreviation_of("ON", "Texas Instruments")
    # TXN is TI's ticker, NOT its initials and not a prefix of its name. Nothing here can prove
    # they are the same company, so nothing here claims it.
    assert not is_abbreviation_of("TXN", "Texas Instruments")


def test_a_full_name_is_never_treated_as_an_abbreviation_of_a_longer_one():
    # The corporate-suffix trap: preferring "longest" would turn every name into its
    # "... Incorporated" form. Only a SHORT, single-token answer can be an abbreviation.
    assert not is_abbreviation_of("Texas Instruments", "Texas Instruments Incorporated")


def test_fullest_name_picks_the_spelled_out_answer_among_what_sources_said():
    assert fullest_name(["TI", "Texas Instruments"]) == "Texas Instruments"
    assert fullest_name(["Texas Instruments", "TI"]) == "Texas Instruments"
    assert fullest_name(["ST", "STMicroelectronics"]) == "STMicroelectronics"


def test_fullest_name_keeps_the_first_answer_when_nothing_proves_a_relationship():
    # Two different companies, or two spellings we cannot relate: the slot rule (first source
    # wins, spec 6.1) stands. This never arbitrates between real disagreements.
    assert fullest_name(["Toshiba", "TI"]) == "Toshiba"
    assert fullest_name(["TXN", "Texas Instruments"]) == "TXN"
    assert fullest_name([]) == ""
    assert fullest_name(["", "TI"]) == "TI"
