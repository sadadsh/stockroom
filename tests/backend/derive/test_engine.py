"""The derive engine's three spec properties, measured rather than asserted.

Spec section 9's acceptance test, verbatim: *"change the naming scheme, re-derive the entire
library, and lose nothing that was imported. If a re-derive can destroy imported data, the schema
is wrong. Concretely: a re-derive must be idempotent (run it twice, get identical records) and
lossless (the sourced/ tree is never written by it)."*

So: IDEMPOTENT, LOSSLESS, and the naming swap that is the reason the split exists at all.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from stockroom.derive.engine import Identity, derive_block, load_payloads, rederive
from stockroom.derive.naming import UnknownNamingScheme, scheme_names
from stockroom.model.part import PartRecord
from stockroom.model.part_class import PartClass
from stockroom.model.sourced import write_payload

AT = "2026-07-27T04:00:00Z"


# A Mouser response with DELIBERATELY MESSY spec labels and values, because the point of moving
# normalization to derive time is that the messy original SURVIVES on disk. A tidy fixture could
# not tell a normalizing derive from a non-normalizing one.
MOUSER_BODY = {
    "SearchResults": {
        "Parts": [
            {
                "ManufacturerPartNumber": "ERJ-P03F1101V",
                "Manufacturer": "Panasonic",
                "Description": "Thick Film Resistors - SMD 0603 1.1Kohms 1% AEC-Q200",
                "DataSheetUrl": "https://example.invalid/erj.pdf",
                "AvailabilityInStock": "4200",
                "ProductDetailUrl": "https://www.mouser.com/erj-p03f1101v",
                "Category": "Chip Resistor - Surface Mount",
                "ProductAttributes": [
                    {"AttributeName": "Resistance:  Resistance", "AttributeValue": "1.1 kOhms"},
                    {"AttributeName": "Tolerance", "AttributeValue": "1 %"},
                    {"AttributeName": "Package / Case", "AttributeValue": "0603"},
                ],
            }
        ]
    }
}


def _seed(tmp_path: Path, part_id: str, source: str, body: dict) -> Path:
    """Write one raw payload the way the importer will, and return the library root."""
    write_payload(tmp_path, part_id, source, json.dumps(body, indent=1))
    return tmp_path


def _tree_hashes(root: Path) -> dict[str, str]:
    """Content hash of every file under a directory, so 'untouched' is a measurement."""
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _record(part_id: str = "erj-p03f1101v-0000") -> PartRecord:
    return PartRecord(
        id=part_id,
        mpn="ERJ-P03F1101V",
        manufacturer="Panasonic",
        part_class=PartClass.PASSIVE,
    )


# ------------------------------------------------------------------ the harness works

def test_the_fixture_really_produces_a_derived_block():
    """Anti-vacuous guard. Every test below compares derivations; if the fixture derived NOTHING
    they would all pass by comparing empty to empty, which is the failure mode that makes a whole
    suite meaningless."""
    block = derive_block(Identity.of(_record()), {"mouser": MOUSER_BODY}, derived_at=AT)
    assert block.description, "the fixture yielded no description - every comparison below is vacuous"
    assert block.specs, "the fixture yielded no specs - every comparison below is vacuous"
    assert block.display_name, "the fixture yielded no name - the naming tests are vacuous"


# ------------------------------------------------------------------------- IDEMPOTENT

def test_deriving_twice_gives_a_byte_identical_record(tmp_path):
    """The spec's word is 'byte-identical', so this compares the SERIALIZED record, not the object.

    Comparing dataclasses would miss an ordering difference that a real git diff would show, and
    the whole reason to care is that a re-derive must not churn history.
    """
    root = _seed(tmp_path, "erj-p03f1101v-0000", "mouser", MOUSER_BODY)
    rec = _record()

    rederive(rec, root, derived_at=AT)
    first = json.dumps(rec.to_dict(), sort_keys=True, indent=2)

    rederive(rec, root, derived_at=AT)
    second = json.dumps(rec.to_dict(), sort_keys=True, indent=2)

    assert first == second


def test_a_derive_from_a_CLEARED_block_reproduces_the_record(tmp_path):
    """DISPOSABLE BY CONSTRUCTION: drop the whole block, recompute, get the record back.

    This is the property that makes `derived` safe to throw away, and it is the one the schema is
    wrong without. `clear_derived` exists so it is testable rather than asserted.
    """
    root = _seed(tmp_path, "erj-p03f1101v-0000", "mouser", MOUSER_BODY)
    rec = _record()
    rederive(rec, root, derived_at=AT)
    before = json.dumps(rec.to_dict(), sort_keys=True)

    rec.clear_derived()
    assert not rec.display_name, "clear_derived did not actually empty the block"
    rederive(rec, root, derived_at=AT)

    assert json.dumps(rec.to_dict(), sort_keys=True) == before

    # And REPLACED, not merged into: the block the engine hands back must be computed purely from
    # the evidence, so a stale field cannot ride along. Checked on the engine's own return value
    # because `record.derived` is a property that rebuilds the block from flat fields - reading it
    # back cannot distinguish "the engine replaced it" from "the engine merged it".
    rec.description = "a description with no evidence behind it"
    fresh = derive_block(
        Identity.of(rec), load_payloads(root, rec.id), derived_at=AT, current_category=rec.category
    )
    assert fresh.description != "a description with no evidence behind it"


def test_the_derivation_does_not_depend_on_a_clock(tmp_path):
    """`derived_at` is the ONLY field a caller's timestamp may reach.

    If anything else read the clock, two derives seconds apart would differ somewhere the test
    above cannot see, because it passes the same timestamp both times.
    """
    root = _seed(tmp_path, "erj-p03f1101v-0000", "mouser", MOUSER_BODY)
    a = rederive(_record(), root, derived_at="2020-01-01T00:00:00Z").derived.to_dict()
    b = rederive(_record(), root, derived_at="2099-12-31T23:59:59Z").derived.to_dict()
    assert a.pop("derived_at") != b.pop("derived_at")
    assert a == b, "something other than derived_at changed with the timestamp"


def test_the_merge_follows_REGISTRY_priority_not_the_order_the_payloads_arrive_in(tmp_path):
    """Determinism, which is what idempotency actually rests on.

    `merge_missing` gives a field to whoever fills it FIRST, so if the engine iterated the payload
    mapping instead of the registry, the winning description would depend on dict/listing order -
    and `sourced/` is listed ALPHABETICALLY (`list_sources` sorts), which is not the priority order.
    Mouser outranks DigiKey in PAYLOAD_PARSERS but sorts second, so alphabetical iteration would
    silently hand every contested field to DigiKey.

    Added after a mutation survived: reversing the loop to `for source in payloads` left the whole
    suite green, because every other test seeds ONE payload and order cannot matter with one source.
    """
    payloads = {
        # Deliberately DigiKey first, i.e. the order `list_sources` would produce.
        "digikey": {
            "Products": [
                {
                    "ManufacturerProductNumber": "ERJ-P03F1101V",
                    "Description": {"ProductDescription": "DIGIKEY WORDING"},
                }
            ]
        },
        "mouser": MOUSER_BODY,
    }
    assert list(payloads) == ["digikey", "mouser"], "the fixture must present the WRONG order"

    block = derive_block(Identity.of(_record()), payloads, derived_at=AT)
    assert "DIGIKEY WORDING" not in block.description, (
        f"the lower-priority source won the description slot: {block.description!r}. The merge is "
        f"following payload order, not PAYLOAD_PARSERS order."
    )
    assert "Thick Film" in block.description, (
        f"Mouser is first in PAYLOAD_PARSERS so its description must win: {block.description!r}"
    )


# ---------------------------------------------------------------------------- LOSSLESS

def test_a_derive_never_writes_under_sourced(tmp_path):
    """LOSSLESS, measured by hashing the evidence tree before and after.

    `assert_no_writer_imported` proves the derive path cannot REACH the writer; this proves the
    observable outcome, which is the thing the owner actually cares about. Both, because a check
    of the mechanism and a check of the effect fail in different ways.
    """
    root = _seed(tmp_path, "erj-p03f1101v-0000", "mouser", MOUSER_BODY)
    _seed(tmp_path, "erj-p03f1101v-0000", "digikey", {"Products": []})
    sourced = root / "sourced"
    before = _tree_hashes(sourced)
    assert before, "nothing was seeded, so 'untouched' would be vacuously true"

    rec = _record()
    for _ in range(3):
        rederive(rec, root, derived_at=AT)

    assert _tree_hashes(sourced) == before


def test_the_raw_messy_value_survives_on_disk_while_the_derived_one_is_normalized(tmp_path):
    """The whole reason normalization moved off the import path.

    Before this, `normalize_spec_*` ran at IMPORT, so the winning value AS THE SOURCE RETURNED IT
    was gone forever - permanently, for all 158 of the owner's records. Both halves are asserted
    here: the derived block IS canonical, and the raw answer is STILL on disk to re-derive from.
    """
    root = _seed(tmp_path, "erj-p03f1101v-0000", "mouser", MOUSER_BODY)

    # Asserted on `derive_block`'s OWN return value, NOT through the record.
    #
    # MEASURED 2026-07-27: routing this through `rederive(...)` and reading `rec.specs` made the
    # test unable to fail. `PartRecord.derived` normalizes specs in BOTH its getter and its setter
    # (model/part.py), so the record cleans up after the engine and a derive that normalized
    # nothing at all still produced clean specs. Deleting the engine's `normalize_specs` call left
    # the whole suite green - which is exactly the "test that cannot fail" this repo keeps paying
    # for. Inspect the STAGE, not the end of the pipeline.
    block = derive_block(Identity.of(_record()), {"mouser": MOUSER_BODY}, derived_at=AT)

    # The duplicated-label twin "Resistance:  Resistance" is canonicalized BY THE ENGINE...
    assert "Resistance" in block.specs
    assert not any(":" in k for k in block.specs), (
        f"a raw label leaked out of the derive engine: {sorted(block.specs)}"
    )

    # ...the record agrees (belt and braces, and this is the layer a reader sees)...
    rec = rederive(_record(), root, derived_at=AT)
    assert "Resistance" in rec.specs

    # ...and the raw label is still exactly as Mouser sent it.
    raw = json.loads((root / "sourced" / "erj-p03f1101v-0000" / "mouser.json").read_text("utf-8"))
    labels = [a["AttributeName"] for a in raw["SearchResults"]["Parts"][0]["ProductAttributes"]]
    assert "Resistance:  Resistance" in labels


# ----------------------------------------------------------------- the naming-scheme swap

def test_changing_the_naming_scheme_renames_without_touching_anything_else(tmp_path):
    """The owner's requirement: *"change the way the data's manipulated later (human naming scheme
    for example)"* - with no re-import and no data loss."""
    root = _seed(tmp_path, "erj-p03f1101v-0000", "mouser", MOUSER_BODY)
    sourced_before = _tree_hashes(root / "sourced")

    human = rederive(_record(), root, derived_at=AT, scheme="spec-aware").derived.to_dict()
    bare = rederive(_record(), root, derived_at=AT, scheme="mpn").derived.to_dict()
    full = rederive(_record(), root, derived_at=AT, scheme="manufacturer-mpn").derived.to_dict()

    assert bare["display_name"] == "ERJ-P03F1101V"
    assert full["display_name"] == "Panasonic ERJ-P03F1101V"
    assert human["display_name"] not in {bare["display_name"], full["display_name"]}

    # ONLY the name moved. Everything else derived from the same evidence is identical...
    for other in (bare, full):
        assert {k: v for k, v in other.items() if k != "display_name"} == {
            k: v for k, v in human.items() if k != "display_name"
        }
    # ...and the evidence itself was not read-modify-written by any of the three.
    assert _tree_hashes(root / "sourced") == sourced_before


