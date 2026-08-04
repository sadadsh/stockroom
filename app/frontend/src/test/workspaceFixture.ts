/**
 * ONE wire-shaped `ComponentWorkspaceResponse` factory, for every test that opens a component.
 *
 * Same reasoning as `partFixture.ts`, one layer up: the opened component reads the normalized
 * projection, so a test that hand-rolls its own workspace object is asserting against a shape the
 * server may have stopped sending. Typed as the real response and defined once, the chain closes:
 *
 *     stockroom.workspace.component_workspace()
 *       -> tests/backend/test_workspace.py
 *       -> src/api/workspaceTypes.ts
 *       -> tsc                                  (this file must satisfy it)
 *       -> every test's fixture
 */
import { Factory } from "fishery";
import type { DeepPartial } from "fishery";

import type {
  ComponentFact,
  ComponentWorkspaceResponse,
  RepresentationKind,
  RepresentationStatus,
  RepresentationToolView,
  RepresentationView,
  SourceRecordView,
  SourcingOfferView,
} from "../api/workspaceTypes";

/** One captured source, answering successfully unless the case is about a degraded one. */
export function makeSourceRecord(over: Partial<SourceRecordView> = {}): SourceRecordView {
  return {
    id: "digikey",
    label: "DigiKey",
    state: "success",
    fieldCount: 1,
    fetchedAt: "2026-08-01T00:00:00Z",
    file: "sourced/lm358/digikey.json",
    ...over,
  };
}

/** One distributor offer, with a single quoted break unless the case is about the ladder. */
export function makeOffer(over: Partial<SourcingOfferView> = {}): SourcingOfferView {
  return {
    sourceId: "digikey",
    sourceLabel: "DigiKey",
    partNumber: "296-1234-1-ND",
    url: "https://example.invalid/p",
    stock: 512,
    currency: "$",
    priceBreaks: [{ qty: 1, price: 0.42 }],
    fetchedAt: "2026-08-01T00:00:00Z",
    ...over,
  };
}

/** One presented datum. The default is an agreed value with a named source. */
export function makeFact(over: Partial<ComponentFact> = {}): ComponentFact {
  const rawValue = over.rawValue ?? "";
  return {
    id: "fact",
    label: "Fact",
    rawValue,
    formattedValue: String(rawValue),
    unit: null,
    source: { id: "digikey", label: "DigiKey", fetchedAt: "2026-08-01T00:00:00Z" },
    alternates: [],
    state: "agrees",
    ...over,
  };
}

export function makeTool(over: Partial<RepresentationToolView> = {}): RepresentationToolView {
  return {
    tool: "kicad",
    toolLabel: "KiCad",
    status: "ready",
    present: true,
    embedded: false,
    reference: { lib: "SR-ICs", name: "LM358", file: "" },
    sourceId: "snapeda",
    sourceLabel: "SnapEDA",
    sourceUrl: "",
    capturedAt: "2026-08-01T00:00:00Z",
    checks: [],
    ...over,
  };
}

export function makeRepresentation(
  kind: RepresentationKind,
  status: RepresentationStatus = "ready",
  tools: RepresentationToolView[] = [makeTool()],
): RepresentationView {
  return {
    kind,
    status,
    selectedTool: tools[0]?.tool ?? "",
    tools,
    sourceLabel: tools[0]?.sourceLabel ?? "",
    issue:
      status === "missing"
        ? "No file is attached yet."
        : status === "failed"
          ? "A recorded check did not pass."
          : status === "review"
            ? "A recorded check could not be measured."
            : null,
    alternativeCount: 0,
  };
}

export const componentWorkspaceFactory = Factory.define<ComponentWorkspaceResponse>(() => ({
  schemaVersion: 1,
  identity: {
    id: "lm358",
    displayName: "LM358",
    mpn: "LM358DR",
    manufacturer: "Texas Instruments",
    category: "ICs",
    partClass: "component",
    value: "LM358DR",
    package: "SOIC-8",
    pinCount: 8,
    lifecycle: "Active",
    tags: [],
  },
  summary: {
    description: makeFact({
      id: "description",
      label: "Description",
      rawValue: "Dual Operational Amplifier",
      formattedValue: "Dual Operational Amplifier",
    }),
    datasheetUrl: "https://example.invalid/lm358.pdf",
    datasheetFile: "datasheets/lm358.pdf",
  },
  representations: {
    symbol: makeRepresentation("symbol"),
    footprint: makeRepresentation("footprint"),
    model: makeRepresentation("model"),
  },
  specifications: { groups: [], total: 0, pinout: [], pinCount: 0 },
  sourcing: { offers: [], shared: [], relationships: [], resources: [] },
  sources: {
    fields: [],
    records: [],
    diagnostics: {
      schemaVersion: 1,
      derivedAt: "2026-08-01T00:00:00Z",
      derivedBy: "rules@1",
      hashes: { symbolContent: "", footprintContent: "", modelFile: "" },
      unknownKeys: [],
    },
  },
  attention: [],
}));

/**
 * A complete, wire-shaped component workspace. Pass only what the case is about.
 *
 * `representations` merges deeply per kind, so overriding one kind keeps the other two. Arrays
 * REPLACE, which is what a test asserting "no offers" or "exactly these attention items" wants.
 */
export function makeWorkspace(
  over: DeepPartial<ComponentWorkspaceResponse> = {},
): ComponentWorkspaceResponse {
  return componentWorkspaceFactory.build(over);
}
