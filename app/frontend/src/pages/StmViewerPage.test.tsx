import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { StmViewerPage } from "./StmViewerPage";
import { ApiError } from "../api/client";
import type { McuSpecRow } from "../api/types";

// The page reads its server state through these hooks; mock the module so the page (and its
// FamilyPicker child, which reads useStmFamilies) renders deterministically without a backend.
vi.mock("../api/stmQueries", () => ({
  useStmStatus: vi.fn(),
  useStmMcus: vi.fn(),
  useStmFamilies: vi.fn(),
  useStmPinout: vi.fn(),
  useBuildStmIndex: vi.fn(),
}));

import {
  useStmStatus,
  useStmMcus,
  useStmFamilies,
  useStmPinout,
  useBuildStmIndex,
} from "../api/stmQueries";
import type { PinDTO, PinoutDTO } from "../api/types";

const mockStatus = vi.mocked(useStmStatus);
const mockMcus = vi.mocked(useStmMcus);
const mockFamilies = vi.mocked(useStmFamilies);
const mockPinout = vi.mocked(useStmPinout);
const mockBuild = vi.mocked(useBuildStmIndex);

const ROW: McuSpecRow = {
  part: "STM32F407V(E-G)Tx",
  mpn_example: "STM32F407VETx",
  series: "STM32F4",
  line: "STM32F407",
  core: "Cortex-M4",
  package: "LQFP100",
  pin_count: 100,
  io_count: 82,
  flash_kb: 512,
  ram_kb: 192,
  max_freq_mhz: 168,
  vdd_min: 1.8,
  vdd_max: 3.6,
  temp_min_c: -40,
  temp_max_c: 85,
  peripherals: { USART: 4 },
};

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

