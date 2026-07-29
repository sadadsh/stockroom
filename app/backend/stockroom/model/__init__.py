"""Pure data layer: category taxonomy and the part record. No IO."""

from stockroom.model.asset import Asset, AssetOrigin, AssetRef, EdaAssets
from stockroom.model.cad_variant import (
    CAD_VARIANT_ROLE_MAP,
    CadVariantArtifactPointer,
    CadVariantPointer,
    CadVariantSelections,
)
from stockroom.model.category import (
    CATEGORIES,
    category_footprint_lib,
    category_nickname,
    category_symbol_lib,
    is_valid_category,
    slugify,
)
from stockroom.model.derived import DERIVED_BY, DERIVED_FIELDS, Derived
from stockroom.model.part import (
    KICAD_MIRROR_FIELDS,
    SCHEMA_VERSION,
    Datasheet,
    EnrichmentField,
    Hashes,
    PartRecord,
    Provenance,
    Purchase,
    UnmigratableRecord,
    asset_present,
    migrate_record,
    new_part_id,
    tool_assets_ready,
    tool_place_ready,
)
from stockroom.model.part_class import PartClass, RequirementOverride
from stockroom.model.part_id import is_valid_part_id, make_part_id, part_id_matches
from stockroom.model.sourced import SourceEntry
from stockroom.model.trust import AssetCheck, Verdict, asset_verdict, record_verdict

__all__ = [
    "CATEGORIES",
    "DERIVED_BY",
    "DERIVED_FIELDS",
    "KICAD_MIRROR_FIELDS",
    "SCHEMA_VERSION",
    "Asset",
    "AssetCheck",
    "AssetOrigin",
    "AssetRef",
    "CAD_VARIANT_ROLE_MAP",
    "CadVariantArtifactPointer",
    "CadVariantPointer",
    "CadVariantSelections",
    "Datasheet",
    "Derived",
    "EdaAssets",
    "EnrichmentField",
    "Hashes",
    "PartClass",
    "PartRecord",
    "Provenance",
    "Purchase",
    "RequirementOverride",
    "SourceEntry",
    "UnmigratableRecord",
    "Verdict",
    "asset_present",
    "asset_verdict",
    "category_footprint_lib",
    "category_nickname",
    "category_symbol_lib",
    "is_valid_category",
    "is_valid_part_id",
    "make_part_id",
    "migrate_record",
    "new_part_id",
    "part_id_matches",
    "record_verdict",
    "slugify",
    "tool_assets_ready",
    "tool_place_ready",
]
