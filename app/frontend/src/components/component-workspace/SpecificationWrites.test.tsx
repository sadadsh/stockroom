/**
 * Inline specification editing, and the one rule every write here obeys.
 *
 * Each endpoint answers with the FULL updated dossier, and the answer REPLACES the cached document
 * rather than being merged into it. An override does not change one value: it changes that value,
 * its verification state, the conflict state of the row, the group's count, the category
 * completeness score, the header's quality summary and the revision history, all at once. A
 * partial merge would leave most of those stale while looking like it had saved - which is the
 * failure this suite exists to catch.
 *
 * The other half is honesty on failure. A rejected write puts NOTHING in the cache, so the row
 * reverts to exactly what the server last said, and it says so where the person is looking. A
 * write that silently appears to have saved is worse than one that visibly did not.
 *
 * The responses are mocked deliberately. The endpoints are a fixed contract, and a suite that
 * could only run once the server implemented them would be a suite nobody could use to build
 * against the contract.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { ApiError, api } from "../../api/client";
import { cadVariantApi } from "../../api/cadVariantClient";
import type { ComponentDossier, SpecificationRecord } from "../../api/dossierTypes";
import { devIdSelector } from "../../lib/componentDevIds";
import { NBSP } from "../../lib/formatValue";
import { ThemeProvider } from "../../lib/theme";
import { ToastProvider } from "../../lib/toast";
import {
  defaultUiSession,
  openComponentInSession,
  resetUiSessionForTests,
} from "../../lib/uiSession";
import {
  makeCandidate,
  makeDossierWith,
  makeOffer,
  makeSpecification,
} from "../../test/dossierFixture";
import { ComponentWorkspace } from "./ComponentWorkspace";
import { alternateCandidates, displayWithUnit } from "./specificationRows";

vi.mock("../../api/client", async (importActual) => {
  const actual = await importActual<typeof import("../../api/client")>();
  return {
    ...actual,
    api: {
      partDossier: vi.fn(),
      partHistory: vi.fn(),
      partDetail: vi.fn(),
      facets: vi.fn(),
      previewSvg: vi.fn(),
      modelGlb: vi.fn(),
      landPattern: vi.fn(),
      refreshSourcing: vi.fn(),
      setSpecificationOverride: vi.fn(),
      clearSpecificationOverride: vi.fn(),
      setSpecificationPreferredSource: vi.fn(),
      clearSpecificationPreferredSource: vi.fn(),
      documentFile: vi.fn(),
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
    setSpin: vi.fn(),
    setLandPattern: vi.fn(),
    setRenderMode: vi.fn(),
    setLayers: vi.fn(),
    setPlacementMode: vi.fn(),
    modelInfo: vi.fn(() => null),
  })),
}));

const mockApi = vi.mocked(api);
const mockCadVariantApi = vi.mocked(cadVariantApi);
const ID = "lm358";

const DIGIKEY = makeCandidate({
  sourceId: "digikey",
  sourceLabel: "DigiKey",
  tier: "distributor",
  tierLabel: "Authorised Distributor",
  value: "3.3",
  displayValue: "3.3",
});
const MOUSER = makeCandidate({
  sourceId: "mouser",
  sourceLabel: "Mouser",
  tier: "distributor",
  tierLabel: "Authorised Distributor",
  value: "3.0",
  displayValue: "3.0",
});

/**
 * The reviewed decision the projection sends when an override is in force.
 *
 * The row reads THIS, not the winning candidate's source id. A source called "manual" is a value
 * that happens to have arrived unattributed; an override is a decision somebody made, and the two
 * are only the same thing by coincidence of naming.
 */
const REVIEWED = {
  value: "3.6",
  note: "",
  verified: true,
  reviewedBy: "",
  reviewedAt: "2026-08-04T00:00:00Z",
  replacedValue: "3.3",
  replacedSource: "digikey",
  replacedSourceLabel: "DigiKey",
};

/** The disputed row: two distributors, two answers, and every answer carried. */
function disputed(over: Partial<SpecificationRecord> = {}): SpecificationRecord {
  return makeSpecification({
    key: "supply_voltage",
    label: "Supply Voltage",
    displayValue: "3.3",
    unit: "V",
    verificationState: "conflicting",
    conflictState: "conflicting",
    sourceCandidates: [DIGIKEY, MOUSER],
    preferredSource: DIGIKEY,
    ...over,
  });
}

