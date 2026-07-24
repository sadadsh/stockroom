import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type ReactNode } from "react";
import { AfCheckPanel, CompatibilityWorkbench, buildAssignments, unionBody } from "./CompatibilityWorkbench";
import { api, ApiError } from "../../api/client";
import type { FamiliesResponse, SuggestionsResponse, UnionDTO, UnionPositionDTO } from "../../api/types";

const FAMILIES: FamiliesResponse = {
  families: [
    { family: "STM32F4", lines: ["STM32F407"], mcu_count: 40, packages: ["LQFP100", "LQFP144"] },
  ],
};

function unionResult(): UnionDTO {
  return {
    parts: ["STM32F407VETx", "STM32F407VGTx"],
    resolved: [
      { ref: "A", mpn: "STM32F407VETx" },
      { ref: "B", mpn: "STM32F407VGTx" },
    ],
    package: "LQFP100",
    family: "STM32F4",
    families: ["STM32F4"],
    grain: "per-part",
    positions: [
      {
        position: "1",
        position_kind: "numeric",
        lqfp_side: "left",
        bga_row: null,
        bga_col: null,
        classification: "shared",
        present_on: 2,
        total: 2,
        per_part: [],
        reconcile: null,
      },
    ],
    verdict: { interchangeable: true, swaps_required: 0, blocking: [] },
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

describe("unionBody", () => {
  it("posts an explicit ref list when parts are loaded (takes precedence over a group)", () => {
    expect(unionBody({ families: ["STM32F4"], package: "LQFP100", parts: ["A", "B"] })).toEqual({
      parts: ["A", "B"],
    });
  });

  it("posts a (families, package) group when both are chosen and no explicit parts", () => {
    expect(unionBody({ families: ["STM32F4"], package: "LQFP100", parts: [] })).toEqual({
      families: ["STM32F4"],
      package: "LQFP100",
    });
  });

  it("posts a MULTI-family group (owner amendment: cross-family sets on one footprint)", () => {
    expect(unionBody({ families: ["STM32F4", "STM32F7"], package: "LQFP100", parts: [] })).toEqual(
      { families: ["STM32F4", "STM32F7"], package: "LQFP100" },
    );
  });

  it("is not buildable from a partial group (families but no package)", () => {
    expect(unionBody({ families: ["STM32F4"], package: null, parts: [] })).toBeNull();
    expect(unionBody({ families: [], package: null, parts: [] })).toBeNull();
  });
});

describe("CompatibilityWorkbench", () => {
  it("assembles a (family, package) group, posts it, and renders the union map on success", async () => {
    vi.spyOn(api, "getStmFamilies").mockResolvedValue(FAMILIES);
    const unionSpy = vi.spyOn(api, "postStmCompatUnion").mockResolvedValue(unionResult());

    render(<CompatibilityWorkbench />, { wrapper: wrapperWith(freshClient()) });

    // pick the one family, then its package
    fireEvent.click(await screen.findByText("STM32F4"));
    fireEvent.click(await screen.findByText("LQFP100"));

    // Build Set fires the union with the group body
    fireEvent.click(screen.getByRole("button", { name: "Build Set" }));
    await waitFor(() =>
      expect(unionSpy).toHaveBeenCalledWith({ families: ["STM32F4"], package: "LQFP100" }),
    );

    // the socket-union map renders from the result
    expect(await screen.findByTestId("compat-union-map-svg")).toBeInTheDocument();
  });

  it("Build Set stays disabled until the group is complete", async () => {
    vi.spyOn(api, "getStmFamilies").mockResolvedValue(FAMILIES);
    render(<CompatibilityWorkbench />, { wrapper: wrapperWith(freshClient()) });

    const build = () => screen.getByRole("button", { name: "Build Set" });
    expect(build()).toBeDisabled();
    // family alone is not enough; a package is still required
    fireEvent.click(await screen.findByText("STM32F4"));
    expect(build()).toBeDisabled();
    fireEvent.click(await screen.findByText("LQFP100"));
    expect(build()).toBeEnabled();
  });

  it("renders the reused Build the Index state (never a crash) when the union call 409s", async () => {
    vi.spyOn(api, "getStmFamilies").mockResolvedValue(FAMILIES);
    vi.spyOn(api, "postStmCompatUnion").mockRejectedValue(
      new ApiError(409, "STM index not built"),
    );

    render(<CompatibilityWorkbench />, { wrapper: wrapperWith(freshClient()) });
    fireEvent.click(await screen.findByText("STM32F4"));
    fireEvent.click(await screen.findByText("LQFP100"));
    fireEvent.click(screen.getByRole("button", { name: "Build Set" }));

    expect(
      await screen.findByRole("heading", { name: "Build the Index" }),
    ).toBeInTheDocument();
  });

  it("loads a suggested set into the assembly on pick, without auto-running the union (COMPAT-04)", async () => {
    vi.spyOn(api, "getStmFamilies").mockResolvedValue(FAMILIES);
    const suggestions: SuggestionsResponse = {
      groups: [
        {
          signature_id: "sig-a",
          tier: "baseline",
          package: "LQFP100",
          family: "STM32F4",
          refs: ["STM32F407VETx", "STM32F407VGTx"],
          divergent_positions: 0,
        },
      ],
    };
    vi.spyOn(api, "getStmCompatSuggestions").mockResolvedValue(suggestions);
    const unionSpy = vi.spyOn(api, "postStmCompatUnion").mockResolvedValue(unionResult());

    render(<CompatibilityWorkbench />, { wrapper: wrapperWith(freshClient()) });
    fireEvent.click(await screen.findByText("STM32F4"));
    fireEvent.click(await screen.findByText("LQFP100"));

    // pick the suggested set
    fireEvent.click(await screen.findByRole("button", { name: "Load This Set" }));

    // the assembly now reflects the loaded set, and the union was NOT auto-run (opt-in)
    expect(await screen.findByText(/Building from a loaded set of 2 parts/)).toBeInTheDocument();
    expect(unionSpy).not.toHaveBeenCalled();

    // the user still presses Build Set, which posts the explicit ref list
    fireEvent.click(screen.getByRole("button", { name: "Build Set" }));
    await waitFor(() =>
      expect(unionSpy).toHaveBeenCalledWith({ parts: ["STM32F407VETx", "STM32F407VGTx"] }),
    );
  });
});

function divergentPosition(): UnionPositionDTO {
  return {
    position: "23",
    position_kind: "numeric",
    lqfp_side: "left",
    bga_row: null,
    bga_col: null,
    classification: "divergent",
    present_on: 2,
    total: 2,
    per_part: [],
    reconcile: {
      swappable: true,
      swaps: [{ ref: "STM32F407VE", target_signal: "USART2_TX", via_af_index: 7 }],
      reason: null,
    },
  };
}

function unionWithSwaps(): UnionDTO {
  return { ...unionResult(), positions: [divergentPosition()] };
}

describe("buildAssignments", () => {
  it("derives a per-ref position->{signal, af_index} assignment from the reconcile swaps", () => {
    expect(buildAssignments(unionWithSwaps())).toEqual({
      STM32F407VE: { "23": { signal: "USART2_TX", af_index: 7 } },
    });
  });
});

describe("AfCheckPanel", () => {
  it("posts the held assignment and renders returned conflicts (kind + message)", async () => {
    const spy = vi.spyOn(api, "postStmAfCheck").mockResolvedValue({
      conflicts: [
        {
          kind: "peripheral-collision",
          positions: ["23", "41"],
          peripheral: "USART2",
          message: "USART2 is already routed to position 41 in this assignment.",
        },
      ],
    });
    render(<AfCheckPanel union={unionWithSwaps()} />, { wrapper: wrapperWith(freshClient()) });

    fireEvent.click(screen.getByRole("button", { name: "Check Conflicts" }));
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith({
        part: "STM32F407VE",
        assignment: { "23": { signal: "USART2_TX", af_index: 7 } },
      }),
    );
    expect(await screen.findByTestId("af-check-conflicts")).toBeInTheDocument();
    expect(screen.getByText("peripheral-collision")).toBeInTheDocument();
    expect(screen.getByText(/already routed to position 41/)).toBeInTheDocument();
  });

  it("renders a clean no-conflict state for an empty conflicts list", async () => {
    vi.spyOn(api, "postStmAfCheck").mockResolvedValue({ conflicts: [] });
    render(<AfCheckPanel union={unionWithSwaps()} />, { wrapper: wrapperWith(freshClient()) });
    fireEvent.click(screen.getByRole("button", { name: "Check Conflicts" }));
    expect(await screen.findByTestId("af-check-clean")).toBeInTheDocument();
    expect(screen.queryByTestId("af-check-conflicts")).toBeNull();
  });
});
