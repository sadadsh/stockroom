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


# --- manufacturer name forms ---------------------------------------------------------------
#
# RESEARCHED FIRST (2026-07-26, external): there is NO industry standard for manufacturer names.
# Texas Instruments is written TI, T.I., TXN, Texas, Tex and TexasInst across component
# databases, and every search engine truncates to a different field length. A general "expand
# the abbreviation" table is therefore a liability we would own forever and could never finish.
#
# So this NEVER invents a name. It only answers one narrow question about two answers REAL
# SOURCES gave for one part: is this one a shorter spelling of that one? When the answer is yes
# the spelled-out form takes the slot; when it cannot be proven, the first source keeps it
# (spec 6.1). A pair we cannot relate - "TXN" against "Texas Instruments" - is left alone, which
# is the honest outcome: nothing in the data proves they are the same company.

_ABBREVIATION_MAX_LEN = 5


def _letters(text: str) -> str:
    return "".join(ch for ch in str(text).lower() if ch.isalnum())


def is_abbreviation_of(short: str, long: str) -> bool:
    """True when `short` is provably a shorter spelling of `long`.

    Two proofs, both exact:
      * `short` is the INITIALS of `long`'s words ("TI" / "Texas Instruments"), or
      * `long` begins with `short` ("ST" / "STMicroelectronics").

    Only a SHORT, single-token candidate qualifies. That is what keeps the corporate-suffix trap
    shut: "Texas Instruments" must never be read as an abbreviation of "Texas Instruments
    Incorporated", or every maker would drift toward its longest legal form.
    """
    s, ln = str(short).strip(), str(long).strip()
    if not s or not ln or len(_letters(s)) > _ABBREVIATION_MAX_LEN or " " in s:
        return False
    s_letters, l_letters = _letters(s), _letters(ln)
    if s_letters == l_letters:
        return False
    # PREFIX proof, and it must continue INSIDE the first word: "ST" -> "STMicroelectronics".
    # Requiring the same word is what shuts the suffix trap. "Yageo" is the whole first word of
    # "Yageo Corporation", and "NXP" the whole first word of "NXP Semiconductors" - in both the
    # longer form only appends a separate word, and NOTHING in the data says whether that word
    # is a legal suffix worth dropping or a name worth keeping. Those are left alone rather than
    # arbitrated: the first source keeps the slot, which is the documented rule anyway.
    first_word = _letters(ln.split()[0])
    if first_word.startswith(s_letters) and first_word != s_letters:
        return True
    # INITIALS proof: "TI" -> "Texas Instruments".
    initials = "".join(word[0] for word in ln.split() if word)
    return _letters(initials) == s_letters and len(ln.split()) > 1


def fullest_name(candidates) -> str:
    """The most spelled-out of `candidates`, where "most spelled-out" is PROVEN, not guessed.

    Returns the first non-empty candidate unless another candidate proves it to be its own
    abbreviation. Real disagreements ("Toshiba" against "TI") are never arbitrated here.
    """
    names = [str(c).strip() for c in candidates if str(c).strip()]
    if not names:
        return ""
    best = names[0]
    for other in names[1:]:
        if is_abbreviation_of(best, other):
            best = other
    return best
