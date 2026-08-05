/**
 * The CAD Assets column: the one column-level decision, the nine states, and the real previews.
 *
 * Three things are asserted here that a well-meaning change can silently undo:
 *
 *   the preferred source is a CONTROL, and it says what a change replaces BEFORE the change. A
 *   confirmation that arrives after the write is a report, and a report cannot be declined;
 *
 *   collapsing a module never removes it. "Is this symbol consistent with this footprint" is one
 *   question, and it cannot be answered by flipping between two views;
 *
 *   the previews are drawn from the FILE. Pin counts, duplicate numbers, courtyard presence and
 *   overall size are facts a rasterised thumbnail throws away, so a preview that cannot state
 *   them can only show a picture and hope.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { ApiError, api } from "../../api/client";
import type {
  CadPreferenceScope,
  CadPreferenceView,
  ComponentDossier,
} from "../../api/dossierTypes";
import { CaptureProvider } from "../../lib/capture";
import { componentRepresentationDevId, devIdSelector } from "../../lib/componentDevIds";
import { ThemeProvider } from "../../lib/theme";
import { ToastProvider } from "../../lib/toast";
import {
  defaultUiSession,
  openComponentInSession,
  resetUiSessionForTests,
} from "../../lib/uiSession";
import {
  makeDossier,
  makeRepresentation,
  makeSpecification,
  makeTool,
} from "../../test/dossierFixture";
import { ComponentWorkspace } from "./ComponentWorkspace";
import { symbolEvidence } from "./SymbolPreview";
import { footprintEvidence, padPitch } from "./FootprintPreview";
import { cadAssetStatus } from "./workspaceStatus";

vi.mock("../../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../../api/client")>();
  return {
    ...actual,
    api: {
      partDossier: vi.fn(),
      partHistory: vi.fn(),
      partDetail: vi.fn(),
      partCadSource: vi.fn(),
      setPartProviderCoverage: vi.fn(),
      setCadPreferredSource: vi.fn(),
      clearCadPreferredSource: vi.fn(),
      setCadAssetPreferredSource: vi.fn(),
      clearCadAssetPreferredSource: vi.fn(),
      facets: vi.fn(),
      previewSvg: vi.fn(),
      modelGlb: vi.fn(),
      landPattern: vi.fn(),
      symbolGeometry: vi.fn(),
      runCapture: vi.fn(),
      showCaptureProvider: vi.fn(),
      captureWorkflow: vi.fn(),
      workflowEvents: vi.fn(),
    },
  };
});

vi.mock("../../api/cadVariantClient", async (importActual) => {
  const actual = await importActual<typeof import("../../api/cadVariantClient")>();
  return {
    ...actual,
    cadVariantApi: { inventory: vi.fn(), activatePair: vi.fn() },
  };
});

vi.mock("../../lib/threeScene", () => ({
  mountModelScene: vi.fn(() => ({
    dispose: vi.fn(),
    fit: vi.fn(),
    setView: vi.fn(),
    setSpin: vi.fn((wanted: boolean) => wanted),
    setLandPattern: vi.fn(),
    setRenderMode: vi.fn(),
    setLayers: vi.fn(),
    setPlacementMode: vi.fn(),
    modelInfo: vi.fn(() => null),
  })),
}));

const mockApi = vi.mocked(api);
const ID = "lm358";

const OK: CadPreferenceScope = {
  allowed: true,
  refusal: "",
  reason: "",
  changes: [],
  current: false,
};

/** A preference offering one provider that replaces what is attached from another. */
function preference(over: Partial<CadPreferenceView> = {}): CadPreferenceView {
  return {
    provider: "snapmagic",
    label: "SnapMagic",
    mixed: false,
    pinned: false,
    reviewedAt: "",
    assets: {
      symbol: { provider: "snapmagic", label: "SnapMagic", origin: "installed" },
      footprint: { provider: "snapmagic", label: "SnapMagic", origin: "installed" },
      model: { provider: "snapmagic", label: "SnapMagic", origin: "installed" },
    },
    assetLabels: { symbol: "Symbol", footprint: "Footprint", model: "3D Model" },
    options: [
      {
        provider: "ultralibrarian",
        label: "Ultra Librarian",
        coverage: { symbol: "validated", footprint: "validated", model: "available" },
        set: {
          ...OK,
          changes: [
            {
              asset: "symbol",
              assetLabel: "Symbol",
              fromProvider: "snapmagic",
              fromLabel: "SnapMagic",
              fromOrigin: "installed",
              toProvider: "ultralibrarian",
              toLabel: "Ultra Librarian",
            },
            {
              asset: "footprint",
              assetLabel: "Footprint",
              fromProvider: "snapmagic",
              fromLabel: "SnapMagic",
              fromOrigin: "installed",
              toProvider: "ultralibrarian",
              toLabel: "Ultra Librarian",
            },
          ],
        },
        assets: { symbol: { ...OK }, footprint: { ...OK }, model: { ...OK } },
      },
      {
        provider: "samacsys",
        label: "SamacSys",
        coverage: { symbol: "available", footprint: "unknown", model: "unknown" },
        set: {
          allowed: false,
          refusal: "unsupplied",
          reason: "SamacSys does not supply the Footprint, 3D Model for this component.",
          changes: [],
          current: false,
        },
        assets: {
          symbol: { ...OK },
          footprint: { ...OK },
          model: { ...OK },
        },
      },
    ],
    ...over,
  };
}