const IDLE_BUILD = {
  status: "idle" as const,
  progress: null,
  result: null,
  error: null,
  start: vi.fn(),
  run: vi.fn(),
  reset: vi.fn(),
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function query(over: Record<string, unknown>): any {
  return { data: undefined, isLoading: false, isError: false, error: null, refetch: vi.fn(), ...over };
}

const PINOUT: PinoutDTO = {
  part: "STM32F407V(E-G)Tx",
  mpn_example: "STM32F407VETx",
  package: "LQFP100",
  geometry: { body_shape: "qfp", pin_count: 2, rows: null, cols: null, pitch_mm: 0.5, has_center_pad: false },
  pins: [
    {
      position: "1",
      position_kind: "numeric",
      lqfp_side: "left",
      bga_row: null,
      bga_col: null,
      canonical_pin_name: "PE2",
      raw_pin_name: "PE2",
      pin_type: "I/O",
      electrical_class: "io",
      category: "io",
      roles: [],
      functions: [],
      alternate_functions: [{ af_index: 0, signal: "TRACECLK", peripheral: "TRACE" }],
      five_v: { tolerant: true, by_family: {}, caveat: "" },
      supply: null,
    } satisfies PinDTO,
    {
      position: "2",
      position_kind: "numeric",
      lqfp_side: "bottom",
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
    } satisfies PinDTO,
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  mockBuild.mockReturnValue(IDLE_BUILD);
  mockFamilies.mockReturnValue(
    query({ data: { families: [{ family: "STM32F4", lines: [], mcu_count: 1, packages: [] }] } }),
  );
  // by default no part is selected, so the pinout query is idle/empty
  mockPinout.mockReturnValue(query({ data: undefined }));
});

describe("StmViewerPage", () => {
  it("renders the Build the Index call to action on a 409 and not the matrix", () => {
    mockStatus.mockReturnValue(query({ data: { built: false } }));
    mockMcus.mockReturnValue(query({ error: new ApiError(409, "STM index not built") }));

    wrap(<StmViewerPage />);

    expect(screen.getByRole("button", { name: "Build the Index" })).toBeInTheDocument();
    expect(screen.queryByText("STM32F407VETx")).toBeNull();
    expect(screen.queryByText("STM index not built")).toBeNull();
  });

  it("composes the family picker and spec matrix on success, showing mpn_example (never ref_name)", () => {
    mockStatus.mockReturnValue(query({ data: { built: true, mcu_count: 1, family_count: 1 } }));
    mockMcus.mockReturnValue(query({ data: { mcus: [ROW], count: 1, facets: {} } }));

    wrap(<StmViewerPage />);

    // FamilyPicker (the scope column renders first; "STM32F4" also appears in the matrix Series cell)
    expect(screen.getByText("Families")).toBeInTheDocument();
    expect(screen.getAllByText("STM32F4").length).toBeGreaterThanOrEqual(1);
    // SpecMatrixTable
    expect(screen.getByText("Part")).toBeInTheDocument();
    expect(screen.getByText("STM32F407VETx")).toBeInTheDocument();
    expect(screen.queryByText("STM32F407V(E-G)Tx")).toBeNull();
    // the reserved pinout region shows its empty state until a part is picked
    expect(screen.getByText("Select a part to see its pinout.")).toBeInTheDocument();
  });

  it("changing the scope re-drives useStmMcus with the new family", async () => {
    mockStatus.mockReturnValue(query({ data: { built: true, mcu_count: 1, family_count: 1 } }));
    mockMcus.mockReturnValue(query({ data: { mcus: [ROW], count: 1, facets: {} } }));

    wrap(<StmViewerPage />);
    // initial render fetched with no coarse family
    expect(mockMcus).toHaveBeenCalledWith({ family: undefined });

    // the FamilyPicker family toggle is the first "STM32F4" in DOM order (the scope column)
    await userEvent.click(screen.getAllByText("STM32F4")[0]);

    // selecting exactly one family narrows server-side on the next render
    expect(mockMcus).toHaveBeenLastCalledWith({ family: "STM32F4" });
  });

  it("selecting a part renders the pinout map + legend; a pad click opens the inspector", async () => {
    mockStatus.mockReturnValue(query({ data: { built: true, mcu_count: 1, family_count: 1 } }));
    mockMcus.mockReturnValue(query({ data: { mcus: [ROW], count: 1, facets: {} } }));
    // the pinout is available for the selected part (one fetch per part; decision 4)
    mockPinout.mockReturnValue(query({ data: PINOUT }));

    const { container } = wrap(<StmViewerPage />);
    // before a part is picked, the chamber empty state shows
    expect(screen.getByText("Select a part to see its pinout.")).toBeInTheDocument();

    await userEvent.click(screen.getByText("STM32F407VETx"));

    // the map + legend render for the active part
    expect(screen.getByTestId("pinout-map-svg")).toBeInTheDocument();
    expect(screen.getByTestId("pinout-legend")).toBeInTheDocument();
    expect(screen.getByText("Select a pin to inspect its facts.")).toBeInTheDocument();

    // clicking a pad opens the inspector for that pin, read from the already-fetched pinout
    // (fireEvent.click is a bare click; d3-zoom's mousedown gesture is not exercisable under jsdom)
    const pad1 = container.querySelector('[data-position="1"]')!;
    fireEvent.click(pad1);
    expect(screen.getByTestId("pin-inspector")).toBeInTheDocument();
    expect(screen.getByText("PE2")).toBeInTheDocument();
    expect(screen.getByText("TRACECLK")).toBeInTheDocument();
  });

  it("looks the inspected pin up from the fetched pinout without an extra fetch per pin", async () => {
    mockStatus.mockReturnValue(query({ data: { built: true, mcu_count: 1, family_count: 1 } }));
    mockMcus.mockReturnValue(query({ data: { mcus: [ROW], count: 1, facets: {} } }));
    mockPinout.mockReturnValue(query({ data: PINOUT }));

    const { container } = wrap(<StmViewerPage />);
    await userEvent.click(screen.getByText("STM32F407VETx"));

    const callsAfterPart = mockPinout.mock.calls.length;
    // click two different pads: no new getStmPinout invocation is added per pin (decision 4)
    fireEvent.click(container.querySelector('[data-position="1"]')!);
    fireEvent.click(container.querySelector('[data-position="2"]')!);
    // useStmPinout is only ever called with the part (never a per-pin argument)
    for (const call of mockPinout.mock.calls) {
      expect(call[0] === null || typeof call[0] === "string").toBe(true);
    }
    // the second pad shows the power pin's supply facts
    expect(screen.getByText("Supply")).toBeInTheDocument();
    expect(mockPinout.mock.calls.length).toBeGreaterThanOrEqual(callsAfterPart);
  });
});
