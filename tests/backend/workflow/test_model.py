from uuid import UUID

import pytest

from stockroom.workflow.model import IntakeIdentity, canonical_json, new_opaque_id
from stockroom.workflow.planner import StageName, default_stage_plan


def test_default_plan_is_deterministic_and_expresses_fanout_and_join():
    first = default_stage_plan()
    second = default_stage_plan()

    assert first == second
    assert [stage.name for stage in first] == [
        StageName.IDENTITY_DEDUPE,
        StageName.METADATA,
        StageName.DATASHEET,
        StageName.EXISTING_EVIDENCE,
        StageName.CAD_ACQUISITION,
        StageName.RECONCILE,
        StageName.CANONICAL_DEFINITION,
        StageName.TEMPLATE_GENERATION,
        StageName.NATIVE_CONVERSION_ACQUISITION,
        StageName.KICAD_BUILD_READBACK,
        StageName.ALTIUM_BUILD_READBACK,
        StageName.CROSS_EDA_VERIFICATION,
        StageName.CATALOG_LINK_GENERATION,
        StageName.PUBLISH,
    ]
    assert {stage.name: stage.dependencies for stage in first} == {
        StageName.IDENTITY_DEDUPE: (),
        StageName.METADATA: (StageName.IDENTITY_DEDUPE,),
        StageName.DATASHEET: (StageName.IDENTITY_DEDUPE,),
        StageName.EXISTING_EVIDENCE: (StageName.IDENTITY_DEDUPE,),
        StageName.CAD_ACQUISITION: (StageName.IDENTITY_DEDUPE,),
        StageName.RECONCILE: (
            StageName.METADATA,
            StageName.DATASHEET,
            StageName.EXISTING_EVIDENCE,
        ),
        StageName.CANONICAL_DEFINITION: (StageName.RECONCILE,),
        StageName.TEMPLATE_GENERATION: (StageName.CANONICAL_DEFINITION,),
        StageName.NATIVE_CONVERSION_ACQUISITION: (
            StageName.CAD_ACQUISITION,
            StageName.CANONICAL_DEFINITION,
        ),
        StageName.KICAD_BUILD_READBACK: (
            StageName.TEMPLATE_GENERATION,
            StageName.NATIVE_CONVERSION_ACQUISITION,
        ),
        StageName.ALTIUM_BUILD_READBACK: (
            StageName.TEMPLATE_GENERATION,
            StageName.NATIVE_CONVERSION_ACQUISITION,
        ),
        StageName.CROSS_EDA_VERIFICATION: (
            StageName.KICAD_BUILD_READBACK,
            StageName.ALTIUM_BUILD_READBACK,
        ),
        StageName.CATALOG_LINK_GENERATION: (StageName.CROSS_EDA_VERIFICATION,),
        StageName.PUBLISH: (StageName.CATALOG_LINK_GENERATION,),
    }


def test_identity_keys_preserve_punctuation_while_normalizing_text_only():
    ampersand = IntakeIdentity("  ACME™  ", " ABC&_123 ")
    parenthesis = IntakeIdentity("acme™", "abc(%123")

    assert ampersand.manufacturer == "  ACME™  "
    assert ampersand.mpn == " ABC&_123 "
    assert ampersand.manufacturer_key == "ACME™"
    assert ampersand.mpn_key == "ABC&_123"
    assert parenthesis.mpn_key == "abc(%123"
    assert ampersand.mpn_key != parenthesis.mpn_key


def test_identity_keys_use_nfc_without_compatibility_collisions():
    compatibility_glyphs = IntakeIdentity("ACME™", "ＡＢＣ①")
    literal_text = IntakeIdentity("ACMETM", "ABC1")
    decomposed = IntakeIdentity("Cafe\u0301", "P-1")
    composed = IntakeIdentity("Café", "P-1")

    assert compatibility_glyphs.manufacturer_key == "ACME™"
    assert literal_text.manufacturer_key == "ACMETM"
    assert compatibility_glyphs.manufacturer_key != literal_text.manufacturer_key
    assert compatibility_glyphs.mpn_key != literal_text.mpn_key
    assert compatibility_glyphs.mpn == "ＡＢＣ①"
    assert decomposed.manufacturer_key == composed.manufacturer_key


def test_identity_keys_do_not_merge_case_variants():
    uppercase = IntakeIdentity("ACME", "PART-1")
    lowercase = IntakeIdentity("acme", "part-1")

    assert uppercase.manufacturer_key == "ACME"
    assert lowercase.manufacturer_key == "acme"
    assert uppercase.manufacturer_key != lowercase.manufacturer_key
    assert uppercase.mpn_key == "PART-1"
    assert lowercase.mpn_key == "part-1"
    assert uppercase.mpn_key != lowercase.mpn_key


@pytest.mark.parametrize(
    "value",
    [
        {"integer-key": {"valid": True}, 1: "not JSON"},
        {"tuple": ("not", "a", "JSON", "array")},
        {"nan": float("nan")},
        {"positive_infinity": float("inf")},
        {"negative_infinity": float("-inf")},
    ],
)
def test_canonical_json_rejects_python_only_or_non_finite_shapes(value):
    with pytest.raises(TypeError, match="JSON"):
        canonical_json(value)


def test_opaque_ids_are_uuid_values_without_identity_content():
    value = new_opaque_id()

    assert UUID(value).version == 4
    assert len(value) == 36
    assert "acme" not in value