def test_identity_survives_every_scheme(tmp_path):
    """Spec rule 3: a re-derive never rewrites `id`, `mpn`, `manufacturer` or `part_class`."""
    root = _seed(tmp_path, "erj-p03f1101v-0000", "mouser", MOUSER_BODY)
    for scheme in scheme_names():
        rec = rederive(_record(), root, derived_at=AT, scheme=scheme)
        assert rec.id == "erj-p03f1101v-0000"
        assert rec.mpn == "ERJ-P03F1101V"
        assert rec.manufacturer == "Panasonic"
        assert rec.part_class is PartClass.PASSIVE


def test_an_unknown_scheme_is_LOUD_rather_than_silently_the_default(tmp_path):
    """A typo in a config key must not quietly rename a whole library to something nobody asked
    for. That is the exact failure the re-derive is meant to make safe."""
    root = _seed(tmp_path, "erj-p03f1101v-0000", "mouser", MOUSER_BODY)
    with pytest.raises(UnknownNamingScheme) as exc:
        rederive(_record(), root, derived_at=AT, scheme="humna-readable")
    assert "humna-readable" in str(exc.value)
    assert "spec-aware" in str(exc.value), "the error must name the schemes that DO exist"


# ------------------------------------------------------------------------- edge cases

def test_a_part_with_no_evidence_keeps_NOTHING_from_its_previous_block(tmp_path):
    """Every record in the owner's library is in this state until the importer runs.

    The honest outcome is that the previous block is GONE, not preserved: a silent "keep what was
    there" would make a library look re-derived when nothing had been, which is the one way this
    engine could lie.

    The name does not go blank, and that is correct rather than a leak - with no specs to name from,
    `propose_component_name` falls back to the MPN, which is IDENTITY (always present, never
    derived from evidence). The assertion that matters is that it is the MPN and not the stale
    hand-written name, so this pins both: the old value is gone AND what replaced it came from
    identity.
    """
    rec = _record()
    rec.display_name = "Some Name From Before"
    rec.description = "an old description"
    rec.specs = {"Resistance": "1.1 kOhms"}
    rederive(rec, tmp_path, derived_at=AT)

    assert rec.display_name == "ERJ-P03F1101V", "the name must fall back to identity, not persist"
    assert rec.description == "", "a description with no evidence behind it survived a re-derive"
    assert rec.specs == {}, "specs with no evidence behind them survived a re-derive"
    # Identity is untouched even with no evidence at all.
    assert rec.mpn == "ERJ-P03F1101V"


