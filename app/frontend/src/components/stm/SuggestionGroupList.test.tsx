import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type ReactNode } from "react";
import { SuggestionGroupList } from "./SuggestionGroupList";
import { api } from "../../api/client";
import type { SuggestionsResponse } from "../../api/types";

const GROUPS: SuggestionsResponse = {
  groups: [
    {
      signature_id: "sig-a",
      tier: "baseline",
      package: "LQFP100",
      family: "STM32F4",
      refs: ["STM32F407VETx", "STM32F407VGTx"],
      divergent_positions: 0,
    },
    {
      signature_id: "sig-b",
      tier: "divergent",
      package: "LQFP100",
      family: "STM32F4",
      refs: ["STM32F415VGTx", "STM32F417VGTx"],
      divergent_positions: 4,
    },
  ],
};

function wrapperWith(qc: QueryClient) {
  return ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children);
}

function freshClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

afterEach(() => vi.restoreAllMocks());

describe("SuggestionGroupList", () => {
  it("renders each discovered group with its tier and divergence count", async () => {
    vi.spyOn(api, "getStmCompatSuggestions").mockResolvedValue(GROUPS);
    render(
      <SuggestionGroupList package="LQFP100" family="STM32F4" onLoadSet={vi.fn()} />,
      { wrapper: wrapperWith(freshClient()) },
    );
    expect(await screen.findByText("Baseline")).toBeInTheDocument();
    expect(screen.getByText("Divergent")).toBeInTheDocument();
    expect(screen.getAllByTestId("suggestion-group")).toHaveLength(2);
    expect(screen.getByText(/4 divergent/)).toBeInTheDocument();
  });

  it("picking a group loads its refs (an explicit action) and never auto-runs anything", async () => {
    vi.spyOn(api, "getStmCompatSuggestions").mockResolvedValue(GROUPS);
    const onLoadSet = vi.fn();
    render(
      <SuggestionGroupList package="LQFP100" family="STM32F4" onLoadSet={onLoadSet} />,
      { wrapper: wrapperWith(freshClient()) },
    );
    const loadButtons = await screen.findAllByRole("button", { name: "Load This Set" });
    fireEvent.click(loadButtons[0]);
    expect(onLoadSet).toHaveBeenCalledWith(["STM32F407VETx", "STM32F407VGTx"]);
  });

  it("stays gated until a package and family are chosen (no wasted query)", async () => {
    const spy = vi.spyOn(api, "getStmCompatSuggestions").mockResolvedValue(GROUPS);
    render(<SuggestionGroupList package={null} family={null} onLoadSet={vi.fn()} />, {
      wrapper: wrapperWith(freshClient()),
    });
    expect(
      screen.getByText(/Select one family and a package to discover compatible sets/),
    ).toBeInTheDocument();
    // give the effect a tick; the gated query must not fire
    await waitFor(() => expect(spy).not.toHaveBeenCalled());
  });
});
