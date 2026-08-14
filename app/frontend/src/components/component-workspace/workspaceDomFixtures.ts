/**
 * The dossiers the DOM-parity gate renders, and nothing else.
 *
 * They live apart from the test so the gate file is about the COMPARISON and this one is about the
 * INPUT. Two shapes, because the workspace's arrangement is content-driven and the two ends of that
 * behave differently:
 *
 *   POPULATED  every conditional branch on: four identity lines, three attached CAD assets, a key
 *              block and two specification groups (so the anchor strip clears its two-heading
 *              floor), a pinout, and all five collapsible sourcing sections filled.
 *   SPARSE     nothing sourced at all, which is the `sourcingIsSparse` geometry, the reveal control
 *              with five hidden sections, and the specifications column's own empty state.
 *
 * Every timestamp is fixed and the gate freezes the clock against `FIXTURE_NOW`, because the
 * lifecycle row and the status bar both render a RELATIVE time and a gate whose expected output
 * ages overnight is a gate nobody keeps.
 */
import type { ComponentDossier } from "../../api/dossierTypes";
import {
  makeDocument,
  makeDossier,
  makeDossierWith,
  makeFieldConflict,
  makeManualOverride,
  makeOffer,
  makeRelatedPart,
  makeRepresentation,
  makeRevisionEvent,
  makeSourceLedgerEntry,
  makeSpecification,
} from "../../test/dossierFixture";

/** The component id every fixture render opens, so `componentDevId` is a constant here. */
export const FIXTURE_COMPONENT_ID = "lm358";

/**
 * The instant the gate pretends it is.
 *
 * Two days after the fixtures' own `2026-08-01` stamps, so the relative times render as a settled
 * "2 days ago" rather than as an hour boundary that a slow suite could cross mid-run.
 */
export const FIXTURE_NOW = new Date("2026-08-03T00:00:00Z");

/** Everything on: every conditional line, section and control the workspace can draw. */
export function populatedDossier(): ComponentDossier {
  const dossier = makeDossierWith({
    keySpecifications: [
      makeSpecification({
        key: "supply_voltage",
        label: "Supply Voltage",
        group: "electrical",
        groupLabel: "Electrical",
        displayValue: "3.3",
        unit: "V",
      }),
      makeSpecification({
        key: "channels",
        label: "Channels",
        group: "electrical",
        groupLabel: "Electrical",
        displayValue: "2",
        unit: "",
        verificationState: "verified",
      }),
    ],
    groups: [
      {
        id: "electrical",
        label: "Electrical",
        specifications: [
          makeSpecification({
            key: "gain_bandwidth",
            label: "Gain Bandwidth",
            group: "electrical",
            groupLabel: "Electrical",
            displayValue: "1.1",
            unit: "MHz",
          }),
          makeSpecification({
            key: "input_offset",
            label: "Input Offset Voltage",
            group: "electrical",
            groupLabel: "Electrical",
            verificationState: "missing",
          }),
        ],
      },
      {
        id: "package_mechanical",
        label: "Package and Mechanical",
        specifications: [
          makeSpecification({
            key: "pin_count",
            label: "Pin Count",
            group: "package_mechanical",
            groupLabel: "Package and Mechanical",
            displayValue: "8",
            unit: "",
            verificationState: "conflicting",
          }),
          makeSpecification({
            key: "pitch",
            label: "Pitch",
            group: "package_mechanical",
            groupLabel: "Package and Mechanical",
            displayValue: "1.27",
            unit: "mm",
          }),
        ],
      },
    ],
    documents: [
      makeDocument({ isPreferred: true }),
      makeDocument({
        documentType: "application_note",
        documentTypeLabel: "Application Note",
        title: "Single-Supply Operation",
        localPath: "",
        remoteUrl: "https://ti.example.invalid/an-lm358.pdf",
        status: "referenced",
      }),
    ],
  });

  return {
    ...dossier,
    identity: {
      ...dossier.identity,
      manufacturerPage: {
        url: "https://ti.example.invalid/product/lm358",
        host: "ti.example.invalid",
        sourceId: "manufacturer",
        sourceLabel: "Texas Instruments",
        state: "verified",
        verified: true,
        reason: "manufacturer host",
        checkedAt: "2026-08-01T00:00:00Z",
        rejectedCandidates: [],
      },
    },
    cadAssets: {
      ...dossier.cadAssets,
      kinds: {
        symbol: makeRepresentation("symbol"),
        footprint: makeRepresentation("footprint"),
        model: makeRepresentation("model"),
      },
    },
    supplySummary: {
      ...dossier.supplySummary,
      offerCount: 2,
      providersInStock: ["digikey", "mouser"],
      totalStock: 1512,
      bestUnitPrice: 0.38,
      bestUnitPriceCurrency: "$",
      bestUnitPriceProvider: "mouser",
      lifecycle: "Active",
      manufacturerStatus: "Active",
      leadTime: "In stock",
      factoryLeadTime: "12 weeks",
      staleness: "fresh",
      failures: [],
    },
    officialApiData: {
      providerCount: 2,
      fieldCount: 2,
      providers: [
        {
          provider: "digikey",
          providerLabel: "DigiKey",
          state: "success",
          fetchedAt: "2026-08-01T00:00:00Z",
          payloadRef: "sourced/lm358/digikey.json",
          fieldCount: 1,
          rows: [
            {
              path: "product_details.Product.QuantityAvailable",
              endpoint: "product_details",
              kind: "number",
              value: 512,
              displayValue: "512",
            },
          ],
        },
        {
          provider: "mouser",
          providerLabel: "Mouser",
          state: "success",
          fetchedAt: "2026-08-01T00:00:00Z",
          payloadRef: "sourced/lm358/mouser.json",
          fieldCount: 1,
          rows: [
            {
              path: "SearchResults.Parts[0].AvailabilityInStock",
              endpoint: "SearchResults",
              kind: "number",
              value: 1000,
              displayValue: "1000",
            },
          ],
        },
      ],
    },
    distributorOffers: [
      makeOffer(),
      makeOffer({
        provider: "mouser",
        providerLabel: "Mouser",
        sku: "595-LM358DR",
        stock: 1000,
        unitPrice: 0.38,
        priceBreaks: [
          { qty: 1, price: 0.38 },
          { qty: 100, price: 0.31 },
        ],
      }),
    ],
    relatedParts: [makeRelatedPart()],
    provenance: {
      ...dossier.provenance,
      sources: [makeSourceLedgerEntry(), makeSourceLedgerEntry({ id: "mouser", label: "Mouser" })],
      conflicts: [makeFieldConflict()],
      manualOverrides: [makeManualOverride()],
    },
    revisions: [makeRevisionEvent()],
    diagnostics: { ...dossier.diagnostics, pinCount: 8 },
  };
}

/**
 * Nothing sourced, nothing specified: the other end of every condition in the document.
 *
 * The factory default already IS this component - no offers, no documents, no related parts, no
 * provenance, no specification groups - so it is used unchanged rather than re-stated.
 */
export function sparseDossier(): ComponentDossier {
  return makeDossier();
}
