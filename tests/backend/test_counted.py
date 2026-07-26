"""A number and its noun agree, in the messages the backend writes for a person to read.

The frontend already has this (`app/frontend/src/lib/plural.ts`) after the status bar shipped
"1 Components" on 10 of 12 captured screens. The backend then wrote `10 component(s)` into the
project Buildability warning, `library(s)` into the Altium install result, and `copper layer(s)`
into a fab preset error - the same carelessness, in the half nobody had checked.
"""
from __future__ import annotations

import pytest

from stockroom.text import counted, plural


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
