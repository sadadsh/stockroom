import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type ReactNode } from "react";
import { AfOptionsPanel } from "./AfOptionsPanel";
import { PinInspector } from "./PinInspector";
import { api } from "../../api/client";
import type { PinAfResponse, PinDTO, SignalCandidatesResponse } from "../../api/types";

// One pin at `position`, enough for PinInspector to mount the AF panel for it.
function pinAt(position: string): PinDTO {
  return {
    position,
    position_kind: "numeric",
    lqfp_side: "left",
    bga_row: null,
    bga_col: null,
    canonical_pin_name: `PA${position}`,
    raw_pin_name: `PA${position}`,
    pin_type: "I/O",
    electrical_class: "io",
    category: "io",
    roles: [],
    functions: [],
    alternate_functions: [],
    five_v: null,
    supply: null,
  };
}

const PIN_AF: PinAfResponse = {
  position: "23",
  alternate_functions: [
    { af_index: 7, signal: "USART2_TX", peripheral: "USART2" },
    { af_index: 1, signal: "TIM2_CH1", peripheral: "TIM2" },
  ],
};

// Deliberately out of order (A10 before A2) so a lexicographic sort would fail the numeric test.
const CANDIDATES: SignalCandidatesResponse = {
  signal: "USART2_TX",
  candidates: [
    { position: "A10", canonical_pin_name: "PD5", af_index: 7 },
    { position: "A2", canonical_pin_name: "PA2", af_index: 7 },
    { position: "A1", canonical_pin_name: "PA0", af_index: 7 },
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

describe("AfOptionsPanel", () => {
  it("lists a selected pin's complete AF set ordered by AF index (SWAP-01)", async () => {
    vi.spyOn(api, "getStmPinAf").mockResolvedValue(PIN_AF);
    render(<AfOptionsPanel part="STM32F407VETx" position="23" />, {
      wrapper: wrapperWith(freshClient()),
    });
    expect(await screen.findByText(/USART2_TX/)).toBeInTheDocument();
    expect(screen.getByText(/TIM2_CH1/)).toBeInTheDocument();
    // ordered by af_index: AF1 renders before AF7
    const rows = screen.getAllByText(/^AF\d+$/).map((el) => el.textContent);
    expect(rows).toEqual(["AF1", "AF7"]);
  });

  it("shows every candidate pin for a chosen signal, collated numeric-aware (A1, A2, A10) (SWAP-02)", async () => {
    vi.spyOn(api, "getStmPinAf").mockResolvedValue(PIN_AF);
    const candSpy = vi.spyOn(api, "getStmSignalCandidates").mockResolvedValue(CANDIDATES);
    render(<AfOptionsPanel part="STM32F407VETx" position="23" />, {
      wrapper: wrapperWith(freshClient()),
    });

    // choose the signal by clicking its AF row (a first-class control, not a hidden modifier)
    fireEvent.click(await screen.findByText(/USART2_TX/));
    await waitFor(() =>
      expect(candSpy).toHaveBeenCalledWith("STM32F407VETx", "USART2_TX"),
    );

    const list = await screen.findByTestId("af-signal-candidates");
    const positions = within(list)
      .getAllByText(/^A\d+$/)
      .map((el) => el.textContent);
    expect(positions).toEqual(["A1", "A2", "A10"]);
  });

  it("does not fetch candidates until a signal is chosen (both queries enabled-gated)", async () => {
    vi.spyOn(api, "getStmPinAf").mockResolvedValue(PIN_AF);
    const candSpy = vi.spyOn(api, "getStmSignalCandidates").mockResolvedValue(CANDIDATES);
    render(<AfOptionsPanel part="STM32F407VETx" position="23" />, {
      wrapper: wrapperWith(freshClient()),
    });
    await screen.findByText(/USART2_TX/);
    expect(candSpy).not.toHaveBeenCalled();
    expect(
      screen.getByText(/Select a signal above to see each candidate pin/),
    ).toBeInTheDocument();
  });

  // The chosen signal belongs to ONE pin: the previous pin's signal may not exist on the new one.
  // The panel no longer clears it in an effect (which showed the stale candidate list for a render
  // first); PinInspector keys the panel on the pin, so a new pin arrives already clear.
  it("a new pin clears the chosen signal, with no render still showing the old candidates", async () => {
    vi.spyOn(api, "getStmPinAf").mockResolvedValue(PIN_AF);
    vi.spyOn(api, "getStmSignalCandidates").mockResolvedValue(CANDIDATES);
    const { rerender } = render(<PinInspector pin={pinAt("23")} part="STM32F407VETx" />, {
      wrapper: wrapperWith(freshClient()),
    });
    fireEvent.click(await screen.findByText(/USART2_TX/));
    expect(await screen.findByTestId("af-signal-candidates")).toBeInTheDocument();

    rerender(<PinInspector pin={pinAt("24")} part="STM32F407VETx" />);

    expect(screen.queryByTestId("af-signal-candidates")).toBeNull();
    expect(
      screen.getByText(/Select a signal above to see each candidate pin/),
    ).toBeInTheDocument();
  });
});
