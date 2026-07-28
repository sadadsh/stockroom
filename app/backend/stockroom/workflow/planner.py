"""Deterministic per-item stage planning for the next Stockroom workflow.

One item and one thousand items receive this exact same DAG.  Provider and
existing-evidence work fans out after the exact-identity/deduplication gate.
Tool-neutral reconciliation and definition feed both EDA builds, whose native
readbacks join at cross-EDA verification before catalog generation and publish.

This module describes dependencies only.  Workers, provider policies, artifact
generation, and live-library mutation remain later adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

WORKFLOW_GRAPH_VERSION = 1


class StageName(StrEnum):
    IDENTITY_DEDUPE = "identity_dedupe"
    METADATA = "metadata"
    DATASHEET = "datasheet"
    EXISTING_EVIDENCE = "existing_evidence"
    CAD_ACQUISITION = "cad_acquisition"
    RECONCILE = "reconcile"
    CANONICAL_DEFINITION = "canonical_definition"
    TEMPLATE_GENERATION = "template_generation"
    NATIVE_CONVERSION_ACQUISITION = "native_conversion_acquisition"
    KICAD_BUILD_READBACK = "kicad_build_readback"
    ALTIUM_BUILD_READBACK = "altium_build_readback"
    CROSS_EDA_VERIFICATION = "cross_eda_verification"
    CATALOG_LINK_GENERATION = "catalog_link_generation"
    PUBLISH = "publish"


@dataclass(frozen=True, slots=True)
class StageSpec:
    name: StageName
    ordinal: int
    dependencies: tuple[StageName, ...] = ()


_DEFAULT_PLAN = (
    StageSpec(StageName.IDENTITY_DEDUPE, 0),
    StageSpec(StageName.METADATA, 1, (StageName.IDENTITY_DEDUPE,)),
    StageSpec(StageName.DATASHEET, 2, (StageName.IDENTITY_DEDUPE,)),
    StageSpec(StageName.EXISTING_EVIDENCE, 3, (StageName.IDENTITY_DEDUPE,)),
    StageSpec(StageName.CAD_ACQUISITION, 4, (StageName.IDENTITY_DEDUPE,)),
    StageSpec(
        StageName.RECONCILE,
        5,
        (
            StageName.METADATA,
            StageName.DATASHEET,
            StageName.EXISTING_EVIDENCE,
        ),
    ),
    StageSpec(
        StageName.CANONICAL_DEFINITION,
        6,
        (StageName.RECONCILE,),
    ),
    StageSpec(
        StageName.TEMPLATE_GENERATION,
        7,
        (StageName.CANONICAL_DEFINITION,),
    ),
    StageSpec(
        StageName.NATIVE_CONVERSION_ACQUISITION,
        8,
        (
            StageName.CAD_ACQUISITION,
            StageName.CANONICAL_DEFINITION,
        ),
    ),
    StageSpec(
        StageName.KICAD_BUILD_READBACK,
        9,
        (
            StageName.TEMPLATE_GENERATION,
            StageName.NATIVE_CONVERSION_ACQUISITION,
        ),
    ),
    StageSpec(
        StageName.ALTIUM_BUILD_READBACK,
        10,
        (
            StageName.TEMPLATE_GENERATION,
            StageName.NATIVE_CONVERSION_ACQUISITION,
        ),
    ),
    StageSpec(
        StageName.CROSS_EDA_VERIFICATION,
        11,
        (
            StageName.KICAD_BUILD_READBACK,
            StageName.ALTIUM_BUILD_READBACK,
        ),
    ),
    StageSpec(
        StageName.CATALOG_LINK_GENERATION,
        12,
        (StageName.CROSS_EDA_VERIFICATION,),
    ),
    StageSpec(
        StageName.PUBLISH,
        13,
        (StageName.CATALOG_LINK_GENERATION,),
    ),
)


def default_stage_plan() -> tuple[StageSpec, ...]:
    """Return the immutable, topologically ordered vNext stage plan."""

    return _DEFAULT_PLAN
