import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type ReactNode } from "react";
import {
  CompatibilityWorkbench,
  benchExport,
  benchSets,
  packageKind,
  packagesForScope,
} from "./CompatibilityWorkbench";
import { api, ApiError } from "../../api/client";
import type { FamiliesResponse, SuggestionsResponse, UnionDTO } from "../../api/types";

const FAMILIES: FamiliesResponse = {
  families: [
    { family: "STM32F4", lines: ["STM32F407"], mcu_count: 40, packages: ["LQFP100", "LQFP144"] },
    { family: "STM32F7", lines: ["STM32F746"], mcu_count: 20, packages: ["LQFP144"] },
  ],
};

const SUGGESTIONS: SuggestionsResponse = {
  groups: [
    {
      signature_id: "sig-base",
      tier: "baseline",
      package: "LQFP144",
      family: "STM32F4 + STM32F7",
      refs: ["STM32F429ZET6", "STM32F746ZGT6"],
      divergent_positions: 0,
    },
    {
      signature_id: "sig-div-a",
      tier: "divergent",
      package: "LQFP144",
      family: "STM32F4 + STM32F7",
      refs: ["STM32F407ZGT6"],
      divergent_positions: 12,
    },
  ],
};

function unionResult(): UnionDTO {
  return {
    parts: ["STM32F429ZET6", "STM32F746ZGT6", "STM32F407ZGT6"],
    resolved: [
      { ref: "STM32F429ZET6", mpn: "STM32F429ZET6" },
      { ref: "STM32F746ZGT6", mpn: "STM32F746ZGT6" },
      { ref: "STM32F407ZGT6", mpn: "STM32F407ZGT6" },
    ],
    package: "LQFP144",
    family: "STM32F4 + STM32F7",
    families: ["STM32F4", "STM32F7"],
    grain: "per-part",
    positions: [
      {
        position: "1",
        position_kind: "numeric",
        lqfp_side: "left",
        bga_row: null,
        bga_col: null,
        classification: "shared",
        present_on: 3,
        total: 3,
        per_part: [],
        reconcile: null,
      },
      {
        position: "23",
        position_kind: "numeric",
        lqfp_side: "left",
        bga_row: null,
        bga_col: null,
        classification: "divergent",
        present_on: 3,
        total: 3,
        per_part: [
          { ref: "STM32F429ZET6", canonical_pin_name: "PA9", roles: [], functions: ["USART1_TX"] },
          { ref: "STM32F746ZGT6", canonical_pin_name: "PA9", roles: [], functions: ["USART1_TX"] },
          { ref: "STM32F407ZGT6", canonical_pin_name: "PA9", roles: [], functions: ["ETH_TXD3"] },
        ],
        reconcile: {
          swappable: false,
          swaps: [],
          reason: "STM32F407ZGT6 offers no alternate function carrying USART1_TX here",
        },
      },
    ],
    verdict: {
      interchangeable: false,
      swaps_required: 0,
      blocking: [{ position: "23", signal: "USART1_TX", reason: "no AF carries it" }],
    },
  };
}

function wrapperWith(qc: QueryClient) {
  return ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children);
}

function freshClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

afterEach(() => vi.restoreAllMocks());

describe("packagesForScope", () => {
  it("unions packages across the selected families with honest coverage", () => {
    const out = packagesForScope(FAMILIES.families, ["STM32F4", "STM32F7"]);
    const byName = Object.fromEntries(out.map((p) => [p.name, p]));
    // LQFP100 exists on F4 only: still LISTED, with F7 named as missing
    expect(byName.LQFP100.covered).toEqual(["STM32F4"]);
    expect(byName.LQFP100.missing).toEqual(["STM32F7"]);
    // LQFP144 is fully covered
    expect(byName.LQFP144.covered).toEqual(["STM32F4", "STM32F7"]);
    expect(byName.LQFP144.missing).toEqual([]);
  });
});

describe("packageKind", () => {
  it("classifies package names for the filter chips", () => {
    expect(packageKind("LQFP144")).toBe("LQFP");
    expect(packageKind("UFQFPN48")).toBe("QFN");
    expect(packageKind("UFBGA176")).toBe("BGA");
    expect(packageKind("WLCSP81")).toBe("CSP");
    expect(packageKind("TSSOP20")).toBe("Other");
  });
});

