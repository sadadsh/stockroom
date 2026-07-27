"""Naming schemes, selected by NAME rather than by editing code.

The owner's requirement, verbatim: *"Import everything so we can change the way the data's
manipulated later (human naming scheme for example)"*. A naming scheme you have to edit a function
to change is not swappable - it is a code change plus a re-import, and re-importing is the thing
the sourced/derived split exists to make unnecessary.

So a scheme is DATA: a registered function keyed by name. Changing the library's names is
selecting a different key and re-deriving; nothing is re-fetched and nothing under `sourced/` is
touched. `Derived.derived_by` records the ruleset that produced a block, so a library can be swept
for parts still carrying the old naming instead of everything being re-derived blindly.

REJECTED (recorded so it is not re-proposed):

- **A format STRING** (`"{value} {tolerance} {package} {noun}"`). Tempting, and wrong for this
  data: a resistor names itself from Resistance + Tolerance while an IC names itself from its MPN,
  the noun is per-category, and a missing spec must drop its segment AND its separator rather than
  leaving "1% Resistor" with a hole. Every one of those is a conditional, so a template language
  would have to grow conditionals - at which point it is a worse programming language than Python
  with none of the tooling.
- **A per-category table in the config file.** That is `TITLE_REGISTRY` in
  `ingest/component_naming.py`, which already exists and is already the right shape. Duplicating
  it into config would fork the rule.

The registry starts with the two schemes that are genuinely wanted: the spec-aware human name that
`propose_component_name` already produces, and the bare MPN - which is not a toy entry, it is the
honest fallback for a library whose specs have not been pulled yet, and it makes the swap
observable in a test without inventing a third naming convention.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class NameInputs:
    """Everything a scheme may read. Deliberately a flat value object, not the record.

    A scheme must be a PURE function of derived-and-identity inputs, because its output lands in
    the derived block and the block has to be reproducible. Handing it the record would let a
    scheme read `assets` or `sources` and quietly make the name depend on which files happen to be
    attached - so a capture would change a part's name, and a re-derive on a fresh clone would
    produce a different one.
    """

    mpn: str = ""
    manufacturer: str = ""
    category: str = ""
    description: str = ""
    # Normalized specs, i.e. post-normalization: naming reads the same values the record shows.
    specs: dict | None = None

    def spec_bag(self) -> dict:
        return dict(self.specs or {})


NamingScheme = Callable[[NameInputs], str]


def _spec_aware(inputs: NameInputs) -> str:
    """The scheme in force today: a spec-aware human name ("1.1 kΩ ±1% 0603 Resistor").

    Delegates to `ingest.component_naming.propose_component_name`, which already holds the
    per-category noun and title-spec registry. Imported inside the function to keep this module
    free of an import cycle (the ingest package imports the model, which imports nothing here).
    """
    from stockroom.ingest.component_naming import propose_component_name

    return propose_component_name(
        inputs.category, inputs.spec_bag(), inputs.mpn, inputs.description
    )


def _mpn_only(inputs: NameInputs) -> str:
    """The bare manufacturer part number.

    The honest name for a part whose specs have not been pulled, and the scheme a person picks who
    wants the library to read like a BOM rather than like a catalogue.
    """
    return (inputs.mpn or "").strip()


def _manufacturer_mpn(inputs: NameInputs) -> str:
    """"Texas Instruments TPS62130RGTR" - unambiguous across manufacturers reusing a number."""
    maker = (inputs.manufacturer or "").strip()
    mpn = (inputs.mpn or "").strip()
    return f"{maker} {mpn}".strip()


SCHEMES: dict[str, NamingScheme] = {
    "spec-aware": _spec_aware,
    "mpn": _mpn_only,
    "manufacturer-mpn": _manufacturer_mpn,
}

# What a library uses when nothing says otherwise: the scheme the existing records were named by,
# so adopting the derive engine does not rename anybody's library as a side effect.
DEFAULT_SCHEME = "spec-aware"


class UnknownNamingScheme(Exception):
    """A scheme name nothing is registered under.

    LOUD, never a silent fall back to the default. A typo in a config key that quietly renamed a
    whole library to something the person did not ask for is exactly the kind of failure the
    re-derive is supposed to make safe, and a silent default would make it unsafe again.
    """


def get_scheme(name: str = "") -> NamingScheme:
    key = (name or DEFAULT_SCHEME).strip()
    scheme = SCHEMES.get(key)
    if scheme is None:
        known = ", ".join(sorted(SCHEMES))
        raise UnknownNamingScheme(f"unknown naming scheme {key!r}: registered schemes are {known}")
    return scheme


def scheme_names() -> tuple[str, ...]:
    return tuple(sorted(SCHEMES))
