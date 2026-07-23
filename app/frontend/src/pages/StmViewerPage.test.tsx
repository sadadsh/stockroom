import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { StmViewerPage } from "./StmViewerPage";
import { ApiError } from "../api/client";
import type { McuSpecRow } from "../api/types";

// The page reads its server state through these hooks; mock the module so the page renders
// deterministically without a live backend (the LibraryPage.test module-mock pattern).
vi.mock("../api/stmQueries", () => ({
  useStmStatus: vi.fn(),
  useStmMcus: vi.fn(),
  useStmFamilies: vi.fn(),
  useStmPinout: vi.fn(),
  useBuildStmIndex: vi.fn(),
}));

import { useStmStatus, useStmMcus, useBuildStmIndex } from "../api/stmQueries";

const mockStatus = vi.mocked(useStmStatus);
const mockMcus = vi.mocked(useStmMcus);
const mockBuild = vi.mocked(useBuildStmIndex);

const ROW: McuSpecRow = {
  part: "STM32F407V(E-G)Tx", // the ref_name wildcard: must NEVER appear as visible text
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
  peripherals: { USART: 4, SPI: 3 },
};

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>{node}</QueryClientProvider>,
  );
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

beforeEach(() => {
  vi.clearAllMocks();
  mockBuild.mockReturnValue(IDLE_BUILD);
});

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function query(over: Record<string, unknown>): any {
  return { data: undefined, isLoading: false, error: null, refetch: vi.fn(), ...over };
}

describe("StmViewerPage", () => {
  it("renders the Build the Index call to action on a 409 and not the matrix", () => {
    mockStatus.mockReturnValue(query({ data: { built: false } }));
    mockMcus.mockReturnValue(query({ error: new ApiError(409, "STM index not built") }));

    wrap(<StmViewerPage />);

    expect(screen.getByRole("button", { name: "Build the Index" })).toBeInTheDocument();
    // the honest gate, not a raw error body or an infinite spinner
    expect(screen.queryByTestId("stm-mcu-list")).toBeNull();
    expect(screen.queryByText("STM index not built")).toBeNull();
  });

  it("renders one row per MCU by mpn_example, and never the raw ref_name, on success", () => {
    mockStatus.mockReturnValue(query({ data: { built: true, mcu_count: 1, family_count: 1 } }));
    mockMcus.mockReturnValue(
      query({ data: { mcus: [ROW], count: 1, facets: {} } }),
    );

    wrap(<StmViewerPage />);

    expect(screen.getByText("STM32F407VETx")).toBeInTheDocument();
    // the ref_name wildcard is used only as the ?part= value, never shown (Pitfall 1)
    expect(screen.queryByText("STM32F407V(E-G)Tx")).toBeNull();
    // and the build gate is absent on the success path
    expect(screen.queryByRole("button", { name: "Build the Index" })).toBeNull();
  });
});