function dossierWith(record: SpecificationRecord): ComponentDossier {
  return makeDossierWith({
    groups: [{ id: "electrical", label: "Electrical", specifications: [record] }],
    distributorOffers: [
      makeOffer({ provider: "mouser", providerLabel: "Mouser", offerUrl: "https://m.invalid/p" }),
    ],
  });
}

beforeEach(() => {
  window.localStorage.clear();
  mockApi.previewSvg.mockResolvedValue(new Blob(["<svg/>"], { type: "image/svg+xml" }));
  mockApi.modelGlb.mockResolvedValue(new Uint8Array([0x67, 0x6c, 0x54, 0x46]).buffer);
  mockApi.landPattern.mockRejectedValue(new ApiError(404, "no footprint"));
  mockApi.partHistory.mockResolvedValue({ commits: [], count: 0 });
  mockCadVariantApi.inventory.mockResolvedValue({
    partId: ID,
    inventories: [],
    pairs: [],
    supplementary: [],
  });
  mockApi.facets.mockResolvedValue({
    by_category: { ICs: 1 },
    by_manufacturer: {},
    complete: 1,
    incomplete: 0,
  });
});

function provide(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <ToastProvider>{ui}</ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

async function open(dossier: ComponentDossier) {
  resetUiSessionForTests(openComponentInSession(defaultUiSession(), ID));
  mockApi.partDossier.mockResolvedValue(dossier);
  const view = provide(<ComponentWorkspace componentId={ID} />);
  await waitFor(() =>
    expect(document.querySelector(devIdSelector("component-browser.header-mpn"))).not.toBeNull(),
  );
  return view;
}

/** Open one row's attached provenance, the way a person does. */
async function evidenceFor(user: ReturnType<typeof userEvent.setup>, key: string) {
  const row = document.querySelector<HTMLElement>(`[data-spec-key="${key}"]`)!;
  await user.click(within(row).getByRole("button", { name: /Source evidence/ }));
  return row;
}

describe("what a specification row shows before anything is written", () => {
  it("puts the alternates on the row they disagree with, with source and tier", async () => {
    const user = userEvent.setup();
    await open(dossierWith(disputed()));
    const row = await evidenceFor(user, "supply_voltage");

    expect(row).toHaveTextContent("In force from DigiKey (Authorised Distributor)");
    const alternate = within(row).getByRole("listitem");
    expect(alternate).toHaveTextContent("3.0");
    expect(alternate).toHaveTextContent("Mouser · Authorised Distributor");
  });

  it("counts an alternate as everything that is not the value in force", () => {
    expect(alternateCandidates(disputed()).map((item) => item.sourceId)).toEqual(["mouser"]);
    // One source agreeing with itself is not an alternate.
    expect(
      alternateCandidates(
        makeSpecification({ sourceCandidates: [DIGIKEY], preferredSource: DIGIKEY }),
      ),
    ).toEqual([]);
  });

  it("joins a value to its unit with a non-breaking space, and never doubles a unit", () => {
    // The pair must never wrap apart: "3.3" on one line and "V" on the next is a different value.
    expect(displayWithUnit(makeSpecification({ displayValue: "3.3", unit: "V" }))).toBe(
      `3.3${NBSP}V`,
    );
    // A range already carrying its unit is re-typeset, not doubled: the en dash stays, and the
    // one unit is bound to the range with a non-breaking space like any other value.
    expect(
      displayWithUnit(makeSpecification({ displayValue: "1.65–5.5 V", unit: "V" })),
    ).toBe(`1.65–5.5${NBSP}V`);
    expect(
      displayWithUnit(makeSpecification({ displayValue: "", verificationState: "missing" })),
    ).toBe("");
  });

  it("offers View Source only where the source has somewhere to go", async () => {
    const user = userEvent.setup();
    const first = await open(dossierWith(disputed()));
    // Mouser has an offer for this part, so its listing is a real destination.
    expect(
      within(await evidenceFor(user, "supply_voltage")).getByRole("link", { name: "View Mouser" }),
    ).toHaveAttribute("href", "https://m.invalid/p");
    first.unmount();

    // A source with no listing and no verified manufacturer page produces no control at all,
    // rather than a link that opens nothing.
    const nowhere = makeCandidate({
      sourceId: "parsed",
      sourceLabel: "Parsed",
      value: "2.7",
      displayValue: "2.7",
    });
    await open(dossierWith(disputed({ sourceCandidates: [DIGIKEY, nowhere] })));
    const second = await evidenceFor(user, "supply_voltage");
    expect(within(second).queryByRole("link", { name: /View/ })).toBeNull();
  });
});

describe("fixed specification source authority", () => {
  it("shows competing evidence without source-ranking controls", async () => {
    const user = userEvent.setup();
    await open(dossierWith(disputed()));

    const row = await evidenceFor(user, "supply_voltage");
    expect(within(row).queryByRole("button", { name: /Use .* Value/ })).toBeNull();
    expect(within(row).queryByRole("button", { name: "Use Ranked Source" })).toBeNull();
    expect(mockApi.setSpecificationPreferredSource).not.toHaveBeenCalled();
    expect(mockApi.clearSpecificationPreferredSource).not.toHaveBeenCalled();
  });
});

describe("recording a reviewed override", () => {
  it("edits in place, saves the typed value, and takes the whole dossier back", async () => {
    const user = userEvent.setup();
    const manual = makeCandidate({
      sourceId: "manual",
      sourceLabel: "Manual Override",
      tier: "manual",
      tierLabel: "Reviewed Override",
      value: "3.6",
      displayValue: "3.6",
    });
    mockApi.setSpecificationOverride.mockResolvedValue(
      dossierWith(
        disputed({
          displayValue: "3.6",
          verificationState: "verified",
          conflictState: "resolved",
          sourceCandidates: [DIGIKEY, MOUSER, manual],
          preferredSource: manual,
        }),
      ),
    );
    await open(dossierWith(disputed()));

    const row = await evidenceFor(user, "supply_voltage");
    await user.click(within(row).getByRole("button", { name: "Add Override" }));

    const input = within(row).getByRole("textbox", { name: "Supply Voltage value" });
    await user.clear(input);
    await user.type(input, "3.6");
    await user.click(within(row).getByRole("button", { name: "Save Value" }));

    // The unit travels INSIDE the value, because the record has no second slot for it, and the
    // reviewer's confidence travels with the same write rather than in a second one.
    await waitFor(() =>
      expect(mockApi.setSpecificationOverride).toHaveBeenCalledWith(
        ID,
        "supply_voltage",
        `3.6${NBSP}V`,
        { note: "", verified: true },
      ),
    );
    await waitFor(() =>
      expect(
        document.querySelector<HTMLElement>('[data-spec-key="supply_voltage"]')!.dataset.specState,
      ).toBe("verified"),
    );
  });

  it("offers Clear Override only once one is actually in force", async () => {
    const user = userEvent.setup();
    const manual = makeCandidate({
      sourceId: "manual",
      sourceLabel: "Manual Override",
      value: "3.6",
      displayValue: "3.6",
    });
    const first = await open(dossierWith(disputed()));
    expect(
      within(await evidenceFor(user, "supply_voltage")).queryByRole("button", {
        name: "Clear Override",
      }),
    ).toBeNull();
    first.unmount();

    await open(
      dossierWith(
        disputed({
          displayValue: "3.6",
          verificationState: "verified",
          sourceCandidates: [DIGIKEY, manual],
          preferredSource: manual,
          override: REVIEWED,
        }),
      ),
    );
    const row = await evidenceFor(user, "supply_voltage");
    expect(within(row).getByRole("button", { name: "Clear Override" })).toBeEnabled();
    // And the editor names itself for what it would do to a value that already has one.
    expect(within(row).getByRole("button", { name: "Edit Override" })).toBeEnabled();
  });

  it("withdraws an override through the delete endpoint", async () => {
    const user = userEvent.setup();
    const manual = makeCandidate({
      sourceId: "manual",
      sourceLabel: "Manual Override",
      value: "3.6",
      displayValue: "3.6",
    });
    mockApi.clearSpecificationOverride.mockResolvedValue(dossierWith(disputed()));
    await open(
      dossierWith(
        disputed({
          displayValue: "3.6",
          verificationState: "verified",
          sourceCandidates: [DIGIKEY, manual],
          preferredSource: manual,
          override: REVIEWED,
        }),
      ),
    );
    const row = await evidenceFor(user, "supply_voltage");
    await user.click(within(row).getByRole("button", { name: "Clear Override" }));

    await waitFor(() =>
      expect(mockApi.clearSpecificationOverride).toHaveBeenCalledWith(ID, "supply_voltage"),
    );
    await waitFor(() =>
      expect(
        document.querySelector<HTMLElement>('[data-spec-key="supply_voltage"]')!.dataset.specState,
      ).toBe("conflicting"),
    );
  });

  it("can put a value on a Missing row, because that is what a gap is for", async () => {
    const user = userEvent.setup();
    const gap = makeSpecification({
      key: "gain_bandwidth",
      label: "Gain Bandwidth",
      verificationState: "missing",
      applicability: "expected",
      expectedForCategory: true,
    });
    mockApi.setSpecificationOverride.mockResolvedValue(
      dossierWith(
        makeSpecification({
          key: "gain_bandwidth",
          label: "Gain Bandwidth",
          displayValue: "1.1",
          unit: "MHz",
          verificationState: "verified",
        }),
      ),
    );
    await open(dossierWith(gap));

    const row = await evidenceFor(user, "gain_bandwidth");
    await user.click(within(row).getByRole("button", { name: "Add Override" }));
    await user.type(within(row).getByRole("textbox", { name: "Gain Bandwidth value" }), "1.1");
    await user.click(within(row).getByRole("button", { name: "Save Value" }));

    await waitFor(() =>
      expect(mockApi.setSpecificationOverride).toHaveBeenCalledWith(
        ID,
        "gain_bandwidth",
        "1.1",
        { note: "", verified: true },
      ),
    );
  });
});

describe("a write that does not save", () => {
  it("reverts the row and says so beside it, rather than appearing to have saved", async () => {
    const user = userEvent.setup();
    mockApi.setSpecificationOverride.mockRejectedValue(
      new ApiError(422, "3.6 is above the category maximum of 3.6 V"),
    );
    await open(dossierWith(disputed()));

    const row = await evidenceFor(user, "supply_voltage");
    await user.click(within(row).getByRole("button", { name: "Add Override" }));
    await user.type(within(row).getByRole("textbox", { name: "Supply Voltage value" }), "9");
    await user.click(within(row).getByRole("button", { name: "Save Value" }));

    const failure = await within(row).findByRole("alert");
    expect(failure).toHaveTextContent("above the category maximum");
    // The value in force is untouched: nothing was written to the cache at all.
    expect(row.dataset.specState).toBe("conflicting");
    expect(row).toHaveTextContent("3.3 V");
  });

});

describe("a constraint the category itself declares", () => {
  it("reports the violation and leaves the source's value exactly as it was given", async () => {
    await open(
      dossierWith(
        disputed({
          constraint: { minimum: 1.65, maximum: 5.5, unit: "V", allowed: [], note: "" },
          constraintViolation: "above the maximum of 5.5V",
        }),
      ),
    );
    const row = document.querySelector<HTMLElement>('[data-spec-key="supply_voltage"]')!;
    expect(within(row).getByText(/above the maximum of 5.5V/)).toBeInTheDocument();
    // Rewriting a distributor's answer to satisfy our own rule would hide the disagreement.
    expect(row).toHaveTextContent("3.3 V");
  });
});

describe("the column stays a renderer", () => {
  it("shows a specification's own importance so the row weight is not guessed", async () => {
    await open(
      makeDossierWith({
        keySpecifications: [
          makeSpecification({ key: "supply_voltage", displayValue: "3.3", importance: "key" }),
        ],
        groups: [
          {
            id: "electrical",
            label: "Electrical",
            specifications: [
              makeSpecification({ key: "slew_rate", displayValue: "0.5", importance: "secondary" }),
            ],
          },
        ],
      }),
    );
    const key = document.querySelector<HTMLElement>('[data-spec-key="supply_voltage"]')!;
    const ordinary = document.querySelector<HTMLElement>('[data-spec-key="slew_rate"]')!;
    expect(key.dataset.specImportance).toBe("key");
    expect(ordinary.dataset.specImportance).toBe("secondary");
    // The key block is the FIRST thing in the column, above every group. Scoped to the section
    // headings: the anchor strip names the same headings, and it sits above both.
    const headings = [
      ...document.querySelectorAll<HTMLElement>(
        devIdSelector("component-browser.spec-group-toggle"),
      ),
    ].map((button) => button.textContent ?? "");
    expect(headings[0]).toContain("Main Specifications");
    expect(headings[1]).toContain("Electrical");
  });
});

describe("the attached editor covers the whole decision", () => {
  /** Open one row's editor, the way a person does. */
  async function editorFor(user: ReturnType<typeof userEvent.setup>, key: string) {
    const row = await evidenceFor(user, key);
    await user.click(within(row).getByRole("button", { name: "Add Override" }));
    return row;
  }

  it("offers a labelled control for every part of the decision, not one unnamed box", async () => {
    const user = userEvent.setup();
    await open(dossierWith(disputed()));
    const row = await editorFor(user, "supply_voltage");
    const editor = within(row);

    // The value decision is explicit; source precedence is fixed by the product.
    expect(editor.getByRole("textbox", { name: "Supply Voltage value" })).toBeInTheDocument();
    expect(editor.getByRole("textbox", { name: "Unit" })).toHaveValue("V");
    expect(editor.getByRole("combobox", { name: "Value Kind" })).toHaveValue("quantity");
    expect(editor.queryByRole("combobox", { name: "Source" })).toBeNull();
    expect(editor.getByRole("combobox", { name: "Verification Status" })).toHaveValue("verified");
    expect(editor.getByRole("textbox", { name: "Reason" })).toBeInTheDocument();
    expect(editor.queryByRole("checkbox", { name: "Prefer this value over all sources" })).toBeNull();
  });

  it("keeps every label on screen while the field is being typed into", async () => {
    const user = userEvent.setup();
    await open(dossierWith(disputed()));
    const row = await editorFor(user, "supply_voltage");
    const reason = within(row).getByRole("textbox", { name: "Reason" });
    await user.type(reason, "reel label");
    // A placeholder is never the only name a field has: it vanishes at the first keystroke.
    expect(within(row).getByRole("textbox", { name: "Reason" })).toHaveValue("reel label");
  });

  it("carries the reason and the verification status on the one write", async () => {
    const user = userEvent.setup();
    mockApi.setSpecificationOverride.mockResolvedValue(dossierWith(disputed()));
    await open(dossierWith(disputed()));
    const row = await editorFor(user, "supply_voltage");

    const value = within(row).getByRole("textbox", { name: "Supply Voltage value" });
    await user.clear(value);
    await user.type(value, "3.6");
    await user.type(within(row).getByRole("textbox", { name: "Reason" }), "measured");
    await user.selectOptions(
      within(row).getByRole("combobox", { name: "Verification Status" }),
      "unverified",
    );
    await user.click(within(row).getByRole("button", { name: "Save Value" }));

    await waitFor(() =>
      expect(mockApi.setSpecificationOverride).toHaveBeenCalledWith(
        ID,
        "supply_voltage",
        `3.6${NBSP}V`,
        { note: "measured", verified: false },
      ),
    );
  });

  it("never converts a reviewed value edit into a source-ranking write", async () => {
    const user = userEvent.setup();
    mockApi.setSpecificationOverride.mockResolvedValue(dossierWith(disputed()));
    await open(dossierWith(disputed()));
    const row = await editorFor(user, "supply_voltage");

    await user.click(within(row).getByRole("button", { name: "Save Value" }));

    await waitFor(() => expect(mockApi.setSpecificationOverride).toHaveBeenCalled());
    expect(mockApi.setSpecificationPreferredSource).not.toHaveBeenCalled();
  });

  it("refuses a value the category's own rule forbids, and says what the rule is", async () => {
    const user = userEvent.setup();
    await open(
      dossierWith(
        disputed({
          constraint: { minimum: 1.65, maximum: 5.5, unit: "V", allowed: [], note: "" },
        }),
      ),
    );
    const row = await editorFor(user, "supply_voltage");
    const value = within(row).getByRole("textbox", { name: "Supply Voltage value" });
    await user.clear(value);
    await user.type(value, "9");
    await user.click(within(row).getByRole("button", { name: "Save Value" }));

    // Nothing was sent at all, and the correction is stated beside the field rather than guessed.
    expect(mockApi.setSpecificationOverride).not.toHaveBeenCalled();
    expect(await within(row).findByRole("alert")).toHaveTextContent(
      "This field cannot be above 5.5 V",
    );
    // The row still shows exactly what the library holds.
    expect(row).toHaveTextContent("3.3 V");
  });

  it("refuses a unit the field is not measured in, and names the one it is", async () => {
    const user = userEvent.setup();
    await open(
      dossierWith(
        disputed({
          constraint: { minimum: 1.65, maximum: 5.5, unit: "V", allowed: [], note: "" },
        }),
      ),
    );
    const row = await editorFor(user, "supply_voltage");
    const unit = within(row).getByRole("textbox", { name: "Unit" });
    await user.clear(unit);
    await user.type(unit, "A");
    await user.click(within(row).getByRole("button", { name: "Save Value" }));

    expect(mockApi.setSpecificationOverride).not.toHaveBeenCalled();
    expect(await within(row).findByRole("alert")).toHaveTextContent("measured in V");
  });

  it("puts a failed write beside the editor, with the edit still in front of the person", async () => {
    const user = userEvent.setup();
    mockApi.setSpecificationOverride.mockRejectedValue(
      new ApiError(422, "no canonical specification is named that"),
    );
    await open(dossierWith(disputed()));
    const row = await editorFor(user, "supply_voltage");
    await user.click(within(row).getByRole("button", { name: "Save Value" }));

    const failure = await within(row).findByRole("alert");
    expect(failure).toHaveTextContent("no canonical specification is named that");
    // Attached to the editor that failed, not to the row's control strip and not to a toast.
    expect(
      failure.closest(devIdSelector("component-browser.spec-editor")),
    ).not.toBeNull();
    // And the row REVERTED: nothing was written to the cache.
    expect(row.dataset.specState).toBe("conflicting");
    expect(within(row).getByRole("textbox", { name: "Supply Voltage value" })).toBeInTheDocument();
  });

  it("closes on Escape and hands focus back to the control that opened it", async () => {
    const user = userEvent.setup();
    await open(dossierWith(disputed()));
    const row = await editorFor(user, "supply_voltage");
    expect(within(row).getByRole("textbox", { name: "Supply Voltage value" })).toHaveFocus();

    await user.keyboard("{Escape}");

    expect(within(row).queryByRole("textbox", { name: "Supply Voltage value" })).toBeNull();
    await waitFor(() =>
      expect(within(row).getByRole("button", { name: "Add Override" })).toHaveFocus(),
    );
  });

  it("is not offered at all on a field the category says does not apply", async () => {
    await open(
      dossierWith(
        makeSpecification({
          key: "program_memory_size",
          label: "Program Memory Size",
          verificationState: "not_applicable",
          applicability: "not_applicable",
        }),
      ),
    );
    const row = document.querySelector<HTMLElement>(
      '[data-spec-key="program_memory_size"]',
    )!;
    // The row is still emitted - a reader looking for the field learns it does not exist here
    // rather than wondering - but nothing offers to fill a gap nobody can fill.
    // A quiet state at rest: the dash, with the exact word as the cell's accessible name.
    expect(
      row.querySelector('[data-dev-id="component-browser.spec-value"]'),
    ).toHaveAccessibleName("Not Applicable");
    expect(within(row).queryByRole("button", { name: "Add Override" })).toBeNull();
    expect(within(row).queryByRole("button", { name: /Source evidence/ })).toBeNull();
  });
});

describe("how a value is weighted, and when it says where it came from", () => {
  it("spends weight 500 on key facts, disagreements and gaps - and on nothing else", async () => {
    await open(
      makeDossierWith({
        keySpecifications: [makeSpecification({ key: "supply_voltage", importance: "key" })],
        groups: [
          {
            id: "electrical",
            label: "Electrical",
            specifications: [
              makeSpecification({ key: "slew_rate", displayValue: "0.5" }),
              disputed({ key: "output_current", label: "Output Current" }),
            ],
          },
        ],
      }),
    );
    const weightOf = (key: string) =>
      document
        .querySelector(`[data-spec-key="${key}"] [data-dev-id="component-browser.spec-value"]`)!
        .className.includes("font-medium");

    expect(weightOf("supply_voltage")).toBe(true); // a key fact
    expect(weightOf("output_current")).toBe(true); // sources disagree: needs review
    expect(weightOf("slew_rate")).toBe(false); // an ordinary value, at the body weight
  });

  it("states a retrieval time relatively, with the exact time one hover away", async () => {
    const user = userEvent.setup();
    const dated = makeCandidate({
      sourceId: "digikey",
      sourceLabel: "DigiKey",
      value: "3.3",
      displayValue: "3.3",
      retrievedAt: "2026-08-05T14:42:00",
    });
    await open(dossierWith(disputed({ sourceCandidates: [dated], preferredSource: dated })));
    const row = await evidenceFor(user, "supply_voltage");

    // A relative time on its own cannot be turned back into a date, so it never travels alone.
    const stamp = within(row).getByTitle("Aug 5, 2026, 2:42 PM");
    expect(stamp).toHaveTextContent(/Retrieved/);
  });
});