const SYMBOL_GEOMETRY = {
  units: "mm",
  name: "LM358",
  namesHidden: false,
  numbersHidden: false,
  pins: [
    {
      number: "1",
      name: "OUT1",
      electrical: "output",
      style: "line",
      at: [-7.62, 2.54] as [number, number],
      angle: 0,
      length: 2.54,
      hidden: false,
    },
    {
      number: "2",
      name: "IN1-",
      electrical: "input",
      style: "line",
      at: [-7.62, 0] as [number, number],
      angle: 0,
      length: 2.54,
      hidden: false,
    },
  ],
  graphics: [
    {
      kind: "rectangle" as const,
      points: [
        [-5.08, 5.08],
        [5.08, -5.08],
      ] as [number, number][],
      center: [0, 0] as [number, number],
      radius: 0,
      width: 0.254,
      fill: "background",
      closed: false,
    },
  ],
  bounds: { x: -7.62, y: -5.08, width: 12.7, height: 10.16 },
};

const LAND = {
  units: "mm",
  pads: [
    {
      number: "1",
      at: [-0.95, -1.27] as [number, number],
      size: [0.6, 1.5] as [number, number],
      shape: "rect",
      rotation: 0,
      drill: 0,
      pad_type: "smd",
      side: "front",
      rratio: 0,
      layers: ["F.Cu", "F.Paste", "F.Mask"],
    },
    {
      number: "2",
      at: [-0.95, 0] as [number, number],
      size: [0.6, 1.5] as [number, number],
      shape: "rect",
      rotation: 0,
      drill: 0,
      pad_type: "smd",
      side: "front",
      rratio: 0,
      layers: ["F.Cu"],
    },
  ],
  graphics: [
    {
      start: [-1.5, -2] as [number, number],
      end: [1.5, -2] as [number, number],
      layer: "F.CrtYd",
      width: 0.05,
    },
  ],
  model_placement: null,
};

beforeEach(() => {
  mockApi.previewSvg.mockResolvedValue(new Blob(["<svg/>"], { type: "image/svg+xml" }));
  mockApi.modelGlb.mockResolvedValue(new Uint8Array([0x67, 0x6c, 0x54, 0x46]).buffer);
  mockApi.landPattern.mockResolvedValue(LAND);
  mockApi.symbolGeometry.mockResolvedValue(SYMBOL_GEOMETRY);
  mockApi.partHistory.mockResolvedValue({ commits: [], count: 0 });
  mockApi.facets.mockResolvedValue({
    by_category: { ICs: 1 },
    by_manufacturer: {},
    complete: 1,
    incomplete: 0,
    category_catalog: ["ICs"],
  });
});

