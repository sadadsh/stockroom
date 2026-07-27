/**
 * ONE wire-shaped `PartDetail` factory, for every test that needs a part.
 *
 * WHY THIS EXISTS. On 2026-07-27 the backend record was renamed wholesale - `display_name`,
 * `category`, `description` and `specs` moved into a `derived` block, `eda` became `assets`,
 * every asset slot gained a `ref` wrapper, and `passive` became a four-valued `part_class` -
 * and zero frontend files were touched. The frontend suite stayed green through all of it,
 * because each test file hand-rolled its own `detail()` builder in the OLD shape. Green tests,
 * hand-written mocks, and a detail panel that crashed on every part.
 *
 * A mock is only evidence if something forces it to match the server. So the factory is typed
 * as `PartDetail` and defined ONCE, which closes the chain:
 *
 *     backend `PartRecord.to_dict()`
 *       -> tests/backend/test_part_wire_contract.py   (key sets must match, both directions)
 *       -> src/api/types.ts `PartDetail`
 *       -> tsc                                        (this file must satisfy it)
 *       -> every test's fixture
 *
 * Rename a field on the backend now and the pytest fails; fix types.ts and `tsc` fails here;
 * fix here and every test using it moves at once. No link in that chain can be skipped, and no
 * test can quietly keep asserting a shape the server stopped sending.
 *
 * PRIOR ART (checked before writing, 2026-07-27). The first draft hand-rolled a factory plus a
 * recursive deep-merge. ADOPTED INSTEAD: `fishery` (thoughtbot, MIT, TypeScript-first, no
 * runtime dependencies), which is the established answer to exactly this - typed factories with
 * deep-merged overrides, modelled on Ruby's factory_bot. Writing the merge by hand would have
 * meant owning its null/array/undefined semantics forever, and a subtly wrong merge in a FIXTURE
 * is the worst place to have one: it makes tests pass. REJECTED: `@faker-js/faker` (generates
 * random VALUES; the problem here is the SHAPE, and random data would make failures
 * irreproducible), and plain static object literals (that is precisely what drifted).
 *
 * Overrides are typed against the real nested shape on purpose. A flat convenience vocabulary
 * here would reintroduce exactly the old field names this rename removed, and the next reader
 * could not tell which spelling the server actually speaks.
 */
import { Factory } from "fishery";
import type { DeepPartial } from "fishery";

import type { Asset, AssetRef, EdaAssets, PartDetail } from "../api/types";

/** Build one asset slot. A bare reference is "attached, unattributed, unchecked", which is what
 * most fixtures mean; pass `origin`/`checks` when the case is actually about provenance. */
export function makeAsset(ref: Partial<AssetRef>, rest: Omit<Asset, "ref"> = {}): Asset {
  return { ref: { lib: "", name: "", file: "", ...ref }, ...rest };
}

/** An empty per-tool bundle. Slots are null, never absent: that is what the backend emits. */
export function makeEdaAssets(over: Partial<EdaAssets> = {}): EdaAssets {
  return { symbol: null, footprint: null, model: null, ...over };
}

/** The default KiCad bundle: a symbol, a footprint and an owned 3D model. */
export function kicadComplete(): Record<string, EdaAssets> {
  return {
    kicad: makeEdaAssets({
      symbol: makeAsset({ lib: "SR-ICs", name: "LM358" }),
      footprint: makeAsset({ lib: "SR-ICs", name: "SOIC-8" }),
      model: makeAsset({ file: "models/lm358.step" }),
    }),
  };
}

export const partDetailFactory = Factory.define<PartDetail>(() => ({
  schema_version: 3,
  id: "lm358-0000",
  mpn: "LM358DR",
  manufacturer: "TI",
  part_class: "component",
  requires_override: null,
  derived: {
    display_name: "LM358",
    value: "LM358DR",
    category: "ICs",
    description: "Dual op-amp",
    specs: {},
    derived_at: "2026-07-27T00:00:00Z",
    derived_by: "rules@1",
  },
  sources: {},
  assets: {},
  tags: [],
  datasheet: null,
  purchase: [],
  provenance: null,
  hashes: null,
  enrichment: {},
}));

/**
 * A complete, wire-shaped part detail. Pass only what the case is actually about; `derived` and
 * `assets` merge deeply, so `{ derived: { category: "Resistors" } }` keeps the rest of the block.
 *
 * MEASURED, not assumed (2026-07-27, `fishery@2.4.0`): the merge is deep, arrays REPLACE rather
 * than concatenate (`{ tags: [] }` really does mean no tags), and an empty object does NOT clear
 * a branch - `{ assets: {} }` leaves the base assets untouched. That last one is a footgun, so
 * the base carries NO assets at all and every test builds them up additively. A test that needs
 * a slot ABSENT must say so explicitly with `makeEdaAssets({ symbol: null })`, never by omission.
 */
export function makePartDetail(over: DeepPartial<PartDetail> = {}): PartDetail {
  return partDetailFactory.build(over);
}