describe("benchSets", () => {
  it("builds the stepper: All Parts first, then Baseline, then lettered divergent groups", () => {
    const sets = benchSets(SUGGESTIONS.groups, 3);
    expect(sets.map((s) => s.label)).toEqual(["All Parts", "Baseline", "Divergent A"]);
    expect(sets[0].refs).toBeNull();
    expect(sets[0].count).toBe(3);
    expect(sets[2].divergent).toBe(12);
  });
});

describe("benchExport", () => {
  it("bundles the scope, every set, and the active union for the build-card pipeline", () => {
    const sets = benchSets(SUGGESTIONS.groups, 3);
    const parsed = JSON.parse(
      benchExport({ families: ["STM32F4", "STM32F7"], package: "LQFP144" }, sets, unionResult()),
    );
    expect(parsed.format).toBe("stm-bench/1");
    expect(parsed.scope.package).toBe("LQFP144");
    expect(parsed.sets).toHaveLength(3);
    expect(parsed.active_set.verdict.interchangeable).toBe(false);
    expect(parsed.active_set.positions.some((p: { position: string }) => p.position === "23")).toBe(
      true,
    );
  });
});

describe("CompatibilityWorkbench (the Bench)", () => {
  function mockScope() {
    vi.spyOn(api, "getStmFamilies").mockResolvedValue(FAMILIES);
    const suggSpy = vi.spyOn(api, "getStmCompatSuggestions").mockResolvedValue(SUGGESTIONS);
    const unionSpy = vi.spyOn(api, "postStmCompatUnion").mockResolvedValue(unionResult());
    return { suggSpy, unionSpy };
  }

  async function pickScope() {
    fireEvent.click(await screen.findByText("STM32F4"));
    fireEvent.click(await screen.findByText("STM32F7"));
    fireEvent.click(await screen.findByRole("button", { name: /LQFP144/ }));
  }

  it("shows the UNION of packages with coverage badges, and filters them", async () => {
    mockScope();
    render(<CompatibilityWorkbench />, { wrapper: wrapperWith(freshClient()) });
    fireEvent.click(await screen.findByText("STM32F4"));
    fireEvent.click(await screen.findByText("STM32F7"));

    const grid = await screen.findByTestId("bench-packages");
    // LQFP100 is present despite F7 lacking it, badged 1/2
    const lqfp100 = within(grid).getByRole("button", { name: /LQFP100/ });
    expect(within(lqfp100).getByText("1/2")).toBeInTheDocument();
    // full-coverage LQFP144 carries no badge
    const lqfp144 = within(grid).getByRole("button", { name: /LQFP144/ });
    expect(within(lqfp144).queryByText("2/2")).toBeNull();

    // the text filter narrows the grid
    fireEvent.change(screen.getByLabelText("Filter Packages"), { target: { value: "144" } });
    expect(within(grid).queryByRole("button", { name: /LQFP100/ })).toBeNull();
  });

  it("auto-computes the sets and auto-unions the scope - no Build Set button anywhere", async () => {
    const { suggSpy, unionSpy } = mockScope();
    render(<CompatibilityWorkbench />, { wrapper: wrapperWith(freshClient()) });
    await pickScope();

    await waitFor(() =>
      expect(suggSpy).toHaveBeenCalledWith("LQFP144", "STM32F4,STM32F7", undefined),
    );
    // the whole-scope union fires automatically with the COVERED families
    await waitFor(() =>
      expect(unionSpy).toHaveBeenCalledWith({
        families: ["STM32F4", "STM32F7"],
        package: "LQFP144",
      }),
    );
    expect(screen.queryByRole("button", { name: "Build Set" })).toBeNull();
    // the stepper lists every set
    const stepper = await screen.findByTestId("bench-stepper");
    expect(within(stepper).getByText("All Parts")).toBeInTheDocument();
    expect(within(stepper).getByText("Baseline")).toBeInTheDocument();
    expect(within(stepper).getByText("Divergent A")).toBeInTheDocument();
  });

  it("stepping to a divergent set auto-unions its refs (no rebuild)", async () => {
    const { unionSpy } = mockScope();
    render(<CompatibilityWorkbench />, { wrapper: wrapperWith(freshClient()) });
    await pickScope();
    await screen.findByTestId("bench-stepper");

    fireEvent.click(screen.getByText("Divergent A"));
    await waitFor(() => expect(unionSpy).toHaveBeenCalledWith({ parts: ["STM32F407ZGT6"] }));
  });

  it("renders the switch plan with the blocked position and its baseline identity", async () => {
    mockScope();
    render(<CompatibilityWorkbench />, { wrapper: wrapperWith(freshClient()) });
    await pickScope();

    const plan = await screen.findByTestId("switch-plan");
    expect(within(plan).getByText("23")).toBeInTheDocument();
    expect(within(plan).getByText("PA9")).toBeInTheDocument(); // the baseline identity
    expect(within(plan).getByText("Needs switching hardware")).toBeInTheDocument();
    expect(within(plan).getByText(/1 shared/)).toBeInTheDocument();
  });

  it("dropping a chip switches to a custom set and auto-rebuilds with the remaining refs", async () => {
    const { unionSpy } = mockScope();
    render(<CompatibilityWorkbench />, { wrapper: wrapperWith(freshClient()) });
    await pickScope();
    await screen.findByTestId("compat-set-strip");
    unionSpy.mockClear();

    fireEvent.click(screen.getByRole("button", { name: "Remove STM32F407ZGT6 from the set" }));
    await waitFor(() =>
      expect(unionSpy).toHaveBeenCalledWith({ parts: ["STM32F429ZET6", "STM32F746ZGT6"] }),
    );
    expect(await screen.findByText("Custom")).toBeInTheDocument();
  });

  it("a chip click opens that part's full pinout table modal", async () => {
    mockScope();
    vi.spyOn(api, "getStmPinout").mockResolvedValue({
      part: "STM32F746ZGT6",
      mpn_example: "STM32F746ZGT6",
      package: "LQFP144",
      geometry: {
        body_shape: "qfp",
        pin_count: 1,
        rows: null,
        cols: null,
        pitch_mm: null,
        has_center_pad: false,
      },
      pins: [
        {
          position: "1",
          position_kind: "numeric",
          lqfp_side: "left",
          bga_row: null,
          bga_col: null,
          canonical_pin_name: "VDD",
          raw_pin_name: "VDD",
          pin_type: "Power",
          electrical_class: "power",
          category: "power",
          roles: [],
          functions: [],
          alternate_functions: [],
          five_v: null,
          supply: "VDD",
        },
      ],
    });
    render(<CompatibilityWorkbench />, { wrapper: wrapperWith(freshClient()) });
    await pickScope();
    const strip = await screen.findByTestId("compat-set-strip");

    fireEvent.click(within(strip).getByRole("button", { name: "STM32F746ZGT6" }));
    const modal = await screen.findByTestId("bench-part-modal");
    expect(await within(modal).findByTestId("pinout-table")).toBeInTheDocument();
    expect(within(modal).getByText("VDD")).toBeInTheDocument();
  });

  it("exports the active set as the build-card JSON bundle", async () => {
    mockScope();
    const createUrl = vi.fn(() => "blob:x");
    const revokeUrl = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL: createUrl, revokeObjectURL: revokeUrl });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    render(<CompatibilityWorkbench />, { wrapper: wrapperWith(freshClient()) });
    await pickScope();
    await screen.findByTestId("bench-stepper");

    fireEvent.click(screen.getByRole("button", { name: "Export" }));
    expect(createUrl).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
    vi.unstubAllGlobals();
  });

  it("renders the reused Build the Index state when the scope 409s", async () => {
    vi.spyOn(api, "getStmFamilies").mockResolvedValue(FAMILIES);
    vi.spyOn(api, "getStmCompatSuggestions").mockRejectedValue(
      new ApiError(409, "STM index not built"),
    );
    vi.spyOn(api, "postStmCompatUnion").mockRejectedValue(
      new ApiError(409, "STM index not built"),
    );
    render(<CompatibilityWorkbench />, { wrapper: wrapperWith(freshClient()) });
    await pickScope();
    expect(await screen.findByRole("heading", { name: "Build the Index" })).toBeInTheDocument();
  });
});
