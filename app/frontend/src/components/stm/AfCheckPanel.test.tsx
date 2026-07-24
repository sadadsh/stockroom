import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type ReactNode } from "react";
import { AfCheckPanel, buildAssignments } from "./AfCheckPanel";
import { api } from "../../api/client";
import type { UnionDTO, UnionPositionDTO } from "../../api/types";

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
    positions: [divergentPosition()],
    verdict: { interchangeable: true, swaps_required: 1, blocking: [] },
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
