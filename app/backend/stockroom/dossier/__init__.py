"""The component dossier: the one normalized presentation read model of a `PartRecord`.

Split into focused modules rather than one file, because the decisions are genuinely different
kinds of decision and each of them is worth reading on its own:

    vocabulary      the closed sets of states, groups and value types everything speaks in
    fields          the canonical field registry a raw distributor key resolves through
    categories      what a component of THIS kind is described by, and how complete means
    units           one comparable magnitude behind every engineering value
    precedence      which source wins a field, and what happens to the answers that lose
    specifications  the canonical specification record and the category-aware grouping
    decisions       the reviewed overrides and preferred sources a person may record
    documents       typed resources, and which datasheet a person should actually open
    manufacturer    the official page, held apart from every distributor listing
    offers          distributor offers, normalized so nothing downstream parses a payload
    related         related parts, each carrying why it is related
    cad             what the part holds per EDA tool, with source/provider/format kept apart
    revisions       the dated events the record can prove
    raw             the three levels at which source data is preserved
    build           the assembly, and the only entry point

`stockroom.workspace` re-exports the entry point under its historical name.
"""

from stockroom.dossier.build import component_dossier
from stockroom.dossier.cad import REPRESENTATION_STATUSES
from stockroom.dossier.categories import (
    BASE_SCHEMA,
    CATEGORY_SCHEMAS,
    CategorySchema,
    resolve_schema,
)
from stockroom.dossier.decisions import (
    UnknownSpecification,
    UnpinnableSource,
    canonical_key,
    clear_override,
    clear_preferred_source,
    set_override,
    set_preferred_source,
    sourced_candidates,
)
from stockroom.dossier.destinations import DATA_DESTINATIONS
from stockroom.dossier.documents import (
    DOCUMENT_TYPES,
    find_document,
    preferred_datasheet,
)
from stockroom.dossier.fields import FIELDS, FieldDefinition, field_for
from stockroom.dossier.manufacturer import manufacturer_page
from stockroom.dossier.offers import build_offers, manufacturer_status, supply_summary
from stockroom.dossier.precedence import SOURCE_TIERS, source_tier
from stockroom.dossier.specifications import build_specifications
from stockroom.dossier.vocabulary import (
    APPLICABILITY_STATES,
    CONFLICT_STATES,
    DOSSIER_SCHEMA_VERSION,
    IMPORTANCE_LEVELS,
    UNIVERSAL_GROUPS,
    VALUE_TYPES,
    VERIFICATION_STATES,
)

__all__ = [
    "APPLICABILITY_STATES",
    "BASE_SCHEMA",
    "CATEGORY_SCHEMAS",
    "CONFLICT_STATES",
    "DATA_DESTINATIONS",
    "DOCUMENT_TYPES",
    "DOSSIER_SCHEMA_VERSION",
    "FIELDS",
    "IMPORTANCE_LEVELS",
    "REPRESENTATION_STATUSES",
    "SOURCE_TIERS",
    "UNIVERSAL_GROUPS",
    "VALUE_TYPES",
    "VERIFICATION_STATES",
    "CategorySchema",
    "FieldDefinition",
    "UnknownSpecification",
    "UnpinnableSource",
    "build_offers",
    "build_specifications",
    "canonical_key",
    "clear_override",
    "clear_preferred_source",
    "component_dossier",
    "field_for",
    "find_document",
    "manufacturer_page",
    "manufacturer_status",
    "preferred_datasheet",
    "resolve_schema",
    "set_override",
    "set_preferred_source",
    "source_tier",
    "sourced_candidates",
    "supply_summary",
]