function provide(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <ToastProvider>
          <CaptureProvider>{ui}</CaptureProvider>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

async function open(dossier: ComponentDossier): Promise<HTMLElement> {
  resetUiSessionForTests(openComponentInSession(defaultUiSession(), ID));
  mockApi.partDossier.mockResolvedValue(dossier);
  provide(<ComponentWorkspace componentId={ID} />);
  await screen.findByText(dossier.identity.mpn);
  return document.querySelector<HTMLElement>('[data-dev-id="component-browser.column-cad"]')!;
}

/** A component holding all three assets, with a preference that offers a real replacement. */
function attached(over: Partial<CadPreferenceView> = {}): ComponentDossier {
  const tool = makeTool({ sourceId: "snapmagic", sourceLabel: "SnapMagic" });
  return makeDossier({
    cadAssets: {
      kinds: {
        symbol: makeRepresentation("symbol", "ready", [tool]),
        footprint: makeRepresentation("footprint", "ready", [tool]),
        model: makeRepresentation("model", "ready", [tool]),
      },
      preference: preference(over),
    },
    keySpecifications: [
      makeSpecification({ key: "pin_count", displayValue: "8", normalizedValue: 8 }),
    ],
  });
}

function module_(kind: string): HTMLElement {
  return document.querySelector<HTMLElement>(
    devIdSelector(componentRepresentationDevId(ID, kind)),
  )!;
}

/* -------------------------------------------------------------- preferred source */

describe("the preferred source is a control, not a caption", () => {
  it("offers every provider the backend allows, and says why a refused one is refused", async () => {
    const column = await open(attached());
    const control = within(column).getByRole("combobox", { name: "Preferred Source" });
    const options = within(control)
      .getAllByRole("option")
      .map((option) => option.textContent ?? "");
    expect(options[1]).toBe("Ultra Librarian");
    // A provider that cannot supply the whole set is LISTED, disabled, carrying its reason -
    // hiding it would answer "why is SamacSys missing" with silence.
    expect(options[2]).toMatch(/SamacSys - SamacSys does not supply the Footprint, 3D Model/);
    expect(within(control).getAllByRole("option")[2]).toBeDisabled();
  });

  it("names the assets a change would replace BEFORE changing anything", async () => {
    const column = await open(attached());
    const user = userEvent.setup();
    await user.selectOptions(
      within(column).getByRole("combobox", { name: "Preferred Source" }),
      "ultralibrarian",
    );

    const dialog = await screen.findByRole("dialog", { name: "Change Preferred Source" });
    expect(within(dialog).getByText(/replaces the source of 2 assets/)).toBeInTheDocument();
    expect(within(dialog).getByText("Symbol: SnapMagic becomes Ultra Librarian")).toBeInTheDocument();
    expect(
      within(dialog).getByText("Footprint: SnapMagic becomes Ultra Librarian"),
    ).toBeInTheDocument();
    // Nothing has been written: the change is shown first, not performed and then reported.
    expect(mockApi.setCadPreferredSource).not.toHaveBeenCalled();
  });

  it("writes only after the change is approved, and writes nothing when it is declined", async () => {
    const column = await open(attached());
    const user = userEvent.setup();
    const control = within(column).getByRole("combobox", { name: "Preferred Source" });

    await user.selectOptions(control, "ultralibrarian");
    await user.click(
      within(await screen.findByRole("dialog", { name: "Change Preferred Source" })).getByRole(
        "button",
        { name: "Cancel" },
      ),
    );
    expect(mockApi.setCadPreferredSource).not.toHaveBeenCalled();

    mockApi.setCadPreferredSource.mockResolvedValue(attached({ pinned: true }));
    await user.selectOptions(control, "ultralibrarian");
    await user.click(
      within(await screen.findByRole("dialog", { name: "Change Preferred Source" })).getByRole(
        "button",
        { name: "Change Source" },
      ),
    );
    await waitFor(() =>
      expect(mockApi.setCadPreferredSource).toHaveBeenCalledWith(ID, "ultralibrarian"),
    );
  });

  it("states the set as Mixed rather than picking one of two providers to show", async () => {
    const column = await open(
      attached({
        provider: "",
        label: "",
        mixed: true,
        assets: {
          symbol: { provider: "snapmagic", label: "SnapMagic", origin: "installed" },
          footprint: { provider: "ultralibrarian", label: "Ultra Librarian", origin: "installed" },
          model: { provider: "snapmagic", label: "SnapMagic", origin: "installed" },
        },
      }),
    );
    const control = within(column).getByRole("combobox", { name: "Preferred Source" });
    expect(within(control).getAllByRole("option")[0]).toHaveTextContent("Mixed");
  });

  it("repeats no provider sentence when all three agree with the column", async () => {
    await open(attached());
    for (const kind of ["symbol", "footprint", "model"]) {
      expect(module_(kind).textContent ?? "").not.toContain("SnapMagic");
    }
  });

  it("states a provider under an asset when that asset's source differs from the set's", async () => {
    await open(
      attached({
        provider: "snapmagic",
        assets: {
          symbol: { provider: "snapmagic", label: "SnapMagic", origin: "set_preference" },
          footprint: {
            provider: "ultralibrarian",
            label: "Ultra Librarian",
            origin: "asset_preference",
          },
          model: { provider: "snapmagic", label: "SnapMagic", origin: "set_preference" },
        },
      }),
    );
    expect(module_("footprint").textContent ?? "").toContain("Ultra Librarian");
    expect(module_("symbol").textContent ?? "").not.toContain("Ultra Librarian");
  });
});

/* -------------------------------------------------------------- module behaviour */

describe("the three modules", () => {
  it("keeps every header AND a preview when one module is focused", async () => {
    const column = await open(attached());
    const user = userEvent.setup();
    // The header IS the control: its name is the asset it names, and its title says which way
    // the click goes. A separate Expand text button would compete with the asset for the line.
    await user.click(within(module_("symbol")).getByRole("button", { name: "Symbol" }));

    // Focusing one asset compacts the other two. It never removes them: comparing a symbol
    // against its footprint is one question, and two views cannot answer it.
    for (const kind of ["symbol", "footprint", "model"]) {
      expect(module_(kind)).toBeInTheDocument();
      expect(
        module_(kind).querySelector('[data-dev-id="component-browser.asset-preview"]'),
      ).toBeInTheDocument();
    }
    expect(module_("symbol").dataset.expanded).toBe("true");
    expect(module_("footprint").dataset.expanded).toBe("false");
    expect(within(column).getByRole("button", { name: "Show All Three" })).toBeInTheDocument();
  });

  it("carries no generic Expand text button, only a maximize control with its full name", async () => {
    const column = await open(attached());
    expect(within(column).queryByRole("button", { name: "Expand" })).toBeNull();
    expect(within(column).queryByRole("button", { name: "Collapse" })).toBeNull();
    expect(
      within(module_("symbol")).getAllByRole("button", { name: "Open Full Preview" }).length,
    ).toBeGreaterThan(0);
  });

  it("renders a status that is text, never a control", async () => {
    await open(attached());
    const status = module_("symbol").querySelector(".ui-status-text");
    expect(status).not.toBeNull();
    expect(status!.tagName).not.toBe("BUTTON");
    expect(status!.closest("button")).toBeNull();
  });
});

/* -------------------------------------------------------------- the state vocabulary */

describe("the nine states", () => {
  const ready = makeRepresentation("symbol", "ready", [makeTool()]);

  it("says Pin Match Failed when the drawn terminals disagree with the pin count", () => {
    expect(
      cadAssetStatus(ready, { terminals: 5, expected: 8, duplicates: 0, unnumbered: 0 }),
    ).toBe("Pin Match Failed");
  });

  it("says Incomplete when a terminal is unnumbered or a number appears twice", () => {
    expect(
      cadAssetStatus(ready, { terminals: 8, expected: 8, duplicates: 1, unnumbered: 0 }),
    ).toBe("Incomplete");
    expect(
      cadAssetStatus(ready, { terminals: 8, expected: 8, duplicates: 0, unnumbered: 2 }),
    ).toBe("Incomplete");
  });

  it("never guesses a comparison the specification does not state", () => {
    // No expected count: the terminals are counted and nothing is claimed about them.
    expect(
      cadAssetStatus(ready, { terminals: 5, expected: null, duplicates: 0, unnumbered: 0 }),
    ).toBe("Available");
  });

  it("says Package Matched when a recorded package check passed", () => {
    const view = makeRepresentation("footprint", "ready", [
      makeTool({
        checks: [
          {
            check: "package_vs_pads",
            measured: "SOIC-8",
            expected: "SOIC-8",
            against: "datasheet rev C",
            checkedAt: "2026-08-01T00:00:00Z",
            note: "",
          },
        ],
      }),
    ]);
    expect(cadAssetStatus(view)).toBe("Package Matched");
  });

  it("never says the vague Ready", () => {
    expect(cadAssetStatus(ready)).toBe("Available");
  });
});

/* -------------------------------------------------------------- the real previews */

describe("the previews are drawn from the file", () => {
  it("draws the symbol's pins and body, and its three visibility switches operate", async () => {
    await open(attached());
    const symbol = module_("symbol");
    await waitFor(() =>
      expect(symbol.querySelector('[data-dev-id="component-browser.symbol-canvas"]')).not.toBeNull(),
    );
    // Both pins are drawn, and both names are on because the file does not hide them.
    expect(symbol.querySelectorAll("line[data-pin]").length).toBe(2);
    expect(within(symbol).getByText("OUT1")).toBeInTheDocument();

    const user = userEvent.setup();
    const names = within(symbol).getByRole("button", { name: "Pin Names" });
    expect(names).toHaveAttribute("aria-pressed", "true");
    await user.click(names);
    expect(names).toHaveAttribute("aria-pressed", "false");
    expect(within(symbol).queryByText("OUT1")).toBeNull();

    // Electrical type is off until asked for, then it is drawn from the pin's own type.
    const electrical = within(symbol).getByRole("button", { name: "Electrical Type" });
    expect(electrical).toHaveAttribute("aria-pressed", "false");
    await user.click(electrical);
    expect(within(symbol).getAllByText("O").length).toBeGreaterThan(0);
  });

  it("draws the land pattern's pads, and says why a layer switch cannot operate", async () => {
    await open(attached());
    const footprint = module_("footprint");
    await waitFor(() =>
      expect(
        footprint.querySelector('[data-dev-id="component-browser.footprint-canvas"]'),
      ).not.toBeNull(),
    );
    expect(footprint.querySelectorAll("rect[data-pad]").length).toBe(2);
    // Pin 1 is always marked when the copper is drawn: every orientation check starts there.
    expect(footprint.querySelector('[data-pin-one="true"]')).not.toBeNull();

    // Only one pad declares a paste layer, so Paste operates. No pad declares silkscreen line
    // work, so Silkscreen is disabled AND says why rather than turning nothing on.
    const silkscreen = within(footprint).getByRole("button", { name: "Silkscreen" });
    expect(silkscreen).toBeDisabled();
    expect(silkscreen.getAttribute("title")).toMatch(/draws nothing on that layer/);

    const user = userEvent.setup();
    const paste = within(footprint).getByRole("button", { name: "Paste" });
    await user.click(paste);
    expect(paste).toHaveAttribute("aria-pressed", "true");
    expect(footprint.querySelectorAll('[data-layer="paste"]').length).toBe(1);
  });

  it("states the evidence it measured, and never a comparison it could not make", async () => {
    await open(attached());
    const line = await waitFor(() => {
      const node = module_("footprint").querySelector(
        '[data-dev-id="component-browser.asset-evidence"]',
      );
      expect(node?.textContent ?? "").toContain("pads");
      return node!;
    });
    // Two pads against a stated pin count of eight, a courtyard, and a real measured size.
    expect(line.textContent).toContain("2/8 pads");
    expect(line.textContent).toContain("Courtyard present");
    expect(line.textContent).toMatch(/mm/);
  });

  it("says a file that cannot be read is unreadable rather than showing an empty frame", async () => {
    mockApi.symbolGeometry.mockRejectedValue(new ApiError(404, "no symbol"));
    await open(attached());
    await waitFor(() =>
      expect(
        within(module_("symbol")).getByText("This file could not be read on this machine"),
      ).toBeInTheDocument(),
    );
  });
});

/* -------------------------------------------------------------- the measurements */

describe("what the drawings measure", () => {
  it("counts pins, duplicate numbers and the drawn body", () => {
    const evidence = symbolEvidence(
      { ...SYMBOL_GEOMETRY, pins: [...SYMBOL_GEOMETRY.pins, SYMBOL_GEOMETRY.pins[0]] },
      8,
    );
    expect(evidence.pins).toBe(3);
    expect(evidence.duplicates).toEqual(["1"]);
    expect(evidence.expectedPins).toBe(8);
    expect(evidence.bounds).toEqual({ width: 12.7, height: 10.16 });
  });

  it("reports the pitch as the most common nearest-neighbour spacing, not an average", () => {
    // Three pads on a 1.27 mm grid plus one deliberately offset: a mean would be dragged away
    // from the spacing every other pad actually sits on.
    const pad = (x: number) => ({ ...LAND.pads[0], at: [x, 0] as [number, number] });
    expect(padPitch([pad(0), pad(1.27), pad(2.54), pad(9)])).toBe(1.27);
  });

  it("reports a missing courtyard and a missing pad 1 as facts, not as silence", () => {
    const evidence = footprintEvidence(
      { ...LAND, graphics: [], pads: [{ ...LAND.pads[1] }] },
      { pins: null, pitch: null },
    );
    expect(evidence.courtyard).toBe(false);
    expect(evidence.hasPinOne).toBe(false);
    expect(evidence.expectedPins).toBeNull();
  });
});
