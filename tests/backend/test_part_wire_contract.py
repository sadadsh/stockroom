"""The part record's WIRE SHAPE is pinned to the TypeScript that consumes it.

`GET /api/library/parts/{id}` returns `PartRecord.to_dict()` verbatim
(`api/routers/library.py`), so the record dataclass IS the wire contract. On 2026-07-27 that
contract was renamed wholesale - `display_name`/`category`/`description`/`specs` moved into a
`derived` block, `eda` became `assets`, each asset slot gained a `ref` wrapper, and `passive`
became `part_class` - and ZERO frontend files were touched. Every gate stayed green:

  - the backend suite passed, because its API tests were updated to the new shape;
  - `npm run typecheck` passed, because `PartDetail` is a HAND-WRITTEN structural declaration
    over untyped JSON, so it describes what the author believed, never what the server sends;
  - the frontend suite passed, because its fixtures are hand-written mocks of the old shape.

Meanwhile `edaTarget.ts` read `part.eda?.[tool]`, got `undefined` for every part, and reported
every component as missing its symbol, footprint and 3D model. That is the "CAD Incomplete
forever" defect this repo has already shipped once, reported ~10 times by the owner before it
was found, because every check ran on the layer BELOW the one they were looking at.

Three green gates could not see a broken app. This is the gate that can.

FACT, not judgement: it compares the key set the backend actually emits (built by calling
`to_dict()` on a real record) against the field names declared in the `PartDetail` interface in
`app/frontend/src/api/types.ts`, parsed from the source text. No judgement, so it may BLOCK.

Direction matters and is asymmetric on purpose:
  - a backend key the TS does not declare is a FAILURE: the SPA cannot read it, and if a
    consumer dereferences it the app crashes or silently shows nothing.
  - a TS field the backend never emits is also a FAILURE here, because that is precisely the
    stale-declaration shape that made the rename invisible.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TYPES_TS = ROOT / "app" / "frontend" / "src" / "api" / "types.ts"


def _record(*, maximal: bool):
    """A real record. `maximal` fills every CONDITIONALLY-emitted field.

    Two records are needed, not one. `to_dict` omits some keys while they are empty (`alternates`
    today), so a single fixture can only ever measure one side: a minimal one makes a legitimately
    optional key look deleted, and a maximal one alone cannot tell which keys are omittable.
    """
    from stockroom.model.asset import AssetRef, EdaAssets
    from stockroom.model.part import PartRecord, SourcedValue
    from stockroom.model.part_class import PartClass

    rec = PartRecord(
        id="tps62130rgtr-d77f",
        mpn="TPS62130RGTR",
        manufacturer="Texas Instruments",
        part_class=PartClass.COMPONENT,
        display_name="Buck Converter",
        category="ICs",
        description="3A step-down",
        specs={"Package / Case": "16-VQFN"},
        assets={"kicad": EdaAssets(symbol=AssetRef(lib="SR-ICs", name="TPS62130RGTR"))},
    )
    if maximal:
        rec.alternates = {
            "description": [SourcedValue(value="Step-down converter", source="digikey")]
        }
    return rec


def _emitted_keys(*, maximal: bool = True) -> set[str]:
    """Top-level keys the backend really puts on the wire, from a real record."""
    return set(_record(maximal=maximal).to_dict().keys())


def _declared_fields() -> dict[str, bool]:
    """`PartDetail`'s declared fields in types.ts, mapped to whether each is OPTIONAL (`name?:`).

    Parsed from source rather than executed: a pytest run has no TS runtime, and shelling out
    to node would make a backend test depend on the frontend toolchain being installed.
    """
    src = TYPES_TS.read_text(encoding="utf-8")
    m = re.search(r"export\s+interface\s+PartDetail\s*\{(.*?)\n\}", src, re.S)
    assert m, "could not find `export interface PartDetail { ... }` in types.ts"
    body = m.group(1)
    # Strip comments so a field name mentioned in prose is never mistaken for a declaration.
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    body = re.sub(r"//[^\n]*", "", body)
    # `name?: Type;` / `name: Type;` at one level of nesting only.
    return {
        name: bool(q)
        for name, q in re.findall(r"^\s{2}([A-Za-z_][A-Za-z0-9_]*)(\??)\s*:", body, re.M)
    }


def test_the_harness_can_actually_see_both_sides():
    """Anti-vacuous guard: a comparison that silently matches nothing always passes.

    Both spaces must be non-trivially populated, or a green result below means nothing.
    """
    emitted, declared = _emitted_keys(), set(_declared_fields())
    assert len(emitted) >= 10, f"parsed too few backend keys ({len(emitted)}): {sorted(emitted)}"
    assert len(declared) >= 10, f"parsed too few TS fields ({len(declared)}): {sorted(declared)}"
    # The two must overlap at all; if they are disjoint the parse is broken, not the code.
    assert emitted & declared, "backend and TS key sets are DISJOINT - the parser is wrong"
    # The optionality parse must actually distinguish the two forms, or the omission test below
    # is vacuous: it would read every field as required and still pass on a record that omits one.
    flags = _declared_fields()
    assert set(flags.values()) == {True, False}, (
        f"the `name?:` parse found only {set(flags.values())} - it cannot tell optional from "
        "required, so the omission test below proves nothing"
    )


def test_every_key_the_backend_emits_is_declared_in_the_typescript():
    emitted = _emitted_keys()
    declared = set(_declared_fields())
    undeclared = emitted - declared
    assert not undeclared, (
        f"the API emits {sorted(undeclared)}, which `PartDetail` in "
        f"{TYPES_TS.relative_to(ROOT).as_posix()} does not declare. The SPA cannot read these. "
        f"Update the TS interface AND its consumers in the same commit as the backend rename."
    )


def test_the_typescript_declares_nothing_the_backend_stopped_emitting():
    emitted = _emitted_keys()
    declared = set(_declared_fields())
    stale = declared - emitted
    assert not stale, (
        f"`PartDetail` still declares {sorted(stale)}, which the backend no longer emits. "
        f"Any consumer reading these gets `undefined` SILENTLY - that is the "
        f"'CAD Incomplete forever' failure. Remove or move them, and fix every reader."
    )


def test_a_key_the_backend_can_omit_is_declared_OPTIONAL_in_the_typescript():
    """The third direction, and the one a key-set comparison alone cannot see.

    `to_dict` omits some keys while they are empty, so a real record often lacks them. A field
    that is REQUIRED in TypeScript but absent from the payload is the same silent-undefined bug
    as a renamed one - the compiler promises the consumer it is there, and it is not. Anything
    the minimal record leaves out must therefore be spelled `name?:`.
    """
    omittable = _emitted_keys(maximal=True) - _emitted_keys(maximal=False)
    assert omittable, (
        "no key was omitted by the minimal record, so this test is measuring nothing - either "
        "`to_dict` stopped omitting empty keys, or the maximal fixture stopped filling them"
    )
    declared = _declared_fields()
    wrongly_required = sorted(k for k in omittable if declared.get(k) is False)
    assert not wrongly_required, (
        f"the backend OMITS {wrongly_required} from a record that has none, but `PartDetail` "
        f"declares them required. A consumer dereferences `undefined` with the compiler's "
        f"blessing. Spell them `name?:` in {TYPES_TS.relative_to(ROOT).as_posix()}."
    )


@pytest.mark.parametrize("tool", ["kicad", "altium"])
def test_an_asset_slot_keeps_its_ref_wrapper_on_the_wire(tool):
    """The per-slot shape changed too, which a top-level key check cannot catch.

    An asset is no longer a bare `{lib,name,file}`: it wraps `ref` alongside `origin` and
    `checks`, which is what makes "where did this file come from" answerable at all. A frontend
    reading `slot.name` instead of `slot.ref.name` gets `undefined` and reports the asset absent.
    """
    from stockroom.model.asset import AssetRef, EdaAssets
    from stockroom.model.part import PartRecord
    from stockroom.model.part_class import PartClass

    rec = PartRecord(
        id="x-0000", mpn="X", manufacturer="M", part_class=PartClass.COMPONENT,
        assets={tool: EdaAssets(symbol=AssetRef(lib="L", name="N"))},
    )
    slot = rec.to_dict()["assets"][tool]["symbol"]
    assert "ref" in slot, f"{tool} symbol slot lost its `ref` wrapper: {slot}"
    assert slot["ref"]["name"] == "N"
    # `origin`/`checks` are omitted WHILE EMPTY on purpose (asset.py:149-151), so adopting the
    # schema does not rewrite every record to carry a null and an empty list. Pin both
    # directions: absent when unset, present when set. A reader must treat absence as "nobody
    # recorded where this came from", never as a trusted blank.
    assert "origin" not in slot, f"an unset origin must be OMITTED, not nulled: {slot}"


def test_a_recorded_origin_reaches_the_wire():
    """The other direction of the omission rule, and the owner's actual question.

    Their complaint was verbatim "its not trusted where we've gotten them", so provenance
    reaching the client is the point of the schema. A slot that silently dropped a recorded
    origin would leave the UI unable to answer it while looking fine.
    """
    from stockroom.model.asset import Asset, AssetOrigin, AssetRef, EdaAssets
    from stockroom.model.part import PartRecord
    from stockroom.model.part_class import PartClass

    rec = PartRecord(
        id="x-0000", mpn="X", manufacturer="M", part_class=PartClass.COMPONENT,
        assets={"kicad": EdaAssets(symbol=Asset(
            ref=AssetRef(lib="L", name="N"),
            origin=AssetOrigin(vendor="ultralibrarian", url="https://u/x",
                               captured_at="2026-07-27T00:00:00Z"),
        ))},
    )
    slot = rec.to_dict()["assets"]["kicad"]["symbol"]
    assert slot.get("origin", {}).get("vendor") == "ultralibrarian", (
        f"a recorded origin must survive to the wire: {slot}"
    )
