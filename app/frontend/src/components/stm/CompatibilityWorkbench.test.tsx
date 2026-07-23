import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type ReactNode } from "react";
import { CompatibilityWorkbench, unionBody } from "./CompatibilityWorkbench";
import { api, ApiError } from "../../api/client";
import type { FamiliesResponse, UnionDTO } from "../../api/types";

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
    expect(unionBody({ family: "STM32F4", package: "LQFP100", parts: ["A", "B"] })).toEqual({
      parts: ["A", "B"],
    });
  });

  it("posts a (family, package) group when both are chosen and no explicit parts", () => {
    expect(unionBody({ family: "STM32F4", package: "LQFP100", parts: [] })).toEqual({
      family: "STM32F4",
      package: "LQFP100",
    });
  });

  it("is not buildable from a partial group (a family but no package)", () => {
    expect(unionBody({ family: "STM32F4", package: null, parts: [] })).toBeNull();
    expect(unionBody({ family: null, package: null, parts: [] })).toBeNull();
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
      expect(unionSpy).toHaveBeenCalledWith({ family: "STM32F4", package: "LQFP100" }),
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
});
