import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
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
  useBuildStmIndex,
} from "../api/stmQueries";

const mockStatus = vi.mocked(useStmStatus);
const mockMcus = vi.mocked(useStmMcus);
const mockFamilies = vi.mocked(useStmFamilies);
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

beforeEach(() => {
  vi.clearAllMocks();
  mockBuild.mockReturnValue(IDLE_BUILD);
  mockFamilies.mockReturnValue(
    query({ data: { families: [{ family: "STM32F4", lines: [], mcu_count: 1, packages: [] }] } }),
  );
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

  it("clicking a matrix row sets activePart, updating the reserved pinout region", async () => {
    mockStatus.mockReturnValue(query({ data: { built: true, mcu_count: 1, family_count: 1 } }));
    mockMcus.mockReturnValue(query({ data: { mcus: [ROW], count: 1, facets: {} } }));

    wrap(<StmViewerPage />);
    expect(screen.getByText("Select a part to see its pinout.")).toBeInTheDocument();

    await userEvent.click(screen.getByText("STM32F407VETx"));

    expect(screen.getByText("The pinout map lands here.")).toBeInTheDocument();
    expect(screen.queryByText("Select a part to see its pinout.")).toBeNull();
  });
});
