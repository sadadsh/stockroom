"""The opened-component projection, under its historical name.

The projection itself lives in `stockroom.dossier`, split into focused modules. It was one file
here and outgrew that: the crude substring rule that grouped specifications applied the same
buckets to a resistor, a microcontroller and a connector, and no amount of extra substrings
could make one universal rule right for all three. That rule is replaced by a category schema
registry, which is data.

Nothing was forked. This is the same projection and the same route - `component_workspace` IS
`component_dossier` - so there is one presentation model rather than two competing ones. This
module exists only so that callers and tests that named it here keep working.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from stockroom.dossier import component_dossier
from stockroom.dossier.cad import REPRESENTATION_STATUSES
from stockroom.dossier.destinations import DATA_DESTINATIONS
from stockroom.dossier.vocabulary import DOSSIER_SCHEMA_VERSION, UNIVERSAL_GROUPS
from stockroom.enrich.schema import SOURCE_STATES

# The historical name for the dossier's schema version. Kept in step by assignment rather than
# by a second literal, so the two can never drift.
WORKSPACE_SCHEMA_VERSION = DOSSIER_SCHEMA_VERSION

SPEC_GROUPS = UNIVERSAL_GROUPS


def component_workspace(
    record,
    *,
    coverage: Mapping[str, Any] | None = None,
    now: str = "",
) -> dict[str, Any]:
    """The component dossier. See `stockroom.dossier.build.component_dossier`."""
    return component_dossier(record, coverage=coverage, now=now)


__all__ = [
    "DATA_DESTINATIONS",
    "REPRESENTATION_STATUSES",
    "SOURCE_STATES",
    "SPEC_GROUPS",
    "WORKSPACE_SCHEMA_VERSION",
    "component_dossier",
    "component_workspace",
]
