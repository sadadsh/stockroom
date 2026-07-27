"""Which of the four part classes a part belongs to. A TABLE, and deliberately timid.

`PartClass` has held four values since 2026-07-27 but only `PASSIVE` was ever constructed, so
`MECHANICAL` and `VIRTUAL` were unreachable in practice: `_v2_to_v3` maps everything that is not a
passive to `COMPONENT`. The owner's register already holds M3 mounting holes and a ring LED that
were BOTH kept out of the library by hand because they fitted neither of the two values that
existed. This is what makes those classes reachable.

WHY IT IS TIMID, and why that is the whole design. The class decides which files a part needs, so a
wrong answer is invisible and expensive in both directions:

  - misclassify a component as mechanical -> it stops asking for a symbol it genuinely needs, and
    the library reports it complete forever. That is the "CAD Incomplete" failure inverted, and
    strictly worse, because a missing gap is silent where a false gap is merely annoying.
  - misclassify a mechanical part as a component -> it asks for a symbol that cannot exist. Noisy,
    visible, and correctable in one click.

So the default is `COMPONENT` (the acquisition case), and a part is only moved off it on a
POSITIVE, specific signal. The spec's own warning is the measurement behind this: on 2026-07-27 a
package-vs-pad-count check reported 16 mismatches on the owner's library and ALL 16 were false
positives, because it read "SOT-23" as 23 pins. *"A false-positive machine is worse than no check."*

WHAT IT WILL NOT DO. It never overrides a class a human already set (`reclassify` returns None),
because a vendor taxonomy and a keyword are suggestions and a person's filing is a decision - the
same rule `refile_category` applies to categories.
"""

from __future__ import annotations

import re

from stockroom.model.part_class import DEFAULT_PART_CLASS, PartClass

# A signal is a whole-word regex over the part's category + description + MPN. Whole-word on
# purpose: substring matching is how "SOT-23" became 23 pins. `\bnut\b` must not fire on
# "connut", and `\bpin\b` must not fire on "pinout" - which is exactly why VIRTUAL does not
# look for "pin" at all.
#
# Ordered most-specific first. VIRTUAL before MECHANICAL because a "test point" is a pad on the
# board (mechanical-shaped) but has no BOM line, and the BOM line is the distinction that matters.
_RULES: tuple[tuple[PartClass, tuple[str, ...]], ...] = (
    (
        PartClass.VIRTUAL,
        (
            r"\bfiducial\b",
            r"\btest\s*point\b",
            r"\btestpoint\b",
            r"\blogo\b",
            r"\bsilkscreen\s+(mark|marker|artwork)\b",
            r"\bmounting\s+hole\b",  # a plain hole is drilled, not bought
        ),
    ),
    (
        PartClass.MECHANICAL,
        (
            r"\bstandoff\b",
            r"\bspacer\b",
            r"\bmachine\s+screw\b",
            r"\bself[-\s]tapping\s+screw\b",
            r"\bscrew\b",
            r"\bhex\s+nut\b",
            r"\bnut\b",
            r"\bwasher\b",
            r"\brivet\b",
            r"\bheat\s*sink\b",
            r"\bheatsink\b",
            r"\bthreaded\s+insert\b",
            r"\bcable\s+gland\b",
            r"\bbracket\b",
            r"\benclosure\b",
        ),
    ),
)

_COMPILED: tuple[tuple[PartClass, tuple[re.Pattern[str], ...]], ...] = tuple(
    (cls, tuple(re.compile(p, re.IGNORECASE) for p in pats)) for cls, pats in _RULES
)

# A part that is ELECTRICALLY functional is never mechanical or virtual, however its description
# reads. "Heatsink-mounted TO-220 regulator" contains "heatsink"; it is a regulator. This is the
# veto that stops the keyword table from being a false-positive machine, and it runs FIRST.
_ELECTRICAL_VETO = re.compile(
    r"\b(resistor|capacitor|inductor|diode|transistor|mosfet|regulator|converter|amplifier"
    r"|microcontroller|mcu|processor|memory|eeprom|flash|sram|dram|oscillator|crystal|resonator"
    r"|sensor|thermistor|led|photodiode|optocoupler|relay|switch|connector|header|receptacle"
    r"|transformer|fuse|varistor|transceiver|comparator|multiplexer|gate|buffer|driver|ic\b)",
    re.IGNORECASE,
)


def _haystack(*, mpn: str, category: str, description: str, specs: dict | None = None) -> str:
    bag = specs or {}
    extra = " ".join(
        str(bag.get(k, "")) for k in ("Product Category", "Category", "Type", "Product Type")
    )
    return " ".join(part for part in (category, description, extra, mpn) if part)


def classify(
    *,
    mpn: str = "",
    category: str = "",
    description: str = "",
    specs: dict | None = None,
) -> PartClass:
    """The class a part's own text supports, defaulting to COMPONENT.

    COMPONENT is the default rather than a "don't know" value because there is no fifth class and
    an unclassified part must show up as NEEDING WORK, not as excused. That mirrors
    `DEFAULT_PART_CLASS`, which exists for the same reason.
    """
    from stockroom.enrich.passive import detect_passive

    text = _haystack(mpn=mpn, category=category, description=description, specs=specs)

    # PASSIVE first, through the existing detector rather than a second keyword list: it decodes
    # real MPN families and is already proven against the owner's 68 passives. It takes category
    # and MPN only - deliberately not the description, which is where the false positives live
    # ("resistor network driver" is not a resistor).
    if detect_passive(mpn=mpn, category=category):
        return PartClass.PASSIVE

    if _ELECTRICAL_VETO.search(text):
        return DEFAULT_PART_CLASS

    for cls, patterns in _COMPILED:
        if any(p.search(text) for p in patterns):
            return cls

    return DEFAULT_PART_CLASS


def reclassify(record) -> PartClass | None:
    """The class an UNCLASSIFIED record should take, or None to leave it alone.

    The record-shaped twin of `classify`, and the important half is the guard: a record whose class
    is anything other than the default is NEVER touched. A person who marked a part mechanical, or
    an importer that already classified it, has made a decision; re-running the importer must not
    quietly overturn it. Same rule, and same reason, as `refile_category`.
    """
    current = getattr(record, "part_class", None)
    if current is not None and current is not DEFAULT_PART_CLASS:
        return None
    proposed = classify(
        mpn=getattr(record, "mpn", "") or "",
        category=getattr(record, "category", "") or "",
        description=getattr(record, "description", "") or "",
        specs=getattr(record, "specs", {}) or {},
    )
    return proposed if proposed is not current else None
