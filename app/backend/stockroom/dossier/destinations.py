"""Every canonical `PartRecord` field, and the ONE place the product presents it.

A field with no entry here is a field the product forgot. `tests/backend/test_dossier.py` fails
on it, which is the whole mechanism: adding a field to the record without deciding where a
person reads it is caught by a test rather than discovered as an absence months later.

`diagnostics` is a real destination - technical truth an owner can still reach - but it is never
a dumping ground for something a person would look for somewhere else.
"""

from __future__ import annotations

DATA_DESTINATIONS: dict[str, str] = {
    "id": "identity",
    "display_name": "identity.displayName",
    "mpn": "identity.mpn",
    "manufacturer": "identity.manufacturer",
    "category": "identity.category",
    "part_class": "identity.partClass",
    "value": "identity.value",
    "description": "qualitySummary.description",
    "specs": "specificationGroups",
    "tags": "identity.tags",
    "requires_override": "qualitySummary.attention",
    "assets": "cadAssets",
    "cad_variants": "cadAssets.kinds",
    "datasheet": "documents.items",
    "documents": "documents.items",
    "manufacturer_page": "identity.manufacturerPage",
    "overrides": "provenance.manualOverrides",
    "purchase": "distributorOffers",
    "catalog": "relatedParts",
    "provider_assertions": "cadSourceCoverage.rows",
    # Held apart from `provider_assertions` on purpose, and read in a different place. An
    # assertion is what a person OBSERVED about a provider's coverage and belongs in the
    # comparison row it corrects; the preference is what a person DECIDED about where this
    # component's CAD comes from, and it is the CAD column's own statement about the set.
    "cad_preference": "cadAssets.preference",
    "enrichment": "provenance.sources",
    "alternates": "provenance.raw",
    "sources": "provenance.sources",
    "provenance": "revisions",
    "hashes": "diagnostics.hashes",
    "derived_at": "revisions",
    "derived_by": "diagnostics",
    "derived_extra": "diagnostics.unknownKeys",
    "schema_version": "diagnostics.recordSchemaVersion",
    "extra": "diagnostics.unknownKeys",
}

__all__ = ["DATA_DESTINATIONS"]