def test_a_payload_from_an_UNKNOWN_source_is_skipped_and_left_on_disk(tmp_path):
    """Forward compatibility, the same guarantee `PartRecord.extra` gives the record.

    A newer build may store a source this one cannot parse. Refusing to derive would make an older
    peer unable to rebuild a library it just pulled; deleting the payload would destroy evidence.
    """
    root = _seed(tmp_path, "erj-p03f1101v-0000", "mouser", MOUSER_BODY)
    write_payload(root, "erj-p03f1101v-0000", "farnell", json.dumps({"whatever": 1}))
    before = _tree_hashes(root / "sourced")

    rec = rederive(_record(), root, derived_at=AT)
    assert rec.display_name, "an unknown payload broke the derivation instead of being skipped"
    assert "farnell" not in load_payloads(root, "erj-p03f1101v-0000")
    assert _tree_hashes(root / "sourced") == before


def test_an_unparseable_payload_does_not_stop_the_part_from_deriving(tmp_path):
    """One damaged file must not make a part unrebuildable; the remaining evidence still counts."""
    root = _seed(tmp_path, "erj-p03f1101v-0000", "mouser", MOUSER_BODY)
    (root / "sourced" / "erj-p03f1101v-0000" / "digikey.json").write_text("{not json", "utf-8")

    rec = rederive(_record(), root, derived_at=AT)
    assert rec.description, "a corrupt sibling payload took the whole derivation down"


