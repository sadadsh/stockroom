"""The DERIVED block: everything about a part that is recomputable from `sourced/`.

Spec section 9. The governing sentence is the owner's:

    "the new schema would allow us to manipulate the data after without losing what we
     imported"

So `display_name`, `value`, `category`, `description` and the normalized `specs` are grouped
into one block and marked disposable BY CONSTRUCTION: dropping the whole block and recomputing
it must reproduce the record. A naming-scheme change is then a re-derive, not a re-import, and
never a data loss.

What that buys, and what it costs to get wrong: the pre-v3 schema stored these flat beside the
identity fields with no boundary between them, and normalized spec keys and values at IMPORT
time - so the winning value AS THE SOURCE RETURNED IT was gone forever from all 158 of the
owner's records. Normalization is legitimate HERE, on the derived side, precisely because the
raw winner now survives in `sourced/`.

`derived_by` records WHICH ruleset produced the block, so a library can be swept for parts
still carrying an older derivation instead of everything being re-derived blindly.

PRIOR ART (checked before writing, 2026-07-27): this is the materialized-view / build-artifact
pattern - a derived table stamped with the transformation version that produced it (dbt models,
Bazel action keys, Rust's `Cargo.lock` build fingerprints). The stamp-the-producer idea is taken
from those. REJECTED as machinery: a full lineage/DAG system, because there is exactly one
derivation step here (sourced -> derived) and a dependency graph for one edge is cost with no
information; and a content hash of the inputs as the stamp, because the useful question is
"which RULES ran", not "did the bytes change" - the bytes changing is a re-pull, which is
already recorded per source in `sources`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The derivation ruleset version. Bump it when a change to the derivation RULES would produce
# different output from unchanged evidence (a new naming scheme, a different category
# assignment, a changed spec-normalization table).
#
# Deliberately NOT tied to the record's `schema_version`, and starting at 1 rather than 3. They
# version different things and move for different reasons: a naming-scheme change bumps this
# and not the schema, and adding a field bumps the schema and not this. The spec's illustrative
# JSON showed "rules@3" as an example value in a section that lists the ruleset version under
# "still to decide"; this is that decision.
# 1 -> 2 (2026-07-27): descriptions are cleaned at derive time. Mouser's catalogue tail is cut
# and its HTML entities decoded (enrich/mouser.py::clean_mouser_description), and DigiKey's
# readable `DetailedDescription` outranks its abbreviated listing string. Same evidence, different
# output, so the stamp moves.
RULESET_VERSION = 2
DERIVED_BY = f"rules@{RULESET_VERSION}"

# Every field of the derived block, in one place, so the record model, the serializer and the
# drift test all read the same list. Adding a derived field means adding it HERE.
DERIVED_FIELDS: tuple[str, ...] = (
    "display_name",
    "value",
    "category",
    "description",
    "specs",
    "derived_at",
    "derived_by",
)


@dataclass
class Derived:
    """The recomputable half of a part record.

    Nothing in here is authored by a human and nothing in here is identity. A re-derive
    replaces this object wholesale; `id`, `mpn`, `manufacturer` and `part_class` are untouched
    by it.
    """

    # What a person calls this part. Carries the human naming scheme, which is exactly why the
    # id must not: the scheme is expected to change.
    display_name: str = ""
    # The schematic/BOM Value: a passive's parametric value, an active's MPN.
    value: str = ""
    category: str = ""
    description: str = ""
    # Normalized spec keys and values. Normalization belongs HERE, at derive time, never at
    # import time.
    specs: dict = field(default_factory=dict)
    # When this block was computed, and by which ruleset.
    derived_at: str = ""
    derived_by: str = ""
    # Keys a newer build wrote into the block, kept verbatim and re-emitted.
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            **self.extra,
            "display_name": self.display_name,
            "value": self.value,
            "category": self.category,
            "description": self.description,
            "specs": dict(self.specs),
            "derived_at": self.derived_at,
            "derived_by": self.derived_by,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Derived":
        known = set(DERIVED_FIELDS)
        return cls(
            display_name=d.get("display_name", ""),
            value=d.get("value", ""),
            category=d.get("category", ""),
            description=d.get("description", ""),
            specs=dict(d.get("specs") or {}),
            derived_at=d.get("derived_at", ""),
            derived_by=d.get("derived_by", ""),
            extra={k: v for k, v in d.items() if k not in known},
        )
