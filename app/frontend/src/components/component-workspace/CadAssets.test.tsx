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
import { runtimeDesignId } from "../../lib/designIdentity";
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
import { footprintEvidence, padPitch, symbolEvidence } from "./cadEvidence";
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

function emptyPreference(over: Partial<CadPreferenceView> = {}): CadPreferenceView {
  return preference({
    provider: "",
    label: "",
    mixed: false,
    pinned: false,
    assets: {
      symbol: { provider: "", label: "", origin: "" },
      footprint: { provider: "", label: "", origin: "" },
      model: { provider: "", label: "", origin: "" },
    },
    options: [],
    ...over,
  });
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
  it("omits an empty None recorded row but keeps Show All Three when an asset is focused", async () => {
    const column = await open(attached(emptyPreference()));
    expect(within(column).queryByRole("combobox", { name: "Preferred Source" })).toBeNull();

    const user = userEvent.setup();
    await user.click(within(module_("symbol")).getByRole("button", { name: "Symbol" }));
    const showAll = within(column).getByRole("button", { name: "Show All Three" });
    expect(showAll).toBeInTheDocument();
    await user.click(showAll);
    expect(within(column).queryByRole("button", { name: "Show All Three" })).toBeNull();
  });

  it("keeps a provider fact even when there is no alternative choice", async () => {
    const column = await open(
      attached(emptyPreference({ provider: "snapmagic", label: "SnapMagic" })),
    );
    expect(within(column).getByRole("combobox", { name: "Preferred Source" })).toHaveValue("");
    expect(within(column).getByRole("option", { name: "SnapMagic" })).toBeInTheDocument();
  });

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
  it("divides the available pane height between assets without a CAD scrollbar", async () => {
    const column = await open(attached());
    const body = column.querySelector<HTMLElement>('[data-workspace-scroll="cad"]')!;
    expect(body).toHaveClass("overflow-hidden");
    expect(body).not.toHaveClass("overflow-y-auto");
    for (const kind of ["symbol", "footprint", "model"]) {
      expect(module_(kind)).toHaveClass("flex-1");
      expect(
        module_(kind).querySelector('[data-dev-id="component-browser.asset-preview"]'),
      ).toHaveClass("flex-1");
    }
  });

  it("gives attached previews the height missing assets would otherwise consume", async () => {
    const dossier = attached();
    dossier.cadAssets.kinds.footprint = makeRepresentation("footprint", "missing", []);
    dossier.cadAssets.kinds.model = makeRepresentation("model", "missing", []);
    await open(dossier);

    expect(module_("symbol")).toHaveClass("flex-1");
    expect(
      module_("symbol").querySelector('[data-dev-id="component-browser.asset-preview"]'),
    ).toHaveClass("flex-1");
    for (const kind of ["footprint", "model"]) {
      expect(module_(kind)).toHaveClass("flex-none");
      expect(
        module_(kind).querySelector('[data-dev-id="component-browser.asset-preview"]'),
      ).toHaveClass("h-[40px]", "flex-none");
    }
  });

  it("keeps an all-missing CAD set compact without removing its asset workflow", async () => {
    const dossier = attached(emptyPreference());
    for (const kind of ["symbol", "footprint", "model"] as const) {
      dossier.cadAssets.kinds[kind] = makeRepresentation(kind, "missing", []);
    }
    await open(dossier);

    for (const kind of ["symbol", "footprint", "model"]) {
      expect(module_(kind)).toHaveClass("flex-none");
      expect(
        module_(kind).querySelector('[data-dev-id="component-browser.asset-preview"]'),
      ).toHaveClass("h-[40px]");
    }
    expect(screen.getByRole("button", { name: "Manage CAD Assets" })).toBeVisible();
  });

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
    // And the module header's tooltip names what pressing it DOES, rather than a state the control
    // does not have: at rest all three are expanded, so "Collapse" described nothing.
    expect(
      module_("symbol")
        .querySelector('[data-dev-id="component-browser.asset-header"]')!
        .getAttribute("title"),
    ).toBe("Focus This Asset");
    expect(
      within(module_("symbol")).getAllByRole("button", { name: "Open Full Preview" }).length,
    ).toBeGreaterThan(0);
  });

  it("leaves the expanded preview a surface, not a second control with the maximize button's name", async () => {
    // Two faults, one cause. `button` takes PRESENTATIONAL CHILDREN, so a widget role on this
    // container deletes its whole subtree from the accessibility tree - and while the module is
    // expanded that subtree is the asset's control surface (the 3D settings popover, the maximize
    // control riding inside the viewer, the land pattern's measure target). At the same time the
    // role put a SECOND control named "Open Full Preview" in every expanded module, beside the
    // real maximize button that already had that name. The stage carried role="button" in both
    // states, so both faults were live at rest, on all three modules at once.
    await open(attached());
    const symbol = module_("symbol");
    expect(symbol.dataset.expanded).toBe("true");
    const stage = symbol.querySelector<HTMLElement>(
      '[data-dev-id="component-browser.asset-preview"]',
    )!;
    expect(stage.tagName).toBe("DIV");
    expect(stage.getAttribute("role")).toBeNull();
    // One name, one control. The maximize button is the one, and it is not the stage.
    const named = within(symbol).getAllByRole("button", { name: "Open Full Preview" });
    expect(named).toHaveLength(1);
    expect(named[0]).not.toBe(stage);
  });

  it("makes the COMPACT preview a real button, so Space opens the full preview too", async () => {
    // Compact, `interactive={false}` switches every child's controls off, so the subtree is inert
    // and nothing is swallowed - which is what lets the stage be a real control. A native <button>
    // is what earns Space; the div-with-a-role it replaced answered Enter only, because a div gets
    // no keyboard behaviour of its own.
    const user = userEvent.setup();
    await open(attached());
    await user.click(within(module_("symbol")).getByRole("button", { name: "Symbol" }));
    expect(module_("footprint").dataset.expanded).toBe("false");

    const stage = module_("footprint").querySelector<HTMLElement>(
      '[data-dev-id="component-browser.asset-preview"]',
    )!;
    expect(stage.tagName).toBe("BUTTON");
    // The accessible name states the COMPLETE action, not a truncated visible label.
    expect(stage.getAttribute("aria-label")).toBe("Open Full Preview");

    stage.focus();
    expect(document.activeElement).toBe(stage);
    await user.keyboard(" ");
    await waitFor(() => {
      expect(screen.getByRole("dialog", { name: /^Inspect / })).toBeInTheDocument();
    });
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
    // The switches live behind the preview's one visibility button, not on a row above it.
    await user.click(within(symbol).getByRole("button", { name: "Show Or Hide Drawn Detail" }));
    const names = within(symbol).getByRole("checkbox", { name: "Pin Names" });
    expect(names).toBeChecked();
    await user.click(names);
    expect(names).not.toBeChecked();
    expect(within(symbol).queryByText("OUT1")).toBeNull();

    // Electrical type is off until asked for, then it is drawn from the pin's own type.
    const electrical = within(symbol).getByRole("checkbox", { name: "Electrical Type" });
    expect(electrical).not.toBeChecked();
    await user.click(electrical);
    expect(within(symbol).getAllByText("O").length).toBeGreaterThan(0);
  });

  it("closes a visibility panel on Escape and hands focus back to its button", async () => {
    await open(attached());
    const symbol = module_("symbol");
    await waitFor(() =>
      expect(symbol.querySelector('[data-dev-id="component-browser.symbol-canvas"]')).not.toBeNull(),
    );
    const user = userEvent.setup();
    const button = within(symbol).getByRole("button", { name: "Show Or Hide Drawn Detail" });
    await user.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");

    await user.keyboard("{Escape}");
    expect(button).toHaveAttribute("aria-expanded", "false");
    // Focus lands back on the control that opened it, not on the page behind the panel, and the
    // opened component is still open: this Escape is answered here and goes no further.
    expect(button).toHaveFocus();
    expect(screen.getByText(makeDossier().identity.mpn)).toBeInTheDocument();
  });

  it("uses one technical sheet background for model, footprint, and schematic", async () => {
    await open(attached());
    const canvases = [
      await within(module_("model")).findByTestId("model-canvas"),
      module_("footprint").querySelector('[data-dev-id="component-browser.footprint-canvas"]'),
      module_("symbol").querySelector('[data-dev-id="component-browser.symbol-canvas"]'),
    ];
    for (const canvas of canvases) expect(canvas).toHaveClass("bg-technical");
  });

  it("starts the mini 3D preview without the PCB slab", async () => {
    await open(attached());
    const model = module_("model");
    const user = userEvent.setup();
    const settings = await within(model).findByRole("button", { name: "3D view settings" });
    await user.click(settings);
    expect(within(model).getByRole("button", { name: "PCB" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
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
    // The downloaded pad geometry already identifies pad 1. Do not add a second red ring over it.
    expect(footprint.querySelector('[data-pin-one="true"]')).toBeNull();

    const user = userEvent.setup();
    await user.click(within(footprint).getByRole("button", { name: "Show Or Hide Drawn Detail" }));

    // Only one pad declares a paste layer, so Paste operates. No pad declares silkscreen line
    // work, so Silkscreen is disabled AND says why rather than turning nothing on. Inside the
    // panel the reason is READABLE as well as a tooltip, which a hover-only reason never was.
    const silkscreen = within(footprint).getByRole("checkbox", { name: /Silkscreen/ });
    expect(silkscreen).toBeDisabled();
    expect(
      within(footprint).getAllByText("This footprint draws nothing on that layer").length,
    ).toBeGreaterThan(0);

    const paste = within(footprint).getByRole("checkbox", { name: "Paste" });
    await user.click(paste);
    expect(paste).toBeChecked();
    expect(footprint.querySelectorAll('[data-layer="paste"]').length).toBe(1);
  });

  /**
   * THE ROWS OF PILLS MUST NOT COME BACK.
   *
   * The column carried its layer switches as always-visible outlined pills: three under the symbol
   * and ten under the land pattern, wrapped across three or four rows each in a ~300px column, plus
   * two toolbar rows above the first preview. Counted, that was fourteen bordered controls before
   * the first piece of evidence, and the owner read the whole column as noise. Every switch still
   * exists - it is a row in the panel above - so the guard is on the STRIP, which may hold only
   * icon controls, and on the module, which may hold no checkbox until one is asked for.
   */
  it("keeps every visibility switch off the strip until its button is pressed", async () => {
    await open(attached());
    await waitFor(() =>
      expect(
        module_("symbol").querySelector('[data-dev-id="component-browser.symbol-canvas"]'),
      ).not.toBeNull(),
    );
    for (const kind of ["symbol", "footprint", "model"]) {
      const node = module_(kind);
      // No switch is on screen at rest, in any of the three modules.
      expect(within(node).queryAllByRole("checkbox")).toEqual([]);
      const strip = node.querySelector<HTMLElement>(
        '[data-dev-id="component-browser.asset-control-strip"]',
      );
      if (!strip) continue;
      // Every control on the strip is an ICON control: it names itself with an accessible label
      // and renders no text run, so the strip cannot grow back into a row of labelled pills.
      const controls = Array.from(strip.querySelectorAll("button"));
      expect(controls.length).toBeGreaterThan(0);
      expect(controls.length).toBeLessThanOrEqual(3);
      for (const control of controls) {
        expect(control.getAttribute("aria-label")).toBeTruthy();
        expect(control.textContent?.trim()).toBe("");
      }
    }
  });

  it("keeps the measured evidence off the resting column and states it on the focused module", async () => {
    const user = userEvent.setup();
    await open(attached());
    // AT REST the column stacks three drawings and states no counts under any of them. It used to
    // put a line under each - `2 pins · No duplicates`, `2 pads · 0.96 mm pitch · Courtyard present ·
    // 1.80 x 0.84 mm`, `No file is attached` - which is three lines of measurement nobody asked for
    // above the specifications the component was opened to read.
    await waitFor(() =>
      expect(
        module_("footprint").querySelector('[data-dev-id="component-browser.footprint-canvas"]'),
      ).not.toBeNull(),
    );
    for (const kind of ["model", "footprint", "symbol"]) {
      expect(
        module_(kind).querySelector('[data-dev-id="component-browser.asset-evidence"]'),
      ).toBeNull();
    }

    // FOCUS the footprint - clicking its header is the same control that already reduced the other
    // two to compact previews - and the module states what it measured.
    await user.click(
      module_("footprint").querySelector<HTMLElement>(
        '[data-dev-id="component-browser.asset-header"]',
      )!,
    );
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

  it("never hides a recorded fault behind the focus, whatever else the footer stops saying", async () => {
    // The one thing the evidence footer carried that a person must not have to ask for. The module
    // header's status word says THAT something is wrong in every state; this says WHAT, and it is
    // rendered at rest with the three previews stacked.
    const tool = makeTool({ sourceId: "snapmagic", sourceLabel: "SnapMagic" });
    const dossier = attached();
    await open({
      ...dossier,
      cadAssets: {
        ...dossier.cadAssets,
        kinds: {
          ...dossier.cadAssets.kinds,
          footprint: {
            ...makeRepresentation("footprint", "review", [tool]),
            issue: "The land pattern declares no courtyard.",
          },
        },
      },
    });
    const issue = await waitFor(() =>
      within(module_("footprint")).getByText("The land pattern declares no courtyard."),
    );
    expect(issue).toBeInTheDocument();
    expect(
      module_("footprint").querySelector('[data-dev-id="component-browser.asset-evidence"]'),
    ).toBeNull();
  });

  it("uses one accessible question mark where no file is attached without repeating Missing", async () => {
    // The question mark is the visual statement. The exact Missing state remains screen-reader text,
    // data-status and the module's accessible asset name; inert visibility controls do not render.
    await open(
      makeDossier({
        cadAssets: {
          kinds: {
            symbol: makeRepresentation("symbol", "missing", []),
            footprint: makeRepresentation("footprint", "missing", []),
            model: makeRepresentation("model", "missing", []),
          },
          preference: preference(),
        },
      }),
    );
    for (const kind of ["model", "footprint", "symbol"]) {
      const node = module_(kind);
      const status = await waitFor(() => within(node).getByText("Missing"));
      expect(status).toHaveClass("sr-only");
      expect(node).toHaveAttribute("data-status", "Missing");
      expect(node).toHaveAccessibleName(kind === "model" ? "3D Model" : kind === "footprint" ? "Footprint" : "Symbol");
      expect(within(node).queryByText("No file is attached")).toBeNull();
      expect(within(node).queryByText("No file is attached yet.")).toBeNull();
      expect(node.querySelector('[data-dev-id="component-browser.asset-issue"]')).toBeNull();
      expect(node.querySelector('[data-dev-id="component-browser.asset-control-strip"]')).toBeNull();
      const art = node.querySelector<HTMLElement>(
        '[data-dev-id="component-browser.asset-missing-art"]',
      );
      expect(art).toHaveAttribute("aria-hidden", "true");
      const icon = art?.querySelector("svg");
      expect(icon).toHaveAttribute(
        "data-design-id",
        runtimeDesignId("icon", "status.cad-missing"),
      );
      expect(icon).toHaveClass("opacity-50");
      expect(icon).toHaveClass("h-6");
      expect(icon).toHaveClass("w-6");
    }
  });

  it("says a file that cannot be read is unreadable rather than showing an empty frame", async () => {
    mockApi.symbolGeometry.mockRejectedValue(new ApiError(404, "no symbol"));
    await open(attached());
    await waitFor(() =>
      expect(
        within(module_("symbol")).getByText("This file could not be read on this machine"),
      ).toBeInTheDocument(),
    );
    expect(
      module_("symbol").querySelector('[data-dev-id="component-browser.asset-missing-art"]'),
    ).toBeNull();
    expect(
      module_("symbol").querySelector('[data-dev-id="component-browser.asset-control-strip"]'),
    ).toBeInTheDocument();
    expect(
      module_("symbol").querySelector('[data-dev-id="component-browser.cad-status"]'),
    ).not.toHaveClass("sr-only");
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
