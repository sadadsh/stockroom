"""Human-readable text the backend writes for a person to READ, not for a machine to parse.

Kept deliberately tiny and Qt-free. The frontend twin is `app/frontend/src/lib/plural.ts`; the
two are separate on purpose (one is what the API says, one is what the SPA renders) and they
agree on semantics so a count never changes shape as it crosses the wire.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations


def plural(count: int, one: str, many: str | None = None) -> str:
    """The form of `one` that agrees with `count`.

    Deliberately NOT a general English inflector: this app counts a small, known set of nouns and
    a clever rule engine serving five words is a liability. An irregular plural is passed
    explicitly (`plural(2, "library", "libraries")`).
    """
    return one if count == 1 else (many if many is not None else f"{one}s")


def counted(count: int, one: str, many: str | None = None) -> str:
    """"1 component" / "2 components", with the number grouped.

    Grouped because a four-digit library is reachable and a bare `1204` sitting in a line full of
    manufacturer part numbers reads as another part number.
    """
    return f"{count:,} {plural(count, one, many)}"


def have(count: int) -> str:
    """"has" for exactly one, "have" for every other count.

    A noun that agrees with its number in front of a verb that does not ("1 components have")
    only moves the mistake one word to the right.
    """
    return "has" if count == 1 else "have"


def is_are(count: int) -> str:
    """"is" for exactly one, "are" for every other count. Sibling of `have`."""
    return "is" if count == 1 else "are"