def test_a_human_filing_is_never_overwritten_by_a_vendor_taxonomy(tmp_path):
    """A vendor's Product Category is a suggestion for an UNFILED part, never an override.

    The record here is already filed somewhere real, so the derive must leave it alone even though
    the payload's own taxonomy says "Chip Resistor - Surface Mount".
    """
    root = _seed(tmp_path, "erj-p03f1101v-0000", "mouser", MOUSER_BODY)
    rec = _record()
    rec.category = "Precision Resistors"
    rederive(rec, root, derived_at=AT)
    assert rec.category == "Precision Resistors"


def test_an_unfiled_part_IS_classified_from_the_payload(tmp_path):
    """The other side of the rule above, and the negative control for it: without this the test
    above would pass on a derive that simply never classified anything."""
    root = _seed(tmp_path, "erj-p03f1101v-0000", "mouser", MOUSER_BODY)
    rec = _record()
    rec.category = "Other"
    rederive(rec, root, derived_at=AT)
    assert rec.category == "Resistors", f"an unfiled resistor was left as {rec.category!r}"


def test_the_ruleset_stamp_is_recorded_on_every_block(tmp_path):
    """`derived_by` is what lets a library be swept for parts still on an older derivation instead
    of everything being re-derived blindly."""
    root = _seed(tmp_path, "erj-p03f1101v-0000", "mouser", MOUSER_BODY)
    rec = rederive(_record(), root, derived_at=AT)
    assert rec.derived.derived_by.startswith("rules@")
    assert rec.derived.derived_at == AT
